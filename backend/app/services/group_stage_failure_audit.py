from __future__ import annotations

import csv
import html
import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BacktestPrediction, WorldCupMatch, WorldCupOdds
from app.services.market_vs_model_audit import _result_team
from app.services.worldcup_historical_audit import _audit_stage, _market_favorite, _pick, _upset_probability, latest_run_for_years


ERROR_TYPES = {
    "A_hot_favorite_upset": "热门球队爆冷",
    "B_draw_misread": "平局判断失败",
    "C_market_model_aligned_failure": "模型与市场一致但仍失败",
    "D_market_model_conflict_failure": "模型与市场冲突且失败",
    "E_high_confidence_failure": "高信心失败",
    "F_low_confidence_failure": "低信心失败",
}


@dataclass(frozen=True)
class FailedGroupStageMatch:
    match_id: int
    tournament_year: int
    match_date: str
    match: str
    home_team: str
    away_team: str
    predicted_result: str
    predicted_result_team: str
    actual_result: str
    actual_result_team: str
    home_probability: float
    draw_probability: float
    away_probability: float
    confidence_score: float
    upset_probability: float
    market_favorite: str | None
    market_favorite_team: str | None
    model_favorite: str
    model_favorite_team: str
    is_conflict_match: bool | None
    error_types: str
    A_hot_favorite_upset: bool
    B_draw_misread: bool
    C_market_model_aligned_failure: bool
    D_market_model_conflict_failure: bool
    E_high_confidence_failure: bool
    F_low_confidence_failure: bool
    research_priority: int


def _rows_for_run(db: Session, run_id: int) -> list[tuple[BacktestPrediction, WorldCupMatch, WorldCupOdds | None]]:
    return list(
        db.execute(
            select(BacktestPrediction, WorldCupMatch, WorldCupOdds)
            .join(WorldCupMatch, BacktestPrediction.match_id == WorldCupMatch.id)
            .outerjoin(WorldCupOdds, WorldCupOdds.match_id == WorldCupMatch.id)
            .where(BacktestPrediction.run_id == run_id)
            .order_by(WorldCupMatch.match_date.asc(), WorldCupMatch.id.asc())
        ).all()
    )


def _confidence_score(prediction: BacktestPrediction) -> float:
    probabilities = {
        "Home Win": prediction.home_win_probability,
        "Draw": prediction.draw_probability,
        "Away Win": prediction.away_win_probability,
    }
    return round(probabilities[prediction.predicted_result] * 100, 2)


def _failure_flags(
    prediction: BacktestPrediction,
    match: WorldCupMatch,
    market_favorite: str | None,
    model_favorite: str,
    confidence_score: float,
) -> dict[str, bool]:
    is_conflict = None if market_favorite is None else market_favorite != model_favorite
    hot_favorite_upset = bool(market_favorite in {"Home Win", "Away Win"} and match.result != market_favorite)
    draw_misread = bool((prediction.predicted_result == "Draw") != (match.result == "Draw"))
    return {
        "A_hot_favorite_upset": hot_favorite_upset,
        "B_draw_misread": draw_misread,
        "C_market_model_aligned_failure": bool(is_conflict is False),
        "D_market_model_conflict_failure": bool(is_conflict is True),
        "E_high_confidence_failure": confidence_score >= 70,
        "F_low_confidence_failure": confidence_score < 50,
    }


def _research_priority(flags: dict[str, bool], confidence_score: float, upset_probability: float) -> int:
    priority = 0
    if flags["E_high_confidence_failure"]:
        priority += 10000
    if flags["D_market_model_conflict_failure"]:
        priority += 5000
    if flags["A_hot_favorite_upset"]:
        priority += 2500
    priority += int(confidence_score * 10)
    priority += int(upset_probability)
    return priority


