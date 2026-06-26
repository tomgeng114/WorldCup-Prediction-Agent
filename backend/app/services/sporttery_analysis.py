from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.models import Team


WEBAPI = "https://webapi.sporttery.cn"


def _request_json(path: str, params: dict) -> dict:
    url = f"{WEBAPI}{path}?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "Referer": "https://m.sporttery.cn/zqlszl/bssj/",
            "User-Agent": "Mozilla/5.0",
        },
    )
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("success"):
        return {}
    value = payload.get("value")
    return value if isinstance(value, dict) else {}


def _parse_float(value: object, default: float = 0.0) -> float:
    try:
        if value in ("", None):
            return default
        return float(str(value).replace("%", ""))
    except (TypeError, ValueError):
        return default


def _form_from_statistics(statistics: dict) -> float | None:
    total = _parse_float(statistics.get("totalLegCnt"))
    if total <= 0:
        return None
    wins = _parse_float(statistics.get("winGoalMatchCnt"))
    draws = _parse_float(statistics.get("drawMatchCnt"))
    return max(0.05, min(0.95, (wins * 3 + draws) / (total * 3)))


def _form_from_feature(feature: dict, side: str) -> float | None:
    each_home_away = feature.get("eachHomeAway") or {}
    total = _parse_float(each_home_away.get("totalLegCnt"))
    if total <= 0:
        return None
    wins = _parse_float(each_home_away.get(f"{side}WinGoalMatchCnt"))
    draws = _parse_float(each_home_away.get(f"{side}DrawMatchCnt"))
    return max(0.05, min(0.95, (wins * 3 + draws) / (total * 3)))


def _derived_elo(team: Team) -> int:
    form_edge = (team.recent_form - 0.5) * 260
    xg_edge = (team.xg_for - team.xga_against) * 95
    h2h_edge = (team.world_cup_history_score - 0.5) * 70
    return int(max(1150, min(1950, 1500 + form_edge + xg_edge + h2h_edge)))


def _injury_penalty(team_side: dict) -> float:
    players = team_side.get("injuriesAndSuspensionsList") or []
    penalty = 0.0
    for player in players:
        started = _parse_float(player.get("startedMatchCnt"))
        appearances = _parse_float(player.get("appearanceCnt"))
        importance = min(1.0, (started * 0.08) + (appearances * 0.03))
        if player.get("suspensionFlag") == 1:
            penalty += 0.06 + importance
        elif player.get("injuryFlag") == 1:
            penalty += 0.04 + importance
    return min(0.22, penalty)


def fetch_match_analysis(sporttery_match_id: int) -> dict:
    params = {"sportteryMatchId": sporttery_match_id}
    return {
        "feature": _request_json(
            "/gateway/uniform/football/getMatchFeatureV1.qry",
            {"sportteryMatchId": sporttery_match_id, "termLimits": 10},
        ),
        "history": _request_json(
            "/gateway/uniform/football/getResultHistoryV1.qry",
            {"sportteryMatchId": sporttery_match_id, "termLimits": 10, "tournamentFlag": 0, "homeAwayFlag": 0},
        ),
        "recent": _request_json(
            "/gateway/uniform/football/getMatchResultV1.qry",
            {"sportteryMatchId": sporttery_match_id, "termLimits": 10, "tournamentFlag": 0, "homeAwayFlag": 0},
        ),
        "injury": _request_json(
            "/gateway/uniform/football/getInjurySuspensionV1.qry",
            params,
        ),
    }


def apply_analysis_to_teams(home_team: Team, away_team: Team, analysis: dict) -> None:
    feature = analysis.get("feature") or {}
    recent = analysis.get("recent") or {}
    injury = analysis.get("injury") or {}
    history = analysis.get("history") or {}

    goal_avg = feature.get("goalAvg") or {}
    loss_goal_avg = feature.get("lossGoalAvg") or {}
    home_team.xg_for = max(0.2, _parse_float(goal_avg.get("homeGoalAvgCnt"), home_team.xg_for))
    away_team.xg_for = max(0.2, _parse_float(goal_avg.get("awayGoalAvgCnt"), away_team.xg_for))
    home_team.xga_against = max(0.2, _parse_float(loss_goal_avg.get("homeLossGoalAvgCnt"), home_team.xga_against))
    away_team.xga_against = max(0.2, _parse_float(loss_goal_avg.get("awayLossGoalAvgCnt"), away_team.xga_against))

    home_form = _form_from_statistics((recent.get("home") or {}).get("statistics") or {})
    away_form = _form_from_statistics((recent.get("away") or {}).get("statistics") or {})
    if home_form is None:
        home_form = _form_from_feature(feature, "home")
    if away_form is None:
        away_form = _form_from_feature(feature, "away")
    home_penalty = _injury_penalty(injury.get("home") or {})
    away_penalty = _injury_penalty(injury.get("away") or {})
    if home_form is not None:
        home_team.recent_form = max(0.05, home_form - home_penalty)
    if away_form is not None:
        away_team.recent_form = max(0.05, away_form - away_penalty)

    h2h_stats = history.get("statistics") or {}
    total_h2h = _parse_float(h2h_stats.get("totalLegCnt"))
    if total_h2h > 0:
        wins = _parse_float(h2h_stats.get("winGoalMatchCnt"))
        draws = _parse_float(h2h_stats.get("drawMatchCnt"))
        home_team.world_cup_history_score = max(0.05, min(0.95, (wins + draws * 0.5) / total_h2h))
        away_team.world_cup_history_score = 1 - home_team.world_cup_history_score

    home_team.elo_rating = _derived_elo(home_team)
    away_team.elo_rating = _derived_elo(away_team)
