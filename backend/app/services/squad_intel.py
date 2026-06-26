"""
Squad Intelligence Layer MVP

Computes squad strength scores (0-100) based on:
  - Starting XI completeness
  - Key player absences (GK, CB, DM, Playmaker, Striker, Captain)
  - Rotation penalty (3+ / 5+ / 7+ changes)

Does NOT modify any probability model.
Output is a standalone squad_strength_score for consumption by prediction layer.
"""
from __future__ import annotations

# ── Penalty weights ─────────────────
PENALTY_GK         = -20   # Goalkeeper
PENALTY_CB         = -10   # Center-back
PENALTY_DM         = -8    # Defensive midfielder
PENALTY_PLAYMAKER  = -12   # Creative playmaker
PENALTY_STRIKER    = -15   # Main striker
PENALTY_CAPTAIN    = -5    # Captain (cumulative on top of position)

ROTATION_3  = -8    # 3+ changes from best XI
ROTATION_5  = -15   # 5+ changes
ROTATION_7  = -25   # 7+ changes (heavy rotation / B-team)


def compute_squad_score(
    starting_xi_count: int = 11,
    missing_positions: list[str] | None = None,
    captain_absent: bool = False,
    rotation_count: int = 0,
) -> int:
    """
    Compute squad strength score.

    Args:
        starting_xi_count: Number of starters available (0-11)
        missing_positions: List of absent key player positions
            Valid values: 'GK','CB','DM','PLAYMAKER','STRIKER'
        captain_absent: Whether the team captain is absent
        rotation_count: Number of changes from best XI (0 = full strength)

    Returns:
        Score 0-100 (100 = full strength)
    """
    score = 100

    # Position penalties
    if missing_positions:
        for pos in missing_positions:
            pos_upper = pos.upper().strip()
            if pos_upper == 'GK':
                score += PENALTY_GK
            elif pos_upper in ('CB', 'CENTERBACK', 'DC'):
                score += PENALTY_CB
            elif pos_upper in ('DM', 'CDM', 'DEFENSIVE MIDFIELDER'):
                score += PENALTY_DM
            elif pos_upper in ('PLAYMAKER', 'AM', 'CAM', '10'):
                score += PENALTY_PLAYMAKER
            elif pos_upper in ('STRIKER', 'ST', 'CF', '9'):
                score += PENALTY_STRIKER

    # Captain penalty (cumulative)
    if captain_absent:
        score += PENALTY_CAPTAIN

    # Rotation penalty
    if rotation_count >= 7:
        score += ROTATION_7
    elif rotation_count >= 5:
        score += ROTATION_5
    elif rotation_count >= 3:
        score += ROTATION_3

    # Starter count floor
    if starting_xi_count < 11:
        missing_starters = 11 - starting_xi_count
        score -= missing_starters * 3  # -3 per missing starter

    return max(0, min(100, score))


def compute_squad_gap(home_score: int, away_score: int) -> dict:
    """
    Compute squad-based adjustment.

    Returns dict with:
        squad_gap: raw difference
        home_strength_adj: adjustment for home team (-1.0 to +1.0)
        away_strength_adj: adjustment for away team (-1.0 to +1.0)
    """
    squad_gap = home_score - away_score
    # Map to [-1.0, +1.0] range: gap of 20 = 1.0 adjustment
    home_adj = squad_gap / 100.0
    away_adj = -squad_gap / 100.0
    return {
        'squad_gap': squad_gap,
        'home_strength_adj': round(home_adj, 3),
        'away_strength_adj': round(away_adj, 3),
    }
