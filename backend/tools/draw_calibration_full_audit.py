#!/usr/bin/env python3
"""
Draw Calibration Layer — FULL AUDIT

Phase 1: Backtest all finished matches
Phase 2: Test 5 parameter sets
Phase 3: Output all metrics
Phase 4: Flip analysis
Phase 5: Final recommendation
"""
from __future__ import annotations

import math, sqlite3, json
from dataclasses import dataclass, field
from collections import defaultdict

DB = "worldcup_ai.db"
WORLD_CUP_COMPETITIONS = {"世界杯", "World Cup", "FIFA World Cup"}

PARAM_SETS = {
    "A (f=1.00 baseline)": (1.00, 0.42),
    "B (f=1.10)":          (1.10, 0.42),
    "C (f=1.15)":          (1.15, 0.42),
    "D (f=1.20)":          (1.20, 0.42),
    "E (f=1.25 current)":  (1.25, 0.42),
}


# ═══════════════════════════════════════════════════════════
#  CALIBRATION LOGIC (exact copy from predictor.py)
# ═══════════════════════════════════════════════════════════
def normalize(h, d, a):
    t = h + d + a
    if t <= 0: return 1/3, 1/3, 1/3
    return h/t, d/t, a/t


def draw_calibrate(hwp, dp, awp, competition="世界杯", factor=1.25, cap=0.42):
    if competition not in WORLD_CUP_COMPETITIONS or dp <= 0:
        return hwp, dp, awp, False
    d_corrected = min(dp * factor, cap)
    boost = d_corrected - dp
    if boost <= 0.001:
        return hwp, dp, awp, False
    total_side = hwp + awp
    if total_side <= 0:
        return hwp, dp, awp, False
    h_new = max(0.01, hwp - boost * hwp / total_side)
    a_new = max(0.01, awp - boost * awp / total_side)
    total = h_new + d_corrected + a_new
    return round(h_new / total, 4), round(d_corrected / total, 4), round(a_new / total, 4), True


def pick_v2(h, d, a, upset=0.0):
    wp = max(h, a); wg = wp - d
    if d >= 0.30: return "Draw"
    if d >= 0.25:
        if wg <= 0.12 and upset >= 60.0: return "Draw"
        if wg > 0.15: return "Home Win" if h >= a else "Away Win"
        return "UNCERTAIN"
    return "Home Win" if h >= d and h >= a else ("Away Win" if a >= h and a >= d else "Draw")


# ═══════════════════════════════════════════════════════════
#  METRICS
# ═══════════════════════════════════════════════════════════
@dataclass
class AuditResult:
    factor: float = 1.00
    cap: float = 0.42
    label: str = ""
    total: int = 0
    hits: int = 0
    draw_hits: int = 0
    draw_pred: int = 0
    draw_act: int = 0
    brier: float = 0.0
    logloss: float = 0.0
    roi: float = 0.0
    conf_matrix: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    flips_correct: list = field(default_factory=list)
    flips_wrong: list = field(default_factory=list)
    calibrated_count: int = 0

    @property
    def accuracy(self): return self.hits / self.total * 100 if self.total else 0

    @property
    def draw_recall(self): return self.draw_hits / self.draw_act * 100 if self.draw_act else 0

    @property
    def draw_precision(self): return self.draw_hits / self.draw_pred * 100 if self.draw_pred else 0


