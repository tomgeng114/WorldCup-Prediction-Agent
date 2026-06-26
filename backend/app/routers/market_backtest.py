from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import WorldCupOdds
from app.services.phase2_market import (
    benchmark_market_vs_ai,
    edge_sensitivity_report,
    handicap_backtest,
    import_world_cup_odds_csv,
    roi_backtest,
    upset_analysis,
    value_bet_report,
)

router = APIRouter(prefix="/market-backtest", tags=["market-backtest"])


@router.post("/odds/import")
def import_odds(csv_path: str = Query(..., description="Absolute path to verified historical odds CSV"), db: Session = Depends(get_db)) -> dict:
    summary = import_world_cup_odds_csv(db, csv_path)
    return {
        "imported": summary.imported,
        "updated": summary.updated,
        "skipped": summary.skipped,
    }


@router.get("/odds/status")
def odds_status(db: Session = Depends(get_db)) -> dict:
    total = db.scalar(select(func.count()).select_from(WorldCupOdds)) or 0
    with_handicap = db.scalar(select(func.count()).select_from(WorldCupOdds).where(WorldCupOdds.handicap.is_not(None))) or 0
    return {
        "world_cup_odds_rows": total,
        "handicap_rows": with_handicap,
        "expected_2018_2022_rows": 128,
        "coverage_rate": round(total / 128 * 100, 2) if total else 0.0,
        "status": "需要导入真实赛前体彩赔率" if total == 0 else "ok",
    }


@router.get("/benchmark")
def benchmark(run_id: int | None = None, db: Session = Depends(get_db)) -> dict:
    return benchmark_market_vs_ai(db, run_id=run_id)


@router.get("/roi")
def roi(
    run_id: int | None = None,
    staking: str = Query(default="unit", pattern="^(unit|kelly)$"),
    unit: float = 1.0,
    kelly_fraction: float = 0.25,
    db: Session = Depends(get_db),
) -> dict:
    return roi_backtest(db, run_id=run_id, staking=staking, unit=unit, kelly_fraction=kelly_fraction)


@router.get("/handicap")
def handicap(run_id: int | None = None, db: Session = Depends(get_db)) -> dict:
    return handicap_backtest(db, run_id=run_id)


@router.get("/upsets")
def upsets(
    run_id: int | None = None,
    high_odds_threshold: float = 3.0,
    db: Session = Depends(get_db),
) -> dict:
    return upset_analysis(db, run_id=run_id, high_odds_threshold=high_odds_threshold)


@router.get("/value-bets")
def value_bets(
    run_id: int | None = None,
    observe_edge: float = 0.05,
    recommend_edge: float = 0.10,
    unit: float = 1.0,
    kelly_fraction: float = 0.25,
    db: Session = Depends(get_db),
) -> dict:
    return value_bet_report(
        db,
        run_id=run_id,
        observe_edge=observe_edge,
        recommend_edge=recommend_edge,
        unit=unit,
        kelly_fraction=kelly_fraction,
    )


@router.get("/edge-sensitivity")
def edge_sensitivity(
    run_id: int | None = None,
    unit: float = 1.0,
    kelly_fraction: float = 0.25,
    db: Session = Depends(get_db),
) -> dict:
    return edge_sensitivity_report(
        db,
        run_id=run_id,
        unit=unit,
        kelly_fraction=kelly_fraction,
    )
