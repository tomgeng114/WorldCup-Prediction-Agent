from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(8), unique=True, nullable=False)
    group_name: Mapped[str] = mapped_column(String(10), nullable=False)
    fifa_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    elo_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    recent_form: Mapped[float] = mapped_column(Float, nullable=False)
    xg_for: Mapped[float] = mapped_column(Float, nullable=False)
    xga_against: Mapped[float] = mapped_column(Float, nullable=False)
    world_cup_history_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    competition: Mapped[str] = mapped_column(String(80), nullable=False, default="World Cup")
    stage: Mapped[str] = mapped_column(String(80), nullable=False, default="Group Stage")
    kickoff_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    venue: Mapped[str] = mapped_column(String(120), nullable=False)
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="scheduled")

    home_team: Mapped[Team] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped[Team] = relationship(foreign_keys=[away_team_id])
    odds: Mapped["OddsSnapshot"] = relationship(back_populates="match", uselist=False)
    prediction: Mapped["Prediction"] = relationship(back_populates="match", uselist=False)


class OddsSnapshot(Base):
    __tablename__ = "odds_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), unique=True)
    home_win_odds: Mapped[float] = mapped_column(Float, nullable=False)
    draw_odds: Mapped[float] = mapped_column(Float, nullable=False)
    away_win_odds: Mapped[float] = mapped_column(Float, nullable=False)
    over_25_odds: Mapped[float] = mapped_column(Float, nullable=False)
    under_25_odds: Mapped[float] = mapped_column(Float, nullable=False)
    asian_line: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source_pool: Mapped[str] = mapped_column(String(20), nullable=False, default="HAD")
    handicap: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    line_movement: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    kelly_index: Mapped[float] = mapped_column(Float, nullable=False, default=0.95)

    match: Mapped[Match] = relationship(back_populates="odds")


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), unique=True)
    home_win_probability: Mapped[float] = mapped_column(Float, nullable=False)
    draw_probability: Mapped[float] = mapped_column(Float, nullable=False)
    away_win_probability: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_result: Mapped[str] = mapped_column(String(20), nullable=False)
    predicted_score: Mapped[str] = mapped_column(String(20), nullable=False)
    backup_scores: Mapped[str] = mapped_column(String(120), nullable=False)
    half_full_time: Mapped[str] = mapped_column(String(20), nullable=False)
    total_goals_band: Mapped[str] = mapped_column(String(20), nullable=False)
    over_under_pick: Mapped[str] = mapped_column(String(20), nullable=False)
    both_teams_to_score: Mapped[str] = mapped_column(String(10), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    upset_probability: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    score_probability: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    top_scores: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    total_goals_probabilities: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    model_breakdown: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    market_type: Mapped[str] = mapped_column(String(20), nullable=False, default="HAD")
    handicap: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    predicted_market_result: Mapped[str] = mapped_column(String(20), nullable=False, default="Home Win")
    market_home_probability: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    market_draw_probability: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    market_away_probability: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    one_goal_handicap_result: Mapped[str] = mapped_column(String(20), nullable=False, default="Home Win")
    one_goal_handicap_probabilities: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    report_preview: Mapped[str] = mapped_column(Text, nullable=False)
    is_red_pick: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    match: Mapped[Match] = relationship(back_populates="prediction")


class WorldCupMatch(Base):
    __tablename__ = "world_cup_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_year: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    match_date: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    stage: Mapped[str] = mapped_column(String(80), nullable=False)
    group_name: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    ground: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    home_team: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    away_team: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    home_score: Mapped[int] = mapped_column(Integer, nullable=False)
    away_score: Mapped[int] = mapped_column(Integer, nullable=False)
    home_half_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    away_half_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    half_result: Mapped[str] = mapped_column(String(20), nullable=False)
    half_full_result: Mapped[str] = mapped_column(String(20), nullable=False)
    total_goals: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False, default="")


class WorldCupOdds(Base):
    __tablename__ = "world_cup_odds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("world_cup_matches.id"), unique=True, index=True, nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False, default="manual_verified")
    captured_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    home_win_odds: Mapped[float] = mapped_column(Float, nullable=False)
    draw_odds: Mapped[float] = mapped_column(Float, nullable=False)
    away_win_odds: Mapped[float] = mapped_column(Float, nullable=False)
    handicap: Mapped[float | None] = mapped_column(Float, nullable=True)
    handicap_home_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    handicap_draw_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    handicap_away_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    match: Mapped[WorldCupMatch] = relationship()


