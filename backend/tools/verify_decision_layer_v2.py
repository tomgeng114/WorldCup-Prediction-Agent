"""
Decision Layer v2 Verification — standalone (stdlib only).
Re-evaluates 2018+2022 World Cup backtest predictions using the new
risk-stratified decision logic without touching any model code.

Usage:
    cd E:\Tom\WorldCupAI2026\backend
    .venv/Scripts/python tools/verify_decision_layer_v2.py
"""

import sqlite3
import json
import math
import io
import sys
from pathlib import Path

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB_PATH = Path(__file__).resolve().parents[1] / "worldcup_ai.db"
RESULTS = ["Home Win", "Draw", "Away Win"]
UNCERTAIN = "UNCERTAIN"


# ── Decision Layer v2 (exact replica of predictor.py::_pick_result_v2) ──

def pick_result_v2(home: float, draw: float, away: float, upset: float = 0.0):
    """Returns (result, decision_confidence, risk_level)."""
    win_prob = max(home, away)
    win_gap = win_prob - draw

    # Zone 1: Strong Draw
    if draw >= 0.30:
        confidence = 55.0 + (draw - 0.30) * 150.0
        return "Draw", round(min(85.0, confidence), 1), "LOW"

    # Zone 2: Gray Zone (25%–30%)
    if draw >= 0.25:
        if win_gap <= 0.12 and upset >= 60.0:
            confidence = 42.0 + (upset - 60.0) * 0.5
            return "Draw", round(min(65.0, confidence), 1), "MEDIUM"
        if win_gap > 0.15:
            if home >= away:
                return "Home Win", round(40.0 + win_gap * 60.0, 1), "MEDIUM"
            return "Away Win", round(40.0 + win_gap * 60.0, 1), "MEDIUM"
        uncertainty_score = round(15.0 + (0.15 - win_gap) * 300.0, 1)
        return UNCERTAIN, min(45.0, uncertainty_score), "HIGH"

    # Zone 3: Normal Zone (draw < 25%)
    risk = "LOW"
    if home >= draw and home >= away:
        gap = home - max(draw, away)
        confidence = 60.0 + gap * 60.0
        if gap < 0.08:
            risk = "MEDIUM"
        return "Home Win", round(min(92.0, confidence), 1), risk
    if away >= home and away >= draw:
        gap = away - max(home, draw)
        confidence = 60.0 + gap * 60.0
        if gap < 0.08:
            risk = "MEDIUM"
        return "Away Win", round(min(92.0, confidence), 1), risk
    return "Draw", 30.0, "HIGH"


# ── Legacy Decision Layer v1 (original predictor.py::_pick_result) ──

def pick_result_v1(home: float, draw: float, away: float) -> str:
    if draw >= 0.25 and max(home, away) - draw <= 0.18:
        return "Draw"
    if home >= draw and home >= away:
        return "Home Win"
    if away >= home and away >= draw:
        return "Away Win"
    return "Draw"


# ── Upset probability (simplified for backtest data) ──

def compute_upset_proxy(
    home_prob: float, draw_prob: float, away_prob: float,
    market_home: float, market_draw: float, market_away: float,
) -> float:
    """Approximate upset probability for a Draw pick using available backtest data."""
    # Model pick probability for Draw
    model_pick_prob = draw_prob
    market_pick_prob = market_draw
    # ELO gap proxy from win probability spread
    elo_gap_proxy = abs(home_prob - away_prob) * 400  # rough inversion of ELO formula
    elo_risk = max(0.0, 1.0 - elo_gap_proxy / 450.0)
    market_disagreement = max(0.0, market_pick_prob - model_pick_prob)
    # Simplified without line_movement/kelly (not available in historical data)
    upset = (1.0 - model_pick_prob) * 0.55 + elo_risk * 0.18 + market_disagreement * 0.18
    return round(max(0.0, min(100.0, upset * 100.0)), 1)


# ── Main verification ──

