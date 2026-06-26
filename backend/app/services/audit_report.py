from __future__ import annotations

import csv
import html
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import Match
from app.services.statistics import actual_market_result, settled_matches, settle_match, sporttery_hot_pick


CONFIDENCE_BUCKETS = [
    ("0-40", 0, 40),
    ("40-50", 40, 50),
    ("50-60", 50, 60),
    ("60-70", 60, 70),
    ("70-80", 70, 80),
    ("80+", 80, None),
]

UPSET_BUCKETS = [
    ("0-20", 0, 20),
    ("20-40", 20, 40),
    ("40-50", 40, 50),
    ("50-60", 50, 60),
    ("60-70", 60, 70),
    ("70+", 70, None),
]

FILTER_STRATEGIES = [
    ("A_all_matches", None),
    ("B_filter_upset_gt_50", 50),
    ("C_filter_upset_gt_55", 55),
    ("D_filter_upset_gt_60", 60),
    ("E_filter_upset_gt_65", 65),
]

TOP_CONFIDENCE_BUCKETS = [
    ("Top 10%", 0.10),
    ("Top 20%", 0.20),
    ("Top 30%", 0.30),
    ("Top 50%", 0.50),
    ("All Matches", 1.00),
]


@dataclass(frozen=True)
class AuditRow:
    match_id: int
    competition: str
    kickoff_time: str
    home_team: str
    away_team: str
    confidence: float
    upset_probability: float
    predicted_result: str
    actual_result: str
    result_hit: bool
    predicted_score: str
    actual_score: str
    score_hit: bool
    market_type: str
    handicap: str
    predicted_market_result: str
    actual_market_result: str
    market_hit: bool
    hot_pick: str | None
    model_hot_pick: str
    conflict: bool | None
    profit: float
    roi: float


def _load_finished_matches(db: Session) -> list[Match]:
    rows = db.scalars(
        select(Match)
        .where(Match.status == "finished")
        .options(
            joinedload(Match.home_team),
            joinedload(Match.away_team),
            joinedload(Match.odds),
            joinedload(Match.prediction),
        )
        .order_by(Match.kickoff_time.asc())
    ).unique().all()
    return settled_matches(rows)


def _model_hot_pick(match: Match) -> str:
    probabilities = {
        "Home Win": match.prediction.home_win_probability,
        "Draw": match.prediction.draw_probability,
        "Away Win": match.prediction.away_win_probability,
    }
    return max(probabilities, key=probabilities.get)


def _to_audit_rows(matches: Iterable[Match]) -> list[AuditRow]:
    rows: list[AuditRow] = []
    for match in matches:
        settlement = settle_match(match)
        hot_pick = sporttery_hot_pick(match)
        model_hot_pick = _model_hot_pick(match)
        rows.append(
            AuditRow(
                match_id=match.id,
                competition=match.competition,
                kickoff_time=match.kickoff_time.isoformat(),
                home_team=match.home_team.name,
                away_team=match.away_team.name,
                confidence=float(match.prediction.confidence),
                upset_probability=float(match.prediction.upset_probability),
                predicted_result=match.prediction.predicted_result,
                actual_result=settlement["actual_result"],
                result_hit=bool(settlement["result_hit"]),
                predicted_score=match.prediction.predicted_score,
                actual_score=f"{match.home_score}-{match.away_score}",
                score_hit=bool(settlement["score_hit"]),
                market_type=match.prediction.market_type,
                handicap=match.prediction.handicap,
                predicted_market_result=match.prediction.predicted_market_result,
                actual_market_result=actual_market_result(match),
                market_hit=bool(settlement["market_hit"]),
                hot_pick=hot_pick,
                model_hot_pick=model_hot_pick,
                conflict=None if hot_pick is None else hot_pick != model_hot_pick,
                profit=float(settlement["profit"]),
                roi=float(settlement["roi"]),
            )
        )
    return rows


def _pct(numerator: int | float, denominator: int | float) -> float:
    return round((numerator / denominator * 100) if denominator else 0.0, 2)


def _summarize(rows: list[AuditRow]) -> dict:
    total = len(rows)
    result_hits = sum(row.result_hit for row in rows)
    score_hits = sum(row.score_hit for row in rows)
    handicap_rows = [row for row in rows if row.market_type == "HHAD"]
    handicap_hits = sum(row.market_hit for row in handicap_rows)
    profit = sum(row.profit for row in rows)
    roi_values = [row.roi for row in rows]
    return {
        "total_matches": total,
        "result_hits": result_hits,
        "result_accuracy": _pct(result_hits, total),
        "score_hits": score_hits,
        "score_accuracy": _pct(score_hits, total),
        "handicap_matches": len(handicap_rows),
        "handicap_hits": handicap_hits,
        "handicap_accuracy": _pct(handicap_hits, len(handicap_rows)),
        "average_roi": round(sum(roi_values) / total, 2) if total else 0.0,
        "cumulative_profit": round(profit, 4),
        "cumulative_roi": round((profit / total * 100) if total else 0.0, 2),
    }


