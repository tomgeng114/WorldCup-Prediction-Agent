from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.predictions import run_predictions

router = APIRouter(prefix="/predict", tags=["predict"])


@router.post("")
def predict(db: Session = Depends(get_db)) -> dict:
    return run_predictions(db)

