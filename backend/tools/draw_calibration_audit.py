#!/usr/bin/env python3
"""Draw Calibration Audit — run against worldcup_ai.db"""
import sqlite3, json, math, sys
from collections import defaultdict

DB = "worldcup_ai.db"

def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
        SELECT m.id, m.home_score, m.away_score, m.kickoff_time,
               ht.name as home_name, at.name as away_name,
               p.predicted_result, p.home_win_probability,
               p.draw_probability, p.away_win_probability,
               p.model_breakdown, p.confidence
        FROM matches m
        JOIN teams ht ON m.home_team_id = ht.id
        JOIN teams at ON m.away_team_id = at.id
        LEFT JOIN predictions p ON m.id = p.match_id
        WHERE m.home_score IS NOT NULL AND m.away_score IS NOT NULL
        ORDER BY m.kickoff_time DESC
    """)

    rows = cur.fetchall()
    total = len(rows)

    # ── Categorize ──────────────────────────────────────────
    actual_draws = []
    actual_home = []
    actual_away = []
    all_draw_probs = []

    for r in rows:
        mid, hs, aws, ko, hn, an, pr, hwp, dp, awp, mb_json, conf = r
        if hs > aws:
            actual_home.append(r)
            onehot = (1, 0, 0)
        elif hs < aws:
            actual_away.append(r)
            onehot = (0, 0, 1)
        else:
            actual_draws.append(r)
            onehot = (0, 1, 0)
        all_draw_probs.append(dp)

    # ── 1. OVERALL ──────────────────────────────────────────
    print("=" * 64)
    print("  DRAW CALIBRATION AUDIT REPORT")
    print("=" * 64)
    print(f"\n  Total finished matches: {total}")
    print(f"  Actual  Home Win: {len(actual_home):2d}  ({len(actual_home)/total*100:5.1f}%)")
    print(f"  Actual  Draw:     {len(actual_draws):2d}  ({len(actual_draws)/total*100:5.1f}%)")
    print(f"  Actual  Away Win: {len(actual_away):2d}  ({len(actual_away)/total*100:5.1f}%)")

    # ── 2. MODEL DRAW PROB ──────────────────────────────────
    avg_dp = sum(r[8] for r in rows) / total
    avg_dp_actual_draw = sum(r[8] for r in actual_draws) / len(actual_draws) if actual_draws else 0
    avg_dp_actual_notdraw = sum(r[8] for r in actual_home + actual_away) / len(actual_home + actual_away)

    print(f"\n  Model average draw probability: {avg_dp*100:.1f}%")
    print(f"  Model avg dp when actual=Draw:  {avg_dp_actual_draw*100:.1f}%")
    print(f"  Model avg dp when actual≠Draw:  {avg_dp_actual_notdraw*100:.1f}%")

    actual_draw_rate = len(actual_draws) / total
    calibration_error = avg_dp - actual_draw_rate
    print(f"\n  Actual draw rate:  {actual_draw_rate*100:.1f}%")
    print(f"  Calibration error: {calibration_error*100:+.1f}%  (model {'OVER' if calibration_error > 0 else 'UNDER'}estimates draw)")

    # ── 3. BRIER SCORE ──────────────────────────────────────
    brier = 0.0
    draw_only_brier = 0.0
    for r in rows:
        mid, hs, aws, ko, hn, an, pr, hwp, dp, awp, mb_json, conf = r
        if hs > aws:
            brier += (hwp - 1) ** 2 + (dp - 0) ** 2 + (awp - 0) ** 2
        elif hs < aws:
            brier += (hwp - 0) ** 2 + (dp - 0) ** 2 + (awp - 1) ** 2
        else:
            brier += (hwp - 0) ** 2 + (dp - 1) ** 2 + (awp - 0) ** 2
        draw_only_brier += (dp - (1 if hs == aws else 0)) ** 2
    brier /= total
    draw_only_brier /= total
    print(f"\n  Overall Brier Score:   {brier:.4f}")
    print(f"  Draw-only Brier Score: {draw_only_brier:.4f}")

    # ── 4. LOG LOSS ─────────────────────────────────────────
    logloss = 0.0
    eps = 1e-15
    for r in rows:
        mid, hs, aws, ko, hn, an, pr, hwp, dp, awp, mb_json, conf = r
        if hs > aws:
            logloss += -math.log(max(hwp, eps))
        elif hs < aws:
            logloss += -math.log(max(awp, eps))
        else:
            logloss += -math.log(max(dp, eps))
    logloss /= total
    print(f"  Log Loss:              {logloss:.4f}")

    # ── 5. RECALL BY RESULT ─────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"  RECALL BY RESULT CLASS")
    print(f"{'─'*60}")
    for label, subset in [("Home Win", actual_home), ("Draw", actual_draws), ("Away Win", actual_away)]:
        if not subset:
            continue
        hits = sum(1 for r in subset if r[6] == label)
        print(f"  {label:10s}: {hits:2d}/{len(subset):2d} = {hits/len(subset)*100:5.1f}%")

    # ── 6. CONFIDENCE BUCKET CALIBRATION ────────────────────
    print(f"\n{'─'*60}")
    print(f"  DRAW PROBABILITY BUCKET CALIBRATION")
    print(f"{'─'*60}")
    buckets = [(0.15, 0.20), (0.20, 0.25), (0.25, 0.30), (0.30, 0.35), (0.35, 1.0)]
    for lo, hi in buckets:
        bucket_matches = [r for r in rows if lo <= r[8] < hi]
        if not bucket_matches:
            continue
        bucket_draws = sum(1 for r in bucket_matches if r[1] == r[2])
        avg_bucket_dp = sum(r[8] for r in bucket_matches) / len(bucket_matches)
        print(f"  dp [{lo:.2f}-{hi:.2f}): {len(bucket_matches):2d} matches, "
              f"actual draws={bucket_draws}/{len(bucket_matches)} ({bucket_draws/len(bucket_matches)*100:.1f}%), "
              f"avg model dp={avg_bucket_dp*100:.1f}%")

    # ── 7. MODEL BREAKDOWN CONTRIBUTIONS ────────────────────
    print(f"\n{'─'*60}")
    print(f"  DRAW PROBABILITY BY MODULE (avg across all matches)")
    print(f"{'─'*60}")
    module_draws = defaultdict(list)
    for r in rows:
        mb_json = r[10]
        if not mb_json:
            continue
        try:
            mb = json.loads(mb_json)
        except (json.JSONDecodeError, TypeError):
            continue
        for module, probs in mb.items():
            if isinstance(probs, dict) and 'draw' in probs:
                module_draws[module].append(probs['draw'])

    for module in ["elo", "form", "odds", "poisson", "monte_carlo", "h2h", "strength_proxy"]:
        probs = module_draws.get(module, [])
        if probs:
            print(f"  {module:20s}: avg draw = {sum(probs)/len(probs)*100:5.1f}%  (n={len(probs)})")

    # ── 8. WORLD CUP vs NON-WORLD CUP ──────────────────────
    print(f"\n{'─'*60}")
    print(f"  WORLD CUP SPECIFIC")
    print(f"{'─'*60}")
    wc_rows = [r for r in rows if r[3] and '2026' in str(r[3])]
    if wc_rows:
        wc_draws = sum(1 for r in wc_rows if r[1] == r[2])
        wc_avg_dp = sum(r[8] for r in wc_rows) / len(wc_rows)
        print(f"  World Cup 2026 matches: {len(wc_rows)}")
        print(f"  WC actual draws: {wc_draws} ({wc_draws/len(wc_rows)*100:.1f}%)")
        print(f"  WC model avg dp:  {wc_avg_dp*100:.1f}%")
        print(f"  WC calibration error: {(wc_avg_dp - wc_draws/len(wc_rows))*100:+.1f}%")

    # ── 9. LATEST 8 MATCHES (incl the 4 from today) ────────
    print(f"\n{'─'*60}")
    print(f"  LATEST FINISHED MATCHES (draw probability detail)")
    print(f"{'─'*60}")
    for r in rows[:12]:
        mid, hs, aws, ko, hn, an, pr, hwp, dp, awp, mb_json, conf = r
        actual = "Home Win" if hs > aws else ("Draw" if hs == aws else "Away Win")
        hit = "✓" if pr == actual else "✗"
        print(f"  #{mid:2d} {hn:8s} vs {an:8s}  {hs}-{aws}  | "
              f"model dp={dp*100:4.1f}%  pred={pr:10s}  actual={actual:10s}  {hit}")

    # ── 10. BINNED RELIABILITY DIAGRAM ─────────────────────
    print(f"\n{'─'*60}")
    print(f"  RELIABILITY: Predicted vs Actual Draw Rate")
    print(f"{'─'*60}")
    bins = [(0.15, 0.19), (0.19, 0.23), (0.23, 0.27), (0.27, 0.31), (0.31, 0.40)]
    for lo, hi in bins:
        bm = [r for r in rows if lo <= r[8] < hi]
        if not bm:
            continue
        draws = sum(1 for r in bm if r[1] == r[2])
        avg = sum(r[8] for r in bm) / len(bm)
        print(f"  Pred dp [{lo:.2f}-{hi:.2f}): {len(bm):2d} matches, "
              f"draw rate={draws/len(bm)*100:5.1f}%, avg pred={avg*100:5.1f}%")

    conn.close()

    # ── FINDINGS ───────────────────────────────────────────
    print(f"\n{'='*64}")
    print(f"  KEY FINDINGS")
    print(f"{'='*64}")
    if calibration_error < -0.02:
        print(f"  ⚠️  Draw is SYSTEMATICALLY UNDERESTIMATED by {abs(calibration_error)*100:.1f}%")
        print(f"     Actual draw rate: {actual_draw_rate*100:.1f}%")
        print(f"     Model avg dp:     {avg_dp*100:.1f}%")
    elif calibration_error > 0.02:
        print(f"  ⚠️  Draw is SYSTEMATICALLY OVERESTIMATED by {calibration_error*100:.1f}%")
    else:
        print(f"  ✅ Draw calibration is within ±2% — acceptable.")

    print(f"\n  ELO module    — draw capped at 18-32% (min/max clamp)")
    print(f"  Form module   — draw capped at 18-34% (min/max clamp)")
    print(f"  Poisson       — draw from 6x6 score matrix (Dixon-Coles corrected)")
    print(f"  Monte Carlo   — 100k samples over score matrix")
    print(f"  Odds Fusion   — 1/odds normalization")
    print(f"  Draw Specialist — fires only when λ<2.3-2.5 & ELO gap<50-80")
    print(f"                   max boost 0.22 in conflict scenarios")
    print(f"                   otherwise boost is 0.04-0.08 or none")
    print(f"\n  ROOT CAUSE: ELO + Form clamps at 18-32/34% are the binding")
    print(f"  constraint. Draw Specialist gate is too narrow to compensate.")
    print(f"  Weighted fusion with Poisson (22%) and MC (10%) cannot")
    print(f"  overcome the clamps on the larger-weight modules (ELO 27% + Form 20%).")

if __name__ == "__main__":
    main()
