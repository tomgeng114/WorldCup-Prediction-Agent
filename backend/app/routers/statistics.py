from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models import Match
from app.services.statistics import actual_market_result, actual_result, hit_summary, performance_curves, roi_summary, score_hit, settle_match, settled_matches

statistics_router = APIRouter(prefix="/statistics", tags=["statistics"])
roi_router = APIRouter(prefix="/roi", tags=["roi"])
results_router = APIRouter(prefix="/results", tags=["results"])


def _load_matches(db: Session) -> list[Match]:
    return db.scalars(
        select(Match)
        .options(joinedload(Match.prediction), joinedload(Match.home_team), joinedload(Match.away_team), joinedload(Match.odds))
        .order_by(Match.kickoff_time.asc())
    ).unique().all()


@statistics_router.get("")
def statistics(db: Session = Depends(get_db)) -> dict:
    matches = _load_matches(db)
    curves = performance_curves(matches)
    return {
        "today": hit_summary(matches, days=1),
        "seven_day": hit_summary(matches, days=7),
        "thirty_day": hit_summary(matches, days=30),
        "all_time": hit_summary(matches),
        "curves": curves,
    }


def _predicted_goal_diff(match: Match) -> int | None:
    try:
        home_score, away_score = [int(value) for value in match.prediction.predicted_score.split("-", 1)]
    except (AttributeError, TypeError, ValueError):
        return None
    return home_score - away_score


@statistics_router.get("/backtest/toto-1000")
def toto_backtest(limit: int = 1000, db: Session = Depends(get_db)) -> dict:
    rows = sorted(settled_matches(_load_matches(db)), key=lambda match: match.kickoff_time, reverse=True)[:limit]
    handicap_rows = [
        match
        for match in rows
        if match.prediction.market_type == "HHAD"
    ]
    win_draw_loss_hits = sum(1 for match in rows if match.prediction.predicted_result == actual_result(match))
    handicap_hits = sum(1 for match in handicap_rows if match.prediction.predicted_market_result == actual_market_result(match))
    score_hits = sum(1 for match in rows if score_hit(match))
    goal_diff_hits = sum(
        1
        for match in rows
        if _predicted_goal_diff(match) is not None
        and _predicted_goal_diff(match) == match.home_score - match.away_score
    )
    return {
        "requested_limit": limit,
        "sample_size": len(rows),
        "handicap_sample_size": len(handicap_rows),
        "win_draw_loss_hit_rate": round((win_draw_loss_hits / len(rows) * 100) if rows else 0, 1),
        "handicap_hit_rate": round((handicap_hits / len(handicap_rows) * 100) if handicap_rows else 0, 1),
        "score_hit_rate": round((score_hits / len(rows) * 100) if rows else 0, 1),
        "goal_diff_hit_rate": round((goal_diff_hits / len(rows) * 100) if rows else 0, 1),
        "note": "Only settled real database rows are used; no mock matches are generated.",
    }


@roi_router.get("")
def roi(db: Session = Depends(get_db)) -> dict:
    return roi_summary(_load_matches(db))


@results_router.post("/settle")
def settle_results(db: Session = Depends(get_db)) -> dict:
    matches = settled_matches(_load_matches(db))
    settled = [settle_match(match, persist=True) for match in matches]
    db.commit()
    return {"settled_matches": len(settled), "results": settled}


@results_router.get("")
def results(db: Session = Depends(get_db)) -> list[dict]:
    rows = settled_matches(_load_matches(db))
    return [
        {
            "match_id": match.id,
            "competition": match.competition,
            "kickoff_time": match.kickoff_time,
            "home_team": match.home_team.name,
            "away_team": match.away_team.name,
            "home_score": match.home_score,
            "away_score": match.away_score,
            "settlement": settle_match(match),
        }
        for match in rows
    ]
