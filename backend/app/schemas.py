from datetime import datetime

from pydantic import BaseModel


class TeamOut(BaseModel):
    id: int
    name: str
    code: str
    group_name: str
    fifa_rank: int
    elo_rating: int
    recent_form: float
    xg_for: float
    xga_against: float

    model_config = {"from_attributes": True}


class MatchCardOut(BaseModel):
    id: int
    competition: str
    stage: str
    kickoff_time: datetime
    venue: str
    status: str
    home_team: TeamOut
    away_team: TeamOut
    rank_summary: str
    live_odds: dict
    prediction: dict


class DashboardSummaryOut(BaseModel):
    total_predictions: int
    win_draw_loss_hit_rate: float
    handicap_hit_rate: float
    score_hit_rate: float
    goal_diff_hit_rate: float
    half_full_hit_rate: float
    over_under_hit_rate: float
    roi: float
    today_red: int
    today_black: int
    today_hit_rate: float
    seven_day_red: int
    seven_day_black: int
    seven_day_hit_rate: float
    thirty_day_red: int
    thirty_day_black: int
    thirty_day_hit_rate: float
    ai_hot_same_count: int
    ai_hot_opposite_count: int
    ai_hot_sample_size: int
    ai_hot_same_rate: float
    ai_hot_opposite_rate: float
    profit_curve: list[dict]
    accuracy_curve: list[dict]


class HistoryRowOut(BaseModel):
    match_id: int
    date: datetime
    competition: str
    home_team: str
    away_team: str
    predicted_result: str
    actual_result: str
    predicted_score: str
    actual_score: str
    hit_result: bool
    hit_score: bool
    roi: float
    profit: float


class RunPredictionResponse(BaseModel):
    updated_predictions: int
    message: str
