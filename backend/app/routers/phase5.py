from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.phase5_international import run_phase5


router = APIRouter(prefix="/phase5", tags=["phase5"])


@router.post("/run")
def run_phase5_pipeline(db: Session = Depends(get_db)) -> dict:
    result = run_phase5(db)
    return {
        "imported": result.imported,
        "reports": {key: str(path) for key, path in result.reports.items()},
        "metrics": result.metrics,
    }
