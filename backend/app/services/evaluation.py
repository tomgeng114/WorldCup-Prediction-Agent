"""
Standardized Match-by-Match Backtest Evaluation Layer

Generates a fixed-format evaluation report suitable for:
  - Console backtest summaries
  - Frontend table rendering (JSON export)
  - Reproducible audit trails

Does NOT modify any prediction model (ELO, Poisson, lambda, weights, etc.).
Read-only evaluation layer — pure post-hoc analysis.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

# Lazy import: pandas only needed when user calls create_evaluation_report()
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


@dataclass
class ScoreRow:
    """One row of the evaluation table — one match."""
    index: int
    match_label: str
    home_team: str
    away_team: str
    actual_score: str
    top1_score: str
    top3_scores: list[str]
    hit1: bool
    hit3: bool
    home_goals: int = 0
    away_goals: int = 0
    lambda_home: Optional[float] = None
    lambda_away: Optional[float] = None
    draw_probability: Optional[float] = None
    predicted_result: str = ""
    actual_result: str = ""
    hit_result: bool = False


@dataclass
class EvaluationSummary:
    """Aggregated statistics from the evaluation report."""
    total_matches: int
    top1_hits: int
    top3_hits: int
    top1_accuracy: float
    top3_accuracy: float
    avg_lambda_home: Optional[float] = None
    avg_lambda_away: Optional[float] = None
    avg_actual_goals: Optional[float] = None
    lambda_error: Optional[float] = None
    high_score_matches: int = 0           # >=5 total goals
    high_score_top3_missed: int = 0
    result_accuracy: Optional[float] = None


def build_score_row(
    match_id: int,
    home_team: str,
    away_team: str,
    home_score: int,
    away_score: int,
    top_scores: list[dict],
    predicted_result: str = "",
    actual_result: str = "",
    lambda_home: Optional[float] = None,
    lambda_away: Optional[float] = None,
    draw_probability: Optional[float] = None,
) -> ScoreRow:
    """
    Build a single evaluation row from match data.

    Args:
        match_id: database match ID
        home_team, away_team: team names
        home_score, away_score: actual goals
        top_scores: list of {"score": "2-1", "probability": 0.10} dicts
        predicted_result: "Home Win" / "Draw" / "Away Win"
        actual_result: same format
        lambda_home, lambda_away: expected goals from model
        draw_probability: model's draw probability
    """
    actual_score = f"{home_score}-{away_score}"
    top3 = top_scores[:3]
    top1_score = top3[0]["score"] if top3 else "?"
    top3_strs = [s["score"] for s in top3]

    hit1 = (top1_score == actual_score)
    hit3 = (actual_score in top3_strs)

    result_hit = (predicted_result == actual_result) if predicted_result and actual_result else False

    return ScoreRow(
        index=match_id,
        match_label=f"{home_team} vs {away_team}",
        home_team=home_team,
        away_team=away_team,
        actual_score=actual_score,
        top1_score=top1_score,
        top3_scores=top3_strs,
        hit1=hit1,
        hit3=hit3,
        home_goals=home_score,
        away_goals=away_score,
        lambda_home=lambda_home,
        lambda_away=lambda_away,
        draw_probability=draw_probability,
        predicted_result=predicted_result,
        actual_result=actual_result,
        hit_result=result_hit,
    )


def create_evaluation_report(
    rows: list[ScoreRow],
    as_dataframe: bool = True,
) -> "pd.DataFrame | list[dict]":
    """
    Generate a standardized evaluation report.

    Args:
        rows: list of ScoreRow objects (one per match)
        as_dataframe: if True, return pandas DataFrame; else return list[dict]

    Returns:
        DataFrame with fixed column order, or list of dicts.
        Columns: #, Match, Score, Top1, Top3, Hit@1, Hit@3, lamH, lamA, Result Hit
    """
    data = []
    for i, r in enumerate(rows):
        top3_display = " / ".join(r.top3_scores) if r.top3_scores else "?"
        data.append({
            "#": r.index,
            "Match": r.match_label,
            "Score": r.actual_score,
            "Top1": r.top1_score,
            "Top3": top3_display,
            "Hit@1": "Y" if r.hit1 else "N",
            "Hit@3": "Y" if r.hit3 else "N",
            "lamH": round(r.lambda_home, 2) if r.lambda_home is not None else "",
            "lamA": round(r.lambda_away, 2) if r.lambda_away is not None else "",
            "Result Hit": "Y" if r.hit_result else ("N" if r.predicted_result else ""),
        })

    if as_dataframe and HAS_PANDAS:
        df = pd.DataFrame(data)
        return df[["#", "Match", "Score", "Top1", "Top3", "Hit@1", "Hit@3", "lamH", "lamA", "Result Hit"]]
    return data


def compute_summary(rows: list[ScoreRow]) -> EvaluationSummary:
    """
    Compute aggregated statistics from evaluation rows.

    Args:
        rows: list of ScoreRow objects
    Returns:
        EvaluationSummary with all computed metrics
    """
    n = len(rows)
    if n == 0:
        return EvaluationSummary(total_matches=0, top1_hits=0, top3_hits=0,
                                 top1_accuracy=0.0, top3_accuracy=0.0)

    t1_hits = sum(1 for r in rows if r.hit1)
    t3_hits = sum(1 for r in rows if r.hit3)
    result_hits = sum(1 for r in rows if r.hit_result)

    lam_h_vals = [r.lambda_home for r in rows if r.lambda_home is not None]
    lam_a_vals = [r.lambda_away for r in rows if r.lambda_away is not None]

    avg_lam_h = sum(lam_h_vals) / len(lam_h_vals) if lam_h_vals else None
    avg_lam_a = sum(lam_a_vals) / len(lam_a_vals) if lam_a_vals else None

    avg_goals = sum(r.home_goals + r.away_goals for r in rows) / n

    lam_error = None
    if avg_lam_h is not None and avg_lam_a is not None:
        lam_error = (avg_lam_h + avg_lam_a) - avg_goals

    high_score = [r for r in rows if r.home_goals + r.away_goals >= 5]
    high_missed = sum(1 for r in high_score if not r.hit3)

    return EvaluationSummary(
        total_matches=n,
        top1_hits=t1_hits,
        top3_hits=t3_hits,
        top1_accuracy=round(t1_hits / n * 100, 1),
        top3_accuracy=round(t3_hits / n * 100, 1),
        avg_lambda_home=round(avg_lam_h, 2) if avg_lam_h else None,
        avg_lambda_away=round(avg_lam_a, 2) if avg_lam_a else None,
        avg_actual_goals=round(avg_goals, 2),
        lambda_error=round(lam_error, 2) if lam_error is not None else None,
        high_score_matches=len(high_score),
        high_score_top3_missed=high_missed,
        result_accuracy=round(result_hits / n * 100, 1),
    )


def format_report_text(rows: list[ScoreRow], summary: EvaluationSummary) -> str:
    """
    Format the evaluation report as a plain-text table (for console/log output).

    Returns a multi-line string suitable for printing or writing to a log file.
    """
    lines = []
    header = f"{'#':>3} {'Match':28s} {'Score':>5} {'Top1':>5} {'Top3':30s} {'H@1':>4} {'H@3':>4} {'lamH':>6} {'lamA':>6}"
    lines.append(header)
    lines.append("=" * 105)

    for r in rows:
        top3_str = " / ".join(r.top3_scores[:3]) if r.top3_scores else "?"
        lam_h_str = f"{r.lambda_home:.2f}" if r.lambda_home is not None else "  -"
        lam_a_str = f"{r.lambda_away:.2f}" if r.lambda_away is not None else "  -"
        lines.append(
            f"{r.index:3d} {r.match_label:28s} {r.actual_score:>5} {r.top1_score:>5} "
            f"{top3_str:30s} {'Y' if r.hit1 else 'N':>4} {'Y' if r.hit3 else 'N':>4} "
            f"{lam_h_str:>6} {lam_a_str:>6}"
        )

    lines.append("")
    lines.append(f"  Top1 Accuracy:  {summary.top1_hits}/{summary.total_matches} = {summary.top1_accuracy}%")
    lines.append(f"  Top3 Accuracy:  {summary.top3_hits}/{summary.total_matches} = {summary.top3_accuracy}%")
    if summary.lambda_error is not None:
        label = "OVER" if summary.lambda_error > 0 else "UNDER"
        lines.append(f"  Lambda Error:   {summary.lambda_error:+.2f} ({label}-estimate)")
    if summary.result_accuracy is not None:
        lines.append(f"  Result Accuracy:{summary.result_accuracy}%")
    lines.append(f"  High-score (5g+) Top3 missed: {summary.high_score_top3_missed}/{summary.high_score_matches}")

    return "\n".join(lines)


def evaluate_from_database(db_path: str = "worldcup_ai.db") -> tuple[list[ScoreRow], EvaluationSummary]:
    """
    Convenience function: load all finished matches from the database,
    build ScoreRows, and compute the summary.

    Args:
        db_path: path to SQLite database
    Returns:
        (rows, summary) tuple
    """
    import sqlite3, json

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT m.id, m.home_score, m.away_score, m.kickoff_time,
               ht.name, at.name,
               p.predicted_score, p.top_scores, p.predicted_result,
               p.home_win_probability, p.draw_probability, p.away_win_probability,
               p.model_breakdown
        FROM matches m
        JOIN teams ht ON m.home_team_id = ht.id
        JOIN teams at ON m.away_team_id = at.id
        LEFT JOIN predictions p ON m.id = p.match_id
        WHERE m.home_score IS NOT NULL AND m.away_score IS NOT NULL
        ORDER BY m.kickoff_time ASC
    """)
    db_rows = cur.fetchall()
    conn.close()

    rows = []
    for r in db_rows:
        (mid, hs, aws, ko, hn, an, ps, top_json, pr, hwp, dp, awp, mb_json) = r
        hs = int(hs) if hs is not None else -1
        aws = int(aws) if aws is not None else -1
        actual = "Home Win" if hs > aws else ("Draw" if hs == aws else "Away Win")
        top_scores = json.loads(top_json or "[]")
        mb = json.loads(mb_json or "{}")
        gm = mb.get("goal_model", {})
        row = build_score_row(
            match_id=mid, home_team=hn, away_team=an,
            home_score=hs, away_score=aws, top_scores=top_scores,
            predicted_result=pr or "", actual_result=actual,
            lambda_home=gm.get("lambda_home"), lambda_away=gm.get("lambda_away"),
            draw_probability=dp,
        )
        rows.append(row)

    summary = compute_summary(rows)
    return rows, summary


# ── Runnable entry point ──────────────────────────────
if __name__ == "__main__":
    rows, summary = evaluate_from_database()
    print(format_report_text(rows, summary))
    print(f"\n  [Evaluation module ready — import from app.services.evaluation]")
