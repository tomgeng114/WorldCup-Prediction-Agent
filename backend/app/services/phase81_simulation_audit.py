from __future__ import annotations

import json
from pathlib import Path
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import WorldCupTeamProfile


REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"
PHASE8_REPORT_PATH = REPORTS_DIR / "phase8_simulation_report.json"
PHASE81_JSON_PATH = REPORTS_DIR / "phase81_simulation_audit_report.json"
PHASE81_MD_PATH = REPORTS_DIR / "phase81_simulation_audit_report.md"
RANK_DELTA_THRESHOLD = 8
CONFEDERATIONS = ["UEFA", "CONMEBOL", "AFC", "CAF", "CONCACAF", "OFC"]


def run_phase81_simulation_audit(db: Session) -> dict:
    if not PHASE8_REPORT_PATH.exists():
        return {
            "status": "missing_phase8_report",
            "error": f"Phase 8 simulation report not found: {PHASE8_REPORT_PATH}",
        }

    phase8 = json.loads(PHASE8_REPORT_PATH.read_text(encoding="utf-8"))
    if phase8.get("status") != "ok":
        return {
            "status": "invalid_phase8_report",
            "phase8_status": phase8.get("status"),
            "error": "Phase 8 report must be status=ok before audit.",
        }

    profile_map = _load_profile_map(db)
    rows = _build_rank_rows(phase8, profile_map)
    confederation_summary = _confederation_summary(rows)
    overrated, underrated = _detect_rank_anomalies(rows)

    payload = {
        "status": "ok",
        "audit_policy": "Audit only; no model parameters, strengths, or simulation logic were modified.",
        "input_report": str(PHASE8_REPORT_PATH),
        "simulations": phase8.get("simulations"),
        "pre_draw_simulation": phase8.get("pre_draw_simulation"),
        "real_schedule_simulation": phase8.get("real_schedule_simulation"),
        "schedule_source": phase8.get("schedule_source"),
        "rank_delta_threshold": RANK_DELTA_THRESHOLD,
        "top20_champion_probability": _top20(rows, "champion_probability"),
        "top20_final_probability": _top20(rows, "final_probability"),
        "top20_semi_final_probability": _top20(rows, "semi_final_probability"),
        "top20_quarter_final_probability": _top20(rows, "quarter_final_probability"),
        "top20_group_qualification_probability": _top20(rows, "group_qualification_probability"),
        "confederation_champion_probability": confederation_summary,
        "overrated_teams": overrated,
        "underrated_teams": underrated,
        "rank_audit_rows": rows,
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    PHASE81_JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(PHASE81_MD_PATH, payload)
    payload["json_path"] = str(PHASE81_JSON_PATH)
    payload["report_path"] = str(PHASE81_MD_PATH)
    return payload


def _load_profile_map(db: Session) -> dict[str, dict]:
    profiles = db.scalars(
        select(WorldCupTeamProfile).where(WorldCupTeamProfile.tournament_year == 2026)
    ).all()
    return {
        profile.country or profile.team_name: {
            "confederation": profile.confederation or "UNKNOWN",
            "strength_score": float(profile.world_cup_strength_score or 0),
        }
        for profile in profiles
    }


def _build_rank_rows(phase8: dict, profile_map: dict[str, dict]) -> list[dict]:
    probabilities = list(phase8.get("probabilities") or [])
    strength_sorted = sorted(
        probabilities,
        key=lambda row: (
            float(row.get("strength_score") or 0),
            float(row.get("champion_probability") or 0),
        ),
        reverse=True,
    )
    champion_sorted = sorted(
        probabilities,
        key=lambda row: (
            float(row.get("champion_probability") or 0),
            float(row.get("final_probability") or 0),
            float(row.get("strength_score") or 0),
        ),
        reverse=True,
    )
    strength_rank = {row["country"]: index for index, row in enumerate(strength_sorted, start=1)}
    champion_rank = {row["country"]: index for index, row in enumerate(champion_sorted, start=1)}

    rows = []
    for row in champion_sorted:
        country = row["country"]
        profile = profile_map.get(country, {})
        rank_delta = strength_rank[country] - champion_rank[country]
        rows.append(
            {
                "country": country,
                "confederation": profile.get("confederation", "UNKNOWN"),
                "strength_score": round(float(row.get("strength_score") or 0), 2),
                "strength_score_rank": strength_rank[country],
                "champion_probability": round(float(row.get("champion_probability") or 0), 2),
                "champion_probability_rank": champion_rank[country],
                "rank_delta": rank_delta,
                "rank_delta_explanation": "positive means champion probability rank is better than strength rank",
                "final_probability": round(float(row.get("final_probability") or 0), 2),
                "semi_final_probability": round(float(row.get("semi_final_probability") or 0), 2),
                "quarter_final_probability": round(float(row.get("quarter_final_probability") or 0), 2),
                "round_of_16_probability": round(float(row.get("round_of_16_probability") or 0), 2),
                "group_qualification_probability": round(float(row.get("group_qualification_probability") or 0), 2),
            }
        )
    return rows


def _top20(rows: list[dict], field: str) -> list[dict]:
    return sorted(
        rows,
        key=lambda row: (float(row[field]), float(row["strength_score"])),
        reverse=True,
    )[:20]


def _confederation_summary(rows: list[dict]) -> list[dict]:
    summary = []
    for confederation in CONFEDERATIONS:
        teams = [row for row in rows if row["confederation"] == confederation]
        if not teams:
            summary.append(
                {
                    "confederation": confederation,
                    "teams": 0,
                    "average_champion_probability": 0.0,
                    "total_champion_probability": 0.0,
                    "top_team": None,
                }
            )
            continue
        top_team = max(teams, key=lambda row: row["champion_probability"])
        summary.append(
            {
                "confederation": confederation,
                "teams": len(teams),
                "average_champion_probability": round(mean(row["champion_probability"] for row in teams), 3),
                "total_champion_probability": round(sum(row["champion_probability"] for row in teams), 2),
                "top_team": top_team["country"],
                "top_team_champion_probability": top_team["champion_probability"],
            }
        )
    return summary


def _detect_rank_anomalies(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    overrated = [
        row for row in rows
        if row["rank_delta"] >= RANK_DELTA_THRESHOLD and row["champion_probability"] > 0
    ]
    underrated = [
        row for row in rows
        if row["rank_delta"] <= -RANK_DELTA_THRESHOLD
    ]
    overrated.sort(key=lambda row: row["rank_delta"], reverse=True)
    underrated.sort(key=lambda row: row["rank_delta"])
    return overrated, underrated


def _write_markdown(path: Path, payload: dict) -> None:
    lines = [
        "# Phase 8.1 World Cup Simulation Audit",
        "",
        "## Audit Scope",
        "",
        f"- Simulations audited: {payload['simulations']}",
        f"- pre_draw_simulation: {payload['pre_draw_simulation']}",
        f"- real_schedule_simulation: {payload['real_schedule_simulation']}",
        f"- Schedule source: {payload['schedule_source']}",
        f"- Rank anomaly threshold: {payload['rank_delta_threshold']} places",
        "- Policy: audit only; model parameters and simulation logic were not modified.",
        "",
    ]
    _append_table(lines, "Top20 Champion Probability", payload["top20_champion_probability"], "champion_probability")
    _append_table(lines, "Top20 Final Probability", payload["top20_final_probability"], "final_probability")
    _append_table(lines, "Top20 Semi Final Probability", payload["top20_semi_final_probability"], "semi_final_probability")
    _append_table(lines, "Top20 Quarter Final Probability", payload["top20_quarter_final_probability"], "quarter_final_probability")
    _append_table(lines, "Top20 Group Qualification Probability", payload["top20_group_qualification_probability"], "group_qualification_probability")

    lines.extend(
        [
            "",
            "## Confederation Champion Probability",
            "",
            "| Confederation | Teams | Avg Champion % | Total Champion % | Top Team | Top Team Champion % |",
            "|---|---:|---:|---:|---|---:|",
        ]
    )
    for row in payload["confederation_champion_probability"]:
        lines.append(
            f"| {row['confederation']} | {row['teams']} | {row['average_champion_probability']}% | "
            f"{row['total_champion_probability']}% | {row.get('top_team') or '-'} | "
            f"{row.get('top_team_champion_probability', 0)}% |"
        )

    _append_anomaly_table(lines, "Overrated Teams", payload["overrated_teams"])
    _append_anomaly_table(lines, "Underrated Teams", payload["underrated_teams"])
    _append_anomaly_table(lines, "Strength vs Champion Probability Rank Audit", payload["rank_audit_rows"])
    path.write_text("\n".join(lines), encoding="utf-8")


def _append_table(lines: list[str], title: str, rows: list[dict], field: str) -> None:
    lines.extend(
        [
            "",
            f"## {title}",
            "",
            "| Rank | Team | Confed | Strength Rank | Champion Rank | Rank Delta | Strength | Probability |",
            "|---:|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"| {index} | {row['country']} | {row['confederation']} | {row['strength_score_rank']} | "
            f"{row['champion_probability_rank']} | {row['rank_delta']} | {row['strength_score']} | "
            f"{row[field]}% |"
        )


def _append_anomaly_table(lines: list[str], title: str, rows: list[dict]) -> None:
    lines.extend(
        [
            "",
            f"## {title}",
            "",
            "| Team | Confed | Strength Rank | Champion Rank | Rank Delta | Strength | Champion % | Final % | Semi % | Quarter % | Group Qual % |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    if not rows:
        lines.append("| - | - | - | - | - | - | - | - | - | - | - |")
        return
    for row in rows:
        lines.append(
            f"| {row['country']} | {row['confederation']} | {row['strength_score_rank']} | "
            f"{row['champion_probability_rank']} | {row['rank_delta']} | {row['strength_score']} | "
            f"{row['champion_probability']}% | {row['final_probability']}% | "
            f"{row['semi_final_probability']}% | {row['quarter_final_probability']}% | "
            f"{row['group_qualification_probability']}% |"
        )
