from __future__ import annotations

import csv
import html
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BacktestPrediction, BacktestRun, WorldCupMatch, WorldCupOdds


RESULTS = ("Home Win", "Draw", "Away Win")
CONFIDENCE_BUCKETS = (
    ("0-40", 0, 40),
    ("40-50", 40, 50),
    ("50-60", 50, 60),
    ("60-70", 60, 70),
    ("70-80", 70, 80),
    ("80+", 80, None),
)
UPSET_BUCKETS = (
    ("0-20", 0, 20),
    ("20-40", 20, 40),
    ("40-50", 40, 50),
    ("50-60", 50, 60),
    ("60-70", 60, 70),
    ("70+", 70, None),
)
FILTER_STRATEGIES = (
    ("A_all_matches", None),
    ("B_filter_upset_gt_50", 50),
    ("C_filter_upset_gt_55", 55),
    ("D_filter_upset_gt_60", 60),
    ("E_filter_upset_gt_65", 65),
    ("F_filter_upset_gt_70", 70),
)
TOP_CONFIDENCE_BUCKETS = (
    ("Top 10%", 0.10),
    ("Top 20%", 0.20),
    ("Top 30%", 0.30),
    ("Top 50%", 0.50),
    ("All Matches", 1.00),
)
STAGE_ORDER = ("Group Stage", "Round of 16", "Quarter-finals", "Semi-finals", "Third-place match", "Final")
STRONG_TEAMS = ("Argentina", "France", "Brazil", "England", "Germany", "Spain", "Portugal", "Netherlands")


@dataclass(frozen=True)
class HistoricalAuditRow:
    match_id: int
    match_date: str
    tournament_year: int
    stage: str
    home_team: str
    away_team: str
    predicted_result: str
    actual_result: str
    predicted_score: str
    actual_score: str
    confidence_score: float
    upset_probability: float
    market_favorite: str | None
    model_favorite: str
    is_conflict_match: bool | None
    odds_home: float | None
    odds_draw: float | None
    odds_away: float | None
    handicap: float | None
    predicted_handicap_result: str | None
    actual_handicap_result: str | None
    result_hit: bool
    score_hit: bool
    handicap_hit: bool | None
    roi: float | None
    profit: float | None
    time_safe_valid: bool
    time_safe_note: str


def latest_run_for_years(db: Session, years: list[int]) -> BacktestRun | None:
    year_text = ",".join(str(year) for year in years)
    return db.scalar(
        select(BacktestRun)
        .where(BacktestRun.years == year_text)
        .order_by(BacktestRun.created_at.desc(), BacktestRun.id.desc())
    )


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


def _pick(probabilities: dict[str, float]) -> str:
    return max(probabilities, key=probabilities.get)


def _market_favorite(odds: WorldCupOdds | None) -> str | None:
    if not odds:
        return None
    prices = {
        "Home Win": odds.home_win_odds,
        "Draw": odds.draw_odds,
        "Away Win": odds.away_win_odds,
    }
    if any(value is None or value <= 0 for value in prices.values()):
        return None
    return min(prices, key=prices.get)


def _odds_for_pick(odds: WorldCupOdds | None, pick: str) -> float | None:
    if not odds:
        return None
    return {
        "Home Win": odds.home_win_odds,
        "Draw": odds.draw_odds,
        "Away Win": odds.away_win_odds,
    }.get(pick)


def _handicap_result(home_score: int, away_score: int, handicap: float) -> str:
    adjusted_home = home_score + handicap
    if adjusted_home > away_score:
        return "Home Win"
    if adjusted_home < away_score:
        return "Away Win"
    return "Draw"


def _parse_score(score: str) -> tuple[int, int] | None:
    try:
        home, away = score.split("-", 1)
        return int(home), int(away)
    except (AttributeError, ValueError):
        return None


def _confidence_score(prediction: BacktestPrediction) -> float:
    probability = {
        "Home Win": prediction.home_win_probability,
        "Draw": prediction.draw_probability,
        "Away Win": prediction.away_win_probability,
    }[prediction.predicted_result]
    return round(probability * 100, 2)


def _upset_probability(prediction: BacktestPrediction, market_favorite: str | None) -> float:
    probabilities = {
        "Home Win": prediction.home_win_probability,
        "Draw": prediction.draw_probability,
        "Away Win": prediction.away_win_probability,
    }
    if market_favorite in probabilities:
        return round((1 - probabilities[market_favorite]) * 100, 2)
    favorite = _pick(probabilities)
    underdogs = [result for result in RESULTS if result != favorite]
    return round(max(probabilities[result] for result in underdogs) * 100, 2)


