from __future__ import annotations

import json
import math
import csv
from collections import defaultdict, deque
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import BacktestPrediction, BacktestRun, WorldCupMatch
from app.services.world_cup_history import WORLD_CUP_YEARS, fetch_world_cup_year


RESULTS = ["Home Win", "Draw", "Away Win"]
INITIAL_WEIGHTS = {
    "elo": 0.41,
    "dixon_coles": 0.32,
    "odds": 0.20,
    "form": 0.00,
    "strength": 0.00,
    "fifa": 0.27,
}
WARMUP_YEARS = [1930, 1934, 1938, 1950, 1954, 1958, 1962, 1966, 1970, 1974, 1978, 1982, 1986, 1990, 1994, 1998]
GOAL_BUCKET_PRIOR = {
    0: 0.06,
    1: 0.18,
    2: 0.25,
    3: 0.25,
    4: 0.13,
    5: 0.08,
    6: 0.05,
}
TEAM_NAME_ALIASES = {
    "Korea Republic": "South Korea",
    "IR Iran": "Iran",
    "United States": "USA",
}


@dataclass
class TeamState:
    elo: float = 1500.0
    matches: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals_for: int = 0
    goals_against: int = 0
    recent: deque[tuple[int, int, str]] = field(default_factory=lambda: deque(maxlen=10))
    world_cup_matches: int = 0
    knockout_matches: int = 0


@dataclass
class PredictionBundle:
    probabilities: dict[str, float]
    predicted_result: str
    predicted_score: str
    predicted_half_full: str
    predicted_total_goals: int
    component_probabilities: dict[str, dict[str, float]]
    component_predictions: dict[str, str]
    weights: dict[str, float]


@dataclass
class GoalCalibrationState:
    actual_buckets: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    predicted_buckets: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    actual_scores_by_result: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )

    def bucket_multiplier(self, bucket: int) -> float:
        actual_total = sum(self.actual_buckets.values())
        predicted_total = sum(self.predicted_buckets.values())
        if actual_total < 80 or predicted_total < 80:
            return 1.0
        actual_rate = (self.actual_buckets.get(bucket, 0) + 2.0) / (actual_total + 14.0)
        predicted_rate = (self.predicted_buckets.get(bucket, 0) + 2.0) / (predicted_total + 14.0)
        return max(0.88, min(1.14, math.sqrt(actual_rate / max(predicted_rate, 1e-9))))

    def score_multiplier(self, result: str, score: str) -> float:
        result_scores = self.actual_scores_by_result.get(result, {})
        total = sum(result_scores.values())
        if total < 80:
            return 1.0
        max_count = max(result_scores.values()) if result_scores else 1
        relative_frequency = (result_scores.get(score, 0) + 1.0) / (max_count + 1.0)
        return max(0.78, min(1.32, 0.82 + 0.50 * math.sqrt(relative_frequency)))

    def update(
        self,
        predicted_total_goals: int,
        actual_total_goals: int,
        actual_result: str | None = None,
        actual_score: str | None = None,
    ) -> None:
        self.predicted_buckets[_goal_bucket(predicted_total_goals)] += 1
        self.actual_buckets[_goal_bucket(actual_total_goals)] += 1
        if actual_result and actual_score:
            self.actual_scores_by_result[actual_result][actual_score] += 1


def _normalize(values: dict[str, float]) -> dict[str, float]:
    total = sum(values.values())
    if total <= 0:
        return {key: 1 / len(values) for key in values}
    return {key: value / total for key, value in values.items()}


@lru_cache(maxsize=1)
def _load_fifa_rankings() -> dict[int, dict[str, int]]:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    rankings: dict[int, dict[str, int]] = {2018: {}, 2022: {}}
    rank_2018 = data_dir / "World_cup_2018_country.csv"
    if rank_2018.exists():
        with rank_2018.open(newline="", encoding="utf-8") as file:
            for row in csv.DictReader(file):
                country = row.get("Country") or ""
                rank = row.get("World_ranking") or ""
                if country and rank:
                    rankings[2018][country] = int(rank)

    rank_2022 = data_dir / "fifa_ranking-2022-10-06.csv"
    if rank_2022.exists():
        with rank_2022.open(newline="", encoding="utf-8") as file:
            for row in csv.DictReader(file):
                if row.get("rank_date") != "2022-10-06":
                    continue
                country = row.get("country_full") or ""
                rank = row.get("rank") or ""
                if country and rank:
                    rankings[2022][country] = int(rank)
                    rankings[2022][TEAM_NAME_ALIASES.get(country, country)] = int(rank)

    return rankings


