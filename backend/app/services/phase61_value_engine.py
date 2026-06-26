from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.services.phase6_calibration import (
    RESULTS,
    PredictionCase,
    _load_international_cases,
    _load_world_cup_cases,
)


DEFAULT_MIN_MODEL_PROBABILITY = 0.35
DEFAULT_MIN_MARKET_PROBABILITY = 0.10
DEFAULT_EDGE_THRESHOLD = 0.15
EV_THRESHOLDS = (0.00, 0.05, 0.10, 0.15)
OUTCOME_LABELS = {
    "Home Win": "主胜",
    "Draw": "平局",
    "Away Win": "客胜",
}


def _profit(pick: str, actual: str, odds: float, stake: float = 1.0) -> float:
    return stake * (odds - 1) if pick == actual else -stake


def _kelly_stake(probability: float, odds: float, fraction: float = 0.25) -> float:
    edge = probability * odds - 1
    raw_fraction = max(0.0, edge / max(odds - 1, 1e-9))
    return min(raw_fraction * fraction, 1.0)


def _max_drawdown(curve: list[float]) -> float:
    peak = 0.0
    drawdown = 0.0
    for value in curve:
        peak = max(peak, value)
        drawdown = min(drawdown, value - peak)
    return round(drawdown, 4)


def _strategy_stats(bets: list[dict]) -> dict:
    unit_profit = 0.0
    kelly_profit = 0.0
    kelly_stake = 0.0
    hits = 0
    unit_curve = []
    kelly_curve = []
    for bet in bets:
        odds = bet["odds"]
        probability = bet["model_probability"]
        hit = bet["hit"]
        unit_profit += _profit(bet["pick"], bet["actual"], odds, 1.0)
        stake = _kelly_stake(probability, odds)
        kelly_profit += _profit(bet["pick"], bet["actual"], odds, stake)
        kelly_stake += stake
        hits += int(hit)
        unit_curve.append(unit_profit)
        kelly_curve.append(kelly_profit)
    return {
        "bets": len(bets),
        "hits": hits,
        "hit_rate": round(hits / len(bets) * 100, 2) if bets else 0.0,
        "unit_profit": round(unit_profit, 4),
        "unit_roi": round(unit_profit / len(bets) * 100, 2) if bets else None,
        "kelly_profit": round(kelly_profit, 4),
        "kelly_stake": round(kelly_stake, 4),
        "kelly_roi": round(kelly_profit / kelly_stake * 100, 2) if kelly_stake else None,
        "max_drawdown": _max_drawdown(unit_curve),
        "kelly_max_drawdown": _max_drawdown(kelly_curve),
    }


def _outcome_stats(bets: list[dict]) -> dict:
    return {
        outcome: _strategy_stats([bet for bet in bets if bet["pick"] == outcome])
        for outcome in RESULTS
    }


def _best_edge_bet(case: PredictionCase) -> dict:
    edges = {
        result: case.probabilities[result] - case.market_probabilities[result]
        for result in RESULTS
    }
    pick = max(RESULTS, key=lambda result: edges[result])
    odds = case.odds[pick]
    probability = case.probabilities[pick]
    return {
        "match_id": case.match_id,
        "date": case.match_date.isoformat(sep=" ") if hasattr(case.match_date, "isoformat") else str(case.match_date),
        "home_team": case.home_team,
        "away_team": case.away_team,
        "pick": pick,
        "actual": case.actual_result,
        "model_probability": probability,
        "market_probability": case.market_probabilities[pick],
        "edge": edges[pick],
        "ev": probability * odds - 1,
        "odds": odds,
        "hit": pick == case.actual_result,
    }


