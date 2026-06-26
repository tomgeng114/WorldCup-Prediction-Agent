from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.db import SessionLocal
from app.models import Match
from app.services.sporttery import sync_sporttery_matches
from app.services.statistics import settle_match, settled_matches


scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


def sync_sporttery_job() -> None:
    with SessionLocal() as db:
        sync_sporttery_matches(db, purge_legacy_samples=True)


def settle_results_job() -> None:
    with SessionLocal() as db:
        matches = db.scalars(
            select(Match)
            .options(joinedload(Match.prediction), joinedload(Match.odds))
            .where(Match.status == "finished")
        ).unique().all()
        for match in settled_matches(matches):
            settle_match(match)
        db.commit()


def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.add_job(sync_sporttery_job, "interval", minutes=15, id="sporttery_sync", replace_existing=True)
    scheduler.add_job(settle_results_job, "cron", hour=0, minute=10, id="daily_settlement", replace_existing=True)
    scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
