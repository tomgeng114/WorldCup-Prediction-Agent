from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    BacktestPrediction,
    BacktestRun,
    InternationalBacktestPrediction,
    InternationalBacktestRun,
    InternationalMatch,
    InternationalOdds,
    WorldCupMatch,
    WorldCupOdds,
)


RESULTS = ("Home Win", "Draw", "Away Win")
CALIBRATION_BINS = (
    ("50%-55%", 0.50, 0.55),
    ("55%-60%", 0.55, 0.60),
    ("60%-65%", 0.60, 0.65),
    ("65%-70%", 0.65, 0.70),
    ("70%-75%", 0.70, 0.75),
    ("75%-80%", 0.75, 0.80),
    ("80%+", 0.80, 1.01),
)


@dataclass
class PredictionCase:
    dataset: str
    match_id: int
    match_date: object
    home_team: str
    away_team: str
    probabilities: dict[str, float]
    market_probabilities: dict[str, float]
    odds: dict[str, float]
    actual_result: str


class IdentityCalibrator:
    name = "raw"

    def predict(self, probability: float) -> float:
        return _clip_probability(probability)


class PlattCalibrator:
    name = "platt"

    def __init__(self) -> None:
        self.weight = 1.0
        self.bias = 0.0
        self.mean = 0.0
        self.std = 1.0

    def fit(self, samples: list[tuple[float, int]]) -> None:
        if not samples:
            return
        xs = [_logit(probability) for probability, _ in samples]
        self.mean = sum(xs) / len(xs)
        variance = sum((x - self.mean) ** 2 for x in xs) / len(xs)
        self.std = max(math.sqrt(variance), 1e-6)
        normalized = [((x - self.mean) / self.std, y) for x, (_, y) in zip(xs, samples, strict=False)]

        weight = 1.0
        bias = _logit(sum(y for _, y in normalized) / len(normalized))
        learning_rate = 0.03
        l2 = 0.002
        for _ in range(2500):
            grad_w = 0.0
            grad_b = 0.0
            for x, y in normalized:
                pred = _sigmoid(weight * x + bias)
                grad_w += (pred - y) * x
                grad_b += pred - y
            grad_w = grad_w / len(normalized) + l2 * weight
            grad_b = grad_b / len(normalized)
            weight -= learning_rate * grad_w
            bias -= learning_rate * grad_b
        self.weight = weight
        self.bias = bias

    def predict(self, probability: float) -> float:
        x = (_logit(probability) - self.mean) / self.std
        return _clip_probability(_sigmoid(self.weight * x + self.bias))


class IsotonicCalibrator:
    name = "isotonic"

    def __init__(self) -> None:
        self.thresholds: list[float] = []
        self.values: list[float] = []

    def fit(self, samples: list[tuple[float, int]]) -> None:
        if not samples:
            return
        blocks = [
            {"min": p, "max": p, "sum": float(y), "weight": 1.0}
            for p, y in sorted(samples, key=lambda item: item[0])
        ]
        index = 0
        while index < len(blocks) - 1:
            current = blocks[index]["sum"] / blocks[index]["weight"]
            next_value = blocks[index + 1]["sum"] / blocks[index + 1]["weight"]
            if current <= next_value:
                index += 1
                continue
            blocks[index]["max"] = blocks[index + 1]["max"]
            blocks[index]["sum"] += blocks[index + 1]["sum"]
            blocks[index]["weight"] += blocks[index + 1]["weight"]
            del blocks[index + 1]
            if index:
                index -= 1

        self.thresholds = [block["max"] for block in blocks]
        self.values = [
            _clip_probability((block["sum"] + 0.5) / (block["weight"] + 1.0))
            for block in blocks
        ]

    def predict(self, probability: float) -> float:
        if not self.thresholds:
            return _clip_probability(probability)
        for threshold, value in zip(self.thresholds, self.values, strict=False):
            if probability <= threshold:
                return value
        return self.values[-1]


def _clip_probability(value: float) -> float:
    return min(0.999, max(0.001, float(value)))


def _logit(value: float) -> float:
    value = _clip_probability(value)
    return math.log(value / (1 - value))


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1 / (1 + z)
    z = math.exp(value)
    return z / (1 + z)