def _fifa_rank(team_name: str, tournament_year: int | None) -> int | None:
    if tournament_year not in (2018, 2022):
        return None
    rankings = _load_fifa_rankings().get(tournament_year, {})
    return rankings.get(team_name)


def _pick(probabilities: dict[str, float]) -> str:
    draw = probabilities.get("Draw", 0.0)
    strongest_side = max(probabilities.get("Home Win", 0.0), probabilities.get("Away Win", 0.0))
    if draw >= 0.30 and strongest_side - draw <= 0.14:
        return "Draw"
    return max(probabilities, key=probabilities.get)


def _expected_total_goals(scores: list[dict]) -> float:
    return sum((item["home_goals"] + item["away_goals"]) * item["probability"] for item in scores)


def _goal_bucket(total_goals: int) -> int:
    return 6 if total_goals >= 6 else total_goals


def _score_within_one_goal(predicted_score: str, actual_score: str) -> bool:
    try:
        predicted_home, predicted_away = (int(value) for value in predicted_score.split("-", 1))
        actual_home, actual_away = (int(value) for value in actual_score.split("-", 1))
    except (AttributeError, ValueError):
        return False
    return abs(predicted_home - actual_home) <= 1 and abs(predicted_away - actual_away) <= 1


def _calibrated_top_scores(
    scores: list[dict],
    predicted_result: str,
    limit: int = 3,
    goal_calibration: GoalCalibrationState | None = None,
) -> list[dict]:
    bucket_mass: dict[int, float] = defaultdict(float)
    for item in scores:
        bucket_mass[_goal_bucket(item["home_goals"] + item["away_goals"])] += item["probability"]

    result_filtered = [
        item
        for item in scores
        if _result(item["home_goals"], item["away_goals"]) == predicted_result
    ]
    candidates = result_filtered or scores
    ranked = []
    for item in candidates:
        bucket = _goal_bucket(item["home_goals"] + item["away_goals"])
        prior = GOAL_BUCKET_PRIOR.get(bucket, 0.04)
        model_mass = max(bucket_mass.get(bucket, 0.0), 1e-9)
        rolling_multiplier = goal_calibration.bucket_multiplier(bucket) if goal_calibration else 1.0
        score_multiplier = goal_calibration.score_multiplier(predicted_result, item["score"]) if goal_calibration else 1.0
        calibrated_probability = item["probability"] * math.sqrt(prior / model_mass) * rolling_multiplier * score_multiplier
        ranked.append({**item, "calibrated_probability": calibrated_probability})

    expected_goals = _expected_total_goals(scores)
    if expected_goals < 1.99:
        target_bucket = 0
    elif expected_goals < 2.29:
        target_bucket = 1
    elif expected_goals < 2.46:
        target_bucket = 2
    elif expected_goals < 2.46:
        target_bucket = 2
    elif expected_goals < 2.68:
        target_bucket = 3
    elif expected_goals < 2.75:
        target_bucket = 4
    elif expected_goals < 2.80:
        target_bucket = 5
    else:
        target_bucket = 6

    ranked.sort(key=lambda item: item["calibrated_probability"], reverse=True)
    target_candidates = []
    for distance in range(0, 7):
        possible_buckets = [target_bucket] if distance == 0 else [target_bucket - distance, target_bucket + distance]
        target_candidates = [
            item
            for item in ranked
            if _goal_bucket(item["home_goals"] + item["away_goals"]) in possible_buckets
        ]
        if target_candidates:
            break
    if target_candidates:
        ranked = target_candidates + [item for item in ranked if item not in target_candidates]

    selected: list[dict] = []
    used_buckets: set[int] = set()
    for item in ranked:
        bucket = _goal_bucket(item["home_goals"] + item["away_goals"])
        if bucket in used_buckets and len(selected) < limit:
            continue
        selected.append(item)
        used_buckets.add(bucket)
        if len(selected) == limit:
            break
    if len(selected) < limit:
        for item in ranked:
            if item not in selected:
                selected.append(item)
                if len(selected) == limit:
                    break
    if expected_goals >= 2.85:
        high_goal_candidates = [
            item
            for item in ranked
            if 4 <= item["home_goals"] + item["away_goals"] <= 6
        ]
        if high_goal_candidates and all(item["home_goals"] + item["away_goals"] < 4 for item in selected):
            selected[-1] = high_goal_candidates[0]
        if expected_goals >= 3.25 and high_goal_candidates:
            selected = [high_goal_candidates[0]] + [item for item in selected if item != high_goal_candidates[0]]
    return selected[:limit]


