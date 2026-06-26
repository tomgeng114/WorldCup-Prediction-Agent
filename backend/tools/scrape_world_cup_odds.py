from __future__ import annotations

import base64
import csv
import gzip
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from pathlib import Path
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy import select

from app.db import SessionLocal
from app.models import WorldCupMatch
from app.services.phase2_market import import_world_cup_odds_csv


CHECKBESTODDS_URLS = {
    2018: "https://checkbestodds.com/football-odds/archive-world-cup-2018",
    2022: "https://checkbestodds.com/football-odds/archive-world-cup-2022",
}
ODDSPORTAL_URLS = {
    2018: "https://www.oddsportal.com/football/world/world-cup-2018/results/",
    2022: "https://www.oddsportal.com/football/world/world-cup-2022/results/",
}
ODDSPORTAL_ARCHIVE_TOKENS = {
    2018: "fFsiH75r",
    2022: "fRgR6gtF",
}
ODDSPORTAL_ARCHIVE_MASK = (
    "X262144X16384X0X0X134217728X0X0X0X0X0X0X0X0X134217729X0X0X1048576"
    "X0X1024X40X0X32X0X0X0X0X0X0X0X536870912X2560X2048X0X33554560"
    "X8519680X0X0X0X524288"
)
ODDSPORTAL_AES_PASSWORD = b"J*8sQ!p$7aD_fR2yW@gHn*3bVp#sAdLd_k"
ODDSPORTAL_AES_SALT = b"5b9a8f2c3e6d1a4b7c8e9d0f1a2b3c4d"
WORLD_CUP_WINDOWS = {
    2018: (datetime(2018, 6, 14), datetime(2018, 7, 16)),
    2022: (datetime(2022, 11, 20), datetime(2022, 12, 19)),
}
TEAM_ALIASES = {
    "Korea": "South Korea",
    "USA": "USA",
}


@dataclass
class ScrapeSummary:
    year: int
    scraped_rows: int
    matched_rows: int
    missing_matches: list[str]
    output_path: Path
    source_status: dict[str, str]


def _fetch(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", errors="ignore")
        except Exception as exc:  # noqa: BLE001 - network source can fail transiently.
            last_error = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise last_error or RuntimeError(f"failed to fetch {url}")


def _html_to_lines(html: str) -> list[str]:
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"</(?:p|div|tr|h\d)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]


def scrape_checkbestodds(year: int) -> list[dict]:
    html = _fetch(CHECKBESTODDS_URLS[year])
    lines = _html_to_lines(html)
    current_date = ""
    rows: list[dict] = []
    date_pattern = re.compile(r"^(\d{1,2} [A-Za-z]+ \d{4}) 1 X 2$")
    match_pattern = re.compile(
        r"^(\d{1,2}:\d{2}) ([^-]+?) - ([^-]+?) "
        r"(\d+(?:\.\d+)?) (\d+(?:\.\d+)?) (\d+(?:\.\d+)?)$"
    )
    for line in lines:
        date_match = date_pattern.match(line)
        if date_match:
            current_date = date_match.group(1)
            continue
        match = match_pattern.match(line)
        if not match or not current_date:
            continue
        kickoff = datetime.strptime(f"{current_date} {match.group(1)}", "%d %B %Y %H:%M")
        home_team = TEAM_ALIASES.get(match.group(2).strip(), match.group(2).strip())
        away_team = TEAM_ALIASES.get(match.group(3).strip(), match.group(3).strip())
        rows.append(
            {
                "match_date": kickoff,
                "home_team": home_team,
                "away_team": away_team,
                "home_win_odds": float(match.group(4)),
                "draw_odds": float(match.group(5)),
                "away_win_odds": float(match.group(6)),
                "source": CHECKBESTODDS_URLS[year],
            }
        )
    return rows


def _oddsportal_archive_url(year: int, page: int) -> str:
    return (
        "https://www.oddsportal.com/ajax-sport-country-tournament-archive_/"
        f"1/{ODDSPORTAL_ARCHIVE_TOKENS[year]}/{ODDSPORTAL_ARCHIVE_MASK}/1/0/?page={page}"
    )


def _decrypt_oddsportal_payload(payload: str) -> dict:
    encrypted_payload = base64.b64decode(payload).decode("utf-8")
    ciphertext_b64, iv_hex = encrypted_payload.split(":", 1)
    key = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=ODDSPORTAL_AES_SALT,
        iterations=1000,
    ).derive(ODDSPORTAL_AES_PASSWORD)
    cipher = Cipher(algorithms.AES(key), modes.CBC(bytes.fromhex(iv_hex)))
    decrypted = cipher.decryptor().update(base64.b64decode(ciphertext_b64))
    unpadder = padding.PKCS7(128).unpadder()
    try:
        decrypted = unpadder.update(decrypted) + unpadder.finalize()
    except ValueError:
        pass
    if len(decrypted) >= 2 and decrypted[:2] == b"\x1f\x8b":
        decrypted = gzip.decompress(decrypted)
    return json.loads(decrypted.decode("utf-8"))


