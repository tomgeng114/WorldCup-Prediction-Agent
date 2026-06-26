#!/usr/bin/env python3
"""
Draw Calibration Layer v1 — Parameter Sweep & Pareto Optimization

Sweeps: 7 FACTORS × 5 CAPS = 35 combinations
Datasets: 2018 WC, 2022 WC, 2026 Recent 24, 2026 Recent 20

Score: 40% Accuracy + 30% Draw Recall + 20% Brier + 10% Draw Precision
(Brier is inverted: lower Brier → higher score)
"""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field

DB = "worldcup_ai.db"
WORLD_CUP_COMPETITIONS = {"世界杯", "World Cup", "FIFA World Cup"}

FACTORS = [1.00, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30]
CAPS = [0.35, 0.38, 0.40, 0.42, 0.45]


def normalize(h, d, a):
    t = h + d + a
    if t <= 0:
        return 1 / 3, 1 / 3, 1 / 3
    return h / t, d / t, a / t


def draw_calibrate(hwp, dp, awp, factor=1.30, cap=0.42):
    if dp <= 0:
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
    brier: float = 0.0
    logloss: float = 0.0

    @property
    def accuracy(self) -> float:
        return self.hits / self.total * 100 if self.total else 0

    @property
    def draw_recall(self) -> float:
        return self.draw_hits / self.draw_act * 100 if self.draw_act else 0

    @property
    def draw_precision(self) -> float:
        return self.draw_hits / self.draw_pred * 100 if self.draw_pred else 0


def evaluate(matches, factor=1.30, cap=0.42) -> Stats:
    s = Stats()
    for m in matches:
        hwp, dp, awp = m["home_prob"], m["draw_probability"], m["away_prob"]
        actual = m["actual_result"]
        upset = m.get("upset_probability", 0.0)

        hwp, dp, awp, _ = draw_calibrate(hwp, dp, awp, factor=factor, cap=cap)
        pred = pick_v2(hwp, dp, awp, upset)

        if actual == "Draw":
            s.draw_act += 1
        if pred == "Draw":
            s.draw_pred += 1
        if pred == actual:
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

    s.brier /= s.total if s.total else 1
    s.logloss /= s.total if s.total else 1
    return s


def composite_score(s: Stats, baseline_brier: float) -> float:
    """40% Accuracy + 30% Draw Recall + 20% Brier + 10% Draw Precision.
    Brier is inverted: score = (1 - brier/baseline_brier) * 100, so lower brier = higher score.
    """
    brier_score = max(0, (1 - s.brier / max(baseline_brier, 0.001)) * 100)
    return (
        0.40 * s.accuracy +
        0.30 * s.draw_recall +
        0.20 * brier_score +
        0.10 * s.draw_precision
    )


