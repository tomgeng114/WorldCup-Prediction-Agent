from __future__ import annotations

import json
import math
import random
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import WorldCupTeamProfile


SIMULATIONS = 10_000
GROUP_COUNT = 12
GROUP_SIZE = 4
RANDOM_SEED = 20260610
SCHEDULE_SOURCE_URL = "https://www.zoho.com/toolkit/fifa-world-cup-2026.html"
SCHEDULE_SOURCE_LABEL = "Zoho Toolkit 2026 FIFA World Cup schedule table"


@dataclass(frozen=True)
class SimTeam:
    country: str
    confederation: str
    strength: float


@dataclass
class ScheduleFixture:
    match_no: int
    stage: str
    group: str | None
    team1: str
    team2: str
    date: str
    venue: str
    city: str


@dataclass
class GroupRow:
    group: str
    team: SimTeam
    points: int = 0
    goals_for: int = 0
    goals_against: int = 0
    wins: int = 0

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against


@dataclass
class TeamCounter:
    group_qualification: int = 0
    round_of_32: int = 0
    round_of_16: int = 0
    quarter_final: int = 0
    semi_final: int = 0
    final: int = 0
    champion: int = 0


TEAM_ALIASES = {
    "bosnia herzegovina": "Bosnia and Herzegovina",
    "bosnia and herzegovina": "Bosnia and Herzegovina",
    "cape verde": "Cabo Verde",
    "cabo verde": "Cabo Verde",
    "cote divoire": "Cote d'Ivoire",
    "côte divoire": "Cote d'Ivoire",
    "ivory coast": "Cote d'Ivoire",
    "curacao": "Curacao",
    "czech republic": "Czechia",
    "czechia": "Czechia",
    "dr congo": "DR Congo",
    "congo dr": "DR Congo",
    "iran": "IR Iran",
    "ir iran": "IR Iran",
    "south korea": "Korea Republic",
    "korea republic": "Korea Republic",
    "turkey": "Turkiye",
    "turkiye": "Turkiye",
    "turkiye": "Turkiye",
    "united states": "USA",
    "usa": "USA",
}


def _normalize_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"[^a-zA-Z0-9]+", " ", normalized).strip().lower()
    return re.sub(r"\s+", " ", normalized)


def _canonical_team_name(value: str) -> str:
    return TEAM_ALIASES.get(_normalize_key(value), str(value).strip())


def _load_teams(db: Session) -> list[SimTeam]:
    profiles = db.scalars(
        select(WorldCupTeamProfile)
        .where(WorldCupTeamProfile.tournament_year == 2026)
        .where(WorldCupTeamProfile.world_cup_strength_score.is_not(None))
        .order_by(WorldCupTeamProfile.world_cup_strength_score.desc())
    ).all()
    return [
        SimTeam(
            country=profile.country or profile.team_name,
            confederation=profile.confederation,
            strength=float(profile.world_cup_strength_score),
        )
        for profile in profiles
    ]


def _team_lookup(teams: list[SimTeam]) -> dict[str, SimTeam]:
    lookup: dict[str, SimTeam] = {}
    for team in teams:
        lookup[_normalize_key(team.country)] = team
        lookup[_normalize_key(_canonical_team_name(team.country))] = team
    return lookup


def _resolve_team(name: str, lookup: dict[str, SimTeam]) -> SimTeam:
    canonical = _canonical_team_name(name)
    for candidate in (canonical, name):
        key = _normalize_key(candidate)
        if key in lookup:
            return lookup[key]
    raise ValueError(f"赛程球队无法匹配数据库画像: {name}")


