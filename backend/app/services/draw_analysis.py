import json
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import BacktestPrediction, BacktestRun, Match
from app.services.statistics import actual_result, settled_matches

RESULTS = ("Home Win", "Draw", "Away Win")
DRAW_WARNING_THRESHOLD = 15.0


def _rate(count: int, total: int) -> float:
    return round(count / total * 100, 1) if total else 0.0


def _prediction_distribution(matches: list[Match]) -> dict:
    total = len(matches)
    counts = Counter(match.prediction.predicted_result for match in matches if match.prediction)
    return {
        "total": total,
        "home_win_pct": _rate(counts["Home Win"], total),
        "draw_pct": _rate(counts["Draw"], total),
        "away_win_pct": _rate(counts["Away Win"], total),
        "draw_bias_warning": _rate(counts["Draw"], total) < DRAW_WARNING_THRESHOLD,
    }


def _draw_calibration(matches: list[Match]) -> dict:
    settled = settled_matches(matches)
    total = len(settled)
    predicted_draws = sum(1 for match in settled if match.prediction.predicted_result == "Draw")
    actual_draws = sum(1 for match in settled if actual_result(match) == "Draw")
    predicted_draw_rate = _rate(predicted_draws, total)
    actual_draw_rate = _rate(actual_draws, total)
    return {
        "settled_matches": total,
        "predicted_draw_rate": predicted_draw_rate,
        "actual_draw_rate": actual_draw_rate,
        "error": round(predicted_draw_rate - actual_draw_rate, 1),
        "draw_bias_warning": predicted_draw_rate < DRAW_WARNING_THRESHOLD,
    }


def _checklist(matches: list[Match]) -> dict:
    odds_draw_probabilities = []
    final_draw_probabilities = []
    for match in matches:
        if not match.prediction:
            continue
        final_draw_probabilities.append(match.prediction.draw_probability)
        try:
            breakdown = json.loads(match.prediction.model_breakdown or "{}")
            odds = breakdown.get("odds") or {}
            if "draw" in odds:
                odds_draw_probabilities.append(float(odds["draw"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

    avg_final_draw = sum(final_draw_probabilities) / len(final_draw_probabilities) if final_draw_probabilities else 0.0
    avg_odds_draw = sum(odds_draw_probabilities) / len(odds_draw_probabilities) if odds_draw_probabilities else 0.0
    return {
        "odds_weight_too_high_risk": bool(odds_draw_probabilities and avg_odds_draw + 0.04 < avg_final_draw),
        "score_matrix_required": "0-0 to 5-5 Dixon-Coles matrix is required before draw and handicap decisions.",
        "draw_probability_compression_risk": avg_final_draw < 0.18,
        "final_recommendation_ignores_draw": _prediction_distribution(matches)["draw_bias_warning"],
        "avg_final_draw_probability": round(avg_final_draw * 100, 1),
        "avg_odds_draw_probability": round(avg_odds_draw * 100, 1),
    }


def _load_prediction_matches(db: Session, limit: int) -> list[Match]:
    return db.scalars(
        select(Match)
        .where(Match.prediction != None)  # noqa: E711
        .options(joinedload(Match.prediction), joinedload(Match.odds), joinedload(Match.home_team), joinedload(Match.away_team))
        .order_by(Match.kickoff_time.desc())
        .limit(limit)
    ).unique().all()


def _world_cup_class_hit_rates(db: Session) -> dict:
    run = db.scalar(select(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(1))
    if not run:
        return {"available": False, "message": "No World Cup backtest run found."}

    rows = db.scalars(select(BacktestPrediction).where(BacktestPrediction.run_id == run.id)).all()
    payload = {"available": True, "run_id": run.id, "total_matches": len(rows), "classes": {}}
    for result in RESULTS:
        class_rows = [row for row in rows if row.actual_result == result]
        hits = sum(1 for row in class_rows if row.predicted_result == result)
        payload["classes"][result] = {
            "actual_count": len(class_rows),
            "hit_count": hits,
            "hit_rate": _rate(hits, len(class_rows)),
        }

    prediction_counts = Counter(row.predicted_result for row in rows)
    actual_counts = Counter(row.actual_result for row in rows)
    payload["prediction_distribution"] = {result: _rate(prediction_counts[result], len(rows)) for result in RESULTS}
    payload["actual_distribution"] = {result: _rate(actual_counts[result], len(rows)) for result in RESULTS}
    payload["draw_bias_warning"] = payload["prediction_distribution"].get("Draw", 0.0) < DRAW_WARNING_THRESHOLD
    return payload


def draw_analysis_report(db: Session) -> dict:
    windows = {}
    for limit in (100, 500, 1000):
        matches = _load_prediction_matches(db, limit)
        windows[str(limit)] = {
            "prediction_distribution": _prediction_distribution(matches),
            "draw_calibration": _draw_calibration(matches),
            "diagnostics": _checklist(matches),
        }

    return {
        "thresholds": {"draw_bias_warning_below_pct": DRAW_WARNING_THRESHOLD},
        "windows": windows,
        "world_cup_backtest": _world_cup_class_hit_rates(db),
    }