def _time_safe_check(match: WorldCupMatch, odds: WorldCupOdds | None) -> tuple[bool, str]:
    if not odds:
        return False, "missing pre-match odds"
    if odds.captured_at and odds.captured_at >= match.match_date:
        return False, "odds captured after kickoff; ROI/market audit should be treated as invalid"
    if odds.captured_at is None:
        return True, "odds captured_at missing; accepted as imported historical pre-match odds, but timestamp cannot be independently verified"
    return True, "ok"


def _audit_stage(stage: str | None) -> str:
    if not stage:
        return "Unknown"
    normalized = stage.strip()
    if normalized.startswith("Matchday"):
        return "Group Stage"
    if normalized == "Match for third place":
        return "Third-place match"
    return normalized


def _to_audit_rows(raw_rows: Iterable[tuple[BacktestPrediction, WorldCupMatch, WorldCupOdds | None]]) -> list[HistoricalAuditRow]:
    rows: list[HistoricalAuditRow] = []
    for prediction, match, odds in raw_rows:
        probabilities = {
            "Home Win": prediction.home_win_probability,
            "Draw": prediction.draw_probability,
            "Away Win": prediction.away_win_probability,
        }
        model_favorite = _pick(probabilities)
        market_favorite = _market_favorite(odds)
        conflict = None if market_favorite is None else market_favorite != model_favorite
        confidence = _confidence_score(prediction)
        upset = _upset_probability(prediction, market_favorite)
        actual_score = f"{match.home_score}-{match.away_score}"
        result_hit = prediction.predicted_result == match.result
        score_hit = prediction.predicted_score == actual_score
        odds_price = _odds_for_pick(odds, prediction.predicted_result)
        time_safe_valid, time_safe_note = _time_safe_check(match, odds)
        profit = None
        roi = None
        if odds_price and time_safe_valid:
            profit = round(odds_price - 1, 4) if result_hit else -1.0
            roi = round(profit * 100, 2)

        predicted_handicap_result = None
        actual_handicap_result = None
        handicap_hit = None
        handicap = odds.handicap if odds else None
        predicted_score = _parse_score(prediction.predicted_score)
        if handicap is not None and predicted_score:
            predicted_handicap_result = _handicap_result(predicted_score[0], predicted_score[1], handicap)
            actual_handicap_result = _handicap_result(match.home_score, match.away_score, handicap)
            handicap_hit = predicted_handicap_result == actual_handicap_result

        rows.append(
            HistoricalAuditRow(
                match_id=match.id,
                match_date=match.match_date.isoformat(),
                tournament_year=match.tournament_year,
                stage=match.stage,
                home_team=match.home_team,
                away_team=match.away_team,
                predicted_result=prediction.predicted_result,
                actual_result=match.result,
                predicted_score=prediction.predicted_score,
                actual_score=actual_score,
                confidence_score=confidence,
                upset_probability=upset,
                market_favorite=market_favorite,
                model_favorite=model_favorite,
                is_conflict_match=conflict,
                odds_home=odds.home_win_odds if odds else None,
                odds_draw=odds.draw_odds if odds else None,
                odds_away=odds.away_win_odds if odds else None,
                handicap=handicap,
                predicted_handicap_result=predicted_handicap_result,
                actual_handicap_result=actual_handicap_result,
                result_hit=result_hit,
                score_hit=score_hit,
                handicap_hit=handicap_hit,
                roi=roi,
                profit=profit,
                time_safe_valid=time_safe_valid,
                time_safe_note=time_safe_note,
            )
        )
    return rows


def _pct(numerator: int | float, denominator: int | float) -> float:
    return round(numerator / denominator * 100, 2) if denominator else 0.0


