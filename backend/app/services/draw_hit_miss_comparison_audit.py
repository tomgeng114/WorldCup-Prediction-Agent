from __future__ import annotations

import csv
import html
import json
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BacktestPrediction, WorldCupMatch, WorldCupOdds
from app.services.market_vs_model_audit import _result_team
from app.services.worldcup_historical_audit import (
    _audit_stage,
    _market_favorite,
    _pick,
    _upset_probability,
    latest_run_for_years,
)


NUMERIC_FEATURES = (
    "draw_probability",
    "home_probability",
    "away_probability",
    "home_away_probability_gap",
    "win_probability_gap",
    "market_odds_difference",
    "predicted_total_goals",
    "upset_probability",
    "confidence_score",
)

BUCKETS = (
    ("<20", None, 20),
    ("20-25", 20, 25),
    ("25-30", 25, 30),
    ("30-35", 30, 35),
    ("35+", 35, None),
)


@dataclass(frozen=True)
class DrawComparisonRow:
    group: str
    match_id: int
    year: int
    match_date: str
    stage: str
    stage_type: str
    match: str
    home_team: str
    away_team: str
    predicted_result: str
    predicted_result_team: str
    actual_result: str
    home_probability: float
    draw_probability: float
    away_probability: float
    home_away_probability_gap: float
    win_probability_gap: float
    elo_difference: float | None
    market_odds_difference: float | None
    expected_goals: float | None
    predicted_total_goals: int
    btts_recommendation: str | None
    market_favorite: str | None
    market_favorite_team: str | None
    market_favorite_status: str
    upset_probability: float
    predicted_score: str
    top3_score_distribution: str | None
    confidence_score: float


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


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _median(values: list[float]) -> float | None:
    return round(median(values), 2) if values else None


def _confidence_score(prediction: BacktestPrediction) -> float:
    probabilities = {
        "Home Win": prediction.home_win_probability,
        "Draw": prediction.draw_probability,
        "Away Win": prediction.away_win_probability,
    }
    return round(probabilities[prediction.predicted_result] * 100, 2)


def _market_odds_difference(odds: WorldCupOdds | None) -> float | None:
    if not odds:
        return None
    prices = [odds.home_win_odds, odds.draw_odds, odds.away_win_odds]
    if any(price is None or price <= 0 for price in prices):
        return None
    return round(max(prices) - min(prices), 4)


def _stage_type(stage: str) -> str:
    return "Group Stage" if stage == "Group Stage" else "Knockout Stage"


def _market_favorite_status(market_favorite: str | None, predicted_result: str) -> str:
    if market_favorite is None:
        return "Unavailable"
    if market_favorite == predicted_result:
        return "Market and model aligned"
    return "Market and model conflict"


def _comparison_rows(raw_rows: list[tuple[BacktestPrediction, WorldCupMatch, WorldCupOdds | None]]) -> list[DrawComparisonRow]:
    output: list[DrawComparisonRow] = []
    for prediction, match, odds in raw_rows:
        if match.result != "Draw":
            continue
        group = "A_hit_draw" if prediction.predicted_result == "Draw" else "B_missed_draw"
        home_probability = round(prediction.home_win_probability * 100, 2)
        draw_probability = round(prediction.draw_probability * 100, 2)
        away_probability = round(prediction.away_win_probability * 100, 2)
        market_favorite = _market_favorite(odds)
        stage = _audit_stage(match.stage)
        win_probability = max(home_probability, away_probability)
        output.append(
            DrawComparisonRow(
                group=group,
                match_id=match.id,
                year=match.tournament_year,
                match_date=match.match_date.isoformat(),
                stage=stage,
                stage_type=_stage_type(stage),
                match=f"{match.home_team} vs {match.away_team}",
                home_team=match.home_team,
                away_team=match.away_team,
                predicted_result=prediction.predicted_result,
                predicted_result_team=_result_team(prediction.predicted_result, match.home_team, match.away_team),
                actual_result=match.result,
                home_probability=home_probability,
                draw_probability=draw_probability,
                away_probability=away_probability,
                home_away_probability_gap=round(abs(home_probability - away_probability), 2),
                win_probability_gap=round(win_probability - draw_probability, 2),
                elo_difference=None,
                market_odds_difference=_market_odds_difference(odds),
                expected_goals=None,
                predicted_total_goals=prediction.predicted_total_goals,
                btts_recommendation=None,
                market_favorite=market_favorite,
                market_favorite_team=None if market_favorite is None else _result_team(market_favorite, match.home_team, match.away_team),
                market_favorite_status=_market_favorite_status(market_favorite, prediction.predicted_result),
                upset_probability=_upset_probability(prediction, market_favorite),
                predicted_score=prediction.predicted_score,
                top3_score_distribution=None,
                confidence_score=_confidence_score(prediction),
            )
        )
    return output


