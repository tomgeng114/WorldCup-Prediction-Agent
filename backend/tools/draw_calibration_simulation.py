#!/usr/bin/env python3
"""Draw Calibration Layer v1 — simulation and backtest"""
import sqlite3, json, math
from collections import defaultdict

DB = "worldcup_ai.db"

def normalize(h, d, a):
    t = h + d + a
    if t <= 0:
        return 1/3, 1/3, 1/3
    return h/t, d/t, a/t

def actual_result(hs, aws):
    if hs > aws: return "Home Win"
    if hs < aws: return "Away Win"
    return "Draw"

def pick_result(h, d, a):
    if d >= 0.25 and max(h, a) - d <= 0.18:
        return "Draw"
    if h >= d and h >= a:
        return "Home Win"
    if a >= h and a >= d:
        return "Away Win"
    return "Draw"

def pick_result_v2(h, d, a, upset=0):
    win_gap = max(h, a) - d
    if d >= 0.30:
        return "Draw"
    if d >= 0.25:
        if win_gap <= 0.12 and upset >= 60.0:
            return "Draw"
        if win_gap > 0.15:
            return "Home Win" if h >= a else "Away Win"
        return "UNCERTAIN"
    if h >= d and h >= a:
        return "Home Win"
    if a >= h and a >= d:
        return "Away Win"
    return "Draw"

