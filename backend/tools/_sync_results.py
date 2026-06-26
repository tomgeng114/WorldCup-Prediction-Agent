"""Fetch latest match results from Sporttery API and update scores."""
import sys, os
os.chdir('E:/Tom/WorldCupAI2026/backend')
sys.path.insert(0, '.')

from app.db import SessionLocal
from app.services.sporttery import sync_sporttery_results

db = SessionLocal()
try:
    result = sync_sporttery_results(db, days=7, commit=True)
    print(f"Fetched: {result.fetched_results}")
    print(f"Settled: {result.settled_matches}")
    print(f"Pending: {result.pending_results}")
    print(f"Skipped: {result.skipped_results}")
finally:
    db.close()
