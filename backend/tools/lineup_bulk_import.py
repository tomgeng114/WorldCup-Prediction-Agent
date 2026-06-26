#!/usr/bin/env python3
"""
Lineup Intelligence Layer — Bulk Import Tool

Usage:
  1. Edit LINEUPS_DATA below with real lineups from match reports
  2. Run: python tools/lineup_bulk_import.py
  3. Verify: curl http://127.0.0.1:8000/api/lineups/stats

Data sources for lineups:
  - FIFA.com match reports
  - Sofascore / Flashscore
  - sporttery.cn
  - zhibo8.com
"""
import json, sqlite3, sys

DB = "worldcup_ai.db"

# ═══════════════════════════════════════════════════════════════
#  TEMPLATE — copy and fill in for each match
# ═══════════════════════════════════════════════════════════════

LINEUPS_DATA = [
    # Paste additional entries here. Format:
    # {
    #     "match_id": 1,
    #     "home": {
    #         "formation": "4-3-3",
    #         "starting_xi": [
    #             {"name": "Player Name", "position": "GK", "number": 1},
    #             ...
    #         ],
    #         "captain": "Captain Name",
    #         "missing_players": [
    #             {"name": "Injured Player", "reason": "injury"},
    #         ],
    #     },
    #     "away": { ... same format ... },
    # },
]


def import_lineups(data: list[dict]):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    inserted = 0
    skipped = 0

    for entry in data:
        match_id = entry["match_id"]

        for side, is_home in [("home", True), ("away", False)]:
            if side not in entry:
                continue
            lu = entry[side]

            # Resolve team_id
            col = "home_team_id" if is_home else "away_team_id"
            cur.execute(f"SELECT {col} FROM matches WHERE id=?", (match_id,))
            row = cur.fetchone()
            if not row:
                print(f"  SKIP match #{match_id} {side}: match not found")
                skipped += 1
                continue
            team_id = row[0]

            # Check duplicate
            cur.execute(
                "SELECT id FROM match_lineups WHERE match_id=? AND team_id=?",
                (match_id, team_id),
            )
            if cur.fetchone():
                print(f"  SKIP match #{match_id} {side}: already exists")
                skipped += 1
                continue

            cur.execute(
                """INSERT INTO match_lineups
                   (match_id, team_id, is_home, formation, starting_xi,
                    substitutes, missing_players, captain, source, notes, created_at)
                   VALUES (?, ?, ?, ?, ?, '[]', ?, ?, 'bulk_import', '', datetime('now'))""",
                (
                    match_id,
                    team_id,
                    1 if is_home else 0,
                    lu.get("formation", ""),
                    json.dumps(lu.get("starting_xi", []), ensure_ascii=False),
                    json.dumps(lu.get("missing_players", []), ensure_ascii=False),
                    lu.get("captain", ""),
                ),
            )
            team_name = "?"
            cur.execute("SELECT name FROM teams WHERE id=?", (team_id,))
            tr = cur.fetchone()
            if tr:
                team_name = tr[0]
            print(f"  + match #{match_id} [{team_name}] {side}: {lu.get('formation', '?')} "
                  f"({len(lu.get('starting_xi', []))} players)")
            inserted += 1

    conn.commit()

    # Stats
    cur.execute("SELECT COUNT(*) FROM match_lineups")
    total = cur.fetchone()[0]
    cur.execute("""
        SELECT COUNT(DISTINCT ml.match_id)
        FROM match_lineups ml
        JOIN matches m ON ml.match_id = m.id
        WHERE m.status = 'finished'
    """)
    completed = cur.fetchone()[0]

    print(f"\n{'='*50}")
    print(f"  Inserted: {inserted}  Skipped: {skipped}")
    print(f"  Total lineup records: {total}")
    print(f"  Completed match samples: {completed}")
    print(f"  Progress: {completed}/50 = {completed/50*100:.0f}%")
    print(f"  Remaining: {max(0, 50 - completed)} completed-match lineups needed")
    conn.close()


if __name__ == "__main__":
    if not LINEUPS_DATA:
        print(__doc__)
        print("\n  Add entries to LINEUPS_DATA in the script and re-run.")
        print(f"  Current progress: ", end="")
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM match_lineups")
        total = cur.fetchone()[0]
        cur.execute("""
            SELECT COUNT(DISTINCT ml.match_id)
            FROM match_lineups ml
            JOIN matches m ON ml.match_id = m.id
            WHERE m.status = 'finished'
        """)
        completed = cur.fetchone()[0]
        print(f"{completed}/50 ({completed/50*100:.0f}%)")
        conn.close()
    else:
        import_lineups(LINEUPS_DATA)