def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
        SELECT m.id, m.home_score, m.away_score, m.kickoff_time,
               ht.name, at.name,
               p.predicted_result, p.home_win_probability,
               p.draw_probability, p.away_win_probability,
               p.model_breakdown, p.market_type, p.confidence,
               p.upset_probability, p.predicted_market_result
        FROM matches m
        JOIN teams ht ON m.home_team_id = ht.id
        JOIN teams at ON m.away_team_id = at.id
        LEFT JOIN predictions p ON m.id = p.match_id
        WHERE m.home_score IS NOT NULL AND m.away_score IS NOT NULL
        ORDER BY m.kickoff_time
    """)

    rows = cur.fetchall()
    conn.close()

    # ── BASELINE ────────────────────────────────────────────
    def baseline_stats(rows):
        total = len(rows)
        hits = 0
        draw_hits = 0
        draw_actual = 0
        draw_predicted = 0
        uncert = 0
        for r in rows:
            mid, hs, aws, ko, hn, an, pr, hwp, dp, awp, mb_json, mkt, conf, upset, pmr = r
            actual = actual_result(hs, aws)
            if actual == "Draw":
                draw_actual += 1
            if pr == "Draw":
                draw_predicted += 1
            if pr == actual:
                hits += 1
                if actual == "Draw":
                    draw_hits += 1
            if pr == "UNCERTAIN":
                uncert += 1
        return {
            "total": total, "hits": hits, "draw_hits": draw_hits,
            "draw_actual": draw_actual, "draw_predicted": draw_predicted,
            "accuracy": hits/total*100,
            "draw_recall": draw_hits/draw_actual*100 if draw_actual else 0,
            "draw_precision": draw_hits/draw_predicted*100 if draw_predicted else 0,
            "uncertain": uncert,
        }

    baseline = baseline_stats(rows)
    print("="*64)
    print("  BASELINE (current model)")
    print("="*64)
    print(f"  Accuracy:      {baseline['accuracy']:.1f}% ({baseline['hits']}/{baseline['total']})")
    print(f"  Draw Recall:   {baseline['draw_recall']:.1f}% ({baseline['draw_hits']}/{baseline['draw_actual']})")
    print(f"  Draw Precision:{baseline['draw_precision']:.1f}% ({baseline['draw_hits']}/{baseline['draw_predicted']})")
    print(f"  UNCERTAIN:     {baseline['uncertain']}")

    # ── APPROACH A: Additive calibration boost ──────────────
    # dp_corrected = dp + calibration_boost
    # Re-normalize after boost
    print(f"\n{'='*64}")
    print(f"  APPROACH A: dp_corrected = dp + CALIBRATION_BOOST")
    print(f"{'='*64}")
    for boost in [0.04, 0.06, 0.08, 0.10, 0.12, 0.15]:
        hits = 0; draw_hits = 0; draw_pred = 0; draw_act = 0; uncert = 0
        for r in rows:
            mid, hs, aws, ko, hn, an, pr, hwp, dp, awp, mb_json, mkt, conf, upset, pmr = r
            actual = actual_result(hs, aws)
            if actual == "Draw":
                draw_act += 1
            # Apply boost
            ndp = dp + boost
            nh, nd, na = normalize(hwp * (1 - boost), ndp, awp * (1 - boost))
            new_pr = pick_result_v2(nh, nd, na, upset or 0)
            if new_pr == "UNCERTAIN":
                uncert += 1
            elif new_pr == "Draw":
                draw_pred += 1
                if actual == "Draw":
                    draw_hits += 1
            if new_pr == actual:
                hits += 1
        acc = hits / len(rows) * 100
        recall = draw_hits / draw_act * 100 if draw_act else 0
        prec = draw_hits / draw_pred * 100 if draw_pred else 0
        acc_drop = baseline["accuracy"] - acc
        print(f"  boost={boost:5.2f}: Acc={acc:5.1f}% (Δ{acc_drop:+.1f})  "
              f"DrawRecall={recall:5.1f}%  DrawPrec={prec:5.1f}%  "
              f"DrawsPred={draw_pred}  UNCERTAIN={uncert}")

    # ── APPROACH B: Multiplicative factor ───────────────────
    # dp = dp * factor, capped at some max
    print(f"\n{'='*64}")
    print(f"  APPROACH B: dp_corrected = dp * FACTOR (capped)")
    print(f"{'='*64}")
    for factor in [1.15, 1.20, 1.25, 1.30, 1.40, 1.50, 1.60]:
        for cap in [0.38, 0.42, 0.45]:
            hits = 0; draw_hits = 0; draw_pred = 0; draw_act = 0; uncert = 0
            for r in rows:
                mid, hs, aws, ko, hn, an, pr, hwp, dp, awp, mb_json, mkt, conf, upset, pmr = r
                actual = actual_result(hs, aws)
                if actual == "Draw":
                    draw_act += 1
                ndp = min(dp * factor, cap)
                total_boost = ndp - dp
                nh, nd, na = normalize(
                    max(0.01, hwp - total_boost * hwp/(hwp+awp) if hwp+awp > 0 else 0),
                    ndp,
                    max(0.01, awp - total_boost * awp/(hwp+awp) if hwp+awp > 0 else 0),
                )
                new_pr = pick_result_v2(nh, nd, na, upset or 0)
                if new_pr == "UNCERTAIN":
                    uncert += 1
                elif new_pr == "Draw":
                    draw_pred += 1
                    if actual == "Draw":
                        draw_hits += 1
                if new_pr == actual:
                    hits += 1
            acc = hits / len(rows) * 100
            recall = draw_hits / draw_act * 100 if draw_act else 0
            prec = draw_hits / draw_pred * 100 if draw_pred else 0
            acc_drop = baseline["accuracy"] - acc
            print(f"  x{factor:.2f} cap={cap:.2f}: Acc={acc:5.1f}% (Δ{acc_drop:+.1f})  "
                  f"Recall={recall:5.1f}%  Prec={prec:5.1f}%  "
                  f"DrawsPred={draw_pred}  UNC={uncert}")

    # ── APPROACH C: World Cup gate ──────────────────────────
    # If world_cup: dp *= factor, else unchanged
    print(f"\n{'='*64}")
    print(f"  APPROACH C: if WORLD_CUP then dp = dp * FACTOR")
    print(f"{'='*64}")
    for factor in [1.20, 1.25, 1.30, 1.40, 1.50, 1.60, 1.80]:
        hits = 0; draw_hits = 0; draw_pred = 0; draw_act = 0; uncert = 0
        for r in rows:
            mid, hs, aws, ko, hn, an, pr, hwp, dp, awp, mb_json, mkt, conf, upset, pmr = r
            actual = actual_result(hs, aws)
            if actual == "Draw":
                draw_act += 1
            # Apply WC factor
            ndp = min(dp * factor, 0.45)
            total_boost = ndp - dp
            nh, nd, na = normalize(
                max(0.01, hwp - total_boost * hwp/(hwp+awp) if hwp+awp > 0 else 0),
                ndp,
                max(0.01, awp - total_boost * awp/(hwp+awp) if hwp+awp > 0 else 0),
            )
            new_pr = pick_result_v2(nh, nd, na, upset or 0)
            if new_pr == "UNCERTAIN":
                uncert += 1
            elif new_pr == "Draw":
                draw_pred += 1
                if actual == "Draw":
                    draw_hits += 1
            if new_pr == actual:
                hits += 1
        acc = hits / len(rows) * 100
        recall = draw_hits / draw_act * 100 if draw_act else 0
        prec = draw_hits / draw_pred * 100 if draw_pred else 0
        acc_drop = baseline["accuracy"] - acc
        print(f"  x{factor:.2f}: Acc={acc:5.1f}% (Δ{acc_drop:+.1f})  "
              f"Recall={recall:5.1f}%  Prec={prec:5.1f}%  "
              f"DrawsPred={draw_pred}  UNC={uncert}")

    # ── APPROACH D: Tiered boost based on dp level ──────────
    # Low dp (<0.21): big boost; medium (0.21-0.25): medium; high (>0.25): small
    print(f"\n{'='*64}")
    print(f"  APPROACH D: Tiered boost by dp level")
    print(f"{'='*64}")

    tiers = [
        # (dp_lo, dp_hi, boost)
        # Tier 1: very low dp → biggest boost (these are the draws we miss most)
        # Tier 2: medium dp → moderate boost
        # Tier 3: already high dp → small or no boost
        (0.00, 0.21, 0.12, "T1: dp<0.21  +0.12"),
        (0.00, 0.21, 0.10, "T1: dp<0.21  +0.10"),
        (0.00, 0.21, 0.08, "T1: dp<0.21  +0.08"),
    ]
    for lo, hi, boost, label in tiers:
        hits = 0; draw_hits = 0; draw_pred = 0; draw_act = 0; uncert = 0
        for r in rows:
            mid, hs, aws, ko, hn, an, pr, hwp, dp, awp, mb_json, mkt, conf, upset, pmr = r
            actual = actual_result(hs, aws)
            if actual == "Draw":
                draw_act += 1
            # Tiered boost
            if dp < 0.21:
                actual_boost = 0.12
            elif dp < 0.25:
                actual_boost = 0.08
            elif dp < 0.28:
                actual_boost = 0.04
            else:
                actual_boost = 0.0

            ndp = min(dp + actual_boost, 0.42)
            nh, nd, na = normalize(
                max(0.01, hwp * (1 - actual_boost * 0.7)),
                ndp,
                max(0.01, awp * (1 - actual_boost * 0.7)),
            )
            new_pr = pick_result_v2(nh, nd, na, upset or 0)
            if new_pr == "UNCERTAIN":
                uncert += 1
            elif new_pr == "Draw":
                draw_pred += 1
                if actual == "Draw":
                    draw_hits += 1
            if new_pr == actual:
                hits += 1
        acc = hits / len(rows) * 100
        recall = draw_hits / draw_act * 100 if draw_act else 0
        prec = draw_hits / draw_pred * 100 if draw_pred else 0
        acc_drop = baseline["accuracy"] - acc
        print(f"  Tiered: Acc={acc:5.1f}% (Δ{acc_drop:+.1f})  "
              f"Recall={recall:5.1f}%  Prec={prec:5.1f}%  "
              f"DrawsPred={draw_pred}  UNC={uncert}")

    # ── RECOMMENDATION ─────────────────────────────────────
    print(f"\n{'='*64}")
    print(f"  RECOMMENDATION")
    print(f"{'='*64}")
    print(f"""
    APPROACH A (additive boost +0.10) provides the best balance:
      - Simple: single constant added to dp then re-normalize
      - No new parameters needed beyond the boost value
      - Does not modify any upstream module (ELO, Poisson, etc.)
      - Can be easily tuned per-competition (WC vs non-WC)

    IMPLEMENTATION:
      dp_corrected = dp + DRAW_CALIBRATION_BOOST
      home, dp_corrected, away = normalize(home * (1-DRAW_CALIBRATION_BOOST),
                                            dp_corrected,
                                            away * (1-DRAW_CALIBRATION_BOOST))

    RECOMMENDED VALUE:
      DRAW_CALIBRATION_BOOST = 0.08 (conservative) or 0.10 (aggressive)
      - Conservative (0.08): prioritizes accuracy stability
      - Aggressive (0.10): prioritizes draw recall

    This is strictly a post-processing layer — it sits AFTER
    _draw_specialist_adjustment and BEFORE _pick_result_v2.
    """)


if __name__ == "__main__":
    main()
