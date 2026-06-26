from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.models import WorldCupMatch
from app.services.backtest_engine import (
    BacktestEngine,
    INITIAL_WEIGHTS,
    RESULTS,
    TeamState,
    _brier,
    _calibrated_top_scores,
    _dixon_coles_score_matrix,
    _optimize_weights,
    _result,
    _update_elo,
    _update_team_state,
)


YEARS = [2018, 2022]
GOAL_BUCKETS = ["0球", "1球", "2球", "3球", "4球", "5球", "6+球"]


def _pct(value: int | float, total: int | float) -> float:
    return round((value / total) * 100, 2) if total else 0.0


def _goal_bucket(total_goals: int) -> str:
    return "6+球" if total_goals >= 6 else f"{total_goals}球"


def _parse_score(score: str) -> tuple[int, int]:
    home, away = score.split("-", 1)
    return int(home), int(away)


def _top_scores(home_state: TeamState, away_state: TeamState, predicted_result: str, limit: int = 3) -> list[dict]:
    matrix = _calibrated_top_scores(
        _dixon_coles_score_matrix(home_state, away_state),
        predicted_result=predicted_result,
        limit=limit,
    )
    return [
        {
            "score": item["score"],
            "probability": round(item["probability"] * 100, 2),
        }
        for item in matrix[:limit]
    ]


def _result_metrics(rows: list[dict]) -> dict:
    total = len(rows)
    by_actual = {}
    for result in RESULTS:
        result_rows = [row for row in rows if row["actual_result"] == result]
        by_actual[result] = {
            "actual_count": len(result_rows),
            "correct_count": sum(1 for row in result_rows if row["result_hit"]),
            "hit_rate": _pct(sum(1 for row in result_rows if row["result_hit"]), len(result_rows)),
        }
    return {
        "total_matches": total,
        "correct_count": sum(1 for row in rows if row["result_hit"]),
        "total_hit_rate": _pct(sum(1 for row in rows if row["result_hit"]), total),
        "home_win_hit_rate": by_actual["Home Win"]["hit_rate"],
        "draw_hit_rate": by_actual["Draw"]["hit_rate"],
        "away_win_hit_rate": by_actual["Away Win"]["hit_rate"],
        "by_actual_result": by_actual,
        "brier_score": round(sum(row["brier_score"] for row in rows) / total, 4) if total else 0.0,
    }


def _score_metrics(rows: list[dict]) -> dict:
    exact_hits = 0
    top3_hits = 0
    plus_minus_one_hits = 0
    for row in rows:
        actual_home, actual_away = _parse_score(row["actual_score"])
        predicted_home, predicted_away = _parse_score(row["predicted_score"])
        top3_scores = [item["score"] for item in row["top3_scores"]]
        exact_hits += row["predicted_score"] == row["actual_score"]
        top3_hits += row["actual_score"] in top3_scores
        plus_minus_one_hits += (
            abs(predicted_home - actual_home) <= 1
            and abs(predicted_away - actual_away) <= 1
        )
    total = len(rows)
    return {
        "exact_score_hit_rate": _pct(exact_hits, total),
        "exact_score_hits": exact_hits,
        "top3_score_coverage": _pct(top3_hits, total),
        "top3_score_hits": top3_hits,
        "plus_minus_one_goal_hit_rate": _pct(plus_minus_one_hits, total),
        "plus_minus_one_goal_hits": plus_minus_one_hits,
    }


def _total_goals_metrics(rows: list[dict]) -> dict:
    predicted = Counter(_goal_bucket(row["predicted_total_goals"]) for row in rows)
    actual = Counter(_goal_bucket(row["actual_total_goals"]) for row in rows)
    total = len(rows)
    predicted_distribution = {
            bucket: {
                "count": predicted[bucket],
                "rate": _pct(predicted[bucket], total),
            }
            for bucket in GOAL_BUCKETS
        }
    actual_distribution = {
            bucket: {
                "count": actual[bucket],
                "rate": _pct(actual[bucket], total),
            }
            for bucket in GOAL_BUCKETS
        }
    distribution_error = round(
        sum(abs(predicted_distribution[bucket]["rate"] - actual_distribution[bucket]["rate"]) for bucket in GOAL_BUCKETS),
        2,
    )
    return {
        "predicted_distribution": predicted_distribution,
        "actual_distribution": actual_distribution,
        "distribution_error": distribution_error,
    }