def _normalize(values: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, value) for value in values.values())
    if total <= 0:
        return {result: 1 / len(values) for result in values}
    return {result: max(0.0, value) / total for result, value in values.items()}


def _market_probabilities(odds: dict[str, float]) -> dict[str, float]:
    implied = {result: 1 / price for result, price in odds.items()}
    return _normalize(implied)


def _pick(probabilities: dict[str, float]) -> str:
    return max(probabilities, key=probabilities.get)


def _brier(probabilities: dict[str, float], actual: str) -> float:
    return sum((probabilities[result] - (1.0 if result == actual else 0.0)) ** 2 for result in RESULTS)


def _profit(pick: str, actual: str, odds: float, stake: float = 1.0) -> float:
    return stake * (odds - 1) if pick == actual else -stake


def _kelly_stake(probability: float, odds: float, fraction: float = 0.25) -> float:
    edge = probability * odds - 1
    raw_fraction = max(0.0, edge / max(odds - 1, 1e-9))
    return min(raw_fraction * fraction, 1.0)


def _max_drawdown(values: list[float]) -> float:
    peak = 0.0
    drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = min(drawdown, value - peak)
    return round(drawdown, 4)


def _latest_world_cup_run(db: Session) -> BacktestRun | None:
    return db.scalar(
        select(BacktestRun)
        .where(BacktestRun.years == "2018,2022")
        .order_by(BacktestRun.created_at.desc(), BacktestRun.id.desc())
    )


def _latest_international_run(db: Session, run_name: str) -> InternationalBacktestRun | None:
    return db.scalar(
        select(InternationalBacktestRun)
        .where(InternationalBacktestRun.run_name == run_name)
        .order_by(InternationalBacktestRun.created_at.desc(), InternationalBacktestRun.id.desc())
    )


def _load_world_cup_cases(db: Session) -> list[PredictionCase]:
    run = _latest_world_cup_run(db)
    if not run:
        return []
    rows = db.execute(
        select(BacktestPrediction, WorldCupMatch, WorldCupOdds)
        .join(WorldCupMatch, BacktestPrediction.match_id == WorldCupMatch.id)
        .join(WorldCupOdds, WorldCupOdds.match_id == WorldCupMatch.id)
        .where(BacktestPrediction.run_id == run.id)
        .order_by(WorldCupMatch.match_date.asc(), WorldCupMatch.id.asc())
    ).all()
    cases = []
    for prediction, match, odds in rows:
        prices = {
            "Home Win": odds.home_win_odds,
            "Draw": odds.draw_odds,
            "Away Win": odds.away_win_odds,
        }
        cases.append(
            PredictionCase(
                dataset="WorldCup",
                match_id=match.id,
                match_date=match.match_date,
                home_team=match.home_team,
                away_team=match.away_team,
                probabilities={
                    "Home Win": prediction.home_win_probability,
                    "Draw": prediction.draw_probability,
                    "Away Win": prediction.away_win_probability,
                },
                market_probabilities=_market_probabilities(prices),
                odds=prices,
                actual_result=prediction.actual_result,
            )
        )
    return cases


def _load_international_cases(db: Session, dataset: str, run_name: str) -> list[PredictionCase]:
    run = _latest_international_run(db, run_name)
    if not run:
        return []
    rows = db.execute(
        select(InternationalBacktestPrediction, InternationalMatch, InternationalOdds)
        .join(InternationalMatch, InternationalBacktestPrediction.match_id == InternationalMatch.id)
        .join(InternationalOdds, InternationalOdds.match_id == InternationalMatch.id)
        .where(InternationalBacktestPrediction.run_id == run.id)
        .order_by(InternationalMatch.match_date.asc(), InternationalMatch.id.asc())
    ).all()
    cases = []
    for prediction, match, odds in rows:
        prices = {
            "Home Win": odds.home_win_odds,
            "Draw": odds.draw_odds,
            "Away Win": odds.away_win_odds,
        }
        cases.append(
            PredictionCase(
                dataset=dataset,
                match_id=match.id,
                match_date=match.match_date,
                home_team=match.home_team,
                away_team=match.away_team,
                probabilities={
                    "Home Win": prediction.home_win_probability,
                    "Draw": prediction.draw_probability,
                    "Away Win": prediction.away_win_probability,
                },
                market_probabilities=_market_probabilities(prices),
                odds=prices,
                actual_result=prediction.actual_result,
            )
        )
    return cases


