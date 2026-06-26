from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.sporttery import SPORTTERY_MATCH_URL, SPORTTERY_RESULT_URL, sync_sporttery_matches, sync_sporttery_results
from app.services.sporttery_analysis import fetch_match_analysis

router = APIRouter(prefix="/data-sources", tags=["data-sources"])


@router.post("/sporttery/sync")
def sync_sporttery(purge_legacy_samples: bool = True, db: Session = Depends(get_db)) -> dict:
    result = sync_sporttery_matches(db, purge_legacy_samples=purge_legacy_samples)
    return {
        "source": "中国体育彩票",
        "source_url": SPORTTERY_MATCH_URL,
        "fetched_matches": result.fetched_matches,
        "imported_matches": result.imported_matches,
        "updated_matches": result.updated_matches,
        "skipped_matches": result.skipped_matches,
        "closed_matches": result.closed_matches,
        "settled_matches": result.settled_matches,
        "pending_results": result.pending_results,
    }


@router.post("/sporttery/results/sync")
def sync_sporttery_result_data(days: int = 7, db: Session = Depends(get_db)) -> dict:
    result = sync_sporttery_results(db, days=days)
    return {
        "source": "中国体育彩票足球赛果开奖",
        "source_url": SPORTTERY_RESULT_URL,
        "fetched_results": result.fetched_results,
        "settled_matches": result.settled_matches,
        "pending_results": result.pending_results,
        "skipped_results": result.skipped_results,
    }


@router.get("/sporttery/analysis/{sporttery_match_id}")
def sporttery_analysis(sporttery_match_id: int) -> dict:
    return fetch_match_analysis(sporttery_match_id)
