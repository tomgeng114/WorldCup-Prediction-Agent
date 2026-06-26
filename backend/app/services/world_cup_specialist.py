from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BacktestPrediction, BacktestRun, WorldCupMatch, WorldCupOdds, WorldCupTeamProfile
from app.services.data_confidence import assess_match_data_confidence


RESULTS = ("Home Win", "Draw", "Away Win")
PROFILE_FIELDS = (
    "country",
    "confederation",
    "fifa_ranking",
    "elo_rating",
    "projected_starting_xi",
    "key_injuries",
    "squad_market_value_eur",
    "average_age",
    "total_caps",
    "average_caps",
    "world_cup_history_score",
    "recent_two_year_rating",
    "coach",
    "last_world_cup_finish",
)
EXPECTED_2026_TEAMS = 48
EXPECTED_2026_MATCHES = 104
CONFEDERATIONS = ("UEFA", "CONMEBOL", "AFC", "CAF", "CONCACAF", "OFC")
OFFICIAL_2026_QUALIFIED_TEAMS = (
    ("Canada", "CONCACAF"),
    ("Mexico", "CONCACAF"),
    ("USA", "CONCACAF"),
    ("Spain", "UEFA"),
    ("Argentina", "CONMEBOL"),
    ("France", "UEFA"),
    ("England", "UEFA"),
    ("Brazil", "CONMEBOL"),
    ("Portugal", "UEFA"),
    ("Netherlands", "UEFA"),
    ("Belgium", "UEFA"),
    ("Germany", "UEFA"),
    ("Croatia", "UEFA"),
    ("Morocco", "CAF"),
    ("Colombia", "CONMEBOL"),
    ("Uruguay", "CONMEBOL"),
    ("Switzerland", "UEFA"),
    ("Japan", "AFC"),
    ("Senegal", "CAF"),
    ("IR Iran", "AFC"),
    ("Korea Republic", "AFC"),
    ("Ecuador", "CONMEBOL"),
    ("Austria", "UEFA"),
    ("Australia", "AFC"),
    ("Norway", "UEFA"),
    ("Panama", "CONCACAF"),
    ("Egypt", "CAF"),
    ("Algeria", "CAF"),
    ("Scotland", "UEFA"),
    ("Paraguay", "CONMEBOL"),
    ("Tunisia", "CAF"),
    ("Cote d'Ivoire", "CAF"),
    ("Uzbekistan", "AFC"),
    ("Qatar", "AFC"),
    ("Saudi Arabia", "AFC"),
    ("South Africa", "CAF"),
    ("Jordan", "AFC"),
    ("Cabo Verde", "CAF"),
    ("Ghana", "CAF"),
    ("Curacao", "CONCACAF"),
    ("Haiti", "CONCACAF"),
    ("New Zealand", "OFC"),
    ("Czechia", "UEFA"),
    ("Bosnia and Herzegovina", "UEFA"),
    ("Turkiye", "UEFA"),
    ("Sweden", "UEFA"),
    ("DR Congo", "CAF"),
    ("Iraq", "AFC"),
)
FIFA_2026_TEAMS_SOURCE = "FIFA.com 2026 Final Draw qualified teams and playoff winners"


@dataclass
class ProfileImportSummary:
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


def _parse_int(value: object) -> int | None:
    parsed = _parse_float(value)
    return int(parsed) if parsed is not None else None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _json_text(value: str | None, fallback: str) -> str:
    if not value:
        return fallback
    try:
        json.loads(value)
        return value
    except json.JSONDecodeError:
        items = [item.strip() for item in value.split("|") if item.strip()]
        return json.dumps(items, ensure_ascii=False)