def _calibration_samples(cases: list[PredictionCase]) -> list[tuple[float, int]]:
    samples = []
    for case in cases:
        for result in RESULTS:
            samples.append((case.probabilities[result], int(case.actual_result == result)))
    return samples


def _apply_calibrator(probabilities: dict[str, float], calibrator: IdentityCalibrator | PlattCalibrator | IsotonicCalibrator) -> dict[str, float]:
    calibrated = {result: calibrator.predict(probabilities[result]) for result in RESULTS}
    return _normalize(calibrated)


def _confidence_rows(
    cases: list[PredictionCase],
    calibrator: IdentityCalibrator | PlattCalibrator | IsotonicCalibrator,
    edge_only: bool = False,
) -> list[dict]:
    rows = []
    for case in cases:
        probabilities = _apply_calibrator(case.probabilities, calibrator)
        if edge_only:
            edges = {result: probabilities[result] - case.market_probabilities[result] for result in RESULTS}
            pick = max(RESULTS, key=lambda result: edges[result])
            if edges[pick] < 0.15:
                continue
            edge = edges[pick]
        else:
            pick = _pick(probabilities)
            edge = probabilities[pick] - case.market_probabilities[pick]
        rows.append(
            {
                "confidence": probabilities[pick],
                "hit": int(pick == case.actual_result),
                "pick": pick,
                "actual": case.actual_result,
                "edge": edge,
                "odds": case.odds[pick],
            }
        )
    return rows


def _reliability(rows: list[dict]) -> dict:
    bins = []
    total = len(rows)
    weighted_error = 0.0
    max_error = 0.0
    covered = 0
    below_50 = sum(1 for row in rows if row["confidence"] < 0.50)
    for label, lower, upper in CALIBRATION_BINS:
        bucket = [row for row in rows if lower <= row["confidence"] < upper]
        sample_size = len(bucket)
        avg_prediction = sum(row["confidence"] for row in bucket) / sample_size if sample_size else 0.0
        actual_hit_rate = sum(row["hit"] for row in bucket) / sample_size if sample_size else 0.0
        bias = avg_prediction - actual_hit_rate
        abs_error = abs(bias)
        covered += sample_size
        weighted_error += abs_error * sample_size
        max_error = max(max_error, abs_error)
        bins.append(
            {
                "range": label,
                "sample_size": sample_size,
                "actual_hit_rate": round(actual_hit_rate * 100, 2) if sample_size else 0.0,
                "avg_predicted_probability": round(avg_prediction * 100, 2) if sample_size else 0.0,
                "bias": round(bias * 100, 2) if sample_size else 0.0,
            }
        )
    return {
        "sample_size": total,
        "below_50_count": below_50,
        "covered_by_requested_bins": covered,
        "bins": bins,
        "ece": round(weighted_error / covered * 100, 2) if covered else 0.0,
        "mce": round(max_error * 100, 2),
    }


def _probability_metrics(cases: list[PredictionCase], calibrator: IdentityCalibrator | PlattCalibrator | IsotonicCalibrator) -> dict:
    if not cases:
        return {"brier_score": None, "reliability": _reliability([]), "edge_15_reliability": _reliability([])}
    brier = sum(_brier(_apply_calibrator(case.probabilities, calibrator), case.actual_result) for case in cases) / len(cases)
    return {
        "brier_score": round(brier, 4),
        "reliability": _reliability(_confidence_rows(cases, calibrator, edge_only=False)),
        "edge_15_reliability": _reliability(_confidence_rows(cases, calibrator, edge_only=True)),
    }


