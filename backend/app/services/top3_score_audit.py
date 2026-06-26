from __future__ import annotations

import csv
import html
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BacktestPrediction, Match, Prediction, WorldCupMatch
from app.services.statistics import actual_result
from app.services.worldcup_historical_audit import _audit_stage, latest_run_for_years


STAGE_ORDER = ("Group Stage", "Round of 16", "Quarter-finals", "Semi-finals", "Third-place match", "Final")


@dataclass(frozen=True)
class Top3ScoreRow:
    sample: str
    match_id: int
    match_date: str
    stage: str
    match: str
    predicted_result: str
    actual_result: str
    actual_score: str
    top1_score: str
    top2_score: str | None
    top3_score: str | None
    top3_available: bool
    result_hit: bool
    top1_hit: bool
    top2_coverage_hit: bool
    top3_coverage_hit: bool


def _parse_live_top_scores(prediction: Prediction) -> list[str]:
    scores: list[str] = []
    try:
        payload = json.loads(prediction.top_scores or "[]")
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict) and item.get("score"):
                    scores.append(str(item["score"]))
                elif isinstance(item, str):
                    scores.append(item)
    except json.JSONDecodeError:
        pass
    if not scores and prediction.backup_scores:
        scores = [part.strip() for part in prediction.backup_scores.split("|") if part.strip()]
    if prediction.predicted_score and prediction.predicted_score not in scores:
        scores.insert(0, prediction.predicted_score)
    return scores[:3]


def _historical_rows(db: Session, years: list[int]) -> list[Top3ScoreRow]:
    run = latest_run_for_years(db, years)
    if run is None:
        raise RuntimeError(f"No backtest run found for years={years}. Run historical audit first.")
    raw_rows = list(
        db.execute(
            select(BacktestPrediction, WorldCupMatch)
            .join(WorldCupMatch, BacktestPrediction.match_id == WorldCupMatch.id)
            .where(BacktestPrediction.run_id == run.id)
            .order_by(WorldCupMatch.match_date.asc(), WorldCupMatch.id.asc())
        ).all()
    )
    rows: list[Top3ScoreRow] = []
    for prediction, match in raw_rows:
        actual_score = f"{match.home_score}-{match.away_score}"
        rows.append(
            Top3ScoreRow(
                sample=str(match.tournament_year),
                match_id=match.id,
                match_date=match.match_date.isoformat(),
                stage=_audit_stage(match.stage),
                match=f"{match.home_team} vs {match.away_team}",
                predicted_result=prediction.predicted_result,
                actual_result=match.result,
                actual_score=actual_score,
                top1_score=prediction.predicted_score,
                top2_score=None,
                top3_score=None,
                top3_available=False,
                result_hit=prediction.predicted_result == match.result,
                top1_hit=prediction.predicted_score == actual_score,
                top2_coverage_hit=False,
                top3_coverage_hit=False,
            )
        )
    return rows


def _live_rows(db: Session) -> list[Top3ScoreRow]:
    raw_rows = list(
        db.execute(
            select(Match, Prediction)
            .join(Prediction, Prediction.match_id == Match.id)
            .where(Match.status == "finished")
            .where(Match.home_score.is_not(None))
            .where(Match.away_score.is_not(None))
            .order_by(Match.kickoff_time.asc(), Match.id.asc())
        ).all()
    )
    rows: list[Top3ScoreRow] = []
    for match, prediction in raw_rows:
        actual = actual_result(match)
        actual_score = f"{match.home_score}-{match.away_score}"
        top_scores = _parse_live_top_scores(prediction)
        top1 = top_scores[0] if top_scores else prediction.predicted_score
        top2 = top_scores[1] if len(top_scores) > 1 else None
        top3 = top_scores[2] if len(top_scores) > 2 else None
        top3_available = len(top_scores) >= 3
        rows.append(
            Top3ScoreRow(
                sample="2026_live",
                match_id=match.id,
                match_date=match.kickoff_time.isoformat(),
                stage=match.stage or "Unknown",
                match=f"{match.home_team.name} vs {match.away_team.name}",
                predicted_result=prediction.predicted_result,
                actual_result=actual,
                actual_score=actual_score,
                top1_score=top1,
                top2_score=top2,
                top3_score=top3,
                top3_available=top3_available,
                result_hit=prediction.predicted_result == actual,
                top1_hit=top1 == actual_score,
                top2_coverage_hit=actual_score in top_scores[:2],
                top3_coverage_hit=actual_score in top_scores[:3],
            )
        )
    return rows


def _pct(numerator: int | float, denominator: int | float) -> float:
    return round(numerator / denominator * 100, 2) if denominator else 0.0


def _top1_summary(rows: list[Top3ScoreRow]) -> dict:
    hits = sum(row.top1_hit for row in rows)
    return {"metric": "Top1 Score", "matches": len(rows), "hits": hits, "accuracy": _pct(hits, len(rows))}


