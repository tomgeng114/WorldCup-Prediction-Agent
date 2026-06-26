from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import WorldCupMatch, WorldCupOdds, WorldCupTeamProfile


REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"
TEAM_CONFIDENCE_JSON = REPORTS_DIR / "phase82_data_confidence_report.json"
TEAM_CONFIDENCE_MD = REPORTS_DIR / "phase82_data_confidence_report.md"


def _safe_json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def _field(present: bool, points: float, label: str) -> dict:
    return {"label": label, "present": bool(present), "points": points if present else 0.0, "max_points": points}


def assess_team_profile_confidence(profile: WorldCupTeamProfile | None) -> dict:
    if not profile:
        return {
            "team": None,
            "score": 0.0,
            "level": "Critical",
            "suggested_action": "跳过推荐：缺少球队画像。",
            "missing_fields": ["team_profile"],
            "components": [],
        }

    components = [
        _field(bool(profile.country), 3, "country"),
        _field(bool(profile.confederation), 3, "confederation"),
        _field(profile.elo_rating is not None, 14, "elo_rating"),
        _field(profile.fifa_ranking is not None, 10, "fifa_ranking"),
        _field(profile.world_cup_strength_score is not None, 10, "world_cup_strength_score"),
        _field(profile.squad_market_value_eur is not None, 8, "squad_market_value_eur"),
        _field(profile.recent_two_year_rating is not None, 8, "recent_two_year_rating"),
        _field(profile.world_cup_history_score is not None, 6, "world_cup_history_score"),
        _field(profile.average_age is not None, 4, "average_age"),
        _field(profile.total_caps is not None, 4, "total_caps"),
        _field(profile.average_caps is not None, 4, "average_caps"),
        _field(bool(profile.coach), 3, "coach"),
        _field(bool(profile.last_world_cup_finish), 3, "last_world_cup_finish"),
        _field(bool(_safe_json_list(profile.projected_starting_xi)), 10, "projected_starting_xi"),
        _field(bool(_safe_json_list(profile.key_injuries)), 10, "key_injuries"),
    ]
    score = round(sum(item["points"] for item in components), 2)
    missing = [item["label"] for item in components if not item["present"]]
    return {
        "team": profile.country or profile.team_name,
        "confederation": profile.confederation,
        "score": score,
        "level": _confidence_level(score),
        "suggested_action": _suggested_action(score),
        "missing_fields": missing,
        "components": components,
        "source": profile.source,
        "captured_at": profile.captured_at.isoformat() if profile.captured_at else None,
    }


def assess_match_data_confidence(
    match: WorldCupMatch,
    home_profile: WorldCupTeamProfile | None,
    away_profile: WorldCupTeamProfile | None,
    odds: WorldCupOdds | None,
) -> dict:
    home = assess_team_profile_confidence(home_profile)
    away = assess_team_profile_confidence(away_profile)
    team_score = (home["score"] + away["score"]) / 2
    odds_score, odds_missing = _odds_confidence(odds)
    freshness_score, freshness_missing = _freshness_confidence(home_profile, away_profile, odds)
    score = round(team_score * 0.72 + odds_score * 0.20 + freshness_score * 0.08, 2)
    missing = sorted(set(home["missing_fields"] + away["missing_fields"] + odds_missing + freshness_missing))
    return {
        "match_id": match.id,
        "home_team": match.home_team,
        "away_team": match.away_team,
        "score": score,
        "level": _confidence_level(score),
        "suggested_action": _suggested_action(score),
        "confidence_adjustment_factor": _confidence_adjustment_factor(score),
        "missing_fields": missing,
        "home_team_confidence": home,
        "away_team_confidence": away,
        "odds_confidence": {
            "score": odds_score,
            "missing_fields": odds_missing,
            "has_1x2_odds": odds is not None and all(
                value and value > 0 for value in (
                    odds.home_win_odds if odds else None,
                    odds.draw_odds if odds else None,
                    odds.away_win_odds if odds else None,
                )
            ),
            "has_handicap_odds": odds is not None and odds.handicap is not None,
        },
        "freshness_confidence": {
            "score": freshness_score,
            "missing_fields": freshness_missing,
        },
        "policy": "Data confidence is advisory only and does not modify model probabilities.",
    }


