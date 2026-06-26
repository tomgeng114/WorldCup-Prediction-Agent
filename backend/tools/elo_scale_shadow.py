import sys,os,math
os.chdir('E:/Tom/WorldCupAI2026/backend'); sys.path.insert(0,'.')
from app.db import SessionLocal; from app.models import Match
from app.services.predictor import predict_match
from sqlalchemy.orm import joinedload; from sqlalchemy import select

db=SessionLocal()
ms=db.scalars(select(Match).where(Match.home_score.isnot(None),Match.away_score.isnot(None)).options(joinedload(Match.home_team),joinedload(Match.away_team),joinedload(Match.odds)).order_by(Match.kickoff_time.asc())).unique().all()

def poisson(l,g): return math.exp(-l)*(l**g)/math.factorial(g) if g>=0 else 0

scenarios=[
    ('A: Baseline (x1.0)', [(0,1.0),(100,1.0),(200,1.0),(300,1.0),(9999,1.0)]),
    ('B: Mild (x1.1/1.2/1.3)', [(0,1.0),(100,1.10),(200,1.20),(300,1.30),(9999,1.30)]),
    ('C: Moderate (x1.15/1.3/1.5)', [(0,1.0),(100,1.15),(200,1.30),(300,1.50),(9999,1.50)]),
    ('D: Aggressive (x1.2/1.4/1.7)', [(0,1.0),(100,1.20),(200,1.40),(300,1.70),(9999,1.70)]),
]

blowout_ids=[25,36,11,42,15]  # Germany-Curacao, Canada-Qatar, Sweden-Tunisia, Netherlands-Sweden, France-Senegal

print('='*70)
print('  ELO SCALING — SHADOW BACKTEST')
print('='*70)

for label, tiers in scenarios:
    t1=0; t3=0; n=0; acc=0; wd=0
    goals={k:{'n':0,'t3':0} for k in ['0','1','2','3','4','5+']}
    hs4_n=0; hs4_t3=0; hs5_n=0; hs5_t3=0

    for m in ms:
        if not m.odds: continue
        hs=m.home_score; aws=m.away_score; tg=hs+aws
        act='%d-%d'%(hs,aws)
        af='Home Win' if hs>aws else ('Draw' if hs==aws else 'Away Win')
        p=predict_match(m,m.odds)  # Get baseline lambda
        gm=p.model_breakdown.get('goal_model',{})
        lh=gm.get('lambda_home',0); la=gm.get('lambda_away',0)
        elo_h=m.home_team.elo_rating or 1500; elo_a=m.away_team.elo_rating or 1500
        elo_gap=abs(elo_h-elo_a)

        # Apply ELO scale to BOTH sides based on gap
        scale=1.0
        for thresh, mult in tiers:
            if elo_gap >= thresh: scale=mult
        if elo_h > elo_a:
            lh=lh*scale  # boost stronger side
        else:
            la=la*scale

        scores=[]
        for hg in range(9):
            for ag in range(9):
                pr=poisson(lh,hg)*poisson(la,ag); scores.append({'s':'%d-%d'%(hg,ag),'p':pr})
        total=sum(x['p'] for x in scores)
        for x in scores: x['p']/=total
        scores.sort(key=lambda x:x['p'],reverse=True)
        t1s=scores[0]['s']; t3s=[x['s'] for x in scores[:3]]
        h1=t1s==act; h3=act in t3s
        n+=1
        if h1: t1+=1
        if h3: t3+=1
        # Winner (simplified: argmax of probs)
        if lh>=la: pred='Home Win'
        else: pred='Away Win'
        if pred==af: acc+=1
        if pred!=af and af!='Draw' and pred!='Draw': wd+=1

        gk=str(tg) if tg<5 else '5+'
        goals[gk]['n']+=1
        if h3: goals[gk]['t3']+=1
        if tg>=4: hs4_n+=1
        if tg>=4 and h3: hs4_t3+=1
        if tg>=5: hs5_n+=1
        if tg>=5 and h3: hs5_t3+=1

    t1p=t1/n*100; t3p=t3/n*100; accp=acc/n*100
    h4p=hs4_t3/hs4_n*100 if hs4_n else 0; h5p=hs5_t3/hs5_n*100 if hs5_n else 0
    print('%s: Acc=%.1f%% T1=%.1f%% T3=%.1f%% HS4=%.0f%%(%d/%d) HS5=%.0f%%(%d/%d) WD=%d' % (
        label,accp,t1p,t3p,h4p,hs4_t3,hs4_n,h5p,hs5_t3,hs5_n,wd))
    for gk in ['0','1','2','3','4','5+']:
        b=goals[gk]
        if b['n']:
            pct='%.0f%%'%(b['t3']/b['n']*100)
            print('  %sg: %d/%d=%s' % (gk,b['t3'],b['n'],pct))

# Blowout detail for best candidate
print()
print('BLOWOUT DETAIL (Scheme B: Mild):')
for mid in blowout_ids:
    m=db.scalar(select(Match).where(Match.id==mid).options(joinedload(Match.home_team),joinedload(Match.away_team),joinedload(Match.odds)))
    if not m or not m.odds: continue
    p=predict_match(m,m.odds)
    gm=p.model_breakdown.get('goal_model',{})
    lh=gm.get('lambda_home',0); la=gm.get('lambda_away',0)
    elo_h=m.home_team.elo_rating or 1500; elo_a=m.away_team.elo_rating or 1500
    elo_gap=abs(elo_h-elo_a)
    # Old Top3
    old_scores=[]
    for hg in range(9):
        for ag in range(9):
            old_scores.append({'s':'%d-%d'%(hg,ag),'p':poisson(lh,hg)*poisson(la,ag)})
    old_total=sum(x['p'] for x in old_scores)
    for x in old_scores: x['p']/=old_total
    old_scores.sort(key=lambda x:x['p'],reverse=True)
    old_t3=[x['s'] for x in old_scores[:3]]
    # New (B scheme)
    scale=1.0
    if elo_gap>=300: scale=1.30
    elif elo_gap>=200: scale=1.20
    elif elo_gap>=100: scale=1.10
    nlh=lh*scale if elo_h>elo_a else lh
    nla=la*scale if elo_a>elo_h else la
    new_scores=[]
    for hg in range(9):
        for ag in range(9):
            new_scores.append({'s':'%d-%d'%(hg,ag),'p':poisson(nlh,hg)*poisson(nla,ag)})
    new_total=sum(x['p'] for x in new_scores)
    for x in new_scores: x['p']/=new_total
    new_scores.sort(key=lambda x:x['p'],reverse=True)
    new_t3=[x['s'] for x in new_scores[:3]]
    act='%d-%d'%(m.home_score,m.away_score)
    old_hit=act in old_t3; new_hit=act in new_t3
    print('#%d %s vs %s %s elo_gap=%d scale=%.2f old_LT=%.1f new_LT=%.1f old_T3=%s new_T3=%s old_hit=%d new_hit=%d' % (
        mid,m.home_team.name[:8],m.away_team.name[:8],act,elo_gap,scale,lh+la,nlh+nla,
        str(old_t3),str(new_t3),old_hit,new_hit))

db.close()