def _top3_summary(rows: list[Top3ScoreRow]) -> dict:
    available = [row for row in rows if row.top3_available]
    hits = sum(row.top3_coverage_hit for row in available)
    return {
        "metric": "Top3 Score",
        "matches": len(available),
        "hits": hits,
        "accuracy": _pct(hits, len(available)),
        "unavailable_matches": len(rows) - len(available),
    }


def _conditional_summary(rows: list[Top3ScoreRow]) -> list[dict]:
    result_correct = [row for row in rows if row.result_hit]
    result_correct_with_top3 = [row for row in result_correct if row.top3_available]
    top1_hits = sum(row.top1_hit for row in result_correct)
    top3_hits = sum(row.top3_coverage_hit for row in result_correct_with_top3)
    return [
        {
            "metric": "Top1 Accuracy Given Correct Result",
            "matches": len(result_correct),
            "hits": top1_hits,
            "accuracy": _pct(top1_hits, len(result_correct)),
        },
        {
            "metric": "Top3 Accuracy Given Correct Result",
            "matches": len(result_correct_with_top3),
            "hits": top3_hits,
            "accuracy": _pct(top3_hits, len(result_correct_with_top3)),
            "unavailable_matches": len(result_correct) - len(result_correct_with_top3),
        },
    ]


def _stage_analysis(rows: list[Top3ScoreRow]) -> list[dict]:
    stages = list(STAGE_ORDER) + sorted({row.stage for row in rows if row.stage not in STAGE_ORDER})
    output = []
    for stage in stages:
        selected = [row for row in rows if row.stage == stage]
        if not selected:
            continue
        top3_available = [row for row in selected if row.top3_available]
        output.append(
            {
                "stage": stage,
                "matches": len(selected),
                "top1_accuracy": _pct(sum(row.top1_hit for row in selected), len(selected)),
                "top3_available_matches": len(top3_available),
                "top3_accuracy": _pct(sum(row.top3_coverage_hit for row in top3_available), len(top3_available)),
                "top3_unavailable_matches": len(selected) - len(top3_available),
            }
        )
    return output


def _coverage(rows: list[Top3ScoreRow]) -> list[dict]:
    available = [row for row in rows if row.top3_available]
    return [
        {
            "coverage_level": "Top1",
            "matches": len(rows),
            "hits": sum(row.top1_hit for row in rows),
            "accuracy": _pct(sum(row.top1_hit for row in rows), len(rows)),
        },
        {
            "coverage_level": "Top2",
            "matches": len(available),
            "hits": sum(row.top2_coverage_hit for row in available),
            "accuracy": _pct(sum(row.top2_coverage_hit for row in available), len(available)),
            "unavailable_matches": len(rows) - len(available),
        },
        {
            "coverage_level": "Top3",
            "matches": len(available),
            "hits": sum(row.top3_coverage_hit for row in available),
            "accuracy": _pct(sum(row.top3_coverage_hit for row in available), len(available)),
            "unavailable_matches": len(rows) - len(available),
        },
    ]


def _hit_scores(rows: list[Top3ScoreRow]) -> list[dict]:
    counts = Counter(row.actual_score for row in rows if row.top3_coverage_hit)
    return [{"score": score, "hit_count": count} for score, count in counts.most_common()]


def _near_misses(rows: list[Top3ScoreRow]) -> list[dict]:
    counts = Counter(
        (
            " | ".join(score for score in [row.top1_score, row.top2_score, row.top3_score] if score),
            row.actual_score,
        )
        for row in rows
        if row.top3_available and not row.top1_hit and row.top3_coverage_hit
    )
    return [
        {"predicted_top3": top3, "actual_score": actual, "count": count}
        for (top3, actual), count in counts.most_common()
    ]


def _conclusion(report: dict) -> dict:
    top1 = report["top1_vs_top3"][0]
    top3 = report["top1_vs_top3"][1]
    conditional_top3 = report["conditional_top3"][1]
    improvement = None if top3["matches"] == 0 else round(top3["accuracy"] - top1["accuracy"], 2)
    return {
        "current_13_28_is_top1_accuracy": True,
        "top1_accuracy": top1["accuracy"],
        "top3_accuracy": top3["accuracy"],
        "top3_available_matches": top3["matches"],
        "top3_unavailable_matches": top3["unavailable_matches"],
        "top3_accuracy_given_correct_result": conditional_top3["accuracy"],
        "top3_improvement_over_top1": improvement,
        "front_end_should_emphasize_top3": bool(top3["matches"] and top3["accuracy"] > top1["accuracy"]),
        "historical_top3_note": "2018/2022 backtest rows only store Top1 predicted_score. Top3 coverage is calculated only for rows with stored top_scores, currently 2026 live settled matches.",
    }


