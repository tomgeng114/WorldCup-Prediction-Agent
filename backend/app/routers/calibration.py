from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.phase6_calibration import run_phase6_calibration


router = APIRouter(prefix="/calibration", tags=["calibration"])


@router.post("/run")
def run_calibration_report(db: Session = Depends(get_db)) -> dict:
    return run_phase6_calibration(db)
