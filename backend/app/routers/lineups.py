"""
Lineup Intelligence Layer v1 — API endpoints.

Read-only data ingestion. Does NOT affect predictions.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.lineup_service import (
    LineupRecord,
    get_lineup,
    get_lineups_for_match,
    lineup_stats,
    list_all_lineups,
    upsert_lineup,
)

router = APIRouter(prefix="/lineups", tags=["lineups"])


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)) -> dict:
    """Lineup Intelligence Layer stats — progress toward 50 samples."""
    return lineup_stats(db)


@router.get("")
def list_lineups(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[dict]:
    """List all lineup records."""
    return list_all_lineups(db, limit=limit)


@router.get("/match/{match_id}")
def match_lineups(match_id: int, db: Session = Depends(get_db)) -> list[dict]:
    """Get lineups for a specific match."""
    lineups = get_lineups_for_match(db, match_id)
    result = []
    for lu in lineups:
        result.append(
            {
                "id": lu.id,
                "match_id": lu.match_id,
                "team_id": lu.team_id,
                "team_name": lu.team.name if lu.team else "",
                "is_home": lu.is_home,
                "formation": lu.formation,
                "starting_xi": __import__("json").loads(lu.starting_xi or "[]"),
                "substitutes": __import__("json").loads(lu.substitutes or "[]"),
                "missing_players": __import__("json").loads(lu.missing_players or "[]"),
                "captain": lu.captain,
                "lineup_strength_score": lu.lineup_strength_score,
                "source": lu.source,
                "notes": lu.notes,
                "created_at": lu.created_at.isoformat() if lu.created_at else None,
            }
        )
    return result


@router.post("")
def create_lineup(payload: dict, db: Session = Depends(get_db)) -> dict:
    """Create or update a lineup record.

    Required fields:
        match_id, team_id, is_home
    Optional:
        formation, starting_xi, substitutes, missing_players,
        captain, source, notes
    """
    record = LineupRecord(
        match_id=payload["match_id"],
        team_id=payload["team_id"],
        is_home=payload.get("is_home", True),
        formation=payload.get("formation", ""),
        starting_xi=payload.get("starting_xi", []),
        substitutes=payload.get("substitutes", []),
        missing_players=payload.get("missing_players", []),
        captain=payload.get("captain", ""),
        source=payload.get("source", "manual"),
        notes=payload.get("notes", ""),
    )
    lineup = upsert_lineup(db, record)
    return {"id": lineup.id, "created": True}
