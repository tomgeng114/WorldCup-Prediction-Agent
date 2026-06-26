export type MatchCard = {
  id: number;
  competition: string;
  stage: string;
  kickoff_time: string;
  venue: string;
  status: string;
  rank_summary: string;
  home_team: {
    id: number;
    name: string;
    code: string;
    group_name: string;
    fifa_rank: number;
    elo_rating: number;
  };
  away_team: {
    id: number;
    name: string;
    code: string;
    group_name: string;
    fifa_rank: number;
    elo_rating: number;
  };
  live_odds: {
    home: number;
    draw: number;
    away: number;
    source_pool: string;
    handicap: string;
  };
  prediction: {
    result: string;
    result_pick: string;
    probabilities: {
      home: number;
      draw: number;
      away: number;
    };
    market_type: string;
    handicap: string;
    market_pick: string;
    market_probabilities: {
      home: number;
      draw: number;
      away: number;
    };
    one_goal_handicap_pick: string;
    one_goal_handicap_probabilities: {
      home: number;
      draw: number;
      away: number;
    };
    score: string;
    score_probability: number;
    top_scores: { score: string; probability: number }[];
    backup_scores: string[];
    half_full_time: string;
    total_goals_band: string;
    total_goals_probabilities: Record<string, number>;
    over_under_pick: string;
    both_teams_to_score: string;
    confidence: number;
    upset_probability: number;
    risk_level: string;
    risk_action: string;
    risk_advice: string;
    risk_badge_class: string;
    model_breakdown: Record<string, { home: number; draw: number; away: number }>;
    explanation: string;
    report_preview: string;
  };
};

export type DashboardSummary = {
  total_predictions: number;
  win_draw_loss_hit_rate: number;
  handicap_hit_rate: number;
  score_hit_rate: number;
  goal_diff_hit_rate: number;
  half_full_hit_rate: number;
  over_under_hit_rate: number;
  roi: number;
  today_red: number;
  today_black: number;
  today_hit_rate: number;
  seven_day_red: number;
  seven_day_black: number;
  seven_day_hit_rate: number;
  thirty_day_red: number;
  thirty_day_black: number;
  thirty_day_hit_rate: number;
  ai_hot_same_count: number;
  ai_hot_opposite_count: number;
  ai_hot_sample_size: number;
  ai_hot_same_rate: number;
  ai_hot_opposite_rate: number;
  profit_curve: { date: string; value: number }[];
  accuracy_curve: { date: string; value: number }[];
};

export type HistoryRow = {
  match_id: number;
  date: string;
  competition: string;
  home_team: string;
  away_team: string;
  predicted_result: string;
  actual_result: string;
  predicted_market_result: string;
  actual_market_result: string;
  market_type: string;
  handicap: string;
  one_goal_handicap_result: string;
  one_goal_handicap_actual_result: string;
  predicted_score: string;
  predicted_scores: string[];
  actual_score: string;
  hit_result: boolean;
  hit_score: boolean;
  roi: number;
  profit: number;
};
