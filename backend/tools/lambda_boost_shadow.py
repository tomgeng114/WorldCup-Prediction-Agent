import sys,os,math; os.chdir('E:/Tom/WorldCupAI2026/backend'); sys.path.insert(0,'.')
from app.db import SessionLocal; from app.models import Match
from app.services.predictor import predict_match
from sqlalchemy.orm import joinedload; from sqlalchemy import select

# Monkey-patch _xg_adjusted_lambdas to use custom boost
import app.services.predictor as pred_module

original_fn = pred_module._xg_adjusted_lambdas

def make_patched_fn(boost_mult):
    _orig = original_fn
    def patched(home, away, prob_anchor):
        hl, al = _orig(home, away, prob_anchor)
        # Re-apply dominance with custom multiplier - simplified: just scale the final lambda
        # This is approximate but tests the concept
        return hl, al
    return patched

# Actually, the dominance boost is inside _xg_adjusted_lambdas. Let's patch it differently.
# We'll modify the module temporarily, run tests, and restore.

import app.services.predictor as pmod

# Save original
orig_xg = pmod._xg_adjusted_lambdas

def boosted_lambdas(home, away, prob_anchor, boost_mult=1.0):
    """Copy of _xg_adjusted_lambdas with multiplier on dominance boost"""
    mh_l,ma_l = pmod._expected_goals_from_probabilities(*prob_anchor)
    hs_l = 0.62*home.xg_for + 0.38*away.xga_against
    as_l = 0.62*away.xg_for + 0.38*home.xga_against
    hl = hs_l*0.68 + mh_l*0.32; al = as_l*0.68 + ma_l*0.32
    hl *= 1.04; al *= 0.98
    hp,_,ap = prob_anchor; mg = hp-ap
    eg = (home.elo_rating - away.elo_rating)/400
    xg_gap = (home.xg_for-home.xga_against) - (away.xg_for-away.xga_against)
    dom = mg*0.58 + eg*0.24 + xg_gap*0.18
    if dom >= 0.52:
        hl += boost_mult*(0.55 + min(0.35,(dom-0.52)*0.55))
        al = max(0.25, al - 0.12*boost_mult)
    elif dom >= 0.34:
        hl += boost_mult*(0.28 + min(0.20,(dom-0.34)*0.45))
        al = max(0.30, al - 0.06*boost_mult)
    elif dom <= -0.52:
        al += boost_mult*(0.55 + min(0.35,(-dom-0.52)*0.55))
        hl = max(0.25, hl - 0.12*boost_mult)
    elif dom <= -0.34:
        al += boost_mult*(0.28 + min(0.20,(-dom-0.34)*0.45))
        hl = max(0.30, hl - 0.06*boost_mult)
    return max(0.15,min(5.0,hl)), max(0.15,min(5.0,al))

for boost, label in [(1.0,'A (x1.0 baseline)'),(1.5,'B (x1.5)'),(2.0,'C (x2.0)'),(3.0,'D (x3.0)')]:
    # Patch
    def make_patch(bm):
        return lambda h,a,p: boosted_lambdas(h,a,p,bm)
    pmod._xg_adjusted_lambdas = make_patch(boost)

    db=SessionLocal()
    ms=db.scalars(select(Match).where(Match.home_score.isnot(None),Match.away_score.isnot(None)).options(joinedload(Match.home_team),joinedload(Match.away_team),joinedload(Match.odds)).order_by(Match.kickoff_time.asc())).unique().all()

    n=t1=t3=acc=wd=0
    goal_bins={k:{'n':0,'t3':0} for k in ['0','1','2','3','4','5+']}
    hs4_n=hs4_t3=hs5_n=hs5_t3=bl_n=bl_t3=odds_n=odds_t3=0
    improved=[]

    for m in ms:
        if not m.odds: continue
        orig_pm=predict_match(m,m.odds)  # baseline
        # With patched lambda, predict_match uses the patched _xg_adjusted_lambdas
        # But predict_match was already called above - need fresh call
        # Actually the patching IS active now, so orig_pm IS using the boost
        # For baseline (boost=1.0), this is identical to production

        hs=m.home_score; aws=m.away_score; tg=hs+aws; act=f'{hs}-{aws}'
        af='Home Win' if hs>aws else ('Draw' if hs==aws else 'Away Win')
        gm=orig_pm.model_breakdown.get('goal_model',{})
        lh=gm.get('lambda_home',0); la=gm.get('lambda_away',0)
        t3_l=[s['score'] for s in (orig_pm.top_scores or [])[:3]]
        t1s=orig_pm.predicted_score
        h1=t1s==act; h3=act in t3_l; pred=orig_pm.predicted_result
        n+=1
        if h1: t1+=1
        if h3: t3+=1
        if pred==af: acc+=1
        if pred!=af and af!='Draw' and pred!='Draw' and pred!='UNCERTAIN': wd+=1

        gk=str(tg) if tg<5 else '5+'
        goal_bins[gk]['n']+=1
        if h3: goal_bins[gk]['t3']+=1

        if tg>=4: hs4_n+=1
        if tg>=4 and h3: hs4_t3+=1
        if tg>=5: hs5_n+=1
        if tg>=5 and h3: hs5_t3+=1

        elo_gap=abs((m.home_team.elo_rating or 1500)-(m.away_team.elo_rating or 1500))
        if elo_gap>200: bl_n+=1
        if elo_gap>200 and h3: bl_t3+=1
        if m.odds.home_win_odds and m.odds.home_win_odds<1.50: odds_n+=1
        if m.odds.home_win_odds and m.odds.home_win_odds<1.50 and h3: odds_t3+=1

    db.close()

    t1p=t1/n*100; t3p=t3/n*100; accp=acc/n*100
    hs4p=hs4_t3/hs4_n*100 if hs4_n else 0; hs5p=hs5_t3/hs5_n*100 if hs5_n else 0
    blp=bl_t3/bl_n*100 if bl_n else 0; odp=odds_t3/odds_n*100 if odds_n else 0
    print(f'{label:20s} Acc={accp:5.1f}% T1={t1p:5.1f}% T3={t3p:5.1f}% WD={wd:2d} HS4={hs4p:5.1f}% HS5={hs5p:5.1f}% BL={blp:5.1f}% Odds={odp:5.1f}%')
    for gk in ['0','1','2','3','4','5+']:
        b=goal_bins[gk]
        if b['n']:
            pct = b['t3']/b['n']*100
            t3v = b['t3']; nv = b['n']
            print(f'  {gk}g: {pct:5.1f}%({t3v}/{nv})', end='')
    print()

# Restore
pmod._xg_adjusted_lambdas = orig_xg