def run_audit(matches, factor, cap) -> AuditResult:
    r = AuditResult(factor=factor, cap=cap)
    for m in matches:
        orig_h = m["home_prob"]
        orig_d = m["draw_probability"]
        orig_a = m["away_prob"]
        actual = m["actual_result"]
        competition = m.get("competition", "世界杯")
        upset = m.get("upset_probability", 0.0)
        label = m.get("label", "")

        # Baseline prediction (no calibration)
        bl_pred = pick_v2(orig_h, orig_d, orig_a, upset)

        # Calibrated prediction
        cal_h, cal_d, cal_a, applied = draw_calibrate(orig_h, orig_d, orig_a, competition, factor, cap)
        cal_pred = pick_v2(cal_h, cal_d, cal_a, upset)

        if applied:
            r.calibrated_count += 1

        # ── Use calibrated prediction ──
        pred = cal_pred
        hwp, dp, awp = cal_h, cal_d, cal_a

        if actual == "Draw":
            r.draw_act += 1
        if pred == "Draw":
            r.draw_pred += 1
        if pred == actual:
            r.hits += 1
            if actual == "Draw":
                r.draw_hits += 1

        r.total += 1

        # Confusion matrix
        r.conf_matrix[actual][pred] += 1

        # Brier & LogLoss (use calibrated probabilities)
        eps = 1e-15
        if actual == "Home Win":
            r.brier += (hwp-1)**2 + (dp-0)**2 + (awp-0)**2
            r.logloss += -math.log(max(hwp, eps))
        elif actual == "Away Win":
            r.brier += (hwp-0)**2 + (dp-0)**2 + (awp-1)**2
            r.logloss += -math.log(max(awp, eps))
        else:
            r.brier += (hwp-0)**2 + (dp-1)**2 + (awp-0)**2
            r.logloss += -math.log(max(dp, eps))

        # ROI (simplified: +1 for hit, -1 for miss, 0 for UNCERTAIN)
        if pred == "UNCERTAIN":
            r.roi += 0
        elif pred == actual:
            r.roi += 1
        else:
            r.roi += -1

        # Flip analysis
        if applied:
            if bl_pred != "Draw" and cal_pred == "Draw":
                if actual == "Draw":
                    r.flips_correct.append({
                        "label": label,
                        "old_pred": bl_pred,
                        "new_pred": cal_pred,
                        "actual": actual,
                        "orig_dp": round(orig_d, 4),
                        "new_dp": round(cal_d, 4),
                    })
                else:
                    r.flips_wrong.append({
                        "label": label,
                        "old_pred": bl_pred,
                        "new_pred": cal_pred,
                        "actual": actual,
                        "orig_dp": round(orig_d, 4),
                        "new_dp": round(cal_d, 4),
                    })

    r.brier /= r.total if r.total else 1
    r.logloss /= r.total if r.total else 1
    r.roi = round(r.roi / r.total * 100, 2) if r.total else 0
    return r