def _bucket_rows(rows: list[AuditRow], buckets: list[tuple[str, float, float | None]], field: str) -> list[dict]:
    output = []
    for label, lower, upper in buckets:
        bucket = [
            row
            for row in rows
            if getattr(row, field) >= lower and (upper is None or getattr(row, field) < upper)
        ]
        summary = _summarize(bucket)
        output.append(
            {
                "range": label,
                "matches": summary["total_matches"],
                "result_accuracy": summary["result_accuracy"],
                "score_accuracy": summary["score_accuracy"],
                "roi": summary["cumulative_roi"],
            }
        )
    return output


def _filter_strategy_report(rows: list[AuditRow]) -> list[dict]:
    output = []
    for strategy, threshold in FILTER_STRATEGIES:
        retained = rows if threshold is None else [row for row in rows if row.upset_probability <= threshold]
        summary = _summarize(retained)
        output.append(
            {
                "strategy": strategy,
                "filter_rule": "none" if threshold is None else f"upset_probability <= {threshold}",
                "matches": summary["total_matches"],
                "accuracy": summary["result_accuracy"],
                "score_accuracy": summary["score_accuracy"],
                "roi": summary["cumulative_roi"],
            }
        )
    return output


def _conflict_report(rows: list[AuditRow]) -> dict:
    comparable = [row for row in rows if row.conflict is not None]
    conflict_rows = [row for row in comparable if row.conflict]
    normal_rows = [row for row in comparable if not row.conflict]
    conflict_summary = _summarize(conflict_rows)
    normal_summary = _summarize(normal_rows)
    return {
        "comparable_matches": len(comparable),
        "conflict_matches": conflict_summary["total_matches"],
        "conflict_accuracy": conflict_summary["result_accuracy"],
        "conflict_roi": conflict_summary["cumulative_roi"],
        "normal_matches": normal_summary["total_matches"],
        "normal_accuracy": normal_summary["result_accuracy"],
        "normal_roi": normal_summary["cumulative_roi"],
    }


def _top_confidence_report(rows: list[AuditRow]) -> list[dict]:
    ranked = sorted(rows, key=lambda row: row.confidence, reverse=True)
    output = []
    for label, share in TOP_CONFIDENCE_BUCKETS:
        count = len(ranked) if share >= 1 else math.ceil(len(ranked) * share)
        selected = ranked[:count]
        summary = _summarize(selected)
        output.append(
            {
                "top_confidence_bucket": label,
                "matches": summary["total_matches"],
                "accuracy": summary["result_accuracy"],
                "score_accuracy": summary["score_accuracy"],
                "roi": summary["cumulative_roi"],
            }
        )
    return output


def build_audit_report(db: Session) -> dict:
    rows = _to_audit_rows(_load_finished_matches(db))
    return {
        "metadata": {
            "source": "real_database_finished_matches",
            "model_change": "none",
            "note": "Audit only reads settled historical predictions; no model weights or prediction logic are modified.",
        },
        "overall": _summarize(rows),
        "confidence_buckets": _bucket_rows(rows, CONFIDENCE_BUCKETS, "confidence"),
        "upset_buckets": _bucket_rows(rows, UPSET_BUCKETS, "upset_probability"),
        "filter_strategies": _filter_strategy_report(rows),
        "market_model_conflict": _conflict_report(rows),
        "top_confidence": _top_confidence_report(rows),
        "matches": [row.__dict__ for row in rows],
    }


def _csv_rows(report: dict) -> list[dict]:
    rows: list[dict] = []

    overall = report["overall"]
    rows.append(
        {
            "section": "overall",
            "bucket": "Total Matches",
            "matches": overall["total_matches"],
            "result_accuracy": overall["result_accuracy"],
            "score_accuracy": overall["score_accuracy"],
            "handicap_accuracy": overall["handicap_accuracy"],
            "roi": overall["cumulative_roi"],
            "average_roi": overall["average_roi"],
            "note": "",
        }
    )

    for item in report["confidence_buckets"]:
        rows.append({"section": "confidence", "bucket": item["range"], "matches": item["matches"], "result_accuracy": item["result_accuracy"], "score_accuracy": item["score_accuracy"], "handicap_accuracy": "", "roi": item["roi"], "average_roi": "", "note": ""})
    for item in report["upset_buckets"]:
        rows.append({"section": "upset", "bucket": item["range"], "matches": item["matches"], "result_accuracy": item["result_accuracy"], "score_accuracy": item["score_accuracy"], "handicap_accuracy": "", "roi": item["roi"], "average_roi": "", "note": ""})
    for item in report["filter_strategies"]:
        rows.append({"section": "filter_strategy", "bucket": item["strategy"], "matches": item["matches"], "result_accuracy": item["accuracy"], "score_accuracy": item["score_accuracy"], "handicap_accuracy": "", "roi": item["roi"], "average_roi": "", "note": item["filter_rule"]})
    conflict = report["market_model_conflict"]
    rows.append({"section": "market_model_conflict", "bucket": "conflict", "matches": conflict["conflict_matches"], "result_accuracy": conflict["conflict_accuracy"], "score_accuracy": "", "handicap_accuracy": "", "roi": conflict["conflict_roi"], "average_roi": "", "note": ""})
    rows.append({"section": "market_model_conflict", "bucket": "normal", "matches": conflict["normal_matches"], "result_accuracy": conflict["normal_accuracy"], "score_accuracy": "", "handicap_accuracy": "", "roi": conflict["normal_roi"], "average_roi": "", "note": ""})
    for item in report["top_confidence"]:
        rows.append({"section": "top_confidence", "bucket": item["top_confidence_bucket"], "matches": item["matches"], "result_accuracy": item["accuracy"], "score_accuracy": item["score_accuracy"], "handicap_accuracy": "", "roi": item["roi"], "average_roi": "", "note": ""})
    return rows


