from __future__ import annotations

import csv
import html
import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BacktestPrediction, Match, Prediction, WorldCupMatch
from app.services.statistics import actual_result
from app.services.worldcup_historical_audit import CONFIDENCE_BUCKETS, _upset_probability, latest_run_for_years


@dataclass(frozen=True)
class ConfidenceAuditRow:
    sample: str
    match_id: int
    match_date: str
    home_team: str
    away_team: str
    predicted_result: str
    actual_result: str
    predicted_score: str
    actual_score: str
    confidence_score: float
    upset_probability: float
    home_probability: float
    draw_probability: float
    away_probability: float
    result_hit: bool
    score_hit: bool


def _historical_rows(db: Session, years: list[int]) -> list[ConfidenceAuditRow]:
    run = latest_run_for_years(db, years)
    if run is None:
        raise RuntimeError(f"No backtest run found for years={years}. Run historical audit first.")
    raw_rows = list(
        db.execute(
            select(BacktestPrediction, WorldCupMatch)
            .join(WorldCupMatch, BacktestPrediction.match_id == WorldCupMatch.id)
            .where(BacktestPrediction.run_id == run.id)
            .order_by(WorldCupMatch.match_date.asc(), WorldCupMatch.id.asc())
        ).all()
    )
    output = []
    for prediction, match in raw_rows:
        probabilities = {
            "Home Win": prediction.home_win_probability,
            "Draw": prediction.draw_probability,
            "Away Win": prediction.away_win_probability,
        }
        confidence = round(probabilities[prediction.predicted_result] * 100, 2)
        output.append(
            ConfidenceAuditRow(
                sample=str(match.tournament_year),
                match_id=match.id,
                match_date=match.match_date.isoformat(),
                home_team=match.home_team,
                away_team=match.away_team,
                predicted_result=prediction.predicted_result,
                actual_result=match.result,
                predicted_score=prediction.predicted_score,
                actual_score=f"{match.home_score}-{match.away_score}",
                confidence_score=confidence,
                upset_probability=_upset_probability(prediction, None),
                home_probability=round(prediction.home_win_probability * 100, 2),
                draw_probability=round(prediction.draw_probability * 100, 2),
                away_probability=round(prediction.away_win_probability * 100, 2),
                result_hit=prediction.predicted_result == match.result,
                score_hit=prediction.predicted_score == f"{match.home_score}-{match.away_score}",
            )
        )
    return output


def _live_2026_rows(db: Session) -> list[ConfidenceAuditRow]:
    raw_rows = list(
        db.execute(
            select(Match, Prediction)
            .join(Prediction, Prediction.match_id == Match.id)
            .where(Match.status == "finished")
            .where(Match.home_score.is_not(None))
            .where(Match.away_score.is_not(None))
            .order_by(Match.kickoff_time.asc(), Match.id.asc())
        ).all()
    )
    output = []
    for match, prediction in raw_rows:
        actual = actual_result(match)
        output.append(
            ConfidenceAuditRow(
                sample="2026_live",
                match_id=match.id,
                match_date=match.kickoff_time.isoformat(),
                home_team=match.home_team.name,
                away_team=match.away_team.name,
                predicted_result=prediction.predicted_result,
                actual_result=actual,
                predicted_score=prediction.predicted_score,
                actual_score=f"{match.home_score}-{match.away_score}",
                confidence_score=round(prediction.confidence, 2),
                upset_probability=round(prediction.upset_probability, 2),
                home_probability=round(prediction.home_win_probability * 100, 2),
                draw_probability=round(prediction.draw_probability * 100, 2),
                away_probability=round(prediction.away_win_probability * 100, 2),
                result_hit=prediction.predicted_result == actual,
                score_hit=prediction.predicted_score == f"{match.home_score}-{match.away_score}",
            )
        )
    return output


def _pct(numerator: int | float, denominator: int | float) -> float:
    return round(numerator / denominator * 100, 2) if denominator else 0.0


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 2) if values else None


