from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.phase72_elo_integration import run_phase72_elo_integration


router = APIRouter(prefix="/phase72", tags=["phase72"])


@router.post("/run")
def run_phase72(db: Session = Depends(get_db)) -> dict:
    return run_phase72_elo_integration(db)
