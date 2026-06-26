import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models import Match, Prediction
from app.schemas import MatchCardOut

router = APIRouter(prefix="/matches", tags=["matches"])


def _risk_advice(confidence: float, upset_probability: float) -> dict:
    if upset_probability >= 65:
        return {
            "risk_level": "极高风险",
            "action": "直接过滤",
            "advice": "冷门预警达到 65% 以上，建议直接过滤，不进入下注候选。",
            "badge_class": "danger",
        }
    if upset_probability >= 55:
        return {
            "risk_level": "高风险",
            "action": "建议避开",
            "advice": "冷门预警达到 55% 以上，除非有非常明确的盘口价值，否则建议避开。",
            "badge_class": "danger",
        }
    if upset_probability >= 45:
        return {
            "risk_level": "偏高风险",
            "action": "谨慎观察",
            "advice": "冷门预警进入 45%-55% 区间，不建议重仓，优先复核伤停、盘口和赔率变化。",
            "badge_class": "warning",
        }
    if confidence >= 75 and upset_probability < 40:
        return {
            "risk_level": "低风险",
            "action": "重点关注",
            "advice": "信心指数较高且冷门预警低于 40%，可以作为重点关注候选。",
            "badge_class": "success",
        }
    if confidence >= 60 and upset_probability < 45:
        return {
            "risk_level": "中低风险",
            "action": "小注观察",
            "advice": "信心指数尚可且冷门预警低于 45%，可小注或继续观察临场赔率。",
            "badge_class": "neutral",
        }
    return {
        "risk_level": "中风险",
        "action": "观望",
        "advice": "模型信心或冷门风险未达到重点关注标准，建议观望或等待临场数据。",
        "badge_class": "neutral",
    }


def _serialize_match(match: Match) -> dict:
    prediction = match.prediction
    top_scores = json.loads(prediction.top_scores or "[]")
    total_goals_probabilities = json.loads(prediction.total_goals_probabilities or "{}")
    model_breakdown = json.loads(prediction.model_breakdown or "{}")
    one_goal_handicap_probabilities = json.loads(prediction.one_goal_handicap_probabilities or "{}")
    risk_advice = _risk_advice(prediction.confidence, prediction.upset_probability)
    return {
        "id": match.id,
        "competition": match.competition,
        "stage": match.stage,
        "kickoff_time": match.kickoff_time,
        "venue": match.venue,
        "status": match.status,
        "home_team": match.home_team,
        "away_team": match.away_team,
        "rank_summary": f"FIFA #{match.home_team.fifa_rank} vs FIFA #{match.away_team.fifa_rank}",
        "live_odds": {
            "home": match.odds.home_win_odds,
            "draw": match.odds.draw_odds,
            "away": match.odds.away_win_odds,
            "source_pool": match.odds.source_pool,
            "handicap": match.odds.handicap,
        },
        "prediction": {
            "result": prediction.predicted_result,
            "result_pick": prediction.predicted_result,
            "probabilities": {
                "home": prediction.home_win_probability,
                "draw": prediction.draw_probability,
                "away": prediction.away_win_probability,
            },
            "market_type": prediction.market_type,
            "handicap": prediction.handicap,
            "market_pick": prediction.predicted_market_result,
            "market_probabilities": {
                "home": prediction.market_home_probability,
                "draw": prediction.market_draw_probability,
                "away": prediction.market_away_probability,
            },
            "one_goal_handicap_pick": prediction.one_goal_handicap_result,
            "one_goal_handicap_probabilities": one_goal_handicap_probabilities,
            "score": prediction.predicted_score,
            "score_probability": prediction.score_probability,
            "top_scores": top_scores,
            "backup_scores": prediction.backup_scores.split(" | "),
            "half_full_time": prediction.half_full_time,
            "total_goals_band": prediction.total_goals_band,
            "total_goals_probabilities": total_goals_probabilities,
            "over_under_pick": prediction.over_under_pick,
            "both_teams_to_score": prediction.both_teams_to_score,
            "confidence": prediction.confidence,
            "upset_probability": prediction.upset_probability,
            "risk_level": risk_advice["risk_level"],
            "risk_action": risk_advice["action"],
            "risk_advice": risk_advice["advice"],
            "risk_badge_class": risk_advice["badge_class"],
            "model_breakdown": model_breakdown,
            "explanation": prediction.explanation,
            "report_preview": prediction.report_preview,
        },
    }


@router.get("", response_model=list[MatchCardOut])
def list_matches(db: Session = Depends(get_db)) -> list[dict]:
    matches = db.scalars(
        select(Match)
        .where(Match.status == "scheduled")
        .options(joinedload(Match.home_team), joinedload(Match.away_team), joinedload(Match.odds), joinedload(Match.prediction))
        .order_by(Match.kickoff_time.asc())
    ).unique().all()
    return [_serialize_match(match) for match in matches]


@router.get("/today", response_model=list[MatchCardOut])
def today_matches(db: Session = Depends(get_db)) -> list[dict]:
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1, hours=12)
    matches = db.scalars(
        select(Match)
        .where(Match.kickoff_time >= start, Match.kickoff_time < end, Match.status == "scheduled")
        .options(joinedload(Match.home_team), joinedload(Match.away_team), joinedload(Match.odds), joinedload(Match.prediction))
        .order_by(Match.kickoff_time.asc())
    ).unique().all()
    return [_serialize_match(match) for match in matches]


@router.get("/{match_id}")
def match_detail(match_id: int, db: Session = Depends(get_db)) -> dict:
    match = db.scalar(
        select(Match)
        .where(Match.id == match_id)
        .options(joinedload(Match.home_team), joinedload(Match.away_team), joinedload(Match.odds), joinedload(Match.prediction))
    )
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return _serialize_match(match)


@router.post("/reports/post-match-refresh")
def refresh_post_match_reports(db: Session = Depends(get_db)) -> dict:
    finished_predictions = db.scalars(
        select(Prediction).join(Match).where(Match.status == "finished").options(joinedload(Prediction.match))
    ).all()
    for prediction in finished_predictions:
        match = prediction.match
        prediction.report_preview = (
            f"赛后复盘：{match.home_team.name} {match.home_score}-{match.away_score} {match.away_team.name}。"
            f"真实赛果预测 {prediction.predicted_result}，竞彩盘口预测 {prediction.predicted_market_result}，"
            f"预测比分 {prediction.predicted_score}。"
        )
    db.commit()
    return {"updated_reports": len(finished_predictions)}