def _best_ev_bet(case: PredictionCase) -> dict:
    evs = {
        result: case.probabilities[result] * case.odds[result] - 1
        for result in RESULTS
    }
    pick = max(RESULTS, key=lambda result: evs[result])
    probability = case.probabilities[pick]
    return {
        "match_id": case.match_id,
        "date": case.match_date.isoformat(sep=" ") if hasattr(case.match_date, "isoformat") else str(case.match_date),
        "home_team": case.home_team,
        "away_team": case.away_team,
        "pick": pick,
        "actual": case.actual_result,
        "model_probability": probability,
        "market_probability": case.market_probabilities[pick],
        "edge": probability - case.market_probabilities[pick],
        "ev": evs[pick],
        "odds": case.odds[pick],
        "hit": pick == case.actual_result,
    }


def _passes_common_filters(
    bet: dict,
    min_model_probability: float,
    min_market_probability: float,
) -> bool:
    return (
        bet["model_probability"] >= min_model_probability
        and bet["market_probability"] >= min_market_probability
    )


def _strategy_payload(name: str, bets: list[dict]) -> dict:
    return {
        "name": name,
        "summary": _strategy_stats(bets),
        "by_outcome": _outcome_stats(bets),
    }


def _dataset_report(
    name: str,
    cases: list[PredictionCase],
    min_model_probability: float,
    min_market_probability: float,
) -> dict:
    edge_candidates = [_best_edge_bet(case) for case in cases]
    ev_candidates = [_best_ev_bet(case) for case in cases]

    edge_raw = [bet for bet in edge_candidates if bet["edge"] >= DEFAULT_EDGE_THRESHOLD]
    edge_filtered = [
        bet for bet in edge_candidates
        if bet["edge"] >= DEFAULT_EDGE_THRESHOLD
        and _passes_common_filters(bet, min_model_probability, min_market_probability)
        and bet["ev"] > 0
    ]

    strategies = {
        "edge_15_raw": _strategy_payload("Edge>=15% 原始", edge_raw),
        "edge_15_filtered": _strategy_payload("Edge>=15% + 最低概率/市场概率/EV过滤", edge_filtered),
    }
    for threshold in EV_THRESHOLDS:
        bets = [
            bet for bet in ev_candidates
            if bet["ev"] > threshold
            and _passes_common_filters(bet, min_model_probability, min_market_probability)
        ]
        key = f"ev_gt_{int(threshold * 100)}"
        strategies[key] = _strategy_payload(f"EV>{threshold * 100:.0f}% + 最低概率/市场概率过滤", bets)

    best_by_roi = max(
        (payload for payload in strategies.values() if payload["summary"]["unit_roi"] is not None),
        key=lambda payload: payload["summary"]["unit_roi"],
        default=None,
    )
    return {
        "dataset": name,
        "sample_size": len(cases),
        "filters": {
            "min_model_probability": min_model_probability,
            "min_market_probability": min_market_probability,
            "edge_threshold": DEFAULT_EDGE_THRESHOLD,
            "ev_thresholds": list(EV_THRESHOLDS),
        },
        "strategies": strategies,
        "best_strategy_by_unit_roi": best_by_roi,
    }


def _format_roi(value: float | None) -> str:
    return "None" if value is None else f"{value}%"