def _summarize(rows: list[HistoricalAuditRow]) -> dict:
    total = len(rows)
    result_hits = sum(row.result_hit for row in rows)
    score_hits = sum(row.score_hit for row in rows)
    handicap_rows = [row for row in rows if row.handicap_hit is not None]
    handicap_hits = sum(bool(row.handicap_hit) for row in handicap_rows)
    roi_rows = [row for row in rows if row.profit is not None]
    profit = round(sum(row.profit or 0 for row in roi_rows), 4)
    return {
        "total_matches": total,
        "result_hits": result_hits,
        "result_accuracy": _pct(result_hits, total),
        "score_hits": score_hits,
        "score_accuracy": _pct(score_hits, total),
        "handicap_matches": len(handicap_rows),
        "handicap_hits": handicap_hits,
        "handicap_accuracy": _pct(handicap_hits, len(handicap_rows)),
        "average_roi": round(sum(row.roi or 0 for row in roi_rows) / len(roi_rows), 2) if roi_rows else None,
        "cumulative_roi": round(profit / len(roi_rows) * 100, 2) if roi_rows else None,
        "profit_units": profit,
        "win_rate": _pct(result_hits, total),
        "loss_rate": _pct(total - result_hits, total),
        "roi_sample_size": len(roi_rows),
        "time_safe_invalid_matches": sum(not row.time_safe_valid for row in rows),
    }


def _bucket_rows(rows: list[HistoricalAuditRow], buckets: tuple[tuple[str, float, float | None], ...], field: str) -> list[dict]:
    output = []
    for label, lower, upper in buckets:
        selected = [
            row
            for row in rows
            if getattr(row, field) >= lower and (upper is None or getattr(row, field) < upper)
        ]
        summary = _summarize(selected)
        output.append(
            {
                "bucket": label,
                "matches": summary["total_matches"],
                "result_accuracy": summary["result_accuracy"],
                "score_accuracy": summary["score_accuracy"],
                "roi": summary["cumulative_roi"],
                "profit_units": summary["profit_units"],
            }
        )
    return output


def _filter_strategies(rows: list[HistoricalAuditRow]) -> list[dict]:
    output = []
    for strategy, threshold in FILTER_STRATEGIES:
        selected = rows if threshold is None else [row for row in rows if row.upset_probability <= threshold]
        summary = _summarize(selected)
        output.append(
            {
                "strategy": strategy,
                "filter_rule": "none" if threshold is None else f"upset_probability <= {threshold}",
                "matches": summary["total_matches"],
                "result_accuracy": summary["result_accuracy"],
                "score_accuracy": summary["score_accuracy"],
                "roi": summary["cumulative_roi"],
                "profit_units": summary["profit_units"],
            }
        )
    return output


def _conflict_analysis(rows: list[HistoricalAuditRow]) -> dict:
    comparable = [row for row in rows if row.is_conflict_match is not None]
    conflict = [row for row in comparable if row.is_conflict_match]
    normal = [row for row in comparable if not row.is_conflict_match]
    conflict_summary = _summarize(conflict)
    normal_summary = _summarize(normal)
    return {
        "comparable_matches": len(comparable),
        "conflict_matches": conflict_summary["total_matches"],
        "conflict_accuracy": conflict_summary["result_accuracy"],
        "conflict_roi": conflict_summary["cumulative_roi"],
        "conflict_profit": conflict_summary["profit_units"],
        "non_conflict_matches": normal_summary["total_matches"],
        "non_conflict_accuracy": normal_summary["result_accuracy"],
        "non_conflict_roi": normal_summary["cumulative_roi"],
        "non_conflict_profit": normal_summary["profit_units"],
    }


def _stage_analysis(rows: list[HistoricalAuditRow]) -> list[dict]:
    output = []
    row_stages = {_audit_stage(row.stage) for row in rows}
    stages = list(STAGE_ORDER) + sorted(stage for stage in row_stages if stage not in STAGE_ORDER)
    for stage in stages:
        selected = [row for row in rows if _audit_stage(row.stage) == stage]
        if not selected:
            continue
        summary = _summarize(selected)
        output.append(
            {
                "stage": stage,
                "matches": summary["total_matches"],
                "accuracy": summary["result_accuracy"],
                "roi": summary["cumulative_roi"],
                "profit": summary["profit_units"],
            }
        )
    return output


