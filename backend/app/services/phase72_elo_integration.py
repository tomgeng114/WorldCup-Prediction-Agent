from __future__ import annotations

import csv
import json
import re
import unicodedata
import urllib.request
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import WorldCupTeamProfile
from app.services.phase71_data_acquisition import OUTPUT_CSV
from app.services.world_cup_specialist import (
    calculate_team_upset_alert,
    calculate_world_cup_strength_score,
)


ELO_WORLD_URL = "https://eloratings.net/World.tsv"
ELO_TEAMS_URL = "https://eloratings.net/en.teams.tsv"
REQUIRED_FIELDS = (
    "fifa_ranking",
    "elo_rating",
    "squad_market_value_eur",
    "average_age",
    "total_caps",
    "average_caps",
    "coach",
    "last_world_cup_finish",
    "recent_two_year_rating",
)
NAME_ALIASES = {
    "USA": "United States",
    "United States": "USA",
    "IR Iran": "Iran",
    "Iran": "IR Iran",
    "Korea Republic": "South Korea",
    "South Korea": "Korea Republic",
    "Cote d'Ivoire": "Ivory Coast",
    "Côte d'Ivoire": "Ivory Coast",
    "Ivory Coast": "Cote d'Ivoire",
    "Curacao": "Curaçao",
    "Curaçao": "Curacao",
    "Turkiye": "Türkiye",
    "Türkiye": "Turkiye",
    "Turkey": "Turkiye",
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "Cabo Verde": "Cape Verde",
    "Cape Verde": "Cabo Verde",
    "DR Congo": "Congo DR",
    "Congo DR": "DR Congo",
}


def _normalize_name(name: str) -> str:
    text = str(name).replace(" ", " ").replace("&", "and").strip()
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    text = text.replace("'", "").replace("-", " ")
    return re.sub(r"\s+", " ", text).lower()


def _lookup_keys(name: str) -> set[str]:
    keys = {_normalize_name(name), _normalize_name(NAME_ALIASES.get(name, name))}
    for alias_key, alias_value in NAME_ALIASES.items():
        if _normalize_name(alias_key) in keys or _normalize_name(alias_value) in keys:
            keys.add(_normalize_name(alias_key))
            keys.add(_normalize_name(alias_value))
    return keys


def _fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="ignore")


def _elo_team_names() -> dict[str, list[str]]:
    rows = {}
    for line in _fetch_text(ELO_TEAMS_URL).splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        code = parts[0]
        rows[code] = [value for value in parts[1:] if value]
    return rows


def _elo_ratings_by_name() -> dict[str, float]:
    code_names = _elo_team_names()
    ratings = {}
    for line in _fetch_text(ELO_WORLD_URL).splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        code = parts[2]
        try:
            elo = float(parts[3])
        except ValueError:
            continue
        for name in code_names.get(code, []):
            ratings[_normalize_name(name)] = elo
    return ratings


def _profile_missing_fields(profile: WorldCupTeamProfile) -> list[str]:
    return [
        field for field in REQUIRED_FIELDS
        if getattr(profile, field) in (None, "")
    ]