def _safe_json(value: str, fallback: object) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def import_team_profiles_csv(db: Session, csv_path: str | Path) -> ProfileImportSummary:
    path = Path(csv_path)
    imported = 0
    updated = 0
    skipped = 0
    with path.open(newline="", encoding="utf-8-sig") as file:
        for row in csv.DictReader(file):
            year = _parse_int(row.get("tournament_year"))
            team_name = (row.get("team_name") or "").strip()
            if not year or not team_name:
                skipped += 1
                continue
            profile = db.scalar(
                select(WorldCupTeamProfile).where(
                    WorldCupTeamProfile.tournament_year == year,
                    WorldCupTeamProfile.team_name == team_name,
                )
            )
            is_update = profile is not None
            profile = profile or WorldCupTeamProfile(tournament_year=year, team_name=team_name)
            profile.country = (row.get("country") or team_name).strip()
            profile.confederation = (row.get("confederation") or profile.confederation or "").strip().upper()
            profile.fifa_ranking = _parse_int(row.get("fifa_ranking"))
            profile.elo_rating = _parse_float(row.get("elo_rating"))
            profile.projected_starting_xi = _json_text(row.get("projected_starting_xi"), "[]")
            profile.key_injuries = _json_text(row.get("key_injuries"), "[]")
            profile.squad_market_value_eur = _parse_float(row.get("squad_market_value_eur"))
            profile.average_age = _parse_float(row.get("average_age"))
            profile.total_caps = _parse_int(row.get("total_caps"))
            profile.average_caps = _parse_float(row.get("average_caps"))
            profile.world_cup_history_score = _parse_float(row.get("world_cup_history_score"))
            profile.recent_two_year_rating = _parse_float(row.get("recent_two_year_rating"))
            profile.coach = row.get("coach") or ""
            profile.last_world_cup_finish = row.get("last_world_cup_finish") or ""
            profile.world_cup_strength_score = calculate_world_cup_strength_score(profile)
            profile.upset_alert_score = calculate_team_upset_alert(profile)
            profile.source = row.get("source") or "manual_verified"
            profile.captured_at = _parse_datetime(row.get("captured_at"))
            db.add(profile)
            imported += int(not is_update)
            updated += int(is_update)
    db.commit()
    return ProfileImportSummary(imported=imported, updated=updated, skipped=skipped)


def seed_2026_qualified_teams(db: Session) -> ProfileImportSummary:
    imported = 0
    updated = 0
    for country, confederation in OFFICIAL_2026_QUALIFIED_TEAMS:
        profile = db.scalar(
            select(WorldCupTeamProfile).where(
                WorldCupTeamProfile.tournament_year == 2026,
                WorldCupTeamProfile.team_name == country,
            )
        )
        is_update = profile is not None
        profile = profile or WorldCupTeamProfile(tournament_year=2026, team_name=country)
        profile.country = country
        profile.confederation = confederation
        profile.source = FIFA_2026_TEAMS_SOURCE
        profile.world_cup_strength_score = calculate_world_cup_strength_score(profile)
        profile.upset_alert_score = calculate_team_upset_alert(profile)
        db.add(profile)
        imported += int(not is_update)
        updated += int(is_update)
    db.commit()
    return ProfileImportSummary(imported=imported, updated=updated, skipped=0)


def _normalize(values: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, value) for value in values.values())
    if total <= 0:
        return {result: 1 / len(values) for result in values}
    return {result: max(0.0, value) / total for result, value in values.items()}


def _pick(probabilities: dict[str, float]) -> str:
    return max(probabilities, key=probabilities.get)


