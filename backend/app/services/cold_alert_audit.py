from __future__ import annotations

import csv
import html
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.services.worldcup_historical_audit import _rows_for_run, _summarize, _to_audit_rows, latest_run_for_years


COLD_ALERT_BUCKETS = (
    ("0-30", 0, 30),
    ("30-40", 30, 40),
    ("40-45", 40, 45),
    ("45-55", 45, 55),
    ("55-65", 55, 65),
    ("65+", 65, None),
)


FILTER_THRESHOLDS = (55, 65)


def _pct(numerator: int | float, denominator: int | float) -> float:
    return round(numerator / denominator * 100, 2) if denominator else 0.0


def _draw_accuracy(rows: list) -> float:
    predicted_draws = [row for row in rows if row.predicted_result == "Draw"]
    if not predicted_draws:
        return 0.0
    return _pct(sum(row.actual_result == "Draw" for row in predicted_draws), len(predicted_draws))


def _bucket_analysis(rows: list) -> list[dict]:
    output = []
    for label, lower, upper in COLD_ALERT_BUCKETS:
        selected = [row for row in rows if row.upset_probability >= lower and (upper is None or row.upset_probability < upper)]
        summary = _summarize(selected)
        output.append(
            {
                "upset_bucket": label,
                "matches": summary["total_matches"],
                "result_accuracy": summary["result_accuracy"],
                "score_accuracy": summary["score_accuracy"],
                "draw_accuracy": _draw_accuracy(selected),
                "predicted_draws": sum(row.predicted_result == "Draw" for row in selected),
                "actual_draws": sum(row.actual_result == "Draw" for row in selected),
                "roi": summary["cumulative_roi"],
                "profit_units": summary["profit_units"],
                "roi_sample_size": summary["roi_sample_size"],
            }
        )
    return output


def _filter_analysis(rows: list) -> list[dict]:
    baseline = _summarize(rows)
    output = [
        {
            "strategy": "AI_all_recommendations",
            "filter_rule": "none",
            "matches": baseline["total_matches"],
            "result_accuracy": baseline["result_accuracy"],
            "score_accuracy": baseline["score_accuracy"],
            "draw_accuracy": _draw_accuracy(rows),
            "roi": baseline["cumulative_roi"],
            "profit_units": baseline["profit_units"],
            "roi_sample_size": baseline["roi_sample_size"],
        }
    ]
    for threshold in FILTER_THRESHOLDS:
        selected = [row for row in rows if row.upset_probability < threshold]
        summary = _summarize(selected)
        output.append(
            {
                "strategy": f"filter_upset_gte_{threshold}",
                "filter_rule": f"upset_probability < {threshold}",
                "matches": summary["total_matches"],
                "result_accuracy": summary["result_accuracy"],
                "score_accuracy": summary["score_accuracy"],
                "draw_accuracy": _draw_accuracy(selected),
                "roi": summary["cumulative_roi"],
                "profit_units": summary["profit_units"],
                "roi_sample_size": summary["roi_sample_size"],
            }
        )
    return output


def _best_roi_bucket(bucket_rows: list[dict]) -> dict | None:
    valid = [row for row in bucket_rows if row["matches"] and row["roi"] is not None]
    return max(valid, key=lambda row: row["roi"], default=None)


def _conclusion(report: dict) -> dict:
    overall = report["summary"]
    cautious = next((row for row in report["upset_bucket_analysis"] if row["upset_bucket"] == "45-55"), None)
    over_55 = [row for row in report["upset_bucket_analysis"] if row["upset_bucket"] in {"55-65", "65+"}]
    over_55_matches = sum(row["matches"] for row in over_55)
    over_55_hits = 0
    for row in report["matches"]:
        if row["upset_probability"] >= 55 and row["result_hit"]:
            over_55_hits += 1
    over_55_accuracy = _pct(over_55_hits, over_55_matches)
    best_roi = _best_roi_bucket(report["upset_bucket_analysis"])
    return {
        "overall_ai_result_accuracy": overall["result_accuracy"],
        "cautious_45_55_accuracy": None if not cautious else cautious["result_accuracy"],
        "cautious_45_55_matches": 0 if not cautious else cautious["matches"],
        "cautious_45_55_obviously_below_overall": bool(cautious and cautious["result_accuracy"] + 5 < overall["result_accuracy"]),
        "upset_55_plus_matches": over_55_matches,
        "upset_55_plus_accuracy": over_55_accuracy,
        "filter_55_plus_recommended": bool(over_55_matches and over_55_accuracy + 5 < overall["result_accuracy"]),
        "best_roi_bucket": None if not best_roi else best_roi["upset_bucket"],
        "best_roi": None if not best_roi else best_roi["roi"],
        "roi_note": "ROI is unavailable when no rows pass time-safe pre-match odds validation." if not best_roi else "ok",
    }


