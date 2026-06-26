#!/usr/bin/env python3
"""
Draw Calibration Layer v1 — Comprehensive Backtest

Datasets:
  1. 2018 World Cup (64 matches)
  2. 2022 World Cup (64 matches)
  3. Recent 24 2026 matches
  4. Recent 20 2026 matches
"""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass

DB = "worldcup_ai.db"

FACTOR = 1.30
CAP = 0.42
WORLD_CUP_COMPETITIONS = {"世界杯", "World Cup", "FIFA World Cup"}


def normalize(h, d, a):
    t = h + d + a
    if t <= 0:
        return 1 / 3, 1 / 3, 1 / 3
    return h / t, d / t, a / t


def draw_calibrate(hwp, dp, awp, competition="世界杯", enabled=True, factor=FACTOR, cap=CAP):
    """Apply Draw Calibration Layer v1."""
    if not enabled or competition not in WORLD_CUP_COMPETITIONS or dp <= 0:
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


def pick_result(h, d, a):
    """Legacy Decision Layer."""
    if d >= 0.25 and max(h, a) - d <= 0.18:
        return "Draw"
    if h >= d and h >= a:
        return "Home Win"
    if a >= h and a >= d:
        return "Away Win"
    return "Draw"


def _pick_v2(h, d, a, upset=0.0):
    """Decision Layer v2."""
    wp = max(h, a)
    wg = wp - d
    if d >= 0.30:
        return "Draw"
    if d >= 0.25:
        if wg <= 0.12 and upset >= 60.0:
            return "Draw"
        if wg > 0.15:
            return "Home Win" if h >= a else "Away Win"
        return "UNCERTAIN"
    if h >= d and h >= a:
        return "Home Win"
    if a >= h and a >= d:
        return "Away Win"
    return "Draw"


@dataclass
class Stats:
    total: int = 0
    hits: int = 0
    draw_hits: int = 0
    draw_pred: int = 0
    draw_act: int = 0
    uncert: int = 0
    brier: float = 0.0
    logloss: float = 0.0
    calibrated_count: int = 0
    flips_to_draw: list = None

    def __post_init__(self):
        if self.flips_to_draw is None:
            self.flips_to_draw = []


def evaluate(matches, use_calibration=False) -> Stats:
    s = Stats()
    for m in matches:
        hwp, dp, awp = m["home_prob"], m["draw_probability"], m["away_prob"]
        actual = m["actual_result"]
        upset = m.get("upset_probability", 0.0)
        competition = m.get("competition", "世界杯")

        orig_h, orig_d, orig_a = hwp, dp, awp

        calibrated = False
        if use_calibration:
            hwp, dp, awp, calibrated = draw_calibrate(hwp, dp, awp, competition)
            if calibrated:
                s.calibrated_count += 1

        pred_v2 = _pick_v2(hwp, dp, awp, upset)
        pred_legacy = pick_result(hwp, dp, awp)

        if actual == "Draw":
            s.draw_act += 1
        if pred_v2 == "Draw":
            s.draw_pred += 1
        if pred_v2 == "UNCERTAIN":
            s.uncert += 1

        if pred_v2 == actual:
            s.hits += 1
            if actual == "Draw":
                s.draw_hits += 1

        s.total += 1

        # Brier
        if actual == "Home Win":
            s.brier += (hwp - 1) ** 2 + (dp - 0) ** 2 + (awp - 0) ** 2
        elif actual == "Away Win":
            s.brier += (hwp - 0) ** 2 + (dp - 0) ** 2 + (awp - 1) ** 2
        else:
            s.brier += (hwp - 0) ** 2 + (dp - 1) ** 2 + (awp - 0) ** 2

        # LogLoss
        eps = 1e-15
        if actual == "Home Win":
            s.logloss += -math.log(max(hwp, eps))
        elif actual == "Away Win":
            s.logloss += -math.log(max(awp, eps))
        else:
            s.logloss += -math.log(max(dp, eps))

        # Track flips
        if calibrated and use_calibration:
            old_pred = _pick_v2(orig_h, orig_d, orig_a, upset)
            if old_pred != "Draw" and pred_v2 == "Draw":
                s.flips_to_draw.append({
                    "match": m.get("label", ""),
                    "old_dp": round(orig_d, 4),
                    "new_dp": round(dp, 4),
                    "old_pred": old_pred,
                    "new_pred": pred_v2,
                    "actual": actual,
                })

    s.brier /= s.total if s.total else 1
    s.logloss /= s.total if s.total else 1
    return s


def print_stats(label: str, s: Stats):
    acc = s.hits / s.total * 100 if s.total else 0
    recall = s.draw_hits / s.draw_act * 100 if s.draw_act else 0
    prec = s.draw_hits / s.draw_pred * 100 if s.draw_pred else 0
    print(f"  {label}:")
    print(f"    Accuracy:       {acc:6.1f}% ({s.hits}/{s.total})")
    print(f"    Draw Recall:    {recall:6.1f}% ({s.draw_hits}/{s.draw_act})")
    print(f"    Draw Precision: {prec:6.1f}% ({s.draw_hits}/{s.draw_pred})")
    print(f"    Brier Score:    {s.brier:.4f}")
    print(f"    Log Loss:       {s.logloss:.4f}")
    print(f"    Calibrated:     {s.calibrated_count}/{s.total}")
    if s.uncert:
        print(f"    UNCERTAIN:      {s.uncert}")


