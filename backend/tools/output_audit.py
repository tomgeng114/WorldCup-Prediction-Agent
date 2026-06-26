import sys,os,math,sqlite3
os.chdir('E:/Tom/WorldCupAI2026/backend'); sys.path.insert(0,'.')
from app.db import SessionLocal; from app.models import Match
from app.services.predictor import predict_match
from sqlalchemy.orm import joinedload; from sqlalchemy import select

db=SessionLocal()
ms=db.scalars(select(Match).where(Match.home_score.isnot(None),Match.away_score.isnot(None)).options(joinedload(Match.home_team),joinedload(Match.away_team),joinedload(Match.odds)).order_by(Match.kickoff_time.asc())).unique().all()

matches=[]
for m in ms:
    if not m.odds: continue
    p=predict_match(m,m.odds)
    hs=m.home_score; aws=m.away_score
    af='Home Win' if hs>aws else ('Draw' if hs==aws else 'Away Win')
    top1_prob = p.top_scores[0]['probability']*100 if p.top_scores else 0
    matches.append({
        'hs':hs,'aws':aws,'af':af,'pred':p.predicted_result,'conf':p.confidence,
        'upset':p.upset_probability,'dp':p.draw_probability,
        'hwp':p.home_win_probability,'awp':p.away_win_probability,
        'ho':m.odds.home_win_odds or 9,'do':m.odds.draw_odds or 3,'ao':m.odds.away_win_odds or 9,
        'top1_score':p.predicted_score,'top_scores':p.top_scores,'top1_prob':top1_prob,
        'market_type':p.market_type,'handicap':p.handicap,
        'market_pred':p.predicted_market_result,
        'home_team':m.home_team.name,'away_team':m.away_team.name
    })
db.close()

n=len(matches)

# 1. Confidence
print('='*60)
print('  1. CONFIDENCE AUDIT')
print('='*60)
for lo,hi in [(90,999),(80,89),(70,79),(60,69),(0,59)]:
    sub=[m for m in matches if lo<=m['conf']<=hi]
    if not sub: continue
    hits=sum(1 for m in sub if m['pred']==m['af'])
    roi=sum((1.0 if m['pred']==m['af'] else -1.0) for m in sub)/len(sub)*100
    label='90+' if hi==999 else '%d-%d'%(lo,hi)
    print('  conf %6s: n=%3d  Acc=%.1f%%  ROI=%+.1f%%' % (label,len(sub),hits/len(sub)*100,roi))

# 2. Upset
print()
print('='*60)
print('  2. UPSET/COLD ALERT AUDIT')
print('='*60)
for lo,hi in [(0,39),(40,49),(50,59),(60,999)]:
    sub=[m for m in matches if lo<=m['upset']<=hi]
    if not sub: continue
    hits=sum(1 for m in sub if m['pred']==m['af'])
    upsets=sum(1 for m in sub if m['pred']!=m['af'] and m['af']!='Draw')
    roi=sum((1.0 if m['pred']==m['af'] else -1.0) for m in sub)/len(sub)*100
    label='60+' if hi==999 else '%d-%d'%(lo,hi)
    print('  upset %5s: n=%3d  Acc=%.1f%%  UpsetRate=%.1f%%  ROI=%+.1f%%' % (label,len(sub),hits/len(sub)*100,upsets/len(sub)*100 if sub else 0,roi))

# 3. Handicap simplified
print()
print('='*60)
print('  3. HANDICAP AUDIT (model market pick)')
print('='*60)
hc={'Home Win':{'h':0,'t':0},'Away Win':{'h':0,'t':0},'Draw':{'h':0,'t':0}}
for m in matches:
    hs=m['hs']; aws=m['aws']
    if hs>aws: actual_hc='Home Win'
    elif hs<aws: actual_hc='Away Win'
    else: actual_hc='Draw'
    pred=m['market_pred']
    if pred not in hc: continue
    hc[pred]['t']+=1
    if pred==actual_hc: hc[pred]['h']+=1
for k in ['Home Win','Draw','Away Win']:
    if hc[k]['t']:
        print('  %s: %d/%d=%.1f%%' % (k,hc[k]['h'],hc[k]['t'],hc[k]['h']/hc[k]['t']*100))

# 4. Score confidence
print()
print('='*60)
print('  4. SCORE CONFIDENCE')
print('='*60)
for lo,hi in [(15,999),(12,15),(10,12),(0,10)]:
    sub=[m for m in matches if lo<=m['top1_prob'] and (hi==999 or m['top1_prob']<hi)]
    if not sub: continue
    t3=0; t1=0
    for m_ in sub:
        act='%d-%d'%(m_['hs'],m_['aws'])
        if m_['top1_score']==act: t1+=1
        if act in [s['score'] for s in m_['top_scores'][:3]]: t3+=1
    label='>=%d%%'%lo if hi==999 else '%d-%d%%'%(lo,hi)
    print('  Top1Prob %8s: n=%3d  T1=%.1f%%  T3=%.1f%%' % (label,len(sub),t1/len(sub)*100 if sub else 0,t3/len(sub)*100 if sub else 0))

# 5. Combinations
print()
print('='*60)
print('  5. COMBINATION HUNT')
print('='*60)
combos=[
    ('Conf>70 & Upset<50', lambda m: m['conf']>70 and m['upset']<50),
    ('Conf>75 & Upset<45', lambda m: m['conf']>75 and m['upset']<45),
    ('Conf>80 & Upset<40', lambda m: m['conf']>80 and m['upset']<40),
    ('Conf>70 & OddsH<1.6', lambda m: m['conf']>70 and m['ho']<1.6),
    ('Conf>75 & OddsH<1.5', lambda m: m['conf']>75 and m['ho']<1.5),
    ('HWP>0.55 & dp<0.25', lambda m: m['hwp']>0.55 and m['dp']<0.25),
    ('HWP>0.60 & dp<0.22', lambda m: m['hwp']>0.60 and m['dp']<0.22),
    ('AWP>0.55 & dp<0.25', lambda m: m['awp']>0.55 and m['dp']<0.25),
    ('Upset<40', lambda m: m['upset']<40),
    ('Conf>85', lambda m: m['conf']>85),
]

best=None
for label, cond in combos:
    sub=[m for m in matches if cond(m)]
    if len(sub)<3: continue
    hits=sum(1 for m in sub if m['pred']==m['af'])
    roi=sum((1.0 if m['pred']==m['af'] else -1.0) for m in sub)/len(sub)*100
    acc=hits/len(sub)*100
    score=acc+roi
    if best is None or score>best[0]: best=(score,label,acc,roi,len(sub))
    print('  %-35s n=%3d  Acc=%.1f%%  ROI=%+.1f%%' % (label,len(sub),acc,roi))

if best:
    print()
    print('  >>> BEST: %s  Acc=%.1f%%  ROI=%+.1f%%  n=%d' % (best[1],best[2],best[3],best[4]))
    print()
    print('  RECOMMENDED BETTING RULES:')
    print('  1. Single bet: Conf>80 & Upset<40  (high confidence, low risk)')
    print('  2. Favorite bet: HWP>0.60 & dp<0.22 (clear favorite, no draw signal)')
    print('  3. Score bet: Top1Prob>=15% only (otherwise skip score betting)')
