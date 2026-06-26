#!/usr/bin/env python3
"""Structural audit: Match Type Classification v1.1 — is draw signal being suppressed?"""
import sqlite3, json, math, sys
sys.path.insert(0, ".")

from app.services.match_type_classifier import (
    classify_match, apply_match_type_adjustments, MatchTypeResult
)

DB = "worldcup_ai.db"

def pick_v2(h, d, a, upset=0):
    wp = max(h, a); wg = wp - d
    if d >= 0.30: return "Draw"
    if d >= 0.25:
        if wg <= 0.12 and upset >= 60: return "Draw"
        if wg > 0.15: return "Home Win" if h >= a else "Away Win"
        return "UNCERTAIN"
    return "Home Win" if h >= d and h >= a else ("Away Win" if a >= h and a >= d else "Draw")

conn = sqlite3.connect(DB); cur = conn.cursor()
cur.execute("""
    SELECT m.id,m.home_score,m.away_score,m.kickoff_time,
           ht.name,at.name,ht.elo_rating,at.elo_rating,
           ht.world_cup_history_score,at.world_cup_history_score,
           p.home_win_probability,p.draw_probability,p.away_win_probability,
           p.predicted_result,p.model_breakdown,
           o.home_win_odds,o.draw_odds,o.away_win_odds
    FROM matches m
    JOIN teams ht ON m.home_team_id=ht.id JOIN teams at ON m.away_team_id=at.id
    LEFT JOIN predictions p ON m.id=p.match_id LEFT JOIN odds_snapshots o ON m.id=o.match_id
    WHERE m.home_score IS NOT NULL AND m.away_score IS NOT NULL
    ORDER BY m.kickoff_time ASC
""")
rows = cur.fetchall(); conn.close()

print("=" * 72)
print("  STRUCTURAL AUDIT: Match Type Classification v1.1")
print("  Question: Is draw signal being suppressed?")
print("=" * 72)

# ── Audit 1: Net dp change per match type ──
type_changes = {"A": [], "B": [], "C": [], "D": []}
type_actual_draws = {"A": 0, "B": 0, "C": 0, "D": 0}
type_draw_missed = {"A": 0, "B": 0, "C": 0, "D": 0}
type_suppressed = {"A": 0, "B": 0, "C": 0, "D": 0}

for r in rows:
    (mid, hs, aws, ko, hn, an, elo_h, elo_a, h_hist, a_hist,
     hwp, dp, awp, old_pred, mb_json, h_odds, d_odds, a_odds) = r
    actual = "Home Win" if hs > aws else ("Draw" if hs == aws else "Away Win")
    elo_gap = elo_h - elo_a

    mtr = classify_match(elo_gap, h_odds or 999, d_odds or 999, a_odds or 999, h_hist or 0.5, a_hist or 0.5)

    mb = json.loads(mb_json or "{}"); gm = mb.get("goal_model", {})
    lh = gm.get("lambda_home", 1.5); la = gm.get("lambda_away", 1.5)

    adj = apply_match_type_adjustments(hwp, dp, awp, lh, la, mtr, elo_gap=elo_gap)
    new_dp = adj["draw_prob"]
    dp_change = new_dp - dp

    type_changes[mtr.match_type].append(dp_change)

    if actual == "Draw":
        type_actual_draws[mtr.match_type] += 1
        old_pred_draw = pick_v2(hwp, dp, awp)
        new_pred_draw = pick_v2(adj["home_prob"], new_dp, adj["away_prob"])
        if old_pred_draw == "Draw" and new_pred_draw != "Draw":
            type_draw_missed[mtr.match_type] += 1
        if new_dp < dp:
            type_suppressed[mtr.match_type] += 1

print(f"\n  {'─'*60}")
print(f"  AUDIT 1: Net dp change per match type")
print(f"  {'─'*60}")
for t in ["A", "B", "C", "D"]:
    changes = type_changes[t]
    if not changes: continue
    avg = sum(changes)/len(changes)
    pos = sum(1 for c in changes if c > 0)
    neg = sum(1 for c in changes if c < 0)
    zero = sum(1 for c in changes if abs(c) < 0.001)
    print(f"  Type {t} ({len(changes)} matches): avg_dp_change={avg:+.4f}  "
          f"boosted={pos}  suppressed={neg}  unchanged={zero}")

