from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BacktestPrediction, BacktestRun, WorldCupMatch, WorldCupOdds


RESULTS = ("Home Win", "Draw", "Away Win")
RESULT_LABELS = {
    "Home Win": "主胜",
    "Draw": "平局",
    "Away Win": "客胜",
}
EDGE_BUCKETS = (
    ("5%-10%", 0.05, 0.10),
    ("10%-15%", 0.10, 0.15),
    ("15%-20%", 0.15, 0.20),
    ("20%-25%", 0.20, 0.25),
    ("25%+", 0.25, None),
)
EXPANSION_COMPETITIONS = ("欧洲杯", "美洲杯", "世预赛", "欧国联")


@dataclass
class OddsImportSummary:
    imported: int
    updated: int
    skipped: int


def _parse_float(value: object) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _find_match(db: Session, row: dict) -> WorldCupMatch | None:
    match_id = row.get("match_id")
    if match_id:
        try:
            match = db.get(WorldCupMatch, int(match_id))
        except ValueError:
            match = None
        if match:
            return match

    year = row.get("tournament_year")
    home_team = row.get("home_team")
    away_team = row.get("away_team")
    if not year or not home_team or not away_team:
        return None
    query = select(WorldCupMatch).where(
        WorldCupMatch.tournament_year == int(year),
        WorldCupMatch.home_team == home_team,
        WorldCupMatch.away_team == away_team,
    )
    return db.scalar(query)


def import_world_cup_odds_csv(db: Session, csv_path: str | Path) -> OddsImportSummary:
    path = Path(csv_path)
    imported = 0
    updated = 0
    skipped = 0
    with path.open(newline="", encoding="utf-8-sig") as file:
        for row in csv.DictReader(file):
            match = _find_match(db, row)
            home_odds = _parse_float(row.get("home_win_odds"))
            draw_odds = _parse_float(row.get("draw_odds"))
            away_odds = _parse_float(row.get("away_win_odds"))
            if not match or not home_odds or not draw_odds or not away_odds:
                skipped += 1
                continue
            existing = db.scalar(select(WorldCupOdds).where(WorldCupOdds.match_id == match.id))
            payload = existing or WorldCupOdds(match_id=match.id)
            payload.source = row.get("source") or "manual_verified"
            payload.captured_at = _parse_datetime(row.get("captured_at"))
            payload.home_win_odds = home_odds
            payload.draw_odds = draw_odds
            payload.away_win_odds = away_odds
            payload.handicap = _parse_float(row.get("handicap"))
            payload.handicap_home_odds = _parse_float(row.get("handicap_home_odds"))
            payload.handicap_draw_odds = _parse_float(row.get("handicap_draw_odds"))
            payload.handicap_away_odds = _parse_float(row.get("handicap_away_odds"))
            db.add(payload)
            if existing:
                updated += 1
            else:
                imported += 1
    db.commit()
    return OddsImportSummary(imported=imported, updated=updated, skipped=skipped)


def _latest_run(db: Session, years: list[int] | None = None) -> BacktestRun | None:
    query = select(BacktestRun).order_by(BacktestRun.created_at.desc())
    if years:
        year_text = ",".join(str(year) for year in years)
        query = query.where(BacktestRun.years == year_text)
    return db.scalar(query)


def _rows_with_odds(db: Session, run_id: int | None = None) -> list[tuple[BacktestPrediction, WorldCupMatch, WorldCupOdds]]:
    run = db.get(BacktestRun, run_id) if run_id else _latest_run(db)
    if not run:
        return []
    query = (
        select(BacktestPrediction, WorldCupMatch, WorldCupOdds)
        .join(WorldCupMatch, BacktestPrediction.match_id == WorldCupMatch.id)
        .join(WorldCupOdds, WorldCupOdds.match_id == WorldCupMatch.id)
        .where(BacktestPrediction.run_id == run.id)
        .order_by(WorldCupMatch.match_date.asc(), WorldCupMatch.id.asc())
    )
    return list(db.execute(query).all())


def _actual_result(match: WorldCupMatch) -> str:
    if match.home_score > match.away_score:
        return "Home Win"
    if match.home_score < match.away_score:
        return "Away Win"
    return "Draw"


