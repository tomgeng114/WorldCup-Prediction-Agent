from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from app.models import Match, OddsSnapshot, Team


MONTE_CARLO_RUNS = 100_000


@dataclass
class PredictionPayload:
    home_win_probability: float
    draw_probability: float
    away_win_probability: float
    predicted_result: str
    predicted_score: str
    backup_scores: str
    half_full_time: str
    total_goals_band: str
    over_under_pick: str
    both_teams_to_score: str
    confidence: float
    upset_probability: float
    explanation: str
    report_preview: str
    is_red_pick: bool
    score_probability: float = 0.0
    top_scores: list[dict] = field(default_factory=list)
    total_goals_probabilities: dict[str, float] = field(default_factory=dict)
    model_breakdown: dict[str, dict[str, float]] = field(default_factory=dict)
    market_type: str = "HAD"
    handicap: str = ""
    predicted_market_result: str = "Home Win"
    market_probabilities: dict[str, float] = field(default_factory=dict)
    one_goal_handicap_result: str = "Home Win"
    one_goal_handicap_probabilities: dict[str, float] = field(default_factory=dict)
    decision_confidence: float = 0.0
    risk_level: str = "LOW"


def _safe_inverse(odds: float) -> float:
    return 1 / odds if odds and odds > 0 else 0.0


def _normalize_three(home: float, draw: float, away: float) -> tuple[float, float, float]:
    total = home + draw + away
    if total <= 0:
        return 1 / 3, 1 / 3, 1 / 3
    return home / total, draw / total, away / total


def _market_probabilities(odds: OddsSnapshot) -> tuple[float, float, float]:
    return _normalize_three(
        _safe_inverse(odds.home_win_odds),
        _safe_inverse(odds.draw_odds),
        _safe_inverse(odds.away_win_odds),
    )


def _elo_probabilities(home: Team, away: Team) -> tuple[float, float, float]:
    diff = home.elo_rating - away.elo_rating
    home_no_draw = 1 / (1 + 10 ** (-diff / 400))
    draw = max(0.14, min(0.38, 0.28 - abs(diff) / 2000))
    return _normalize_three(home_no_draw * (1 - draw), draw, (1 - home_no_draw) * (1 - draw))


def _form_probabilities(home: Team, away: Team) -> tuple[float, float, float]:
    home_strength = max(0.05, home.recent_form + (home.xg_for - home.xga_against) * 0.12)
    away_strength = max(0.05, away.recent_form + (away.xg_for - away.xga_against) * 0.12)
    draw = max(0.14, min(0.38, 0.30 - abs(home_strength - away_strength) * 0.10))
    total_strength = home_strength + away_strength
    return _normalize_three(
        home_strength / total_strength * (1 - draw),
        draw,
        away_strength / total_strength * (1 - draw),
    )


def _poisson_probability(lmbda: float, goals: int) -> float:
    return math.exp(-lmbda) * (lmbda**goals) / math.factorial(goals)


def _expected_goals_from_probabilities(home_prob: float, draw_prob: float, away_prob: float) -> tuple[float, float]:
    edge = max(-1.4, min(1.4, math.log(max(home_prob, 0.001) / max(away_prob, 0.001))))
    # Decoupled from draw_prob — lambda driven by edge (dominance gap), not dp suppression
    home_lambda = max(0.15, 1.35 + edge * 0.42)
    away_lambda = max(0.15, 1.35 - edge * 0.42)
    return home_lambda, away_lambda


def _xg_adjusted_lambdas(
    home: Team,
    away: Team,
    probability_anchor: tuple[float, float, float],
) -> tuple[float, float]:
    market_home_lambda, market_away_lambda = _expected_goals_from_probabilities(*probability_anchor)
    home_stat_lambda = 0.62 * home.xg_for + 0.38 * away.xga_against
    away_stat_lambda = 0.62 * away.xg_for + 0.38 * home.xga_against

    # 竞彩数据里的近况统计更像 xG proxy；用市场强弱只做校准，避免赔率单独决定比分。
    home_lambda = home_stat_lambda * 0.68 + market_home_lambda * 0.32
    away_lambda = away_stat_lambda * 0.68 + market_away_lambda * 0.32
    home_lambda *= 1.04
    away_lambda *= 0.98

    home_prob, _draw_prob, away_prob = probability_anchor
    market_gap = home_prob - away_prob
    elo_gap = (home.elo_rating - away.elo_rating) / 400
    xg_gap = (home.xg_for - home.xga_against) - (away.xg_for - away.xga_against)
    dominance = market_gap * 0.58 + elo_gap * 0.24 + xg_gap * 0.18
    if dominance >= 0.52:
        home_lambda += 0.55 + min(0.35, (dominance - 0.52) * 0.55)
        away_lambda = max(0.25, away_lambda - 0.12)
    elif dominance >= 0.34:
        home_lambda += 0.28 + min(0.20, (dominance - 0.34) * 0.45)
        away_lambda = max(0.30, away_lambda - 0.06)
    elif dominance <= -0.52:
        away_lambda += 0.55 + min(0.35, (-dominance - 0.52) * 0.55)
        home_lambda = max(0.25, home_lambda - 0.12)
    elif dominance <= -0.34:
        away_lambda += 0.28 + min(0.20, (-dominance - 0.34) * 0.45)
        home_lambda = max(0.30, home_lambda - 0.06)
    return max(0.15, min(3.8, home_lambda)), max(0.15, min(3.8, away_lambda))


