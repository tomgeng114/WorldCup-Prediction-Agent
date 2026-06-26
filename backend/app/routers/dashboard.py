from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models import Match
from app.schemas import DashboardSummaryOut
from app.services.statistics import (
    actual_market_result,
    actual_result,
    ai_hot_alignment_summary,
    hit_summary,
    performance_curves,
    roi_summary,
    score_hit,
    settled_matches,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummaryOut)
def dashboard_summary(db: Session = Depends(get_db)) -> dict:
    matches = db.scalars(
        select(Match)
        .options(joinedload(Match.prediction), joinedload(Match.home_team), joinedload(Match.away_team), joinedload(Match.odds))
        .order_by(Match.kickoff_time.asc())
    ).unique().all()

    predictions = [match.prediction for match in matches if match.prediction]
    finished_matches = settled_matches(matches)
    total_finished = len(finished_matches)
    result_hits = sum(1 for match in finished_matches if match.prediction.predicted_result == actual_result(match))
    score_hits = sum(1 for match in finished_matches if score_hit(match))
    handicap_matches = [
        match
        for match in finished_matches
        if match.prediction.market_type == "HHAD"
    ]
    handicap_hits = sum(1 for match in handicap_matches if match.prediction.predicted_market_result == actual_market_result(match))
    goal_diff_hits = 0
    for match in finished_matches:
        try:
            predicted_home, predicted_away = [int(value) for value in match.prediction.predicted_score.split("-", 1)]
        except (AttributeError, TypeError, ValueError):
            continue
        if predicted_home - predicted_away == match.home_score - match.away_score:
            goal_diff_hits += 1
    over_under_hits = sum(
        1
        for match in finished_matches
        if (match.home_score + match.away_score >= 3 and match.prediction.over_under_pick == "Over 2.5")
        or (match.home_score + match.away_score < 3 and match.prediction.over_under_pick == "Under 2.5")
    )
    today = hit_summary(matches, days=1)
    seven_day = hit_summary(matches, days=7)
    thirty_day = hit_summary(matches, days=30)
    roi = roi_summary(matches)
    curves = performance_curves(matches)
    hot_alignment = ai_hot_alignment_summary(matches)

    return {
        "total_predictions": len(predictions),
        "win_draw_loss_hit_rate": round((result_hits / total_finished * 100) if total_finished else 0, 1),
        "handicap_hit_rate": round((handicap_hits / len(handicap_matches) * 100) if handicap_matches else 0, 1),
        "score_hit_rate": round((score_hits / total_finished * 100) if total_finished else 0, 1),
        "goal_diff_hit_rate": round((goal_diff_hits / total_finished * 100) if total_finished else 0, 1),
        "half_full_hit_rate": 0.0,
        "over_under_hit_rate": round((over_under_hits / total_finished * 100) if total_finished else 0, 1),
        "roi": roi["roi"],
        "today_red": today["red"],
        "today_black": today["black"],
        "today_hit_rate": today["hit_rate"],
        "seven_day_red": seven_day["red"],
        "seven_day_black": seven_day["black"],
        "seven_day_hit_rate": seven_day["hit_rate"],
        "thirty_day_red": thirty_day["red"],
        "thirty_day_black": thirty_day["black"],
        "thirty_day_hit_rate": thirty_day["hit_rate"],
        "ai_hot_same_count": hot_alignment["same"],
        "ai_hot_opposite_count": hot_alignment["opposite"],
        "ai_hot_sample_size": hot_alignment["sample_size"],
        "ai_hot_same_rate": hot_alignment["same_rate"],
        "ai_hot_opposite_rate": hot_alignment["opposite_rate"],
        "profit_curve": curves["profit_curve"],
        "accuracy_curve": curves["accuracy_curve"],
    }