def _accuracy_top_scores(scores: list[dict], predicted_result: str, limit: int = 3) -> list[dict]:
    candidates = [
        item
        for item in scores
        if _result(item["home_goals"], item["away_goals"]) == predicted_result
    ] or scores
    expected_goals = _expected_total_goals(scores)
    target_total = 2 if 2.15 <= expected_goals <= 2.85 else int(round(max(0, min(6, expected_goals))))
    ranked = sorted(
        candidates,
        key=lambda item: (
            -abs((item["home_goals"] + item["away_goals"]) - target_total),
            item["probability"],
        ),
        reverse=True,
    )
    selected: list[dict] = []
    seen_scores: set[str] = set()
    for item in ranked:
        if item["score"] in seen_scores:
            continue
        selected.append(item)
        seen_scores.add(item["score"])
        if len(selected) == limit:
            break
    return selected[:limit]


def _draw_specialist_adjustment(probabilities: dict[str, float], scores: list[dict], home: TeamState, away: TeamState) -> dict[str, float]:
    total_expected_goals = _expected_total_goals(scores)
    elo_gap = abs(home.elo - away.elo)
    boost = 0.0
    if total_expected_goals < 2.3 and elo_gap < 50:
        boost = 0.04
    elif total_expected_goals < 2.6 and elo_gap < 120:
        boost = 0.025
    elif probabilities.get("Draw", 0.0) >= 0.24 and max(probabilities.get("Home Win", 0.0), probabilities.get("Away Win", 0.0)) - probabilities.get("Draw", 0.0) <= 0.20:
        boost = 0.02

    if boost <= 0:
        return probabilities

    return _normalize(
        {
            "Home Win": probabilities["Home Win"] * (1 - boost),
            "Draw": probabilities["Draw"] + boost,
            "Away Win": probabilities["Away Win"] * (1 - boost),
        }
    )


def _draw_model_probability(home: TeamState, away: TeamState, scores: list[dict], stage: str = "") -> float:
    expected_goals = _expected_total_goals(scores)
    elo_gap = abs(home.elo - away.elo)
    home_defense = _goal_rate(home, False)
    away_defense = _goal_rate(away, False)
    defensive_strength = max(0.0, 1.35 - ((home_defense + away_defense) / 2))
    home_draw_rate = home.draws / home.matches if home.matches else 0.24
    away_draw_rate = away.draws / away.matches if away.matches else 0.24
    historical_draw = (home_draw_rate + away_draw_rate) / 2
    knockout = any(token in stage for token in ("Round of 16", "Quarter", "Semi", "Final", "Third"))

    draw = 0.18
    draw += max(0.0, min(0.08, (120 - elo_gap) / 120 * 0.08))
    draw += max(0.0, min(0.07, (2.7 - expected_goals) / 2.7 * 0.07))
    draw += max(0.0, min(0.04, defensive_strength * 0.04))
    draw += max(-0.03, min(0.05, (historical_draw - 0.22) * 0.35))
    if knockout:
        draw += 0.025
    return max(0.18, min(0.36, draw))


def _draw_calibration_adjustment(
    probabilities: dict[str, float],
    home: TeamState,
    away: TeamState,
    scores: list[dict],
    stage: str,
    home_team: str,
    away_team: str,
    tournament_year: int | None,
) -> dict[str, float]:
    expected_goals = _expected_total_goals(scores)
    elo_gap = abs(home.elo - away.elo)
    home_rank = _fifa_rank(home_team, tournament_year)
    away_rank = _fifa_rank(away_team, tournament_year)
    rank_gap = abs(home_rank - away_rank) if home_rank is not None and away_rank is not None else 999
    home_recent_ga = _recent_goal_rate(home, False)
    away_recent_ga = _recent_goal_rate(away, False)
    goals_against_gap = abs(home_recent_ga - away_recent_ga)
    knockout = any(token in stage for token in ("Round of 16", "Quarter", "Semi", "Final", "Third"))

    boost = 0.0
    if elo_gap < 100:
        boost += 0.02
    if expected_goals < 2.0:
        boost += 0.02
    if rank_gap < 6:
        boost += 0.02
    if goals_against_gap < 0.25:
        boost += 0.007
    if knockout:
        boost += 0.015

    if boost <= 0:
        return probabilities
    boost = min(boost, 0.08)
    return _normalize(
        {
            "Home Win": probabilities["Home Win"] * (1 - boost),
            "Draw": probabilities["Draw"] + boost,
            "Away Win": probabilities["Away Win"] * (1 - boost),
        }
    )