def _score_matrix(lambda_home: float, lambda_away: float, max_goals: int = 8) -> list[dict]:
    scores = []
    for home_goals in range(max_goals + 1):
        for away_goals in range(max_goals + 1):
            probability = _poisson_probability(lambda_home, home_goals) * _poisson_probability(lambda_away, away_goals)
            scores.append(
                {
                    "score": f"{home_goals}-{away_goals}",
                    "home_goals": home_goals,
                    "away_goals": away_goals,
                    "probability": probability,
                }
            )
    total = sum(item["probability"] for item in scores)
    for item in scores:
        item["probability"] = item["probability"] / total if total else 0.0
    return scores


def _apply_low_score_correction(
    scores: list[dict],
    lambda_home: float,
    lambda_away: float,
    home: Team | None = None,
    away: Team | None = None,
) -> list[dict]:
    corrected = []
    rho = -0.08
    dominance_gap = abs(lambda_home - lambda_away)
    high_favorite_total = lambda_home + lambda_away >= 2.75 and dominance_gap >= 0.95
    for item in scores:
        home_goals = item["home_goals"]
        away_goals = item["away_goals"]
        multiplier = 1.0
        if home_goals == 0 and away_goals == 0:
            multiplier = 1 - (lambda_home * lambda_away * rho)
        elif home_goals == 0 and away_goals == 1:
            multiplier = 1 + (lambda_home * rho)
        elif home_goals == 1 and away_goals == 0:
            multiplier = 1 + (lambda_away * rho)
        elif home_goals == 1 and away_goals == 1:
            multiplier = 1 - rho
        if high_favorite_total:
            total_goals = home_goals + away_goals
            if total_goals <= 1:
                multiplier *= 0.78
            elif total_goals >= 3:
                multiplier *= 1.10
            if lambda_home > lambda_away and home_goals - away_goals >= 2:
                multiplier *= 1.08
            elif lambda_away > lambda_home and away_goals - home_goals >= 2:
                multiplier *= 1.08
            if home and away:
                if lambda_away - lambda_home >= 1.75 and home.xg_for >= 0.75 and home_goals >= 1 and away_goals >= 2:
                    multiplier *= 1.16
                elif lambda_home - lambda_away >= 1.75 and away.xg_for >= 0.75 and away_goals >= 1 and home_goals >= 2:
                    multiplier *= 1.16
        corrected.append({**item, "probability": max(0.0, item["probability"] * multiplier)})
    total = sum(item["probability"] for item in corrected)
    for item in corrected:
        item["probability"] = item["probability"] / total if total else 0.0
    return corrected


def _poisson_outcome_probabilities(scores: list[dict]) -> tuple[float, float, float]:
    home = sum(item["probability"] for item in scores if item["home_goals"] > item["away_goals"])
    draw = sum(item["probability"] for item in scores if item["home_goals"] == item["away_goals"])
    away = sum(item["probability"] for item in scores if item["home_goals"] < item["away_goals"])
    return _normalize_three(home, draw, away)


def _h2h_probabilities(home: Team, away: Team) -> tuple[float, float, float]:
    home_edge = max(0.05, min(0.95, home.world_cup_history_score))
    away_edge = max(0.05, min(0.95, away.world_cup_history_score))
    draw = max(0.14, min(0.38, 0.28 - abs(home_edge - away_edge) * 0.10))
    return _normalize_three(home_edge * (1 - draw), draw, away_edge * (1 - draw))


def _monte_carlo_probabilities(scores: list[dict], seed: int) -> tuple[float, float, float]:
    rng = random.Random(seed)
    cumulative = []
    running = 0.0
    for item in scores:
        running += item["probability"]
        cumulative.append((running, item["home_goals"], item["away_goals"]))

    home = draw = away = 0
    for _ in range(MONTE_CARLO_RUNS):
        sample = rng.random()
        for threshold, home_goals, away_goals in cumulative:
            if sample <= threshold:
                if home_goals > away_goals:
                    home += 1
                elif home_goals == away_goals:
                    draw += 1
                else:
                    away += 1
                break
    return home / MONTE_CARLO_RUNS, draw / MONTE_CARLO_RUNS, away / MONTE_CARLO_RUNS


