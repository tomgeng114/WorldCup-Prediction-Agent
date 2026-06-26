#!/usr/bin/env python3
"""Quick sweep for key factor range on both 2026 R24 and 2018+2022."""
import sqlite3, math

DB = "worldcup_ai.db"

def norm(h,d,a):
    t=h+d+a; return (h/t,d/t,a/t) if t>0 else (1/3,1/3,1/3)

def calibrate(hwp,dp,awp,factor,cap):
    if dp<=0: return hwp,dp,awp,False
    dc=min(dp*factor,cap); boost=dc-dp
    if boost<=0.001: return hwp,dp,awp,False
    ts=hwp+awp
    if ts<=0: return hwp,dp,awp,False
    hn=max(0.01,hwp-boost*hwp/ts); an=max(0.01,awp-boost*awp/ts)
    t=hn+dc+an; return round(hn/t,4),round(dc/t,4),round(an/t,4),True

def pick(h,d,a,u=0):
    wp=max(h,a); wg=wp-d
    if d>=0.30: return 'Draw'
    if d>=0.25:
        if wg<=0.12 and u>=60: return 'Draw'
        if wg>0.15: return 'Home Win' if h>=a else 'Away Win'
        return 'UNCERTAIN'
    return 'Home Win' if h>=d and h>=a else ('Away Win' if a>=h and a>=d else 'Draw')

def load_2026(n=None):
    c=sqlite3.connect(DB).cursor()
    c.execute("""SELECT m.home_score,m.away_score,p.draw_probability,p.home_win_probability,p.away_win_probability
        FROM matches m LEFT JOIN predictions p ON m.id=p.match_id
        WHERE m.home_score IS NOT NULL AND m.away_score IS NOT NULL ORDER BY m.kickoff_time ASC""")
    rows=c.fetchall(); c.connection.close()
    if n: rows=rows[-n:]
    return [{'h':r[3]or.5,'d':r[2]or.23,'a':r[4]or.27,'act':'Draw'if r[0]==r[1]else('Home Win'if r[0]>r[1]else'Away Win')}for r in rows]

def load_wc(year):
    c=sqlite3.connect(DB).cursor()
    c.execute(f"""SELECT wcm.home_score,wcm.away_score,bp.draw_probability,bp.home_win_probability,bp.away_win_probability
        FROM world_cup_matches wcm JOIN backtest_predictions bp ON wcm.id=bp.match_id
        JOIN backtest_runs br ON bp.run_id=br.id
        WHERE wcm.tournament_year={year} AND br.years LIKE '%{year}%'
        AND br.id=(SELECT MAX(id) FROM backtest_runs WHERE years LIKE '%{year}%')
        ORDER BY wcm.match_date ASC""")
    rows=c.fetchall(); c.connection.close()
    return [{'h':r[3]or.5,'d':r[2]or.25,'a':r[4]or.25,'act':'Draw'if r[0]==r[1]else('Home Win'if r[0]>r[1]else'Away Win')}for r in rows]

def eval_m(matches,factor,cap):
    s={'t':0,'h':0,'dh':0,'dp':0,'da':0,'b':0.0,'ll':0.0}
    for m in matches:
        hwp,dp,awp,cal=calibrate(m['h'],m['d'],m['a'],factor,cap)
        pred=pick(hwp,dp,awp); act=m['act']
        s['t']+=1
        if act=='Draw': s['da']+=1
        if pred=='Draw': s['dp']+=1
        if pred==act:
            s['h']+=1
            if act=='Draw': s['dh']+=1
        eps=1e-15
        if act=='Home Win': s['b']+=(hwp-1)**2+(dp-0)**2+(awp-0)**2; s['ll']+=-math.log(max(hwp,eps))
        elif act=='Away Win': s['b']+=(hwp-0)**2+(dp-0)**2+(awp-1)**2; s['ll']+=-math.log(max(awp,eps))
        else: s['b']+=(hwp-0)**2+(dp-1)**2+(awp-0)**2; s['ll']+=-math.log(max(dp,eps))
    s['b']/=s['t']; s['ll']/=s['t']
    return s

r24 = load_2026(24)
wc128 = load_wc(2018) + load_wc(2022)
r24_bl = eval_m(r24, 1.00, 0.42)
wc_bl = eval_m(wc128, 1.00, 0.42)

for label, matches, bl in [('2026 R24', r24, r24_bl), ('2018+2022 (128)', wc128, wc_bl)]:
    bl_acc = bl['h']/bl['t']*100
    print(f"\n=== {label} (baseline: Acc={bl_acc:.1f}%  DrawR={bl['dh']/bl['da']*100:.1f}%) ===")
    print(f"{'F':<6} {'Cap':<6} {'Acc%':<8} {'DR%':<8} {'DP%':<8} {'Brier':<8} {'LogL':<8} {'ΔAcc':<8}")
    print('-'*65)
    for f in [1.05, 1.10, 1.15, 1.20, 1.25, 1.30]:
        for cap in [0.35, 0.38, 0.40, 0.42, 0.45]:
            s = eval_m(matches, f, cap)
            acc = s['h']/s['t']*100
            dr = s['dh']/s['da']*100 if s['da'] else 0
            dp = s['dh']/s['dp']*100 if s['dp'] else 0
            d = acc - bl_acc
            print(f"{f:<6.2f} {cap:<6.2f} {acc:<8.1f} {dr:<8.1f} {dp:<8.1f} {s['b']:<8.4f} {s['ll']:<8.4f} {d:+.1f}")