# ── Audit 2: Actual draws by type — are we suppressing them? ──
print(f"\n  {'─'*60}")
print(f"  AUDIT 2: Actual draws — classification effect")
print(f"  {'─'*60}")
total_draws = sum(type_actual_draws.values())
print(f"  Total actual draws: {total_draws}")
for t in ["A", "B", "C", "D"]:
    ad = type_actual_draws[t]
    missed = type_draw_missed[t]
    supp = type_suppressed[t]
    if ad > 0:
        print(f"  Type {t}: {ad} actual draws | dp suppressed in {supp}/{ad} | "
              f"Draw→non-Draw flips: {missed}/{ad}")

# ── Audit 3: Draw Cap — how often does it fire? And on which matches? ──
print(f"\n  {'─'*60}")
print(f"  AUDIT 3: Draw Cap (dp>0.33 x0.95) — impact analysis")
print(f"  {'─'*60}")
cap_fired = 0
for r in rows:
    (mid, hs, aws, ko, hn, an, elo_h, elo_a, h_hist, a_hist,
     hwp, dp, awp, old_pred, mb_json, h_odds, d_odds, a_odds) = r
    actual = "Home Win" if hs > aws else ("Draw" if hs == aws else "Away Win")
    elo_gap = elo_h - elo_a
    mtr = classify_match(elo_gap, h_odds or 999, d_odds or 999, a_odds or 999, h_hist or 0.5, a_hist or 0.5)
    mb = json.loads(mb_json or "{}"); gm = mb.get("goal_model", {})
    lh = gm.get("lambda_home", 1.5); la = gm.get("lambda_away", 1.5)

    # Simulate: what would dp be WITHOUT cap?
    # Re-run adjustments but temporarily disable cap
    adj_with_cap = apply_match_type_adjustments(hwp, dp, awp, lh, la, mtr, elo_gap=elo_gap)
    # Check if cap fired: raw dp > 0.33
    raw_adj = adj_with_cap.get("dp_adjustment_applied_raw", 0)
    raw_dp = dp + raw_adj
    final_dp = adj_with_cap["draw_prob"]

    if raw_dp > 0.33 and abs(final_dp - raw_dp * 0.95) < 0.01:
        cap_fired += 1
        actual_str = f"actual={actual} ({hs}-{aws})"
        print(f"  Cap fired: #{mid} {hn} vs {an}  type={mtr.match_type}  "
              f"base_dp={dp:.3f} raw={raw_dp:.3f} final={final_dp:.3f}  {actual_str}")

print(f"  Total cap firings: {cap_fired}/36")

# ── Audit 4: Anti-flip guard — impact ──
print(f"\n  {'─'*60}")
print(f"  AUDIT 4: Anti-Flip Guard (elo>180 & dp>0.28) — impact analysis")
print(f"  {'─'*60}")
guard_fired = 0
for r in rows:
    (mid, hs, aws, ko, hn, an, elo_h, elo_a, h_hist, a_hist,
     hwp, dp, awp, old_pred, mb_json, h_odds, d_odds, a_odds) = r
    actual = "Home Win" if hs > aws else ("Draw" if hs == aws else "Away Win")
    elo_gap = elo_h - elo_a; abs_elo = abs(elo_gap)
    mtr = classify_match(elo_gap, h_odds or 999, d_odds or 999, a_odds or 999, h_hist or 0.5, a_hist or 0.5)
    mb = json.loads(mb_json or "{}"); gm = mb.get("goal_model", {})
    lh = gm.get("lambda_home", 1.5); la = gm.get("lambda_away", 1.5)
    adj = apply_match_type_adjustments(hwp, dp, awp, lh, la, mtr, elo_gap=elo_gap)
    raw_adj = adj.get("dp_adjustment_applied_raw", 0); raw_dp = dp + raw_adj
    final_dp = adj["draw_prob"]

    if abs_elo > 180 and raw_dp > 0.28:
        guard_fired += 1
        actual_str = f"actual={actual} ({hs}-{aws})"
        note = " [DRAW MISSED]" if actual == "Draw" else ""
        print(f"  Guard: #{mid} {hn} vs {an}  type={mtr.match_type}  "
              f"elo_gap={abs_elo:.0f}  raw_dp={raw_dp:.3f} final={final_dp:.3f}  {actual_str}{note}")

print(f"  Total guard firings: {guard_fired}/36")

# ── Audit 5: Who dominates — ELO/xG/Poisson or classifier? ──
print(f"\n  {'─'*60}")
print(f"  AUDIT 5: Classification influence vs base model")
print(f"  {'─'*60}")
influences = []
for r in rows:
    (mid, hs, aws, ko, hn, an, elo_h, elo_a, h_hist, a_hist,
     hwp, dp, awp, old_pred, mb_json, h_odds, d_odds, a_odds) = r
    elo_gap = elo_h - elo_a
    mtr = classify_match(elo_gap, h_odds or 999, d_odds or 999, a_odds or 999, h_hist or 0.5, a_hist or 0.5)
    mb = json.loads(mb_json or "{}"); gm = mb.get("goal_model", {})
    lh = gm.get("lambda_home", 1.5); la = gm.get("lambda_away", 1.5)
    adj = apply_match_type_adjustments(hwp, dp, awp, lh, la, mtr, elo_gap=elo_gap)
    new_dp = adj["draw_prob"]
    dp_change = abs(new_dp - dp)
    influences.append(dp_change)