# ═══════════════════════════════════════════════════════════
#  DATA LOADER
# ═══════════════════════════════════════════════════════════
def load_all_finished() -> list[dict]:
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        SELECT m.id, m.home_score, m.away_score, m.kickoff_time, m.competition,
               ht.name, at.name,
               p.draw_probability, p.home_win_probability, p.away_win_probability,
               p.predicted_result, p.upset_probability
        FROM matches m
        JOIN teams ht ON m.home_team_id = ht.id
        JOIN teams at ON m.away_team_id = at.id
        LEFT JOIN predictions p ON m.id = p.match_id
        WHERE m.home_score IS NOT NULL AND m.away_score IS NOT NULL
        ORDER BY m.kickoff_time ASC
    """)
    rows = cur.fetchall()
    conn.close()
    matches = []
    for r in rows:
        mid, hs, aws, ko, comp, hn, an, dp, hwp, awp, pr, upset = r
        actual = "Home Win" if hs > aws else ("Draw" if hs == aws else "Away Win")
        matches.append({
            "label": f"#{mid} {hn} vs {an}",
            "home_prob": hwp or 0.50,
            "draw_probability": dp or 0.23,
            "away_prob": awp or 0.27,
            "actual_result": actual,
            "competition": comp or "世界杯",
            "upset_probability": upset or 0.0,
            "date": ko,
            "home_team": hn, "away_team": an,
            "home_score": hs, "away_score": aws,
            "predicted_result": pr,
        })
    return matches


# ═══════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════
def main():
    all_matches = load_all_finished()
    print(f"Total finished matches with predictions: {len(all_matches)}")

    # Datasets
    datasets = {
        "ALL (n={})".format(len(all_matches)): all_matches,
        "LAST-20": all_matches[-20:],
        "LAST-30": all_matches[-30:] if len(all_matches) >= 30 else all_matches,
        "LAST-50": all_matches[-50:] if len(all_matches) >= 50 else all_matches,
    }

    # ── PHASE 2 & 3: Parameter sweep across all datasets ──
    print("\n" + "=" * 80)
    print("  PHASE 2 & 3: PARAMETER SWEEP — FULL METRICS")
    print("=" * 80)

    all_results = {}
    for ds_name, ds_matches in datasets.items():
        n = len(ds_matches)
        actual_draws = sum(1 for m in ds_matches if m["actual_result"] == "Draw")
        avg_dp = sum(m["draw_probability"] for m in ds_matches) / n

        print(f"\n{'─'*80}")
        print(f"  DATASET: {ds_name}")
        print(f"  Matches={n}  Actual draws={actual_draws} ({actual_draws/n*100:.1f}%)  Avg model dp={avg_dp*100:.1f}%")
        print(f"{'─'*80}")

        for param_label, (factor, cap) in PARAM_SETS.items():
            r = run_audit(ds_matches, factor, cap)
            all_results[(ds_name, param_label)] = r

            # Print metrics table
            acc = r.accuracy
            recall = r.draw_recall
            prec = r.draw_precision
            print(f"\n  [{param_label}]  factor={factor}  cap={cap}  calibrated={r.calibrated_count}/{r.total}")
            print(f"    Accuracy:       {acc:6.1f}%  ({r.hits}/{r.total})")
            print(f"    Draw Recall:    {recall:6.1f}%  ({r.draw_hits}/{r.draw_act})")
            print(f"    Draw Precision: {prec:6.1f}%  ({r.draw_hits}/{r.draw_pred})")
            print(f"    ROI:            {r.roi:+.1f}%")
            print(f"    Brier Score:    {r.brier:.4f}")
            print(f"    Log Loss:       {r.logloss:.4f}")
            print(f"    Draws Predicted:{r.draw_pred}  UNCERTAIN: {sum(r.conf_matrix[a].get('UNCERTAIN', 0) for a in ['Home Win','Draw','Away Win'])}")

            # Confusion matrix
            cm = r.conf_matrix
            print(f"    Confusion Matrix (actual → predicted):")
            for act in ["Home Win", "Draw", "Away Win"]:
                row_vals = []
                for pred in ["Home Win", "Draw", "Away Win", "UNCERTAIN"]:
                    v = cm.get(act, {}).get(pred, 0)
                    if v > 0:
                        row_vals.append(f"{pred}={v}")
                print(f"      {act:10s} → {'  '.join(row_vals)}")

        # ── Delta vs baseline ──
        print(f"\n  {'─'*60}")
        print(f"  DELTA vs BASELINE (f=1.00)")
        print(f"  {'─'*60}")
        bl = all_results[(ds_name, "A (f=1.00 baseline)")]
        print(f"  {'Param':<20} {'ΔAcc':>8} {'ΔRecall':>10} {'ΔPrec':>10} {'ΔROI':>8} {'ΔBrier':>8} {'ΔLogL':>8}")
        for param_label, (factor, cap) in PARAM_SETS.items():
            if param_label == "A (f=1.00 baseline)":
                continue
            r = all_results[(ds_name, param_label)]
            da = r.accuracy - bl.accuracy
            dr = r.draw_recall - bl.draw_recall
            dp_ = r.draw_precision - bl.draw_precision
            droi = r.roi - bl.roi
            db = r.brier - bl.brier
            dl = r.logloss - bl.logloss
            print(f"  {param_label:<20} {da:+.1f}pp    {dr:+.1f}pp    {dp_:+.1f}pp    {droi:+.1f}%  {db:+.4f}  {dl:+.4f}")

    # ── PHASE 4: Flip Analysis ──
    print(f"\n{'='*80}")
    print(f"  PHASE 4: FLIP ANALYSIS (ALL matches)")
    print(f"{'='*80}")

    for param_label, (factor, cap) in PARAM_SETS.items():
        if param_label == "A (f=1.00 baseline)":
            continue
        r = all_results[("ALL (n={})".format(len(all_matches)), param_label)]
        correct = r.flips_correct
        wrong = r.flips_wrong
        total_flips = len(correct) + len(wrong)
        if total_flips == 0:
            print(f"\n  [{param_label}] No flips (calibration never crossed decision threshold)")
            continue
        print(f"\n  [{param_label}] Total flips: {total_flips}  (Correct={len(correct)}  Wrong={len(wrong)})")
        if correct:
            print(f"    ✓ Correct flips (was Win/Loss → Draw, actual=Draw):")
            for f in correct:
                print(f"      {f['label']:40s} {f['old_pred']:>10s} → Draw  dp: {f['orig_dp']:.3f}→{f['new_dp']:.3f}")
        if wrong:
            print(f"    ✗ Wrong flips (was Win/Loss → Draw, actual≠Draw):")
            for f in wrong:
                print(f"      {f['label']:40s} {f['old_pred']:>10s} → Draw  dp: {f['orig_dp']:.3f}→{f['new_dp']:.3f}  actual={f['actual']}")

    # ── PHASE 5: Final Recommendation ──
    print(f"\n{'='*80}")
    print(f"  PHASE 5: FINAL RECOMMENDATION")
    print(f"{'='*80}")

    # Use ALL matches for recommendation
    ds_key = "ALL (n={})".format(len(all_matches))
    bl = all_results[(ds_key, "A (f=1.00 baseline)")]

    print(f"\n  Baseline (f=1.00): Acc={bl.accuracy:.1f}%  DrawRecall={bl.draw_recall:.1f}%  "
          f"DrawPrec={bl.draw_precision:.1f}%  ROI={bl.roi:+.1f}%")

    best = None
    best_label = ""
    for param_label in ["B (f=1.10)", "C (f=1.15)", "D (f=1.20)", "E (f=1.25 current)"]:
        r = all_results[(ds_key, param_label)]
        da = r.accuracy - bl.accuracy
        dr = r.draw_recall - bl.draw_recall

        verdict = ""
        if dr > 0 and da >= -1.0:
            verdict = "✅ EFFECTIVE"
        elif dr > 0 and da < -1.0:
            verdict = "⚠️ OVER-INTERVENTION"
        elif dr <= 0:
            verdict = "❌ NO BENEFIT"
        else:
            verdict = "—"

        print(f"\n  [{param_label}] Acc={r.accuracy:.1f}% (Δ{da:+.1f}pp)  "
              f"DrawRecall={r.draw_recall:.1f}% (Δ{dr:+.1f}pp)  "
              f"ROI={r.roi:+.1f}%  → {verdict}")

        if verdict == "✅ EFFECTIVE":
            if best is None or dr > best[0]:
                best = (dr, da, r, param_label)

    print(f"\n  {'='*60}")
    if best:
        dr, da, r_best, label = best
        factor, cap = PARAM_SETS[label]
        print(f"  ✅ RECOMMENDED: {label}")
        print(f"     DRAW_CALIBRATION_FACTOR = {factor}")
        print(f"     DRAW_CALIBRATION_CAP    = {cap}")
        print(f"     Accuracy:  {r_best.accuracy:.1f}% (Δ{da:+.1f}pp vs baseline)")
        print(f"     Draw Recall: {r_best.draw_recall:.1f}% (Δ{dr:+.1f}pp)")
        print(f"     Draw Precision: {r_best.draw_precision:.1f}%")
        print(f"     ROI: {r_best.roi:+.1f}%")
        correct_flips = len(r_best.flips_correct) if hasattr(r_best, 'flips_correct') else 0
        wrong_flips = len(r_best.flips_wrong) if hasattr(r_best, 'flips_wrong') else 0
        print(f"     Flips: {correct_flips} correct + {wrong_flips} wrong")
    else:
        print(f"  ❌ No parameter set meets the effectiveness criteria.")
        print(f"     Draw Calibration Layer should be DISABLED or re-designed.")

    print(f"\n  Criteria: Draw Recall ↑ AND Accuracy drop ≤ 1pp")


if __name__ == "__main__":
    main()