def write_team_data_confidence_report(db: Session, year: int = 2026) -> dict:
    profiles = db.scalars(
        select(WorldCupTeamProfile)
        .where(WorldCupTeamProfile.tournament_year == year)
        .order_by(WorldCupTeamProfile.confederation.asc(), WorldCupTeamProfile.country.asc())
    ).all()
    rows = [assess_team_profile_confidence(profile) for profile in profiles]
    rows.sort(key=lambda row: (row["score"], row["team"] or ""), reverse=True)
    total = len(rows)
    by_level = {
        level: sum(1 for row in rows if row["level"] == level)
        for level in ("High", "Medium", "Low", "Critical")
    }
    by_confederation: dict[str, dict] = {}
    for row in rows:
        confed = row.get("confederation") or "UNKNOWN"
        bucket = by_confederation.setdefault(confed, {"teams": 0, "average_score": 0.0, "scores": []})
        bucket["teams"] += 1
        bucket["scores"].append(row["score"])
    for bucket in by_confederation.values():
        scores = bucket.pop("scores")
        bucket["average_score"] = round(sum(scores) / len(scores), 2) if scores else 0.0

    payload = {
        "status": "ok",
        "year": year,
        "total_teams": total,
        "average_score": round(sum(row["score"] for row in rows) / total, 2) if total else 0.0,
        "by_level": by_level,
        "by_confederation": by_confederation,
        "lowest_confidence_teams": sorted(rows, key=lambda row: row["score"])[:10],
        "highest_confidence_teams": rows[:10],
        "rows": rows,
        "policy": "No mock data. Missing fields lower confidence and remain visible.",
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    TEAM_CONFIDENCE_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(TEAM_CONFIDENCE_MD, payload)
    payload["json_path"] = str(TEAM_CONFIDENCE_JSON)
    payload["report_path"] = str(TEAM_CONFIDENCE_MD)
    return payload


def _odds_confidence(odds: WorldCupOdds | None) -> tuple[float, list[str]]:
    if not odds:
        return 0.0, ["world_cup_odds"]
    components = [
        _field(odds.home_win_odds > 0 and odds.draw_odds > 0 and odds.away_win_odds > 0, 60, "1x2_odds"),
        _field(odds.handicap is not None, 15, "handicap"),
        _field(odds.handicap_home_odds is not None or odds.handicap_away_odds is not None, 10, "handicap_odds"),
        _field(odds.captured_at is not None, 15, "odds_captured_at"),
    ]
    score = round(sum(item["points"] for item in components), 2)
    missing = [item["label"] for item in components if not item["present"]]
    return score, missing


def _freshness_confidence(
    home_profile: WorldCupTeamProfile | None,
    away_profile: WorldCupTeamProfile | None,
    odds: WorldCupOdds | None,
) -> tuple[float, list[str]]:
    timestamps = [
        profile.captured_at
        for profile in (home_profile, away_profile)
        if profile and profile.captured_at is not None
    ]
    if odds and odds.captured_at is not None:
        timestamps.append(odds.captured_at)
    if not timestamps:
        return 0.0, ["captured_at"]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    newest_days = min(max((now - timestamp).days, 0) for timestamp in timestamps)
    if newest_days <= 30:
        return 100.0, []
    if newest_days <= 90:
        return 80.0, []
    if newest_days <= 180:
        return 55.0, []
    return 35.0, ["fresh_data_within_180_days"]


def _confidence_level(score: float) -> str:
    if score >= 80:
        return "High"
    if score >= 60:
        return "Medium"
    if score >= 40:
        return "Low"
    return "Critical"


def _confidence_adjustment_factor(score: float) -> float:
    if score >= 80:
        return 1.0
    if score >= 60:
        return 0.85
    if score >= 40:
        return 0.65
    return 0.5


def _suggested_action(score: float) -> str:
    if score >= 80:
        return "可正常使用预测，但仍需关注临场阵容。"
    if score >= 60:
        return "可预测，推荐降低信心和投注权重。"
    if score >= 40:
        return "只展示预测，不建议进入推荐列表。"
    return "跳过推荐，等待关键数据补齐。"


def _write_markdown(path: Path, payload: dict) -> None:
    lines = [
        "# Phase 8.2 Data Confidence Report",
        "",
        "## Scope",
        "",
        f"- Year: {payload['year']}",
        f"- Teams: {payload['total_teams']}",
        f"- Average data confidence score: {payload['average_score']}",
        "- Policy: no mock data; missing fields lower confidence and remain visible.",
        "",
        "## Level Summary",
        "",
        "| Level | Teams |",
        "|---|---:|",
    ]
    for level, count in payload["by_level"].items():
        lines.append(f"| {level} | {count} |")
    lines.extend(
        [
            "",
            "## Confederation Summary",
            "",
            "| Confederation | Teams | Average Score |",
            "|---|---:|---:|",
        ]
    )
    for confed, row in sorted(payload["by_confederation"].items()):
        lines.append(f"| {confed} | {row['teams']} | {row['average_score']} |")
    _append_team_table(lines, "Lowest Confidence Teams", payload["lowest_confidence_teams"])
    _append_team_table(lines, "Highest Confidence Teams", payload["highest_confidence_teams"])
    path.write_text("\n".join(lines), encoding="utf-8")


def _append_team_table(lines: list[str], title: str, rows: list[dict]) -> None:
    lines.extend(
        [
            "",
            f"## {title}",
            "",
            "| Team | Confed | Score | Level | Missing Fields | Suggested Action |",
            "|---|---|---:|---|---|---|",
        ]
    )
    for row in rows:
        missing = ", ".join(row["missing_fields"]) if row["missing_fields"] else "-"
        lines.append(
            f"| {row['team']} | {row.get('confederation') or '-'} | {row['score']} | "
            f"{row['level']} | {missing} | {row['suggested_action']} |"
        )
