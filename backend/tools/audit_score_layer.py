#!/usr/bin/env python3
"""Score-layer audit: Top3 coverage, λ accuracy, diversity, over/under estimation."""
import sqlite3, json, math
from collections import defaultdict, Counter

DB = "worldcup_ai.db"

conn = sqlite3.connect(DB); cur = conn.cursor()
cur.execute("""
    SELECT m.id,m.home_score,m.away_score,m.kickoff_time,
           ht.name,at.name,ht.elo_rating,at.elo_rating,
           p.predicted_score,p.top_scores,p.draw_probability,
           p.home_win_probability,p.away_win_probability,
           p.model_breakdown,p.total_goals_band,
           o.home_win_odds,o.draw_odds,o.away_win_odds
    FROM matches m
    JOIN teams ht ON m.home_team_id=ht.id JOIN teams at ON m.away_team_id=at.id
    LEFT JOIN predictions p ON m.id=p.match_id LEFT JOIN odds_snapshots o ON m.id=o.match_id
    WHERE m.home_score IS NOT NULL AND m.away_score IS NOT NULL
    ORDER BY m.kickoff_time ASC
""")
rows = cur.fetchall(); conn.close()
total = len(rows)

# ── Per-match table ──
print(f"{'#':>3} {'Match':26s} {'Act':>5} {'Top1':>5} {'Top3Scores':28s} {'H@1':>4} {'H@3':>4} {'lamH':>6} {'lamA':>6} {'Gap':>4}")
print("=" * 105)

matches_data = []
for r in rows:
    (mid, hs, aws, ko, hn, an, elo_h, elo_a, pred_score, top_json, dp, hwp, awp,
     mb_json, tgb, h_odds, d_odds, a_odds) = r
    hs = int(hs) if hs is not None else -1; aws = int(aws) if aws is not None else -1
    actual_score = f"{hs}-{aws}"; actual_total = hs + aws
    elo_gap = abs((elo_h or 1500) - (elo_a or 1500))
    top_scores = json.loads(top_json or "[]")
    mb = json.loads(mb_json or "{}"); gm = mb.get("goal_model", {})
    lh = gm.get("lambda_home", 0); la = gm.get("lambda_away", 0)

    top3_strs = [s.get("score", "?") for s in top_scores[:3]]
    h1 = "Y" if pred_score == actual_score else "N"
    h3 = "Y" if actual_score in top3_strs else "N"

    print(f"{mid:3d} {hn[:8]:8s} vs {an[:8]:8s} {actual_score:>5} {pred_score or '?':>5} "
          f"{str(top3_strs):28s} {h1:>4} {h3:>4} {lh:6.2f} {la:6.2f} {elo_gap:4.0f}")

    matches_data.append({
        "id": mid, "hn": hn, "an": an, "actual_score": actual_score,
        "hs": hs, "aws": aws, "total_g": actual_total,
        "pred_score": pred_score, "top3": top3_strs,
        "h1": h1, "h3": h3, "lh": lh, "la": la,
        "elo_gap": elo_gap, "dp": dp or 0, "hwp": hwp or 0, "awp": awp or 0,
        "h_odds": h_odds, "d_odds": d_odds, "a_odds": a_odds,
    })

# ── Statistics ──
t1_hit = sum(1 for m in matches_data if m["h1"] == "Y")
t3_hit = sum(1 for m in matches_data if m["h3"] == "Y")
avg_lh = sum(m["lh"] for m in matches_data) / total
avg_la = sum(m["la"] for m in matches_data) / total
avg_lam_total = avg_lh + avg_la
avg_actual_total = sum(m["total_g"] for m in matches_data) / total
lam_error = avg_lam_total - avg_actual_total

print(f"\n{'='*60}")
print(f"  SCORE-LAYER STATISTICS (n={total})")
print(f"{'='*60}")
print(f"  Top1 Score Accuracy:  {t1_hit}/{total} = {t1_hit/total*100:.1f}%")
print(f"  Top3 Score Accuracy:  {t3_hit}/{total} = {t3_hit/total*100:.1f}%")
print(f"  Avg lambda (home):    {avg_lh:.2f}")
print(f"  Avg lambda (away):    {avg_la:.2f}")
print(f"  Avg lambda (total):   {avg_lam_total:.2f}")
print(f"  Avg actual goals:     {avg_actual_total:.2f}")
print(f"  Lambda error:         {lam_error:+.2f} ({'OVER-estimate' if lam_error > 0 else 'UNDER-estimate'})")

# ── High-scoring matches (5+ goals) ──
high_score = [m for m in matches_data if m["total_g"] >= 5]
print(f"\n  HIGH-SCORING MATCHES (>=5 goals): {len(high_score)}")
for m in high_score:
    print(f"  #{m['id']} {m['hn'][:8]} vs {m['an'][:8]}  {m['actual_score']}  "
          f"Top1={m['pred_score']}  Top3={m['top3']}  lam={m['lh']:.2f}+{m['la']:.2f}  H@3={m['h3']}")

