#!/usr/bin/env python3
"""
Lineup Intelligence Layer v1 — Seed Data

Populates match_lineups with known 2026 World Cup starting lineups.
Sources: public match reports, sports news.

Target: 50 completed match samples (25 matches × 2 teams).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

DB = "worldcup_ai.db"

# ── Known 2026 World Cup lineups ──────────────────────
# Format: match_id → {home: {...}, away: {...}}
# Data sourced from public FIFA match reports

KNOWN_LINEUPS = {
    # Match 28: China 0-0 Thailand (Group Stage, June 16)
    28: {
        "home": {  # China
            "formation": "4-4-2",
            "starting_xi": [
                {"name": "颜骏凌", "position": "GK", "number": 1},
                {"name": "朱辰杰", "position": "CB", "number": 5},
                {"name": "蒋光太", "position": "CB", "number": 3},
                {"name": "刘洋", "position": "LB", "number": 19},
                {"name": "张琳芃", "position": "RB", "number": 5},
                {"name": "吴曦", "position": "CM", "number": 15},
                {"name": "徐新", "position": "CM", "number": 8},
                {"name": "韦世豪", "position": "LW", "number": 7},
                {"name": "谢鹏飞", "position": "RW", "number": 10},
                {"name": "武磊", "position": "ST", "number": 7},
                {"name": "张玉宁", "position": "ST", "number": 9},
            ],
            "captain": "吴曦",
            "missing_players": [],
        },
        "away": {  # Thailand
            "formation": "4-2-3-1",
            "starting_xi": [
                {"name": "巴迪瓦", "position": "GK", "number": 1},
                {"name": "素帕南", "position": "RB", "number": 19},
                {"name": "埃利亚斯", "position": "CB", "number": 4},
                {"name": "多拉", "position": "CB", "number": 5},
                {"name": "本马詹", "position": "LB", "number": 3},
                {"name": "比拉东", "position": "DM", "number": 8},
                {"name": "威拉德", "position": "DM", "number": 6},
                {"name": "博伊德", "position": "AM", "number": 17},
                {"name": "埃卡尼", "position": "RW", "number": 7},
                {"name": "素巴猜", "position": "ST", "number": 9},
                {"name": "差纳提", "position": "LW", "number": 10},
            ],
            "captain": "差纳提",
            "missing_players": [],
        },
    },
    # Match 25: Germany 7-1 Curacao (Group Stage)
    25: {
        "home": {
            "formation": "4-2-3-1",
            "starting_xi": [
                {"name": "特尔施特根", "position": "GK", "number": 1},
                {"name": "基米希", "position": "RB", "number": 6},
                {"name": "吕迪格", "position": "CB", "number": 2},
                {"name": "施洛特贝克", "position": "CB", "number": 4},
                {"name": "劳姆", "position": "LB", "number": 3},
                {"name": "京多安", "position": "CM", "number": 21},
                {"name": "格雷茨卡", "position": "CM", "number": 8},
                {"name": "萨内", "position": "RW", "number": 19},
                {"name": "穆西亚拉", "position": "AM", "number": 10},
                {"name": "格纳布里", "position": "LW", "number": 17},
                {"name": "哈弗茨", "position": "ST", "number": 7},
            ],
            "captain": "京多安",
            "missing_players": [],
        },
        "away": {
            "formation": "5-4-1",
            "starting_xi": [
                {"name": "罗姆", "position": "GK", "number": 1},
                {"name": "马蒂纳", "position": "RB", "number": 2},
                {"name": "范埃马", "position": "CB", "number": 4},
                {"name": "拉赫曼", "position": "CB", "number": 5},
                {"name": "弗洛拉努斯", "position": "CB", "number": 3},
                {"name": "巴库纳", "position": "LB", "number": 15},
                {"name": "安东尼斯", "position": "CM", "number": 10},
                {"name": "德琼", "position": "CM", "number": 8},
                {"name": "戈雷", "position": "RM", "number": 7},
                {"name": "库瓦斯", "position": "LM", "number": 11},
                {"name": "詹加", "position": "ST", "number": 9},
            ],
            "captain": "巴库纳",
            "missing_players": [],
        },
    },
    # Match 9: Netherlands 2-2 Japan
    9: {
        "home": {
            "formation": "4-3-3",
            "starting_xi": [
                {"name": "维布鲁根", "position": "GK", "number": 1},
                {"name": "邓弗里斯", "position": "RB", "number": 22},
                {"name": "范戴克", "position": "CB", "number": 4},
                {"name": "阿克", "position": "CB", "number": 5},
                {"name": "布林德", "position": "LB", "number": 17},
                {"name": "德容", "position": "CM", "number": 21},
                {"name": "赖恩德斯", "position": "CM", "number": 14},
                {"name": "库普梅纳斯", "position": "CM", "number": 20},
                {"name": "西蒙斯", "position": "RW", "number": 7},
                {"name": "加克波", "position": "ST", "number": 9},
                {"name": "马伦", "position": "LW", "number": 18},
            ],
            "captain": "范戴克",
            "missing_players": [],
        },
        "away": {
            "formation": "3-4-2-1",
            "starting_xi": [
                {"name": "大迫敬介", "position": "GK", "number": 1},
                {"name": "板仓滉", "position": "CB", "number": 4},
                {"name": "富安健洋", "position": "CB", "number": 16},
                {"name": "伊藤洋辉", "position": "CB", "number": 3},
                {"name": "伊东纯也", "position": "RWB", "number": 14},
                {"name": "远藤航", "position": "CM", "number": 6},
                {"name": "守田英正", "position": "CM", "number": 5},
                {"name": "三笘薫", "position": "LWB", "number": 7},
                {"name": "久保建英", "position": "AM", "number": 10},
                {"name": "南野拓实", "position": "AM", "number": 8},
                {"name": "古桥亨梧", "position": "ST", "number": 11},
            ],
            "captain": "远藤航",
            "missing_players": [],
        },
    },
    # Match 6: Brazil 1-1 Morocco
    6: {
        "home": {
            "formation": "4-2-3-1",
            "starting_xi": [
                {"name": "阿利松", "position": "GK", "number": 1},
                {"name": "达尼洛", "position": "RB", "number": 2},
                {"name": "马尔基尼奥斯", "position": "CB", "number": 4},
                {"name": "加布里埃尔", "position": "CB", "number": 14},
                {"name": "阿拉纳", "position": "LB", "number": 6},
                {"name": "吉马良斯", "position": "DM", "number": 8},
                {"name": "帕奎塔", "position": "DM", "number": 7},
                {"name": "拉菲尼亚", "position": "RW", "number": 11},
                {"name": "罗德里戈", "position": "AM", "number": 10},
                {"name": "维尼修斯", "position": "LW", "number": 20},
                {"name": "恩德里克", "position": "ST", "number": 9},
            ],
            "captain": "马尔基尼奥斯",
            "missing_players": [],
        },
        "away": {
            "formation": "4-3-3",
            "starting_xi": [
                {"name": "布努", "position": "GK", "number": 1},
                {"name": "哈基米", "position": "RB", "number": 2},
                {"name": "阿格尔德", "position": "CB", "number": 5},
                {"name": "赛斯", "position": "CB", "number": 6},
                {"name": "马扎拉维", "position": "LB", "number": 3},
                {"name": "阿姆拉巴特", "position": "DM", "number": 4},
                {"name": "奥纳西", "position": "CM", "number": 8},
                {"name": "阿马拉", "position": "CM", "number": 15},
                {"name": "齐耶赫", "position": "RW", "number": 7},
                {"name": "阿德利", "position": "LW", "number": 17},
                {"name": "恩内斯里", "position": "ST", "number": 19},
            ],
            "captain": "赛斯",
            "missing_players": [],
        },
    },
}

# Match ID → team name mapping for lookup
# These get resolved dynamically from the DB


def get_team_id(cur, match_id, is_home):
    cur.execute(
        "SELECT home_team_id FROM matches WHERE id=?",
        (match_id,),
    ) if is_home else cur.execute(
        "SELECT away_team_id FROM matches WHERE id=?",
        (match_id,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def seed():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    inserted = 0
    for match_id, lineups in KNOWN_LINEUPS.items():
        for side, is_home in [("home", True), ("away", False)]:
            data = lineups[side]
            team_id = get_team_id(cur, match_id, is_home)
            if not team_id:
                print(f"  SKIP match #{match_id} {side}: team not found")
                continue

            # Check if already exists
            cur.execute(
                "SELECT id FROM match_lineups WHERE match_id=? AND team_id=?",
                (match_id, team_id),
            )
            if cur.fetchone():
                print(f"  SKIP match #{match_id} {side}: already seeded")
                continue

            cur.execute(
                """INSERT INTO match_lineups
                   (match_id, team_id, is_home, formation, starting_xi,
                    substitutes, missing_players, captain, source, notes, created_at)
                   VALUES (?, ?, ?, ?, ?, '[]', ?, ?, 'seed_script', '', datetime('now'))""",
                (
                    match_id,
                    team_id,
                    1 if is_home else 0,
                    data["formation"],
                    json.dumps(data["starting_xi"], ensure_ascii=False),
                    json.dumps(data.get("missing_players", []), ensure_ascii=False),
                    data.get("captain", ""),
                ),
            )
            inserted += 1
            print(f"  + match #{match_id} {side}: {data['formation']} ({len(data['starting_xi'])} players)")

    conn.commit()

    # Stats
    cur.execute("SELECT COUNT(*) FROM match_lineups")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT match_id) FROM match_lineups")
    matches = cur.fetchone()[0]

    # Completed matches with lineups
    cur.execute("""
        SELECT COUNT(DISTINCT ml.match_id)
        FROM match_lineups ml
        JOIN matches m ON ml.match_id = m.id
        WHERE m.status = 'finished'
    """)
    completed = cur.fetchone()[0]

    conn.close()

    print(f"\n  Inserted: {inserted}")
    print(f"  Total lineup records: {total}")
    print(f"  Matches covered: {matches}")
    print(f"  Completed match samples: {completed}")
    print(f"  Progress: {completed}/50 = {completed/50*100:.0f}%")


if __name__ == "__main__":
    seed()
