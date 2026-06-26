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
from app.services.worldcup_historical_audit import (
    _audit_stage,
    _market_favorite,
    _pick,
    _upset_probability,
    latest_run_for_years,
)


STRONG_TEAMS = ("Brazil", "Argentina", "France", "England", "Spain", "Germany", "Portugal", "Netherlands")
DRAW_PROBABILITY_BUCKETS = (
    ("<20%", None, 20),
    ("20-25%", 20, 25),
    ("25-30%", 25, 30),
    ("30-35%", 30, 35),
    ("35%+", 35, None),
)
GOAL_BUCKET_LABELS = ("0 goals", "1 goal", "2 goals", "3 goals", "4+ goals")


@dataclass(frozen=True)
class DrawMissRow:
    match_id: int
    year: int
    match_date: str
    stage: str
    match: str
    home_team: str
    away_team: str
    predicted_result: str
    predicted_result_team: str
    actual_result: str
    home_probability: float
    draw_probability: float
    away_probability: float
    confidence_score: float
    upset_probability: float
    market_favorite: str | None
    market_favorite_team: str | None
    model_favorite: str
    model_favorite_team: str
    top1_score: str
    top2_score: str | None
    top3_score: str | None
    top3_available: bool
    top3_has_draw_score: bool
    top1_not_draw_but_top2_or_top3_has_draw: bool
    predicted_total_goals: int
    predicted_total_goals_bucket: str
    actual_score: str
    actual_total_goals: int
    actual_total_goals_bucket: str
    both_teams_to_score_recommendation: str | None
    actual_btts: str


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


def _goal_bucket(total_goals: int) -> str:
    if total_goals <= 0:
        return "0 goals"
    if total_goals == 1:
        return "1 goal"
    if total_goals == 2:
        return "2 goals"
    if total_goals == 3:
        return "3 goals"
    return "4+ goals"


def _is_draw_score(score: str | None) -> bool:
    if not score or "-" not in score:
        return False
    try:
        home, away = [int(part) for part in score.split("-", 1)]
    except ValueError:
        return False
    return home == away


def _confidence_score(prediction: BacktestPrediction) -> float:
    probabilities = {
        "Home Win": prediction.home_win_probability,
        "Draw": prediction.draw_probability,
        "Away Win": prediction.away_win_probability,
    }
    return round(probabilities[prediction.predicted_result] * 100, 2)


def _draw_miss_rows(raw_rows: list[tuple[BacktestPrediction, WorldCupMatch, WorldCupOdds | None]]) -> list[DrawMissRow]:
    output: list[DrawMissRow] = []
    for prediction, match, odds in raw_rows:
        if match.result != "Draw" or prediction.predicted_result == "Draw":
            continue

        probabilities = {
            "Home Win": prediction.home_win_probability,
            "Draw": prediction.draw_probability,
            "Away Win": prediction.away_win_probability,
        }
        market_favorite = _market_favorite(odds)
        model_favorite = _pick(probabilities)

        # Historical 2018/2022 backtest rows store only Top1 predicted_score.
        top1 = prediction.predicted_score
        top2 = None
        top3 = None
        draw_score_flags = [_is_draw_score(score) for score in (top1, top2, top3)]

        actual_score = f"{match.home_score}-{match.away_score}"
        actual_btts = "Yes" if match.home_score > 0 and match.away_score > 0 else "No"
        output.append(
            DrawMissRow(
                match_id=match.id,
                year=match.tournament_year,
                match_date=match.match_date.isoformat(),
                stage=_audit_stage(match.stage),
                match=f"{match.home_team} vs {match.away_team}",
                home_team=match.home_team,
                away_team=match.away_team,
                predicted_result=prediction.predicted_result,
                predicted_result_team=_result_team(prediction.predicted_result, match.home_team, match.away_team),
                actual_result=match.result,
                home_probability=round(prediction.home_win_probability * 100, 2),
                draw_probability=round(prediction.draw_probability * 100, 2),
                away_probability=round(prediction.away_win_probability * 100, 2),
                confidence_score=_confidence_score(prediction),
                upset_probability=_upset_probability(prediction, market_favorite),
                market_favorite=market_favorite,
                market_favorite_team=None if market_favorite is None else _result_team(market_favorite, match.home_team, match.away_team),
                model_favorite=model_favorite,
                model_favorite_team=_result_team(model_favorite, match.home_team, match.away_team),
                top1_score=top1,
                top2_score=top2,
                top3_score=top3,
                top3_available=False,
                top3_has_draw_score=any(draw_score_flags),
                top1_not_draw_but_top2_or_top3_has_draw=(not draw_score_flags[0]) and any(draw_score_flags[1:]),
                predicted_total_goals=prediction.predicted_total_goals,
                predicted_total_goals_bucket=_goal_bucket(prediction.predicted_total_goals),
                actual_score=actual_score,
                actual_total_goals=match.total_goals,
                actual_total_goals_bucket=_goal_bucket(match.total_goals),
                both_teams_to_score_recommendation=None,
                actual_btts=actual_btts,
            )
        )
    return output