def _table(headers: list[str], rows: list[dict]) -> str:
    head = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body = []
    for row in rows:
        body.append(
            "<tr>"
            + "".join(f"<td>{html.escape(str(row.get(header, '')))}</td>" for header in headers)
            + "</tr>"
        )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _html_dashboard(report: dict) -> str:
    overall = report["overall"]
    cards = [
        ("Total Matches", overall["total_matches"]),
        ("Result Accuracy", f"{overall['result_accuracy']}%"),
        ("Score Accuracy", f"{overall['score_accuracy']}%"),
        ("Handicap Accuracy", f"{overall['handicap_accuracy']}%"),
        ("Average ROI", f"{overall['average_roi']}%"),
        ("Cumulative ROI", f"{overall['cumulative_roi']}%"),
    ]
    card_html = "".join(
        f"<div class='card'><span>{html.escape(label)}</span><strong>{html.escape(str(value))}</strong></div>"
        for label, value in cards
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Historical Backtest Audit Report</title>
  <style>
    :root {{ color-scheme: dark; font-family: 'Segoe UI', sans-serif; background: #08111f; color: #e5edf7; }}
    body {{ margin: 0; padding: 32px; background: radial-gradient(circle at top left, #12345b, #08111f 42%, #050914); }}
    h1 {{ margin: 0 0 8px; font-size: 30px; }}
    h2 {{ margin-top: 28px; color: #93c5fd; }}
    .note {{ color: #9fb3c8; margin-bottom: 24px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; }}
    .card {{ border: 1px solid rgba(148,163,184,.22); border-radius: 18px; padding: 18px; background: rgba(15,23,42,.72); box-shadow: 0 18px 45px rgba(0,0,0,.22); }}
    .card span {{ display: block; color: #9fb3c8; font-size: 13px; }}
    .card strong {{ display: block; margin-top: 10px; font-size: 26px; color: #f8fafc; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 12px; overflow: hidden; border-radius: 14px; background: rgba(15,23,42,.68); }}
    th, td {{ padding: 11px 12px; border-bottom: 1px solid rgba(148,163,184,.16); text-align: left; font-size: 13px; }}
    th {{ color: #bfdbfe; background: rgba(30,41,59,.9); }}
    tr:hover td {{ background: rgba(59,130,246,.08); }}
  </style>
</head>
<body>
  <h1>历史回测统计分析 Audit Report</h1>
  <p class="note">只读取真实数据库中已结算比赛；不修改模型、权重、ELO、Poisson、Monte Carlo、Dixon-Coles 或推荐逻辑。</p>
  <section class="cards">{card_html}</section>
  <h2>信心指数分层</h2>
  {_table(['range', 'matches', 'result_accuracy', 'score_accuracy', 'roi'], report['confidence_buckets'])}
  <h2>冷门概率分层</h2>
  {_table(['range', 'matches', 'result_accuracy', 'score_accuracy', 'roi'], report['upset_buckets'])}
  <h2>过滤策略验证</h2>
  {_table(['strategy', 'filter_rule', 'matches', 'accuracy', 'score_accuracy', 'roi'], report['filter_strategies'])}
  <h2>市场热门 vs 模型热门冲突</h2>
  {_table(['comparable_matches', 'conflict_matches', 'conflict_accuracy', 'conflict_roi', 'normal_matches', 'normal_accuracy', 'normal_roi'], [report['market_model_conflict']])}
  <h2>推荐等级验证</h2>
  {_table(['top_confidence_bucket', 'matches', 'accuracy', 'score_accuracy', 'roi'], report['top_confidence'])}
</body>
</html>
"""


def write_audit_outputs(report: dict, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "audit_report.json"
    csv_path = output_dir / "audit_report.csv"
    html_path = output_dir / "audit_dashboard.html"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_rows = _csv_rows(report)
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "section",
                "bucket",
                "matches",
                "result_accuracy",
                "score_accuracy",
                "handicap_accuracy",
                "roi",
                "average_roi",
                "note",
            ],
        )
        writer.writeheader()
        writer.writerows(csv_rows)
    html_path.write_text(_html_dashboard(report), encoding="utf-8")
    return {
        "json": str(json_path),
        "csv": str(csv_path),
        "html": str(html_path),
    }