def _stage_conflict_analysis(rows: list[HistoricalAuditRow]) -> list[dict]:
    output = []
    row_stages = {_audit_stage(row.stage) for row in rows}
    stages = list(STAGE_ORDER) + sorted(stage for stage in row_stages if stage not in STAGE_ORDER)
    for stage in stages:
        selected = [row for row in rows if _audit_stage(row.stage) == stage and row.is_conflict_match is not None]
        if not selected:
            continue
        conflict = [row for row in selected if row.is_conflict_match]
        non_conflict = [row for row in selected if not row.is_conflict_match]
        overall_summary = _summarize(selected)
        conflict_summary = _summarize(conflict)
        non_conflict_summary = _summarize(non_conflict)
        output.append(
            {
                "stage": stage,
                "matches": overall_summary["total_matches"],
                "overall_accuracy": overall_summary["result_accuracy"],
                "conflict_matches": conflict_summary["total_matches"],
                "conflict_accuracy": conflict_summary["result_accuracy"],
                "non_conflict_matches": non_conflict_summary["total_matches"],
                "non_conflict_accuracy": non_conflict_summary["result_accuracy"],
                "accuracy_after_excluding_conflict": non_conflict_summary["result_accuracy"],
                "accuracy_delta_after_excluding_conflict": round(non_conflict_summary["result_accuracy"] - overall_summary["result_accuracy"], 2),
            }
        )
    return output


def _strong_team_analysis(rows: list[HistoricalAuditRow]) -> list[dict]:
    output = []
    for team in STRONG_TEAMS:
        selected = [row for row in rows if row.home_team == team or row.away_team == team]
        summary = _summarize(selected)
        output.append(
            {
                "team": team,
                "matches": summary["total_matches"],
                "accuracy": summary["result_accuracy"],
                "roi": summary["cumulative_roi"],
                "profit": summary["profit_units"],
            }
        )
    return output


def _top_confidence(rows: list[HistoricalAuditRow]) -> list[dict]:
    ranked = sorted(rows, key=lambda row: row.confidence_score, reverse=True)
    output = []
    for label, share in TOP_CONFIDENCE_BUCKETS:
        count = len(ranked) if share >= 1 else math.ceil(len(ranked) * share)
        selected = ranked[:count]
        summary = _summarize(selected)
        output.append(
            {
                "bucket": label,
                "matches": summary["total_matches"],
                "accuracy": summary["result_accuracy"],
                "roi": summary["cumulative_roi"],
                "profit": summary["profit_units"],
            }
        )
    return output


def _best_by(items: list[dict], metric: str) -> dict | None:
    valid = [item for item in items if item.get("matches", 0) and item.get(metric) is not None]
    return max(valid, key=lambda item: item[metric], default=None)


def _conclusion(report: dict) -> dict:
    overall = report["overall"]
    roi_auditable = overall["roi_sample_size"] > 0 and overall["time_safe_invalid_matches"] == 0
    best_strategy_by_roi = _best_by(report["strategy_analysis"], "roi")
    best_confidence_bucket_by_roi = _best_by(report["confidence_analysis"], "roi")
    best_top_confidence_by_roi = _best_by(report["top_confidence_analysis"], "roi")
    best_strategy_by_accuracy = _best_by(report["strategy_analysis"], "result_accuracy")
    best_confidence_bucket_by_accuracy = _best_by(report["confidence_analysis"], "result_accuracy")
    best_top_confidence_by_accuracy = _best_by(report["top_confidence_analysis"], "accuracy")
    conflict = report["conflict_analysis"]
    confidence_effective = bool(
        report["top_confidence_analysis"]
        and report["top_confidence_analysis"][0]["accuracy"] >= overall["result_accuracy"]
    )
    low_upset = [item for item in report["upset_analysis"] if item["bucket"] in ("0-20", "20-40")]
    high_upset = [item for item in report["upset_analysis"] if item["bucket"] in ("50-60", "60-70", "70+")]
    low_acc = sum(item["result_accuracy"] * item["matches"] for item in low_upset) / sum(item["matches"] for item in low_upset) if sum(item["matches"] for item in low_upset) else None
    high_acc = sum(item["result_accuracy"] * item["matches"] for item in high_upset) / sum(item["matches"] for item in high_upset) if sum(item["matches"] for item in high_upset) else None
    upset_effective = low_acc is not None and high_acc is not None and low_acc > high_acc
    conflict_filter = (
        conflict["conflict_matches"] > 0
        and conflict["conflict_accuracy"] < conflict["non_conflict_accuracy"]
        and (conflict["conflict_roi"] or -999) < (conflict["non_conflict_roi"] or -999)
    )
    score = 0
    score += 35 if overall["result_accuracy"] >= 55 else 20 if overall["result_accuracy"] >= 50 else 10
    score += 20 if overall["cumulative_roi"] is not None and overall["cumulative_roi"] > 0 else 5
    score += 15 if confidence_effective else 5
    score += 15 if upset_effective else 5
    score += 15 if conflict_filter else 5
    return {
        "system_score": min(score, 100),
        "roi_auditable": roi_auditable,
        "roi_audit_note": "ROI is unavailable because no odds rows passed the time-safe pre-match validation." if not roi_auditable else "ok",
        "best_filter_threshold": None if not best_strategy_by_roi else best_strategy_by_roi["strategy"],
        "best_confidence_range": None if not best_confidence_bucket_by_roi else best_confidence_bucket_by_roi["bucket"],
        "best_filter_threshold_by_accuracy": None if not best_strategy_by_accuracy else best_strategy_by_accuracy["strategy"],
        "best_confidence_range_by_accuracy": None if not best_confidence_bucket_by_accuracy else best_confidence_bucket_by_accuracy["bucket"],
        "conflict_matches_should_be_filtered": conflict_filter,
        "upset_probability_effective": upset_effective,
        "confidence_score_effective": confidence_effective,
        "highest_roi_strategy": None if not best_strategy_by_roi else best_strategy_by_roi,
        "highest_roi_top_confidence": best_top_confidence_by_roi,
        "highest_accuracy_strategy": best_strategy_by_accuracy,
        "highest_accuracy_confidence_bucket": best_confidence_bucket_by_accuracy,
        "highest_accuracy_top_confidence": best_top_confidence_by_accuracy,
        "recommend_world_cup_live_stage": bool(overall["result_accuracy"] >= 55 and (overall["cumulative_roi"] or -999) > 0 and overall["time_safe_invalid_matches"] == 0),
        "sample_warning": "Phase 1 only uses 2022 World Cup 64 matches; validate again with 2018 before final deployment.",
    }