def _values(rows: list[DrawComparisonRow], feature: str) -> list[float]:
    values = [getattr(row, feature) for row in rows]
    return [float(value) for value in values if value is not None]


def _bucket_distribution(rows: list[DrawComparisonRow], feature: str) -> list[dict]:
    output = []
    total = len(rows)
    for label, lower, upper in BUCKETS:
        selected = [
            row
            for row in rows
            if getattr(row, feature) is not None
            and (lower is None or getattr(row, feature) >= lower)
            and (upper is None or getattr(row, feature) < upper)
        ]
        output.append({"feature": feature, "bucket": label, "matches": len(selected), "percentage": _pct(len(selected), total)})
    return output


def _numeric_summary(rows: list[DrawComparisonRow]) -> list[dict]:
    groups = {
        "A_hit_draw": [row for row in rows if row.group == "A_hit_draw"],
        "B_missed_draw": [row for row in rows if row.group == "B_missed_draw"],
    }
    output = []
    for feature in NUMERIC_FEATURES:
        for group, selected in groups.items():
            values = _values(selected, feature)
            output.append(
                {
                    "feature": feature,
                    "group": group,
                    "matches": len(selected),
                    "available_values": len(values),
                    "average": _mean(values),
                    "median": _median(values),
                    "min": round(min(values), 2) if values else None,
                    "max": round(max(values), 2) if values else None,
                }
            )
    return output


def _feature_differences(rows: list[DrawComparisonRow]) -> list[dict]:
    hit_rows = [row for row in rows if row.group == "A_hit_draw"]
    miss_rows = [row for row in rows if row.group == "B_missed_draw"]
    output = []
    for feature in NUMERIC_FEATURES:
        hit_values = _values(hit_rows, feature)
        miss_values = _values(miss_rows, feature)
        hit_avg = _mean(hit_values)
        miss_avg = _mean(miss_values)
        if hit_avg is None or miss_avg is None:
            difference = None
            abs_difference = None
        else:
            difference = round(hit_avg - miss_avg, 2)
            abs_difference = abs(difference)
        output.append(
            {
                "feature": feature,
                "hit_draw_avg": hit_avg,
                "miss_draw_avg": miss_avg,
                "difference_hit_minus_miss": difference,
                "absolute_difference": abs_difference,
                "hit_draw_median": _median(hit_values),
                "miss_draw_median": _median(miss_values),
                "available_note": "available" if hit_values and miss_values else "unavailable_or_partial",
            }
        )
    return sorted(output, key=lambda row: (-1 if row["absolute_difference"] is None else -row["absolute_difference"], row["feature"]))


def _categorical_summary(rows: list[DrawComparisonRow]) -> list[dict]:
    output = []
    for feature in ("stage_type", "market_favorite_status", "predicted_result", "predicted_score", "btts_recommendation", "top3_score_distribution"):
        for group in ("A_hit_draw", "B_missed_draw"):
            selected = [row for row in rows if row.group == group]
            total = len(selected)
            buckets = {}
            for row in selected:
                value = getattr(row, feature)
                key = "Unavailable" if value is None else str(value)
                buckets[key] = buckets.get(key, 0) + 1
            for value, count in sorted(buckets.items(), key=lambda item: (-item[1], item[0])):
                output.append({"feature": feature, "group": group, "value": value, "matches": count, "percentage": _pct(count, total)})
    return output


def _draw_probability_distribution(rows: list[DrawComparisonRow]) -> list[dict]:
    output = []
    for group in ("A_hit_draw", "B_missed_draw"):
        output.extend({"group": group, **item} for item in _bucket_distribution([row for row in rows if row.group == group], "draw_probability"))
    return output