def _roi(cases: list[PredictionCase], calibrator: IdentityCalibrator | PlattCalibrator | IsotonicCalibrator, edge_threshold: float = 0.15) -> dict:
    bets = []
    unit_profit = 0.0
    kelly_profit = 0.0
    unit_curve = []
    kelly_curve = []
    unit_hits = 0
    kelly_stake_total = 0.0
    for case in cases:
        probabilities = _apply_calibrator(case.probabilities, calibrator)
        edges = {result: probabilities[result] - case.market_probabilities[result] for result in RESULTS}
        pick = max(RESULTS, key=lambda result: edges[result])
        edge = edges[pick]
        if edge < edge_threshold:
            continue
        odds = case.odds[pick]
        hit = pick == case.actual_result
        profit = _profit(pick, case.actual_result, odds, 1.0)
        unit_profit += profit
        unit_hits += int(hit)
        unit_curve.append(unit_profit)
        stake = _kelly_stake(probabilities[pick], odds)
        kelly_profit += _profit(pick, case.actual_result, odds, stake)
        kelly_stake_total += stake
        kelly_curve.append(kelly_profit)
        bets.append({"pick": pick, "edge": edge, "probability": probabilities[pick], "hit": hit})
    return {
        "matches": len(bets),
        "hits": unit_hits,
        "hit_rate": round(unit_hits / len(bets) * 100, 2) if bets else 0.0,
        "unit_profit": round(unit_profit, 4),
        "unit_roi": round(unit_profit / len(bets) * 100, 2) if bets else None,
        "kelly_profit": round(kelly_profit, 4),
        "kelly_stake": round(kelly_stake_total, 4),
        "kelly_roi": round(kelly_profit / kelly_stake_total * 100, 2) if kelly_stake_total else None,
        "max_drawdown": _max_drawdown(unit_curve),
    }


def _time_split(cases: list[PredictionCase], train_ratio: float = 0.60) -> tuple[list[PredictionCase], list[PredictionCase]]:
    ordered = sorted(cases, key=lambda case: (case.match_date, case.match_id))
    split_at = max(1, min(len(ordered) - 1, int(len(ordered) * train_ratio))) if len(ordered) > 1 else len(ordered)
    return ordered[:split_at], ordered[split_at:]


def _fit_calibrators(train_cases: list[PredictionCase]) -> dict[str, IdentityCalibrator | PlattCalibrator | IsotonicCalibrator]:
    samples = _calibration_samples(train_cases)
    platt = PlattCalibrator()
    platt.fit(samples)
    isotonic = IsotonicCalibrator()
    isotonic.fit(samples)
    return {
        "raw": IdentityCalibrator(),
        "platt": platt,
        "isotonic": isotonic,
    }


def _dataset_report(name: str, cases: list[PredictionCase]) -> dict:
    train, holdout = _time_split(cases)
    calibrators = _fit_calibrators(train)
    full_raw = _probability_metrics(cases, calibrators["raw"])
    edge_raw_rows = _confidence_rows(cases, calibrators["raw"], edge_only=True)
    holdout_payload = {}
    for method, calibrator in calibrators.items():
        holdout_payload[method] = {
            "probability_metrics": _probability_metrics(holdout, calibrator),
            "edge_15_roi": _roi(holdout, calibrator),
        }
    return {
        "dataset": name,
        "sample_size": len(cases),
        "train_size": len(train),
        "holdout_size": len(holdout),
        "raw_full_sample": full_raw,
        "edge_15_overconfidence": {
            "sample_size": len(edge_raw_rows),
            "avg_probability": round(sum(row["confidence"] for row in edge_raw_rows) / len(edge_raw_rows) * 100, 2) if edge_raw_rows else 0.0,
            "actual_hit_rate": round(sum(row["hit"] for row in edge_raw_rows) / len(edge_raw_rows) * 100, 2) if edge_raw_rows else 0.0,
            "bias": round(
                (sum(row["confidence"] for row in edge_raw_rows) / len(edge_raw_rows) - sum(row["hit"] for row in edge_raw_rows) / len(edge_raw_rows)) * 100,
                2,
            ) if edge_raw_rows else 0.0,
        },
        "holdout_comparison": holdout_payload,
    }