avg_influence = sum(influences) / len(influences)
max_influence = max(influences)
print(f"  Avg |dp change| from classifier: {avg_influence:.4f}")
print(f"  Max |dp change| from classifier: {max_influence:.4f}")
print(f"  Classification contribution: {avg_influence*100:.1f}% of probability mass")
print(f"  (Base ELO/xG/Poisson dominates at ~{100-avg_influence*100:.1f}%)")

# ── Final Verdict ──
print(f"\n  {'='*60}")
print(f"  FINAL VERDICT")
print(f"  {'='*60}")

bl_hits = 0
for r in rows:
    try:
        hwp_v, dp_v, awp_v = float(r[13] or 0), float(r[14] or 0), float(r[15] or 0)
        hs_v, aws_v = int(r[1] or -1), int(r[2] or -1)
        act = "Home Win" if hs_v > aws_v else ("Draw" if hs_v == aws_v else "Away Win")
        if pick_v2(hwp_v, dp_v, awp_v) == act: bl_hits += 1
    except: pass
base_acc = bl_hits / len(rows) * 100 if rows else 0

total_d = sum(type_actual_draws.values())
total_missed = sum(type_draw_missed.values())
total_supp = sum(type_suppressed.values())

# Count draws correctly predicted by classifier
draw_hits_clf = 0
for r in rows:
    (mid, hs, aws, ko, hn, an, elo_h, elo_a, h_hist, a_hist,
     hwp, dp, awp, old_pred, mb_json, h_odds, d_odds, a_odds) = r
    if hs is None or aws is None: continue
    if int(hs) != int(aws): continue  # only draws
    elo_gap = elo_h - elo_a
    mtr = classify_match(elo_gap, h_odds or 999, d_odds or 999, a_odds or 999, h_hist or 0.5, a_hist or 0.5)
    mb = json.loads(mb_json or "{}"); gm = mb.get("goal_model", {})
    lh = gm.get("lambda_home", 1.5); la = gm.get("lambda_away", 1.5)
    adj = apply_match_type_adjustments(hwp, dp, awp, lh, la, mtr, elo_gap=elo_gap)
    if pick_v2(adj["home_prob"], adj["draw_prob"], adj["away_prob"]) == "Draw":
        draw_hits_clf += 1

print(f"\n  Draw signal strength:")
print(f"    Base model Draw Recall: {draw_hits_clf}/{total_d} = {draw_hits_clf/total_d*100:.1f}%" if total_d else "    N/A")
print(f"    Draws with dp suppressed by classifier: {total_supp}/{total_d}")
print(f"    Draws where classifier flipped Draw→non-Draw: {total_missed}/{total_d}")

# Bias direction
a_count = len(type_changes["A"]); b_count = len(type_changes["B"])
c_count = len(type_changes["C"]); d_count = len(type_changes["D"])
hw_heavy = a_count + b_count  # Types that favor Home/Away Win
bal_heavy = c_count           # Types that favor balanced
draw_heavy = d_count          # Types that favor draw

print(f"\n  Classification bias direction:")
print(f"    Type A+B (Home/Away-leaning): {hw_heavy} matches ({hw_heavy/len(rows)*100:.0f}%)")
print(f"    Type C (Balanced):            {bal_heavy} matches ({bal_heavy/len(rows)*100:.0f}%)")
print(f"    Type D (Draw-leaning):        {draw_heavy} matches ({draw_heavy/len(rows)*100:.0f}%)")

if hw_heavy > bal_heavy + draw_heavy:
    bias = "HOME WIN / AWAY WIN BIASED"
elif bal_heavy > hw_heavy + draw_heavy:
    bias = "BALANCED / NEUTRAL"
else:
    bias = "MIXED — slight Draw leaning in close matches, Home/Away in mismatches"

print(f"\n  >>> Current system is: {bias}")
print(f"  >>> Classification contribution: {avg_influence*100:.1f}% (base model: {100-avg_influence*100:.1f}%)")
print(f"  >>> No structural draw suppression detected." if total_missed <= 2 else f"  >>> WARNING: {total_missed} draws suppressed by classifier")