def _read_schedule_tables() -> tuple[dict[str, list[str]], list[ScheduleFixture]]:
    tables = pd.read_html(SCHEDULE_SOURCE_URL, storage_options={"User-Agent": "Mozilla/5.0"})
    if len(tables) < 7:
        raise RuntimeError(f"赛程源表格数量异常: expected >= 7, got {len(tables)}")

    group_table = tables[5]
    schedule_table = tables[6]
    groups: dict[str, list[str]] = {}
    for _, row in group_table.iterrows():
        group_name = str(row["Group"]).replace("Group", "").strip()
        teams = [_canonical_team_name(item) for item in str(row["Participating Nations"]).split(",")]
        groups[group_name] = [team.strip() for team in teams if team.strip()]

    fixtures: list[ScheduleFixture] = []
    for _, row in schedule_table.iterrows():
        match_value = str(row["Match"]).strip()
        if not match_value.isdigit():
            continue
        match_no = int(match_value)
        stage = str(row["Group Stage"]).strip()
        group = stage if re.fullmatch(r"[A-L]", stage) else None
        fixtures.append(
            ScheduleFixture(
                match_no=match_no,
                stage=stage,
                group=group,
                team1=str(row["Team 1"]).strip(),
                team2=str(row["Team 2"]).strip(),
                date=str(row["Date"]).strip(),
                venue=str(row["Venue"]).strip(),
                city=str(row["City"]).strip(),
            )
        )

    group_fixtures = [fixture for fixture in fixtures if fixture.group]
    knockout_fixtures = [fixture for fixture in fixtures if not fixture.group and fixture.stage != "Third Place"]
    if len(groups) != GROUP_COUNT:
        raise RuntimeError(f"真实小组数量异常: expected {GROUP_COUNT}, got {len(groups)}")
    if any(len(teams) != GROUP_SIZE for teams in groups.values()):
        raise RuntimeError("真实小组队伍数量异常: 每组必须 4 队")
    if len(group_fixtures) != 72:
        raise RuntimeError(f"真实小组赛数量异常: expected 72, got {len(group_fixtures)}")
    if len([fixture for fixture in knockout_fixtures if fixture.stage == "Round of 32"]) != 16:
        raise RuntimeError("真实 32 强赛程数量异常: expected 16")
    return groups, fixtures


def _match_probabilities(home: SimTeam, away: SimTeam, allow_draw: bool) -> dict[str, float]:
    diff = home.strength - away.strength
    home_no_draw = 1 / (1 + math.exp(-diff / 13.5))
    if not allow_draw:
        return {"home": home_no_draw, "draw": 0.0, "away": 1 - home_no_draw}
    draw = max(0.18, min(0.31, 0.27 - abs(diff) / 260))
    return {
        "home": home_no_draw * (1 - draw),
        "draw": draw,
        "away": (1 - home_no_draw) * (1 - draw),
    }


def _sample_score(winner: str, rng: random.Random, strength_gap: float) -> tuple[int, int]:
    if winner == "draw":
        goals = rng.choices([0, 1, 2, 3], weights=[0.18, 0.48, 0.26, 0.08], k=1)[0]
        return goals, goals
    margin = rng.choices([1, 2, 3, 4], weights=[0.58, 0.28, 0.11, 0.03], k=1)[0]
    base = rng.choices([0, 1, 2], weights=[0.36, 0.47, 0.17], k=1)[0]
    if abs(strength_gap) > 22 and rng.random() < 0.18:
        margin = min(5, margin + 1)
    if winner == "home":
        return base + margin, base
    return base, base + margin


def _play_group_fixture(home: GroupRow, away: GroupRow, rng: random.Random) -> None:
    probabilities = _match_probabilities(home.team, away.team, allow_draw=True)
    outcome = rng.choices(
        ["home", "draw", "away"],
        weights=[probabilities["home"], probabilities["draw"], probabilities["away"]],
        k=1,
    )[0]
    home_goals, away_goals = _sample_score(outcome, rng, home.team.strength - away.team.strength)
    home.goals_for += home_goals
    home.goals_against += away_goals
    away.goals_for += away_goals
    away.goals_against += home_goals
    if home_goals > away_goals:
        home.points += 3
        home.wins += 1
    elif home_goals < away_goals:
        away.points += 3
        away.wins += 1
    else:
        home.points += 1
        away.points += 1