def _weighted_probabilities(parts: dict[str, tuple[float, float, float]]) -> tuple[float, float, float]:
    weights = {
        "elo": 0.27,
        "form": 0.20,
        "odds": 0.18,
        "poisson": 0.22,
        "monte_carlo": 0.10,
        "h2h": 0.03,
    }
    home = sum(parts[key][0] * weight for key, weight in weights.items())
    draw = sum(parts[key][1] * weight for key, weight in weights.items())
    away = sum(parts[key][2] * weight for key, weight in weights.items())
    return _normalize_three(home, draw, away)


def _draw_specialist_adjustment(
    probabilities: tuple[float, float, float],
    lambda_home: float,
    lambda_away: float,
    home: Team,
    away: Team,
    market_probabilities: tuple[float, float, float] | None = None,
    strength_probabilities: tuple[float, float, float] | None = None,
) -> tuple[tuple[float, float, float], bool]:
    total_expected_goals = lambda_home + lambda_away
    elo_gap = abs(home.elo_rating - away.elo_rating)
    boost = 0.0
    if total_expected_goals < 2.3 and elo_gap < 50:
        boost = 0.08
    elif total_expected_goals < 2.5 and elo_gap < 80:
        boost = 0.04

    if market_probabilities and strength_probabilities:
        market_pick = _pick_result(*market_probabilities)
        strength_pick = _pick_result(*strength_probabilities)
        market_draw = market_probabilities[1]
        conflict = market_pick != strength_pick and "Draw" not in {market_pick, strength_pick}
        if conflict and market_draw >= 0.24 and total_expected_goals <= 3.1:
            boost = max(boost, 0.22)
        elif conflict and market_draw >= 0.22 and total_expected_goals <= 2.8:
            boost = max(boost, 0.14)

    if boost <= 0:
        return probabilities, False

    return _normalize_three(
        probabilities[0] * (1 - boost),
        probabilities[1] + boost,
        probabilities[2] * (1 - boost),
    ), True


def _pick_result(home: float, draw: float, away: float) -> str:
    """Legacy decision function — kept for internal callers (confidence agreement, handicap picks).

    Decision Layer v2 entry point is _pick_result_v2() below.
    """
    if draw >= 0.25 and max(home, away) - draw <= 0.18:
        return "Draw"
    if home >= draw and home >= away:
        return "Home Win"
    if away >= home and away >= draw:
        return "Away Win"
    return "Draw"


def _pick_result_v2(
    home: float,
    draw: float,
    away: float,
    upset_probability: float = 0.0,
) -> tuple[str, float, str]:
    """Decision Layer v2 — risk-stratified result selection.

    Replaces the legacy forced-single-pick with:
      - Strong-draw zone   (draw ≥ 0.30)           → "Draw"
      - Gray zone          (0.25 ≤ draw < 0.30)    → contextual decision
      - Normal zone        (draw < 0.25)            → argmax

    Returns:
        (predicted_result, decision_confidence, risk_level)
    """
    win_prob = max(home, away)
    win_gap = win_prob - draw

    # ── Zone 1: Strong Draw ──────────────────────────────────────────
    if draw >= 0.32:
        confidence = 55.0 + (draw - 0.30) * 150.0  # 55 → ~85
        return "Draw", round(min(85.0, confidence), 1), "LOW"

    # ── Zone 2: Gray Zone (25%–30% draw probability) ─────────────────
    if draw >= 0.25:
        # 2a — Competitive match with high upset risk → Draw signal
        if win_gap <= 0.12 and upset_probability >= 60.0:
            confidence = 42.0 + (upset_probability - 60.0) * 0.5
            return "Draw", round(min(65.0, confidence), 1), "MEDIUM"

        # 2b — Clear favorite gap → normal favourite pick
        if win_gap > 0.15:
            if home >= away:
                return "Home Win", round(40.0 + win_gap * 60.0, 1), "MEDIUM"
            return "Away Win", round(40.0 + win_gap * 60.0, 1), "MEDIUM"

        # 2c — Neither clear draw nor clear favourite → UNCERTAIN
        uncertainty_score = round(15.0 + (0.15 - win_gap) * 300.0, 1)
        return "UNCERTAIN", min(45.0, uncertainty_score), "HIGH"

    # ── Zone 3: Normal Zone (draw < 25%) ─────────────────────────────
    risk = "LOW"
    if home >= draw and home >= away:
        gap = home - max(draw, away)
        confidence = 60.0 + gap * 60.0
        if gap < 0.08:
            risk = "MEDIUM"
        return "Home Win", round(min(92.0, confidence), 1), risk
    if away >= home and away >= draw:
        gap = away - max(home, draw)
        confidence = 60.0 + gap * 60.0
        if gap < 0.08:
            risk = "MEDIUM"
        return "Away Win", round(min(92.0, confidence), 1), risk
    return "Draw", 30.0, "HIGH"


def _result_label(result: str) -> str:
    return {"Home Win": "主胜", "Draw": "平局", "Away Win": "客胜", "UNCERTAIN": "不确定（灰区）"}.get(result, result)


def _market_label(result: str, market_type: str) -> str:
    if market_type == "HHAD":
        return {"Home Win": "让球胜", "Draw": "让球平", "Away Win": "让球负"}.get(result, result)
    return _result_label(result)