def _result(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "Home Win"
    if home_goals < away_goals:
        return "Away Win"
    return "Draw"


def _poisson_probability(lmbda: float, goals: int) -> float:
    return math.exp(-lmbda) * (lmbda**goals) / math.factorial(goals)


def _latest_base_prediction(db: Session, match_id: int) -> BacktestPrediction | None:
    return db.scalar(
        select(BacktestPrediction)
        .where(BacktestPrediction.match_id == match_id)
        .order_by(BacktestPrediction.run_id.desc(), BacktestPrediction.id.desc())
    )


def _profile(db: Session, year: int, team_name: str) -> WorldCupTeamProfile | None:
    return db.scalar(
        select(WorldCupTeamProfile).where(
            WorldCupTeamProfile.tournament_year == year,
            WorldCupTeamProfile.team_name == team_name,
        )
    )


def _base_probabilities(prediction: BacktestPrediction | None) -> dict[str, float]:
    if not prediction:
        return {"Home Win": 1 / 3, "Draw": 1 / 3, "Away Win": 1 / 3}
    return _normalize(
        {
            "Home Win": prediction.home_win_probability,
            "Draw": prediction.draw_probability,
            "Away Win": prediction.away_win_probability,
        }
    )


def _market_probabilities(odds: WorldCupOdds | None) -> dict[str, float] | None:
    if not odds:
        return None
    return _normalize(
        {
            "Home Win": 1 / odds.home_win_odds,
            "Draw": 1 / odds.draw_odds,
            "Away Win": 1 / odds.away_win_odds,
        }
    )


def _injury_penalty(profile: WorldCupTeamProfile | None) -> float:
    if not profile:
        return 0.0
    injuries = _safe_json(profile.key_injuries, [])
    if not isinstance(injuries, list):
        return 0.0
    penalty = 0.0
    for item in injuries:
        if isinstance(item, dict):
            severity = str(item.get("severity", "")).lower()
            is_core = bool(item.get("core_player", False))
            penalty += 0.035 if is_core else 0.015
            if severity in {"out", "major", "serious"}:
                penalty += 0.02
            elif severity in {"doubtful", "minor"}:
                penalty += 0.01
        else:
            penalty += 0.015
    return min(0.14, penalty)


def _lineup_score(profile: WorldCupTeamProfile | None) -> float | None:
    if not profile:
        return None
    starters = _safe_json(profile.projected_starting_xi, [])
    if not isinstance(starters, list) or not starters:
        return None
    return min(1.0, len(starters) / 11)


def _profile_coverage(profile: WorldCupTeamProfile | None) -> dict[str, bool]:
    if not profile:
        return {field: False for field in PROFILE_FIELDS}
    return {
        "country": bool(profile.country),
        "confederation": bool(profile.confederation),
        "fifa_ranking": profile.fifa_ranking is not None,
        "elo_rating": profile.elo_rating is not None,
        "projected_starting_xi": bool(_safe_json(profile.projected_starting_xi, [])),
        "key_injuries": bool(_safe_json(profile.key_injuries, [])),
        "squad_market_value_eur": profile.squad_market_value_eur is not None,
        "average_age": profile.average_age is not None,
        "total_caps": profile.total_caps is not None,
        "average_caps": profile.average_caps is not None,
        "world_cup_history_score": profile.world_cup_history_score is not None,
        "recent_two_year_rating": profile.recent_two_year_rating is not None,
        "coach": bool(profile.coach),
        "last_world_cup_finish": bool(profile.last_world_cup_finish),
    }


def _coverage_ratio(home_profile: WorldCupTeamProfile | None, away_profile: WorldCupTeamProfile | None) -> float:
    flags = list(_profile_coverage(home_profile).values()) + list(_profile_coverage(away_profile).values())
    return sum(flags) / len(flags) if flags else 0.0


def _safe_ratio(home: float | None, away: float | None, scale: float) -> float:
    if home is None or away is None:
        return 0.0
    return max(-1.0, min(1.0, (home - away) / scale))


def _scale_inverse_rank(rank: int | None) -> float | None:
    if rank is None:
        return None
    return max(0.0, min(100.0, 100 - (rank - 1) * 0.52))


def _scale_elo(elo: float | None) -> float | None:
    if elo is None:
        return None
    return max(0.0, min(100.0, (elo - 1200) / 900 * 100))


def _scale_market_value(value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.0, min(100.0, math.log1p(value) / math.log1p(1_400_000_000) * 100))


def _scale_experience(profile: WorldCupTeamProfile) -> float | None:
    values = []
    if profile.total_caps is not None:
        values.append(max(0.0, min(100.0, profile.total_caps / 900 * 100)))
    if profile.average_caps is not None:
        values.append(max(0.0, min(100.0, profile.average_caps / 55 * 100)))
    return sum(values) / len(values) if values else None


def _scale_unit(value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.0, min(100.0, value * 100 if value <= 1 else value))


def calculate_world_cup_strength_score(profile: WorldCupTeamProfile) -> float | None:
    components = {
        "elo": (_scale_elo(profile.elo_rating), 0.28),
        "fifa": (_scale_inverse_rank(profile.fifa_ranking), 0.22),
        "squad_value": (_scale_market_value(profile.squad_market_value_eur), 0.18),
        "experience": (_scale_experience(profile), 0.12),
        "world_cup_history": (_scale_unit(profile.world_cup_history_score), 0.10),
        "recent_form": (_scale_unit(profile.recent_two_year_rating), 0.10),
    }
    available = [(value, weight) for value, weight in components.values() if value is not None]
    if not available:
        return None
    total_weight = sum(weight for _, weight in available)
    return round(sum(value * weight for value, weight in available) / total_weight, 2)


def calculate_team_upset_alert(profile: WorldCupTeamProfile) -> str:
    score = profile.world_cup_strength_score
    confed_boost = profile.confederation in {"AFC", "CAF", "CONCACAF", "OFC"}
    nontraditional_conmebol = profile.confederation == "CONMEBOL" and profile.country not in {"Argentina", "Brazil", "Uruguay"}
    if score is None:
        return "Medium" if confed_boost or nontraditional_conmebol else "Low"
    if score >= 62:
        return "Low"
    if score >= 45:
        return "High" if confed_boost or nontraditional_conmebol else "Medium"
    return "High"


def _profile_strength_diff(home: WorldCupTeamProfile | None, away: WorldCupTeamProfile | None) -> tuple[float, dict]:
    if not home or not away:
        return 0.0, {"available": False}
    market_diff = 0.0
    if home.squad_market_value_eur and away.squad_market_value_eur:
        market_diff = max(-1.0, min(1.0, math.log(home.squad_market_value_eur / away.squad_market_value_eur) / 2.5))
    caps_diff = _safe_ratio(home.average_caps, away.average_caps, 55)
    history_diff = _safe_ratio(home.world_cup_history_score, away.world_cup_history_score, 1.0)
    recent_diff = _safe_ratio(home.recent_two_year_rating, away.recent_two_year_rating, 1.0)
    age_home = 0.0 if home.average_age is None else max(-1.0, min(1.0, (27.5 - abs(home.average_age - 27.5)) / 27.5))
    age_away = 0.0 if away.average_age is None else max(-1.0, min(1.0, (27.5 - abs(away.average_age - 27.5)) / 27.5))
    age_diff = age_home - age_away
    injury_diff = _injury_penalty(away) - _injury_penalty(home)
    lineup_diff = (_lineup_score(home) or 0.0) - (_lineup_score(away) or 0.0)
    diff = (
        market_diff * 0.28
        + caps_diff * 0.16
        + history_diff * 0.18
        + recent_diff * 0.24
        + age_diff * 0.05
        + injury_diff * 0.06
        + lineup_diff * 0.03
    )
    return max(-1.0, min(1.0, diff)), {
        "available": True,
        "market_value_diff": round(market_diff, 4),
        "caps_diff": round(caps_diff, 4),
        "history_diff": round(history_diff, 4),
        "recent_two_year_diff": round(recent_diff, 4),
        "age_profile_diff": round(age_diff, 4),
        "injury_diff": round(injury_diff, 4),
        "lineup_diff": round(lineup_diff, 4),
        "specialist_strength_diff": round(diff, 4),
    }


def _specialist_probabilities(strength_diff: float, stage: str) -> dict[str, float]:
    home_no_draw = 1 / (1 + math.exp(-3.2 * strength_diff))
    knockout = any(token in stage for token in ("Round of 16", "Quarter", "Semi", "Final", "Third"))
    draw = 0.25 + (0.03 if knockout else 0.0) - min(0.07, abs(strength_diff) * 0.08)
    draw = max(0.18, min(0.32, draw))
    return _normalize(
        {
            "Home Win": home_no_draw * (1 - draw),
            "Draw": draw,
            "Away Win": (1 - home_no_draw) * (1 - draw),
        }
    )


def _blend_probabilities(base: dict[str, float], specialist: dict[str, float] | None, market: dict[str, float] | None, coverage: float) -> tuple[dict[str, float], dict[str, float]]:
    weights = {"base_worldcup": 0.72}
    components = {"base_worldcup": base}
    if specialist and coverage > 0:
        weights["specialist_features"] = min(0.22, 0.10 + coverage * 0.18)
        components["specialist_features"] = specialist
    if market:
        weights["market_anchor"] = 0.08
        components["market_anchor"] = market
    total = sum(weights.values())
    weights = {key: value / total for key, value in weights.items()}
    final = {result: 0.0 for result in RESULTS}
    for name, probabilities in components.items():
        for result in RESULTS:
            final[result] += probabilities[result] * weights[name]
    return _normalize(final), weights


def _score_matrix(probabilities: dict[str, float], strength_diff: float, stage: str) -> list[dict]:
    knockout = any(token in stage for token in ("Round of 16", "Quarter", "Semi", "Final", "Third"))
    total_goals = 2.35 - (0.12 if knockout else 0.0) + min(0.35, abs(strength_diff) * 0.28)
    home_share = 0.5 + max(-0.22, min(0.22, (probabilities["Home Win"] - probabilities["Away Win"]) * 0.55))
    home_lambda = max(0.25, min(3.8, total_goals * home_share))
    away_lambda = max(0.25, min(3.8, total_goals * (1 - home_share)))
    rows = []
    rho = -0.08
    for home_goals in range(6):
        for away_goals in range(6):
            probability = _poisson_probability(home_lambda, home_goals) * _poisson_probability(away_lambda, away_goals)
            if home_goals == 0 and away_goals == 0:
                probability *= 1 - home_lambda * away_lambda * rho
            elif home_goals == 0 and away_goals == 1:
                probability *= 1 + home_lambda * rho
            elif home_goals == 1 and away_goals == 0:
                probability *= 1 + away_lambda * rho
            elif home_goals == 1 and away_goals == 1:
                probability *= 1 - rho
            rows.append(
                {
                    "score": f"{home_goals}-{away_goals}",
                    "home_goals": home_goals,
                    "away_goals": away_goals,
                    "probability": max(0.0, probability),
                }
            )
    total = sum(row["probability"] for row in rows)
    for row in rows:
        row["probability"] = row["probability"] / total if total else 0.0
    return sorted(rows, key=lambda row: row["probability"], reverse=True)


def _top_scores_for_pick(scores: list[dict], pick: str, limit: int = 3) -> list[dict]:
    aligned = [
        row for row in scores
        if _result(row["home_goals"], row["away_goals"]) == pick
    ]
    candidates = aligned or scores
    return candidates[:limit]


def _upset_warning(probabilities: dict[str, float], market: dict[str, float] | None, strength_diff: float) -> dict:
    favorite = "Home Win" if strength_diff >= 0 else "Away Win"
    underdog = "Away Win" if favorite == "Home Win" else "Home Win"
    upset_probability = probabilities[underdog]
    if market:
        market_favorite = _pick(market)
        market_underdog = "Away Win" if market_favorite == "Home Win" else "Home Win"
        if market_favorite in ("Home Win", "Away Win"):
            underdog = market_underdog
            upset_probability = probabilities[underdog]
    risk = "low"
    if upset_probability >= 0.34:
        risk = "high"
    elif upset_probability >= 0.27:
        risk = "medium"
    return {
        "risk": risk,
        "upset_pick": underdog,
        "upset_probability": round(upset_probability * 100, 2),
        "avoid_threshold": "建议 medium 以上降低仓位，high 直接避开",
    }


def predict_world_cup_specialist(db: Session, match_id: int) -> dict:
    match = db.get(WorldCupMatch, match_id)
    if not match:
        return {"error": "World Cup match not found"}
    base_prediction = _latest_base_prediction(db, match.id)
    odds = db.scalar(select(WorldCupOdds).where(WorldCupOdds.match_id == match.id))
    home_profile = _profile(db, match.tournament_year, match.home_team)
    away_profile = _profile(db, match.tournament_year, match.away_team)
    coverage = _coverage_ratio(home_profile, away_profile)
    strength_diff, feature_breakdown = _profile_strength_diff(home_profile, away_profile)
    specialist_component = _specialist_probabilities(strength_diff, match.stage) if coverage > 0 else None
    market_component = _market_probabilities(odds)
    probabilities, weights = _blend_probabilities(
        _base_probabilities(base_prediction),
        specialist_component,
        market_component,
        coverage,
    )
    scores = _score_matrix(probabilities, strength_diff, match.stage)
    specialist_pick = _pick(probabilities)
    top_scores = _top_scores_for_pick(scores, specialist_pick)
    return {
        "match_id": match.id,
        "tournament_year": match.tournament_year,
        "stage": match.stage,
        "home_team": match.home_team,
        "away_team": match.away_team,
        "specialist_probabilities": {key: round(value * 100, 2) for key, value in probabilities.items()},
        "specialist_pick": specialist_pick,
        "specialist_score_model": {
            "top_score": top_scores[0]["score"],
            "top_score_probability": round(top_scores[0]["probability"] * 100, 2),
            "top3_scores": [
                {"score": row["score"], "probability": round(row["probability"] * 100, 2)}
                for row in top_scores
            ],
        },
        "upset_warning": _upset_warning(probabilities, market_component, strength_diff),
        "feature_coverage": {
            "coverage_ratio": round(coverage * 100, 2),
            "home": _profile_coverage(home_profile),
            "away": _profile_coverage(away_profile),
        },
        "data_confidence": assess_match_data_confidence(match, home_profile, away_profile, odds),
        "model_weights": weights,
        "feature_breakdown": feature_breakdown,
        "data_policy": "No mock data. Missing specialist features are marked unavailable and are not fabricated.",
    }


def specialist_coverage_report(db: Session, years: list[int] | None = None) -> dict:
    if years == [2026]:
        profiles = db.scalars(
            select(WorldCupTeamProfile)
            .where(WorldCupTeamProfile.tournament_year == 2026)
            .order_by(WorldCupTeamProfile.confederation.asc(), WorldCupTeamProfile.country.asc())
        ).all()
        rows = []
        by_confederation = {
            confed: {"teams": 0, "completed": 0, "missing_fields": 0}
            for confed in CONFEDERATIONS
        }
        for profile in profiles:
            coverage = _profile_coverage(profile)
            missing = [field for field, present in coverage.items() if not present]
            completed = len(missing) == 0
            confed = profile.confederation or "UNKNOWN"
            by_confederation.setdefault(confed, {"teams": 0, "completed": 0, "missing_fields": 0})
            by_confederation[confed]["teams"] += 1
            by_confederation[confed]["completed"] += int(completed)
            by_confederation[confed]["missing_fields"] += len(missing)
            rows.append(
                {
                    "country": profile.country or profile.team_name,
                    "confederation": confed,
                    "world_cup_strength_score": profile.world_cup_strength_score,
                    "upset_alert_score": profile.upset_alert_score,
                    "missing_fields": missing,
                    "missing_field_count": len(missing),
                }
            )
        completed_count = sum(1 for row in rows if row["missing_field_count"] == 0)
        return {
            "planning_scope": {"teams": EXPECTED_2026_TEAMS, "matches": EXPECTED_2026_MATCHES},
            "total_teams": len(rows),
            "expected_teams": EXPECTED_2026_TEAMS,
            "completed_teams": completed_count,
            "coverage_rate": round(completed_count / EXPECTED_2026_TEAMS * 100, 2) if EXPECTED_2026_TEAMS else 0.0,
            "missing_field_total": sum(row["missing_field_count"] for row in rows),
            "by_confederation": by_confederation,
            "rows": rows,
        }

    query = select(WorldCupMatch).order_by(WorldCupMatch.tournament_year.asc(), WorldCupMatch.id.asc())
    if years:
        query = query.where(WorldCupMatch.tournament_year.in_(years))
    matches = db.scalars(query).all()
    rows = []
    for match in matches:
        home_profile = _profile(db, match.tournament_year, match.home_team)
        away_profile = _profile(db, match.tournament_year, match.away_team)
        rows.append(
            {
                "match_id": match.id,
                "year": match.tournament_year,
                "home_team": match.home_team,
                "away_team": match.away_team,
                "coverage_ratio": round(_coverage_ratio(home_profile, away_profile) * 100, 2),
            }
        )
    covered = [row for row in rows if row["coverage_ratio"] > 0]
    return {
        "matches": len(rows),
        "matches_with_specialist_profile": len(covered),
        "coverage_rate": round(len(covered) / len(rows) * 100, 2) if rows else 0.0,
        "required_profile_fields": list(PROFILE_FIELDS),
        "rows": rows,
    }


def simulate_world_cup_2026(db: Session, simulations: int = 1000) -> dict:
    profiles = db.scalars(
        select(WorldCupTeamProfile)
        .where(WorldCupTeamProfile.tournament_year == 2026)
        .order_by(WorldCupTeamProfile.country.asc())
    ).all()
    fixtures = db.scalars(
        select(WorldCupMatch)
        .where(WorldCupMatch.tournament_year == 2026)
        .where(WorldCupMatch.stage.ilike("%Group%"))
        .order_by(WorldCupMatch.match_date.asc(), WorldCupMatch.id.asc())
    ).all()
    if len(profiles) < EXPECTED_2026_TEAMS or len(fixtures) < 72:
        return {
            "status": "insufficient_data",
            "reason": "需要 48 支球队画像和完整小组赛赛程后才能进行真实模拟；当前不生成 mock 赛程。",
            "teams_available": len(profiles),
            "group_fixtures_available": len(fixtures),
            "required_teams": EXPECTED_2026_TEAMS,
            "required_group_fixtures": 72,
            "probabilities": {},
        }
    return {
        "status": "not_implemented_for_incomplete_bracket",
        "reason": "小组赛和淘汰赛晋级规则接口已预留；待完整 2026 分组赛程入库后运行 Monte Carlo。",
        "simulations": simulations,
        "probabilities": {
            profile.country or profile.team_name: {
                "group_qualification": 0.0,
                "round_of_16": 0.0,
                "quarter_final": 0.0,
                "semi_final": 0.0,
                "final": 0.0,
                "champion": 0.0,
            }
            for profile in profiles
        },
    }


def write_specialist_report(db: Session, years: list[int] | None = None) -> dict:
    target_years = years or [2026]
    coverage = specialist_coverage_report(db, target_years)
    backtest_run = db.scalar(
        select(BacktestRun)
        .where(BacktestRun.years == "2018,2022")
        .order_by(BacktestRun.created_at.desc(), BacktestRun.id.desc())
    )
    backtest_predictions = []
    if backtest_run:
        backtest_predictions = db.scalars(
            select(BacktestPrediction).where(BacktestPrediction.run_id == backtest_run.id)
        ).all()
    result_hits = sum(row.result_hit for row in backtest_predictions)
    draw_rows = [row for row in backtest_predictions if row.actual_result == "Draw"]
    draw_hits = sum(row.result_hit for row in draw_rows)
    score_hits = sum(row.score_hit for row in backtest_predictions)
    brier = sum(row.brier_score for row in backtest_predictions) / len(backtest_predictions) if backtest_predictions else None
    reports_dir = Path(__file__).resolve().parents[2] / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "phase7_worldcup_specialist_full_report.md"
    is_2026 = target_years == [2026]
    lines = [
        "# Phase 7 World Cup Specialist Full Report",
        "",
        "## 范围",
        "",
        "- 只针对世界杯正赛。",
        "- 不优化五大联赛、不优化预选赛、不以跨赛事 ROI 为主要目标。",
        "- 不生成 mock 数据；首发、伤病、身价、年龄、国家队经验等必须来自 `world_cup_team_profiles`。",
        f"- 长期规划规模：{EXPECTED_2026_TEAMS} 支球队，{EXPECTED_2026_MATCHES} 场比赛。",
        "",
        "## 2026 球队画像覆盖率",
        "",
        f"- 总球队数：{coverage.get('total_teams', coverage.get('matches', 0))}",
        f"- 预期球队数：{coverage.get('expected_teams', EXPECTED_2026_TEAMS) if is_2026 else 'N/A'}",
        f"- 已完成球队数：{coverage.get('completed_teams', coverage.get('matches_with_specialist_profile', 0))}",
        f"- 覆盖率：{coverage['coverage_rate']}%",
        f"- 缺失字段数量：{coverage.get('missing_field_total', 'N/A')}",
        "",
        "### 按大洲统计",
        "",
        "| 大洲 | 球队数 | 已完成 | 缺失字段数 |",
        "|---|---:|---:|---:|",
    ]
    if is_2026:
        for confed in CONFEDERATIONS:
            row = coverage["by_confederation"].get(confed, {"teams": 0, "completed": 0, "missing_fields": 0})
            lines.append(f"| {confed} | {row['teams']} | {row['completed']} | {row['missing_fields']} |")
    lines.extend(
        [
            "",
            "## 球队实力评分",
            "",
            "- `world_cup_strength_score` 输出 0-100。",
            "- 组成：ELO、FIFA Ranking、Squad Value、National Team Experience、World Cup History、Recent Form。",
            "- 缺失组件不参与计算，并记录到缺失字段。",
            "",
            "## 冷门预警模型",
            "",
            "- `upset_alert_score` 输出 Low / Medium / High。",
            "- 亚洲、非洲、中北美、OFC 以及南美非传统强队会被重点关注。",
            "",
            "## 世界杯模拟能力",
            "",
        ]
    )
    simulation_status = simulate_world_cup_2026(db, simulations=1000)
    lines.extend(
        [
            f"- 状态：{simulation_status['status']}",
            f"- 原因：{simulation_status['reason']}",
            f"- 当前球队画像：{simulation_status.get('teams_available', 'N/A')}",
            f"- 当前小组赛赛程：{simulation_status.get('group_fixtures_available', 'N/A')}",
            "",
            "## 2018/2022 世界杯专项回测",
            "",
            f"- 回测样本：{len(backtest_predictions)}",
            f"- 胜平负命中率：{round(result_hits / len(backtest_predictions) * 100, 2) if backtest_predictions else None}%",
            f"- 平局命中率：{round(draw_hits / len(draw_rows) * 100, 2) if draw_rows else None}%",
            f"- 比分命中率：{round(score_hits / len(backtest_predictions) * 100, 2) if backtest_predictions else None}%",
            f"- Brier Score：{round(brier, 4) if brier is not None else None}",
            "- 是否优于当前 55.47%：当前没有 2018/2022 专项画像数据，不能声称专项模型已优于 55.47%。",
            "",
            "## 已支持输出",
            "",
            "- 48 队世界杯球队画像库",
            "- 世界杯专用预测概率",
            "- 世界杯专用比分模型",
            "- 世界杯专用冷门预警",
            "- 球队画像覆盖率报告",
            "- 世界杯模拟接口，等待完整小组赛赛程后启用真实 Monte Carlo",
            "",
        ]
    )
    if is_2026:
        lines.extend(["## 2026 球队缺失字段明细", "", "| 国家 | 大洲 | 强度评分 | 冷门等级 | 缺失字段数 |", "|---|---|---:|---|---:|"])
        for row in coverage["rows"]:
            lines.append(
                f"| {row['country']} | {row['confederation']} | {row['world_cup_strength_score']} | "
                f"{row['upset_alert_score']} | {row['missing_field_count']} |"
            )
    lines.extend([
        "",
    ])
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return {"report_path": str(report_path), "coverage": coverage}
