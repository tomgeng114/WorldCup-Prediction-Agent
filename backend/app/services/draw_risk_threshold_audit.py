from __future__ import annotations

import csv
import html
import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BacktestPrediction, WorldCupMatch, WorldCupOdds
from app.services.worldcup_historical_audit import _market_favorite, _upset_probability, latest_run_for_years


@dataclass(frozen=True)
class DrawRiskRow:
    match_id: int
    year: int
    match: str
    actual_result: str
    predicted_result: str
    draw_probability: float
    win_probability_gap: float
    predicted_total_goals: int
    upset_probability: float


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


def _pct(numerator: int | float, denominator: int | float) -> float:
    return round(numerator / denominator * 100, 2) if denominator else 0.0


def _f1(precision: float, recall: float) -> float:
    return round(2 * precision * recall / (precision + recall), 2) if precision + recall else 0.0


def _audit_rows(raw_rows: list[tuple[BacktestPrediction, WorldCupMatch, WorldCupOdds | None]]) -> list[DrawRiskRow]:
    rows: list[DrawRiskRow] = []
    for prediction, match, odds in raw_rows:
        home_probability = prediction.home_win_probability * 100
        draw_probability = prediction.draw_probability * 100
        away_probability = prediction.away_win_probability * 100
        win_probability_gap = max(home_probability, away_probability) - draw_probability
        market_favorite = _market_favorite(odds)
        rows.append(
            DrawRiskRow(
                match_id=match.id,
                year=match.tournament_year,
                match=f"{match.home_team} vs {match.away_team}",
                actual_result=match.result,
                predicted_result=prediction.predicted_result,
                draw_probability=round(draw_probability, 2),
                win_probability_gap=round(win_probability_gap, 2),
                predicted_total_goals=prediction.predicted_total_goals,
                upset_probability=_upset_probability(prediction, market_favorite),
            )
        )
    return rows


def _conditions() -> list[tuple[str, str, object]]:
    return [
        ("C01", "Draw Probability >= 25%", lambda row: row.draw_probability >= 25),
        ("C02", "Draw Probability >= 27%", lambda row: row.draw_probability >= 27),
        ("C03", "Draw Probability >= 30%", lambda row: row.draw_probability >= 30),
        ("C04", "Win Probability Gap <= 5%", lambda row: row.win_probability_gap <= 5),
        ("C05", "Win Probability Gap <= 10%", lambda row: row.win_probability_gap <= 10),
        ("C06", "Win Probability Gap <= 15%", lambda row: row.win_probability_gap <= 15),
        ("C07", "Draw Probability >= 25% AND Win Probability Gap <= 15%", lambda row: row.draw_probability >= 25 and row.win_probability_gap <= 15),
        ("C08", "Draw Probability >= 25% AND Predicted Total Goals <= 3", lambda row: row.draw_probability >= 25 and row.predicted_total_goals <= 3),
        ("C09", "Draw Probability >= 25% AND Upset Probability >= 55%", lambda row: row.draw_probability >= 25 and row.upset_probability >= 55),
        (
            "C10",
            "Draw Probability >= 25% AND Win Probability Gap <= 15% AND Predicted Total Goals <= 3",
            lambda row: row.draw_probability >= 25 and row.win_probability_gap <= 15 and row.predicted_total_goals <= 3,
        ),
    ]


def _condition_metrics(rows: list[DrawRiskRow]) -> list[dict]:
    actual_draws = [row for row in rows if row.actual_result == "Draw"]
    total_actual_draws = len(actual_draws)
    output = []
    for condition_id, condition, predicate in _conditions():
        selected = [row for row in rows if predicate(row)]
        selected_draws = [row for row in selected if row.actual_result == "Draw"]
        false_positives = len(selected) - len(selected_draws)
        precision = _pct(len(selected_draws), len(selected))
        recall = _pct(len(selected_draws), total_actual_draws)
        output.append(
            {
                "condition_id": condition_id,
                "condition": condition,
                "selected_matches": len(selected),
                "actual_draws_covered": len(selected_draws),
                "coverage": recall,
                "false_positives": false_positives,
                "precision": precision,
                "recall": recall,
                "f1": _f1(precision, recall),
            }
        )
    return sorted(output, key=lambda row: (-row["f1"], -row["precision"], -row["recall"], row["condition_id"]))