def _profile(rows: list[DrawComparisonRow], group: str) -> dict:
    selected = [row for row in rows if row.group == group]
    if not selected:
        return {"group": group, "matches": 0}
    stage_counts = {}
    status_counts = {}
    score_counts = {}
    for row in selected:
        stage_counts[row.stage_type] = stage_counts.get(row.stage_type, 0) + 1
        status_counts[row.market_favorite_status] = status_counts.get(row.market_favorite_status, 0) + 1
        score_counts[row.predicted_score] = score_counts.get(row.predicted_score, 0) + 1
    return {
        "group": group,
        "matches": len(selected),
        "average_draw_probability": _mean(_values(selected, "draw_probability")),
        "median_draw_probability": _median(_values(selected, "draw_probability")),
        "average_win_probability_gap": _mean(_values(selected, "win_probability_gap")),
        "median_win_probability_gap": _median(_values(selected, "win_probability_gap")),
        "average_home_away_probability_gap": _mean(_values(selected, "home_away_probability_gap")),
        "average_predicted_total_goals": _mean(_values(selected, "predicted_total_goals")),
        "average_upset_probability": _mean(_values(selected, "upset_probability")),
        "average_confidence_score": _mean(_values(selected, "confidence_score")),
        "stage_mix": stage_counts,
        "market_favorite_status_mix": status_counts,
        "most_common_predicted_scores": [
            {"score": score, "matches": count, "percentage": _pct(count, len(selected))}
            for score, count in sorted(score_counts.items(), key=lambda item: (-item[1], item[0]))[:8]
        ],
    }


def _profile_contrast(rows: list[DrawComparisonRow]) -> dict:
    return {
        "hit_draw_profile": _profile(rows, "A_hit_draw"),
        "missed_draw_profile": _profile(rows, "B_missed_draw"),
        "note": "This is a descriptive audit profile only. It is not a new recommendation rule and is not written back into any model.",
    }


def _summary(rows: list[DrawComparisonRow], feature_rankings: list[dict]) -> dict:
    hit_rows = [row for row in rows if row.group == "A_hit_draw"]
    miss_rows = [row for row in rows if row.group == "B_missed_draw"]
    top5 = [row for row in feature_rankings if row["absolute_difference"] is not None][:5]
    unavailable = {
        "elo_difference": "not stored in current historical backtest rows",
        "expected_goals": "not stored in current historical backtest rows",
        "btts_recommendation": "not stored in current historical backtest rows",
        "top3_score_distribution": "not stored in current historical backtest rows",
    }
    return {
        "total_actual_draws": len(rows),
        "group_a_hit_draw_matches": len(hit_rows),
        "group_b_missed_draw_matches": len(miss_rows),
        "top5_distinguishing_features": top5,
        "unavailable_fields": unavailable,
        "model_change": "none",
    }