def _confidence(result_probabilities: tuple[float, float, float], parts: dict[str, tuple[float, float, float]]) -> float:
    top_probability = max(result_probabilities)
    winners = [_pick_result(*probabilities) for probabilities in parts.values()]
    agreement = winners.count(max(set(winners), key=winners.count)) / len(winners)
    margin = sorted(result_probabilities, reverse=True)[0] - sorted(result_probabilities, reverse=True)[1]
    return round(max(0, min(100, top_probability * 55 + agreement * 30 + margin * 50)), 1)


def _upset_probability(
    result: str,
    final_probs: tuple[float, float, float],
    market_probs: tuple[float, float, float],
    home: Team,
    away: Team,
    odds: OddsSnapshot,
) -> float:
    model_pick_probability = {"Home Win": final_probs[0], "Draw": final_probs[1], "Away Win": final_probs[2]}[result]
    market_pick_probability = {"Home Win": market_probs[0], "Draw": market_probs[1], "Away Win": market_probs[2]}[result]
    elo_gap = abs(home.elo_rating - away.elo_rating)
    elo_risk = max(0.0, 1 - elo_gap / 450)
    market_disagreement = max(0.0, market_pick_probability - model_pick_probability)
    movement_risk = min(0.18, abs(odds.line_movement) * 0.06)
    kelly_risk = min(0.12, max(0.0, odds.kelly_index - 0.95) * 0.8)
    upset = (1 - model_pick_probability) * 0.55 + elo_risk * 0.18 + market_disagreement * 0.18 + movement_risk + kelly_risk
    return round(max(0, min(100, upset * 100)), 1)


def _total_goal_probabilities(scores: list[dict]) -> dict[str, float]:
    buckets = {"0球": 0.0, "1球": 0.0, "2球": 0.0, "3球": 0.0, "4+": 0.0}
    for item in scores:
        total_goals = item["home_goals"] + item["away_goals"]
        key = "4+" if total_goals >= 4 else f"{total_goals}球"
        buckets[key] += item["probability"]
    return {key: round(value, 4) for key, value in buckets.items()}


def _score_result(item: dict) -> str:
    if item["home_goals"] > item["away_goals"]:
        return "Home Win"
    if item["home_goals"] < item["away_goals"]:
        return "Away Win"
    return "Draw"


def _goal_bucket(total_goals: int) -> str:
    return "4+" if total_goals >= 4 else f"{total_goals}球"


def _goal_band_from_bucket(bucket: str) -> str:
    if bucket in {"0球", "1球"}:
        return "0-1 goals"
    if bucket in {"2球", "3球"}:
        return "2-3 goals"
    return "4+ goals"


def _goal_band_label(band: str) -> str:
    labels = {
        "0-1 goals": "0-1 球",
        "2-3 goals": "2-3 球",
        "4+ goals": "4 球以上",
    }
    return labels.get(band, band)


def _half_full_pick(result: str, home_prob: float, draw_prob: float, away_prob: float) -> str:
    if result == "Home Win":
        return "Win/Win" if home_prob - draw_prob > 0.18 else "Draw/Win"
    if result == "Away Win":
        return "Lose/Lose" if away_prob - draw_prob > 0.18 else "Draw/Lose"
    return "Draw/Draw"


def _market_context(odds: OddsSnapshot) -> tuple[str, str]:
    market_type = (odds.source_pool or "HAD").upper()
    handicap = odds.handicap or ""
    return market_type, handicap


def _parse_handicap(handicap: str) -> float:
    try:
        return float(handicap)
    except (TypeError, ValueError):
        return 0.0


def _handicap_probabilities_from_scores(scores: list[dict], handicap: str) -> tuple[float, float, float]:
    line = _parse_handicap(handicap)
    home = draw = away = 0.0
    for item in scores:
        adjusted_home = item["home_goals"] + line
        if adjusted_home > item["away_goals"]:
            home += item["probability"]
        elif adjusted_home < item["away_goals"]:
            away += item["probability"]
        else:
            draw += item["probability"]
    return _normalize_three(home, draw, away)


def _blend_handicap_market_probabilities(
    scores: list[dict],
    handicap: str,
    odds_probabilities: tuple[float, float, float],
) -> tuple[float, float, float]:
    score_probabilities = _handicap_probabilities_from_scores(scores, handicap)
    score_weight = 0.68
    odds_weight = 1 - score_weight
    return _normalize_three(
        score_probabilities[0] * score_weight + odds_probabilities[0] * odds_weight,
        score_probabilities[1] * score_weight + odds_probabilities[1] * odds_weight,
        score_probabilities[2] * score_weight + odds_probabilities[2] * odds_weight,
    )


def _handicap_result_from_score(score: str, handicap: str) -> str | None:
    try:
        home_score_text, away_score_text = score.split("-", 1)
        adjusted_home = int(home_score_text) + _parse_handicap(handicap)
        away_score = int(away_score_text)
    except (AttributeError, TypeError, ValueError):
        return None

    if adjusted_home > away_score:
        return "Home Win"
    if adjusted_home < away_score:
        return "Away Win"
    return "Draw"


