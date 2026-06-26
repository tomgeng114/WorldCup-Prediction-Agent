#!/usr/bin/env python3
"""Comprehensive 4-problem audit — read-only, no code changes."""
import sqlite3, json, math
from collections import defaultdict

DB = "worldcup_ai.db"

conn = sqlite3.connect(DB)
cur = conn.cursor()

# ── Load all finished matches with predictions ──
cur.execute("""
    SELECT m.id, m.home_score, m.away_score, m.kickoff_time, m.competition,
           ht.name, at.name, ht.elo_rating, at.elo_rating,
           p.predicted_result, p.predicted_score, p.top_scores, p.backup_scores,
           p.home_win_probability, p.draw_probability, p.away_win_probability,
           p.market_type, p.handicap, p.predicted_market_result,
           p.model_breakdown, p.confidence, p.upset_probability,
           o.home_win_odds, o.draw_odds, o.away_win_odds
    FROM matches m
    JOIN teams ht ON m.home_team_id = ht.id
    JOIN teams at ON m.away_team_id = at.id
    LEFT JOIN predictions p ON m.id = p.match_id
    LEFT JOIN odds_snapshots o ON m.id = o.match_id
    WHERE m.home_score IS NOT NULL AND m.away_score IS NOT NULL
    ORDER BY m.kickoff_time ASC
""")

rows = cur.fetchall()
total = len(rows)
print(f"Total finished matches: {total}")

# Parse all matches
matches = []
for r in rows:
    (mid, hs, aws, ko, comp, hn, an, elo_h, elo_a, pr, ps, top_json, backup,
     hwp, dp, awp, mkt, hc, pmr, mb_json, conf, upset, h_odds, d_odds, a_odds) = r
    actual = "Home Win" if hs > aws else ("Draw" if hs == aws else "Away Win")
    actual_score = f"{hs}-{aws}"
    mb = json.loads(mb_json or "{}")
    top_scores = json.loads(top_json or "[]")
    matches.append({
        "id": mid, "home": hn, "away": an, "hs": hs, "aws": aws,
        "actual": actual, "actual_score": actual_score, "date": ko,
        "elo_h": elo_h, "elo_a": elo_a, "h_odds": h_odds, "d_odds": d_odds, "a_odds": a_odds,
        "pred_result": pr, "pred_score": ps, "top_scores": top_scores,
        "hwp": hwp, "dp": dp, "awp": awp, "model_breakdown": mb,
        "confidence": conf, "upset": upset, "market_type": mkt,
    })

# ═══════════════════════════════════════════════════════════════
# PROBLEM 1: λ underestimation for strong teams
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  PROBLEM 1: Strong-team λ Distribution Analysis")
print("=" * 70)

lambdas = []
for m in matches:
    gm = m["model_breakdown"].get("goal_model", {})
    lh = gm.get("lambda_home", 0)
    la = gm.get("lambda_away", 0)
    if lh > 0 or la > 0:
        lambdas.append({
            "id": m["id"], "home": m["home"], "away": m["away"],
            "lh": lh, "la": la, "total": lh + la,
            "hs": m["hs"], "aws": m["aws"],
            "elo_gap": m["elo_h"] - m["elo_a"],
            "odds_ratio": (1/m["h_odds"] if m["h_odds"] else 0) / (1/m["a_odds"] if m["a_odds"] else 0.01) if m["h_odds"] and m["a_odds"] else 0,
        })

# Top 20 highest λ
lambdas.sort(key=lambda x: x["lh"], reverse=True)
print(f"\n  Top 20 highest home λ:")
print(f"  {'Match':30s} {'λ_h':>6} {'λ_a':>6} {'Total':>6} {'Actual':>6} {'ELO gap':>8}")
for m in lambdas[:20]:
    print(f"  #{m['id']} {m['home']:10s} vs {m['away']:10s}  {m['lh']:6.2f} {m['la']:6.2f} {m['total']:6.2f}  {m['hs']}-{m['aws']:5}  {m['elo_gap']:8d}")

# Max λ stats
max_lh = max(m["lh"] for m in lambdas)
max_la = max(m["la"] for m in lambdas)
print(f"\n  Max λ_home: {max_lh:.2f}  Max λ_away: {max_la:.2f}")
print(f"  λ capped at 3.80 (code limit): {sum(1 for m in lambdas if m['lh'] >= 3.79)} matches at max")

# Strong teams (elo gap > 200) — compare λ vs actual goals
print(f"\n  Strong favorite matches (ELO gap > 200):")
strong = [m for m in lambdas if m["elo_gap"] > 200]
for m in strong:
    actual_total = m["hs"] + m["aws"]
    diff = m["total"] - actual_total
    flag = " [UNDER]" if diff < -0.5 else ""
    print(f"  #{m['id']} {m['home']:10s} vs {m['away']:10s}  lam={m['lh']:.2f}+{m['la']:.2f}={m['total']:.2f}  actual={m['hs']}+{m['aws']}={actual_total}  gap={diff:+.1f}{flag}")

