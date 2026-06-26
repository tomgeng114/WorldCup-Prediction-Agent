#!/usr/bin/env python3
"""Backtest current model on 2018+2022 World Cup + upset/confidence breakdown."""
import sys, os, json, math
os.chdir('E:/Tom/WorldCupAI2026/backend')
sys.path.insert(0, '.')

import sqlite3
from collections import defaultdict

DB = 'worldcup_ai.db'
conn = sqlite3.connect(DB)
cur = conn.cursor()

# ── Load 2018+2022 WC matches with odds ──
cur.execute("""
    SELECT wcm.id, wcm.tournament_year, wcm.match_date, wcm.stage,
           wcm.home_team, wcm.away_team, wcm.home_score, wcm.away_score, wcm.result,
           wo.home_win_odds, wo.draw_odds, wo.away_win_odds
    FROM world_cup_matches wcm
    JOIN world_cup_odds wo ON wcm.id = wo.match_id
    WHERE wcm.tournament_year IN (2018, 2022)
    ORDER BY wcm.match_date ASC
""")
wc_rows = cur.fetchall()

# ── Load team data (ELO, xG, etc.) ──
cur.execute("SELECT id, name, elo_rating, xg_for, xga_against, world_cup_history_score, recent_form FROM teams")
team_rows = cur.fetchall()
team_map = {}
for tr in team_rows:
    team_map[tr[1]] = {"id": tr[0], "elo": tr[2] or 1500, "xg_for": tr[3] or 1.5, "xga": tr[4] or 1.0, "history": tr[5] or 0.5, "form": tr[6] or 0.5}
# Add missing teams from WC history
for r in wc_rows:
    for tn in [r[4], r[5]]:
        if tn not in team_map:
            team_map[tn] = {"id": 0, "elo": 1500, "xg_for": 1.5, "xga": 1.0, "history": 0.5, "form": 0.5}

conn.close()

# ── Now use the predictor ──
from app.db import SessionLocal
from app.models import Match as MatchModel, Team as TeamModel, OddsSnapshot
from app.services.predictor import predict_match
from sqlalchemy.orm import joinedload
from sqlalchemy import select

def build_team(name):
    t = team_map.get(name, team_map.get(_fuzzy_match(name, team_map), {"elo": 1500, "xg_for": 1.5, "xga": 1.0, "history": 0.5, "form": 0.5}))
    tm = TeamModel()
    tm.name = name; tm.elo_rating = t["elo"]; tm.xg_for = t["xg_for"]
    tm.xga_against = t["xga"]; tm.world_cup_history_score = t["history"]; tm.recent_form = t["form"]
    tm.fifa_rank = 999
    return tm

def _fuzzy_match(name, team_map):
    for k in team_map:
        if name[:3] in k or k[:3] in name: return k
    return None

def build_odds(h_odds, d_odds, a_odds):
    o = OddsSnapshot()
    o.home_win_odds = h_odds or 2.0; o.draw_odds = d_odds or 3.0; o.away_win_odds = a_odds or 3.0
    o.over_25_odds = 1.9; o.under_25_odds = 1.9; o.asian_line = 0.0
    o.line_movement = 0.0; o.kelly_index = 0.95; o.source_pool = "HAD"; o.handicap = ""
    return o

print(f"Backtesting {len(wc_rows)} matches (2018+2022 World Cup)...")
print(f"{'#':>4} {'Match':32s} {'Score':>5} {'Result':>10} {'Pred':>11} {'dp':>6} {'upset':>6} {'conf':>6} {'Top1':>5} {'Top3':32s} {'Hit':>4}")
print('='*130)

hits = 0; n = 0; draw_hits = 0; draw_pred = 0; draw_act = 0
upset_buckets = defaultdict(lambda: {"total": 0, "hits": 0})
conf_buckets = defaultdict(lambda: {"total": 0, "hits": 0})

for r in wc_rows:
    wid, year, date, stage, hn, an, hs, aws, result, h_odds, d_odds, a_odds = r
    if hs is None or aws is None: continue
    actual = "Home Win" if hs > aws else ("Draw" if hs == aws else "Away Win")
    actual_score = f"{hs}-{aws}"

    home_tm = build_team(hn); away_tm = build_team(an)
    odds_obj = build_odds(h_odds, d_odds, a_odds)
    match_obj = MatchModel()
    match_obj.home_team = home_tm; match_obj.away_team = away_tm
    match_obj.home_team_id = 1; match_obj.away_team_id = 2
    match_obj.competition = "World Cup"; match_obj.kickoff_time = date
    match_obj.id = wid

    try:
        p = predict_match(match_obj, odds_obj)
    except Exception as e:
        continue

    pred = p.predicted_result; t1_s = p.predicted_score
    t3_s = [s['score'] for s in (p.top_scores or [])[:3]]
    upset = p.upset_probability; conf = p.confidence; dp = p.draw_probability
    hit = 'Y' if pred == actual else 'N'
    n += 1
    if hit == 'Y': hits += 1
    if actual == 'Draw': draw_act += 1
    if pred == 'Draw': draw_pred += 1
    if pred == 'Draw' and actual == 'Draw': draw_hits += 1

    # Buckets
    ub = f"{int(upset//10)*10}-{int(upset//10)*10+9}" if upset < 100 else "90-100"
    upset_buckets[ub]["total"] += 1
    if hit == 'Y': upset_buckets[ub]["hits"] += 1

    cb = f"{int(conf//10)*10}-{int(conf//10)*10+9}" if conf < 100 else "90-100"
    conf_buckets[cb]["total"] += 1
    if hit == 'Y': conf_buckets[cb]["hits"] += 1

    label = f'{hn[:14]} vs {an[:14]}'; t3s = ' / '.join(t3_s)
    print(f'{wid:4d} {label:32s} {actual_score:>5} {actual:>10} {pred:>11} {dp:.3f} {upset:5.1f} {conf:5.1f} {t1_s:>5} {t3s:32s} {hit:>4}')

acc = hits / n * 100 if n else 0
dr = draw_hits / draw_act * 100 if draw_act else 0
dp_ = draw_hits / draw_pred * 100 if draw_pred else 0

print(f'\nACCURACY: {acc:.1f}% ({hits}/{n})  DrawR: {dr:.1f}% ({draw_hits}/{draw_act})  DrawP: {dp_:.1f}% ({draw_hits}/{draw_pred})')
print(f'\nUPSET PROBABILITY BUCKETS:')
for ub in sorted(upset_buckets.keys(), key=lambda x: int(x.split('-')[0])):
    b = upset_buckets[ub]
    rate = b["hits"] / b["total"] * 100 if b["total"] else 0
    bar = '█' * int(rate / 5)
    print(f'  upset {ub:>7}%: {b["hits"]:3d}/{b["total"]:3d} = {rate:5.1f}% {bar}')

print(f'\nCONFIDENCE BUCKETS:')
for cb in sorted(conf_buckets.keys(), key=lambda x: int(x.split('-')[0])):
    b = conf_buckets[cb]
    rate = b["hits"] / b["total"] * 100 if b["total"] else 0
    bar = '█' * int(rate / 5)
    print(f'  conf  {cb:>7}%: {b["hits"]:3d}/{b["total"]:3d} = {rate:5.1f}% {bar}')
