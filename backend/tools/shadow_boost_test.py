#!/usr/bin/env python3
"""Shadow backtest: dominance boost multipliers. Does NOT modify production code."""
import sys, os, math, json
os.chdir('E:/Tom/WorldCupAI2026/backend'); sys.path.insert(0, '.')
from app.db import SessionLocal; from app.models import Match
from sqlalchemy.orm import joinedload; from sqlalchemy import select

# ── Shadow predictor: identical to production except dominance boost ──
MONTE_CARLO_RUNS = 100_000

def _safe_inverse(o): return 1/o if o and o>0 else 0
def _normalize_three(h,d,a):
    t=h+d+a; return (h/t,d/t,a/t) if t>0 else (1/3,1/3,1/3)
def _poisson_prob(l,g): return math.exp(-l)*(l**g)/math.factorial(g)
def _expected_goals_from_probabilities(hwp,dp,awp):
    edge=max(-1.4,min(1.4,math.log(max(hwp,0.001)/max(awp,0.001))))
    return max(0.15,1.35+edge*0.42), max(0.15,1.35-edge*0.42)

def _xg_adjusted_lambdas_shadow(home,away,prob_anchor,boost_mult=1.0):
    mh_l,ma_l=_expected_goals_from_probabilities(*prob_anchor)
    hs_l=0.62*home.xg_for+0.38*away.xga_against
    as_l=0.62*away.xg_for+0.38*home.xga_against
    hl=hs_l*0.68+mh_l*0.32; al=as_l*0.68+ma_l*0.32
    hl*=1.04; al*=0.98
    hp,_,ap=prob_anchor; mg=hp-ap
    eg=(home.elo_rating-away.elo_rating)/400
    xg_gap=(home.xg_for-home.xga_against)-(away.xg_for-away.xga_against)
    dom=mg*0.58+eg*0.24+xg_gap*0.18
    if dom>=0.52:
        hl+=boost_mult*(0.55+min(0.35,(dom-0.52)*0.55))
        al=max(0.25,al-0.12*boost_mult)
    elif dom>=0.34:
        hl+=boost_mult*(0.28+min(0.20,(dom-0.34)*0.45))
        al=max(0.30,al-0.06*boost_mult)
    elif dom<=-0.52:
        al+=boost_mult*(0.55+min(0.35,(-dom-0.52)*0.55))
        hl=max(0.25,hl-0.12*boost_mult)
    elif dom<=-0.34:
        al+=boost_mult*(0.28+min(0.20,(-dom-0.34)*0.45))
        hl=max(0.30,hl-0.06*boost_mult)
    return max(0.15,min(3.8,hl)), max(0.15,min(3.8,al))

def _score_matrix(lh,la,m=8):
    s=[]
    for h in range(m+1):
        for a in range(m+1):
            p=_poisson_prob(lh,h)*_poisson_prob(la,a); s.append({'s':f'{h}-{a}','h':h,'a':a,'p':p})
    t=sum(x['p'] for x in s)
    for x in s: x['p']/=t
    s.sort(key=lambda x:x['p'],reverse=True)
    return s

def pick_v2(h,d,a,upset=0):
    wp=max(h,a); wg=wp-d
    if d>=0.30: return 'Draw'
    if d>=0.25:
        if wg<=0.12 and upset>=60: return 'Draw'
        if wg>0.15: return 'Home Win' if h>=a else 'Away Win'
        return 'UNCERTAIN'
    return 'Home Win' if h>=d and h>=a else ('Away Win' if a>=h and a>=d else 'Draw')