def _brier(probabilities: dict[str, float], actual: str) -> float:
    return sum((probabilities[result] - (1.0 if result == actual else 0.0)) ** 2 for result in RESULTS)


def _result(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "Home Win"
    if home_goals < away_goals:
        return "Away Win"
    return "Draw"


def _elo_probabilities(home: TeamState, away: TeamState) -> dict[str, float]:
    diff = home.elo - away.elo
    home_no_draw = 1 / (1 + 10 ** (-diff / 400))
    draw = max(0.18, min(0.32, 0.28 - abs(diff) / 2200))
    return _normalize(
        {
            "Home Win": home_no_draw * (1 - draw),
            "Draw": draw,
            "Away Win": (1 - home_no_draw) * (1 - draw),
        }
    )


def _recent_score(team: TeamState, window: int) -> float:
    if not team.recent:
        return 0.5
    rows = list(team.recent)[-window:]
    points = 0
    for goals_for, goals_against, _ in rows:
        if goals_for > goals_against:
            points += 3
        elif goals_for == goals_against:
            points += 1
    return points / (len(rows) * 3)


def _goal_rate(team: TeamState, for_goals: bool = True) -> float:
    if team.matches == 0:
        return 1.15
    value = team.goals_for if for_goals else team.goals_against
    return max(0.2, value / team.matches)


def _form_probabilities(home: TeamState, away: TeamState) -> dict[str, float]:
    home_form = 0.6 * _recent_score(home, 5) + 0.4 * _recent_score(home, 10)
    away_form = 0.6 * _recent_score(away, 5) + 0.4 * _recent_score(away, 10)
    home_attack = _goal_rate(home, True) - _goal_rate(away, False)
    away_attack = _goal_rate(away, True) - _goal_rate(home, False)
    home_strength = max(0.05, home_form + home_attack * 0.08)
    away_strength = max(0.05, away_form + away_attack * 0.08)
    draw = max(0.20, min(0.33, 0.29 - abs(home_strength - away_strength) * 0.08))
    return _normalize(
        {
            "Home Win": home_strength * (1 - draw),
            "Draw": draw,
            "Away Win": away_strength * (1 - draw),
        }
    )


def _strength_probabilities(home: TeamState, away: TeamState) -> dict[str, float]:
    home_experience = math.log1p(home.world_cup_matches) * 18 + math.log1p(home.knockout_matches) * 10
    away_experience = math.log1p(away.world_cup_matches) * 18 + math.log1p(away.knockout_matches) * 10
    diff = (home.elo + home_experience) - (away.elo + away_experience)
    home_no_draw = 1 / (1 + 10 ** (-diff / 430))
    draw = max(0.19, min(0.31, 0.27 - abs(diff) / 2600))
    return _normalize(
        {
            "Home Win": home_no_draw * (1 - draw),
            "Draw": draw,
            "Away Win": (1 - home_no_draw) * (1 - draw),
        }
    )


def _fifa_probabilities(home_team: str, away_team: str, tournament_year: int | None) -> dict[str, float] | None:
    home_rank = _fifa_rank(home_team, tournament_year)
    away_rank = _fifa_rank(away_team, tournament_year)
    if home_rank is None or away_rank is None:
        return None
    rank_diff = away_rank - home_rank
    home_no_draw = 1 / (1 + 10 ** (-rank_diff / 240))
    draw = max(0.18, min(0.32, 0.27 - abs(rank_diff) / 420))
    return _normalize(
        {
            "Home Win": home_no_draw * (1 - draw),
            "Draw": draw,
            "Away Win": (1 - home_no_draw) * (1 - draw),
        }
    )


def _poisson_probability(lmbda: float, goals: int) -> float:
    return math.exp(-lmbda) * (lmbda**goals) / math.factorial(goals)


def _recent_goal_rate(team: TeamState, for_goals: bool = True) -> float:
    if not team.recent:
        return _goal_rate(team, for_goals)
    index = 0 if for_goals else 1
    return max(0.2, sum(row[index] for row in team.recent) / len(team.recent))


def _dixon_coles_score_matrix(home: TeamState, away: TeamState, max_goals: int = 8) -> list[dict]:
    home_attack = 0.58 * _goal_rate(home, True) + 0.42 * _recent_goal_rate(home, True)
    home_defense = 0.58 * _goal_rate(home, False) + 0.42 * _recent_goal_rate(home, False)
    away_attack = 0.58 * _goal_rate(away, True) + 0.42 * _recent_goal_rate(away, True)
    away_defense = 0.58 * _goal_rate(away, False) + 0.42 * _recent_goal_rate(away, False)
    home_lambda = 0.95 * (0.56 * home_attack + 0.44 * away_defense)
    away_lambda = 0.95 * (0.56 * away_attack + 0.44 * home_defense)
    home_lambda = max(0.15, min(4.5, home_lambda))
    away_lambda = max(0.15, min(4.5, away_lambda))
    rho = -0.08
    scores = []
    for home_goals in range(max_goals + 1):
        for away_goals in range(max_goals + 1):
            probability = _poisson_probability(home_lambda, home_goals) * _poisson_probability(away_lambda, away_goals)
            multiplier = 1.0
            if home_goals == 0 and away_goals == 0:
                multiplier = 1 - (home_lambda * away_lambda * rho)
            elif home_goals == 0 and away_goals == 1:
                multiplier = 1 + (home_lambda * rho)
            elif home_goals == 1 and away_goals == 0:
                multiplier = 1 + (away_lambda * rho)
            elif home_goals == 1 and away_goals == 1:
                multiplier = 1 - rho
            scores.append(
                {
                    "score": f"{home_goals}-{away_goals}",
                    "home_goals": home_goals,
                    "away_goals": away_goals,
                    "probability": max(0.0, probability * multiplier),
                }
            )
    total = sum(item["probability"] for item in scores)
    for item in scores:
        item["probability"] = item["probability"] / total if total else 0.0
    return scores


def _poisson_probabilities(scores: list[dict]) -> dict[str, float]:
    return _normalize(
        {
            "Home Win": sum(item["probability"] for item in scores if item["home_goals"] > item["away_goals"]),
            "Draw": sum(item["probability"] for item in scores if item["home_goals"] == item["away_goals"]),
            "Away Win": sum(item["probability"] for item in scores if item["home_goals"] < item["away_goals"]),
        }
    )


def _redistribute_weights(weights: dict[str, float], available: set[str]) -> dict[str, float]:
    usable = {key: value for key, value in weights.items() if key in available}
    return _normalize(usable)


def _optimize_weights(component_scores: dict[str, list[int]], base_weights: dict[str, float]) -> dict[str, float]:
    raw = {}
    for component, base_weight in base_weights.items():
        rows = component_scores.get(component, [])
        if not rows:
            raw[component] = base_weight
            continue
        accuracy = sum(rows[-48:]) / len(rows[-48:])
        adaptive = max(0.05, min(0.42, base_weight * (0.75 + accuracy)))
        raw[component] = 0.75 * base_weight + 0.25 * adaptive
    return _normalize(raw)


def _update_team_state(team: TeamState, goals_for: int, goals_against: int, stage: str) -> None:
    team.matches += 1
    team.world_cup_matches += 1
    team.goals_for += goals_for
    team.goals_against += goals_against
    result = _result(goals_for, goals_against)
    if result == "Home Win":
        team.wins += 1
    elif result == "Away Win":
        team.losses += 1
    else:
        team.draws += 1
    if "Round of 16" in stage or "Quarter" in stage or "Semi" in stage or "Final" in stage:
        team.knockout_matches += 1
    team.recent.append((goals_for, goals_against, result))


def _update_elo(home: TeamState, away: TeamState, home_score: int, away_score: int) -> None:
    expected_home = 1 / (1 + 10 ** ((away.elo - home.elo) / 400))
    actual_home = 1.0 if home_score > away_score else 0.5 if home_score == away_score else 0.0
    margin = max(1, abs(home_score - away_score))
    k = 28 * math.log1p(margin)
    change = k * (actual_home - expected_home)
    home.elo += change
    away.elo -= change


class BacktestEngine:
    def __init__(
        self,
        db: Session,
        initial_weights: dict[str, float] | None = None,
        score_mode: str = "calibrated",
        use_warmup: bool = True,
    ) -> None:
        self.db = db
        self.initial_weights = _normalize(initial_weights or INITIAL_WEIGHTS)
        self.score_mode = score_mode if score_mode in {"calibrated", "accuracy"} else "calibrated"
        self.use_warmup = use_warmup
        self.skipped_warmup_years: list[dict[str, str]] = []

    def _warmup_states(
        self,
        states: dict[str, TeamState],
        before_year: int,
        component_scores: dict[str, list[int]],
        weights: dict[str, float],
        goal_calibration: GoalCalibrationState,
    ) -> tuple[int, dict[str, float]]:
        warmup_matches = 0
        local_warmup_years = [year for year in WORLD_CUP_YEARS if year < before_year]
        historical_warmup_years = [year for year in WARMUP_YEARS if year < before_year]
        for year in historical_warmup_years + local_warmup_years:
            try:
                raw_matches = fetch_world_cup_year(year)
            except RuntimeError as exc:
                self.skipped_warmup_years.append({"year": str(year), "reason": str(exc)})
                continue
            for raw_match in raw_matches:
                score = raw_match.get("score") or {}
                full_time = score.get("ft") or []
                if len(full_time) != 2:
                    continue
                home_team = raw_match.get("team1") or ""
                away_team = raw_match.get("team2") or ""
                home_score = int(full_time[0])
                away_score = int(full_time[1])
                stage = raw_match.get("round") or ""
                warmup_match = SimpleNamespace(home_team=home_team, away_team=away_team)
                prediction = self._predict(warmup_match, states, weights, goal_calibration)
                actual_result = _result(home_score, away_score)
                for component, component_pick in prediction.component_predictions.items():
                    component_scores[component].append(1 if component_pick == actual_result else 0)
                weights = _optimize_weights(component_scores, self.initial_weights)
                goal_calibration.update(
                    prediction.predicted_total_goals,
                    home_score + away_score,
                    actual_result,
                    f"{home_score}-{away_score}",
                )
                home_state = states[home_team]
                away_state = states[away_team]
                _update_elo(home_state, away_state, home_score, away_score)
                _update_team_state(home_state, home_score, away_score, stage)
                _update_team_state(away_state, away_score, home_score, stage)
                warmup_matches += 1
        return warmup_matches, weights

    def _predict(
        self,
        match: WorldCupMatch,
        states: dict[str, TeamState],
        weights: dict[str, float],
        goal_calibration: GoalCalibrationState | None = None,
    ) -> PredictionBundle:
        home = states[match.home_team]
        away = states[match.away_team]
        scores = _dixon_coles_score_matrix(home, away)
        poisson_probs = _poisson_probabilities(scores)
        component_probabilities = {
            "elo": _elo_probabilities(home, away),
            "dixon_coles": poisson_probs,
            "form": _form_probabilities(home, away),
            "strength": _strength_probabilities(home, away),
        }
        fifa_probs = _fifa_probabilities(
            match.home_team,
            match.away_team,
            getattr(match, "tournament_year", None),
        )
        if fifa_probs:
            component_probabilities["fifa"] = fifa_probs

        # Historical openfootball data has no verified bookmaker odds. Do not fabricate odds.
        available_weights = _redistribute_weights(weights, set(component_probabilities))
        final = {result: 0.0 for result in RESULTS}
        for component, component_probs in component_probabilities.items():
            for result in RESULTS:
                final[result] += component_probs[result] * available_weights[component]
        final = _normalize(final)
        final = _draw_calibration_adjustment(
            final,
            home,
            away,
            scores,
            getattr(match, "stage", ""),
            match.home_team,
            match.away_team,
            getattr(match, "tournament_year", None),
        )

        predicted_result = _pick(final)
        if self.score_mode == "accuracy":
            top_scores = _accuracy_top_scores(scores, predicted_result, limit=3)
        else:
            top_scores = _calibrated_top_scores(scores, predicted_result, limit=3, goal_calibration=goal_calibration)
        top_score = top_scores[0]
        predicted_half = "Draw" if top_score["home_goals"] == top_score["away_goals"] else predicted_result
        return PredictionBundle(
            probabilities=final,
            predicted_result=predicted_result,
            predicted_score=top_score["score"],
            predicted_half_full=f"{predicted_half}/{predicted_result}",
            predicted_total_goals=top_score["home_goals"] + top_score["away_goals"],
            component_probabilities=component_probabilities,
            component_predictions={key: _pick(value) for key, value in component_probabilities.items()},
            weights=available_weights,
        )

    def run(self, years: list[int] | None = None, replace_previous: bool = False) -> BacktestRun:
        query = select(WorldCupMatch).order_by(WorldCupMatch.match_date.asc(), WorldCupMatch.id.asc())
        if years:
            query = query.where(WorldCupMatch.tournament_year.in_(years))
        matches = self.db.scalars(query).all()

        run = BacktestRun(
            model_version="worldcup_backtest_v1",
            years=",".join(str(year) for year in (years or sorted({match.tournament_year for match in matches}))),
            total_matches=len(matches),
            initial_weights=json.dumps(self.initial_weights, ensure_ascii=False),
            final_weights="{}",
            metrics="{}",
        )
        self.db.add(run)
        self.db.flush()
        if replace_previous:
            self.db.execute(delete(BacktestPrediction).where(BacktestPrediction.run_id == run.id))

        states: dict[str, TeamState] = defaultdict(TeamState)
        warmup_before_year = min(match.tournament_year for match in matches) if matches else 2002
        component_scores: dict[str, list[int]] = defaultdict(list)
        weights = dict(self.initial_weights)
        predictions: list[BacktestPrediction] = []
        goal_calibration = GoalCalibrationState()
        if self.use_warmup:
            warmup_matches, weights = self._warmup_states(
                states,
                warmup_before_year,
                component_scores,
                weights,
                goal_calibration,
            )
        else:
            warmup_matches = 0

        for match in matches:
            prediction = self._predict(match, states, weights, goal_calibration)
            actual_score = f"{match.home_score}-{match.away_score}"
            result_hit = prediction.predicted_result == match.result
            score_hit = prediction.predicted_score == actual_score
            half_full_hit = prediction.predicted_half_full == match.half_full_result
            total_goals_hit = prediction.predicted_total_goals == match.total_goals
            brier_score = _brier(prediction.probabilities, match.result)

            for component, component_pick in prediction.component_predictions.items():
                component_scores[component].append(1 if component_pick == match.result else 0)

            row = BacktestPrediction(
                run_id=run.id,
                match_id=match.id,
                predicted_result=prediction.predicted_result,
                actual_result=match.result,
                predicted_score=prediction.predicted_score,
                actual_score=actual_score,
                predicted_half_full=prediction.predicted_half_full,
                actual_half_full=match.half_full_result,
                predicted_total_goals=prediction.predicted_total_goals,
                actual_total_goals=match.total_goals,
                home_win_probability=prediction.probabilities["Home Win"],
                draw_probability=prediction.probabilities["Draw"],
                away_win_probability=prediction.probabilities["Away Win"],
                result_hit=result_hit,
                score_hit=score_hit,
                half_full_hit=half_full_hit,
                total_goals_hit=total_goals_hit,
                brier_score=brier_score,
                roi=0.0,
                component_predictions=json.dumps(prediction.component_predictions, ensure_ascii=False),
                weights=json.dumps(prediction.weights, ensure_ascii=False),
            )
            self.db.add(row)
            predictions.append(row)

            home_state = states[match.home_team]
            away_state = states[match.away_team]
            goal_calibration.update(
                prediction.predicted_total_goals,
                match.total_goals,
                match.result,
                actual_score,
            )
            _update_elo(home_state, away_state, match.home_score, match.away_score)
            _update_team_state(home_state, match.home_score, match.away_score, match.stage)
            _update_team_state(away_state, match.away_score, match.home_score, match.stage)
            weights = _optimize_weights(component_scores, self.initial_weights)

        metrics = summarize_predictions(predictions, matches, component_scores)
        metrics["score_selection_mode"] = self.score_mode
        metrics["use_warmup"] = self.use_warmup
        metrics["warmup_matches"] = warmup_matches
        metrics["skipped_warmup_years"] = self.skipped_warmup_years
        metrics["warmup_note"] = "使用回测起始年份之前全部可获得世界杯历史比赛做赛前 warm-up；不计入回测指标，不使用未来数据。"
        metrics["goal_calibration"] = {
            "enabled": True,
            "policy": "Rolling pre-match calibration: only completed prior matches update predicted/actual total-goal bucket multipliers.",
            "predicted_buckets": dict(sorted(goal_calibration.predicted_buckets.items())),
            "actual_buckets": dict(sorted(goal_calibration.actual_buckets.items())),
        }
        run.metrics = json.dumps(metrics, ensure_ascii=False)
        run.final_weights = json.dumps(weights, ensure_ascii=False)
        self.db.commit()
        return run


def summarize_predictions(
    predictions: list[BacktestPrediction],
    matches: list[WorldCupMatch],
    component_scores: dict[str, list[int]],
) -> dict:
    total = len(predictions)
    if total == 0:
        return {}
    by_year: dict[int, list[BacktestPrediction]] = defaultdict(list)
    match_year = {match.id: match.tournament_year for match in matches}
    for row in predictions:
        by_year[match_year[row.match_id]].append(row)

    def ratio(rows: list[BacktestPrediction], attr: str) -> float:
        return round(sum(1 for row in rows if getattr(row, attr)) / len(rows) * 100, 2) if rows else 0.0

    def total_goal_distribution(rows: list[BacktestPrediction], attr: str) -> dict[str, dict[str, float]]:
        labels = {0: "0球", 1: "1球", 2: "2球", 3: "3球", 4: "4球", 5: "5球", 6: "6+球"}
        counts = {label: 0 for label in labels.values()}
        for row in rows:
            bucket = _goal_bucket(getattr(row, attr))
            counts[labels[bucket]] += 1
        return {
            label: {
                "count": count,
                "rate": round(count / len(rows) * 100, 2) if rows else 0.0,
            }
            for label, count in counts.items()
        }

    def distribution_error(predicted: dict[str, dict], actual: dict[str, dict]) -> float:
        return round(sum(abs(predicted[key]["rate"] - actual[key]["rate"]) for key in predicted), 2)

    predicted_goal_distribution = total_goal_distribution(predictions, "predicted_total_goals")
    actual_goal_distribution = total_goal_distribution(predictions, "actual_total_goals")

    plus_minus_one_goal_hits = sum(
        1
        for row in predictions
        if _score_within_one_goal(row.predicted_score, row.actual_score)
    )

    yearly = {}
    for year, rows in sorted(by_year.items()):
        yearly[str(year)] = {
            "total_matches": len(rows),
            "win_draw_loss_accuracy": ratio(rows, "result_hit"),
            "score_accuracy": ratio(rows, "score_hit"),
            "half_full_accuracy": ratio(rows, "half_full_hit"),
            "total_goals_accuracy": ratio(rows, "total_goals_hit"),
            "brier_score": round(sum(row.brier_score for row in rows) / len(rows), 4),
            "roi": 0.0,
        }

    component_accuracy = {
        component: round(sum(rows) / len(rows) * 100, 2) if rows else 0.0
        for component, rows in component_scores.items()
    }
    calibration_bins: dict[str, dict] = {}
    for row in predictions:
        probabilities = {
            "Home Win": row.home_win_probability,
            "Draw": row.draw_probability,
            "Away Win": row.away_win_probability,
        }
        predicted_probability = probabilities[row.predicted_result]
        bucket_floor = int(predicted_probability * 10) / 10
        bucket = f"{bucket_floor:.1f}-{bucket_floor + 0.1:.1f}"
        calibration_bins.setdefault(bucket, {"count": 0, "hits": 0, "avg_confidence": 0.0})
        calibration_bins[bucket]["count"] += 1
        calibration_bins[bucket]["hits"] += 1 if row.result_hit else 0
        calibration_bins[bucket]["avg_confidence"] += predicted_probability
    for bucket, payload in calibration_bins.items():
        count = payload["count"]
        payload["avg_confidence"] = round(payload["avg_confidence"] / count * 100, 2) if count else 0.0
        payload["observed_hit_rate"] = round(payload["hits"] / count * 100, 2) if count else 0.0
        payload["calibration_gap"] = round(payload["observed_hit_rate"] - payload["avg_confidence"], 2)

    yearly_ranking = sorted(
        (
            {"year": year, **payload}
            for year, payload in yearly.items()
        ),
        key=lambda item: item["win_draw_loss_accuracy"],
        reverse=True,
    )
    return {
        "total_matches": total,
        "win_draw_loss_accuracy": ratio(predictions, "result_hit"),
        "correct_results": sum(1 for row in predictions if row.result_hit),
        "score_accuracy": ratio(predictions, "score_hit"),
        "plus_minus_one_goal_accuracy": round(plus_minus_one_goal_hits / total * 100, 2),
        "half_full_accuracy": ratio(predictions, "half_full_hit"),
        "total_goals_accuracy": ratio(predictions, "total_goals_hit"),
        "total_goals_distribution": {
            "predicted_distribution": predicted_goal_distribution,
            "actual_distribution": actual_goal_distribution,
            "distribution_error": distribution_error(predicted_goal_distribution, actual_goal_distribution),
        },
        "brier_score": round(sum(row.brier_score for row in predictions) / total, 4),
        "roi": 0.0,
        "roi_note": "历史源未提供可验证赛前赔率，ROI 暂不伪造，等待真实赔率数据接入后计算。",
        "odds_coverage": 0.0,
        "component_accuracy": component_accuracy,
        "calibration_bins": dict(sorted(calibration_bins.items())),
        "yearly": yearly,
        "yearly_ranking": yearly_ranking,
    }