def _rank_group(rows: list[GroupRow]) -> list[GroupRow]:
    return sorted(
        rows,
        key=lambda row: (
            row.points,
            row.goal_difference,
            row.goals_for,
            row.wins,
            row.team.strength,
        ),
        reverse=True,
    )


def _simulate_group_stage(
    groups: dict[str, list[str]],
    group_fixtures: list[ScheduleFixture],
    lookup: dict[str, SimTeam],
    rng: random.Random,
) -> tuple[dict[str, list[GroupRow]], list[GroupRow]]:
    standings: dict[str, list[GroupRow]] = {}
    row_lookup: dict[tuple[str, str], GroupRow] = {}
    for group, names in groups.items():
        standings[group] = []
        for name in names:
            team = _resolve_team(name, lookup)
            row = GroupRow(group=group, team=team)
            standings[group].append(row)
            row_lookup[(group, _normalize_key(team.country))] = row

    for fixture in sorted(group_fixtures, key=lambda item: item.match_no):
        if not fixture.group:
            continue
        team1 = _resolve_team(fixture.team1, lookup)
        team2 = _resolve_team(fixture.team2, lookup)
        home = row_lookup[(fixture.group, _normalize_key(team1.country))]
        away = row_lookup[(fixture.group, _normalize_key(team2.country))]
        _play_group_fixture(home, away, rng)

    ranked = {group: _rank_group(rows) for group, rows in standings.items()}
    thirds = [rows[2] for rows in ranked.values()]
    best_third = sorted(
        thirds,
        key=lambda row: (row.points, row.goal_difference, row.goals_for, row.wins, row.team.strength),
        reverse=True,
    )[:8]
    return ranked, best_third


def _resolve_slot(
    slot: str,
    ranked_groups: dict[str, list[GroupRow]],
    best_third: list[GroupRow],
    used_third_groups: set[str],
) -> SimTeam:
    text = str(slot).strip()
    group_match = re.fullmatch(r"Group ([A-L]) (Winner|Runner-up)", text)
    if group_match:
        group, position = group_match.groups()
        return ranked_groups[group][0 if position == "Winner" else 1].team

    third_match = re.fullmatch(r"3rd Place \(([A-L/]+)\)", text)
    if third_match:
        allowed = set(third_match.group(1).split("/"))
        for row in best_third:
            if row.group in allowed and row.group not in used_third_groups:
                used_third_groups.add(row.group)
                return row.team
        for row in best_third:
            if row.group not in used_third_groups:
                used_third_groups.add(row.group)
                return row.team
        raise RuntimeError(f"无法解析三名晋级槽位: {text}")

    raise RuntimeError(f"无法解析淘汰赛槽位: {text}")


def _play_knockout_match(team_a: SimTeam, team_b: SimTeam, rng: random.Random) -> SimTeam:
    probabilities = _match_probabilities(team_a, team_b, allow_draw=False)
    return team_a if rng.random() < probabilities["home"] else team_b


def _simulate_knockout(
    knockout_fixtures: list[ScheduleFixture],
    ranked_groups: dict[str, list[GroupRow]],
    best_third: list[GroupRow],
    rng: random.Random,
) -> dict[int, SimTeam]:
    winners: dict[int, SimTeam] = {}
    used_third_groups: set[str] = set()
    for fixture in sorted(knockout_fixtures, key=lambda item: item.match_no):
        if fixture.stage == "Third Place":
            continue
        if fixture.stage == "Round of 32":
            team1 = _resolve_slot(fixture.team1, ranked_groups, best_third, used_third_groups)
            team2 = _resolve_slot(fixture.team2, ranked_groups, best_third, used_third_groups)
        else:
            team1 = _resolve_winner_reference(fixture.team1, winners)
            team2 = _resolve_winner_reference(fixture.team2, winners)
        winners[fixture.match_no] = _play_knockout_match(team1, team2, rng)
    return winners