def build_top3_score_audit(db: Session) -> dict:
    rows = _historical_rows(db, [2018, 2022]) + _live_rows(db)
    report = {
        "metadata": {
            "scope": "2018 World Cup, 2022 World Cup, 2026 finished live matches",
            "model_change": "none",
            "note": "This audit only reads stored score predictions. It does not modify models, weights, algorithms, Poisson, Monte Carlo, Dixon-Coles, confidence, upset, or recommendation logic.",
        },
        "sample_sizes": {
            "total_matches": len(rows),
            "top3_available_matches": sum(row.top3_available for row in rows),
            "top3_unavailable_matches": sum(not row.top3_available for row in rows),
        },
        "top1_vs_top3": [_top1_summary(rows), _top3_summary(rows)],
        "conditional_top3": _conditional_summary(rows),
        "stage_analysis": _stage_analysis(rows),
        "coverage_analysis": _coverage(rows),
        "hit_score_frequency": _hit_scores(rows),
        "near_miss_analysis": _near_misses(rows),
        "matches": [row.__dict__ for row in rows],
    }
    report["conclusion"] = _conclusion(report)
    return report


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def _html_table(rows: list[dict]) -> str:
    if not rows:
        return "<p>No data</p>"
    headers: list[str] = []
    for row in rows:
        for key in row:
            if key not in headers:
                headers.append(key)
    head = "".join(f"<th>{html.escape(str(header))}</th>" for header in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(row.get(header, '')))}</td>" for header in headers) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _dashboard_html(report: dict) -> str:
    conclusion = report["conclusion"]
    sizes = report["sample_sizes"]
    cards = [
        ("Total Matches", sizes["total_matches"]),
        ("Top3 Available", sizes["top3_available_matches"]),
        ("Top1 Accuracy", f"{conclusion['top1_accuracy']}%"),
        ("Top3 Accuracy", f"{conclusion['top3_accuracy']}%"),
        ("Top3 Improvement", conclusion["top3_improvement_over_top1"]),
    ]
    card_html = "".join(f"<div class='card'><span>{html.escape(str(label))}</span><strong>{html.escape(str(value))}</strong></div>" for label, value in cards)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Top3 Score Audit</title>
  <style>
    :root {{ color-scheme: dark; font-family:'Segoe UI',sans-serif; background:#07111f; color:#e7eef9; }}
    body {{ margin:0; padding:32px; background:radial-gradient(circle at top left,#7c3aed,#07111f 42%,#040711); }}
    h1 {{ margin:0 0 8px; font-size:30px; }}
    h2 {{ margin-top:30px; color:#c4b5fd; }}
    .note {{ color:#a8b8ca; margin-bottom:24px; }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:14px; }}
    .card {{ border:1px solid rgba(148,163,184,.22); border-radius:18px; padding:18px; background:rgba(15,23,42,.72); }}
    .card span {{ display:block; color:#9fb3c8; font-size:13px; }}
    .card strong {{ display:block; margin-top:10px; font-size:24px; color:#f8fafc; }}
    table {{ width:100%; border-collapse:collapse; margin-top:12px; background:rgba(15,23,42,.68); }}
    th,td {{ padding:10px 11px; border-bottom:1px solid rgba(148,163,184,.16); text-align:left; font-size:13px; }}
    th {{ color:#ddd6fe; background:rgba(30,41,59,.92); }}
  </style>
</head>
<body>
  <h1>Top3 Score Audit</h1>
  <p class="note">只读审计：统计 Top1/Top3 比分覆盖，不修改任何模型、权重、算法或预测逻辑。</p>
  <section class="cards">{card_html}</section>
  <h2>Final Conclusion</h2>{_html_table([conclusion])}
  <h2>Top1 vs Top3</h2>{_html_table(report['top1_vs_top3'])}
  <h2>Conditional Top3</h2>{_html_table(report['conditional_top3'])}
  <h2>Stage Analysis</h2>{_html_table(report['stage_analysis'])}
  <h2>Coverage Analysis</h2>{_html_table(report['coverage_analysis'])}
  <h2>Hit Score Frequency</h2>{_html_table(report['hit_score_frequency'])}
  <h2>Near Miss Analysis</h2>{_html_table(report['near_miss_analysis'])}
</body>
</html>
"""


def write_top3_score_outputs(report: dict, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_rows = (
        [{"section": "top1_vs_top3", **row} for row in report["top1_vs_top3"]]
        + [{"section": "conditional_top3", **row} for row in report["conditional_top3"]]
        + [{"section": "stage_analysis", **row} for row in report["stage_analysis"]]
        + [{"section": "coverage_analysis", **row} for row in report["coverage_analysis"]]
        + [{"section": "conclusion", **report["conclusion"]}]
    )
    paths = {
        "top3_score_audit_csv": output_dir / "top3_score_audit.csv",
        "top3_score_summary_json": output_dir / "top3_score_summary.json",
        "top3_score_dashboard_html": output_dir / "top3_score_dashboard.html",
        "top3_score_matches_csv": output_dir / "top3_score_matches.csv",
        "top3_near_misses_csv": output_dir / "top3_near_misses.csv",
    }
    _write_csv(paths["top3_score_audit_csv"], summary_rows)
    _write_csv(paths["top3_score_matches_csv"], report["matches"])
    _write_csv(paths["top3_near_misses_csv"], report["near_miss_analysis"])
    paths["top3_score_summary_json"].write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["top3_score_dashboard_html"].write_text(_dashboard_html(report), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}
