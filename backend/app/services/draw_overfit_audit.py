from __future__ import annotations

import csv
import html
import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BacktestPrediction, WorldCupMatch, WorldCupOdds
from app.services.worldcup_historical_audit import _market_favorite, _upset_probability, latest_run_for_years


PREDICTION_TYPES = ("Home Win", "Draw", "Away Win")
DRAW_PROBABILITY_BUCKETS = (
    ("<20%", None, 20),
    ("20-25%", 20, 25),
    ("25-30%", 25, 30),
    ("30-35%", 30, 35),
    ("35%+", 35, None),
)


@dataclass(frozen=True)
class DrawOverfitRow:
    match_id: int
    year: int
    match_date: str
    match: str
    prediction_type: str
    actual_result: str
    hit: bool
    predicted_score: str
    home_probability: float
    draw_probability: float
    away_probability: float
    confidence_score: float
    upset_probability: float
    odds: float | None
    return_units: float
    roi: float


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


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 2) if values else None


def _confidence_score(prediction: BacktestPrediction) -> float:
    probabilities = {
        "Home Win": prediction.home_win_probability,
        "Draw": prediction.draw_probability,
        "Away Win": prediction.away_win_probability,
    }
    return round(probabilities[prediction.predicted_result] * 100, 2)


def _odds_for_pick(odds: WorldCupOdds | None, pick: str) -> float | None:
    if not odds:
        return None
    return {
        "Home Win": odds.home_win_odds,
        "Draw": odds.draw_odds,
        "Away Win": odds.away_win_odds,
    }.get(pick)


def _score_bucket(score: str) -> str:
    if score in {"0-0", "1-1", "2-2"}:
        return score
    return "Other"


def _audit_rows(raw_rows: list[tuple[BacktestPrediction, WorldCupMatch, WorldCupOdds | None]]) -> list[DrawOverfitRow]:
    rows: list[DrawOverfitRow] = []
    for prediction, match, odds in raw_rows:
        pick = prediction.predicted_result
        hit = pick == match.result
        price = _odds_for_pick(odds, pick)
        return_units = price if hit and price is not None else 0.0
        profit = return_units - 1.0
        market_favorite = _market_favorite(odds)
        rows.append(
            DrawOverfitRow(
                match_id=match.id,
                year=match.tournament_year,
                match_date=match.match_date.isoformat(),
                match=f"{match.home_team} vs {match.away_team}",
                prediction_type=pick,
                actual_result=match.result,
                hit=hit,
                predicted_score=prediction.predicted_score,
                home_probability=round(prediction.home_win_probability * 100, 2),
                draw_probability=round(prediction.draw_probability * 100, 2),
                away_probability=round(prediction.away_win_probability * 100, 2),
                confidence_score=_confidence_score(prediction),
                upset_probability=_upset_probability(prediction, market_favorite),
                odds=price,
                return_units=round(return_units, 4),
                roi=round(profit * 100, 2),
            )
        )
    return rows


def _prediction_type_stats(rows: list[DrawOverfitRow]) -> list[dict]:
    total = len(rows)
    output = []
    for prediction_type in PREDICTION_TYPES:
        selected = [row for row in rows if row.prediction_type == prediction_type]
        hits = sum(row.hit for row in selected)
        output.append(
            {
                "prediction_type": prediction_type,
                "matches": len(selected),
                "share_of_all_matches": _pct(len(selected), total),
                "hits": hits,
                "accuracy": _pct(hits, len(selected)),
            }
        )
    return output


def _roi_stats(rows: list[DrawOverfitRow]) -> list[dict]:
    output = []
    for prediction_type in PREDICTION_TYPES:
        selected = [row for row in rows if row.prediction_type == prediction_type]
        bets = len(selected)
        total_return = round(sum(row.return_units for row in selected), 4)
        profit = round(total_return - bets, 4)
        output.append(
            {
                "prediction_type": prediction_type,
                "bets": bets,
                "return": total_return,
                "profit": profit,
                "roi": _pct(profit, bets),
            }
        )
    return output


def _draw_pick_score_distribution(rows: list[DrawOverfitRow]) -> list[dict]:
    selected = [row for row in rows if row.prediction_type == "Draw"]
    total = len(selected)
    output = []
    for bucket in ("0-0", "1-1", "2-2", "Other"):
        bucket_rows = [row for row in selected if _score_bucket(row.predicted_score) == bucket]
        output.append(
            {
                "predicted_score_bucket": bucket,
                "matches": len(bucket_rows),
                "share": _pct(len(bucket_rows), total),
                "hits": sum(row.hit for row in bucket_rows),
                "accuracy": _pct(sum(row.hit for row in bucket_rows), len(bucket_rows)),
            }
        )
    return output