def _top_score_handicap_support(top_scores: list[dict], handicap: str) -> tuple[set[str], dict[str, float]]:
    support = {"Home Win": 0.0, "Draw": 0.0, "Away Win": 0.0}
    outcomes: set[str] = set()
    for item in top_scores:
        outcome = _handicap_result_from_score(item.get("score", ""), handicap)
        if not outcome:
            continue
        outcomes.add(outcome)
        support[outcome] += float(item.get("probability", 0.0) or 0.0)
    return outcomes, support


def _consistent_handicap_pick(
    matrix_pick: str,
    top_scores: list[dict],
    handicap: str,
) -> tuple[str, bool, dict[str, float]]:
    outcomes, support = _top_score_handicap_support(top_scores, handicap)
    if not outcomes or matrix_pick in outcomes:
        return matrix_pick, False, support

    # The visible recommendation should not contradict every displayed score.
    # When that happens, prefer the handicap outcome backed by the Top3 score mass.
    return max(support, key=support.get), True, support


def _apply_handicap_draw_guard(probabilities: tuple[float, float, float]) -> tuple[float, float, float]:
    return _normalize_three(probabilities[0] * 0.72, probabilities[1] + 0.34, probabilities[2] * 0.72)


def _handicap_margin_guard(
    probabilities: tuple[float, float, float],
    handicap: str,
    lambda_home: float,
    lambda_away: float,
    top_score_support: dict[str, float],
) -> tuple[tuple[float, float, float], bool]:
    line = _parse_handicap(handicap)
    if abs(line) < 1:
        return probabilities, False

    favorite_lambda = lambda_home if line < 0 else lambda_away
    underdog_lambda = lambda_away if line < 0 else lambda_home
    dominance_gap = favorite_lambda - underdog_lambda
    if dominance_gap < 1.15:
        return probabilities, False

    home, draw, away = probabilities
    top_home = top_score_support.get("Home Win", 0.0)
    top_draw = top_score_support.get("Draw", 0.0)
    top_away = top_score_support.get("Away Win", 0.0)
    applied = False

    if line < 0:
        if top_home > 0 and top_away == 0 and home + 0.08 >= away:
            home += 0.10 + min(0.06, max(0.0, dominance_gap - 1.15) * 0.04)
            away *= 0.78
            applied = True
        if top_draw >= top_home and top_draw > 0 and abs(home - draw) <= 0.08:
            draw += 0.05
            applied = True
    else:
        if top_draw > 0 and top_away > 0 and away > draw and away - draw <= 0.22:
            draw += 0.08
            away *= 0.86
            applied = True
        elif top_away > 0 and top_home == 0 and away + 0.08 >= home:
            away += 0.06
            home *= 0.88
            applied = True

    return _normalize_three(home, draw, away), applied


def _goal_bucket(total_goals: int) -> str:
    return "5g+" if total_goals >= 5 else f"{total_goals}g"


def _total_goal_probabilities(scores: list[dict]) -> dict[str, float]:
    buckets = {"0g": 0.0, "1g": 0.0, "2g": 0.0, "3g": 0.0, "4g": 0.0, "5g+": 0.0}
    for item in scores:
        total_goals = item["home_goals"] + item["away_goals"]
        buckets[_goal_bucket(total_goals)] += item["probability"]
    return {key: round(value, 4) for key, value in buckets.items()}


def _goal_band_from_bucket(bucket: str) -> str:
    return bucket


def _goal_band_label(band: str) -> str:
    if " / " in band:
        return " / ".join(_goal_band_label(item) for item in band.split(" / "))
    labels = {
        "0g": "0\u7403",
        "1g": "1\u7403",
        "2g": "2\u7403",
        "3g": "3\u7403",
        "4g": "4\u7403",
        "5g+": "5\u7403\u4ee5\u4e0a",
    }
    return labels.get(band, band)


def _adjacent_goal_buckets(total_goal_probabilities: dict[str, float]) -> list[str]:
    order = ["0g", "1g", "2g", "3g", "4g", "5g+"]
    top_bucket = max(order, key=lambda bucket: total_goal_probabilities.get(bucket, 0.0))
    index = order.index(top_bucket)
    neighbors = []
    if index > 0:
        neighbors.append(order[index - 1])
    if index < len(order) - 1:
        neighbors.append(order[index + 1])
    if not neighbors:
        return [top_bucket]
    adjacent_bucket = max(neighbors, key=lambda bucket: total_goal_probabilities.get(bucket, 0.0))
    return [top_bucket, adjacent_bucket]