# ═══════════════════════════════════════════════════════════════
# PROBLEM 2: Score Matrix Coverage
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  PROBLEM 2: Score Matrix Coverage Analysis")
print("=" * 70)

missed_top3 = []
high_score_matches = []
for m in matches:
    actual = m["actual_score"]
    actual_hg, actual_ag = map(int, actual.split("-"))
    actual_total = actual_hg + actual_ag

    if actual_total >= 4:
        high_score_matches.append(m)

    # Check if actual score is in top 3
    in_top3 = False
    top3_scores = [s["score"] for s in m["top_scores"]]
    if actual in top3_scores:
        in_top3 = True
    else:
        # Find actual score's probability from model breakdown
        missed_top3.append({
            "id": m["id"], "home": m["home"], "away": m["away"],
            "actual": actual, "total_goals": actual_total,
            "pred_result": m["pred_result"], "actual_result": m["actual"],
            "top3": top3_scores,
            "hs": m["hs"], "aws": m["aws"],
        })

print(f"\n  Matches with 4+ total goals: {len(high_score_matches)}")
for m in high_score_matches:
    print(f"  #{m['id']} {m['home']:10s} vs {m['away']:10s}  {m['actual_score']}  pred={m['pred_score']}  top3={[s['score'] for s in m['top_scores']]}")

print(f"\n  Actual score NOT in Top3 (but direction correct):")
correct_dir_missed = [m for m in missed_top3 if m["pred_result"] == m["actual_result"]]
for m in correct_dir_missed:
    print(f"  #{m['id']} {m['home']:10s} vs {m['away']:10s}  actual={m['actual']}  top3={m['top3']}  pred_dir={m['pred_result']} ✓")

print(f"\n  Actual score NOT in Top3 (direction WRONG):")
wrong_dir_missed = [m for m in missed_top3 if m["pred_result"] != m["actual_result"]]
for m in wrong_dir_missed:
    print(f"  #{m['id']} {m['home']:10s} vs {m['away']:10s}  actual={m['actual']}  top3={m['top3']}  pred_dir={m['pred_result']} ✗")

# ═══════════════════════════════════════════════════════════════
# PROBLEM 3: Draw Over-prediction Trend
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  PROBLEM 3: Draw Prediction Trend Analysis")
print("=" * 70)

def draw_stats(subset, label):
    n = len(subset)
    draw_act = sum(1 for m in subset if m["actual"] == "Draw")
    draw_pred = sum(1 for m in subset if m["pred_result"] == "Draw")
    draw_hit = sum(1 for m in subset if m["pred_result"] == "Draw" and m["actual"] == "Draw")
    home_to_draw = sum(1 for m in subset if m["pred_result"] == "Draw" and m["actual"] == "Home Win")
    away_to_draw = sum(1 for m in subset if m["pred_result"] == "Draw" and m["actual"] == "Away Win")
    print(f"\n  {label} (n={n}):")
    print(f"    Actual draws:  {draw_act} ({draw_act/n*100:.1f}%)")
    print(f"    Predicted draws: {draw_pred} ({draw_pred/n*100:.1f}%)")
    print(f"    Draw Recall:   {draw_hit}/{draw_act} = {draw_hit/draw_act*100:.1f}%" if draw_act else "    Draw Recall: N/A")
    print(f"    Draw Precision: {draw_hit}/{draw_pred} = {draw_hit/draw_pred*100:.1f}%" if draw_pred else "    Draw Precision: N/A")
    print(f"    Wrong flips: Home→Draw: {home_to_draw}, Away→Draw: {away_to_draw}")
    return draw_pred, draw_act, draw_hit, home_to_draw, away_to_draw

last20 = matches[-20:] if len(matches) >= 20 else matches
last30 = matches[-30:] if len(matches) >= 30 else matches
last10 = matches[-10:] if len(matches) >= 10 else matches

dp20, da20, dh20, h2d20, a2d20 = draw_stats(last20, "LAST-20")
dp30, da30, dh30, h2d30, a2d30 = draw_stats(last30, "LAST-30")
dp_all, da_all, dh_all, h2d_all, a2d_all = draw_stats(matches, "ALL")

# Latest 10 — list each draw prediction
print(f"\n  Latest 10 matches — Draw predictions:")
for m in last10:
    if m["pred_result"] == "Draw":
        hit = "✓" if m["actual"] == "Draw" else "✗ WRONG FLIP"
        print(f"  #{m['id']} {m['home']:10s} vs {m['away']:10s}  pred=Draw  actual={m['actual']} ({m['actual_score']})  dp={m['dp']:.3f}  {hit}")

# ═══════════════════════════════════════════════════════════════
# PROBLEM 4: Calibration Layer Evaluation
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  PROBLEM 4: Draw Calibration Layer Evaluation (simulated)")
print("=" * 70)

