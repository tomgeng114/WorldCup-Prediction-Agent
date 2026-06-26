from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import WorldCupMatch, WorldCupOdds, WorldCupTeamProfile
from app.services.data_confidence import assess_match_data_confidence, write_team_data_confidence_report
from app.services.world_cup_specialist import (
    import_team_profiles_csv,
    predict_world_cup_specialist,
    seed_2026_qualified_teams,
    simulate_world_cup_2026,
    specialist_coverage_report,
    write_specialist_report,
)


router = APIRouter(prefix="/world-cup-specialist", tags=["world-cup-specialist"])


def _parse_years(years: str | None) -> list[int] | None:
    if not years:
        return None
    parsed = [int(item.strip()) for item in years.split(",") if item.strip()]
    return parsed or None


@router.post("/profiles/import")
def import_profiles(csv_path: str = Query(..., description="Absolute path to verified World Cup team profile CSV"), db: Session = Depends(get_db)) -> dict:
    summary = import_team_profiles_csv(db, csv_path)
    return {
        "imported": summary.imported,
        "updated": summary.updated,
        "skipped": summary.skipped,
    }


@router.post("/profiles/seed-2026")
def seed_2026_profiles(db: Session = Depends(get_db)) -> dict:
    summary = seed_2026_qualified_teams(db)
    return {
        "imported": summary.imported,
        "updated": summary.updated,
        "skipped": summary.skipped,
    }


@router.get("/coverage")
def coverage(years: str | None = None, db: Session = Depends(get_db)) -> dict:
    return specialist_coverage_report(db, _parse_years(years))


@router.get("/data-confidence/teams")
def team_data_confidence(year: int = Query(default=2026), db: Session = Depends(get_db)) -> dict:
    return write_team_data_confidence_report(db, year=year)


@router.get("/data-confidence/match/{match_id}")
def match_data_confidence(match_id: int, db: Session = Depends(get_db)) -> dict:
    match = db.get(WorldCupMatch, match_id)
    if not match:
        return {"error": "World Cup match not found"}
    home_profile = db.scalar(
        select(WorldCupTeamProfile).where(
            WorldCupTeamProfile.tournament_year == match.tournament_year,
            WorldCupTeamProfile.team_name == match.home_team,
        )
    )
    away_profile = db.scalar(
        select(WorldCupTeamProfile).where(
            WorldCupTeamProfile.tournament_year == match.tournament_year,
            WorldCupTeamProfile.team_name == match.away_team,
        )
    )
    odds = db.scalar(select(WorldCupOdds).where(WorldCupOdds.match_id == match.id))
    return assess_match_data_confidence(match, home_profile, away_profile, odds)


@router.get("/predict/{match_id}")
def predict(match_id: int, db: Session = Depends(get_db)) -> dict:
    return predict_world_cup_specialist(db, match_id)


@router.post("/report")
def report(years: str | None = None, db: Session = Depends(get_db)) -> dict:
    return write_specialist_report(db, _parse_years(years))


@router.post("/simulate-2026")
def simulate(simulations: int = Query(default=1000, ge=1, le=100000), db: Session = Depends(get_db)) -> dict:
    return simulate_world_cup_2026(db, simulations=simulations)