def _hot_pick(odds: WorldCupOdds) -> str:
    prices = {
        "Home Win": odds.home_win_odds,
        "Draw": odds.draw_odds,
        "Away Win": odds.away_win_odds,
    }
    return min(prices, key=prices.get)


def _odds_for_pick(odds: WorldCupOdds, pick: str) -> float:
    return {
        "Home Win": odds.home_win_odds,
        "Draw": odds.draw_odds,
        "Away Win": odds.away_win_odds,
    }[pick]


def _market_probabilities(odds: WorldCupOdds) -> dict[str, float]:
    implied = {
        "Home Win": 1 / odds.home_win_odds,
        "Draw": 1 / odds.draw_odds,
        "Away Win": 1 / odds.away_win_odds,
    }
    total = sum(implied.values())
    return {key: value / total for key, value in implied.items()}


def _prediction_probability(row: BacktestPrediction, pick: str) -> float:
    return {
        "Home Win": row.home_win_probability,
        "Draw": row.draw_probability,
        "Away Win": row.away_win_probability,
    }[pick]


def _ratio(hit: int, total: int) -> float:
    return round(hit / total * 100, 2) if total else 0.0


def benchmark_market_vs_ai(db: Session, run_id: int | None = None) -> dict:
    rows = _rows_with_odds(db, run_id)
    hot_hits = 0
    ai_hits = 0
    for prediction, match, odds in rows:
        actual = _actual_result(match)
        hot_hits += _hot_pick(odds) == actual
        ai_hits += prediction.predicted_result == actual
    sample_size = len(rows)
    hot_rate = _ratio(hot_hits, sample_size)
    ai_rate = _ratio(ai_hits, sample_size)
    return {
        "odds_sample_size": sample_size,
        "sporttery_hot_hit_rate": hot_rate if sample_size else None,
        "ai_hit_rate": ai_rate if sample_size else None,
        "ai_edge": round(ai_rate - hot_rate, 2) if sample_size else None,
        "status": "需要导入真实赛前体彩赔率" if not sample_size else "ok",
    }


def _max_drawdown(equity_curve: list[dict]) -> float:
    peak = 0.0
    max_drawdown = 0.0
    for point in equity_curve:
        value = point["value"]
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value - peak)
    return round(max_drawdown, 4)


def _bet_profit(pick: str, actual: str, price: float, stake: float) -> float:
    return stake * (price - 1) if pick == actual else -stake


def _stake_for_bet(staking: str, probability: float, price: float, unit: float, kelly_fraction: float) -> float:
    if staking != "kelly":
        return unit
    expected_value = probability * price - 1
    raw_fraction = max(0.0, expected_value / max(price - 1, 1e-9))
    return unit * min(raw_fraction * kelly_fraction, 1.0)


def _roi_from_bets(bets: list[dict], staking: str = "unit", unit: float = 1.0, kelly_fraction: float = 0.25) -> dict:
    stake_total = 0.0
    profit_total = 0.0
    hits = 0
    curve = []
    for bet in bets:
        probability = bet.get("model_probability_decimal", bet["model_probability"])
        if probability > 1:
            probability = probability / 100
        stake = _stake_for_bet(staking, probability, bet["odds"], unit, kelly_fraction)
        profit = _bet_profit(bet["pick"], bet["actual"], bet["odds"], stake)
        hit = bet["pick"] == bet["actual"]
        hits += hit
        stake_total += stake
        profit_total += profit
        curve.append(
            {
                "date": bet["date"],
                "match_id": bet["match_id"],
                "pick": bet["pick"],
                "stake": round(stake, 4),
                "profit": round(profit, 4),
                "value": round(profit_total, 4),
            }
        )
    return {
        "bets": len(bets),
        "hits": hits,
        "hit_rate": _ratio(hits, len(bets)),
        "stake": round(stake_total, 4),
        "profit": round(profit_total, 4),
        "roi": round(profit_total / stake_total * 100, 2) if stake_total else None,
        "max_drawdown": _max_drawdown(curve),
        "equity_curve": curve,
    }


