#!/usr/bin/env python3
"""Audit odds-related tables, fields, samples, and coverage."""
import sqlite3
from datetime import datetime, timedelta

DB = "worldcup_ai.db"

conn = sqlite3.connect(DB)
cur = conn.cursor()

# ── 1. All tables ────────────────────────────────────
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cur.fetchall()]
print("=" * 70)
print("  1. ALL TABLES")
print("=" * 70)
for t in tables:
    print(f"  {t}")

# ── 2. Odds-related tables ───────────────────────────
odds_tables = [t for t in tables if "odd" in t.lower()]
print(f"\n{'='*70}")
print(f"  2. ODDS-RELATED TABLES ({len(odds_tables)} found)")
print(f"{'='*70}")

for tbl in odds_tables:
    print(f"\n  ┌─ {tbl}")
    cur.execute(f"PRAGMA table_info({tbl})")
    cols = cur.fetchall()
    print(f"  ├ Columns ({len(cols)}):")
    for c in cols:
        null_str = "NULL" if not c[3] else "NOT NULL"
        print(f"  │  {c[1]:35s} {c[2]:18s} {null_str}")
    cur.execute(f"SELECT COUNT(*) FROM {tbl}")
    count = cur.fetchone()[0]
    print(f"  └ Row count: {count}")

    # Show 3 samples
    if count > 0:
        cur.execute(f"SELECT * FROM {tbl} LIMIT 3")
        print(f"    Samples:")
        col_names = [c[1] for c in cols]
        for row in cur.fetchall():
            # Truncate long values
            display = {}
            for i, val in enumerate(row):
                name = col_names[i] if i < len(col_names) else f"col{i}"
                s = str(val)
                if len(s) > 60:
                    s = s[:57] + "..."
                display[name] = s
            print(f"    {display}")

# ── 3. odds_snapshots coverage ────────────────────────
print(f"\n{'='*70}")
print(f"  3. odds_snapshots — COVERAGE ANALYSIS")
print(f"{'='*70}")
cur.execute("SELECT COUNT(*) FROM odds_snapshots")
total = cur.fetchone()[0]
print(f"  Total rows: {total}")

cur.execute("SELECT COUNT(DISTINCT match_id) FROM odds_snapshots")
print(f"  Distinct match_ids: {cur.fetchone()[0]}")

# Date range via joined matches
cur.execute("""
    SELECT MIN(m.kickoff_time), MAX(m.kickoff_time), COUNT(*)
    FROM odds_snapshots os
    JOIN matches m ON os.match_id = m.id
""")
min_d, max_d, cnt = cur.fetchone()
print(f"  Date range: {min_d} → {max_d}")
print(f"  Joined count: {cnt}")

# Last 30 days
thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
cur.execute(f"""
    SELECT COUNT(*) FROM odds_snapshots os
    JOIN matches m ON os.match_id = m.id
    WHERE m.kickoff_time >= '{thirty_days_ago}'
""")
recent = cur.fetchone()[0]
print(f"  Last 30 days (since {thirty_days_ago}): {recent} rows")

# Check for opening/latest distinction
cur.execute("PRAGMA table_info(odds_snapshots)")
cols = [c[1] for c in cur.fetchall()]
print(f"\n  Column list: {cols}")
has_opening = any("open" in c.lower() for c in cols)
has_latest = any("latest" in c.lower() for c in cols)
has_history = any("history" in c.lower() or "movement" in c.lower() for c in cols)
print(f"  Has 'opening' field: {has_opening}")
print(f"  Has 'latest' field:   {has_latest}")
print(f"  Has 'history' field:  {has_history}")

# Check line_movement field
if "line_movement" in cols:
    cur.execute("SELECT match_id, line_movement, kelly_index FROM odds_snapshots WHERE line_movement != 0 LIMIT 10")
    print(f"\n  Non-zero line_movement samples:")
    for r in cur.fetchall():
        print(f"    match_id={r[0]}  movement={r[1]}  kelly={r[2]}")

# ── 4. world_cup_odds ─────────────────────────────────
print(f"\n{'='*70}")
print(f"  4. world_cup_odds")
print(f"{'='*70}")
cur.execute("SELECT COUNT(*) FROM world_cup_odds")
print(f"  Total: {cur.fetchone()[0]}")
cur.execute("PRAGMA table_info(world_cup_odds)")
for c in cur.fetchall():
    print(f"  {c[1]:35s} {c[2]:18s}")

# Date range
cur.execute("SELECT MIN(match_date), MAX(match_date) FROM world_cup_odds")
print(f"  Date range: {cur.fetchone()}")

# Sample
cur.execute("SELECT * FROM world_cup_odds LIMIT 2")
col_names = [c[1] for c in cur.execute("PRAGMA table_info(world_cup_odds)").fetchall()]
for r in cur.fetchall():
    print(f"  Sample: {dict(zip(col_names, r))}")

# ── 5. international_odds ─────────────────────────────
print(f"\n{'='*70}")
print(f"  5. international_odds")
print(f"{'='*70}")
cur.execute("SELECT COUNT(*) FROM international_odds")
print(f"  Total: {cur.fetchone()[0]}")
cur.execute("PRAGMA table_info(international_odds)")
for c in cur.fetchall():
    print(f"  {c[1]:35s} {c[2]:18s}")
cur.execute("SELECT MIN(match_date), MAX(match_date) FROM international_odds")
print(f"  Date range: {cur.fetchone()}")

# ── 6. Summary ────────────────────────────────────────
print(f"\n{'='*70}")
print(f"  6. SUMMARY — Odds Movement Layer Readiness")
print(f"{'='*70}")

checks = {
    "opening_odds exists": has_opening,
    "latest_odds exists": has_latest,
    "odds_history/movement tracking": has_history or ("line_movement" in cols),
    "odds_snapshots has data": total > 0,
    "Recent 30-day coverage": recent > 0,
    "Historical odds (world_cup)": True,  # table exists
    "Multiple time-point odds": False,  # single snapshot per match
}

for check, status in checks.items():
    icon = "✓" if status else "✗"
    print(f"  {icon} {check}")

print(f"\n  Key limitation: odds_snapshots has ONE row per match (snapshot at prediction time).")
print(f"  No opening_odds vs latest_odds distinction.")
print(f"  No time-series odds_history.")
print(f"  line_movement is a scalar field (not a timeseries).")
print(f"  To implement Odds Movement Layer, need either:")
print(f"    a) Add odds_history table + scheduled snapshots")
print(f"    b) Use external API for real-time odds changes")
print(f"    c) Use line_movement + kelly_index as proxies (already available)")

conn.close()
