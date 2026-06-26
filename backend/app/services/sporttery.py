from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Match, OddsSnapshot, Prediction, Team
from app.services.predictor import predict_match
from app.services.sporttery_analysis import apply_analysis_to_teams, fetch_match_analysis
from app.services.statistics import settle_match


SPORTTERY_MATCH_URL = (
    "https://webapi.sporttery.cn/gateway/uniform/football/"
    "getMatchCalculatorV1.qry?channel=c"
)
SPORTTERY_RESULT_URL = (
    "https://webapi.sporttery.cn/gateway/uniform/football/"
    "getUniformMatchResultV1.qry"
)

LEGACY_SAMPLE_TEAM_NAMES = {
    "Argentina",
    "Japan",
    "France",
    "United States",
    "Brazil",
    "Germany",
    "Spain",
    "Mexico",
}

EXCLUDED_COMPETITIONS = {
    "芬兰超级联赛",
}


@dataclass
class SportterySyncResult:
    fetched_matches: int
    imported_matches: int
    updated_matches: int
    skipped_matches: int
    closed_matches: int = 0
    settled_matches: int = 0
    pending_results: int = 0


@dataclass
class SportteryResultSyncResult:
    fetched_results: int
    settled_matches: int
    pending_results: int
    skipped_results: int


def fetch_sporttery_matches() -> list[dict]:
    request = Request(
        SPORTTERY_MATCH_URL,
        headers={
            "Referer": "https://m.sporttery.cn/mjc/jsq/zqspf/",
            "User-Agent": "Mozilla/5.0",
        },
    )
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not payload.get("success"):
        raise RuntimeError(payload.get("errorMessage") or "Sporttery API request failed")

    match_days = payload.get("value", {}).get("matchInfoList", [])
    matches: list[dict] = []
    for day in match_days:
        matches.extend(day.get("subMatchList", []))
    return matches