def build_worldcup_historical_audit(db: Session, run_id: int) -> dict:
    rows = _to_audit_rows(_rows_for_run(db, run_id))
    report = {
        "metadata": {
            "run_id": run_id,
            "source": "world_cup_matches + backtest_predictions + world_cup_odds",
            "time_safe_backtest": True,
            "model_change": "none",
            "note": "Audit report only reads historical backtest rows. It does not modify prediction logic, weights, ELO, Poisson, Monte Carlo, Dixon-Coles, confidence, upset, recommendation, or risk logic.",
        },
        "overall": _summarize(rows),
        "confidence_analysis": _bucket_rows(rows, CONFIDENCE_BUCKETS, "confidence_score"),
        "upset_analysis": _bucket_rows(rows, UPSET_BUCKETS, "upset_probability"),
        "strategy_analysis": _filter_strategies(rows),
        "conflict_analysis": _conflict_analysis(rows),
        "stage_analysis": _stage_analysis(rows),
        "stage_conflict_analysis": _stage_conflict_analysis(rows),
        "strong_team_analysis": _strong_team_analysis(rows),
        "top_confidence_analysis": _top_confidence(rows),
        "matches": [row.__dict__ for row in rows],
    }
    report["conclusion"] = _conclusion(report)
    return report


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        keys: list[str] = []
        for row in rows:
            for key in row:
                if key not in keys:
                    keys.append(key)
        fieldnames = keys
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _summary_csv_rows(report: dict) -> list[dict]:
    rows = [{"section": "overall", **report["overall"]}]
    for section in (
        "confidence_analysis",
        "upset_analysis",
        "strategy_analysis",
        "conflict_analysis",
        "stage_analysis",
        "stage_conflict_analysis",
        "strong_team_analysis",
        "top_confidence_analysis",
    ):
        payload = report[section]
        if isinstance(payload, list):
            rows.extend({"section": section, **item} for item in payload)
        else:
            rows.append({"section": section, **payload})
    rows.append({"section": "conclusion", **report["conclusion"]})
    return rows


