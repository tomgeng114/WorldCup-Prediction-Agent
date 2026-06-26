import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models import Match, Prediction
from app.schemas import RunPredictionResponse
from app.services.predictor import predict_match

router = APIRouter(prefix="/predictions", tags=["predictions"])


@router.post("/run", response_model=RunPredictionResponse)
def run_predictions(db: Session = Depends(get_db)) -> dict:
    matches = db.scalars(
        select(Match)
        .options(joinedload(Match.home_team), joinedload(Match.away_team), joinedload(Match.odds), joinedload(Match.prediction))
    ).unique().all()
    updated = 0
    for match in matches:
        if not match.odds:
            continue
        if match.status == "finished" and match.prediction:
            continue
        payload = predict_match(match, match.odds)
        prediction = match.prediction or Prediction(match_id=match.id)
        prediction.home_win_probability = payload.home_win_probability
        prediction.draw_probability = payload.draw_probability
        prediction.away_win_probability = payload.away_win_probability
        prediction.predicted_result = payload.predicted_result
        prediction.predicted_score = payload.predicted_score
        prediction.backup_scores = payload.backup_scores
        prediction.half_full_time = payload.half_full_time
        prediction.total_goals_band = payload.total_goals_band
        prediction.over_under_pick = payload.over_under_pick
        prediction.both_teams_to_score = payload.both_teams_to_score
        prediction.confidence = payload.confidence
        prediction.upset_probability = payload.upset_probability
        prediction.score_probability = payload.score_probability
        prediction.top_scores = json.dumps(payload.top_scores, ensure_ascii=False)
        prediction.total_goals_probabilities = json.dumps(payload.total_goals_probabilities, ensure_ascii=False)
        prediction.model_breakdown = json.dumps(payload.model_breakdown, ensure_ascii=False)
        prediction.market_type = payload.market_type
        prediction.handicap = payload.handicap
        prediction.predicted_market_result = payload.predicted_market_result
        prediction.market_home_probability = payload.market_probabilities["home"]
        prediction.market_draw_probability = payload.market_probabilities["draw"]
        prediction.market_away_probability = payload.market_probabilities["away"]
        prediction.one_goal_handicap_result = payload.one_goal_handicap_result
        prediction.one_goal_handicap_probabilities = json.dumps(payload.one_goal_handicap_probabilities, ensure_ascii=False)
        prediction.explanation = payload.explanation
        prediction.report_preview = payload.report_preview
        prediction.is_red_pick = payload.is_red_pick
        db.add(prediction)
        updated += 1
    db.commit()
    return {"updated_predictions": updated, "message": "Prediction engine completed successfully."}
