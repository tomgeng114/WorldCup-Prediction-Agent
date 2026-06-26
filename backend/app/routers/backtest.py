import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import BacktestRun
from app.services.backtest_engine import BacktestEngine
from app.services.world_cup_history import RECENT_WORLD_CUP_YEARS, WORLD_CUP_YEARS, historical_match_counts, import_world_cup_history

router = APIRouter(prefix="/backtest", tags=["backtest"])


def _parse_years(years: str | None) -> list[int] | None:
    if not years:
        return None
    parsed = [int(item.strip()) for item in years.split(",") if item.strip()]
    return parsed or None


def _serialize_run(run: BacktestRun) -> dict:
    return {
        "id": run.id,
        "model_version": run.model_version,
        "years": run.years,
        "total_matches": run.total_matches,
        "metrics": json.loads(run.metrics or "{}"),
        "initial_weights": json.loads(run.initial_weights or "{}"),
        "final_weights": json.loads(run.final_weights or "{}"),
        "created_at": run.created_at,
    }


@router.post("/world-cup/import")
def import_history(
    years: str | None = Query(default=None, description="Comma separated years, e.g. 2018,2022"),
    replace: bool = True,
    db: Session = Depends(get_db),
) -> dict:
    selected_years = _parse_years(years) or RECENT_WORLD_CUP_YEARS
    summary = import_world_cup_history(db, selected_years, replace=replace)
    return {
        "imported": summary.imported,
        "years": summary.years,
        "source": summary.source,
        "counts": historical_match_counts(db),
    }


@router.get("/world-cup/status")
def history_status(db: Session = Depends(get_db)) -> dict:
    counts = historical_match_counts(db)
    return {
        "counts": counts,
        "total": sum(counts.values()),
        "expected_per_year": 64,
        "complete": all(counts.get(year) == 64 for year in WORLD_CUP_YEARS),
    }


@router.post("/run")
def run_backtest(
    years: str | None = Query(default=None, description="Comma separated years, e.g. 2002,2006,2010"),
    score_mode: str = Query(default="calibrated", pattern="^(calibrated|accuracy)$"),
    warmup: bool = Query(default=True, description="Use pre-period World Cup matches for model warm-up"),
    db: Session = Depends(get_db),
) -> dict:
    selected_years = _parse_years(years) or RECENT_WORLD_CUP_YEARS
    run = BacktestEngine(db, score_mode=score_mode, use_warmup=warmup).run(years=selected_years)
    return _serialize_run(run)


@router.get("/runs")
def list_runs(db: Session = Depends(get_db)) -> list[dict]:
    runs = db.scalars(select(BacktestRun).order_by(BacktestRun.created_at.desc())).all()
    return [_serialize_run(run) for run in runs]


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)) -> dict:
    run = db.scalar(select(BacktestRun).where(BacktestRun.id == run_id))
    if not run:
        return {"error": "Backtest run not found"}
    return _serialize_run(run)