def shadow_predict(match, odds, boost_mult):
    h=match.home_team; a=match.away_team
    # Simplified: use real odds as probability anchor
    hp,dp,ap=_normalize_three(_safe_inverse(odds.home_win_odds),_safe_inverse(odds.draw_odds),_safe_inverse(odds.away_win_odds))
    elo_p=_normalize_three(1/(1+10**((h.elo_rating-a.elo_rating)/400)), max(0.14,min(0.38,0.28-abs(h.elo_rating-a.elo_rating)/2000)), 1-1/(1+10**((h.elo_rating-a.elo_rating)/400)))
    form_p=_normalize_three(max(0.05,h.recent_form+(h.xg_for-h.xga_against)*0.12), max(0.14,min(0.38,0.30-abs(max(0.05,h.recent_form+(h.xg_for-h.xga_against)*0.12)-max(0.05,a.recent_form+(a.xg_for-a.xga_against)*0.12))*0.10)), max(0.05,a.recent_form+(a.xg_for-a.xga_against)*0.12))
    lh,la=_xg_adjusted_lambdas_shadow(h,a,(hp,dp,ap),boost_mult)
    scores=_score_matrix(lh,la)
    # Poisson probs
    h_sum=sum(s['p'] for s in scores if s['h']>s['a']); d_sum=sum(s['p'] for s in scores if s['h']==s['a']); a_sum=sum(s['p'] for s in scores if s['h']<s['a'])
    poisson_p=_normalize_three(h_sum,d_sum,a_sum)
    # Weighted fusion (simplified)
    parts={'elo':elo_p,'form':form_p,'odds':(hp,dp,ap),'poisson':poisson_p}
    w={'elo':0.30,'form':0.22,'odds':0.20,'poisson':0.28}
    fh=sum(parts[k][0]*w[k] for k in w); fd=sum(parts[k][1]*w[k] for k in w); fa=sum(parts[k][2]*w[k] for k in w)
    fh,fd,fa=_normalize_three(fh,fd,fa)
    pred=pick_v2(fh,fd,fa)
    top3=[s['s'] for s in scores[:3]]; top1=scores[0]['s']
    return {'pred':pred,'dp':fd,'top1':top1,'top3':top3,'lh':lh,'la':la,'fh':fh,'fa':fa}

# ── Run for each multiplier ──
for boost_mult, label in [(1.0,'A (current x1.0)'),(1.5,'B (x1.5)'),(2.0,'C (x2.0)'),(2.5,'D (x2.5)')]:
    db=SessionLocal()
    ms=db.scalars(select(Match).where(Match.home_score.isnot(None),Match.away_score.isnot(None)).options(joinedload(Match.home_team),joinedload(Match.away_team),joinedload(Match.odds)).order_by(Match.kickoff_time.asc())).unique().all()

    n=acc=draw_h=draw_p=draw_a=wd=t1_h=t3_h=0; hs_n=hs_h=0
    for m in ms:
        if not m.odds: continue
        hs=m.home_score; aws=m.away_score; tg=hs+aws
        af='Home Win' if hs>aws else ('Draw' if hs==aws else 'Away Win')
        act=f'{hs}-{aws}'
        r=shadow_predict(m,m.odds,boost_mult)
        n+=1
        if r['pred']==af: acc+=1
        if r['pred']=='Draw': draw_p+=1
        if af=='Draw': draw_a+=1
        if r['pred']=='Draw' and af=='Draw': draw_h+=1
        if r['pred']!=af and af!='Draw' and r['pred']!='Draw' and r['pred']!='UNCERTAIN': wd+=1
        if r['top1']==act: t1_h+=1
        if act in r['top3']: t3_h+=1
        if tg>=4: hs_n+=1
        if tg>=4 and act in r['top3']: hs_h+=1

    db.close()
    acc_p=acc/n*100; dr=draw_h/draw_a*100 if draw_a else 0; dpr=draw_h/draw_p*100 if draw_p else 0
    t1p=t1_h/n*100; t3p=t3_h/n*100
    hs_p=hs_h/hs_n*100 if hs_n else 0

    # Also count >=5 goal matches
    hs5_n=sum(1 for m in ms if m.odds and m.home_score+m.away_score>=5)
    hs5_h=0
    db2=SessionLocal()
    ms2=db2.scalars(select(Match).where(Match.home_score.isnot(None),Match.away_score.isnot(None)).options(joinedload(Match.home_team),joinedload(Match.away_team),joinedload(Match.odds)).order_by(Match.kickoff_time.asc())).unique().all()
    for m in ms2:
        if not m.odds: continue
        tg=m.home_score+m.away_score
        if tg>=5:
            r=shadow_predict(m,m.odds,boost_mult)
            if f'{m.home_score}-{m.away_score}' in r['top3']: hs5_h+=1
    db2.close()
    hs5_p=hs5_h/hs5_n*100 if hs5_n else 0

    print(f'{label:20s}  Acc={acc_p:5.1f}%  T3={t3p:5.1f}%  HS4_T3={hs_p:5.1f}%  HS5_T3={hs5_p:5.1f}%  WD={wd:2d}  DrawR={dr:5.1f}%  DrawP={dpr:5.1f}%  DrawPred={draw_p}')