def _condition_cases(rows: list[DrawRiskRow]) -> list[dict]:
    output = []
    for condition_id, condition, predicate in _conditions():
        for row in rows:
            if predicate(row):
                output.append(
                    {
                        "condition_id": condition_id,
                        "condition": condition,
                        "match_id": row.match_id,
                        "year": row.year,
                        "match": row.match,
                        "actual_result": row.actual_result,
                        "predicted_result": row.predicted_result,
                        "is_actual_draw": row.actual_result == "Draw",
                        "draw_probability": row.draw_probability,
                        "win_probability_gap": row.win_probability_gap,
                        "predicted_total_goals": row.predicted_total_goals,
                        "upset_probability": row.upset_probability,
                    }
                )
    return output


def build_draw_risk_threshold_audit(db: Session, years: list[int]) -> dict:
    run = latest_run_for_years(db, years)
    if run is None:
        raise RuntimeError(f"No backtest run found for years={years}. Run historical audit first.")
    rows = _audit_rows(_rows_for_run(db, run.id))
    ranking = _condition_metrics(rows)
    return {
        "metadata": {
            "run_id": run.id,
            "years": years,
            "scope": "Draw risk threshold coverage analysis across all World Cup historical backtest matches",
            "model_change": "none",
            "note": "Read-only audit only. Conditions are measured historically and are not written back to model, recommendation logic, probabilities, or frontend.",
        },
        "summary": {
            "total_matches": len(rows),
            "actual_draws": sum(row.actual_result == "Draw" for row in rows),
            "best_condition_by_f1": ranking[0] if ranking else None,
        },
        "ranking": ranking,
        "condition_cases": _condition_cases(rows),
    }


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
    best = summary["best_condition_by_f1"] or {}
    cards = [
        ("Total Matches", summary["total_matches"]),
        ("Actual Draws", summary["actual_draws"]),
        ("Best Condition", best.get("condition_id", "n/a")),
        ("Best Precision", f"{best.get('precision', 'n/a')}%"),
        ("Best Recall", f"{best.get('recall', 'n/a')}%"),
        ("Best F1", best.get("f1", "n/a")),
    ]
    card_html = "".join(
        f"<div class='card'><span>{html.escape(str(label))}</span><strong>{html.escape(str(value))}</strong></div>"
        for label, value in cards
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Draw Risk Threshold Audit</title>
  <style>
    :root {{ color-scheme: dark; font-family:'Segoe UI',sans-serif; background:#07111f; color:#e7eef9; }}
    body {{ margin:0; padding:32px; background:radial-gradient(circle at top left,#164e63,#07111f 44%,#030712); }}
    h1 {{ margin:0 0 8px; font-size:30px; }}
    h2 {{ margin-top:30px; color:#67e8f9; }}
    .note {{ color:#a8b8ca; margin-bottom:24px; }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:14px; }}
    .card {{ border:1px solid rgba(148,163,184,.22); border-radius:18px; padding:18px; background:rgba(15,23,42,.72); }}
    .card span {{ display:block; color:#9fb3c8; font-size:13px; }}
    .card strong {{ display:block; margin-top:10px; font-size:23px; color:#f8fafc; }}
    table {{ width:100%; border-collapse:collapse; margin-top:12px; background:rgba(15,23,42,.68); }}
    th,td {{ padding:10px 11px; border-bottom:1px solid rgba(148,163,184,.16); text-align:left; font-size:13px; vertical-align:top; }}
    th {{ color:#cffafe; background:rgba(30,41,59,.92); }}
  </style>
</head>
<body>
  <h1>Draw Risk Threshold Audit</h1>
  <p class="note">Read-only historical coverage analysis. These conditions are audit labels only and do not change predictions, probabilities, recommendations, or frontend logic.</p>
  <section class="cards">{card_html}</section>
  <h2>Ranking by F1</h2>{_html_table(report['ranking'])}
  <h2>Summary</h2>{_html_table([summary])}
</body>
</html>
"""


def write_draw_risk_threshold_outputs(report: dict, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "draw_risk_threshold_ranking_csv": output_dir / "draw_risk_threshold_ranking.csv",
        "draw_risk_threshold_cases_csv": output_dir / "draw_risk_threshold_cases.csv",
        "draw_risk_threshold_summary_json": output_dir / "draw_risk_threshold_summary.json",
        "draw_risk_threshold_dashboard_html": output_dir / "draw_risk_threshold_dashboard.html",
    }
    _write_csv(paths["draw_risk_threshold_ranking_csv"], report["ranking"])
    _write_csv(paths["draw_risk_threshold_cases_csv"], report["condition_cases"])
    paths["draw_risk_threshold_summary_json"].write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["draw_risk_threshold_dashboard_html"].write_text(_dashboard_html(report), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}