def _failed_matches(raw_rows: list[tuple[BacktestPrediction, WorldCupMatch, WorldCupOdds | None]]) -> list[FailedGroupStageMatch]:
    output: list[FailedGroupStageMatch] = []
    for prediction, match, odds in raw_rows:
        if _audit_stage(match.stage) != "Group Stage":
            continue
        if prediction.predicted_result == match.result:
            continue
        probabilities = {
            "Home Win": prediction.home_win_probability,
            "Draw": prediction.draw_probability,
            "Away Win": prediction.away_win_probability,
        }
        market_favorite = _market_favorite(odds)
        model_favorite = _pick(probabilities)
        is_conflict = None if market_favorite is None else market_favorite != model_favorite
        confidence = _confidence_score(prediction)
        upset = _upset_probability(prediction, market_favorite)
        flags = _failure_flags(prediction, match, market_favorite, model_favorite, confidence)
        active_types = [label for key, label in ERROR_TYPES.items() if flags[key]]
        output.append(
            FailedGroupStageMatch(
                match_id=match.id,
                tournament_year=match.tournament_year,
                match_date=match.match_date.isoformat(),
                match=f"{match.home_team} vs {match.away_team}",
                home_team=match.home_team,
                away_team=match.away_team,
                predicted_result=prediction.predicted_result,
                predicted_result_team=_result_team(prediction.predicted_result, match.home_team, match.away_team),
                actual_result=match.result,
                actual_result_team=_result_team(match.result, match.home_team, match.away_team),
                home_probability=round(prediction.home_win_probability * 100, 2),
                draw_probability=round(prediction.draw_probability * 100, 2),
                away_probability=round(prediction.away_win_probability * 100, 2),
                confidence_score=confidence,
                upset_probability=upset,
                market_favorite=market_favorite,
                market_favorite_team=None if market_favorite is None else _result_team(market_favorite, match.home_team, match.away_team),
                model_favorite=model_favorite,
                model_favorite_team=_result_team(model_favorite, match.home_team, match.away_team),
                is_conflict_match=is_conflict,
                error_types="; ".join(active_types),
                research_priority=_research_priority(flags, confidence, upset),
                **flags,
            )
        )
    return output


def _pct(numerator: int | float, denominator: int | float) -> float:
    return round(numerator / denominator * 100, 2) if denominator else 0.0


def _error_analysis(rows: list[FailedGroupStageMatch]) -> list[dict]:
    total = len(rows)
    return [
        {
            "error_type": key,
            "label": label,
            "matches": sum(bool(getattr(row, key)) for row in rows),
            "percentage": _pct(sum(bool(getattr(row, key)) for row in rows), total),
        }
        for key, label in ERROR_TYPES.items()
    ]


def _team_failure_analysis(rows: list[FailedGroupStageMatch]) -> list[dict]:
    teams = sorted({row.home_team for row in rows} | {row.away_team for row in rows})
    output = []
    for team in teams:
        selected = [row for row in rows if row.home_team == team or row.away_team == team]
        as_predicted_team = [row for row in rows if row.predicted_result_team == team]
        output.append(
            {
                "team": team,
                "failed_matches_involving_team": len(selected),
                "failed_matches_when_model_backed_team": len(as_predicted_team),
            }
        )
    return sorted(output, key=lambda row: (row["failed_matches_when_model_backed_team"], row["failed_matches_involving_team"]), reverse=True)


def _top_research_cases(rows: list[FailedGroupStageMatch]) -> list[dict]:
    ranked = sorted(rows, key=lambda row: (row.research_priority, row.confidence_score, row.upset_probability), reverse=True)
    return [
        {
            "match": row.match,
            "tournament_year": row.tournament_year,
            "predicted": row.predicted_result_team,
            "actual": row.actual_result_team,
            "confidence_score": row.confidence_score,
            "upset_probability": row.upset_probability,
            "market_favorite": row.market_favorite_team,
            "model_favorite": row.model_favorite_team,
            "error_types": row.error_types,
        }
        for row in ranked[:10]
    ]


def _conclusion(report: dict) -> dict:
    total = report["summary"]["failed_group_stage_matches"]
    error_map = {row["error_type"]: row for row in report["error_analysis"]}
    most_common = max(report["error_analysis"], key=lambda row: row["matches"], default=None)
    top_team = report["team_failure_analysis"][0] if report["team_failure_analysis"] else None
    return {
        "most_common_error_type": None if not most_common else most_common["label"],
        "most_common_error_matches": 0 if not most_common else most_common["matches"],
        "team_most_associated_with_failures": None if not top_team else top_team["team"],
        "team_failed_matches_when_model_backed": 0 if not top_team else top_team["failed_matches_when_model_backed_team"],
        "draw_is_major_error_source": error_map["B_draw_misread"]["percentage"] >= 30,
        "draw_error_matches": error_map["B_draw_misread"]["matches"],
        "draw_error_percentage": error_map["B_draw_misread"]["percentage"],
        "high_confidence_failure_percentage": error_map["E_high_confidence_failure"]["percentage"],
        "conflict_failure_percentage": error_map["D_market_model_conflict_failure"]["percentage"],
        "total_failed_matches": total,
    }