def build_cold_alert_audit(db: Session, years: list[int]) -> dict:
    run = latest_run_for_years(db, years)
    if run is None:
        raise RuntimeError(f"No backtest run found for years={years}. Run historical audit first.")
    rows = _to_audit_rows(_rows_for_run(db, run.id))
    report = {
        "metadata": {
            "run_id": run.id,
            "years": years,
            "scope": "2018 and 2022 FIFA World Cup cold alert audit",
            "model_change": "none",
            "note": "This audit only reads existing historical backtest rows. It does not modify models, weights, algorithms, confidence, upset, or recommendation logic.",
        },
        "summary": _summarize(rows),
        "upset_bucket_analysis": _bucket_analysis(rows),
        "filter_analysis": _filter_analysis(rows),
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
    summary = report["summary"]
    conclusion = report["conclusion"]
    cards = [
        ("Total Matches", summary["total_matches"]),
        ("AI Result Accuracy", f"{summary['result_accuracy']}%"),
        ("AI Score Accuracy", f"{summary['score_accuracy']}%"),
        ("45-55 Accuracy", f"{conclusion['cautious_45_55_accuracy']}%"),
        ("55+ Accuracy", f"{conclusion['upset_55_plus_accuracy']}%"),
    ]
    card_html = "".join(f"<div class='card'><span>{html.escape(str(label))}</span><strong>{html.escape(str(value))}</strong></div>" for label, value in cards)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Cold Alert Audit</title>
  <style>
    :root {{ color-scheme: dark; font-family:'Segoe UI',sans-serif; background:#07111f; color:#e7eef9; }}
    body {{ margin:0; padding:32px; background:radial-gradient(circle at top left,#1e3a8a,#07111f 42%,#040711); }}
    h1 {{ margin:0 0 8px; font-size:30px; }}
    h2 {{ margin-top:30px; color:#93c5fd; }}
    .note {{ color:#a8b8ca; margin-bottom:24px; }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:14px; }}
    .card {{ border:1px solid rgba(148,163,184,.22); border-radius:18px; padding:18px; background:rgba(15,23,42,.72); }}
    .card span {{ display:block; color:#9fb3c8; font-size:13px; }}
    .card strong {{ display:block; margin-top:10px; font-size:24px; color:#f8fafc; }}
    table {{ width:100%; border-collapse:collapse; margin-top:12px; background:rgba(15,23,42,.68); }}
    th,td {{ padding:10px 11px; border-bottom:1px solid rgba(148,163,184,.16); text-align:left; font-size:13px; }}
    th {{ color:#bfdbfe; background:rgba(30,41,59,.92); }}
  </style>
</head>
<body>
  <h1>Cold Alert Audit</h1>
  <p class="note">只读审计：按冷门预警区间统计 2018+2022 世界杯回测表现，不修改任何模型或预测逻辑。</p>
  <section class="cards">{card_html}</section>
  <h2>Final Conclusion</h2>{_html_table([conclusion])}
  <h2>Upset Bucket</h2>{_html_table(report['upset_bucket_analysis'])}
  <h2>Filter Analysis</h2>{_html_table(report['filter_analysis'])}
</body>
</html>
"""


def write_cold_alert_audit_outputs(report: dict, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = (
        [{"section": "summary", **report["summary"]}]
        + [{"section": "upset_bucket", **row} for row in report["upset_bucket_analysis"]]
        + [{"section": "filter", **row} for row in report["filter_analysis"]]
        + [{"section": "conclusion", **report["conclusion"]}]
    )
    paths = {
        "cold_alert_audit_csv": output_dir / "cold_alert_audit.csv",
        "cold_alert_bucket_analysis_csv": output_dir / "cold_alert_bucket_analysis.csv",
        "cold_alert_summary_json": output_dir / "cold_alert_summary.json",
        "cold_alert_dashboard_html": output_dir / "cold_alert_dashboard.html",
    }
    _write_csv(paths["cold_alert_audit_csv"], rows)
    _write_csv(paths["cold_alert_bucket_analysis_csv"], report["upset_bucket_analysis"])
    paths["cold_alert_summary_json"].write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["cold_alert_dashboard_html"].write_text(_dashboard_html(report), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}