def _write_report(path: Path, payload: dict) -> None:
    lines = [
        "# Phase 6 Probability Calibration Report",
        "",
        "## 目标",
        "",
        "- 暂停新增赛事、赔率库和 UI。",
        "- 检查模型概率是否过度自信。",
        "- 对比 Raw、Platt Scaling、Isotonic Regression 在时间切分 holdout 上的 ROI。",
        "",
    ]
    for name, report in payload["datasets"].items():
        raw = report["raw_full_sample"]
        edge = report["edge_15_overconfidence"]
        lines.extend(
            [
                f"## {name}",
                "",
                f"- 样本数：{report['sample_size']}",
                f"- 校准训练集：{report['train_size']}",
                f"- Holdout：{report['holdout_size']}",
                f"- Raw Brier Score：{raw['brier_score']}",
                f"- Raw ECE：{raw['reliability']['ece']}%",
                f"- Raw MCE：{raw['reliability']['mce']}%",
                f"- Raw 推荐概率低于50%数量：{raw['reliability']['below_50_count']}",
                f"- Raw 推荐概率落入指定区间数量：{raw['reliability']['covered_by_requested_bins']}",
                f"- Edge>=15% 样本数：{edge['sample_size']}",
                f"- Edge>=15% 平均预测概率：{edge['avg_probability']}%",
                f"- Edge>=15% 实际命中率：{edge['actual_hit_rate']}%",
                f"- Edge>=15% 概率偏差：{edge['bias']}%",
                "",
                "### Reliability Diagram 数据",
                "",
                "| 概率区间 | 样本数 | 实际命中率 | 平均预测概率 | 偏差 |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for row in raw["reliability"]["bins"]:
            lines.append(
                f"| {row['range']} | {row['sample_size']} | {row['actual_hit_rate']}% | "
                f"{row['avg_predicted_probability']}% | {row['bias']}% |"
            )
        lines.extend(
            [
                "",
                "### Edge>=15% Reliability Diagram 数据",
                "",
                f"- Edge>=15% 概率低于50%数量：{raw['edge_15_reliability']['below_50_count']}",
                f"- Edge>=15% 概率落入指定区间数量：{raw['edge_15_reliability']['covered_by_requested_bins']}",
                f"- Edge>=15% ECE：{raw['edge_15_reliability']['ece']}%",
                f"- Edge>=15% MCE：{raw['edge_15_reliability']['mce']}%",
                "",
                "| 概率区间 | 样本数 | 实际命中率 | 平均预测概率 | 偏差 |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for row in raw["edge_15_reliability"]["bins"]:
            lines.append(
                f"| {row['range']} | {row['sample_size']} | {row['actual_hit_rate']}% | "
                f"{row['avg_predicted_probability']}% | {row['bias']}% |"
            )
        lines.extend(
            [
                "",
                "### Holdout 校准前后 ROI",
                "",
                "| 方法 | Brier | ECE | MCE | Edge>=15%场数 | 命中率 | 单位ROI | Kelly ROI | 最大回撤 |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for method, item in report["holdout_comparison"].items():
            probability_metrics = item["probability_metrics"]
            roi = item["edge_15_roi"]
            lines.append(
                f"| {method} | {probability_metrics['brier_score']} | "
                f"{probability_metrics['reliability']['ece']}% | {probability_metrics['reliability']['mce']}% | "
                f"{roi['matches']} | {roi['hit_rate']}% | {roi['unit_roi']}% | {roi['kelly_roi']}% | {roi['max_drawdown']} |"
            )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def run_phase6_calibration(db: Session) -> dict:
    datasets = {
        "WorldCup": _load_world_cup_cases(db),
        "UEFA": _load_international_cases(db, "UEFA", "Phase5 UEFA WCQ"),
        "CONMEBOL": _load_international_cases(db, "CONMEBOL", "Phase5 CONMEBOL WCQ"),
    }
    reports = {name: _dataset_report(name, cases) for name, cases in datasets.items()}
    payload = {
        "method": "time_split_calibration",
        "bins": [label for label, _, _ in CALIBRATION_BINS],
        "datasets": reports,
    }
    reports_dir = Path(__file__).resolve().parents[2] / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "phase6_calibration_report.md"
    json_path = reports_dir / "phase6_calibration_report.json"
    _write_report(report_path, payload)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["report_path"] = str(report_path)
    payload["json_path"] = str(json_path)
    return payload
