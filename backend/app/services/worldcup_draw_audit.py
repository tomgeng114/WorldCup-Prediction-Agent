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
from app.services.market_vs_model_audit import ELITE_TEAMS, _result_team
from app.services.worldcup_historical_audit import _audit_stage, _market_favorite, _pick, _upset_probability, latest_run_for_years


DRAW_BUCKETS = (
    ("0-10%", 0, 10),
    ("10-20%", 10, 20),
    ("20-30%", 20, 30),
    ("30-40%", 30, 40),
    ("40%+", 40, None),
)


@dataclass(frozen=True)
class DrawAuditRow:
    match_id: int
    tournament_year: int
    match_date: str
    stage: str
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
    is_actual_draw: bool
    is_predicted_draw: bool
    is_correct_draw: bool
    is_missed_draw: bool
    odds_home: float | None
    odds_draw: float | None
    odds_away: float | None
    odds_spread: float | None


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


def _confidence_score(prediction: BacktestPrediction) -> float:
    probabilities = {
        "Home Win": prediction.home_win_probability,
        "Draw": prediction.draw_probability,
        "Away Win": prediction.away_win_probability,
    }
    return round(probabilities[prediction.predicted_result] * 100, 2)


def _odds_spread(odds: WorldCupOdds | None) -> float | None:
    if not odds:
        return None
    prices = [odds.home_win_odds, odds.draw_odds, odds.away_win_odds]
    if any(price is None or price <= 0 for price in prices):
        return None
    return round(max(prices) - min(prices), 4)


def _audit_rows(raw_rows: list[tuple[BacktestPrediction, WorldCupMatch, WorldCupOdds | None]]) -> list[DrawAuditRow]:
    output: list[DrawAuditRow] = []
    for prediction, match, odds in raw_rows:
        probabilities = {
            "Home Win": prediction.home_win_probability,
            "Draw": prediction.draw_probability,
            "Away Win": prediction.away_win_probability,
        }
        market_favorite = _market_favorite(odds)
        model_favorite = _pick(probabilities)
        output.append(
            DrawAuditRow(
                match_id=match.id,
                tournament_year=match.tournament_year,
                match_date=match.match_date.isoformat(),
                stage=_audit_stage(match.stage),
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
                confidence_score=_confidence_score(prediction),
                upset_probability=_upset_probability(prediction, market_favorite),
                market_favorite=market_favorite,
                market_favorite_team=None if market_favorite is None else _result_team(market_favorite, match.home_team, match.away_team),
                model_favorite=model_favorite,
                model_favorite_team=_result_team(model_favorite, match.home_team, match.away_team),
                is_actual_draw=match.result == "Draw",
                is_predicted_draw=prediction.predicted_result == "Draw",
                is_correct_draw=match.result == "Draw" and prediction.predicted_result == "Draw",
                is_missed_draw=match.result == "Draw" and prediction.predicted_result != "Draw",
                odds_home=odds.home_win_odds if odds else None,
                odds_draw=odds.draw_odds if odds else None,
                odds_away=odds.away_win_odds if odds else None,
                odds_spread=_odds_spread(odds),
            )
        )
    return output


def _draw_summary(rows: list[DrawAuditRow]) -> dict:
    actual_draws = sum(row.is_actual_draw for row in rows)
    predicted_draws = sum(row.is_predicted_draw for row in rows)
    correct_draws = sum(row.is_correct_draw for row in rows)
    recall = _pct(correct_draws, actual_draws)
    precision = _pct(correct_draws, predicted_draws)
    f1 = round(2 * precision * recall / (precision + recall), 2) if precision + recall else 0.0
    return {
        "total_matches": len(rows),
        "actual_draws": actual_draws,
        "predicted_draws": predicted_draws,
        "correct_draws": correct_draws,
        "draw_recall": recall,
        "draw_precision": precision,
        "draw_f1_score": f1,
    }