def _regenerate_csv(data_dir: Path, profiles: list[WorldCupTeamProfile]) -> Path:
    path = data_dir / OUTPUT_CSV
    fieldnames = [
        "tournament_year",
        "team_name",
        "country",
        "confederation",
        "fifa_ranking",
        "elo_rating",
        "squad_market_value_eur",
        "average_age",
        "total_caps",
        "average_caps",
        "world_cup_history_score",
        "recent_two_year_rating",
        "projected_starting_xi",
        "key_injuries",
        "coach",
        "last_world_cup_finish",
        "source",
        "captured_at",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for profile in profiles:
            writer.writerow(
                {
                    "tournament_year": profile.tournament_year,
                    "team_name": profile.team_name,
                    "country": profile.country,
                    "confederation": profile.confederation,
                    "fifa_ranking": profile.fifa_ranking or "",
                    "elo_rating": profile.elo_rating or "",
                    "squad_market_value_eur": profile.squad_market_value_eur or "",
                    "average_age": profile.average_age or "",
                    "total_caps": profile.total_caps or "",
                    "average_caps": profile.average_caps or "",
                    "world_cup_history_score": profile.world_cup_history_score or "",
                    "recent_two_year_rating": profile.recent_two_year_rating or "",
                    "projected_starting_xi": profile.projected_starting_xi,
                    "key_injuries": profile.key_injuries,
                    "coach": profile.coach,
                    "last_world_cup_finish": profile.last_world_cup_finish,
                    "source": profile.source,
                    "captured_at": profile.captured_at.isoformat() if profile.captured_at else "",
                }
            )
    return path


def _coverage_payload(profiles: list[WorldCupTeamProfile], csv_path: Path) -> dict:
    rows = []
    present_total = 0
    field_total = len(REQUIRED_FIELDS) * len(profiles)
    complete = 0
    for profile in profiles:
        missing = _profile_missing_fields(profile)
        present = len(REQUIRED_FIELDS) - len(missing)
        present_total += present
        complete += int(not missing)
        rows.append(
            {
                "country": profile.country or profile.team_name,
                "confederation": profile.confederation,
                "present_fields": present,
                "missing_fields": missing,
            }
        )
    return {
        "total_teams": len(profiles),
        "completed_teams": complete,
        "team_completion_rate": round(complete / len(profiles) * 100, 2) if profiles else 0.0,
        "field_coverage_rate": round(present_total / field_total * 100, 2) if field_total else 0.0,
        "elo_coverage_rate": round(
            sum(profile.elo_rating is not None for profile in profiles) / len(profiles) * 100,
            2,
        ) if profiles else 0.0,
        "strength_score_coverage_rate": round(
            sum(profile.world_cup_strength_score is not None for profile in profiles) / len(profiles) * 100,
            2,
        ) if profiles else 0.0,
        "target_field_coverage_rate": 90.0,
        "target_reached": (present_total / field_total >= 0.90) if field_total else False,
        "missing_fields": rows,
        "source_status": {
            "elo_rating": ELO_WORLD_URL,
            "elo_team_dictionary": ELO_TEAMS_URL,
        },
        "csv_path": str(csv_path),
    }


def run_phase72_elo_integration(db: Session) -> dict:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    reports_dir = Path(__file__).resolve().parents[2] / "reports"
    data_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    ratings = _elo_ratings_by_name()

    profiles = db.scalars(
        select(WorldCupTeamProfile)
        .where(WorldCupTeamProfile.tournament_year == 2026)
        .order_by(WorldCupTeamProfile.country.asc())
    ).all()
    matched = 0
    unmatched = []
    for profile in profiles:
        elo = None
        for key in _lookup_keys(profile.country or profile.team_name):
            if key in ratings:
                elo = ratings[key]
                break
        if elo is None:
            unmatched.append(profile.country or profile.team_name)
            continue
        profile.elo_rating = elo
        profile.world_cup_strength_score = calculate_world_cup_strength_score(profile)
        profile.upset_alert_score = calculate_team_upset_alert(profile)
        if ELO_WORLD_URL not in profile.source:
            profile.source = f"{profile.source}; {ELO_WORLD_URL}".strip("; ")
        db.add(profile)
        matched += 1
    db.commit()

    profiles = db.scalars(
        select(WorldCupTeamProfile)
        .where(WorldCupTeamProfile.tournament_year == 2026)
        .order_by(WorldCupTeamProfile.country.asc())
    ).all()
    csv_path = _regenerate_csv(data_dir, profiles)
    coverage = _coverage_payload(profiles, csv_path)
    coverage_path = reports_dir / "coverage_report.json"
    coverage_path.write_text(json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8")

    report_path = reports_dir / "phase72_elo_report.md"
    lines = [
        "# Phase 7.2 ELO Integration Report",
        "",
        "## 数据源",
        "",
        f"- World Football Elo Ratings：{ELO_WORLD_URL}",
        f"- Team dictionary：{ELO_TEAMS_URL}",
        "",
        "## 验证结果",
        "",
        f"- 2026 球队数：{len(profiles)}",
        f"- ELO 匹配球队数：{matched}",
        f"- ELO 覆盖率：{coverage['elo_coverage_rate']}%",
        f"- Strength Score 覆盖率：{coverage['strength_score_coverage_rate']}%",
        f"- 最终字段覆盖率：{coverage['field_coverage_rate']}%",
        f"- 90% 字段覆盖目标是否达到：{coverage['target_reached']}",
        "",
        "## 未匹配球队",
        "",
    ]
    if unmatched:
        lines.extend(f"- {name}" for name in unmatched)
    else:
        lines.append("- 无")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    coverage["matched"] = matched
    coverage["unmatched"] = unmatched
    coverage["coverage_path"] = str(coverage_path)
    coverage["report_path"] = str(report_path)
    return coverage
