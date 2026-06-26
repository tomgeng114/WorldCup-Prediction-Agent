from __future__ import annotations

import csv
import html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BacktestPrediction, WorldCupMatch, WorldCupOdds
from app.services.worldcup_historical_audit import (
    CONFIDENCE_BUCKETS,
    STAGE_ORDER,
    STRONG_TEAMS,
    UPSET_BUCKETS,
    _audit_stage,
    _market_favorite,
    _pick,
    _upset_probability,
    latest_run_for_years,
)


ELITE_TEAMS = (*STRONG_TEAMS, "Belgium")


@dataclass(frozen=True)
class MarketVsModelConflict:
    match_id: int
    tournament_year: int
    match_date: str
    stage: str
    match: str
    home_team: str
    away_team: str
    market_favorite: str
    market_favorite_team: str
    model_favorite: str
    model_favorite_team: str
    actual_result: str
    actual_result_team: str
    model_correct: bool
    market_correct: bool
    confidence_score: float
    upset_probability: float
    odds_home: float
    odds_draw: float
    odds_away: float


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


def _result_team(result: str, home_team: str, away_team: str) -> str:
    if result == "Home Win":
        return home_team
    if result == "Away Win":
        return away_team
    return "Draw"


def _confidence_score(prediction: BacktestPrediction, model_favorite: str) -> float:
    probabilities = {
        "Home Win": prediction.home_win_probability,
        "Draw": prediction.draw_probability,
        "Away Win": prediction.away_win_probability,
    }
    return round(probabilities[model_favorite] * 100, 2)


def _conflicts(raw_rows: Iterable[tuple[BacktestPrediction, WorldCupMatch, WorldCupOdds | None]]) -> list[MarketVsModelConflict]:
    conflicts: list[MarketVsModelConflict] = []
    for prediction, match, odds in raw_rows:
        market_favorite = _market_favorite(odds)
        if market_favorite is None or odds is None:
            continue
        probabilities = {
            "Home Win": prediction.home_win_probability,
            "Draw": prediction.draw_probability,
            "Away Win": prediction.away_win_probability,
        }
        model_favorite = _pick(probabilities)
        if market_favorite == model_favorite:
            continue
        conflicts.append(
            MarketVsModelConflict(
                match_id=match.id,
                tournament_year=match.tournament_year,
                match_date=match.match_date.isoformat(),
                stage=_audit_stage(match.stage),
                match=f"{match.home_team} vs {match.away_team}",
                home_team=match.home_team,
                away_team=match.away_team,
                market_favorite=market_favorite,
                market_favorite_team=_result_team(market_favorite, match.home_team, match.away_team),
                model_favorite=model_favorite,
                model_favorite_team=_result_team(model_favorite, match.home_team, match.away_team),
                actual_result=match.result,
                actual_result_team=_result_team(match.result, match.home_team, match.away_team),
                model_correct=match.result == model_favorite,
                market_correct=match.result == market_favorite,
                confidence_score=_confidence_score(prediction, model_favorite),
                upset_probability=_upset_probability(prediction, market_favorite),
                odds_home=odds.home_win_odds,
                odds_draw=odds.draw_odds,
                odds_away=odds.away_win_odds,
            )
        )
    return conflicts


def _pct(numerator: int | float, denominator: int | float) -> float:
    return round(numerator / denominator * 100, 2) if denominator else 0.0


def _summary(rows: list[MarketVsModelConflict]) -> dict:
    model_wins = sum(row.model_correct for row in rows)
    market_wins = sum(row.market_correct for row in rows)
    return {
        "conflict_matches": len(rows),
        "model_wins": model_wins,
        "market_wins": market_wins,
        "model_win_rate": _pct(model_wins, len(rows)),
        "market_win_rate": _pct(market_wins, len(rows)),
    }


def _stage_analysis(rows: list[MarketVsModelConflict]) -> list[dict]:
    stages = list(STAGE_ORDER) + sorted({row.stage for row in rows if row.stage not in STAGE_ORDER})
    output = []
    for stage in stages:
        selected = [row for row in rows if row.stage == stage]
        if selected:
            output.append({"stage": stage, **_summary(selected)})
    return output


def _bucket_analysis(rows: list[MarketVsModelConflict], buckets: tuple[tuple[str, float, float | None], ...], field: str) -> list[dict]:
    output = []
    for label, lower, upper in buckets:
        selected = [row for row in rows if getattr(row, field) >= lower and (upper is None or getattr(row, field) < upper)]
        output.append({"bucket": label, **_summary(selected)})
    return output


def _elite_overvaluation(rows: list[MarketVsModelConflict]) -> list[dict]:
    output = []
    for team in ELITE_TEAMS:
        selected = [row for row in rows if row.market_favorite_team == team and row.model_favorite_team != team]
        output.append({"team": team, **_summary(selected)})
    return output


def _best_by(items: list[dict], metric: str) -> dict | None:
    valid = [item for item in items if item.get("conflict_matches", 0)]
    return max(valid, key=lambda item: item[metric], default=None)


