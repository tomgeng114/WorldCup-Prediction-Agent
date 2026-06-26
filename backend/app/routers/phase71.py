from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.phase71_data_acquisition import run_phase71_data_acquisition


router = APIRouter(prefix="/phase71", tags=["phase71"])


@router.post("/run")
def run_phase71(db: Session = Depends(get_db)) -> dict:
    return run_phase71_data_acquisition(db)