def _draw_error_types(rows: list[DrawAuditRow]) -> list[dict]:
    total_errors = sum((row.is_actual_draw and not row.is_predicted_draw) or (row.is_predicted_draw and not row.is_actual_draw) for row in rows)
    cases = [
        ("A_home_win_predicted_actual_draw", "预测主胜实际平局", [row for row in rows if row.predicted_result == "Home Win" and row.actual_result == "Draw"]),
        ("B_away_win_predicted_actual_draw", "预测客胜实际平局", [row for row in rows if row.predicted_result == "Away Win" and row.actual_result == "Draw"]),
        ("C_draw_predicted_actual_home_win", "预测平局实际主胜", [row for row in rows if row.predicted_result == "Draw" and row.actual_result == "Home Win"]),
        ("D_draw_predicted_actual_away_win", "预测平局实际客胜", [row for row in rows if row.predicted_result == "Draw" and row.actual_result == "Away Win"]),
    ]
    return [
        {
            "error_type": key,
            "label": label,
            "matches": len(selected),
            "percentage": _pct(len(selected), total_errors),
        }
        for key, label, selected in cases
    ]


def _stage_draw_analysis(rows: list[DrawAuditRow]) -> list[dict]:
    stages = ("Group Stage", "Round of 16", "Quarter-finals", "Semi-finals", "Third-place match", "Final")
    output = []
    for stage in stages:
        selected = [row for row in rows if row.stage == stage]
        if selected:
            summary = _draw_summary(selected)
            output.append({"stage": stage, **summary})
    return output


def _elite_market_favorite_draws(rows: list[DrawAuditRow]) -> list[dict]:
    output = []
    for team in ELITE_TEAMS:
        selected = [row for row in rows if row.market_favorite_team == team]
        wins = sum(row.actual_result_team == team for row in selected)
        draws = sum(row.actual_result == "Draw" for row in selected)
        losses = len(selected) - wins - draws
        output.append({"team": team, "market_favorite_matches": len(selected), "wins": wins, "draws": draws, "losses": losses})
    return output


def _draw_probability_calibration(rows: list[DrawAuditRow]) -> list[dict]:
    output = []
    for label, lower, upper in DRAW_BUCKETS:
        selected = [row for row in rows if row.draw_probability >= lower and (upper is None or row.draw_probability < upper)]
        output.append(
            {
                "bucket": label,
                "matches": len(selected),
                "average_draw_probability": round(mean([row.draw_probability for row in selected]), 2) if selected else None,
                "actual_draws": sum(row.is_actual_draw for row in selected),
                "actual_draw_rate": _pct(sum(row.is_actual_draw for row in selected), len(selected)),
            }
        )
    return output


def _failed_draw_pattern(rows: list[DrawAuditRow]) -> dict:
    failed = [row for row in rows if row.is_missed_draw]
    odds_spreads = [row.odds_spread for row in failed if row.odds_spread is not None]
    return {
        "failed_draw_matches": len(failed),
        "average_draw_probability": round(mean([row.draw_probability for row in failed]), 2) if failed else None,
        "average_confidence_score": round(mean([row.confidence_score for row in failed]), 2) if failed else None,
        "average_upset_probability": round(mean([row.upset_probability for row in failed]), 2) if failed else None,
        "average_odds_spread": round(mean(odds_spreads), 4) if odds_spreads else None,
        "average_elo_diff": None,
        "average_xg_diff": None,
        "unavailable_fields_note": "ELO difference and xG difference are not stored in the current backtest prediction rows, so they are reported as null instead of estimated.",
    }