def _html_table(rows: list[dict]) -> str:
    if not rows:
        return "<p>No data</p>"
    headers = []
    for row in rows:
        for key in row:
            if key not in headers:
                headers.append(key)
    head = "".join(f"<th>{html.escape(str(header))}</th>" for header in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{html.escape(str(row.get(header, '')))}</td>" for header in headers) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _dashboard_html(report: dict) -> str:
    overall = report["overall"]
    metadata = report.get("metadata", {})
    phase_label = metadata.get("phase_label", "World Cup historical backtest")
    cards = [
        ("Total Matches", overall["total_matches"]),
        ("Result Accuracy", f"{overall['result_accuracy']}%"),
        ("Score Accuracy", f"{overall['score_accuracy']}%"),
        ("Handicap Accuracy", f"{overall['handicap_accuracy']}%"),
        ("Average ROI", f"{overall['average_roi']}%"),
        ("Cumulative ROI", f"{overall['cumulative_roi']}%"),
        ("Profit Units", overall["profit_units"]),
    ]
    card_html = "".join(f"<div class='card'><span>{html.escape(label)}</span><strong>{html.escape(str(value))}</strong></div>" for label, value in cards)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>World Cup Historical Backtest Audit</title>
  <style>
    :root {{ color-scheme: dark; font-family: 'Segoe UI', sans-serif; background: #07111f; color: #e7eef9; }}
    body {{ margin: 0; padding: 32px; background: radial-gradient(circle at top left, #123d6b, #07111f 42%, #040711); }}
    h1 {{ margin: 0 0 8px; font-size: 30px; }}
    h2 {{ margin-top: 30px; color: #93c5fd; }}
    .note {{ color: #a8b8ca; margin-bottom: 24px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 14px; }}
    .card {{ border: 1px solid rgba(148,163,184,.22); border-radius: 18px; padding: 18px; background: rgba(15,23,42,.72); }}
    .card span {{ display:block; color:#9fb3c8; font-size:13px; }}
    .card strong {{ display:block; margin-top:10px; font-size:25px; color:#f8fafc; }}
    table {{ width:100%; border-collapse:collapse; margin-top:12px; background:rgba(15,23,42,.68); }}
    th,td {{ padding:10px 11px; border-bottom:1px solid rgba(148,163,184,.16); text-align:left; font-size:13px; }}
    th {{ color:#bfdbfe; background:rgba(30,41,59,.92); }}
  </style>
</head>
<body>
  <h1>World Cup Historical Backtest Audit</h1>
  <p class="note">{html.escape(phase_label)}. Time-safe audit only; no prediction/model logic modified.</p>
  <section class="cards">{card_html}</section>
  <h2>Final Conclusion</h2>{_html_table([report['conclusion']])}
  <h2>Confidence Bucket</h2>{_html_table(report['confidence_analysis'])}
  <h2>Upset Probability Bucket</h2>{_html_table(report['upset_analysis'])}
  <h2>Strategy Comparison</h2>{_html_table(report['strategy_analysis'])}
  <h2>Market Conflict</h2>{_html_table([report['conflict_analysis']])}
  <h2>Stage Analysis</h2>{_html_table(report['stage_analysis'])}
  <h2>Stage Conflict Analysis</h2>{_html_table(report['stage_conflict_analysis'])}
  <h2>Strong Team Analysis</h2>{_html_table(report['strong_team_analysis'])}
  <h2>Top Confidence Analysis</h2>{_html_table(report['top_confidence_analysis'])}
</body>
</html>
"""


def write_worldcup_audit_outputs(report: dict, output_dir: Path, match_report_name: str = "worldcup_2022_report.csv") -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "audit_report_json": output_dir / "audit_report.json",
        "audit_report_csv": output_dir / "audit_report.csv",
        "audit_dashboard_html": output_dir / "audit_dashboard.html",
        "match_report_csv": output_dir / match_report_name,
        "confidence_analysis_csv": output_dir / "confidence_analysis.csv",
        "upset_analysis_csv": output_dir / "upset_analysis.csv",
        "conflict_analysis_csv": output_dir / "conflict_analysis.csv",
        "stage_conflict_analysis_csv": output_dir / "stage_conflict_analysis.csv",
        "strategy_analysis_csv": output_dir / "strategy_analysis.csv",
    }
    paths["audit_report_json"].write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(paths["audit_report_csv"], _summary_csv_rows(report))
    _write_csv(paths["match_report_csv"], report["matches"])
    _write_csv(paths["confidence_analysis_csv"], report["confidence_analysis"])
    _write_csv(paths["upset_analysis_csv"], report["upset_analysis"])
    _write_csv(paths["conflict_analysis_csv"], [report["conflict_analysis"]])
    _write_csv(paths["stage_conflict_analysis_csv"], report["stage_conflict_analysis"])
    _write_csv(paths["strategy_analysis_csv"], report["strategy_analysis"])
    paths["audit_dashboard_html"].write_text(_dashboard_html(report), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}