def _draw_probability_distribution(rows: list[DrawMissRow]) -> list[dict]:
    output = []
    total = len(rows)
    for label, lower, upper in DRAW_PROBABILITY_BUCKETS:
        selected = [
            row
            for row in rows
            if (lower is None or row.draw_probability >= lower) and (upper is None or row.draw_probability < upper)
        ]
        output.append(
            {
                "pattern": "draw_probability_distribution",
                "bucket": label,
                "matches": len(selected),
                "percentage": _pct(len(selected), total),
            }
        )
    return output


def _top_score_patterns(rows: list[DrawMissRow]) -> list[dict]:
    total = len(rows)
    has_draw = [row for row in rows if row.top3_has_draw_score]
    no_draw = [row for row in rows if not row.top3_has_draw_score]
    top2_or_top3_draw = [row for row in rows if row.top1_not_draw_but_top2_or_top3_has_draw]
    unavailable = sum(not row.top3_available for row in rows)
    return [
        {"pattern": "top3_has_draw_score", "bucket": "Yes", "matches": len(has_draw), "percentage": _pct(len(has_draw), total)},
        {"pattern": "top3_has_draw_score", "bucket": "No", "matches": len(no_draw), "percentage": _pct(len(no_draw), total)},
        {
            "pattern": "top1_not_draw_but_top2_or_top3_has_draw",
            "bucket": "Yes",
            "matches": len(top2_or_top3_draw),
            "percentage": _pct(len(top2_or_top3_draw), total),
        },
        {
            "pattern": "historical_top3_availability",
            "bucket": "Unavailable",
            "matches": unavailable,
            "percentage": _pct(unavailable, total),
            "note": "2018/2022 backtest rows store Top1 predicted_score only; Top2/Top3 are not reconstructed.",
        },
    ]


def _goal_patterns(rows: list[DrawMissRow]) -> list[dict]:
    output = []
    total = len(rows)
    for label in GOAL_BUCKET_LABELS:
        predicted = [row for row in rows if row.predicted_total_goals_bucket == label]
        actual = [row for row in rows if row.actual_total_goals_bucket == label]
        output.append({"pattern": "predicted_total_goals", "bucket": label, "matches": len(predicted), "percentage": _pct(len(predicted), total)})
        output.append({"pattern": "actual_total_goals", "bucket": label, "matches": len(actual), "percentage": _pct(len(actual), total)})
    return output


def _btts_patterns(rows: list[DrawMissRow]) -> list[dict]:
    total = len(rows)
    actual_yes = [row for row in rows if row.actual_btts == "Yes"]
    actual_no = [row for row in rows if row.actual_btts == "No"]
    return [
        {
            "pattern": "btts_recommendation",
            "bucket": "Unavailable",
            "matches": total,
            "percentage": 100.0 if total else 0.0,
            "note": "Historical backtest rows do not store BTTS recommendation.",
        },
        {"pattern": "actual_btts", "bucket": "Yes", "matches": len(actual_yes), "percentage": _pct(len(actual_yes), total)},
        {"pattern": "actual_btts", "bucket": "No", "matches": len(actual_no), "percentage": _pct(len(actual_no), total)},
    ]


def _strong_team_patterns(all_rows: list[tuple[BacktestPrediction, WorldCupMatch, WorldCupOdds | None]]) -> list[dict]:
    output = []
    for team in STRONG_TEAMS:
        market_favorite_rows = [
            (prediction, match, odds)
            for prediction, match, odds in all_rows
            if _market_favorite(odds) in {"Home Win", "Away Win"}
            and _result_team(_market_favorite(odds), match.home_team, match.away_team) == team
        ]
        actual_draw_rows = [(prediction, match, odds) for prediction, match, odds in market_favorite_rows if match.result == "Draw"]
        predicted_draw_rows = [(prediction, match, odds) for prediction, match, odds in actual_draw_rows if prediction.predicted_result == "Draw"]
        missed_draw_rows = [(prediction, match, odds) for prediction, match, odds in actual_draw_rows if prediction.predicted_result != "Draw"]
        output.append(
            {
                "team": team,
                "market_favorite_matches": len(market_favorite_rows),
                "actual_draws_as_market_favorite": len(actual_draw_rows),
                "model_predicted_draws": len(predicted_draw_rows),
                "missed_draws": len(missed_draw_rows),
                "miss_rate": _pct(len(missed_draw_rows), len(actual_draw_rows)),
            }
        )
    return output