def _bucket_rows(rows: list[ConfidenceAuditRow], sample_label: str) -> list[dict]:
    output = []
    for label, lower, upper in CONFIDENCE_BUCKETS:
        selected = [row for row in rows if row.confidence_score >= lower and (upper is None or row.confidence_score < upper)]
        output.append(
            {
                "sample": sample_label,
                "confidence_bucket": label,
                "matches": len(selected),
                "result_accuracy": _pct(sum(row.result_hit for row in selected), len(selected)),
                "score_accuracy": _pct(sum(row.score_hit for row in selected), len(selected)),
                "average_upset_probability": _avg([row.upset_probability for row in selected]),
                "average_home_probability": _avg([row.home_probability for row in selected]),
                "average_draw_probability": _avg([row.draw_probability for row in selected]),
                "average_away_probability": _avg([row.away_probability for row in selected]),
            }
        )
    return output


def _best_bucket(rows: list[dict]) -> dict | None:
    valid = [row for row in rows if row["matches"]]
    return max(valid, key=lambda row: (row["result_accuracy"], row["matches"]), default=None)


def _correlation_direction(rows: list[dict]) -> dict:
    valid = [row for row in rows if row["matches"]]
    if len(valid) < 2:
        return {"is_monotonic_positive": False, "note": "Not enough non-empty buckets."}
    accuracies = [row["result_accuracy"] for row in valid]
    return {
        "is_monotonic_positive": all(later >= earlier for earlier, later in zip(accuracies, accuracies[1:])),
        "non_empty_bucket_count": len(valid),
        "accuracy_path": " -> ".join(f"{row['confidence_bucket']}:{row['result_accuracy']}%" for row in valid),
    }


def _conclusion(combined_rows: list[dict]) -> dict:
    best = _best_bucket(combined_rows)
    bucket_70_80 = next((row for row in combined_rows if row["confidence_bucket"] == "70-80"), None)
    bucket_80 = next((row for row in combined_rows if row["confidence_bucket"] == "80+"), None)
    bucket_low = next((row for row in combined_rows if row["confidence_bucket"] == "0-40"), None)
    overall_matches = sum(row["matches"] for row in combined_rows)
    overall_hits = 0
    # Reconstruct weighted hits from rounded accuracy only for conclusion comparisons.
    for row in combined_rows:
        overall_hits += row["result_accuracy"] * row["matches"] / 100
    overall_accuracy = round(overall_hits / overall_matches * 100, 2) if overall_matches else 0.0
    return {
        "overall_accuracy": overall_accuracy,
        "highest_accuracy_bucket": None if not best else best["confidence_bucket"],
        "highest_accuracy": None if not best else best["result_accuracy"],
        "bucket_70_80_matches": 0 if not bucket_70_80 else bucket_70_80["matches"],
        "bucket_70_80_accuracy": None if not bucket_70_80 else bucket_70_80["result_accuracy"],
        "define_70_as_high_confidence": bool(bucket_70_80 and bucket_70_80["matches"] >= 10 and bucket_70_80["result_accuracy"] > overall_accuracy),
        "bucket_80_plus_matches": 0 if not bucket_80 else bucket_80["matches"],
        "bucket_80_plus_accuracy": None if not bucket_80 else bucket_80["result_accuracy"],
        "bucket_80_plus_has_significant_advantage": bool(bucket_80 and bucket_80["matches"] >= 10 and bucket_80["result_accuracy"] > overall_accuracy + 5),
        "bucket_under_40_matches": 0 if not bucket_low else bucket_low["matches"],
        "bucket_under_40_accuracy": None if not bucket_low else bucket_low["result_accuracy"],
        "under_40_filter_candidate": bool(bucket_low and bucket_low["matches"] >= 10 and bucket_low["result_accuracy"] + 5 < overall_accuracy),
        **_correlation_direction(combined_rows),
    }


