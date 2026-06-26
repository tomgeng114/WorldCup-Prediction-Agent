from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.phase61_value_engine import run_phase61_value_engine


router = APIRouter(prefix="/value-engine", tags=["value-engine"])


@router.post("/run")
def run_value_engine_report(
    min_model_probability: float = Query(default=0.35, ge=0.0, le=1.0),
    min_market_probability: float = Query(default=0.10, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
) -> dict:
    return run_phase61_value_engine(
        db,
        min_model_probability=min_model_probability,
        min_market_probability=min_market_probability,
    )
