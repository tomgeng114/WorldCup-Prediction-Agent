from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta

from app.models import Match


def actual_result(match: Match) -> str:
    if match.home_score is None or match.away_score is None:
        return "Pending"
    if match.home_score > match.away_score:
        return "Home Win"
    if match.home_score < match.away_score:
        return "Away Win"
    return "Draw"


def actual_market_result(match: Match) -> str:
    if match.home_score is None or match.away_score is None or not match.odds:
        return "Pending"
    market_type = "HAD"
    if match.prediction and match.prediction.market_type:
        market_type = match.prediction.market_type
    elif match.odds.source_pool:
        market_type = match.odds.source_pool
    if market_type.upper() != "HHAD":
        return actual_result(match)

    try:
        handicap = float(match.odds.handicap or match.odds.asian_line or 0)
    except (TypeError, ValueError):
        handicap = 0.0
    adjusted_home_score = match.home_score + handicap
    if adjusted_home_score > match.away_score:
        return "Home Win"
    if adjusted_home_score < match.away_score:
        return "Away Win"
    return "Draw"


def picked_odds(match: Match, pick: str | None = None) -> float:
    if not match.prediction or not match.odds:
        return 0.0
    selected_pick = pick or match.prediction.predicted_result
    return {
        "Home Win": match.odds.home_win_odds,
        "Draw": match.odds.draw_odds,
        "Away Win": match.odds.away_win_odds,
    }.get(selected_pick, 0.0)


def predicted_score_candidates(match: Match) -> list[str]:
    if not match.prediction:
        return []

    candidates: list[str] = []
    try:
        top_scores = json.loads(match.prediction.top_scores or "[]")
    except (AttributeError, json.JSONDecodeError, TypeError):
        top_scores = []
    if isinstance(top_scores, list):
        for item in top_scores:
            score = item.get("score") if isinstance(item, dict) else item
            if score and str(score) not in candidates:
                candidates.append(str(score))

    try:
        backup_scores = match.prediction.backup_scores or ""
    except AttributeError:
        backup_scores = ""
    for score in (part.strip() for part in backup_scores.split("|")):
        if score and score not in candidates:
            candidates.append(score)

    if match.prediction.predicted_score and match.prediction.predicted_score not in candidates:
        candidates.insert(0, match.prediction.predicted_score)
    return candidates[:3]


def score_hit(match: Match) -> bool:
    if match.home_score is None or match.away_score is None:
        return False
    actual_score = f"{match.home_score}-{match.away_score}"
    return actual_score in predicted_score_candidates(match)


def sporttery_hot_pick(match: Match) -> str | None:
    if not match.odds:
        return None
    odds = {
        "Home Win": match.odds.home_win_odds,
        "Draw": match.odds.draw_odds,
        "Away Win": match.odds.away_win_odds,
    }
    valid_odds = {pick: value for pick, value in odds.items() if value and value > 0}
    if len(valid_odds) != 3:
        return None
    lowest = min(valid_odds.values())
    hottest = [pick for pick, value in valid_odds.items() if value == lowest]
    if len(hottest) != 1:
        return None
    return hottest[0]


def ai_hot_alignment_summary(matches: list[Match]) -> dict:
    rows = [match for match in matches if match.prediction and match.odds]
    same = 0
    opposite = 0
    skipped = 0
    for match in rows:
        hot_pick = sporttery_hot_pick(match)
        if not hot_pick:
            skipped += 1
            continue
        if match.prediction.predicted_market_result == hot_pick:
            same += 1
        else:
            opposite += 1
    total = same + opposite
    return {
        "same": same,
        "opposite": opposite,
        "sample_size": total,
        "skipped": skipped,
        "same_rate": round(same / total * 100, 1) if total else 0.0,
        "opposite_rate": round(opposite / total * 100, 1) if total else 0.0,
    }


def settled_matches(matches: list[Match]) -> list[Match]:
    return [
        match
        for match in matches
        if match.prediction
        and match.odds
        and match.status == "finished"
        and match.home_score is not None
        and match.away_score is not None
    ]


def settle_match(match: Match, persist: bool = False) -> dict:
    result_hit = match.prediction.predicted_result == actual_result(match)
    market_hit = match.prediction.predicted_market_result == actual_market_result(match)
    score_hit_value = score_hit(match)
    stake = 1.0
    profit = picked_odds(match, match.prediction.predicted_result) - stake if result_hit else -stake
    market_profit = picked_odds(match, match.prediction.predicted_market_result) - stake if market_hit else -stake
    if persist:
        match.prediction.is_red_pick = result_hit
    return {
        "match_id": match.id,
        "result_hit": result_hit,
        "market_hit": market_hit,
        "score_hit": score_hit_value,
        "actual_result": actual_result(match),
        "actual_market_result": actual_market_result(match),
        "predicted_result": match.prediction.predicted_result,
        "predicted_market_result": match.prediction.predicted_market_result,
        "market_type": match.prediction.market_type,
        "handicap": match.prediction.handicap,
        "stake": stake,
        "profit": round(profit, 4),
        "roi": round((profit / stake) * 100, 2),
        "market_profit": round(market_profit, 4),
        "market_roi": round((market_profit / stake) * 100, 2),
    }


def hit_summary(matches: list[Match], days: int | None = None) -> dict:
    rows = settled_matches(matches)
    if days is not None:
        start = datetime.now() - timedelta(days=days)
        rows = [match for match in rows if match.kickoff_time >= start]
    red = sum(1 for match in rows if match.prediction.predicted_result == actual_result(match))
    black = len(rows) - red
    return {
        "red": red,
        "black": black,
        "hit_rate": round(red / len(rows) * 100, 1) if rows else 0.0,
    }


def roi_summary(matches: list[Match]) -> dict:
    rows = settled_matches(matches)
    stake = float(len(rows))
    profit = sum(settle_match(match)["profit"] for match in rows)
    return {
        "stake": round(stake, 4),
        "profit": round(profit, 4),
        "roi": round((profit / stake) * 100, 2) if stake else 0.0,
    }


def performance_curves(matches: list[Match]) -> dict[str, list[dict]]:
    by_date: dict[str, list[Match]] = defaultdict(list)
    for match in settled_matches(matches):
        by_date[match.kickoff_time.date().isoformat()].append(match)

    profit_curve = []
    accuracy_curve = []
    running_profit = 0.0
    running_red = 0
    running_total = 0

    for date in sorted(by_date):
        day_rows = by_date[date]
        for match in day_rows:
            settlement = settle_match(match)
            running_profit += settlement["profit"]
            running_red += 1 if settlement["result_hit"] else 0
            running_total += 1
        profit_curve.append({"date": date, "value": round(running_profit, 2)})
        accuracy_curve.append({"date": date, "value": round(running_red / running_total * 100, 1)})

    return {"profit_curve": profit_curve, "accuracy_curve": accuracy_curve}
