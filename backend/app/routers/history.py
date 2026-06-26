import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models import Match
from app.services.statistics import actual_market_result, actual_result, predicted_score_candidates, settle_match

router = APIRouter(prefix="/history", tags=["history"])


def _result_from_adjusted_score(home_score: int, away_score: int, handicap: float) -> str:
    adjusted_home = home_score + handicap
    if adjusted_home > away_score:
        return "Home Win"
    if adjusted_home < away_score:
        return "Away Win"
    return "Draw"


def _one_goal_prediction(prediction) -> str:
    try:
        probabilities = json.loads(prediction.one_goal_handicap_probabilities or "{}")
    except (AttributeError, json.JSONDecodeError):
        probabilities = {}
    if probabilities:
        return prediction.one_goal_handicap_result

    try:
        home_score, away_score = [int(value) for value in prediction.predicted_score.split("-", 1)]
    except (AttributeError, TypeError, ValueError):
        return "Pending"
    return _result_from_adjusted_score(home_score, away_score, -1)


@router.get("")
def history_list(
    competition: str | None = Query(default=None),
    team: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = (
        select(Match)
        .where(Match.status == "finished")
        .options(joinedload(Match.home_team), joinedload(Match.away_team), joinedload(Match.prediction))
        .order_by(Match.kickoff_time.desc())
    )
    rows = db.scalars(query).unique().all()
    results = []
    for match in rows:
        if not match.prediction:
            continue
        if competition and competition.lower() not in match.competition.lower():
            continue
        if team and team.lower() not in match.home_team.name.lower() and team.lower() not in match.away_team.name.lower():
            continue
        settlement = settle_match(match)
        predicted_scores = predicted_score_candidates(match)
        results.append(
            {
                "match_id": match.id,
                "date": match.kickoff_time,
                "competition": match.competition,
                "home_team": match.home_team.name,
                "away_team": match.away_team.name,
                "predicted_result": match.prediction.predicted_result,
                "actual_result": actual_result(match),
                "predicted_market_result": match.prediction.predicted_market_result,
                "actual_market_result": actual_market_result(match),
                "market_type": match.prediction.market_type,
                "handicap": match.prediction.handicap,
                "one_goal_handicap_result": _one_goal_prediction(match.prediction),
                "one_goal_handicap_actual_result": _result_from_adjusted_score(match.home_score, match.away_score, -1),
                "predicted_score": match.prediction.predicted_score,
                "predicted_scores": predicted_scores[:3],
                "actual_score": f"{match.home_score}-{match.away_score}",
                "hit_result": settlement["result_hit"],
                "hit_market": settlement["market_hit"],
                "hit_score": settlement["score_hit"],
                "roi": settlement["roi"],
                "profit": settlement["profit"],
            }
        )
    return results