def fetch_sporttery_results(start_date: datetime | None = None, end_date: datetime | None = None) -> list[dict]:
    end_date = end_date or datetime.now()
    start_date = start_date or (end_date - timedelta(days=7))
    params = (
        f"matchBeginDate={start_date:%Y-%m-%d}"
        f"&matchEndDate={end_date:%Y-%m-%d}"
        "&leagueId=&pageSize=100&pageNo=1&isFix=0&matchPage=1&pcOrWap=1"
    )
    request = Request(
        f"{SPORTTERY_RESULT_URL}?{params}",
        headers={
            "Referer": "https://www.sporttery.cn/jc/zqsgkj/",
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.sporttery.cn",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 403:
            raise RuntimeError("Sporttery result API returned 403 Forbidden; match sync can continue without settlement.") from exc
        raise
    except URLError as exc:
        raise RuntimeError(f"Sporttery result API request failed: {exc}") from exc

    if payload.get("errorCode") not in ("0", 0, None) and not payload.get("success"):
        raise RuntimeError(payload.get("errorMessage") or "Sporttery result API request failed")

    return (payload.get("value") or {}).get("matchResult") or []


def _parse_float(value: object, default: float = 0.0) -> float:
    try:
        if value in ("", None):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_kickoff(match_data: dict) -> datetime:
    return datetime.strptime(f"{match_data['matchDate']} {match_data['matchTime']}", "%Y-%m-%d %H:%M:%S")


def _parse_result_score(value: object) -> tuple[int, int] | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    home_value, away_value = value.split(":", 1)
    try:
        home_score = int(home_value.strip())
        away_score = int(away_value.strip())
    except ValueError:
        return None
    if home_score < 0 or away_score < 0:
        return None
    return home_score, away_score


def _find_match_for_result(db: Session, result_data: dict) -> Match | None:
    sporttery_match_id = str(result_data.get("matchId") or "").strip()
    if sporttery_match_id:
        match = db.scalar(select(Match).where(Match.venue.like(f"%#{sporttery_match_id}")))
        if match:
            return match

    match_date = str(result_data.get("matchDate") or "")
    match_no = str(result_data.get("matchNumStr") or "")
    home_name = result_data.get("allHomeTeam") or result_data.get("homeTeam")
    away_name = result_data.get("allAwayTeam") or result_data.get("awayTeam")
    if not match_date or not match_no or not home_name or not away_name:
        return None

    try:
        day_start = datetime.strptime(match_date, "%Y-%m-%d")
    except ValueError:
        return None
    day_end = day_start + timedelta(days=1)

    candidates = db.scalars(
        select(Match).where(
            Match.stage == match_no,
            Match.kickoff_time >= day_start,
            Match.kickoff_time < day_end,
        )
    ).all()
    for match in candidates:
        if match.home_team.name == home_name and match.away_team.name == away_name:
            return match
    return None


def _team_code(match_data: dict, side: str) -> str:
    code = (match_data.get(f"{side}TeamCode") or match_data.get(f"{side}TeamAbbEnName") or "").strip()
    if code:
        return code[:8]
    name = match_data.get(f"{side}TeamAllName") or match_data.get(f"{side}TeamAbbName")
    return str(abs(hash(name)))[:8]


def _get_or_create_team(db: Session, match_data: dict, side: str) -> Team:
    name = match_data.get(f"{side}TeamAllName") or match_data.get(f"{side}TeamAbbName")
    code = _team_code(match_data, side)
    team = db.scalar(select(Team).where(Team.name == name))
    if team:
        return team

    existing_code = db.scalar(select(Team).where(Team.code == code))
    if existing_code:
        code = f"{code[:5]}{match_data.get(f'{side}TeamId', '')}"[:8]

    team = Team(
        name=name,
        code=code,
        group_name=match_data.get("groupName") or "-",
        fifa_rank=999,
        elo_rating=1500,
        recent_form=0.5,
        xg_for=1.3,
        xga_against=1.3,
        world_cup_history_score=0.5,
    )
    db.add(team)
    db.flush()
    return team


def _delete_legacy_sample_data(db: Session) -> None:
    sample_team_ids = db.scalars(select(Team.id).where(Team.name.in_(LEGACY_SAMPLE_TEAM_NAMES))).all()
    if not sample_team_ids:
        return

    sample_match_ids = db.scalars(
        select(Match.id).where(
            Match.competition == "World Cup",
            Match.home_team_id.in_(sample_team_ids) | Match.away_team_id.in_(sample_team_ids),
        )
    ).all()
    if sample_match_ids:
        db.execute(delete(Prediction).where(Prediction.match_id.in_(sample_match_ids)))
        db.execute(delete(OddsSnapshot).where(OddsSnapshot.match_id.in_(sample_match_ids)))
        db.execute(delete(Match).where(Match.id.in_(sample_match_ids)))
    db.execute(delete(Team).where(Team.id.in_(sample_team_ids)))
    db.flush()


def sync_sporttery_matches(db: Session, purge_legacy_samples: bool = True) -> SportterySyncResult:
    raw_matches = fetch_sporttery_matches()
    if purge_legacy_samples:
        _delete_legacy_sample_data(db)

    imported = 0
    updated = 0
    skipped = 0
    seen_match_ids: set[int] = set()

    for raw_match in raw_matches:
        had = raw_match.get("had") or {}
        hhad = raw_match.get("hhad") or {}
        odds_source = had if had else hhad
        source_pool = "HAD" if had else "HHAD"
        home_odds = _parse_float(odds_source.get("h"))
        draw_odds = _parse_float(odds_source.get("d"))
        away_odds = _parse_float(odds_source.get("a"))
        if not home_odds or not draw_odds or not away_odds:
            skipped += 1
            continue

        competition = raw_match.get("leagueAllName") or raw_match.get("leagueAbbName") or "竞彩足球"
        if competition in EXCLUDED_COMPETITIONS:
            skipped += 1
            continue

        kickoff_time = _parse_kickoff(raw_match)
        home_team = _get_or_create_team(db, raw_match, "home")
        away_team = _get_or_create_team(db, raw_match, "away")

        match = db.scalar(
            select(Match).where(
                Match.competition == competition,
                Match.kickoff_time == kickoff_time,
                Match.home_team_id == home_team.id,
                Match.away_team_id == away_team.id,
            )
        )

        if match:
            updated += 1
            match.status = "scheduled" if raw_match.get("matchStatus") == "Selling" else "closed"
        else:
            match = Match(
                competition=competition,
                stage=raw_match.get("matchNumStr") or raw_match.get("matchWeek") or "竞彩足球",
                kickoff_time=kickoff_time,
                venue=f"中国体育彩票 #{raw_match.get('matchId')}",
                home_team_id=home_team.id,
                away_team_id=away_team.id,
                status="scheduled" if raw_match.get("matchStatus") == "Selling" else "closed",
            )
            db.add(match)
            db.flush()
            imported += 1
        seen_match_ids.add(match.id)

        if match.odds:
            odds = match.odds
            odds.home_win_odds = home_odds
            odds.draw_odds = draw_odds
            odds.away_win_odds = away_odds
            odds.source_pool = source_pool
            odds.handicap = str(odds_source.get("goalLine") or "")
            odds.asian_line = _parse_float(odds_source.get("goalLineValue"))
            odds.line_movement = _parse_float(odds_source.get("hf")) - _parse_float(odds_source.get("af"))
        else:
            odds = OddsSnapshot(
                match_id=match.id,
                home_win_odds=home_odds,
                draw_odds=draw_odds,
                away_win_odds=away_odds,
                over_25_odds=1.90,
                under_25_odds=1.90,
                asian_line=_parse_float(odds_source.get("goalLineValue")),
                source_pool=source_pool,
                handicap=str(odds_source.get("goalLine") or ""),
                line_movement=_parse_float(odds_source.get("hf")) - _parse_float(odds_source.get("af")),
                kelly_index=0.95,
            )
            db.add(odds)
            db.flush()

        try:
            analysis = fetch_match_analysis(int(raw_match.get("matchId")))
            apply_analysis_to_teams(home_team, away_team, analysis)
            db.flush()
        except Exception:
            analysis = {}

        if match.status == "finished" and match.prediction:
            continue

        payload = predict_match(match, odds)
        prediction = match.prediction or Prediction(match_id=match.id)
        prediction.home_win_probability = payload.home_win_probability
        prediction.draw_probability = payload.draw_probability
        prediction.away_win_probability = payload.away_win_probability
        prediction.predicted_result = payload.predicted_result
        prediction.predicted_score = payload.predicted_score
        prediction.backup_scores = payload.backup_scores
        prediction.half_full_time = payload.half_full_time
        prediction.total_goals_band = payload.total_goals_band
        prediction.over_under_pick = payload.over_under_pick
        prediction.both_teams_to_score = payload.both_teams_to_score
        prediction.confidence = payload.confidence
        prediction.upset_probability = payload.upset_probability
        prediction.score_probability = payload.score_probability
        prediction.top_scores = json.dumps(payload.top_scores, ensure_ascii=False)
        prediction.total_goals_probabilities = json.dumps(payload.total_goals_probabilities, ensure_ascii=False)
        prediction.model_breakdown = json.dumps(payload.model_breakdown, ensure_ascii=False)
        prediction.market_type = payload.market_type
        prediction.handicap = payload.handicap
        prediction.predicted_market_result = payload.predicted_market_result
        prediction.market_home_probability = payload.market_probabilities["home"]
        prediction.market_draw_probability = payload.market_probabilities["draw"]
        prediction.market_away_probability = payload.market_probabilities["away"]
        prediction.one_goal_handicap_result = payload.one_goal_handicap_result
        prediction.one_goal_handicap_probabilities = json.dumps(payload.one_goal_handicap_probabilities, ensure_ascii=False)
        prediction.explanation = payload.explanation
        prediction.report_preview = payload.report_preview
        prediction.is_red_pick = payload.is_red_pick
        db.add(prediction)

    closed = 0
    if seen_match_ids:
        stale_matches = db.scalars(
            select(Match).where(
                Match.status == "scheduled",
                Match.id.not_in(seen_match_ids),
                Match.competition != "世界杯",
            )
        ).all()
        for match in stale_matches:
            match.status = "closed"
            closed += 1

    try:
        result_sync = sync_sporttery_results(db, commit=False)
    except RuntimeError:
        result_sync = SportteryResultSyncResult(
            fetched_results=0,
            settled_matches=0,
            pending_results=0,
            skipped_results=0,
        )
    db.commit()
    return SportterySyncResult(
        fetched_matches=len(raw_matches),
        imported_matches=imported,
        updated_matches=updated,
        skipped_matches=skipped,
        closed_matches=closed,
        settled_matches=result_sync.settled_matches,
        pending_results=result_sync.pending_results,
    )


def sync_sporttery_results(db: Session, days: int = 7, commit: bool = True) -> SportteryResultSyncResult:
    raw_results = fetch_sporttery_results(start_date=datetime.now() - timedelta(days=days), end_date=datetime.now())
    settled = 0
    pending = 0
    skipped = 0

    for raw_result in raw_results:
        match = _find_match_for_result(db, raw_result)
        score = _parse_result_score(raw_result.get("sectionsNo999"))
        if not match:
            skipped += 1
            continue
        if not score:
            pending += 1
            if match.status not in ("scheduled", "finished"):
                match.status = "closed"
            continue

        home_score, away_score = score
        already_settled = (
            match.status == "finished"
            and match.home_score == home_score
            and match.away_score == away_score
        )
        match.home_score = home_score
        match.away_score = away_score
        match.status = "finished"

        if match.prediction:
            settle_match(match)
        if not already_settled:
            settled += 1

    if commit:
        db.commit()

    return SportteryResultSyncResult(
        fetched_results=len(raw_results),
        settled_matches=settled,
        pending_results=pending,
        skipped_results=skipped,
    )
