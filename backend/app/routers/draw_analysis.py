from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.draw_analysis import draw_analysis_report

router = APIRouter(prefix="/draw-analysis", tags=["draw-analysis"])


@router.get("/report")
def report(db: Session = Depends(get_db)) -> dict:
    return draw_analysis_report(db)