def _draw_rule_analysis(rows: list[DrawAuditRow]) -> list[dict]:
    rules = [
        ("A_draw_probability_gte_25", lambda row: row.draw_probability >= 25),
        ("B_draw_probability_gte_30", lambda row: row.draw_probability >= 30),
        ("C_draw_probability_gte_35", lambda row: row.draw_probability >= 35),
        ("D_draw_probability_rank_top2", lambda row: row.draw_probability >= sorted([row.home_probability, row.draw_probability, row.away_probability], reverse=True)[1]),
    ]
    output = []
    for name, predicate in rules:
        selected = [row for row in rows if predicate(row)]
        output.append(
            {
                "rule": name,
                "matches": len(selected),
                "hits_if_recommended_draw": sum(row.is_actual_draw for row in selected),
                "hit_rate": _pct(sum(row.is_actual_draw for row in selected), len(selected)),
                "actual_draw_rate": _pct(sum(row.is_actual_draw for row in selected), len(selected)),
            }
        )
    return output


def _best_rule(rule_rows: list[dict]) -> dict | None:
    valid = [row for row in rule_rows if row["matches"]]
    return max(valid, key=lambda row: (row["hit_rate"], row["matches"]), default=None)


def _conclusion(report: dict) -> dict:
    summary = report["draw_audit_summary"]
    total_pred_rate = _pct(summary["predicted_draws"], summary["total_matches"])
    total_actual_rate = _pct(summary["actual_draws"], summary["total_matches"])
    error_rows = report["draw_error_types"]
    missed_draws = error_rows[0]["matches"] + error_rows[1]["matches"]
    false_draws = error_rows[2]["matches"] + error_rows[3]["matches"]
    best_rule = _best_rule(report["draw_rule_analysis"])
    bucket_with_highest_rate = _best_rule(
        [
            {
                "rule": row["bucket"],
                "matches": row["matches"],
                "hit_rate": row["actual_draw_rate"],
            }
            for row in report["draw_probability_calibration"]
        ]
    )
    return {
        "model_underestimates_draws": total_pred_rate < total_actual_rate,
        "actual_draw_rate": total_actual_rate,
        "predicted_draw_rate": total_pred_rate,
        "draw_is_major_error_source": missed_draws > false_draws,
        "missed_draws": missed_draws,
        "false_draw_predictions": false_draws,
        "most_draw_prone_bucket": None if not bucket_with_highest_rate else bucket_with_highest_rate["rule"],
        "best_draw_rule": None if not best_rule else best_rule["rule"],
        "best_draw_rule_hit_rate": None if not best_rule else best_rule["hit_rate"],
        "draw_warning_pool_recommended": bool(best_rule and best_rule["matches"] >= 10 and best_rule["hit_rate"] >= total_actual_rate),
    }


