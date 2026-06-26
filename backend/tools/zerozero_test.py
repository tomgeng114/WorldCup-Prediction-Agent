import sys,os,math
os.chdir('E:/Tom/WorldCupAI2026/backend'); sys.path.insert(0,'.')
from app.db import SessionLocal; from app.models import Match
from app.services.predictor import predict_match
from sqlalchemy.orm import joinedload; from sqlalchemy import select

db=SessionLocal()
ms=db.scalars(select(Match).where(Match.home_score.isnot(None),Match.away_score.isnot(None)).options(joinedload(Match.home_team),joinedload(Match.away_team),joinedload(Match.odds)).order_by(Match.kickoff_time.asc())).unique().all()

def poisson(l,g): return math.exp(-l)*(l**g)/math.factorial(g) if g>=0 else 0

zeros=[]; non_zeros=[]
for m in ms:
    if not m.odds: continue
    p=predict_match(m,m.odds)
    gm=p.model_breakdown.get('goal_model',{})
    lh=gm.get('lambda_home',0); la=gm.get('lambda_away',0)
    scores=[]
    for h in range(9):
        for a in range(9):
            pr=poisson(lh,h)*poisson(la,a); scores.append({'s':f'{h}-{a}','p':pr})
    total=sum(x['p'] for x in scores)
    for x in scores: x['p']/=total
    scores.sort(key=lambda x:x['p'],reverse=True)
    top3=[x['s'] for x in scores[:3]]
    rec={'hs':m.home_score,'aws':m.away_score,'lh':lh,'la':la,'scores':scores,'top3':top3}
    if m.home_score==0 and m.away_score==0: zeros.append(rec)
    else: non_zeros.append(rec)
db.close()

print('ALL 0-0 MATCHES:')
for z in zeros:
    s=z['scores']
    p00=next(x for x in s if x['s']=='0-0')['p']
    p10=next(x for x in s if x['s']=='1-0')['p']
    p01=next(x for x in s if x['s']=='0-1')['p']
    p11=next(x for x in s if x['s']=='1-1')['p']
    in_top3 = '0-0' in z['top3']
    print('  lH=%.2f lA=%.2f lT=%.2f P00=%.4f P10=%.4f P01=%.4f P11=%.4f Top3=%s 00_in=%d' % (z['lh'],z['la'],z['lh']+z['la'],p00,p10,p01,p11,str(z['top3'][:3]),in_top3))

print()
print('SHADOW TEST: 0-0 boost when lambda_total < threshold')
all_matches=zeros+non_zeros
for thr, mult, label in [(99,1.0,'A baseline'),(2.2,1.5,'B lT<2.2 x1.5'),(2.0,2.0,'C lT<2.0 x2.0'),(1.8,3.0,'D lT<1.8 x3.0')]:
    n=t1=t3=acc=wd=z_n=z_t3=z00_h=0
    for r in all_matches:
        hs=r['hs']; aws=r['aws']; act='%d-%d'%(hs,aws); tg=hs+aws
        af='Home Win' if hs>aws else ('Draw' if hs==aws else 'Away Win')
        lh=r['lh']; la=r['la']; lt=lh+la
        scores=[dict(s) for s in r['scores']]
        if thr<99 and lt<thr:
            for x in scores:
                if x['s']=='0-0': x['p']*=mult; break
            total=sum(x['p'] for x in scores)
            for x in scores: x['p']/=total
        scores.sort(key=lambda x:x['p'],reverse=True)
        top3=[x['s'] for x in scores[:3]]; t1s=scores[0]['s']
        h1=t1s==act; h3=act in top3
        if lh>=la: pred='Home Win'
        else: pred='Away Win'
        n+=1
        if h1: t1+=1
        if h3: t3+=1
        if pred==af: acc+=1
        if pred!=af and af!='Draw' and pred!='Draw' and pred!='UNCERTAIN': wd+=1
        if hs==0 and aws==0:
            z_n+=1
            if h3: z_t3+=1
            if h1: z00_h+=1
    t1p=t1/n*100; t3p=t3/n*100; accp=acc/n*100
    z3p=z_t3/z_n*100 if z_n else 0
    print('%s Acc=%.1f%% T1=%.1f%% T3=%.1f%% 0-0_T3=%d/%d=%.0f%% 0-0_T1=%d/%d WD=%d' % (label,accp,t1p,t3p,z_t3,z_n,z3p,z00_h,z_n,wd))