def _diverse_top_scores(scores: list[dict], result: str) -> list[dict]:
    sorted_scores = sorted(scores, key=lambda item: item["probability"], reverse=True)
    if not sorted_scores:
        return []

    def score_result(item: dict) -> str:
        if item["home_goals"] > item["away_goals"]:
            return "Home Win"
        if item["home_goals"] < item["away_goals"]:
            return "Away Win"
        return "Draw"

    aligned_scores = [item for item in sorted_scores if score_result(item) == result]
    selected = [aligned_scores[0] if aligned_scores else sorted_scores[0]]
    top_probability = selected[0]["probability"]

    def add_candidates(min_probability_ratio: float, require_result: bool, require_new_total: bool) -> None:
        seen_scores = {item["score"] for item in selected}
        seen_totals = {item["home_goals"] + item["away_goals"] for item in selected}
        for item in sorted_scores:
            if len(selected) >= 3:
                return
            if item["score"] in seen_scores:
                continue
            if item["probability"] < top_probability * min_probability_ratio:
                continue
            if require_result and score_result(item) != result:
                continue
            if require_new_total and item["home_goals"] + item["away_goals"] in seen_totals:
                continue
            selected.append(item)
            seen_scores.add(item["score"])
            seen_totals.add(item["home_goals"] + item["away_goals"])

    add_candidates(min_probability_ratio=0.55, require_result=True, require_new_total=True)
    add_candidates(min_probability_ratio=0.45, require_result=False, require_new_total=True)
    add_candidates(min_probability_ratio=0.35, require_result=True, require_new_total=False)
    add_candidates(min_probability_ratio=0.0, require_result=False, require_new_total=False)
    return selected[:3]