def _best_value_candidates(rows: list[tuple[BacktestPrediction, WorldCupMatch, WorldCupOdds]], unit: float = 1.0) -> list[dict]:
    candidates: list[dict] = []
    for prediction, match, odds in rows:
        actual = _actual_result(match)
        market_probabilities = _market_probabilities(odds)
        model_probabilities = {
            "Home Win": prediction.home_win_probability,
            "Draw": prediction.draw_probability,
            "Away Win": prediction.away_win_probability,
        }
        pick = max(RESULTS, key=lambda result: model_probabilities[result] - market_probabilities[result])
        edge_decimal = model_probabilities[pick] - market_probabilities[pick]
        price = _odds_for_pick(odds, pick)
        candidates.append(
            {
                "match_id": match.id,
                "date": match.match_date.date().isoformat(),
                "match_date": match.match_date.isoformat(sep=" "),
                "home_team": match.home_team,
                "away_team": match.away_team,
                "pick": pick,
                "pick_label": RESULT_LABELS[pick],
                "actual": actual,
                "actual_label": RESULT_LABELS[actual],
                "odds": price,
                "market_probability": round(market_probabilities[pick] * 100, 2),
                "model_probability": round(model_probabilities[pick] * 100, 2),
                "model_probability_decimal": model_probabilities[pick],
                "edge": round(edge_decimal * 100, 2),
                "edge_decimal": edge_decimal,
                "hit": pick == actual,
                "unit_profit": round(_bet_profit(pick, actual, price, unit), 4),
            }
        )
    return candidates


def _public_bet(bet: dict) -> dict:
    return {
        key: value
        for key, value in bet.items()
        if key not in {"model_probability_decimal", "edge_decimal"}
    }


def roi_backtest(db: Session, run_id: int | None = None, staking: str = "unit", unit: float = 1.0, kelly_fraction: float = 0.25) -> dict:
    rows = _rows_with_odds(db, run_id)
    stake_total = 0.0
    profit_total = 0.0
    curve = []
    for prediction, match, odds in rows:
        pick = prediction.predicted_result
        price = _odds_for_pick(odds, pick)
        if staking == "kelly":
            probability = _prediction_probability(prediction, pick)
            edge = probability * price - 1
            raw_fraction = max(0.0, edge / max(price - 1, 1e-9))
            stake = unit * min(raw_fraction * kelly_fraction, 1.0)
        else:
            stake = unit
        profit = stake * (price - 1) if pick == _actual_result(match) else -stake
        stake_total += stake
        profit_total += profit
        curve.append({"date": match.match_date.date().isoformat(), "value": round(profit_total, 4)})
    return {
        "odds_sample_size": len(rows),
        "staking": staking,
        "stake": round(stake_total, 4),
        "profit": round(profit_total, 4),
        "roi": round(profit_total / stake_total * 100, 2) if stake_total else None,
        "max_drawdown": _max_drawdown(curve),
        "equity_curve": curve,
        "status": "需要导入真实赛前体彩赔率" if not rows else "ok",
    }