def _draw_pick_calibration(rows: list[DrawOverfitRow]) -> list[dict]:
    selected = [row for row in rows if row.prediction_type == "Draw"]
    output = []
    for label, lower, upper in DRAW_PROBABILITY_BUCKETS:
        bucket_rows = [
            row
            for row in selected
            if (lower is None or row.draw_probability >= lower) and (upper is None or row.draw_probability < upper)
        ]
        output.append(
            {
                "draw_probability_bucket": label,
                "matches": len(bucket_rows),
                "hits": sum(row.hit for row in bucket_rows),
                "actual_draw_rate": _pct(sum(row.hit for row in bucket_rows), len(bucket_rows)),
            }
        )
    return output


def _comparison_ranking(rows: list[DrawOverfitRow]) -> list[dict]:
    type_stats = {row["prediction_type"]: row for row in _prediction_type_stats(rows)}
    roi_stats = {row["prediction_type"]: row for row in _roi_stats(rows)}
    output = []
    for prediction_type in PREDICTION_TYPES:
        selected = [row for row in rows if row.prediction_type == prediction_type]
        output.append(
            {
                "prediction_type": prediction_type,
                "matches": len(selected),
                "accuracy": type_stats[prediction_type]["accuracy"],
                "roi": roi_stats[prediction_type]["roi"],
                "average_confidence": _avg([row.confidence_score for row in selected]),
                "average_draw_probability": _avg([row.draw_probability for row in selected]),
                "average_upset_probability": _avg([row.upset_probability for row in selected]),
            }
        )
    return sorted(output, key=lambda row: (-row["accuracy"], -row["roi"], row["prediction_type"]))


def _draw_pick_summary(rows: list[DrawOverfitRow]) -> dict:
    selected = [row for row in rows if row.prediction_type == "Draw"]
    hits = sum(row.hit for row in selected)
    return {
        "draw_pick_matches": len(selected),
        "actual_draws": hits,
        "actual_non_draws": len(selected) - hits,
        "accuracy": _pct(hits, len(selected)),
    }


def _overfit_detection(rows: list[DrawOverfitRow]) -> dict:
    actual_draws = sum(row.actual_result == "Draw" for row in rows)
    draw_picks = sum(row.prediction_type == "Draw" for row in rows)
    actual_draw_rate = _pct(actual_draws, len(rows))
    draw_pick_rate = _pct(draw_picks, len(rows))
    gap = round(draw_pick_rate - actual_draw_rate, 2)
    if gap > 3:
        status = "C_draw_picks_too_many"
        interpretation = "Model draw-pick rate is materially higher than actual draw rate."
    elif gap < -3:
        status = "A_draw_picks_insufficient"
        interpretation = "Model draw-pick rate is materially lower than actual draw rate."
    else:
        status = "B_draw_picks_reasonable"
        interpretation = "Model draw-pick rate is close to actual draw rate."
    return {
        "total_matches": len(rows),
        "actual_draws": actual_draws,
        "actual_draw_rate": actual_draw_rate,
        "draw_pick_matches": draw_picks,
        "draw_pick_rate": draw_pick_rate,
        "rate_gap_draw_pick_minus_actual": gap,
        "status": status,
        "interpretation": interpretation,
    }


def _conclusion(rows: list[DrawOverfitRow]) -> dict:
    overfit = _overfit_detection(rows)
    type_stats = {row["prediction_type"]: row for row in _prediction_type_stats(rows)}
    roi_stats = {row["prediction_type"]: row for row in _roi_stats(rows)}
    draw_accuracy = type_stats["Draw"]["accuracy"]
    home_accuracy = type_stats["Home Win"]["accuracy"]
    away_accuracy = type_stats["Away Win"]["accuracy"]
    draw_roi = roi_stats["Draw"]["roi"]
    home_roi = roi_stats["Home Win"]["roi"]
    away_roi = roi_stats["Away Win"]["roi"]
    return {
        "is_over_picking_draw": overfit["status"] == "C_draw_picks_too_many",
        "is_under_picking_draw": overfit["status"] == "A_draw_picks_insufficient",
        "draw_pick_accuracy_lower_than_home_and_away": draw_accuracy < home_accuracy and draw_accuracy < away_accuracy,
        "draw_pick_roi_better_than_home_and_away": draw_roi > home_roi and draw_roi > away_roi,
        "draw_module_classification": overfit["status"],
        "draw_accuracy": draw_accuracy,
        "home_accuracy": home_accuracy,
        "away_accuracy": away_accuracy,
        "draw_roi": draw_roi,
        "home_roi": home_roi,
        "away_roi": away_roi,
    }


