from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import sleep
from urllib.error import URLError
from urllib.request import Request, urlopen

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import WorldCupMatch


WORLD_CUP_YEARS = [2002, 2006, 2010, 2014, 2018, 2022]
RECENT_WORLD_CUP_YEARS = [2014, 2018, 2022]
OPENFOOTBALL_URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/{year}/worldcup.json"
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "openfootball_cache"


@dataclass
class ImportSummary:
    imported: int
    years: list[int]
    source: str


def _result(home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return "Home Win"
    if home_score < away_score:
        return "Away Win"
    return "Draw"


def _parse_match_datetime(match_data: dict) -> datetime:
    date_text = match_data["date"]
    time_text = (match_data.get("time") or "00:00").split()[0]
    return datetime.fromisoformat(f"{date_text}T{time_text}")


def fetch_world_cup_year(year: int) -> list[dict]:
    url = OPENFOOTBALL_URL.format(year=year)
    cache_path = DATA_DIR / f"worldcup_{year}.json"
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return payload.get("matches", [])

    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            return payload.get("matches", [])
        except (URLError, TimeoutError, ConnectionError, OSError) as exc:
            last_error = exc
            sleep(1.5 * (attempt + 1))
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return payload.get("matches", [])
    raise RuntimeError(f"Failed to fetch World Cup history for {year}: {last_error}")


def import_world_cup_history(
    db: Session,
    years: list[int] | None = None,
    replace: bool = True,
) -> ImportSummary:
    selected_years = years or WORLD_CUP_YEARS
    if replace:
        db.execute(delete(WorldCupMatch).where(WorldCupMatch.tournament_year.in_(selected_years)))

    imported = 0
    for year in selected_years:
        source = OPENFOOTBALL_URL.format(year=year)
        for raw_match in fetch_world_cup_year(year):
            score = raw_match.get("score") or {}
            full_time = score.get("ft") or []
            half_time = score.get("ht") or [0, 0]
            if len(full_time) != 2:
                continue

            home_score = int(full_time[0])
            away_score = int(full_time[1])
            home_half_score = int(half_time[0] if len(half_time) == 2 else 0)
            away_half_score = int(half_time[1] if len(half_time) == 2 else 0)
            result = _result(home_score, away_score)
            half_result = _result(home_half_score, away_half_score)
            match = WorldCupMatch(
                tournament_year=year,
                match_date=_parse_match_datetime(raw_match),
                stage=raw_match.get("round") or "",
                group_name=raw_match.get("group") or "",
                ground=raw_match.get("ground") or "",
                home_team=raw_match.get("team1") or "",
                away_team=raw_match.get("team2") or "",
                home_score=home_score,
                away_score=away_score,
                home_half_score=home_half_score,
                away_half_score=away_half_score,
                result=result,
                half_result=half_result,
                half_full_result=f"{half_result}/{result}",
                total_goals=home_score + away_score,
                source=source,
            )
            db.add(match)
            imported += 1

    db.commit()
    return ImportSummary(
        imported=imported,
        years=selected_years,
        source="openfootball/worldcup.json",
    )


def historical_match_counts(db: Session) -> dict[int, int]:
    counts: dict[int, int] = {}
    for year in WORLD_CUP_YEARS:
        rows = db.scalars(select(WorldCupMatch.id).where(WorldCupMatch.tournament_year == year)).all()
        counts[year] = len(rows)
    return counts
