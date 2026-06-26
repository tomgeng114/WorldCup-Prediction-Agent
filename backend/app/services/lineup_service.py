"""
Lineup Intelligence Layer v1 — data ingestion only.

Read-only. Does NOT affect predictions.
Target: accumulate 50 match samples, then evaluate predictive value.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Match, MatchLineup


@dataclass
class LineupRecord:
    match_id: int
    team_id: int
    is_home: bool
    formation: str = ""
    starting_xi: list[dict] = field(default_factory=list)
    substitutes: list[dict] = field(default_factory=list)
    missing_players: list[dict] = field(default_factory=list)
    captain: str = ""
    source: str = ""
    notes: str = ""


def upsert_lineup(db: Session, record: LineupRecord) -> MatchLineup:
    """Insert or update a lineup record. One per (match_id, team_id)."""
    existing = db.scalar(
        select(MatchLineup).where(
            MatchLineup.match_id == record.match_id,
            MatchLineup.team_id == record.team_id,
        )
    )

    if existing:
        existing.formation = record.formation
        existing.starting_xi = json.dumps(record.starting_xi, ensure_ascii=False)
        existing.substitutes = json.dumps(record.substitutes, ensure_ascii=False)
        existing.missing_players = json.dumps(record.missing_players, ensure_ascii=False)
        existing.captain = record.captain
        existing.source = record.source
        existing.notes = record.notes
        db.commit()
        return existing

    lineup = MatchLineup(
        match_id=record.match_id,
        team_id=record.team_id,
        is_home=record.is_home,
        formation=record.formation,
        starting_xi=json.dumps(record.starting_xi, ensure_ascii=False),
        substitutes=json.dumps(record.substitutes, ensure_ascii=False),
        missing_players=json.dumps(record.missing_players, ensure_ascii=False),
        captain=record.captain,
        source=record.source,
        notes=record.notes,
    )
    db.add(lineup)
    db.commit()
    db.refresh(lineup)
    return lineup


def get_lineup(db: Session, match_id: int, team_id: int) -> MatchLineup | None:
    return db.scalar(
        select(MatchLineup).where(
            MatchLineup.match_id == match_id,
            MatchLineup.team_id == team_id,
        )
    )


def get_lineups_for_match(db: Session, match_id: int) -> list[MatchLineup]:
    return list(
        db.scalars(
            select(MatchLineup).where(MatchLineup.match_id == match_id)
        ).all()
    )


def lineup_stats(db: Session) -> dict:
    """Return aggregate stats for the Lineup Intelligence Layer."""
    total = db.scalar(select(func.count(MatchLineup.id)))
    matches_with_lineups = db.scalar(
        select(func.count(func.distinct(MatchLineup.match_id)))
    )
    teams_with_lineups = db.scalar(
        select(func.count(func.distinct(MatchLineup.team_id)))
    )

    # Count records with completed matches (result known)
    completed = (
        db.query(MatchLineup)
        .join(Match, MatchLineup.match_id == Match.id)
        .where(Match.status == "finished")
        .count()
    )

    return {
        "total_lineup_records": total,
        "matches_covered": matches_with_lineups,
        "teams_covered": teams_with_lineups,
        "completed_match_samples": completed,
        "target_samples": 50,
        "progress_pct": round(completed / 50 * 100, 1) if completed else 0.0,
        "ready_for_decision_layer": completed >= 50,
    }


def list_all_lineups(db: Session, limit: int = 100) -> list[dict]:
    """List all lineup records with match context."""
    rows = db.scalars(
        select(MatchLineup).order_by(MatchLineup.created_at.desc()).limit(limit)
    ).all()

    result = []
    for lu in rows:
        match = lu.match
        team = lu.team
        result.append(
            {
                "id": lu.id,
                "match_id": lu.match_id,
                "team_id": lu.team_id,
                "team_name": team.name if team else "",
                "is_home": lu.is_home,
                "formation": lu.formation,
                "starting_xi": json.loads(lu.starting_xi or "[]"),
                "substitutes": json.loads(lu.substitutes or "[]"),
                "missing_players": json.loads(lu.missing_players or "[]"),
                "captain": lu.captain,
                "lineup_strength_score": lu.lineup_strength_score,
                "match_status": match.status if match else "",
                "match_score": f"{match.home_score}-{match.away_score}" if match and match.home_score is not None else "pending",
                "source": lu.source,
                "notes": lu.notes,
                "created_at": lu.created_at.isoformat() if lu.created_at else None,
            }
        )
    return result
