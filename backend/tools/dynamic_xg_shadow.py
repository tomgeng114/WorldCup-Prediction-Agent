"""
Dynamic xG Generator — Shadow Design & Backtest
Does NOT modify production code.
"""
import sys,os,math
os.chdir('E:/Tom/WorldCupAI2026/backend'); sys.path.insert(0,'.')
from app.db import SessionLocal; from app.models import Match
from app.services.predictor import predict_match
from sqlalchemy.orm import joinedload; from sqlalchemy import select

db=SessionLocal()
ms=db.scalars(select(Match).where(Match.home_score.isnot(None),Match.away_score.isnot(None)).options(joinedload(Match.home_team),joinedload(Match.away_team),joinedload(Match.odds)).order_by(Match.kickoff_time.asc())).unique().all()

# ─── Compute league average xGA ───
all_teams=set()
for m in ms:
    if m.home_team: all_teams.add(m.home_team)
    if m.away_team: all_teams.add(m.away_team)
avg_xga=sum(t.xga_against for t in all_teams if t.xga_against)/len(all_teams)

print('='*65)
print('  DYNAMIC xG GENERATOR — DESIGN PROPOSAL')
print('='*65)
print('  League avg xGA: %.2f' % avg_xga)
print()
print('  Formula:')
print('    adj_xg = base_xg * (opp_xga / %.2f) * elo_factor' % avg_xga)
print('    elo_factor = 1 + (elo_gap/400) * 0.12')
print()

# ─── Example matches ───
examples=[25,43,51,18,36,42]  # Germany-Curacao, Germany-CIV, France-Iraq, Portugal-Congo, Canada-Qatar, Netherlands-Sweden
print('  EXAMPLE CALCULATIONS:')
for mid in examples:
    m=db.scalar(select(Match).where(Match.id==mid).options(joinedload(Match.home_team),joinedload(Match.away_team)))
    if not m: continue
    h=m.home_team; a=m.away_team
    elo_gap=h.elo_rating-a.elo_rating
    opp_factor=a.xga_against/avg_xga
    elo_f=1+(elo_gap/400)*0.12
    old_xg=h.xg_for
    new_xg=old_xg*opp_factor*elo_f
    # Estimate old/new lambda
    p=predict_match(m,m.odds) if m.odds else None
    old_lt=0
    if p:
        gm=p.model_breakdown.get('goal_model',{})
        old_lt=gm.get('lambda_home',0)+gm.get('lambda_away',0)
    new_lt_est=old_lt*(new_xg/old_xg) if old_xg>0 and old_lt>0 else 0
    print('  #%d %s vs %s: old_xg=%.1f new_xg=%.1f opp_f=%.2f elo_f=%.2f old_lt=%.1f new_lt~%.1f' % (mid,h.name[:8],a.name[:8],old_xg,new_xg,opp_factor,elo_f,old_lt,new_lt_est))

# ─── Shadow Backtest ───
print()
print('='*65)
print('  SHADOW BACKTEST')
print('='*65)

def poisson(l,g): return math.exp(-l)*(l**g)/math.factorial(g) if g>=0 else 0

for scheme_name, use_dynamic in [('A: Static xG (baseline)',False),('B: Dynamic xG (opp+elo adj)',True)]:
    t1=0; t3=0; n=0; acc=0; wd=0
    goals={k:{'n':0,'t3':0} for k in ['0','1','2','3','4','5+']}
    hs_n=0; hs_t3=0

    for m in ms:
        if not m.odds: continue
        hs=m.home_score; aws=m.away_score; tg=hs+aws; act='%d-%d'%(hs,aws)
        af='Home Win' if hs>aws else ('Draw' if hs==aws else 'Away Win')
        p=predict_match(m,m.odds)
        gm=p.model_breakdown.get('goal_model',{})
        lh=gm.get('lambda_home',0); la=gm.get('lambda_away',0)

        if use_dynamic:
            h=m.home_team; a=m.away_team
            elo_gap=h.elo_rating-a.elo_rating
            opp_h=1+(a.xga_against/avg_xga-1)*0.5  # bounded
            opp_a=1+(h.xga_against/avg_xga-1)*0.5
            elo_f=1+(elo_gap/400)*0.12
            xg_mult=max(0.6,min(1.6,opp_h*elo_f))  # cap
            lh=lh*xg_mult  # home lambda boost
            # Away side
            elo_f_a=1+(-elo_gap/400)*0.12
            xg_mult_a=max(0.6,min(1.6,opp_a*elo_f_a))
            la=la*xg_mult_a

        scores=[]
        for hg in range(9):
            for ag in range(9):
                pr=poisson(lh,hg)*poisson(la,ag)
                scores.append({'s':'%d-%d'%(hg,ag),'p':pr})
        total=sum(x['p'] for x in scores)
        for x in scores: x['p']/=total
        scores.sort(key=lambda x:x['p'],reverse=True)
        top1s=scores[0]['s']; top3s=[x['s'] for x in scores[:3]]
        h1=top1s==act; h3=act in top3s
        n+=1
        if h1: t1+=1
        if h3: t3+=1
        if lh>=la: pred='Home Win'
        else: pred='Away Win'
        if pred==af: acc+=1
        if pred!=af and af!='Draw' and pred!='Draw' and pred!='UNCERTAIN': wd+=1
        gk=str(tg) if tg<5 else '5+'
        goals[gk]['n']+=1
        if h3: goals[gk]['t3']+=1
        if tg>=5: hs_n+=1
        if tg>=5 and h3: hs_t3+=1

    t1p=t1/n*100; t3p=t3/n*100; accp=acc/n*100
    hs_pct=hs_t3/hs_n*100 if hs_n else 0
    print('%s: Acc=%.1f%% T1=%.1f%% T3=%.1f%% HS5_T3=%.1f%%(%d/%d) WD=%d' % (scheme_name,accp,t1p,t3p,hs_pct,hs_t3,hs_n,wd))
    for gk in ['0','1','2','3','4','5+']:
        b=goals[gk]
        if b['n']: print('  %sg: %d/%d=%.0f%%' % (gk,b['t3'],b['n'],b['t3']/b['n']*100))

db.close()