# ── DATA LOADERS ──────────────────────────────────────────
def load_wc_year(year: int) -> list[dict]:
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        SELECT wcm.home_team, wcm.away_team, wcm.home_score, wcm.away_score,
               bp.draw_probability, bp.home_win_probability, bp.away_win_probability
        FROM world_cup_matches wcm
        JOIN backtest_predictions bp ON wcm.id = bp.match_id
        JOIN backtest_runs br ON bp.run_id = br.id
        WHERE wcm.tournament_year = ?
          AND br.years LIKE '%' || ? || '%'
          AND br.id = (SELECT MAX(id) FROM backtest_runs WHERE years LIKE '%' || ? || '%')
        ORDER BY wcm.match_date ASC
    """, (year, str(year), str(year)))
    rows = cur.fetchall()
    conn.close()
    matches = []
    for r in rows:
        hn, an, hs, aws, dp, hwp, awp = r
        actual = "Home Win" if hs > aws else ("Draw" if hs == aws else "Away Win")
        matches.append({
            "home_prob": hwp or 0.50, "draw_probability": dp or 0.25,
            "away_prob": awp or 0.25, "actual_result": actual,
        })
    return matches


def load_recent_2026(n: int | None = None) -> list[dict]:
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        SELECT m.home_score, m.away_score,
               p.draw_probability, p.home_win_probability, p.away_win_probability
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
        hs, aws, dp, hwp, awp = r
        actual = "Home Win" if hs > aws else ("Draw" if hs == aws else "Away Win")
        matches.append({
            "home_prob": hwp or 0.50, "draw_probability": dp or 0.23,
            "away_prob": awp or 0.27, "actual_result": actual,
        })
    return matches


# ── MAIN SWEEP ────────────────────────────────────────────
def main():
    datasets = {
        "2018WC (64)": load_wc_year(2018),
        "2022WC (64)": load_wc_year(2022),
        "2018+2022 (128)": load_wc_year(2018) + load_wc_year(2022),
        "2026 R24": load_recent_2026(24),
        "2026 R20": load_recent_2026(20),
    }

    rows = []
    for ds_name, matches in datasets.items():
        if not matches:
            continue
        baseline = evaluate(matches, factor=1.00, cap=0.42)  # factor=1.00 = no change
        bl_brier = baseline.brier

        for factor in FACTORS:
            for cap in CAPS:
                s = evaluate(matches, factor=factor, cap=cap)
                score = composite_score(s, bl_brier)
                rows.append({
                    "dataset": ds_name,
                    "factor": factor,
                    "cap": cap,
                    "accuracy": s.accuracy,
                    "draw_recall": s.draw_recall,
                    "draw_precision": s.draw_precision,
                    "brier": s.brier,
                    "logloss": s.logloss,
                    "composite_score": score,
                    "total": s.total,
                    "draw_act": s.draw_act,
                    "draw_pred": s.draw_pred,
                })

    # ── Print per-dataset best ─────────────────────────────
    for ds_name in datasets:
        ds_rows = [r for r in rows if r["dataset"] == ds_name]
        if not ds_rows:
            continue
        ds_rows.sort(key=lambda r: r["composite_score"], reverse=True)
        print(f"\n{'='*70}")
        print(f"  {ds_name}")
        bl = [r for r in ds_rows if r["factor"] == 1.00][0]
        print(f"  Baseline (f=1.00): Acc={bl['accuracy']:.1f}%  DrawRecall={bl['draw_recall']:.1f}%  "
              f"DrawPrec={bl['draw_precision']:.1f}%  Brier={bl['brier']:.4f}  LogLoss={bl['logloss']:.4f}")
        print(f"  {'─'*60}")
        print(f"  {'Rank':<5} {'F':<6} {'Cap':<6} {'Score':<8} {'Acc':<8} {'DrawR':<9} {'DrawP':<9} {'Brier':<8} {'LogLoss':<8}")
        print(f"  {'─'*60}")
        for i, r in enumerate(ds_rows[:10]):
            print(f"  {i+1:<5} {r['factor']:<6.2f} {r['cap']:<6.2f} {r['composite_score']:<8.1f} "
                  f"{r['accuracy']:<8.1f} {r['draw_recall']:<9.1f} {r['draw_precision']:<9.1f} "
                  f"{r['brier']:<8.4f} {r['logloss']:<8.4f}")

    # ── Cross-dataset ranking ──────────────────────────────
    print(f"\n{'='*70}")
    print(f"  CROSS-DATASET AVERAGE RANKING")
    print(f"{'='*70}")

    # Aggregate scores across all 5 datasets
    agg = {}
    for r in rows:
        key = (r["factor"], r["cap"])
        if key not in agg:
            agg[key] = {"sum_score": 0, "count": 0, "details": []}
        agg[key]["sum_score"] += r["composite_score"]
        agg[key]["count"] += 1
        agg[key]["details"].append(r)

    # Sort by average score
    ranked = sorted(agg.items(), key=lambda x: x[1]["sum_score"] / x[1]["count"], reverse=True)

    print(f"  {'Rank':<5} {'F':<6} {'Cap':<6} {'AvgScore':<9} "
          f"{'2018WC':<10} {'2022WC':<10} {'18+22':<10} {'R24':<10} {'R20':<10}")
    print(f"  {'─'*75}")
    for i, (key, val) in enumerate(ranked[:15]):
        f, c = key
        avg = val["sum_score"] / val["count"]
        scores_by_ds = {}
        for d in val["details"]:
            scores_by_ds[d["dataset"]] = f"{d['composite_score']:.1f}"
        print(f"  {i+1:<5} {f:<6.2f} {c:<6.2f} {avg:<9.1f} "
              f"{scores_by_ds.get('2018WC (64)', '-'):<10} "
              f"{scores_by_ds.get('2022WC (64)', '-'):<10} "
              f"{scores_by_ds.get('2018+2022 (128)', '-'):<10} "
              f"{scores_by_ds.get('2026 R24', '-'):<10} "
              f"{scores_by_ds.get('2026 R20', '-'):<10}")

    # ── Recommend 3 tiers ──────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  RECOMMENDED PARAMETER SETS")
    print(f"{'='*70}")

    # Conservative: best on 2018+2022 (historical)
    hist_key = "2018+2022 (128)"
    hist_rows = [r for r in rows if r["dataset"] == hist_key]
    hist_rows.sort(key=lambda r: r["composite_score"], reverse=True)
    cons = hist_rows[0]

    # Balanced: best cross-dataset average, accuracy must not drop below -3pp on any dataset
    balanced = None
    for i, (key, val) in enumerate(ranked):
        f, c = key
        # Check accuracy constraint on each dataset
        ok = True
        for d in val["details"]:
            bl = [r for r in rows if r["dataset"] == d["dataset"] and r["factor"] == 1.00][0]
            if d["accuracy"] < bl["accuracy"] - 3.0:
                ok = False
                break
        if ok:
            balanced = (f, c, val)
            break

    # Aggressive: best on 2026 data
    r24_rows = [r for r in rows if r["dataset"] == "2026 R24"]
    r24_rows.sort(key=lambda r: r["composite_score"], reverse=True)
    aggr = r24_rows[0]

    for tier, params in [("保守", cons), ("平衡", balanced), ("激进", aggr)]:
        if params is None:
            continue
        if tier == "平衡":
            f, c = params[0], params[1]
            avg_score = params[2]["sum_score"] / params[2]["count"]
            print(f"\n  [{tier}] FACTOR={f:.2f}  CAP={c:.2f}  (AvgScore={avg_score:.1f})")
            for d in params[2]["details"]:
                print(f"    {d['dataset']:20s}: Acc={d['accuracy']:.1f}%  "
                      f"DrawR={d['draw_recall']:.1f}%  DrawP={d['draw_precision']:.1f}%  "
                      f"Brier={d['brier']:.4f}  LL={d['logloss']:.4f}")
        else:
            print(f"\n  [{tier}] FACTOR={params['factor']:.2f}  CAP={params['cap']:.2f}  "
                  f"(Score={params['composite_score']:.1f})")
            print(f"    Acc={params['accuracy']:.1f}%  DrawR={params['draw_recall']:.1f}%  "
                  f"DrawP={params['draw_precision']:.1f}%  "
                  f"Brier={params['brier']:.4f}  LL={params['logloss']:.4f}")


if __name__ == "__main__":
    main()