def build_group_stage_failure_audit(db: Session, years: list[int]) -> dict:
    run = latest_run_for_years(db, years)
    if run is None:
        raise RuntimeError(f"No backtest run found for years={years}. Run historical audit first.")
    rows = _failed_matches(_rows_for_run(db, run.id))
    report = {
        "metadata": {
            "run_id": run.id,
            "years": years,
            "scope": "2018 and 2022 FIFA World Cup group stage failed predictions",
            "model_change": "none",
            "note": "This audit only reads existing backtest rows and odds. It does not modify any model, weight, algorithm, or prediction logic.",
        },
        "summary": {
            "failed_group_stage_matches": len(rows),
            "years": ",".join(str(year) for year in years),
        },
        "failed_matches": [row.__dict__ for row in rows],
        "error_analysis": _error_analysis(rows),
        "team_failure_analysis": _team_failure_analysis(rows),
        "top_research_cases": _top_research_cases(rows),
    }
    report["conclusion"] = _conclusion(report)
    return report


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def _html_table(rows: list[dict]) -> str:
    if not rows:
        return "<p>No data</p>"
    headers: list[str] = []
    for row in rows:
        for key in row:
            if key not in headers:
                headers.append(key)
    head = "".join(f"<th>{html.escape(str(header))}</th>" for header in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(row.get(header, '')))}</td>" for header in headers) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _dashboard_html(report: dict) -> str:
    summary = report["summary"]
    conclusion = report["conclusion"]
    cards = [
        ("Failed Group Stage Matches", summary["failed_group_stage_matches"]),
        ("Most Common Error", conclusion["most_common_error_type"]),
        ("Draw Error %", f"{conclusion['draw_error_percentage']}%"),
        ("High Confidence Failure %", f"{conclusion['high_confidence_failure_percentage']}%"),
        ("Conflict Failure %", f"{conclusion['conflict_failure_percentage']}%"),
    ]
    card_html = "".join(f"<div class='card'><span>{html.escape(str(label))}</span><strong>{html.escape(str(value))}</strong></div>" for label, value in cards)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Group Stage Failure Audit</title>
  <style>
    :root {{ color-scheme: dark; font-family: 'Segoe UI', sans-serif; background:#07111f; color:#e7eef9; }}
    body {{ margin:0; padding:32px; background:radial-gradient(circle at top left,#7c2d12,#07111f 42%,#040711); }}
    h1 {{ margin:0 0 8px; font-size:30px; }}
    h2 {{ margin-top:30px; color:#fdba74; }}
    .note {{ color:#a8b8ca; margin-bottom:24px; }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:14px; }}
    .card {{ border:1px solid rgba(148,163,184,.22); border-radius:18px; padding:18px; background:rgba(15,23,42,.72); }}
    .card span {{ display:block; color:#9fb3c8; font-size:13px; }}
    .card strong {{ display:block; margin-top:10px; font-size:23px; color:#f8fafc; }}
    table {{ width:100%; border-collapse:collapse; margin-top:12px; background:rgba(15,23,42,.68); }}
    th,td {{ padding:10px 11px; border-bottom:1px solid rgba(148,163,184,.16); text-align:left; font-size:13px; }}
    th {{ color:#fed7aa; background:rgba(30,41,59,.92); }}
  </style>
</head>
<body>
  <h1>Group Stage Failure Audit</h1>
  <p class="note">只读审计：分析 2018+2022 世界杯小组赛预测失败案例，不修改任何模型、权重、算法或预测逻辑。</p>
  <section class="cards">{card_html}</section>
  <h2>Final Conclusion</h2>{_html_table([report['conclusion']])}
  <h2>Error Type Analysis</h2>{_html_table(report['error_analysis'])}
  <h2>Top 10 Research Cases</h2>{_html_table(report['top_research_cases'])}
  <h2>Team Failure Analysis</h2>{_html_table(report['team_failure_analysis'][:20])}
  <h2>Failed Matches</h2>{_html_table(report['failed_matches'])}
</body>
</html>
"""


def write_group_stage_failure_outputs(report: dict, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "group_stage_failed_matches_csv": output_dir / "group_stage_failed_matches.csv",
        "group_stage_error_analysis_csv": output_dir / "group_stage_error_analysis.csv",
        "group_stage_failure_report_html": output_dir / "group_stage_failure_report.html",
        "group_stage_failure_summary_json": output_dir / "group_stage_failure_summary.json",
    }
    _write_csv(paths["group_stage_failed_matches_csv"], report["failed_matches"])
    _write_csv(paths["group_stage_error_analysis_csv"], report["error_analysis"])
    paths["group_stage_failure_summary_json"].write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["group_stage_failure_report_html"].write_text(_dashboard_html(report), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}