def predict_match(match: Match, odds: OddsSnapshot) -> PredictionPayload:
    home: Team = match.home_team
    away: Team = match.away_team

    market_type, handicap = _market_context(odds)
    raw_market_probs_tuple = _market_probabilities(odds)

    elo_probs = _elo_probabilities(home, away)
    form_probs = _form_probabilities(home, away)

    # ── Squad Intelligence Layer (SHADOW MODE) ────────────────────
    # Data collection only. Does NOT affect predictions.
    # Shadow audit recorded in model_breakdown['squad_shadow'].
    from app.services.squad_intel import compute_squad_score, compute_squad_gap
    from app.db import SessionLocal as _SessionLocal
    from app.models import MatchLineup as _MatchLineup
    from sqlalchemy import select as _select
    import json as _json

    home_squad = 100; away_squad = 100; squad_shadow = None
    try:
        _db = _SessionLocal()
        _lineups = _db.scalars(_select(_MatchLineup).where(_MatchLineup.match_id == match.id)).all()
        _db.close()
        if _lineups:
            for lu in _lineups:
                _missing = _json.loads(lu.missing_players or '[]') if lu.missing_players else []
                _positions = [m.get('position','') for m in _missing]
                _score = compute_squad_score(
                    starting_xi_count=11,
                    missing_positions=_positions,
                    captain_absent=any(m.get('name','')==lu.captain for m in _missing),
                    rotation_count=0)
                if lu.is_home: home_squad = _score
                else: away_squad = _score
            _squad_adj = compute_squad_gap(home_squad, away_squad)
            if _squad_adj['squad_gap'] != 0:
                h_boost = _squad_adj['home_strength_adj'] * 0.5
                a_boost = _squad_adj['away_strength_adj'] * 0.5
                # Shadow: what would the adjusted ELO probs be?
                _shadow_elo = _normalize_three(
                    max(0.01, elo_probs[0] + h_boost * (1 - elo_probs[1])),
                    elo_probs[1],
                    max(0.01, elo_probs[2] + a_boost * (1 - elo_probs[1])))
                _shadow_form = _normalize_three(
                    max(0.01, form_probs[0] + h_boost * (1 - form_probs[1])),
                    form_probs[1],
                    max(0.01, form_probs[2] + a_boost * (1 - form_probs[1])))
                squad_shadow = {
                    'home_squad': home_squad, 'away_squad': away_squad,
                    'squad_gap': _squad_adj['squad_gap'],
                    'shadow_elo': [round(x,4) for x in _shadow_elo],
                    'shadow_form': [round(x,4) for x in _shadow_form],
                }
    except: pass
    # ── End Squad Intelligence Layer ──────────────────────────────

    if market_type == "HHAD":
        # 让球胜平负不是普通赛果赔率；真实赛果层只用非盘口能力面估计赔率因子。
        true_odds_proxy = _normalize_three(
            (elo_probs[0] + form_probs[0]) / 2,
            (elo_probs[1] + form_probs[1]) / 2,
            (elo_probs[2] + form_probs[2]) / 2,
        )
    else:
        true_odds_proxy = raw_market_probs_tuple

    lambda_home, lambda_away = _xg_adjusted_lambdas(home, away, true_odds_proxy)
    scores = _apply_low_score_correction(_score_matrix(lambda_home, lambda_away), lambda_home, lambda_away, home, away)
    market_probs_tuple = (
        _handicap_probabilities_from_scores(scores, handicap)
        if market_type == "HHAD"
        else raw_market_probs_tuple
    )
    market_pick = _pick_result(*market_probs_tuple)
    one_goal_handicap_probs_tuple = _handicap_probabilities_from_scores(scores, "-1")
    one_goal_handicap_pick = _pick_result(*one_goal_handicap_probs_tuple)

    parts = {
        "elo": elo_probs,
        "form": form_probs,
        "odds": true_odds_proxy,
        "poisson": _poisson_outcome_probabilities(scores),
        "monte_carlo": _monte_carlo_probabilities(scores, seed=match.id or int(match.kickoff_time.timestamp())),
        "h2h": _h2h_probabilities(home, away),
    }
    final_probs = _weighted_probabilities(parts)
    strength_probs = _normalize_three(
        (elo_probs[0] + form_probs[0] + parts["poisson"][0]) / 3,
        (elo_probs[1] + form_probs[1] + parts["poisson"][1]) / 3,
        (elo_probs[2] + form_probs[2] + parts["poisson"][2]) / 3,
    )
    final_probs, draw_specialist_applied = _draw_specialist_adjustment(
        final_probs,
        lambda_home,
        lambda_away,
        home,
        away,
        raw_market_probs_tuple,
        strength_probs,
    )
    home_prob, draw_prob, away_prob = final_probs

    # Lambda values are now decoupled from draw probability.
    # No global calibration needed — edge-based λ naturally matches dominance.

    # Recompute score matrix with calibrated lambdas
    scores = _apply_low_score_correction(
        _score_matrix(lambda_home, lambda_away), lambda_home, lambda_away, home, away
    )

    # Compute upset using "Draw" for gray-zone evaluation — this tells us
    # how risky a Draw pick would be in the current match context.
    draw_upset = _upset_probability("Draw", (home_prob, draw_prob, away_prob), market_probs_tuple, home, away, odds)
    result, decision_confidence, risk_level = _pick_result_v2(
        home_prob, draw_prob, away_prob, upset_probability=draw_upset,
    )
    upset_probability = draw_upset
    top_scores = _diverse_top_scores(scores, result)
    handicap_consistency_applied = False
    top_score_handicap_support: dict[str, float] = {"Home Win": 0.0, "Draw": 0.0, "Away Win": 0.0}
    if market_type == "HHAD":
        top_score_handicap_support = _top_score_handicap_support(top_scores, handicap)[1]
        market_probs_tuple, handicap_margin_guard_applied = _handicap_margin_guard(
            market_probs_tuple,
            handicap,
            lambda_home,
            lambda_away,
            top_score_handicap_support,
        )
        market_pick = _pick_result(*market_probs_tuple)
        market_pick, handicap_consistency_applied, top_score_handicap_support = _consistent_handicap_pick(
            market_pick,
            top_scores,
            handicap,
        )
    else:
        handicap_margin_guard_applied = False
    total_goal_probabilities = _total_goal_probabilities(scores)
    top_goal_buckets = _adjacent_goal_buckets(total_goal_probabilities)

    predicted_score = top_scores[0]["score"]
    score_probability = round(top_scores[0]["probability"], 4)
    total_goals_band = " / ".join(_goal_band_from_bucket(bucket) for bucket in top_goal_buckets)
    over_under_pick = (
        "Over 2.5"
        if sum(item["probability"] for item in scores if item["home_goals"] + item["away_goals"] >= 3) >= 0.5
        else "Under 2.5"
    )
    both_teams_to_score = (
        "Yes"
        if sum(item["probability"] for item in scores if item["home_goals"] > 0 and item["away_goals"] > 0) >= 0.5
        else "No"
    )
    model_confidence = _confidence(final_probs, parts)
    half_full_time = _half_full_pick(result, home_prob, draw_prob, away_prob) if result != "UNCERTAIN" else "—"

    top_score_payload = [
        {"score": item["score"], "probability": round(item["probability"], 4)}
        for item in top_scores
    ]
    model_breakdown = {
        key: {"home": round(value[0], 4), "draw": round(value[1], 4), "away": round(value[2], 4)}
        for key, value in parts.items()
    }
    model_breakdown["strength_proxy"] = {
        "home": round(strength_probs[0], 4),
        "draw": round(strength_probs[1], 4),
        "away": round(strength_probs[2], 4),
    }
    model_breakdown["goal_model"] = {
        "lambda_home": round(lambda_home, 4),
        "lambda_away": round(lambda_away, 4),
        "draw_guard": 1.0 if draw_specialist_applied else 0.0,
    }
    if squad_shadow:
        model_breakdown["squad_shadow"] = squad_shadow
    if market_type == "HHAD":
        model_breakdown["top3_handicap_support"] = {
            "home": round(top_score_handicap_support["Home Win"], 4),
            "draw": round(top_score_handicap_support["Draw"], 4),
            "away": round(top_score_handicap_support["Away Win"], 4),
        }
        model_breakdown["handicap_consistency_guard"] = {
            "applied": 1.0 if handicap_consistency_applied else 0.0,
            "margin_guard": 1.0 if handicap_margin_guard_applied else 0.0,
            "handicap": handicap,
        }
    market_probabilities = {
        "home": round(market_probs_tuple[0], 4),
        "draw": round(market_probs_tuple[1], 4),
        "away": round(market_probs_tuple[2], 4),
    }
    one_goal_handicap_probabilities = {
        "home": round(one_goal_handicap_probs_tuple[0], 4),
        "draw": round(one_goal_handicap_probs_tuple[1], 4),
        "away": round(one_goal_handicap_probs_tuple[2], 4),
    }
    result_label = _result_label(result)
    market_name = "让球胜平负" if market_type == "HHAD" else "胜平负"
    market_pick_label = _market_label(market_pick, market_type)
    handicap_text = f"（{handicap}）" if handicap else ""
    odds_note = (
        "该场只有让球胜平负赔率，真实赛果层未把让球赔率直接当普通胜平负使用。"
        if market_type == "HHAD"
        else "该场使用普通胜平负赔率参与真实赛果融合。"
    )
    risk_label = {"LOW": "低风险", "MEDIUM": "中风险（灰区）", "HIGH": "高风险（不确定）"}.get(risk_level, risk_level)
    if result == "UNCERTAIN":
        gray_note = (
            f"⚠️ 灰区警报：平局概率 {draw_prob:.1%} 处于 25%–30% 不确定区间，"
            f"胜负概率差距仅 {max(home_prob, away_prob) - draw_prob:.1%}，"
            f"冷门概率 {upset_probability:.1f}%。系统拒绝强制单选，标记为 UNCERTAIN。"
        )
    else:
        win_gap = max(home_prob, away_prob) - draw_prob
        gray_note = (
            f"决策层 v2：平局概率 {draw_prob:.1%}，"
            f"风险等级 {risk_label}，决策置信度 {decision_confidence:.1f}/100。"
            f"{'平局强信号已触发。' if draw_prob >= 0.30 else ''}"
            f"{'灰区平局信号：竞争激烈且冷门风险高。' if 0.25 <= draw_prob < 0.30 and result == 'Draw' else ''}"
            f"{'灰区胜负信号：实力差距较明显。' if 0.25 <= draw_prob < 0.30 and result != 'Draw' else ''}"
        )
    explanation = (
        f"模型融合 ELO、近10场近况、竞彩赔率、攻防 xG proxy、交锋先验、Dixon-Coles 低比分修正和 {MONTE_CARLO_RUNS} 次 Monte Carlo 模拟。"
        f"真实赛果概率为主胜 {home_prob:.1%}、平局 {draw_prob:.1%}、客胜 {away_prob:.1%}，"
        f"赛果主推 {result_label}。{odds_note}"
        f"竞彩盘口为{market_name}{handicap_text}，盘口主推 {market_pick_label}。"
        f"{gray_note}"
        f"{'平局专用模型已触发：双方 ELO 接近且预期总进球偏低，已提高平局识别权重。' if draw_specialist_applied else ''}"
        f"让球胜平负使用独立 Handicap Model：先生成 0-0 至 5-5 的 Dixon-Coles 比分概率矩阵，再按让球数汇总让胜/让平/让负概率。"
        f"比分推荐按单一精确比分概率排序；总进球推荐按总进球数概率排序。"
    )
    report_preview = (
        f"赛前分析：{home.name} vs {away.name}。AI 真实赛果主推 {result_label}，"
        f"单一最高比分 {predicted_score}（{score_probability:.1%}）。"
        f"总进球推荐为 {_goal_band_label(total_goals_band)}（按总进球数概率计算）。"
        f"竞彩盘口 {market_name}{handicap_text} 主推 {market_pick_label}，"
        f"决策置信度 {decision_confidence:.1f}/100，风险等级 {risk_label}，冷门概率 {upset_probability:.1f}%。"
    )

    return PredictionPayload(
        home_win_probability=round(home_prob, 4),
        draw_probability=round(draw_prob, 4),
        away_win_probability=round(away_prob, 4),
        predicted_result=result,
        predicted_score=predicted_score,
        backup_scores=" | ".join(item["score"] for item in top_score_payload),
        half_full_time=half_full_time,
        total_goals_band=total_goals_band,
        over_under_pick=over_under_pick,
        both_teams_to_score=both_teams_to_score,
        confidence=model_confidence,
        upset_probability=upset_probability,
        explanation=explanation,
        report_preview=report_preview,
        is_red_pick=False,
        score_probability=score_probability,
        top_scores=top_score_payload,
        total_goals_probabilities=total_goal_probabilities,
        model_breakdown=model_breakdown,
        market_type=market_type,
        handicap=handicap,
        predicted_market_result=market_pick,
        market_probabilities=market_probabilities,
        one_goal_handicap_result=one_goal_handicap_pick,
        one_goal_handicap_probabilities=one_goal_handicap_probabilities,
        decision_confidence=decision_confidence,
        risk_level=risk_level,
    )