def build_draw_hit_miss_comparison_audit(db: Session, years: list[int]) -> dict:
    run = latest_run_for_years(db, years)
    if run is None:
        raise RuntimeError(f"No backtest run found for years={years}. Run historical audit first.")
    rows = _comparison_rows(_rows_for_run(db, run.id))
    numeric_summary = _numeric_summary(rows)
    feature_rankings = _feature_differences(rows)
    categorical_summary = _categorical_summary(rows)
    report = {
        "metadata": {
            "run_id": run.id,
            "years": years,
            "scope": "Actual draw samples split into hit draw vs missed draw",
            "model_change": "none",
            "note": "Read-only audit. No model, weights, algorithms, odds fusion, Poisson, Monte Carlo, Dixon-Coles, confidence, upset, recommendations, or frontend pages were changed.",
        },
        "summary": _summary(rows, feature_rankings),
        "profiles": _profile_contrast(rows),
        "numeric_summary": numeric_summary,
        "draw_probability_distribution": _draw_probability_distribution(rows),
        "categorical_summary": categorical_summary,
        "feature_rankings": feature_rankings,
        "cases": [row.__dict__ for row in rows],
    }
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
        "<tr>" + "".join(f"<td>{html.escape(json.dumps(row.get(header), ensure_ascii=False) if isinstance(row.get(header), (dict, list)) else str(row.get(header, '')))}</td>" for header in headers) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _dashboard_html(report: dict) -> str:
    summary = report["summary"]
    hit = report["profiles"]["hit_draw_profile"]
    miss = report["profiles"]["missed_draw_profile"]
    cards = [
        ("Actual Draws", summary["total_actual_draws"]),
        ("Hit Draw", summary["group_a_hit_draw_matches"]),
        ("Missed Draw", summary["group_b_missed_draw_matches"]),
        ("Hit Avg Draw Prob", f"{hit.get('average_draw_probability')}%"),
        ("Miss Avg Draw Prob", f"{miss.get('average_draw_probability')}%"),
        ("Top Feature", summary["top5_distinguishing_features"][0]["feature"] if summary["top5_distinguishing_features"] else "n/a"),
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
  <title>Draw Hit vs Miss Comparison Audit</title>
  <style>
    :root {{ color-scheme: dark; font-family:'Segoe UI',sans-serif; background:#07111f; color:#e7eef9; }}
    body {{ margin:0; padding:32px; background:radial-gradient(circle at top left,#0f766e,#07111f 44%,#030712); }}
    h1 {{ margin:0 0 8px; font-size:30px; }}
    h2 {{ margin-top:30px; color:#99f6e4; }}
    .note {{ color:#a8b8ca; margin-bottom:24px; }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:14px; }}
    .card {{ border:1px solid rgba(148,163,184,.22); border-radius:18px; padding:18px; background:rgba(15,23,42,.72); }}
    .card span {{ display:block; color:#9fb3c8; font-size:13px; }}
    .card strong {{ display:block; margin-top:10px; font-size:23px; color:#f8fafc; }}
    table {{ width:100%; border-collapse:collapse; margin-top:12px; background:rgba(15,23,42,.68); }}
    th,td {{ padding:10px 11px; border-bottom:1px solid rgba(148,163,184,.16); text-align:left; font-size:13px; vertical-align:top; }}
    th {{ color:#ccfbf1; background:rgba(30,41,59,.92); }}
  </style>
</head>
<body>
  <h1>Draw Hit vs Miss Comparison Audit</h1>
  <p class="note">Read-only audit: compares actual draws predicted as draw against actual draws missed by the model. No model or recommendation logic was changed.</p>
  <section class="cards">{card_html}</section>
  <h2>Summary</h2>{_html_table([summary])}
  <h2>Profiles</h2>{_html_table([hit, miss])}
  <h2>Feature Rankings</h2>{_html_table(report['feature_rankings'])}
  <h2>Numeric Summary</h2>{_html_table(report['numeric_summary'])}
  <h2>Draw Probability Distribution</h2>{_html_table(report['draw_probability_distribution'])}
  <h2>Categorical Summary</h2>{_html_table(report['categorical_summary'])}
  <h2>Cases</h2>{_html_table(report['cases'])}
</body>
</html>
"""


def write_draw_hit_miss_comparison_outputs(report: dict, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "draw_hit_miss_cases_csv": output_dir / "draw_hit_miss_cases.csv",
        "draw_hit_miss_numeric_summary_csv": output_dir / "draw_hit_miss_numeric_summary.csv",
        "draw_hit_miss_categorical_summary_csv": output_dir / "draw_hit_miss_categorical_summary.csv",
        "draw_hit_miss_feature_rankings_csv": output_dir / "draw_hit_miss_feature_rankings.csv",
        "draw_hit_miss_summary_json": output_dir / "draw_hit_miss_summary.json",
        "draw_hit_miss_dashboard_html": output_dir / "draw_hit_miss_dashboard.html",
    }
    _write_csv(paths["draw_hit_miss_cases_csv"], report["cases"])
    _write_csv(paths["draw_hit_miss_numeric_summary_csv"], report["numeric_summary"])
    _write_csv(paths["draw_hit_miss_categorical_summary_csv"], report["categorical_summary"])
    _write_csv(paths["draw_hit_miss_feature_rankings_csv"], report["feature_rankings"])
    paths["draw_hit_miss_summary_json"].write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["draw_hit_miss_dashboard_html"].write_text(_dashboard_html(report), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}