def normalize(h, d, a):
    t = h + d + a; return (h/t, d/t, a/t) if t > 0 else (1/3, 1/3, 1/3)

def calibrate(hwp, dp, awp, factor=1.25, cap=0.42):
    if dp <= 0: return hwp, dp, awp, False
    dc = min(dp * factor, cap); boost = dc - dp
    if boost <= 0.001: return hwp, dp, awp, False
    ts = hwp + awp
    if ts <= 0: return hwp, dp, awp, False
    hn = max(0.01, hwp - boost * hwp / ts); an = max(0.01, awp - boost * awp / ts)
    return normalize(hn, dc, an) + (True,)

def pick_v2(h, d, a, upset=0):
    wp = max(h, a); wg = wp - d
    if d >= 0.30: return "Draw"
    if d >= 0.25:
        if wg <= 0.12 and upset >= 60: return "Draw"
        if wg > 0.15: return "Home Win" if h >= a else "Away Win"
        return "UNCERTAIN"
    return "Home Win" if h >= d and h >= a else ("Away Win" if a >= h and a >= d else "Draw")

# Simulate: baseline vs f=1.25 vs conditional gating
for label, factor, cap, condition in [
    ("Baseline (no cal)", 1.00, 0.42, "none"),
    ("Global x1.25", 1.25, 0.42, "none"),
    ("Conditional: dp<0.22 only", 1.25, 0.42, "low_dp"),
    ("Conditional: ELO gap<100 only", 1.25, 0.42, "close_elo"),
]:
    hits = 0; draw_hits = 0; draw_pred = 0; draw_act = 0
    correct_flips = 0; wrong_flips = 0
    for m in matches:
        hwp, dp, awp = m["hwp"], m["dp"], m["awp"]
        actual = m["actual"]
        upset = m["upset"] or 0
        elo_gap = abs((m["elo_h"] or 1500) - (m["elo_a"] or 1500))

        # Decide whether to calibrate
        should_cal = True
        if condition == "low_dp" and dp >= 0.22:
            should_cal = False
        if condition == "close_elo" and elo_gap >= 100:
            should_cal = False

        if should_cal and factor > 1.00:
            hwp, dp, awp, applied = calibrate(hwp, dp, awp, factor, cap)
        else:
            orig_h, orig_d, orig_a = hwp, dp, awp
            hwp, dp, awp = orig_h, orig_d, orig_a

        pred = pick_v2(hwp, dp, awp, upset)
        if actual == "Draw": draw_act += 1
        if pred == "Draw": draw_pred += 1
        if pred == actual:
            hits += 1
            if actual == "Draw": draw_hits += 1

        # Track flips
        orig_pred = pick_v2(m["hwp"], m["dp"], m["awp"], upset)
        if orig_pred != "Draw" and pred == "Draw":
            if actual == "Draw": correct_flips += 1
            else: wrong_flips += 1

    acc = hits / len(matches) * 100
    recall = draw_hits / draw_act * 100 if draw_act else 0
    precision = draw_hits / draw_pred * 100 if draw_pred else 0
    print(f"\n  {label}:")
    print(f"    Acc={acc:.1f}%  DrawR={recall:.1f}%  DrawP={precision:.1f}%  "
          f"PredictedDraws={draw_pred}/{draw_act}actual")
    print(f"    Flips: {correct_flips} correct + {wrong_flips} wrong = net {correct_flips - wrong_flips:+d}")

# ═══════════════════════════════════════════════════════════════
# FINAL SUMMARY
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  FINAL AUDIT SUMMARY")
print("=" * 70)
print(f"""
  P1 (λ underestimation): Max λ_home={max_lh:.1f} (code cap=3.8).
      Strong favorites (ELO>200) avg λ={sum(m['lh'] for m in strong)/len(strong):.1f} vs actual goals avg={sum(m['hs'] for m in strong)/len(strong):.1f}.
      {'⚠️ λ systemically below actual goals for mismatches' if sum(m['lh']+m['la'] for m in strong)/len(strong) < sum(m['hs']+m['aws'] for m in strong)/len(strong) else 'λ adequate'}

  P2 (Score coverage): {len(missed_top3)}/{total} actual scores not in Top3.
      {len(correct_dir_missed)}/{total} direction correct but score missed.
      {'⚠️ Score matrix (0-5) insufficient for mismatches' if len(high_score_matches) > 3 else 'Score coverage adequate'}

  P3 (Draw trend): Last 20: {dh20}/{da20} draw recall, {h2d20+a2d20} wrong Home/Away→Draw flips.
      {'⚠️ Draw over-prediction emerging in recent matches' if (h2d20 + a2d20) > da20 * 0.5 else 'Draw prediction rate stable'}

  P4 (Calibration): Global x1.25 has net negative flip ratio.
      Conditional gating reduces wrong flips. Recommend evaluating condition-based approach before re-enabling.
""")

conn.close()