def build_worldcup_draw_audit(db: Session, years: list[int]) -> dict:
    run = latest_run_for_years(db, years)
    if run is None:
        raise RuntimeError(f"No backtest run found for years={years}. Run historical audit first.")
    rows = _audit_rows(_rows_for_run(db, run.id))
    report = {
        "metadata": {
            "run_id": run.id,
            "years": years,
            "scope": "2018 and 2022 FIFA World Cup draw audit",
            "model_change": "none",
            "note": "This audit only reads existing backtest rows and odds. It does not modify models, weights, algorithms, Poisson, Monte Carlo, Dixon-Coles, confidence, upset, or recommendations.",
        },
        "draw_audit_summary": _draw_summary(rows),
        "draw_error_types": _draw_error_types(rows),
        "stage_draw_analysis": _stage_draw_analysis(rows),
        "elite_market_favorite_draws": _elite_market_favorite_draws(rows),
        "draw_probability_calibration": _draw_probability_calibration(rows),
        "draw_error_cases": [row.__dict__ for row in rows if row.is_missed_draw],
        "failed_draw_pattern": _failed_draw_pattern(rows),
        "draw_rule_analysis": _draw_rule_analysis(rows),
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
    summary = report["draw_audit_summary"]
    conclusion = report["conclusion"]
    cards = [
        ("Total Matches", summary["total_matches"]),
        ("Actual Draws", summary["actual_draws"]),
        ("Predicted Draws", summary["predicted_draws"]),
        ("Correct Draws", summary["correct_draws"]),
        ("Draw Recall", f"{summary['draw_recall']}%"),
        ("Draw Precision", f"{summary['draw_precision']}%"),
        ("Draw F1", f"{summary['draw_f1_score']}%"),
    ]
    card_html = "".join(f"<div class='card'><span>{html.escape(str(label))}</span><strong>{html.escape(str(value))}</strong></div>" for label, value in cards)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>World Cup Draw Audit</title>
  <style>
    :root {{ color-scheme: dark; font-family:'Segoe UI',sans-serif; background:#07111f; color:#e7eef9; }}
    body {{ margin:0; padding:32px; background:radial-gradient(circle at top left,#365314,#07111f 42%,#040711); }}
    h1 {{ margin:0 0 8px; font-size:30px; }}
    h2 {{ margin-top:30px; color:#bef264; }}
    .note {{ color:#a8b8ca; margin-bottom:24px; }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:14px; }}
    .card {{ border:1px solid rgba(148,163,184,.22); border-radius:18px; padding:18px; background:rgba(15,23,42,.72); }}
    .card span {{ display:block; color:#9fb3c8; font-size:13px; }}
    .card strong {{ display:block; margin-top:10px; font-size:24px; color:#f8fafc; }}
    table {{ width:100%; border-collapse:collapse; margin-top:12px; background:rgba(15,23,42,.68); }}
    th,td {{ padding:10px 11px; border-bottom:1px solid rgba(148,163,184,.16); text-align:left; font-size:13px; }}
    th {{ color:#d9f99d; background:rgba(30,41,59,.92); }}
  </style>
</head>
<body>
  <h1>World Cup Draw Audit</h1>
  <p class="note">只读审计：分析 2018+2022 世界杯平局识别，不修改任何模型、权重、算法或预测逻辑。</p>
  <section class="cards">{card_html}</section>
  <h2>Final Conclusion</h2>{_html_table([conclusion])}
  <h2>Draw Error Types</h2>{_html_table(report['draw_error_types'])}
  <h2>Stage Draw Analysis</h2>{_html_table(report['stage_draw_analysis'])}
  <h2>Elite Market Favorite Draws</h2>{_html_table(report['elite_market_favorite_draws'])}
  <h2>Draw Probability Calibration</h2>{_html_table(report['draw_probability_calibration'])}
  <h2>Failed Draw Pattern</h2>{_html_table([report['failed_draw_pattern']])}
  <h2>Draw Rule Analysis</h2>{_html_table(report['draw_rule_analysis'])}
  <h2>Draw Error Cases</h2>{_html_table(report['draw_error_cases'])}
</body>
</html>
"""


def write_worldcup_draw_audit_outputs(report: dict, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    draw_audit_rows = (
        [{"section": "summary", **report["draw_audit_summary"]}]
        + [{"section": "error_type", **row} for row in report["draw_error_types"]]
        + [{"section": "stage", **row} for row in report["stage_draw_analysis"]]
        + [{"section": "elite_favorite", **row} for row in report["elite_market_favorite_draws"]]
        + [{"section": "rule", **row} for row in report["draw_rule_analysis"]]
        + [{"section": "conclusion", **report["conclusion"]}]
    )
    paths = {
        "draw_audit_csv": output_dir / "draw_audit.csv",
        "draw_error_cases_csv": output_dir / "draw_error_cases.csv",
        "draw_probability_calibration_csv": output_dir / "draw_probability_calibration.csv",
        "draw_pattern_analysis_csv": output_dir / "draw_pattern_analysis.csv",
        "draw_dashboard_html": output_dir / "draw_dashboard.html",
        "draw_summary_json": output_dir / "draw_summary.json",
    }
    _write_csv(paths["draw_audit_csv"], draw_audit_rows)
    _write_csv(paths["draw_error_cases_csv"], report["draw_error_cases"])
    _write_csv(paths["draw_probability_calibration_csv"], report["draw_probability_calibration"])
    _write_csv(paths["draw_pattern_analysis_csv"], [report["failed_draw_pattern"]])
    paths["draw_summary_json"].write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["draw_dashboard_html"].write_text(_dashboard_html(report), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}