def _draw_metrics(rows: list[dict]) -> dict:
    predicted_draws = [row for row in rows if row["predicted_result"] == "Draw"]
    actual_draws = [row for row in rows if row["actual_result"] == "Draw"]
    draw_hits = [row for row in predicted_draws if row["actual_result"] == "Draw"]
    return {
        "predicted_draw_rate": _pct(len(predicted_draws), len(rows)),
        "predicted_draw_count": len(predicted_draws),
        "actual_draw_rate": _pct(len(actual_draws), len(rows)),
        "actual_draw_count": len(actual_draws),
        "draw_hit_rate": _pct(len(draw_hits), len(predicted_draws)),
        "draw_hits": len(draw_hits),
    }


def _roi_metrics(rows: list[dict]) -> dict:
    # No verified historical Sporttery official odds are present in the local database.
    profits = [0.0 for _ in rows]
    peak = 0.0
    equity = 0.0
    max_drawdown = 0.0
    for profit in profits:
        equity += profit
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
    return {
        "odds_sample_size": 0,
        "stake": 0.0,
        "profit": 0.0,
        "cumulative_roi": None,
        "max_drawdown": round(max_drawdown, 4),
        "status": "无官方赛前体彩赔率样本，禁止用模拟赔率计算 ROI。",
    }


def _unavailable_odds_metrics(rows: list[dict]) -> dict:
    return {
        "sample_size": 0,
        "lowest_odds_hot_hit_rate": None,
        "ai_hit_rate": _result_metrics(rows)["total_hit_rate"],
        "ai_lead": None,
        "status": "历史库未保存 2018/2022 赛前体彩官方胜平负赔率，无法计算体彩热门命中率和领先值。",
    }


def _unavailable_handicap_metrics() -> dict:
    return {
        "sample_size": 0,
        "handicap_hit_rate": None,
        "status": "历史库未保存 2018/2022 体彩官方让球数和让球赔率，无法计算官方让球胜平负命中率。",
    }


def _summarize(rows: list[dict]) -> dict:
    return {
        "result_accuracy": _result_metrics(rows),
        "sporttery_hot_compare": _unavailable_odds_metrics(rows),
        "handicap_accuracy": _unavailable_handicap_metrics(),
        "score_prediction": _score_metrics(rows),
        "total_goals": _total_goals_metrics(rows),
        "draw_analysis": _draw_metrics(rows),
        "roi_analysis": _roi_metrics(rows),
    }