def _conclusion(report: dict) -> dict:
    summary = report["summary"]
    best_stage = _best_by(report["stage_analysis"], "model_win_rate")
    best_confidence = _best_by(report["confidence_analysis"], "model_win_rate")
    best_upset = _best_by(report["upset_analysis"], "model_win_rate")
    elite_rows = [row for row in report["elite_overvaluation_analysis"] if row["conflict_matches"]]
    elite_total = sum(row["conflict_matches"] for row in elite_rows)
    elite_model_wins = sum(row["model_wins"] for row in elite_rows)
    elite_market_wins = sum(row["market_wins"] for row in elite_rows)
    elite_model_rate = _pct(elite_model_wins, elite_total)
    elite_market_rate = _pct(elite_market_wins, elite_total)
    return {
        "conflict_model_win_rate": summary["model_win_rate"],
        "conflict_market_win_rate": summary["market_win_rate"],
        "best_stage_for_model": None if not best_stage else best_stage["stage"],
        "best_confidence_bucket_for_conflict": None if not best_confidence else best_confidence["bucket"],
        "best_upset_bucket_for_conflict": None if not best_upset else best_upset["bucket"],
        "elite_overvaluation_exists": bool(elite_total and elite_model_rate > elite_market_rate),
        "elite_overvaluation_matches": elite_total,
        "elite_overvaluation_model_win_rate": elite_model_rate,
        "elite_overvaluation_market_win_rate": elite_market_rate,
        "conflict_pool_recommendation": "Worth separate tracking, but sample is small; do not turn into an automatic betting rule yet." if summary["conflict_matches"] else "No conflict sample available.",
    }


def build_market_vs_model_audit(db: Session, years: list[int]) -> dict:
    run = latest_run_for_years(db, years)
    if run is None:
        raise RuntimeError(f"No backtest run found for years={years}. Run the historical audit first.")
    conflicts = _conflicts(_rows_for_run(db, run.id))
    report = {
        "metadata": {
            "run_id": run.id,
            "years": years,
            "source": "world_cup_matches + backtest_predictions + world_cup_odds",
            "model_change": "none",
            "note": "Market vs Model audit only reads existing backtest rows and odds. It does not modify models, weights, Poisson, Monte Carlo, Dixon-Coles, confidence, upset, or recommendation logic.",
        },
        "summary": _summary(conflicts),
        "stage_analysis": _stage_analysis(conflicts),
        "upset_analysis": _bucket_analysis(conflicts, UPSET_BUCKETS, "upset_probability"),
        "confidence_analysis": _bucket_analysis(conflicts, CONFIDENCE_BUCKETS, "confidence_score"),
        "elite_overvaluation_analysis": _elite_overvaluation(conflicts),
        "conflict_matches": [row.__dict__ for row in conflicts],
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
    cards = [
        ("Conflict Matches", summary["conflict_matches"]),
        ("Model Wins", summary["model_wins"]),
        ("Market Wins", summary["market_wins"]),
        ("Model Win Rate", f"{summary['model_win_rate']}%"),
        ("Market Win Rate", f"{summary['market_win_rate']}%"),
    ]
    card_html = "".join(f"<div class='card'><span>{html.escape(label)}</span><strong>{html.escape(str(value))}</strong></div>" for label, value in cards)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Market vs Model Audit</title>
  <style>
    :root {{ color-scheme: dark; font-family: 'Segoe UI', sans-serif; background:#07111f; color:#e7eef9; }}
    body {{ margin:0; padding:32px; background:radial-gradient(circle at top left,#164e63,#07111f 42%,#040711); }}
    h1 {{ margin:0 0 8px; font-size:30px; }}
    h2 {{ margin-top:30px; color:#67e8f9; }}
    .note {{ color:#a8b8ca; margin-bottom:24px; }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:14px; }}
    .card {{ border:1px solid rgba(148,163,184,.22); border-radius:18px; padding:18px; background:rgba(15,23,42,.72); }}
    .card span {{ display:block; color:#9fb3c8; font-size:13px; }}
    .card strong {{ display:block; margin-top:10px; font-size:25px; color:#f8fafc; }}
    table {{ width:100%; border-collapse:collapse; margin-top:12px; background:rgba(15,23,42,.68); }}
    th,td {{ padding:10px 11px; border-bottom:1px solid rgba(148,163,184,.16); text-align:left; font-size:13px; }}
    th {{ color:#a5f3fc; background:rgba(30,41,59,.92); }}
  </style>
</head>
<body>
  <h1>Market vs Model Audit</h1>
  <p class="note">只读审计：统计市场热门与模型热门冲突盘，不修改任何模型或算法。</p>
  <section class="cards">{card_html}</section>
  <h2>Final Conclusion</h2>{_html_table([report['conclusion']])}
  <h2>Stage Analysis</h2>{_html_table(report['stage_analysis'])}
  <h2>Upset Bucket</h2>{_html_table(report['upset_analysis'])}
  <h2>Confidence Bucket</h2>{_html_table(report['confidence_analysis'])}
  <h2>Elite Overvaluation</h2>{_html_table(report['elite_overvaluation_analysis'])}
  <h2>Conflict Details</h2>{_html_table(report['conflict_matches'])}
</body>
</html>
"""


def write_market_vs_model_outputs(report: dict, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    market_vs_model_rows = (
        [{"section": "summary", **report["summary"]}]
        + [{"section": "stage_analysis", **row} for row in report["stage_analysis"]]
        + [{"section": "upset_analysis", **row} for row in report["upset_analysis"]]
        + [{"section": "confidence_analysis", **row} for row in report["confidence_analysis"]]
        + [{"section": "elite_overvaluation_analysis", **row} for row in report["elite_overvaluation_analysis"]]
        + [{"section": "conclusion", **report["conclusion"]}]
    )
    paths = {
        "market_vs_model_csv": output_dir / "market_vs_model.csv",
        "conflict_detailed_report_csv": output_dir / "conflict_detailed_report.csv",
        "market_vs_model_summary_json": output_dir / "market_vs_model_summary.json",
        "market_vs_model_dashboard_html": output_dir / "market_vs_model_dashboard.html",
    }
    _write_csv(paths["market_vs_model_csv"], market_vs_model_rows)
    _write_csv(paths["conflict_detailed_report_csv"], report["conflict_matches"])
    paths["market_vs_model_summary_json"].write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["market_vs_model_dashboard_html"].write_text(_dashboard_html(report), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}
