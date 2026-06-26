from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.phase81_simulation_audit import run_phase81_simulation_audit
from app.services.phase8_simulation import run_phase8_simulation


router = APIRouter(prefix="/phase8", tags=["phase8"])


@router.post("/simulate")
def simulate(
    simulations: int = Query(default=10000, ge=100, le=100000),
    db: Session = Depends(get_db),
) -> dict:
    return run_phase8_simulation(db, simulations=simulations)


@router.post("/audit")
def audit(db: Session = Depends(get_db)) -> dict:
    return run_phase81_simulation_audit(db)