def _rule_coverage(rows: list[DrawMissRow]) -> list[dict]:
    total = len(rows)
    rules = [
        ("Rule A", "Draw Probability >= 25%", lambda row: row.draw_probability >= 25),
        ("Rule B", "Draw Probability >= 30%", lambda row: row.draw_probability >= 30),
        ("Rule C", "Top3 contains draw score", lambda row: row.top3_has_draw_score),
        ("Rule D", "Predicted total goals is 2 or 3", lambda row: row.predicted_total_goals in {2, 3}),
        (
            "Rule E",
            "Strong market favorite and upset probability >= 45",
            lambda row: row.market_favorite_team in STRONG_TEAMS and row.upset_probability >= 45,
        ),
    ]
    return [
        {
            "rule": rule,
            "description": description,
            "covered_missed_draws": sum(1 for row in rows if predicate(row)),
            "coverage": _pct(sum(1 for row in rows if predicate(row)), total),
        }
        for rule, description, predicate in rules
    ]


def _patterns(rows: list[DrawMissRow], all_rows: list[tuple[BacktestPrediction, WorldCupMatch, WorldCupOdds | None]]) -> dict:
    return {
        "draw_probability_distribution": _draw_probability_distribution(rows),
        "top_score_patterns": _top_score_patterns(rows),
        "goal_patterns": _goal_patterns(rows),
        "btts_patterns": _btts_patterns(rows),
        "strong_team_patterns": _strong_team_patterns(all_rows),
        "rule_coverage": _rule_coverage(rows),
    }


def _flat_patterns(patterns: dict) -> list[dict]:
    rows = []
    for section, payload in patterns.items():
        for item in payload:
            rows.append({"section": section, **item})
    return rows


def _best_rule(rule_rows: list[dict]) -> dict | None:
    valid = [row for row in rule_rows if row["covered_missed_draws"]]
    return max(valid, key=lambda row: (row["coverage"], row["covered_missed_draws"]), default=None)


def _conclusion(rows: list[DrawMissRow], patterns: dict) -> dict:
    draw_dist = patterns["draw_probability_distribution"]
    best_draw_bucket = max(draw_dist, key=lambda row: row["matches"], default=None)
    best_rule = _best_rule(patterns["rule_coverage"])
    sensed_rows = [row for row in rows if row.draw_probability >= 25 or row.top3_has_draw_score]
    actual_goal_2_or_3 = [row for row in rows if row.actual_total_goals in {2, 3}]
    predicted_goal_2_or_3 = [row for row in rows if row.predicted_total_goals in {2, 3}]
    actual_btts_yes = [row for row in rows if row.actual_btts == "Yes"]
    return {
        "total_missed_draws": len(rows),
        "most_common_draw_probability_bucket": None if not best_draw_bucket else best_draw_bucket["bucket"],
        "most_common_draw_probability_bucket_matches": 0 if not best_draw_bucket else best_draw_bucket["matches"],
        "predicted_2_or_3_goal_matches": len(predicted_goal_2_or_3),
        "predicted_2_or_3_goal_share": _pct(len(predicted_goal_2_or_3), len(rows)),
        "actual_2_or_3_goal_matches": len(actual_goal_2_or_3),
        "actual_2_or_3_goal_share": _pct(len(actual_goal_2_or_3), len(rows)),
        "actual_btts_yes_matches": len(actual_btts_yes),
        "actual_btts_yes_share": _pct(len(actual_btts_yes), len(rows)),
        "best_rule": None if not best_rule else best_rule["rule"],
        "best_rule_description": None if not best_rule else best_rule["description"],
        "best_rule_coverage": None if not best_rule else best_rule["coverage"],
        "model_sensed_draw_but_did_not_pick_draw_matches": len(sensed_rows),
        "model_sensed_draw_but_did_not_pick_draw_share": _pct(len(sensed_rows), len(rows)),
        "top3_limit_note": "Historical 2018/2022 backtest rows do not store Top2/Top3 or BTTS recommendation, so these fields are unavailable rather than reconstructed.",
    }