def build_draw_overfit_audit(db: Session, years: list[int]) -> dict:
    run = latest_run_for_years(db, years)
    if run is None:
        raise RuntimeError(f"No backtest run found for years={years}. Run historical audit first.")
    rows = _audit_rows(_rows_for_run(db, run.id))
    return {
        "metadata": {
            "run_id": run.id,
            "years": years,
            "scope": "Draw over-pick / under-pick historical audit",
            "model_change": "none",
            "note": "Read-only audit. No model, weights, Poisson, Dixon-Coles, Monte Carlo, odds fusion, ELO, confidence, upset, recommendations, or frontend pages were changed.",
        },
        "prediction_type_stats": _prediction_type_stats(rows),
        "draw_pick_summary": _draw_pick_summary(rows),
        "draw_pick_score_distribution": _draw_pick_score_distribution(rows),
        "roi_by_prediction_type": _roi_stats(rows),
        "draw_pick_calibration": _draw_pick_calibration(rows),
        "overfit_detection": _overfit_detection(rows),
        "comparison_ranking": _comparison_ranking(rows),
        "conclusion": _conclusion(rows),
        "cases": [row.__dict__ for row in rows],
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
    overfit = report["overfit_detection"]
    conclusion = report["conclusion"]
    cards = [
        ("Actual Draw Rate", f"{overfit['actual_draw_rate']}%"),
        ("Draw Pick Rate", f"{overfit['draw_pick_rate']}%"),
        ("Rate Gap", f"{overfit['rate_gap_draw_pick_minus_actual']}%"),
        ("Classification", overfit["status"]),
        ("Draw Accuracy", f"{conclusion['draw_accuracy']}%"),
        ("Draw ROI", f"{conclusion['draw_roi']}%"),
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
  <title>Draw Overfit Audit</title>
  <style>
    :root {{ color-scheme: dark; font-family:'Segoe UI',sans-serif; background:#07111f; color:#e7eef9; }}
    body {{ margin:0; padding:32px; background:radial-gradient(circle at top left,#7c2d12,#07111f 44%,#030712); }}
    h1 {{ margin:0 0 8px; font-size:30px; }}
    h2 {{ margin-top:30px; color:#fdba74; }}
    .note {{ color:#a8b8ca; margin-bottom:24px; }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:14px; }}
    .card {{ border:1px solid rgba(148,163,184,.22); border-radius:18px; padding:18px; background:rgba(15,23,42,.72); }}
    .card span {{ display:block; color:#9fb3c8; font-size:13px; }}
    .card strong {{ display:block; margin-top:10px; font-size:22px; color:#f8fafc; }}
    table {{ width:100%; border-collapse:collapse; margin-top:12px; background:rgba(15,23,42,.68); }}
    th,td {{ padding:10px 11px; border-bottom:1px solid rgba(148,163,184,.16); text-align:left; font-size:13px; vertical-align:top; }}
    th {{ color:#fed7aa; background:rgba(30,41,59,.92); }}
  </style>
</head>
<body>
  <h1>Draw Overfit Audit</h1>
  <p class="note">Read-only historical audit. No model, weight, probability, recommendation, or frontend logic was changed.</p>
  <section class="cards">{card_html}</section>
  <h2>Prediction Type Stats</h2>{_html_table(report['prediction_type_stats'])}
  <h2>Draw Pick Summary</h2>{_html_table([report['draw_pick_summary']])}
  <h2>Draw Pick Score Distribution</h2>{_html_table(report['draw_pick_score_distribution'])}
  <h2>ROI by Prediction Type</h2>{_html_table(report['roi_by_prediction_type'])}
  <h2>Draw Pick Calibration</h2>{_html_table(report['draw_pick_calibration'])}
  <h2>Overfit Detection</h2>{_html_table([report['overfit_detection']])}
  <h2>Comparison Ranking</h2>{_html_table(report['comparison_ranking'])}
</body>
</html>
"""


def write_draw_overfit_outputs(report: dict, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "draw_overfit_prediction_type_csv": output_dir / "draw_overfit_prediction_type.csv",
        "draw_overfit_roi_csv": output_dir / "draw_overfit_roi.csv",
        "draw_overfit_calibration_csv": output_dir / "draw_overfit_calibration.csv",
        "draw_overfit_comparison_csv": output_dir / "draw_overfit_comparison.csv",
        "draw_overfit_cases_csv": output_dir / "draw_overfit_cases.csv",
        "draw_overfit_summary_json": output_dir / "draw_overfit_summary.json",
        "draw_overfit_dashboard_html": output_dir / "draw_overfit_dashboard.html",
    }
    _write_csv(paths["draw_overfit_prediction_type_csv"], report["prediction_type_stats"])
    _write_csv(paths["draw_overfit_roi_csv"], report["roi_by_prediction_type"])
    _write_csv(paths["draw_overfit_calibration_csv"], report["draw_pick_calibration"])
    _write_csv(paths["draw_overfit_comparison_csv"], report["comparison_ranking"])
    _write_csv(paths["draw_overfit_cases_csv"], report["cases"])
    paths["draw_overfit_summary_json"].write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["draw_overfit_dashboard_html"].write_text(_dashboard_html(report), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}