def value_bet_report(
    db: Session,
    run_id: int | None = None,
    observe_edge: float = 0.05,
    recommend_edge: float = 0.10,
    unit: float = 1.0,
    kelly_fraction: float = 0.25,
) -> dict:
    rows = _rows_with_odds(db, run_id)
    all_ai_bets: list[dict] = []
    value_bets: list[dict] = []
    skipped = 0
    observed = 0
    recommended = 0
    candidates = _best_value_candidates(rows, unit=unit)

    for (prediction, match, odds), candidate in zip(rows, candidates, strict=False):
        actual = _actual_result(match)
        all_ai_bets.append(
            {
                "date": match.match_date.date().isoformat(),
                "match_id": match.id,
                "pick": prediction.predicted_result,
                "actual": actual,
                "odds": _odds_for_pick(odds, prediction.predicted_result),
                "model_probability": _prediction_probability(prediction, prediction.predicted_result),
            }
        )

        edge = candidate["edge_decimal"]
        if edge < observe_edge:
            skipped += 1
            continue
        signal = "推荐" if edge >= recommend_edge else "观察"
        observed += signal == "观察"
        recommended += signal == "推荐"
        candidate["signal"] = signal
        value_bets.append(candidate)

    all_unit = _roi_from_bets(all_ai_bets, staking="unit", unit=unit, kelly_fraction=kelly_fraction)
    all_kelly = _roi_from_bets(all_ai_bets, staking="kelly", unit=unit, kelly_fraction=kelly_fraction)
    value_unit = _roi_from_bets(value_bets, staking="unit", unit=unit, kelly_fraction=kelly_fraction)
    value_kelly = _roi_from_bets(value_bets, staking="kelly", unit=unit, kelly_fraction=kelly_fraction)
    public_value_bets = [_public_bet(bet) for bet in value_bets]
    benchmark = benchmark_market_vs_ai(db, run_id=run_id)
    verdict = "样本不足，暂不能判断"
    if value_unit["bets"] >= 10:
        if value_unit["roi"] is not None and value_unit["roi"] > 0 and value_unit["roi"] > all_unit["roi"]:
            verdict = "Value Bet 样本优于全量AI投注，模型存在发现市场错误定价的迹象"
        elif value_unit["roi"] is not None and value_unit["roi"] > 0:
            verdict = "Value Bet ROI 为正，但未稳定优于全量AI投注，需要扩大样本"
        else:
            verdict = "当前 Value Bet ROI 未转正，暂不能证明模型优于市场"

    return {
        "status": "需要先导入真实赛前赔率并生成回测预测" if not rows else "ok",
        "edge_rules": {
            "skip": f"Edge < {observe_edge * 100:.0f}%",
            "observe": f"{observe_edge * 100:.0f}% <= Edge < {recommend_edge * 100:.0f}%",
            "recommend": f"Edge >= {recommend_edge * 100:.0f}%",
        },
        "summary": {
            "sample_size": len(rows),
            "market_hot_hit_rate": benchmark["sporttery_hot_hit_rate"],
            "ai_hit_rate": benchmark["ai_hit_rate"],
            "ai_edge_vs_market_hot": benchmark["ai_edge"],
            "all_match_unit_roi": all_unit["roi"],
            "all_match_kelly_roi": all_kelly["roi"],
            "all_match_max_drawdown": all_unit["max_drawdown"],
            "value_bet_count": value_unit["bets"],
            "value_bet_observe_count": observed,
            "value_bet_recommend_count": recommended,
            "value_bet_skipped_count": skipped,
            "value_bet_hit_rate": value_unit["hit_rate"],
            "value_bet_unit_roi": value_unit["roi"],
            "value_bet_kelly_roi": value_kelly["roi"],
            "value_bet_max_drawdown": value_unit["max_drawdown"],
            "verdict": verdict,
        },
        "all_matches": {
            "unit": all_unit,
            "kelly": all_kelly,
        },
        "value_bets": {
            "unit": value_unit,
            "kelly": value_kelly,
            "items": public_value_bets,
        },
    }


