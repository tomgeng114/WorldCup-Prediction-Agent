from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.core.config import settings


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, future=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_runtime_schema() -> None:
    # Ensure new tables exist (idempotent)
    with engine.begin() as connection:
        if engine.dialect.name == "sqlite":
            existing_tables = {
                row[0]
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "match_lineups" not in existing_tables:
                connection.exec_driver_sql(
                    """CREATE TABLE match_lineups (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        match_id INTEGER NOT NULL REFERENCES matches(id),
                        team_id INTEGER NOT NULL REFERENCES teams(id),
                        is_home BOOLEAN NOT NULL,
                        formation VARCHAR(10) NOT NULL DEFAULT '',
                        starting_xi TEXT NOT NULL DEFAULT '[]',
                        substitutes TEXT NOT NULL DEFAULT '[]',
                        missing_players TEXT NOT NULL DEFAULT '[]',
                        captain VARCHAR(120) NOT NULL DEFAULT '',
                        lineup_strength_score FLOAT,
                        source VARCHAR(200) NOT NULL DEFAULT '',
                        notes TEXT NOT NULL DEFAULT '',
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
                connection.exec_driver_sql(
                    "CREATE INDEX IF NOT EXISTS ix_match_lineups_match_id ON match_lineups(match_id)"
                )
                connection.exec_driver_sql(
                    "CREATE INDEX IF NOT EXISTS ix_match_lineups_team_id ON match_lineups(team_id)"
                )

    prediction_columns = {
        "score_probability": "FLOAT NOT NULL DEFAULT 0",
        "top_scores": "TEXT NOT NULL DEFAULT '[]'",
        "total_goals_probabilities": "TEXT NOT NULL DEFAULT '{}'",
        "model_breakdown": "TEXT NOT NULL DEFAULT '{}'",
        "market_type": "VARCHAR(20) NOT NULL DEFAULT 'HAD'",
        "handicap": "VARCHAR(20) NOT NULL DEFAULT ''",
        "predicted_market_result": "VARCHAR(20) NOT NULL DEFAULT 'Home Win'",
        "market_home_probability": "FLOAT NOT NULL DEFAULT 0",
        "market_draw_probability": "FLOAT NOT NULL DEFAULT 0",
        "market_away_probability": "FLOAT NOT NULL DEFAULT 0",
        "one_goal_handicap_result": "VARCHAR(20) NOT NULL DEFAULT 'Home Win'",
        "one_goal_handicap_probabilities": "TEXT NOT NULL DEFAULT '{}'",
    }
    odds_columns = {
        "source_pool": "VARCHAR(20) NOT NULL DEFAULT 'HAD'",
        "handicap": "VARCHAR(20) NOT NULL DEFAULT ''",
    }
    world_cup_profile_columns = {
        "country": "VARCHAR(120) NOT NULL DEFAULT ''",
        "confederation": "VARCHAR(20) NOT NULL DEFAULT ''",
        "fifa_ranking": "INTEGER",
        "elo_rating": "FLOAT",
        "coach": "VARCHAR(120) NOT NULL DEFAULT ''",
        "last_world_cup_finish": "VARCHAR(120) NOT NULL DEFAULT ''",
        "world_cup_strength_score": "FLOAT",
        "upset_alert_score": "VARCHAR(20) NOT NULL DEFAULT 'Low'",
    }
    with engine.begin() as connection:
        if engine.dialect.name == "sqlite":
            existing = {
                row[1]
                for row in connection.exec_driver_sql("PRAGMA table_info(predictions)").fetchall()
            }
            for column, definition in prediction_columns.items():
                if column not in existing:
                    connection.exec_driver_sql(f"ALTER TABLE predictions ADD COLUMN {column} {definition}")
            existing_odds = {
                row[1]
                for row in connection.exec_driver_sql("PRAGMA table_info(odds_snapshots)").fetchall()
            }
            for column, definition in odds_columns.items():
                if column not in existing_odds:
                    connection.exec_driver_sql(f"ALTER TABLE odds_snapshots ADD COLUMN {column} {definition}")
            profile_table = connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='world_cup_team_profiles'"
            ).fetchone()
            if profile_table:
                existing_profiles = {
                    row[1]
                    for row in connection.exec_driver_sql("PRAGMA table_info(world_cup_team_profiles)").fetchall()
                }
                for column, definition in world_cup_profile_columns.items():
                    if column not in existing_profiles:
                        connection.exec_driver_sql(f"ALTER TABLE world_cup_team_profiles ADD COLUMN {column} {definition}")
        elif engine.dialect.name == "postgresql":
            for column, definition in prediction_columns.items():
                connection.execute(text(f"ALTER TABLE predictions ADD COLUMN IF NOT EXISTS {column} {definition}"))
            for column, definition in odds_columns.items():
                connection.execute(text(f"ALTER TABLE odds_snapshots ADD COLUMN IF NOT EXISTS {column} {definition}"))
            for column, definition in world_cup_profile_columns.items():
                connection.execute(text(f"ALTER TABLE world_cup_team_profiles ADD COLUMN IF NOT EXISTS {column} {definition}"))