def build_draw_miss_deep_audit(db: Session, years: list[int]) -> dict:
    run = latest_run_for_years(db, years)
    if run is None:
        raise RuntimeError(f"No backtest run found for years={years}. Run historical audit first.")
    all_rows = _rows_for_run(db, run.id)
    rows = _draw_miss_rows(all_rows)
    patterns = _patterns(rows, all_rows)
    return {
        "metadata": {
            "run_id": run.id,
            "years": years,
            "scope": "Actual result is Draw, but final model pick is not Draw",
            "model_change": "none",
            "note": "This audit only reads existing historical backtest rows and odds. It does not modify models, weights, algorithms, odds fusion, Poisson, Monte Carlo, Dixon-Coles, confidence, upset, recommendations, or frontend pages.",
        },
        "summary": _conclusion(rows, patterns),
        "draw_miss_cases": [row.__dict__ for row in rows],
        "patterns": patterns,
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
    cards = [
        ("Missed Draws", summary["total_missed_draws"]),
        ("Main Draw Prob Bucket", summary["most_common_draw_probability_bucket"]),
        ("Predicted 2/3 Goal Share", f"{summary['predicted_2_or_3_goal_share']}%"),
        ("Actual BTTS Yes Share", f"{summary['actual_btts_yes_share']}%"),
        ("Best Rule", summary["best_rule"]),
        ("Best Rule Coverage", f"{summary['best_rule_coverage']}%"),
    ]
    card_html = "".join(
        f"<div class='card'><span>{html.escape(str(label))}</span><strong>{html.escape(str(value))}</strong></div>"
        for label, value in cards
    )
    patterns = report["patterns"]
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Draw Miss Deep Audit</title>
  <style>
    :root {{ color-scheme: dark; font-family:'Segoe UI',sans-serif; background:#07111f; color:#e7eef9; }}
    body {{ margin:0; padding:32px; background:radial-gradient(circle at top left,#14532d,#07111f 42%,#040711); }}
    h1 {{ margin:0 0 8px; font-size:30px; }}
    h2 {{ margin-top:30px; color:#86efac; }}
    .note {{ color:#a8b8ca; margin-bottom:24px; }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:14px; }}
    .card {{ border:1px solid rgba(148,163,184,.22); border-radius:18px; padding:18px; background:rgba(15,23,42,.72); }}
    .card span {{ display:block; color:#9fb3c8; font-size:13px; }}
    .card strong {{ display:block; margin-top:10px; font-size:23px; color:#f8fafc; }}
    table {{ width:100%; border-collapse:collapse; margin-top:12px; background:rgba(15,23,42,.68); }}
    th,td {{ padding:10px 11px; border-bottom:1px solid rgba(148,163,184,.16); text-align:left; font-size:13px; }}
    th {{ color:#bbf7d0; background:rgba(30,41,59,.92); }}
  </style>
</head>
<body>
  <h1>Draw Miss Deep Audit</h1>
  <p class="note">Read-only audit: actual draws where the final model pick was not draw. No model, weight, algorithm, recommendation, or frontend logic was changed.</p>
  <section class="cards">{card_html}</section>
  <h2>Summary</h2>{_html_table([summary])}
  <h2>Rule Coverage</h2>{_html_table(patterns['rule_coverage'])}
  <h2>Draw Probability Distribution</h2>{_html_table(patterns['draw_probability_distribution'])}
  <h2>Top Score Patterns</h2>{_html_table(patterns['top_score_patterns'])}
  <h2>Goal Patterns</h2>{_html_table(patterns['goal_patterns'])}
  <h2>BTTS Patterns</h2>{_html_table(patterns['btts_patterns'])}
  <h2>Strong Team Patterns</h2>{_html_table(patterns['strong_team_patterns'])}
  <h2>Draw Miss Cases</h2>{_html_table(report['draw_miss_cases'])}
</body>
</html>
"""


def write_draw_miss_deep_outputs(report: dict, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "draw_miss_deep_audit_csv": output_dir / "draw_miss_deep_audit.csv",
        "draw_miss_patterns_csv": output_dir / "draw_miss_patterns.csv",
        "draw_miss_summary_json": output_dir / "draw_miss_summary.json",
        "draw_miss_dashboard_html": output_dir / "draw_miss_dashboard.html",
    }
    _write_csv(paths["draw_miss_deep_audit_csv"], report["draw_miss_cases"])
    _write_csv(paths["draw_miss_patterns_csv"], _flat_patterns(report["patterns"]))
    paths["draw_miss_summary_json"].write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["draw_miss_dashboard_html"].write_text(_dashboard_html(report), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}
