#!/usr/bin/env python3
"""Backtest Match Type Classification Layer on 36 finished matches."""
import sqlite3, json, math, sys
sys.path.insert(0, ".")

from app.services.match_type_classifier import (
    classify_match, apply_match_type_adjustments, enforce_diverse_top_scores, MatchTypeResult
)

DB = "worldcup_ai.db"

def normalize(h, d, a):
    t = h + d + a; return (h/t, d/t, a/t) if t > 0 else (1/3, 1/3, 1/3)

def pick_v2(h, d, a, upset=0):
    wp = max(h, a); wg = wp - d
    if d >= 0.30: return "Draw"
    if d >= 0.25:
        if wg <= 0.12 and upset >= 60: return "Draw"
        if wg > 0.15: return "Home Win" if h >= a else "Away Win"
        return "UNCERTAIN"
    return "Home Win" if h >= d and h >= a else ("Away Win" if a >= h and a >= d else "Draw")

def score_result(s):
    hg, ag = map(int, s.split("-"))
    return "Home Win" if hg > ag else ("Draw" if hg == ag else "Away Win")

conn = sqlite3.connect(DB); cur = conn.cursor()
cur.execute("""
    SELECT m.id,m.home_score,m.away_score,m.kickoff_time,
           ht.name,at.name,ht.elo_rating,at.elo_rating,
           ht.world_cup_history_score,at.world_cup_history_score,
           p.predicted_result,p.predicted_score,p.top_scores,p.backup_scores,
           p.home_win_probability,p.draw_probability,p.away_win_probability,
           p.model_breakdown,p.confidence,p.upset_probability,
           o.home_win_odds,o.draw_odds,o.away_win_odds
    FROM matches m
    JOIN teams ht ON m.home_team_id=ht.id JOIN teams at ON m.away_team_id=at.id
    LEFT JOIN predictions p ON m.id=p.match_id LEFT JOIN odds_snapshots o ON m.id=o.match_id
    WHERE m.home_score IS NOT NULL AND m.away_score IS NOT NULL
    ORDER BY m.kickoff_time ASC
""")
rows = cur.fetchall(); conn.close()

# ── Run backtest ──────────────────────────────────────
print("=" * 75)
print("  MATCH TYPE CLASSIFICATION LAYER — BACKTEST (36 matches)")
print("=" * 75)

results = {"A": [], "B": [], "C": [], "D": []}
hits = 0; draw_hits = 0; draw_pred = 0; draw_act = 0
home_to_draw = 0; away_to_draw = 0; total = len(rows)
score_hits = 0

for r in rows:
    (mid, hs, aws, ko, hn, an, elo_h, elo_a, h_hist, a_hist,
     old_pred, old_ps, old_top_json, old_backup, hwp, dp, awp, mb_json, conf, upset,
     h_odds, d_odds, a_odds) = r
    actual = "Home Win" if hs > aws else ("Draw" if hs == aws else "Away Win")
    actual_score = f"{hs}-{aws}"
    elo_gap = elo_h - elo_a

    # 1. Classify
    mtr = classify_match(elo_gap, h_odds or 999, d_odds or 999, a_odds or 999, h_hist or 0.5, a_hist or 0.5)

    # 2. Get model lambdas from stored breakdown
    mb = json.loads(mb_json or "{}")
    gm = mb.get("goal_model", {})
    lh = gm.get("lambda_home", 1.5)
    la = gm.get("lambda_away", 1.5)

    # 3. Apply adjustments
    adj = apply_match_type_adjustments(hwp, dp, awp, lh, la, mtr, elo_gap=elo_gap)
    new_h, new_d, new_a = adj["home_prob"], adj["draw_prob"], adj["away_prob"]
    new_lh, new_la = adj["lambda_home"], adj["lambda_away"]

    # 4. Simple score matrix (6x6) with adjusted lambdas
    scores = []
    for hg in range(6):
        for ag in range(6):
            prob = (new_lh**hg * math.exp(-new_lh) / math.factorial(hg)) * \
                   (new_la**ag * math.exp(-new_la) / math.factorial(ag))
            scores.append({"home_goals": hg, "away_goals": ag, "score": f"{hg}-{ag}", "probability": prob})
    total_prob = sum(s["probability"] for s in scores)
    for s in scores: s["probability"] /= total_prob

    # 5. Generate diverse top 3
    top3 = enforce_diverse_top_scores(scores, hn, an)

    # 6. Predict
    new_pred = pick_v2(new_h, new_d, new_a, upset or 0)
    old_pred_clean = pick_v2(hwp, dp, awp, upset or 0)

    # 7. Track stats + per-match log
    flip_flag = ""
    if old_pred_clean != "Draw" and new_pred == "Draw":
        flip_flag = " [FLIP: {}->Draw]".format(old_pred_clean)
        if actual == "Home Win": home_to_draw += 1
        elif actual == "Away Win": away_to_draw += 1

    if actual == "Draw": draw_act += 1
    if new_pred == "Draw": draw_pred += 1
    if new_pred == actual: hits += 1
    if new_pred == actual and actual == "Draw": draw_hits += 1

    raw_adj = adj.get("dp_adjustment_applied_raw", 0)
    print(f"  #{mid:3d} {hn:8s} vs {an:8s}  type={mtr.match_type}  "
          f"base_dp={dp:.3f} adj={raw_adj:+.3f} final_dp={new_d:.3f}  "
          f"old={old_pred_clean:10s} new={new_pred:10s} actual={actual:10s} ({actual_score}){flip_flag}")

    # Top3 score hit
    top3_scores_str = [s["score"] for s in top3]
    if actual_score in top3_scores_str: score_hits += 1

    results[mtr.match_type].append({
        "id": mid, "home": hn, "away": an, "actual": actual, "actual_score": actual_score,
        "old_pred": old_pred_clean, "new_pred": new_pred, "old_dp": dp, "new_dp": new_d,
        "old_lh": lh, "new_lh": new_lh, "old_la": la, "new_la": new_la,
        "top3": top3_scores_str, "match_type": mtr.match_type, "elo_gap": elo_gap,
    })