high_missed = sum(1 for m in high_score if m["h3"] == "N")
print(f"  High-score Top3 miss rate: {high_missed}/{len(high_score)} = {high_missed/len(high_score)*100:.1f}%" if high_score else "  N/A")

# ── Classification breakdown ──
for label, condition in [
    ("Strong mismatch (ELO>200)", lambda m: m["elo_gap"] > 200),
    ("Balanced (ELO<100)", lambda m: m["elo_gap"] < 100),
    ("Draw-prone (dp>0.30)", lambda m: m["dp"] > 0.30),
]:
    subset = [m for m in matches_data if condition(m)]
    if not subset: continue
    n = len(subset)
    t1 = sum(1 for m in subset if m["h1"] == "Y")
    t3 = sum(1 for m in subset if m["h3"] == "Y")
    avg_l = sum(m["lh"]+m["la"] for m in subset) / n
    avg_g = sum(m["total_g"] for m in subset) / n
    print(f"\n  {label} (n={n}):")
    print(f"    Top1={t1/n*100:.1f}%  Top3={t3/n*100:.1f}%  "
          f"avg_lam={avg_l:.2f}  avg_goals={avg_g:.2f}  error={avg_l-avg_g:+.2f}")

# ── Homogeneity check ──
print(f"\n{'='*60}")
print(f"  TOP3 HOMOGENEITY CHECK")
print(f"{'='*60}")

# Count: how many Top3s are all same direction?
all_same_dir = 0
for m in matches_data:
    dirs = set()
    for s in m["top3"]:
        try: hg, ag = map(int, s.split("-"))
        except: continue
        if hg > ag: dirs.add("H")
        elif ag > hg: dirs.add("A")
        else: dirs.add("D")
    if len(dirs) == 1: all_same_dir += 1
print(f"  All Top3 same direction: {all_same_dir}/{total} = {all_same_dir/total*100:.1f}%")

# Missing common scores
common_scores = ["0-0", "1-0", "0-1", "1-1", "2-1", "1-2"]
for cs in common_scores:
    in_top3 = sum(1 for m in matches_data if cs in m["top3"])
    in_actual = sum(1 for m in matches_data if m["actual_score"] == cs)
    print(f"  '{cs}': in Top3={in_top3}/{total}  actual_occurrence={in_actual}")

# Underdog goal check
print(f"\n  WEAK-TEAM GOAL CHECK (away goals in strong mismatch ELO>200):")
strong_matches = [m for m in matches_data if m["elo_gap"] > 200]
awg_actual = sum(m["aws"] for m in strong_matches) / len(strong_matches) if strong_matches else 0
awg_lambda = sum(m["la"] for m in strong_matches) / len(strong_matches) if strong_matches else 0
print(f"  Avg away goals (actual): {awg_actual:.2f}")
print(f"  Avg away lambda:         {awg_lambda:.2f}")
print(f"  Under-estimation:        {awg_lambda - awg_actual:+.2f}")

# ── Score matrix coverage ──
print(f"\n{'='*60}")
print(f"  SCORE MATRIX COVERAGE (0-5 vs actual)")
print(f"{'='*60}")
beyond_5 = sum(1 for m in matches_data if m["hs"] > 5 or m["aws"] > 5)
beyond_5_any = sum(1 for m in matches_data if m["total_g"] > 5)
print(f"  Matches with any side >5 goals: {beyond_5}/{total}")
print(f"  Matches with total >5 goals:    {beyond_5_any}/{total}")
print(f"  Max actual goals by one side:   {max(m['hs'] for m in matches_data)} (Canada 6-0)")
print(f"  Max actual total goals:         {max(m['total_g'] for m in matches_data)} (Germany 7-1 = 8)")

# ── Final verdict ──
print(f"\n{'='*60}")
print(f"  FINAL VERDICT")
print(f"{'='*60}")

# 1. Lambda bias
if abs(lam_error) < 0.3:
    lam_verdict = "NEUTRAL — lambda estimates centered on actual goals"
elif lam_error > 0:
    lam_verdict = f"OVER-ESTIMATION (+{lam_error:.1f}) — model expects more goals than reality"
else:
    lam_verdict = f"UNDER-ESTIMATION ({lam_error:.1f}) — model expects fewer goals than reality"

# 2. Homogeneity
if all_same_dir / total > 0.5:
    homo_verdict = "HOMOGENEOUS — >50% of matches have Top3 all same direction"
else:
    homo_verdict = f"ACCEPTABLE — {all_same_dir}/{total} all-same-direction"

# 3. Matrix coverage
if beyond_5 > 0:
    matrix_verdict = f"INSUFFICIENT — {beyond_5} matches exceed 0-5 matrix bounds. Expand to 0-8."
else:
    matrix_verdict = "ADEQUATE — all matches within 0-5 bounds"

print(f"  Lambda bias:      {lam_verdict}")
print(f"  Top3 homogeneity: {homo_verdict}")
print(f"  Matrix coverage:  {matrix_verdict}")
print(f"  Top1 accuracy:    {t1_hit/total*100:.1f}% (target: >15%)")
print(f"  Top3 accuracy:    {t3_hit/total*100:.1f}% (target: >35%)")