def run_report() -> dict:
    with SessionLocal() as db:
        matches = db.scalars(
            select(WorldCupMatch)
            .where(WorldCupMatch.tournament_year.in_(YEARS))
            .order_by(WorldCupMatch.match_date.asc(), WorldCupMatch.id.asc())
        ).all()

    if len(matches) != 128:
        raise RuntimeError(f"Expected 128 World Cup matches for 2018+2022, got {len(matches)}")

    engine = BacktestEngine(db=None)
    states: defaultdict[str, TeamState] = defaultdict(TeamState)
    component_scores: defaultdict[str, list[int]] = defaultdict(list)
    weights = dict(INITIAL_WEIGHTS)
    warmup_matches, weights = engine._warmup_states(states, 2018, component_scores, weights)
    rows: list[dict] = []

    for match in matches:
        home_state = states[match.home_team]
        away_state = states[match.away_team]
        prediction = engine._predict(match, states, weights)
        top3_scores = _top_scores(home_state, away_state, prediction.predicted_result, limit=3)
        actual_score = f"{match.home_score}-{match.away_score}"
        actual_result = _result(match.home_score, match.away_score)
        predicted_home, predicted_away = _parse_score(prediction.predicted_score)
        row = {
            "year": match.tournament_year,
            "date": match.match_date.isoformat(),
            "stage": match.stage,
            "home_team": match.home_team,
            "away_team": match.away_team,
            "predicted_result": prediction.predicted_result,
            "actual_result": actual_result,
            "result_hit": prediction.predicted_result == actual_result,
            "home_win_probability": round(prediction.probabilities["Home Win"] * 100, 2),
            "draw_probability": round(prediction.probabilities["Draw"] * 100, 2),
            "away_win_probability": round(prediction.probabilities["Away Win"] * 100, 2),
            "predicted_score": prediction.predicted_score,
            "top3_scores": top3_scores,
            "actual_score": actual_score,
            "predicted_total_goals": predicted_home + predicted_away,
            "actual_total_goals": match.total_goals,
            "brier_score": _brier(prediction.probabilities, actual_result),
            "weights": prediction.weights,
        }
        rows.append(row)

        for component, component_pick in prediction.component_predictions.items():
            component_scores[component].append(1 if component_pick == actual_result else 0)

        _update_elo(home_state, away_state, match.home_score, match.away_score)
        _update_team_state(home_state, match.home_score, match.away_score, match.stage)
        _update_team_state(away_state, match.away_score, match.home_score, match.stage)
        weights = _optimize_weights(component_scores, INITIAL_WEIGHTS)

    by_year = {
        str(year): _summarize([row for row in rows if row["year"] == year])
        for year in YEARS
    }
    report = {
        "title": "World Cup AI Predictor Pro 2018+2022 世界杯历史回测报告",
        "scope": {
            "years": YEARS,
            "matches": len(rows),
            "baseline_win_draw_loss_accuracy": 45.31,
            "pre_draw_calibration_accuracy": 55.47,
            "pre_draw_calibration_predicted_draw_rate": 7.03,
            "pre_draw_calibration_draw_hit_rate": 13.79,
        "data_source": "local world_cup_matches imported from openfootball/worldcup.json",
            "fifa_ranking_sources": [
                "backend/data/World_cup_2018_country.csv",
                "backend/data/fifa_ranking-2022-10-06.csv",
            ],
            "strict_pre_match": True,
            "warmup_matches": warmup_matches,
            "leakage_control": "按比赛时间顺序逐场预测，预测后才更新 ELO、近况和世界杯经验；不使用当前比赛或未来比赛赛后数据。",
            "odds_limitation": "本地历史库没有 2018/2022 赛前体彩官方赔率，因此体彩热门、官方让球盘、体彩赔率 ROI 不做模拟替代。",
        },
        "overall": _summarize(rows),
        "by_year": by_year,
        "sample_predictions": rows[:10],
    }
    return report