def build_confidence_calibration_audit(db: Session) -> dict:
    rows_2018_2022 = _historical_rows(db, [2018, 2022])
    rows_2026 = _live_2026_rows(db)
    rows_all = rows_2018_2022 + rows_2026
    bucket_2018 = _bucket_rows([row for row in rows_2018_2022 if row.sample == "2018"], "2018")
    bucket_2022 = _bucket_rows([row for row in rows_2018_2022 if row.sample == "2022"], "2022")
    bucket_2026 = _bucket_rows(rows_2026, "2026_live")
    bucket_combined = _bucket_rows(rows_all, "combined_2018_2022_2026_live")
    report = {
        "metadata": {
            "historical_years": [2018, 2022],
            "live_sample": "2026 settled matches from matches + predictions",
            "model_change": "none",
            "note": "This audit only reads existing prediction rows. It does not modify models, weights, algorithms, confidence, upset, or recommendation logic.",
        },
        "sample_sizes": {
            "2018": sum(1 for row in rows_2018_2022 if row.sample == "2018"),
            "2022": sum(1 for row in rows_2018_2022 if row.sample == "2022"),
            "2026_live": len(rows_2026),
            "combined": len(rows_all),
        },
        "confidence_bucket_analysis": bucket_2018 + bucket_2022 + bucket_2026 + bucket_combined,
        "combined_bucket_analysis": bucket_combined,
        "matches": [row.__dict__ for row in rows_all],
    }
    report["conclusion"] = _conclusion(bucket_combined)
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
    sizes = report["sample_sizes"]
    conclusion = report["conclusion"]
    cards = [
        ("2018 Matches", sizes["2018"]),
        ("2022 Matches", sizes["2022"]),
        ("2026 Live Matches", sizes["2026_live"]),
        ("Combined Matches", sizes["combined"]),
        ("Best Bucket", conclusion["highest_accuracy_bucket"]),
        ("Best Accuracy", f"{conclusion['highest_accuracy']}%"),
    ]
    card_html = "".join(f"<div class='card'><span>{html.escape(str(label))}</span><strong>{html.escape(str(value))}</strong></div>" for label, value in cards)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Confidence Calibration Audit</title>
  <style>
    :root {{ color-scheme: dark; font-family:'Segoe UI',sans-serif; background:#07111f; color:#e7eef9; }}
    body {{ margin:0; padding:32px; background:radial-gradient(circle at top left,#0f766e,#07111f 42%,#040711); }}
    h1 {{ margin:0 0 8px; font-size:30px; }}
    h2 {{ margin-top:30px; color:#5eead4; }}
    .note {{ color:#a8b8ca; margin-bottom:24px; }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:14px; }}
    .card {{ border:1px solid rgba(148,163,184,.22); border-radius:18px; padding:18px; background:rgba(15,23,42,.72); }}
    .card span {{ display:block; color:#9fb3c8; font-size:13px; }}
    .card strong {{ display:block; margin-top:10px; font-size:24px; color:#f8fafc; }}
    table {{ width:100%; border-collapse:collapse; margin-top:12px; background:rgba(15,23,42,.68); }}
    th,td {{ padding:10px 11px; border-bottom:1px solid rgba(148,163,184,.16); text-align:left; font-size:13px; }}
    th {{ color:#99f6e4; background:rgba(30,41,59,.92); }}
  </style>
</head>
<body>
  <h1>Confidence Calibration Audit</h1>
  <p class="note">只读审计：按信心分桶统计 2018、2022、2026 已结算样本，不修改任何模型、权重、算法或预测逻辑。</p>
  <section class="cards">{card_html}</section>
  <h2>Final Conclusion</h2>{_html_table([conclusion])}
  <h2>Combined Bucket Analysis</h2>{_html_table(report['combined_bucket_analysis'])}
  <h2>All Sample Bucket Analysis</h2>{_html_table(report['confidence_bucket_analysis'])}
</body>
</html>
"""


def write_confidence_calibration_outputs(report: dict, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "confidence_calibration_csv": output_dir / "confidence_calibration.csv",
        "confidence_calibration_summary_json": output_dir / "confidence_calibration_summary.json",
        "confidence_calibration_dashboard_html": output_dir / "confidence_calibration_dashboard.html",
        "confidence_calibration_matches_csv": output_dir / "confidence_calibration_matches.csv",
    }
    _write_csv(paths["confidence_calibration_csv"], report["confidence_bucket_analysis"])
    _write_csv(paths["confidence_calibration_matches_csv"], report["matches"])
    paths["confidence_calibration_summary_json"].write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["confidence_calibration_dashboard_html"].write_text(_dashboard_html(report), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}