def _append_strategy_table(lines: list[str], report: dict) -> None:
    lines.extend(
        [
            "| 策略 | 场数 | 命中率 | 单位ROI | Kelly ROI | 最大回撤 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for payload in report["strategies"].values():
        summary = payload["summary"]
        lines.append(
            f"| {payload['name']} | {summary['bets']} | {summary['hit_rate']}% | "
            f"{_format_roi(summary['unit_roi'])} | {_format_roi(summary['kelly_roi'])} | {summary['max_drawdown']} |"
        )


def _append_outcome_table(lines: list[str], payload: dict) -> None:
    lines.extend(
        [
            "| 结果 | 场数 | 命中率 | 单位ROI | Kelly ROI | 最大回撤 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for outcome, stats in payload["by_outcome"].items():
        lines.append(
            f"| {OUTCOME_LABELS[outcome]} | {stats['bets']} | {stats['hit_rate']}% | "
            f"{_format_roi(stats['unit_roi'])} | {_format_roi(stats['kelly_roi'])} | {stats['max_drawdown']} |"
        )


def _write_report(path: Path, payload: dict) -> None:
    lines = [
        "# Phase 6.1 Value Bet Engine Rewrite Report",
        "",
        "## 过滤规则",
        "",
        f"- Minimum Model Probability：{payload['filters']['min_model_probability'] * 100:.0f}%",
        f"- Market Probability Filter：{payload['filters']['min_market_probability'] * 100:.0f}%",
        "- EV = Model Probability × Decimal Odds - 1",
        "- 暂停新增赛事、赔率库和 UI；仅基于现有回测预测与真实赛前赔率。",
        "",
        "## 跨样本汇总",
        "",
        "| 策略 | 场数 | 命中率 | 单位ROI | 累计利润 |",
        "|---|---:|---:|---:|---:|",
    ]
    strategy_keys = ["edge_15_raw", "edge_15_filtered", "ev_gt_0", "ev_gt_5", "ev_gt_10", "ev_gt_15"]
    for key in strategy_keys:
        bets = 0
        hits = 0
        profit = 0.0
        label = ""
        for report in payload["datasets"].values():
            strategy = report["strategies"][key]
            summary = strategy["summary"]
            label = strategy["name"]
            bets += summary["bets"]
            hits += summary["hits"]
            profit += summary["unit_profit"]
        hit_rate = round(hits / bets * 100, 2) if bets else 0.0
        roi = round(profit / bets * 100, 2) if bets else None
        lines.append(f"| {label} | {bets} | {hit_rate}% | {_format_roi(roi)} | {round(profit, 4)} |")
    lines.append("")
    for name, report in payload["datasets"].items():
        lines.extend(
            [
                f"## {name}",
                "",
                f"- 样本数：{report['sample_size']}",
                "",
                "### 过滤前后与 EV 阈值对比",
                "",
            ]
        )
        _append_strategy_table(lines, report)
        lines.extend(["", "### Outcome Specific Threshold：Edge>=15% 过滤后", ""])
        _append_outcome_table(lines, report["strategies"]["edge_15_filtered"])
        lines.extend(["", "### Outcome Specific Threshold：EV>0% 过滤后", ""])
        _append_outcome_table(lines, report["strategies"]["ev_gt_0"])
        best = report["best_strategy_by_unit_roi"]
        lines.extend(
            [
                "",
                "### 判断",
                "",
                f"- 最佳单位ROI策略：{best['name'] if best else '无'}",
                f"- 最佳单位ROI：{_format_roi(best['summary']['unit_roi']) if best else 'None'}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def run_phase61_value_engine(
    db: Session,
    min_model_probability: float = DEFAULT_MIN_MODEL_PROBABILITY,
    min_market_probability: float = DEFAULT_MIN_MARKET_PROBABILITY,
) -> dict:
    datasets = {
        "WorldCup": _load_world_cup_cases(db),
        "UEFA": _load_international_cases(db, "UEFA", "Phase5 UEFA WCQ"),
        "CONMEBOL": _load_international_cases(db, "CONMEBOL", "Phase5 CONMEBOL WCQ"),
    }
    reports = {
        name: _dataset_report(name, cases, min_model_probability, min_market_probability)
        for name, cases in datasets.items()
    }
    payload = {
        "filters": {
            "min_model_probability": min_model_probability,
            "min_market_probability": min_market_probability,
            "edge_threshold": DEFAULT_EDGE_THRESHOLD,
            "ev_thresholds": list(EV_THRESHOLDS),
        },
        "datasets": reports,
    }
    reports_dir = Path(__file__).resolve().parents[2] / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "phase61_value_engine_report.md"
    json_path = reports_dir / "phase61_value_engine_report.json"
    _write_report(report_path, payload)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["report_path"] = str(report_path)
    payload["json_path"] = str(json_path)
    return payload
