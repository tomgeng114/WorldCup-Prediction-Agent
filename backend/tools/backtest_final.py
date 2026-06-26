#!/usr/bin/env python3
"""36-match backtest — rolled-back predictor (ELO+Form+Odds+Poisson+MC+DC + lambda x1.08)"""
import sys, os
os.chdir('E:/Tom/WorldCupAI2026/backend'); sys.path.insert(0, '.')
from app.db import SessionLocal; from app.models import Match
from app.services.predictor import predict_match
from sqlalchemy.orm import joinedload; from sqlalchemy import select

db = SessionLocal()
matches = db.scalars(
    select(Match).where(Match.home_score.isnot(None), Match.away_score.isnot(None))
    .options(joinedload(Match.home_team), joinedload(Match.away_team), joinedload(Match.odds))
    .order_by(Match.kickoff_time.asc())
).unique().all()

t1 = t3 = n = lh_s = la_s = lc = g_s = hs_t = hs_h = 0
st = sh = bt = bh = dt = dh = 0
awg_a = awg_l = awg_n = 0

print('#   Match                        Score  Top1   Top3                          H@1  H@3   lamH   lamA')
print('=' * 95)

for m in matches:
    if not m.odds: continue
    p = predict_match(m, m.odds)
    hs = m.home_score; aws = m.away_score
    act = f'{hs}-{aws}'; tg = hs + aws
    t1_s = p.predicted_score
    t3_s = [s['score'] for s in (p.top_scores or [])[:3]]
    h1 = 'Y' if t1_s == act else 'N'
    h3 = 'Y' if act in t3_s else 'N'
    gm = p.model_breakdown.get('goal_model', {})
    lh = gm.get('lambda_home', 0); la = gm.get('lambda_away', 0)
    elo_gap = abs((m.home_team.elo_rating or 1500) - (m.away_team.elo_rating or 1500))
    dp = p.draw_probability

    if h1 == 'Y': t1 += 1
    if h3 == 'Y': t3 += 1
    n += 1
    if lh and la: lh_s += lh; la_s += la; lc += 1
    g_s += tg
    if tg >= 5: hs_t += 1
    if tg >= 5 and h3 == 'Y': hs_h += 1

    if elo_gap > 200:
        st += 1
        if h3 == 'Y': sh += 1
        awg_a += aws; awg_l += la; awg_n += 1
    if elo_gap < 100:
        bt += 1
        if h3 == 'Y': bh += 1
    if dp > 0.30:
        dt += 1
        if h3 == 'Y': dh += 1

    label = f'{m.home_team.name[:8]} vs {m.away_team.name[:8]}'
    print(f'{m.id:3d} {label:28s} {act:>5} {t1_s:>5} {str(t3_s):30s} {h1:>4} {h3:>4} {lh:5.2f} {la:5.2f}')

db.close()

print(f'\n{"="*80}')
print(f'SUMMARY')
print(f'{"="*80}')
print(f'Top1 Accuracy:        {t1}/{n} = {t1/n*100:.1f}%')
print(f'Top3 Accuracy:        {t3}/{n} = {t3/n*100:.1f}%')
avg_lh = round(lh_s/lc, 2) if lc else 0
avg_la = round(la_s/lc, 2) if lc else 0
avg_lam = avg_lh + avg_la
avg_g = round(g_s/n, 2) if n else 0
print(f'Lambda home avg:      {avg_lh}')
print(f'Lambda away avg:      {avg_la}')
print(f'Lambda total avg:     {avg_lam}')
print(f'Actual goals avg:     {avg_g}')
print(f'Lambda error:         {round(avg_lam-avg_g, 2):+.2f}')
print(f'High-score (>=5g):    Top3 hit {hs_h}/{hs_t}')

wap = round(awg_a/awg_n, 2) if awg_n else 0
wlp = round(awg_l/awg_n, 2) if awg_n else 0
print(f'Weak away goals (ELO>200): actual={wap}  lambda={wlp}  error={round(wlp-wap,2):+.2f}')

print(f'\nCATEGORY BREAKDOWN')
sp = f'{sh}/{st}={sh/st*100:.0f}%' if st else 'N/A'
bp = f'{bh}/{bt}={bh/bt*100:.0f}%' if bt else 'N/A'
dp_p = f'{dh}/{dt}={dh/dt*100:.0f}%' if dt else 'N/A'
print(f'Strong (ELO>200):     Top3={sp}')
print(f'Balanced (ELO<100):   Top3={bp}')
print(f'Draw-prone (dp>0.30): Top3={dp_p}')