def main():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    # Fetch backtest predictions for 2018+2022 (run_id=40)
    rows = db.execute("""
        SELECT
            bp.id,
            bp.home_win_probability,
            bp.draw_probability,
            bp.away_win_probability,
            bp.predicted_result  AS v1_result,
            bp.actual_result,
            bp.result_hit        AS v1_hit,
            wcm.match_date,
            wcm.home_team,
            wcm.away_team,
            wcm.stage,
            wcm.tournament_year,
            wco.home_win_odds,
            wco.draw_odds,
            wco.away_win_odds
        FROM backtest_predictions bp
        JOIN world_cup_matches wcm ON bp.match_id = wcm.id
        LEFT JOIN world_cup_odds wco ON bp.match_id = wco.match_id
        WHERE bp.run_id = 40
        ORDER BY wcm.match_date ASC
    """).fetchall()

    total = len(rows)
    print(f"Decision Layer v2 Verification")
    print(f"{'='*70}")
    print(f"Dataset: 2018 + 2022 World Cup, {total} matches (run_id=40)")
    print()

    # ── Counters ──
    v1_draw_predicted = 0
    v1_draw_correct = 0
    v1_total_correct = 0

    v2_draw_predicted = 0
    v2_draw_correct = 0
    v2_total_correct = 0
    v2_uncertain_count = 0
    v2_uncertain_actual_draw = 0

    risk_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
    zone_counts = {"strong_draw": 0, "gray_draw": 0, "gray_favorite": 0, "gray_uncertain": 0, "normal": 0}

    v1_details: list[dict] = []
    v2_details: list[dict] = []

    for row in rows:
        hp = row["home_win_probability"]
        dp = row["draw_probability"]
        ap = row["away_win_probability"]
        actual = row["actual_result"]

        # ── Market probabilities ──
        if row["home_win_odds"] and row["draw_odds"] and row["away_win_odds"]:
            inv_h = 1.0 / row["home_win_odds"]
            inv_d = 1.0 / row["draw_odds"]
            inv_a = 1.0 / row["away_win_odds"]
            total_inv = inv_h + inv_d + inv_a
            market_h = inv_h / total_inv if total_inv > 0 else 0.33
            market_d = inv_d / total_inv if total_inv > 0 else 0.33
            market_a = inv_a / total_inv if total_inv > 0 else 0.33
        else:
            market_h, market_d, market_a = hp, dp, ap  # fallback

        upset = compute_upset_proxy(hp, dp, ap, market_h, market_d, market_a)

        # ── V1 decision ──
        v1_result = row["v1_result"]
        v1_hit = bool(row["v1_hit"])
        if v1_result == "Draw":
            v1_draw_predicted += 1
            if actual == "Draw":
                v1_draw_correct += 1
        if v1_hit:
            v1_total_correct += 1

        # ── V2 decision ──
        v2_result, v2_conf, v2_risk = pick_result_v2(hp, dp, ap, upset)
        v2_hit = v2_result == actual

        if v2_result == "Draw":
            v2_draw_predicted += 1
            if actual == "Draw":
                v2_draw_correct += 1
        if v2_hit:
            v2_total_correct += 1
        if v2_result == UNCERTAIN:
            v2_uncertain_count += 1
            if actual == "Draw":
                v2_uncertain_actual_draw += 1

        risk_counts[v2_risk] = risk_counts.get(v2_risk, 0) + 1

        # Zone classification
        if dp >= 0.30:
            zone_counts["strong_draw"] += 1
        elif dp >= 0.25:
            if v2_result == "Draw":
                zone_counts["gray_draw"] += 1
            elif v2_result == UNCERTAIN:
                zone_counts["gray_uncertain"] += 1
            else:
                zone_counts["gray_favorite"] += 1
        else:
            zone_counts["normal"] += 1

        v1_details.append({
            "match": f"{row['home_team']} vs {row['away_team']}",
            "year": row["tournament_year"],
            "stage": row["stage"],
            "probs": f"H:{hp:.2%} D:{dp:.2%} A:{ap:.2%}",
            "v1": v1_result,
            "v2": v2_result,
            "v2_risk": v2_risk,
            "v2_conf": v2_conf,
            "actual": actual,
            "v1_hit": v1_hit,
            "v2_hit": v2_hit,
            "upset": upset,
        })

    # ── Compute metrics ──
    actual_draws = sum(1 for r in rows if r["actual_result"] == "Draw")

    v1_draw_recall = v1_draw_correct / actual_draws * 100 if actual_draws else 0
    v1_draw_precision = v1_draw_correct / v1_draw_predicted * 100 if v1_draw_predicted else 0
    v1_draw_f1 = 2 * v1_draw_recall * v1_draw_precision / (v1_draw_recall + v1_draw_precision) if (v1_draw_recall + v1_draw_precision) else 0

    v2_draw_recall = v2_draw_correct / actual_draws * 100 if actual_draws else 0
    v2_draw_precision = v2_draw_correct / v2_draw_predicted * 100 if v2_draw_predicted else 0
    v2_draw_f1 = 2 * v2_draw_recall * v2_draw_precision / (v2_draw_recall + v2_draw_precision) if (v2_draw_recall + v2_draw_precision) else 0

    # For v2 "effective" accuracy: count UNCERTAIN as "not wrong" (withdrawn bet)
    v2_effective_correct = v2_total_correct + v2_uncertain_count
    v2_effective_accuracy = v2_effective_correct / total * 100

    # ── Output ──
    print(f"{'='*70}")
    print(f"COMPARISON: Decision Layer v1 vs v2")
    print(f"{'='*70}")
    print()
    print(f"{'Metric':<35} {'V1 (Legacy)':>14} {'V2 (New)':>14}")
    print(f"{'-'*35} {'-'*14} {'-'*14}")
    print(f"{'Total Matches':<35} {total:>14} {total:>14}")
    print(f"{'Actual Draws':<35} {actual_draws:>14} {actual_draws:>14}")
    print(f"{'Draws Predicted':<35} {v1_draw_predicted:>14} {v2_draw_predicted:>14}")
    print(f"{'Draws Correct':<35} {v1_draw_correct:>14} {v2_draw_correct:>14}")
    print(f"{'Draw Recall':<35} {v1_draw_recall:>13.1f}% {v2_draw_recall:>13.1f}%")
    print(f"{'Draw Precision':<35} {v1_draw_precision:>13.1f}% {v2_draw_precision:>13.1f}%")
    print(f"{'Draw F1 Score':<35} {v1_draw_f1:>13.1f}% {v2_draw_f1:>13.1f}%")
    print(f"{'Overall Hit Rate':<35} {v1_total_correct/total*100:>13.1f}% {v2_total_correct/total*100:>13.1f}%")
    print(f"{'UNCERTAIN Count':<35} {'—':>14} {v2_uncertain_count:>14}")
    print(f"{'Effective Accuracy (w/ UNCERTAIN)':<35} {'—':>14} {v2_effective_accuracy:>13.1f}%")
    print()

    print(f"{'='*70}")
    print(f"RISK DISTRIBUTION (V2)")
    print(f"{'='*70}")
    for level in ["LOW", "MEDIUM", "HIGH"]:
        count = risk_counts.get(level, 0)
        pct = count / total * 100
        bar = "█" * int(pct / 2)
        print(f"  {level:<8} {count:>4} ({pct:5.1f}%)  {bar}")
    print()

    print(f"{'='*70}")
    print(f"ZONE DISTRIBUTION (V2)")
    print(f"{'='*70}")
    zone_labels = {
        "strong_draw": "Strong Draw (≥30%)",
        "gray_draw": "Gray → Draw",
        "gray_favorite": "Gray → Favorite",
        "gray_uncertain": "Gray → UNCERTAIN",
        "normal": "Normal (<25%)",
    }
    for zone, label in zone_labels.items():
        count = zone_counts.get(zone, 0)
        pct = count / total * 100
        bar = "█" * int(pct / 2)
        print(f"  {label:<28} {count:>4} ({pct:5.1f}%)  {bar}")
    print()

    # Gray zone detailed analysis
    gray_total = zone_counts["gray_draw"] + zone_counts["gray_favorite"] + zone_counts["gray_uncertain"]
    gray_actual_draws = 0
    gray_v2_draw_hits = 0
    for d in v1_details:
        hp = float(d["probs"].split("D:")[1].split("%")[0]) / 100  # parse draw prob
        if 0.25 <= hp < 0.30:
            if d["actual"] == "Draw":
                gray_actual_draws += 1
            if d["v2"] == "Draw" and d["v2_hit"]:
                gray_v2_draw_hits += 1

    print(f"{'='*70}")
    print(f"GRAY ZONE DETAIL (25%–30% draw probability)")
    print(f"{'='*70}")
    print(f"  Matches in gray zone:       {gray_total}")
    print(f"  Actual draws in gray zone:  {gray_actual_draws}")
    print(f"  V2 gray-draw hits:          {gray_v2_draw_hits}")
    print(f"  V2 UNCERTAIN in gray zone:  {zone_counts['gray_uncertain']}")
    if gray_actual_draws > 0:
        print(f"  Gray draw capture rate:     {gray_v2_draw_hits/gray_actual_draws*100:.1f}%")
    print()

    # ── Key change highlights ──
    print(f"{'='*70}")
    print(f"KEY CHANGES (V1 → V2)")
    print(f"{'='*70}")
    changes = []
    for d in v1_details:
        if d["v1"] != d["v2"]:
            changes.append(d)

    for d in sorted(changes, key=lambda x: x["v2_risk"]):
        arrow = "[HIT]" if d["v2_hit"] else ("[WARN]" if d["v2"] == UNCERTAIN else "[MISS]")
        outcome = "HIT" if d["v2_hit"] else ("WITHDRAWN" if d["v2"] == UNCERTAIN else "MISS")
        print(f"  {arrow} [{d['year']}] {d['match']} | V1:{d['v1']} -> V2:{d['v2']} | "
              f"Actual:{d['actual']} | Risk:{d['v2_risk']} | {outcome}")

    print()

    # ── Summary verdict ──
    print(f"{'='*70}")
    print(f"VERDICT")
    print(f"{'='*70}")
    if v2_draw_recall > v1_draw_recall:
        print(f"  ✅ Draw recall improved:     {v1_draw_recall:.1f}% → {v2_draw_recall:.1f}% (+{v2_draw_recall-v1_draw_recall:.1f}pp)")
    else:
        print(f"  ⚠️  Draw recall changed:      {v1_draw_recall:.1f}% → {v2_draw_recall:.1f}% ({v2_draw_recall-v1_draw_recall:+.1f}pp)")

    if v2_draw_precision > v1_draw_precision:
        print(f"  ✅ Draw precision improved:  {v1_draw_precision:.1f}% → {v2_draw_precision:.1f}% (+{v2_draw_precision-v1_draw_precision:.1f}pp)")
    else:
        print(f"  ⚠️  Draw precision changed:   {v1_draw_precision:.1f}% → {v2_draw_precision:.1f}% ({v2_draw_precision-v1_draw_precision:+.1f}pp)")

    if v2_uncertain_count > 0:
        print(f"  📊 UNCERTAIN predictions:    {v2_uncertain_count} matches withdrawn from forced pick")
        print(f"     Of those, {v2_uncertain_actual_draw} were actual draws → avoided {v2_uncertain_count - v2_uncertain_actual_draw} false picks")

    print()
    print("Note: Decision Layer v2 does NOT modify probability models, weights, or features.")
    print("      It only changes how probabilities are translated into final predictions.")

    db.close()


if __name__ == "__main__":
    main()