def _fetch_oddsportal_archive_page(year: int, page: int) -> dict:
    request = Request(
        _oddsportal_archive_url(year, page),
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": ODDSPORTAL_URLS[year],
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/plain, */*",
        },
    )
    with urlopen(request, timeout=30) as response:
        return _decrypt_oddsportal_payload(response.read().decode("utf-8"))


def scrape_oddsportal(year: int) -> list[dict]:
    rows: list[dict] = []
    seen_event_ids: set[int] = set()
    for page in range(1, 4):
        payload = _fetch_oddsportal_archive_page(year, page)
        event_rows = payload.get("d", {}).get("rows", [])
        if not event_rows:
            break
        for event in event_rows:
            event_id = event.get("id")
            if event_id in seen_event_ids:
                continue
            seen_event_ids.add(event_id)
            odds = event.get("odds") or []
            if len(odds) < 3:
                continue
            try:
                match_date = datetime.fromtimestamp(int(event["date-start-timestamp"]))
                window_start, window_end = WORLD_CUP_WINDOWS[year]
                if not (window_start <= match_date < window_end):
                    continue
                if event.get("tournament-name") != f"World Cup {year}":
                    continue
                home_team = TEAM_ALIASES.get(event["home-name"], event["home-name"])
                away_team = TEAM_ALIASES.get(event["away-name"], event["away-name"])
                rows.append(
                    {
                        "match_date": match_date,
                        "home_team": home_team,
                        "away_team": away_team,
                        "home_win_odds": float(odds[0]["avgOdds"]),
                        "draw_odds": float(odds[1]["avgOdds"]),
                        "away_win_odds": float(odds[2]["avgOdds"]),
                        "source": f"{ODDSPORTAL_URLS[year]}#ajax-page-{page}",
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
    return rows


def scrape_oddsportal_status(year: int) -> str:
    try:
        rows = scrape_oddsportal(year)
    except Exception as exc:  # noqa: BLE001 - source availability is diagnostic only.
        return f"ajax_fetch_failed:{type(exc).__name__}"
    return f"ajax_decoded_{len(rows)}_rows"


def _merge_by_match(primary: list[dict], fallback: list[dict]) -> list[dict]:
    merged = {(row["home_team"], row["away_team"]): row for row in fallback}
    merged.update({(row["home_team"], row["away_team"]): row for row in primary})
    return list(merged.values())


def _result(match: WorldCupMatch) -> str:
    if match.home_score > match.away_score:
        return "Home Win"
    if match.home_score < match.away_score:
        return "Away Win"
    return "Draw"


def _load_matches(year: int) -> list[WorldCupMatch]:
    with SessionLocal() as db:
        return db.scalars(
            select(WorldCupMatch)
            .where(WorldCupMatch.tournament_year == year)
            .order_by(WorldCupMatch.match_date.asc(), WorldCupMatch.id.asc())
        ).all()


def _match_scraped_row(match: WorldCupMatch, rows: list[dict]) -> dict | None:
    for row in rows:
        if row["home_team"] == match.home_team and row["away_team"] == match.away_team:
            return row
    return None


def build_csv(year: int) -> ScrapeSummary:
    source_status: dict[str, str] = {}
    try:
        checkbest_rows = scrape_checkbestodds(year)
        source_status["checkbestodds"] = f"scraped_{len(checkbest_rows)}_rows"
    except Exception as exc:  # noqa: BLE001 - preserve partial real data from other source.
        checkbest_rows = []
        source_status["checkbestodds"] = f"fetch_failed:{type(exc).__name__}"
    try:
        oddsportal_rows = scrape_oddsportal(year)
        source_status["oddsportal"] = f"ajax_decoded_{len(oddsportal_rows)}_rows"
    except Exception as exc:  # noqa: BLE001 - preserve partial real data from other source.
        oddsportal_rows = []
        source_status["oddsportal"] = f"ajax_fetch_failed:{type(exc).__name__}"
    # OddsPortal returns structured avgOdds from the decoded AJAX payload.
    # CheckBestOdds is kept as a secondary fill source because its archive HTML
    # can mix non-1X2 numeric fields into the plain-text line parser.
    scraped = _merge_by_match(oddsportal_rows, checkbest_rows)
    matches = _load_matches(year)
    output_path = Path(__file__).resolve().parents[1] / "data" / f"world_cup_odds_{year}.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    missing: list[str] = []
    matched_rows: list[dict] = []
    for match in matches:
        row = _match_scraped_row(match, scraped)
        if not row:
            missing.append(f"{match.home_team} - {match.away_team}")
            continue
        matched_rows.append(
            {
                "tournament_year": year,
                "match_id": match.id,
                "match_date": match.match_date.isoformat(sep=" "),
                "home_team": match.home_team,
                "away_team": match.away_team,
                "home_win_odds": row["home_win_odds"],
                "draw_odds": row["draw_odds"],
                "away_win_odds": row["away_win_odds"],
                "handicap": "",
                "handicap_home_odds": "",
                "handicap_draw_odds": "",
                "handicap_away_odds": "",
                "captured_at": row["match_date"].isoformat(sep=" "),
                "source": row["source"],
                "result": _result(match),
            }
        )

    fieldnames = [
        "tournament_year",
        "match_id",
        "match_date",
        "home_team",
        "away_team",
        "home_win_odds",
        "draw_odds",
        "away_win_odds",
        "handicap",
        "handicap_home_odds",
        "handicap_draw_odds",
        "handicap_away_odds",
        "captured_at",
        "source",
        "result",
    ]
    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(matched_rows)

    return ScrapeSummary(
        year=year,
        scraped_rows=len(scraped),
        matched_rows=len(matched_rows),
        missing_matches=missing,
        output_path=output_path,
        source_status=source_status,
    )


def main() -> None:
    summaries = [build_csv(2018), build_csv(2022)]
    with SessionLocal() as db:
        imports = {
            summary.year: import_world_cup_odds_csv(db, summary.output_path)
            for summary in summaries
        }
    for summary in summaries:
        imported = imports[summary.year]
        print(
            {
                "year": summary.year,
                "scraped_rows": summary.scraped_rows,
                "matched_rows": summary.matched_rows,
                "missing_count": len(summary.missing_matches),
                "missing_matches": summary.missing_matches,
                "output_path": str(summary.output_path),
                "source_status": summary.source_status,
                "db_imported": imported.imported,
                "db_updated": imported.updated,
                "db_skipped": imported.skipped,
            }
        )


if __name__ == "__main__":
    main()