# ── Print results ─────────────────────────────────────
acc = hits / total * 100 if total else 0
recall = draw_hits / draw_act * 100 if draw_act else 0
prec = draw_hits / draw_pred * 100 if draw_pred else 0
score_acc = score_hits / total * 100 if total else 0

dp_disp = draw_pred if draw_pred else 0
print(f"\n  OVERALL: Acc={acc:.1f}% ({hits}/{total})  DrawR={recall:.1f}% ({draw_hits}/{draw_act})  "
      f"DrawP={prec:.1f}% ({draw_hits}/{dp_disp})  Top3Hit={score_acc:.1f}% ({score_hits}/{total})")
print(f"  Wrong flips: Home->Draw={home_to_draw}  Away->Draw={away_to_draw}")

print(f"\n  PER-TYPE BREAKDOWN:")
for t in ["A", "B", "C", "D"]:
    ms = results[t]
    if not ms: continue
    n = len(ms)
    th = sum(1 for m in ms if m["new_pred"] == m["actual"])
    ta = sum(1 for m in ms if m["actual"] == "Draw")
    tp = sum(1 for m in ms if m["new_pred"] == "Draw")
    thd = sum(1 for m in ms if m["new_pred"] == "Draw" and m["actual"] == "Draw")
    ts = sum(1 for m in ms if m["actual_score"] in m["top3"])
    ta_pct = thd/ta*100 if ta else 0
    tp_pct = thd/tp*100 if tp else 0
    print(f"  Type {t} ({n} matches): Acc={th/n*100:.1f}%  DrawR={ta_pct:.1f}%({thd}/{ta})  "
          f"DrawP={tp_pct:.1f}%({thd}/{tp})  Top3Hit={ts/n*100:.1f}%({ts}/{n})")

print(f"\n  TOP 3 SCORE DIVERSITY CHECK:")
for t in ["A", "B", "C", "D"]:
    ms = results[t]
    if not ms: continue
    print(f"\n  Type {t}:")
    for m in ms[:5]:
        print(f"  #{m['id']} {m['home']:8s} vs {m['away']:8s}  {m['actual_score']:5s}  "
              f"old_pred={m['old_pred']:10s} new_pred={m['new_pred']:10s}  "
              f"dp={m['old_dp']:.3f}->{m['new_dp']:.3f}  "
              f"top3={m['top3']}")

print(f"\n  WRONG FLIPS DETAIL:")
for m in sum(results.values(), []):
    if m["old_pred"] != "Draw" and m["new_pred"] == "Draw" and m["actual"] != "Draw":
        print(f"  #{m['id']} {m['home']:8s} vs {m['away']:8s}  "
              f"type={m['match_type']}  {m['old_pred']}->Draw  actual={m['actual']} ({m['actual_score']})  "
              f"dp={m['old_dp']:.3f}->{m['new_dp']:.3f}")

# Compare with baseline
print(f"\n  COMPARISON WITH BASELINE:")
# Count baseline stats
bl_hits = 0; bl_dh = 0; bl_dp = 0; bl_da = 0
for r in rows:
    (mid, hs, aws, ko, hn, an, elo_h, elo_a, h_hist, a_hist,
     old_pred, old_ps, old_top_json, old_backup, hwp, dp, awp, mb_json, conf, upset,
     h_odds, d_odds, a_odds) = r
    actual = "Home Win" if hs > aws else ("Draw" if hs == aws else "Away Win")
    bl_pred = pick_v2(hwp, dp, awp, upset or 0)
    if bl_pred == actual: bl_hits += 1;
    if actual == "Draw" and bl_pred == actual: bl_dh += 1
    if actual == "Draw": bl_da += 1
    if bl_pred == "Draw": bl_dp += 1
bl_acc = bl_hits / total * 100 if total else 0
bl_recall = bl_dh / bl_da * 100 if bl_da else 0
bl_prec = bl_dh / bl_dp * 100 if bl_dp else 0
print(f"  Baseline:      Acc={bl_acc:.1f}%  DrawR={bl_recall:.1f}%  DrawP={bl_prec:.1f}%")
print(f"  MatchType V1:  Acc={acc:.1f}%  DrawR={recall:.1f}%  DrawP={prec:.1f}%")
print(f"  Delta:         Acc={acc-bl_acc:+.1f}pp  DrawR={recall-bl_recall:+.1f}pp  DrawP={prec-bl_prec:+.1f}pp")
print(f"  Top3 Score Hit: {score_acc:.1f}% ({score_hits}/{total})")
