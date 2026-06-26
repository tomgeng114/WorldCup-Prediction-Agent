import sqlite3, math

def norm(h,d,a):
    t=h+d+a; return (h/t,d/t,a/t) if t>0 else (1/3,1/3,1/3)

def pick_v2(h,d,a):
    wp=max(h,a); wg=wp-d
    if d>=0.30: return 'Draw'
    if d>=0.25:
        if wg<=0.12: return 'Draw'
        if wg>0.15: return 'Home Win' if h>=a else 'Away Win'
        return 'UNCERTAIN'
    return 'Home Win' if h>=d and h>=a else ('Away Win' if a>=h and a>=d else 'Draw')

def second_best(h,d,a):
    return 'Home Win' if h>=a else 'Away Win'

def test(label, rows, apply_filter):
    h=0; dh=0; dp_n=0; da=0; n=0; wr=0; flt=[]
    for r in rows:
        hs=int(r[1] or 0); aws=int(r[2] or 0)
        ho=float(r[3] or 9); do=float(r[4] or 3); ao=float(r[5] or 9)
        af='Home Win' if hs>aws else ('Draw' if hs==aws else 'Away Win')
        hwp,dp,awp=norm(1/ho,1/do,1/ao)
        pred=pick_v2(hwp,dp,awp)
        new_pred=apply_filter(pred,dp,ho,hwp,dp,awp)
        if new_pred:
            flt.append(f'  {int(r[0])} {hs}-{aws} ho={ho:.2f} dp={dp:.3f} {pred}->{new_pred} actual={af}')
            pred=new_pred
        n+=1
        if pred=='Draw': dp_n+=1
        if af=='Draw': da+=1
        if pred==af: h+=1
        if pred=='Draw' and af=='Draw': dh+=1
        if pred!=af and af!='Draw' and pred!='Draw' and pred!='UNCERTAIN': wr+=1
    acc=h/n*100; dr=dh/da*100 if da else 0; dpr=dh/dp_n*100 if dp_n else 0
    print(f'{label:25s} Acc={acc:5.1f}% DrawP={dpr:5.1f}% DrawR={dr:5.1f}% WD={wr:2d} PredDraw={dp_n:2d}')
    if flt:
        print(f'  Filtered {len(flt)}:')
        for f in flt[:4]: print(f)
    return acc,dr,dpr,wr,dp_n

def no_f(pred,dp,ho,hwp,dp2,awp): return None
def filterA(pred,dp,ho,hwp,dp2,awp):
    if pred=='Draw' and ho>1.8: return 'UNCERTAIN'
    return None
def filterB(pred,dp,ho,hwp,dp2,awp):
    if pred=='Draw' and ho>1.8: return second_best(hwp,dp2,awp)
    return None

conn=sqlite3.connect('E:/Tom/WorldCupAI2026/backend/worldcup_ai.db'); cur=conn.cursor()
cur.execute('SELECT tournament_year,home_score,away_score,home_win_odds,draw_odds,away_win_odds FROM world_cup_matches wcm JOIN world_cup_odds wo ON wcm.id=wo.match_id WHERE tournament_year IN(2018,2022) AND home_score IS NOT NULL ORDER BY match_date')
wc=[list(r) for r in cur.fetchall()]
r18=[r for r in wc if r[0]==2018]; r22=[r for r in wc if r[0]==2022]
cur.execute('SELECT 2026,m.home_score,m.away_score,o.home_win_odds,o.draw_odds,o.away_win_odds FROM matches m LEFT JOIN odds_snapshots o ON m.id=o.match_id WHERE m.home_score IS NOT NULL ORDER BY m.kickoff_time')
c26_rows=cur.fetchall()
c26=[]
for r in c26_rows:
    if r[1] is None: continue
    c26.append([2026, r[1], r[2], r[3] or 2.5, r[4] or 3.0, r[5] or 2.5])
conn.close()
all_rows=wc+[list(x) for x in c26]

print('='*65)
print('  DRAW QUALITY FILTER SHADOW BACKTEST')
print('='*65)
for rows, name in [(r18,'2018 (64)'),(r22,'2022 (64)'),(c26,'2026'),(all_rows,'ALL')]:
    draws=sum(1 for r in rows if r[1]==r[2])
    print(f'\n  {name} ({len(rows)}m, {draws} draws)')
    test('Baseline (v3.1)', rows, no_f)
    test('Filter A (->UNCERTAIN)', rows, filterA)
    test('Filter B (->2nd best)', rows, filterB)
