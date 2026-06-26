#!/usr/bin/env python3
"""
Draw Environment Monitor + Dynamic Decision Layer — Full Backtest

Walks forward through matches chronologically. For each match:
  1. Compute draw environment from the N matches immediately before it
  2. Apply dynamic Decision Layer thresholds
  3. Compare to baseline V2

Datasets:
  - 2018+2022 World Cup (128 matches from backtest_predictions)
  - 2026 recent N matches (from matches table)
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from typing import Literal

DB = "worldcup_ai.db"

# ── Draw Environment Monitor ────────────────────────────
DrawEnv = Literal["LOW_DRAW_ENV", "NORMAL_DRAW_ENV", "HIGH_DRAW_ENV"]


@dataclass
class DrawEnvMonitor:
    window_size: int = 20
    high_threshold: float = 0.08   # actual_rate - avg_dp >= 0.08 → HIGH
    low_threshold: float = 0.08    # actual_rate - avg_dp <= -0.08 → LOW

    def classify(
        self, recent_matches: list[dict]
    ) -> tuple[DrawEnv, float, float, float]:
        """Given recent matches (each with draw_probability, actual_result),
        return the environment classification and stats."""
        if not recent_matches or len(recent_matches) < 5:
            return "NORMAL_DRAW_ENV", 0.0, 0.0, 0.0

        n = len(recent_matches)
        actual_draws = sum(1 for m in recent_matches if m["actual_result"] == "Draw")
        actual_draw_rate = actual_draws / n
        avg_dp = sum(m["draw_probability"] for m in recent_matches) / n
        calibration_error = actual_draw_rate - avg_dp

        if calibration_error >= self.high_threshold:
            env = "HIGH_DRAW_ENV"
        elif calibration_error <= -self.low_threshold:
            env = "LOW_DRAW_ENV"
        else:
            env = "NORMAL_DRAW_ENV"

        return env, actual_draw_rate, avg_dp, calibration_error


# ── Decision Layer V2 (baseline) ────────────────────────
def pick_result_v2(
    home: float, draw: float, away: float, upset_probability: float = 0.0,
) -> tuple[str, float, str]:
    win_prob = max(home, away)
    win_gap = win_prob - draw

    if draw >= 0.30:
        confidence = 55.0 + (draw - 0.30) * 150.0
        return "Draw", round(min(85.0, confidence), 1), "LOW"

    if draw >= 0.25:
        if win_gap <= 0.12 and upset_probability >= 60.0:
            confidence = 42.0 + (upset_probability - 60.0) * 0.5
            return "Draw", round(min(65.0, confidence), 1), "MEDIUM"
        if win_gap > 0.15:
            if home >= away:
                return "Home Win", round(40.0 + win_gap * 60.0, 1), "MEDIUM"
            return "Away Win", round(40.0 + win_gap * 60.0, 1), "MEDIUM"
        uncertainty_score = round(15.0 + (0.15 - win_gap) * 300.0, 1)
        return "UNCERTAIN", min(45.0, uncertainty_score), "HIGH"

    if home >= draw and home >= away:
        gap = home - max(draw, away)
        confidence = 60.0 + gap * 60.0
        risk = "MEDIUM" if gap < 0.08 else "LOW"
        return "Home Win", round(min(92.0, confidence), 1), risk
    if away >= home and away >= draw:
        gap = away - max(home, draw)
        confidence = 60.0 + gap * 60.0
        risk = "MEDIUM" if gap < 0.08 else "LOW"
        return "Away Win", round(min(92.0, confidence), 1), risk
    return "Draw", 30.0, "HIGH"


# ── Decision Layer V3 (dynamic thresholds) ──────────────
def pick_result_v3(
    home: float,
    draw: float,
    away: float,
    upset_probability: float = 0.0,
    draw_env: DrawEnv = "NORMAL_DRAW_ENV",
) -> tuple[str, float, str]:
    """Decision Layer with draw-environment-aware thresholds."""
    # ── Dynamic thresholds ──
    if draw_env == "HIGH_DRAW_ENV":
        draw_strong = 0.27   # was 0.30
        gray_zone = 0.23     # was 0.25
    elif draw_env == "LOW_DRAW_ENV":
        draw_strong = 0.32   # was 0.30
        gray_zone = 0.27     # was 0.25
    else:
        draw_strong = 0.30
        gray_zone = 0.25

    win_prob = max(home, away)
    win_gap = win_prob - draw

    # ── Zone 1: Strong Draw ──
    if draw >= draw_strong:
        confidence = 55.0 + (draw - draw_strong) * 150.0
        return "Draw", round(min(85.0, confidence), 1), "LOW"

    # ── Zone 2: Gray Zone ──
    if draw >= gray_zone:
        if win_gap <= 0.12 and upset_probability >= 60.0:
            confidence = 42.0 + (upset_probability - 60.0) * 0.5
            return "Draw", round(min(65.0, confidence), 1), "MEDIUM"
        if win_gap > 0.15:
            if home >= away:
                return "Home Win", round(40.0 + win_gap * 60.0, 1), "MEDIUM"
            return "Away Win", round(40.0 + win_gap * 60.0, 1), "MEDIUM"
        uncertainty_score = round(15.0 + (0.15 - win_gap) * 300.0, 1)
        return "UNCERTAIN", min(45.0, uncertainty_score), "HIGH"

    # ── Zone 3: Normal ──
    if home >= draw and home >= away:
        gap = home - max(draw, away)
        confidence = 60.0 + gap * 60.0
        risk = "MEDIUM" if gap < 0.08 else "LOW"
        return "Home Win", round(min(92.0, confidence), 1), risk
    if away >= home and away >= draw:
        gap = away - max(home, draw)
        confidence = 60.0 + gap * 60.0
        risk = "MEDIUM" if gap < 0.08 else "LOW"
        return "Away Win", round(min(92.0, confidence), 1), risk
    return "Draw", 30.0, "HIGH"


# ── Walk-Forward Backtest ────────────────────────────────
@dataclass
class BacktestResult:
    total: int = 0
    hits: int = 0
    draw_hits: int = 0
    draw_predicted: int = 0
    draw_actual: int = 0
    uncertain: int = 0
    brier: float = 0.0
    draw_only_brier: float = 0.0
    env_counts: dict[str, int] = field(default_factory=lambda: {"HIGH_DRAW_ENV": 0, "NORMAL_DRAW_ENV": 0, "LOW_DRAW_ENV": 0})


def walk_forward_backtest(
    matches_chronological: list[dict],
    monitor: DrawEnvMonitor,
    use_env: bool = False,
) -> BacktestResult:
    """Walk-forward: for each match, look at matches before it to determine env."""
    result = BacktestResult()

    for i, match in enumerate(matches_chronological):
        # Determine draw environment from PRECEDING matches only
        recent = matches_chronological[max(0, i - monitor.window_size) : i]
        env, actual_rate, avg_dp, calib_err = monitor.classify(recent)
        result.env_counts[env] += 1

        hwp = match["home_prob"]
        dp = match["draw_probability"]
        awp = match["away_prob"]
        upset = match.get("upset_probability", 0.0)
        actual = match["actual_result"]

        if use_env:
            pred, conf, risk = pick_result_v3(hwp, dp, awp, upset, env)
        else:
            pred, conf, risk = pick_result_v2(hwp, dp, awp, upset)

        if actual == "Draw":
            result.draw_actual += 1
        if pred == "Draw":
            result.draw_predicted += 1
        if pred == actual:
            result.hits += 1
            if actual == "Draw":
                result.draw_hits += 1
        if pred == "UNCERTAIN":
            result.uncertain += 1

        result.total += 1
        # Brier
        if actual == "Home Win":
            result.brier += (hwp - 1) ** 2 + (dp - 0) ** 2 + (awp - 0) ** 2
        elif actual == "Away Win":
            result.brier += (hwp - 0) ** 2 + (dp - 0) ** 2 + (awp - 1) ** 2
        else:
            result.brier += (hwp - 0) ** 2 + (dp - 1) ** 2 + (awp - 0) ** 2
        result.draw_only_brier += (dp - (1 if actual == "Draw" else 0)) ** 2

    result.brier /= result.total
    result.draw_only_brier /= result.total
    return result


def print_result(label: str, r: BacktestResult):
    acc = r.hits / r.total * 100 if r.total else 0
    recall = r.draw_hits / r.draw_actual * 100 if r.draw_actual else 0
    prec = r.draw_hits / r.draw_predicted * 100 if r.draw_predicted else 0
    print(f"  {label}:")
    print(f"    Accuracy:       {acc:.1f}% ({r.hits}/{r.total})")
    print(f"    Draw Recall:    {recall:.1f}% ({r.draw_hits}/{r.draw_actual})")
    print(f"    Draw Precision: {prec:.1f}% ({r.draw_hits}/{r.draw_predicted})")
    print(f"    Draws Predicted:{r.draw_predicted}  UNCERTAIN: {r.uncertain}")
    print(f"    Brier Score:    {r.brier:.4f}  (draw-only: {r.draw_only_brier:.4f})")
    print(f"    Env distribution: HIGH={r.env_counts['HIGH_DRAW_ENV']} "
          f"NORMAL={r.env_counts['NORMAL_DRAW_ENV']} LOW={r.env_counts['LOW_DRAW_ENV']}")


# ── LOAD DATA ────────────────────────────────────────────
def load_wc_2018_2022() -> list[dict]:
    """Load 2018+2022 World Cup backtest data."""
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    # Get the most recent run for 2018,2022
    cur.execute("""
        SELECT bp.draw_probability, bp.home_win_probability,
               bp.away_win_probability, bp.actual_result, bp.predicted_result,
               COALESCE(bp.predicted_score, '0-0'),
               wcm.match_date
        FROM backtest_predictions bp
        JOIN backtest_runs br ON bp.run_id = br.id
        JOIN world_cup_matches wcm ON bp.match_id = wcm.id
        WHERE br.years = '2018,2022'
          AND br.id = (SELECT MAX(id) FROM backtest_runs WHERE years = '2018,2022')
        ORDER BY wcm.match_date ASC
    """)
    rows = cur.fetchall()
    conn.close()

    matches = []
    for r in rows:
        dp, hwp, awp, actual, pred, score, date = r
        # Estimate upset probability (simplified)
        upset = max(0, (1 - max(hwp, dp, awp)) * 100)
        matches.append({
            "draw_probability": dp or 0.23,
            "home_prob": hwp or 0.50,
            "away_prob": awp or 0.27,
            "actual_result": actual,
            "predicted_result": pred,
            "upset_probability": upset,
            "date": date,
        })
    return matches


def load_recent_2026(n: int | None = None) -> list[dict]:
    """Load recent 2026 World Cup matches."""
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        SELECT m.id, m.home_score, m.away_score, m.kickoff_time,
               p.draw_probability, p.home_win_probability,
               p.away_win_probability, p.predicted_result,
               p.market_type, p.upset_probability
        FROM matches m
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
        mid, hs, aws, ko, dp, hwp, awp, pr, mkt, upset = r
        if hs > aws:
            actual = "Home Win"
        elif hs < aws:
            actual = "Away Win"
        else:
            actual = "Draw"
        matches.append({
            "draw_probability": dp or 0.23,
            "home_prob": hwp or 0.50,
            "away_prob": awp or 0.27,
            "actual_result": actual,
            "predicted_result": pr or "Home Win",
            "upset_probability": upset or 0.0,
            "date": ko,
        })
    return matches


# ── MAIN ──────────────────────────────────────────────────
def main():
    monitor = DrawEnvMonitor(window_size=20)

    # ────── Dataset 1: 2018+2022 World Cup ────────────────
    print("=" * 64)
    print("  DATASET 1: 2018+2022 World Cup (128 matches)")
    print("=" * 64)
    wc_matches = load_wc_2018_2022()
    if not wc_matches:
        print("  [SKIP] No 2018+2022 data found in backtest_predictions")
    else:
        print(f"  Loaded {len(wc_matches)} matches")
        actual_draws = sum(1 for m in wc_matches if m["actual_result"] == "Draw")
        print(f"  Actual draws: {actual_draws} ({actual_draws/len(wc_matches)*100:.1f}%)")
        avg_dp = sum(m["draw_probability"] for m in wc_matches) / len(wc_matches)
        print(f"  Avg model dp: {avg_dp*100:.1f}%")

        # Walk-forward: different window sizes
        for window in [20, 30, 50]:
            print(f"\n{'─'*50}")
            print(f"  Window size N = {window}")
            print(f"{'─'*50}")
            mon = DrawEnvMonitor(window_size=window)

            baseline = walk_forward_backtest(wc_matches, mon, use_env=False)
            print_result("  BASELINE (V2)", baseline)

            env = walk_forward_backtest(wc_matches, mon, use_env=True)
            print_result("  ENV-AWARE (V3)", env)

            # Delta
            acc_delta = (env.hits/env.total - baseline.hits/baseline.total) * 100
            recall_delta = (env.draw_hits/max(env.draw_actual,1) - baseline.draw_hits/max(baseline.draw_actual,1)) * 100
            print(f"    Δ Accuracy: {acc_delta:+.1f}pp  Δ Draw Recall: {recall_delta:+.1f}pp")

    # ────── Dataset 2: Recent 20 2026 matches ─────────────
    print(f"\n{'='*64}")
    print(f"  DATASET 2: Recent 20 2026 matches")
    print(f"{'='*64}")
    r20 = load_recent_2026(20)
    print(f"  Loaded {len(r20)} matches")
    actual_draws = sum(1 for m in r20 if m["actual_result"] == "Draw")
    avg_dp = sum(m["draw_probability"] for m in r20) / len(r20)
    print(f"  Actual draws: {actual_draws} ({actual_draws/len(r20)*100:.1f}%)")
    print(f"  Avg model dp: {avg_dp*100:.1f}%")

    for window in [10, 15, 20]:
        print(f"\n  Window N={window}:")
        mon = DrawEnvMonitor(window_size=window)
        bl = walk_forward_backtest(r20, mon, use_env=False)
        ev = walk_forward_backtest(r20, mon, use_env=True)
        print_result("  BASELINE (V2)", bl)
        print_result("  ENV-AWARE (V3)", ev)
        acc_d = (ev.hits/ev.total - bl.hits/bl.total) * 100
        rec_d = (ev.draw_hits/max(ev.draw_actual,1) - bl.draw_hits/max(bl.draw_actual,1)) * 100
        print(f"    Δ Accuracy: {acc_d:+.1f}pp  Δ Draw Recall: {rec_d:+.1f}pp")

    # ────── Dataset 3: All 24 2026 matches ────────────────
    print(f"\n{'='*64}")
    print(f"  DATASET 3: All 24 2026 matches")
    print(f"{'='*64}")
    r24 = load_recent_2026()
    print(f"  Loaded {len(r24)} matches")
    actual_draws = sum(1 for m in r24 if m["actual_result"] == "Draw")
    avg_dp = sum(m["draw_probability"] for m in r24) / len(r24)
    print(f"  Actual draws: {actual_draws} ({actual_draws/len(r24)*100:.1f}%)")
    print(f"  Avg model dp: {avg_dp*100:.1f}%")

    for window in [10, 15, 20, 24]:
        print(f"\n  Window N={window}:")
        mon = DrawEnvMonitor(window_size=window)
        bl = walk_forward_backtest(r24, mon, use_env=False)
        ev = walk_forward_backtest(r24, mon, use_env=True)
        print_result("  BASELINE (V2)", bl)
        print_result("  ENV-AWARE (V3)", ev)
        acc_d = (ev.hits/ev.total - bl.hits/bl.total) * 100
        rec_d = (ev.draw_hits/max(ev.draw_actual,1) - bl.draw_hits/max(bl.draw_actual,1)) * 100
        print(f"    Δ Accuracy: {acc_d:+.1f}pp  Δ Draw Recall: {rec_d:+.1f}pp")

    # ── Summary ───────────────────────────────────────────
    print(f"\n{'='*64}")
    print(f"  SUMMARY")
    print(f"{'='*64}")
    print("""
    Draw Environment Monitor:
      - Computes actual draw rate vs model avg dp over last N matches
      - Classifies: HIGH / NORMAL / LOW draw environment
      - Dynamically adjusts Decision Layer thresholds ONLY

    No modification to:
      - ELO module
      - Poisson/Dixon-Coles score matrix
      - Monte Carlo
      - Odds Fusion
      - Draw Specialist
      - Any probability weights
    """)

if __name__ == "__main__":
    main()
