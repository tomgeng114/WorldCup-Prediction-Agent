from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models import Match

router = APIRouter(prefix="/odds", tags=["odds"])


@router.get("")
def odds(db: Session = Depends(get_db)) -> list[dict]:
    matches = db.scalars(
        select(Match)
        .options(joinedload(Match.home_team), joinedload(Match.away_team), joinedload(Match.odds))
        .order_by(Match.kickoff_time.asc())
    ).unique().all()
    return [
        {
            "match_id": match.id,
            "competition": match.competition,
            "kickoff_time": match.kickoff_time,
            "home_team": match.home_team.name,
            "away_team": match.away_team.name,
            "home_win_odds": match.odds.home_win_odds,
            "draw_odds": match.odds.draw_odds,
            "away_win_odds": match.odds.away_win_odds,
            "source_pool": match.odds.source_pool,
            "handicap": match.odds.handicap,
            "source": "中国体育彩票",
        }
        for match in matches
        if match.odds
    ]