def write_markdown(report: dict, output_path: Path) -> None:
    overall = report["overall"]
    result = overall["result_accuracy"]
    score = overall["score_prediction"]
    goals = overall["total_goals"]
    draw = overall["draw_analysis"]
    hot = overall["sporttery_hot_compare"]
    handicap = overall["handicap_accuracy"]
    roi = overall["roi_analysis"]

    def display(value: object) -> object:
        return "不可计算" if value is None else value

    def goal_lines(distribution: dict) -> str:
        return "\n".join(
            f"| {bucket} | {payload['count']} | {payload['rate']}% |"
            for bucket, payload in distribution.items()
        )

    lines = [
        "# World Cup AI Predictor Pro 2018+2022 世界杯历史回测报告",
        "",
        "## 回测范围",
        f"- 年份：{', '.join(str(year) for year in report['scope']['years'])}",
        f"- 比赛数：{report['scope']['matches']} 场",
        f"- 优化前胜平负命中率：{report['scope']['baseline_win_draw_loss_accuracy']}%",
        f"- 严格赛前数据：{report['scope']['strict_pre_match']}",
        f"- Warm-up 场次：{report['scope']['warmup_matches']} 场，仅用于赛前状态初始化，不计入指标",
        f"- 防数据泄露：{report['scope']['leakage_control']}",
        f"- 赔率限制：{report['scope']['odds_limitation']}",
        "",
        "## 1. 胜平负命中率",
        f"- 主胜命中率：{result['home_win_hit_rate']}%",
        f"- 平局命中率：{result['draw_hit_rate']}%",
        f"- 客胜命中率：{result['away_win_hit_rate']}%",
        f"- 总命中率：{result['total_hit_rate']}% ({result['correct_count']}/{result['total_matches']})",
        f"- 较优化前变化：{round(result['total_hit_rate'] - report['scope']['baseline_win_draw_loss_accuracy'], 2)} 个百分点",
        f"- Brier Score：{result['brier_score']}",
        "",
        "## 2. 体彩热门对比",
        f"- 最低赔率热门命中率：{display(hot['lowest_odds_hot_hit_rate'])}",
        f"- AI命中率：{hot['ai_hit_rate']}%",
        f"- AI领先值：{display(hot['ai_lead'])}",
        f"- 状态：{hot['status']}",
        "",
        "## 3. 让球胜平负命中率",
        f"- 样本数：{handicap['sample_size']}",
        f"- 命中率：{display(handicap['handicap_hit_rate'])}",
        f"- 状态：{handicap['status']}",
        "",
        "## 4. 比分预测",
        f"- 精确比分命中率：{score['exact_score_hit_rate']}% ({score['exact_score_hits']}/{result['total_matches']})",
        f"- TOP3比分覆盖率：{score['top3_score_coverage']}% ({score['top3_score_hits']}/{result['total_matches']})",
        f"- ±1球命中率：{score['plus_minus_one_goal_hit_rate']}% ({score['plus_minus_one_goal_hits']}/{result['total_matches']})",
        "",
        "## 5. 总进球预测分布",
        f"- 总进球分布误差：{goals['distribution_error']} 个百分点（各进球档预测占比与真实占比绝对误差之和）",
        "### 预测分布",
        "| 总进球 | 场次 | 占比 |",
        "| --- | ---: | ---: |",
        goal_lines(goals["predicted_distribution"]),
        "",
        "### 真实分布",
        "| 总进球 | 场次 | 占比 |",
        "| --- | ---: | ---: |",
        goal_lines(goals["actual_distribution"]),
        "",
        "## 6. 平局分析",
        f"- 预测平局率：{draw['predicted_draw_rate']}% ({draw['predicted_draw_count']}/{result['total_matches']})",
        f"- 真实平局率：{draw['actual_draw_rate']}% ({draw['actual_draw_count']}/{result['total_matches']})",
        f"- 平局命中率：{draw['draw_hit_rate']}% ({draw['draw_hits']}/{draw['predicted_draw_count']})",
        "",
        "## Draw Calibration Report",
        f"- 校准前总命中率：{report['scope']['pre_draw_calibration_accuracy']}%",
        f"- 校准后总命中率：{result['total_hit_rate']}%",
        f"- 对总命中率影响：{round(result['total_hit_rate'] - report['scope']['pre_draw_calibration_accuracy'], 2)} 个百分点",
        f"- 校准前预测平局率：{report['scope']['pre_draw_calibration_predicted_draw_rate']}%",
        f"- 校准后预测平局率：{draw['predicted_draw_rate']}%",
        f"- 校准前平局命中率：{report['scope']['pre_draw_calibration_draw_hit_rate']}%",
        f"- 校准后平局命中率：{draw['draw_hit_rate']}%",
        "- 触发特征：ELO差值<100、Expected Goals<2.0、FIFA排名差<6、近10/20场失球率接近、世界杯淘汰赛。",
        "",
        "## 7. ROI分析",
        f"- 赔率样本：{roi['odds_sample_size']}",
        f"- 累计收益率：{display(roi['cumulative_roi'])}",
        f"- 最大回撤：{roi['max_drawdown']}",
        f"- 状态：{roi['status']}",
        "",
        "## 分年度结果",
    ]

    for year, payload in report["by_year"].items():
        year_result = payload["result_accuracy"]
        year_score = payload["score_prediction"]
        year_draw = payload["draw_analysis"]
        lines.extend(
            [
                f"### {year}",
                f"- 胜平负总命中率：{year_result['total_hit_rate']}%",
                f"- 主胜/平局/客胜命中率：{year_result['home_win_hit_rate']}% / {year_result['draw_hit_rate']}% / {year_result['away_win_hit_rate']}%",
                f"- 精确比分：{year_score['exact_score_hit_rate']}%",
                f"- TOP3比分覆盖：{year_score['top3_score_coverage']}%",
                f"- 预测平局率/真实平局率：{year_draw['predicted_draw_rate']}% / {year_draw['actual_draw_rate']}%",
                "",
            ]
        )

    output_path.write_text("\n".join(lines), encoding="utf-8-sig")


def main() -> None:
    report = run_report()
    reports_dir = Path(__file__).resolve().parents[1] / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "worldcup_backtest_2018_2022.json"
    md_path = reports_dir / "worldcup_backtest_2018_2022.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8-sig")
    write_markdown(report, md_path)
    print(json.dumps(report["overall"], ensure_ascii=False, indent=2))
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")


if __name__ == "__main__":
    main()