# ── DATA LOADERS ──────────────────────────────────────────
def load_wc_year(year: int) -> list[dict]:
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        SELECT wcm.home_team, wcm.away_team, wcm.home_score, wcm.away_score,
               wcm.result, wcm.match_date,
               bp.draw_probability, bp.home_win_probability,
               bp.away_win_probability, bp.predicted_result
        FROM world_cup_matches wcm
        JOIN backtest_predictions bp ON wcm.id = bp.match_id
        JOIN backtest_runs br ON bp.run_id = br.id
        WHERE wcm.tournament_year = ?
          AND br.years LIKE '%' || ? || '%'
          AND br.id = (
              SELECT MAX(id) FROM backtest_runs
              WHERE years LIKE '%' || ? || '%'
          )
        ORDER BY wcm.match_date ASC
    """, (year, str(year), str(year)))
    rows = cur.fetchall()
    conn.close()

    matches = []
    for r in rows:
        hn, an, hs, aws, result, date, dp, hwp, awp, pred = r
        actual = "Home Win" if hs > aws else ("Draw" if hs == aws else "Away Win")
        matches.append({
            "label": f"{hn} vs {an}",
            "home_prob": hwp or 0.50,
            "draw_probability": dp or 0.25,
            "away_prob": awp or 0.25,
            "actual_result": actual,
            "competition": "World Cup",
            "upset_probability": max(0, (1 - max(hwp or 0.5, dp or 0.25, awp or 0.25)) * 100),
            "date": date,
        })
    return matches


def load_recent_2026(n: int | None = None) -> list[dict]:
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        SELECT m.id, m.home_score, m.away_score, m.kickoff_time,
               m.competition,
               ht.name, at.name,
               p.draw_probability, p.home_win_probability,
               p.away_win_probability, p.predicted_result,
               p.upset_probability
        FROM matches m
        JOIN teams ht ON m.home_team_id = ht.id
        JOIN teams at ON m.away_team_id = at.id
        LEFT JOIN predictions p ON m.id = p.match_id
        WHERE m.home_score IS NOT NULL AND m.away_score IS NOT NULL
        ORDER BY m.kickoff_time ASC
    """)
    rows = cur.fetchall()
    if n:
        rows = rows[-n:]
    conn.close()

    matches = []
    for r in rows:
        mid, hs, aws, ko, comp, hn, an, dp, hwp, awp, pr, upset = r
        actual = "Home Win" if hs > aws else ("Draw" if hs == aws else "Away Win")
        matches.append({
            "label": f"{hn} vs {an}",
            "home_prob": hwp or 0.50,
            "draw_probability": dp or 0.23,
            "away_prob": awp or 0.27,
            "actual_result": actual,
            "competition": comp or "世界杯",
            "upset_probability": upset or 0.0,
            "date": ko,
        })
    return matches


# ── MAIN ──────────────────────────────────────────────────
def main():
    datasets = [
        ("2018 World Cup (64 matches)", lambda: load_wc_year(2018)),
        ("2022 World Cup (64 matches)", lambda: load_wc_year(2022)),
        ("2018+2022 World Cup (128 matches)", lambda: load_wc_year(2018) + load_wc_year(2022)),
        ("2026 Recent 24 matches", lambda: load_recent_2026(24)),
        ("2026 Recent 20 matches", lambda: load_recent_2026(20)),
    ]

    for ds_name, loader in datasets:
        matches = loader()
        if not matches:
            print(f"\n{'='*60}\n  {ds_name}: [SKIP - no data]\n{'='*60}")
            continue

        # Stats
        total = len(matches)
        actual_draws = sum(1 for m in matches if m["actual_result"] == "Draw")
        avg_dp = sum(m["draw_probability"] for m in matches) / total

        print(f"\n{'='*64}")
        print(f"  {ds_name}")
        print(f"{'='*64}")
        print(f"  Total: {total}  Actual draws: {actual_draws} ({actual_draws/total*100:.1f}%)")
        print(f"  Model avg dp: {avg_dp*100:.1f}%")
        print(f"  Calibration: dp x{FACTOR} cap={CAP}")

        baseline = evaluate(matches, use_calibration=False)
        calibrated = evaluate(matches, use_calibration=True)

        print()
        print_stats("BASELINE (V2)", baseline)
        print()
        print_stats("CALIBRATED  ", calibrated)

        # Delta
        acc_d = (calibrated.hits / calibrated.total - baseline.hits / baseline.total) * 100
        rec_d = (calibrated.draw_hits / max(calibrated.draw_act, 1) -
                 baseline.draw_hits / max(baseline.draw_act, 1)) * 100
        prec_d = (calibrated.draw_hits / max(calibrated.draw_pred, 1) -
                  baseline.draw_hits / max(baseline.draw_pred, 1)) * 100
        brier_d = calibrated.brier - baseline.brier
        logloss_d = calibrated.logloss - baseline.logloss
        print(f"\n  Δ Accuracy:       {acc_d:+.1f}pp")
        print(f"  Δ Draw Recall:    {rec_d:+.1f}pp")
        print(f"  Δ Draw Precision: {prec_d:+.1f}pp")
        print(f"  Δ Brier Score:    {brier_d:+.4f}")
        print(f"  Δ Log Loss:       {logloss_d:+.4f}")

        # Show flips
        if calibrated.flips_to_draw:
            print(f"\n  Matches flipped to Draw by calibration:")
            correct = sum(1 for f in calibrated.flips_to_draw if f["actual"] == "Draw")
            incorrect = len(calibrated.flips_to_draw) - correct
            print(f"  (Correct: {correct}, Incorrect: {incorrect})")
            for f in calibrated.flips_to_draw:
                hit = "✓" if f["actual"] == "Draw" else "✗"
                print(f"    {hit} {f['match']:35s} old_dp={f['old_dp']:.3f} → new_dp={f['new_dp']:.3f}  "
                      f"{f['old_pred']:>10s} → {f['new_pred']:>10s}  actual={f['actual']}")


if __name__ == "__main__":
    main()