def edge_sensitivity_report(
    db: Session,
    run_id: int | None = None,
    unit: float = 1.0,
    kelly_fraction: float = 0.25,
) -> dict:
    rows = _rows_with_odds(db, run_id)
    candidates = _best_value_candidates(rows, unit=unit)
    bucket_results = []
    for label, lower, upper in EDGE_BUCKETS:
        bucket_bets = [
            bet for bet in candidates
            if bet["edge_decimal"] >= lower and (upper is None or bet["edge_decimal"] < upper)
        ]
        unit_result = _roi_from_bets(bucket_bets, staking="unit", unit=unit, kelly_fraction=kelly_fraction)
        bucket_results.append(
            {
                "edge_range": label,
                "edge_min": round(lower * 100, 2),
                "edge_max": round(upper * 100, 2) if upper is not None else None,
                "matches": unit_result["bets"],
                "hits": unit_result["hits"],
                "hit_rate": unit_result["hit_rate"],
                "stake": unit_result["stake"],
                "profit": unit_result["profit"],
                "roi": unit_result["roi"],
                "max_drawdown": unit_result["max_drawdown"],
                "equity_curve": unit_result["equity_curve"],
            }
        )

    threshold_results = []
    for threshold in (0.05, 0.10, 0.15, 0.20, 0.25):
        threshold_bets = [bet for bet in candidates if bet["edge_decimal"] >= threshold]
        unit_result = _roi_from_bets(threshold_bets, staking="unit", unit=unit, kelly_fraction=kelly_fraction)
        kelly_result = _roi_from_bets(threshold_bets, staking="kelly", unit=unit, kelly_fraction=kelly_fraction)
        threshold_results.append(
            {
                "min_edge": round(threshold * 100, 2),
                "matches": unit_result["bets"],
                "hit_rate": unit_result["hit_rate"],
                "unit_roi": unit_result["roi"],
                "kelly_roi": kelly_result["roi"],
                "max_drawdown": unit_result["max_drawdown"],
                "unit_profit": unit_result["profit"],
                "kelly_profit": kelly_result["profit"],
            }
        )
    viable_thresholds = [item for item in threshold_results if item["matches"] > 0 and item["unit_roi"] is not None]
    best_threshold = max(viable_thresholds, key=lambda item: item["unit_roi"], default=None)
    expansion_status = {
        competition: {
            "status": "待导入真实历史赔率与赛前预测，当前不使用世界杯样本外推",
            "sample_size": 0,
            "required_data": ["赛程赛果", "赛前1X2赔率", "赛前模型预测概率"],
        }
        for competition in EXPANSION_COMPETITIONS
    }
    return {
        "status": "需要先导入真实赛前赔率并生成回测预测" if not rows else "ok",
        "scope": {
            "current_dataset": "世界杯 2018 + 2022",
            "sample_size": len(rows),
            "note": "扩展赛事必须导入真实数据后单独验证，禁止用世界杯结果替代。",
        },
        "bucket_results": bucket_results,
        "threshold_results": threshold_results,
        "best_edge_threshold": best_threshold,
        "expansion_status": expansion_status,
    }


def _handicap_result(home_score: int, away_score: int, handicap: float) -> str:
    adjusted_home = home_score + handicap
    if adjusted_home > away_score:
        return "Home Win"
    if adjusted_home < away_score:
        return "Away Win"
    return "Draw"


def handicap_backtest(db: Session, run_id: int | None = None) -> dict:
    rows = [row for row in _rows_with_odds(db, run_id) if row[2].handicap is not None]
    by_line: dict[str, dict[str, int]] = {}
    for prediction, match, odds in rows:
        try:
            predicted_home, predicted_away = [int(value) for value in prediction.predicted_score.split("-", 1)]
        except ValueError:
            continue
        line = f"{odds.handicap:+g}"
        by_line.setdefault(line, {"total": 0, "hits": 0})
        by_line[line]["total"] += 1
        predicted = _handicap_result(predicted_home, predicted_away, odds.handicap or 0.0)
        actual = _handicap_result(match.home_score, match.away_score, odds.handicap or 0.0)
        by_line[line]["hits"] += predicted == actual
    return {
        "handicap_sample_size": len(rows),
        "overall_hit_rate": _ratio(sum(item["hits"] for item in by_line.values()), sum(item["total"] for item in by_line.values())),
        "by_handicap": {
            line: {
                **payload,
                "hit_rate": _ratio(payload["hits"], payload["total"]),
            }
            for line, payload in sorted(by_line.items())
        },
        "status": "需要导入真实赛前体彩让球赔率" if not rows else "ok",
    }


def upset_analysis(db: Session, run_id: int | None = None, high_odds_threshold: float = 3.0) -> dict:
    rows = _rows_with_odds(db, run_id)
    reverse_rows = []
    high_odds_rows = []
    for prediction, match, odds in rows:
        pick = prediction.predicted_result
        price = _odds_for_pick(odds, pick)
        hot = _hot_pick(odds)
        hit = pick == _actual_result(match)
        if pick != hot:
            reverse_rows.append(hit)
        if price >= high_odds_threshold:
            high_odds_rows.append(hit)
    return {
        "odds_sample_size": len(rows),
        "ai_reverse_market_count": len(reverse_rows),
        "ai_reverse_market_hit_rate": _ratio(sum(reverse_rows), len(reverse_rows)),
        "high_odds_threshold": high_odds_threshold,
        "high_odds_pick_count": len(high_odds_rows),
        "high_odds_hit_rate": _ratio(sum(high_odds_rows), len(high_odds_rows)),
        "status": "需要导入真实赛前体彩赔率" if not rows else "ok",
    }