class WorldCupTeamProfile(Base):
    __tablename__ = "world_cup_team_profiles"
    __table_args__ = (
        UniqueConstraint("tournament_year", "team_name", name="uq_world_cup_team_profile"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_year: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    team_name: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    country: Mapped[str] = mapped_column(String(120), index=True, nullable=False, default="")
    confederation: Mapped[str] = mapped_column(String(20), index=True, nullable=False, default="")
    fifa_ranking: Mapped[int | None] = mapped_column(Integer, nullable=True)
    elo_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    projected_starting_xi: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    key_injuries: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    squad_market_value_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_age: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_caps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    average_caps: Mapped[float | None] = mapped_column(Float, nullable=True)
    world_cup_history_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    recent_two_year_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    coach: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    last_world_cup_finish: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    world_cup_strength_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    upset_alert_score: Mapped[str] = mapped_column(String(20), nullable=False, default="Low")
    source: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    captured_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_version: Mapped[str] = mapped_column(String(80), nullable=False, default="worldcup_backtest_v1")
    years: Mapped[str] = mapped_column(String(120), nullable=False)
    total_matches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metrics: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    initial_weights: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    final_weights: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class BacktestPrediction(Base):
    __tablename__ = "backtest_predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"), index=True, nullable=False)
    match_id: Mapped[int] = mapped_column(ForeignKey("world_cup_matches.id"), index=True, nullable=False)
    predicted_result: Mapped[str] = mapped_column(String(20), nullable=False)
    actual_result: Mapped[str] = mapped_column(String(20), nullable=False)
    predicted_score: Mapped[str] = mapped_column(String(20), nullable=False)
    actual_score: Mapped[str] = mapped_column(String(20), nullable=False)
    predicted_half_full: Mapped[str] = mapped_column(String(20), nullable=False)
    actual_half_full: Mapped[str] = mapped_column(String(20), nullable=False)
    predicted_total_goals: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_total_goals: Mapped[int] = mapped_column(Integer, nullable=False)
    home_win_probability: Mapped[float] = mapped_column(Float, nullable=False)
    draw_probability: Mapped[float] = mapped_column(Float, nullable=False)
    away_win_probability: Mapped[float] = mapped_column(Float, nullable=False)
    result_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    score_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    half_full_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    total_goals_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    brier_score: Mapped[float] = mapped_column(Float, nullable=False)
    roi: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    component_predictions: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    weights: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class Competition(Base):
    __tablename__ = "competitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    region: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class InternationalMatch(Base):
    __tablename__ = "international_matches"
    __table_args__ = (
        UniqueConstraint("competition_id", "match_date", "home_team", "away_team", name="uq_international_match"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"), index=True, nullable=False)
    competition: Mapped[Competition] = relationship()
    season: Mapped[str] = mapped_column(String(40), nullable=False)
    qualifier_region: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    stage: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    match_date: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    home_team: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    away_team: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    home_score: Mapped[int] = mapped_column(Integer, nullable=False)
    away_score: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class InternationalOdds(Base):
    __tablename__ = "international_odds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("international_matches.id"), unique=True, index=True, nullable=False)
    match: Mapped[InternationalMatch] = relationship()
    source: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    captured_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    home_win_odds: Mapped[float] = mapped_column(Float, nullable=False)
    draw_odds: Mapped[float] = mapped_column(Float, nullable=False)
    away_win_odds: Mapped[float] = mapped_column(Float, nullable=False)
    home_win_max_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    draw_max_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    away_win_max_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    handicap: Mapped[float | None] = mapped_column(Float, nullable=True)
    handicap_home_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    handicap_away_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class InternationalBacktestRun(Base):
    __tablename__ = "international_backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_name: Mapped[str] = mapped_column(String(120), nullable=False)
    model_version: Mapped[str] = mapped_column(String(80), nullable=False, default="international_value_v1")
    competition_code: Mapped[str] = mapped_column(String(40), nullable=False)
    region_filter: Mapped[str] = mapped_column(String(120), nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metrics: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class MatchLineup(Base):
    """Lineup Intelligence Layer v1 — per-match, per-team starting lineup record.

    Read-only. Does NOT affect predictions. Accumulate 50 samples before
    proving predictive value.
    """

    __tablename__ = "match_lineups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    is_home: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # Formation
    formation: Mapped[str] = mapped_column(String(10), nullable=False, default="")

    # Starting XI — JSON array of {"name": str, "position": str, "number": int}
    starting_xi: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    # Substitutes — JSON array
    substitutes: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    # Missing key players (injuries, suspensions, rest) — JSON array of {"name": str, "reason": str}
    missing_players: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    # Captain
    captain: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    # Computed strength score 0–100 (TBD — placeholder for v2)
    lineup_strength_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Data source
    source: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    # Notes
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    match: Mapped[Match] = relationship(foreign_keys=[match_id])
    team: Mapped[Team] = relationship(foreign_keys=[team_id])


class InternationalBacktestPrediction(Base):
    __tablename__ = "international_backtest_predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("international_backtest_runs.id"), index=True, nullable=False)
    match_id: Mapped[int] = mapped_column(ForeignKey("international_matches.id"), index=True, nullable=False)
    predicted_result: Mapped[str] = mapped_column(String(20), nullable=False)
    actual_result: Mapped[str] = mapped_column(String(20), nullable=False)
    home_win_probability: Mapped[float] = mapped_column(Float, nullable=False)
    draw_probability: Mapped[float] = mapped_column(Float, nullable=False)
    away_win_probability: Mapped[float] = mapped_column(Float, nullable=False)
    market_home_probability: Mapped[float] = mapped_column(Float, nullable=False)
    market_draw_probability: Mapped[float] = mapped_column(Float, nullable=False)
    market_away_probability: Mapped[float] = mapped_column(Float, nullable=False)
    best_value_pick: Mapped[str] = mapped_column(String(20), nullable=False)
    best_value_edge: Mapped[float] = mapped_column(Float, nullable=False)
    value_bet_signal: Mapped[str] = mapped_column(String(20), nullable=False)
    odds: Mapped[float] = mapped_column(Float, nullable=False)
    stake: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    profit: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    component_probabilities: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