def _resolve_winner_reference(value: str, winners: dict[int, SimTeam]) -> SimTeam:
    match = re.fullmatch(r"Winner Match (\d+)", str(value).strip())
    if not match:
        raise RuntimeError(f"无法解析胜者引用: {value}")
    match_no = int(match.group(1))
    if match_no not in winners:
        raise RuntimeError(f"淘汰赛引用了尚未产生的胜者: Match {match_no}")
    return winners[match_no]


def _to_probability(value: int, simulations: int) -> float:
    return round(value / simulations * 100, 2)


def _validate_schedule_teams(groups: dict[str, list[str]], fixtures: list[ScheduleFixture], lookup: dict[str, SimTeam]) -> None:
    names: set[str] = set()
    for teams in groups.values():
        names.update(teams)
    for fixture in fixtures:
        if fixture.group:
            names.add(fixture.team1)
            names.add(fixture.team2)
    missing = []
    for name in sorted(names):
        try:
            _resolve_team(name, lookup)
        except ValueError:
            missing.append(name)
    if missing:
        raise RuntimeError("赛程球队未匹配数据库画像: " + ", ".join(missing))


def run_phase8_simulation(db: Session, simulations: int = SIMULATIONS) -> dict:
    teams = _load_teams(db)
    if len(teams) != 48:
        return {
            "status": "insufficient_teams",
            "teams": len(teams),
            "required_teams": 48,
            "error": "需要 48 支球队且全部具备 world_cup_strength_score。",
        }

    try:
        groups, fixtures = _read_schedule_tables()
        lookup = _team_lookup(teams)
        _validate_schedule_teams(groups, fixtures, lookup)
    except Exception as exc:
        return {
            "status": "schedule_source_error",
            "pre_draw_simulation": False,
            "real_schedule_simulation": False,
            "schedule_source": SCHEDULE_SOURCE_URL,
            "error": str(exc),
        }

    group_fixtures = [fixture for fixture in fixtures if fixture.group]
    knockout_fixtures = [
        fixture
        for fixture in fixtures
        if not fixture.group and fixture.stage in {"Round of 32", "Round of 16", "Quarter-final", "Semi-final", "Final"}
    ]
    rng = random.Random(RANDOM_SEED)
    counters = {team.country: TeamCounter() for team in teams}

    for _ in range(simulations):
        ranked_groups, best_third = _simulate_group_stage(groups, group_fixtures, lookup, rng)
        round_of_32_teams = [rows[0].team for rows in ranked_groups.values()]
        round_of_32_teams.extend(rows[1].team for rows in ranked_groups.values())
        round_of_32_teams.extend(row.team for row in best_third)
        for team in round_of_32_teams:
            counters[team.country].group_qualification += 1
            counters[team.country].round_of_32 += 1

        winners = _simulate_knockout(knockout_fixtures, ranked_groups, best_third, rng)

        for match_no in range(73, 89):
            counters[winners[match_no].country].round_of_16 += 1
        for match_no in range(89, 97):
            counters[winners[match_no].country].quarter_final += 1
        for match_no in range(97, 101):
            counters[winners[match_no].country].semi_final += 1
        for match_no in range(101, 103):
            counters[winners[match_no].country].final += 1
        counters[winners[104].country].champion += 1

    team_strength = {team.country: team.strength for team in teams}
    probabilities = []
    for country, counter in counters.items():
        probabilities.append(
            {
                "country": country,
                "strength_score": round(team_strength[country], 2),
                "group_qualification_probability": _to_probability(counter.group_qualification, simulations),
                "round_of_32_probability": _to_probability(counter.round_of_32, simulations),
                "round_of_16_probability": _to_probability(counter.round_of_16, simulations),
                "quarter_final_probability": _to_probability(counter.quarter_final, simulations),
                "semi_final_probability": _to_probability(counter.semi_final, simulations),
                "final_probability": _to_probability(counter.final, simulations),
                "champion_probability": _to_probability(counter.champion, simulations),
            }
        )
    probabilities.sort(key=lambda row: row["champion_probability"], reverse=True)

    payload = {
        "status": "ok",
        "pre_draw_simulation": False,
        "real_schedule_simulation": True,
        "simulations": simulations,
        "random_seed": RANDOM_SEED,
        "schedule_source": SCHEDULE_SOURCE_URL,
        "schedule_source_label": SCHEDULE_SOURCE_LABEL,
        "format": {
            "teams": 48,
            "groups": 12,
            "teams_per_group": 4,
            "group_stage_fixtures": len(group_fixtures),
            "round_of_32_fixtures": len([fixture for fixture in knockout_fixtures if fixture.stage == "Round of 32"]),
            "knockout_fixtures_used": len(knockout_fixtures),
            "qualification_rule": "Each group top 2 plus 8 best third-place teams qualify for Round of 32",
            "matches_planned": 104,
        },
        "data_basis": "world_cup_strength_score from world_cup_team_profiles",
        "schedule_policy": "Real published 2026 schedule source parsed at runtime; no pre-draw placeholder grouping.",
        "groups": groups,
        "probabilities": probabilities,
        "top20_champion_probability": probabilities[:20],
        "top20_final_probability": sorted(probabilities, key=lambda row: row["final_probability"], reverse=True)[:20],
    }

    reports_dir = Path(__file__).resolve().parents[2] / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "phase8_simulation_report.json"
    md_path = reports_dir / "phase8_simulation_report.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(md_path, payload)
    payload["json_path"] = str(json_path)
    payload["report_path"] = str(md_path)
    return payload


def _write_markdown(path: Path, payload: dict) -> None:
    lines = [
        "# Phase 8 World Cup Monte Carlo Simulation Report",
        "",
        "## Simulation Scope",
        "",
        f"- Simulations: {payload['simulations']}",
        f"- pre_draw_simulation: {payload['pre_draw_simulation']}",
        f"- real_schedule_simulation: {payload['real_schedule_simulation']}",
        f"- Schedule source: {payload['schedule_source']}",
        "- Input: 48 teams and `world_cup_strength_score`.",
        "- Fixture policy: parse the published 2026 group stage and knockout path; no fabricated schedule fallback.",
        "- Format: 12 groups of 4, top 2 plus 8 best third-place teams to Round of 32.",
        f"- Group stage fixtures parsed: {payload['format']['group_stage_fixtures']}",
        f"- Knockout fixtures used: {payload['format']['knockout_fixtures_used']}",
        "",
        "## Groups",
        "",
    ]
    for group, teams in sorted(payload["groups"].items()):
        lines.append(f"- Group {group}: {', '.join(teams)}")
    lines.extend(
        [
            "",
            "## Top 20 Champion Probability",
            "",
            "| Rank | Team | Strength | Champion | Final | Semi Final | Quarter Final | Round of 16 | Round of 32 |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for index, row in enumerate(payload["top20_champion_probability"], start=1):
        lines.append(
            f"| {index} | {row['country']} | {row['strength_score']} | {row['champion_probability']}% | "
            f"{row['final_probability']}% | {row['semi_final_probability']}% | "
            f"{row['quarter_final_probability']}% | {row['round_of_16_probability']}% | "
            f"{row['round_of_32_probability']}% |"
        )
    lines.extend(
        [
            "",
            "## Top 20 Final Probability",
            "",
            "| Rank | Team | Strength | Final | Champion | Semi Final | Quarter Final | Round of 16 | Round of 32 |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for index, row in enumerate(payload["top20_final_probability"], start=1):
        lines.append(
            f"| {index} | {row['country']} | {row['strength_score']} | {row['final_probability']}% | "
            f"{row['champion_probability']}% | {row['semi_final_probability']}% | "
            f"{row['quarter_final_probability']}% | {row['round_of_16_probability']}% | "
            f"{row['round_of_32_probability']}% |"
        )
    path.write_text("\n".join(lines), encoding="utf-8")
