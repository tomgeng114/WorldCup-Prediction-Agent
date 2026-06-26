from __future__ import annotations

import csv
import json
from pathlib import Path

from app.db import SessionLocal
from app.services.backtest_engine import BacktestEngine
from app.services.worldcup_historical_audit import (
    build_worldcup_historical_audit,
    latest_run_for_years,
    write_worldcup_audit_outputs,
)


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    years = [2018, 2022]
    with SessionLocal() as db:
        run = BacktestEngine(db, score_mode="calibrated", use_warmup=True).run(years=years)
        report = build_worldcup_historical_audit(db, run.id)
        report["metadata"]["phase"] = "combined_2018_2022_world_cup"
        report["metadata"]["phase_label"] = "Combined Audit: 2018 + 2022 FIFA World Cup"
        report["conclusion"]["sample_warning"] = "Combined sample uses 2018 and 2022 World Cup 128 matches."
        output_dir = Path(__file__).resolve().parents[1] / "reports" / "worldcup_historical_audit_combined"
        paths = write_worldcup_audit_outputs(report, output_dir, match_report_name="worldcup_2018_2022_report.csv")

        matches_2018 = [row for row in report["matches"] if row["tournament_year"] == 2018]
        matches_2022 = [row for row in report["matches"] if row["tournament_year"] == 2022]
        paths["worldcup_2018_report_csv"] = str(output_dir / "worldcup_2018_report.csv")
        paths["worldcup_2022_report_csv"] = str(output_dir / "worldcup_2022_report.csv")
        _write_csv(Path(paths["worldcup_2018_report_csv"]), matches_2018)
        _write_csv(Path(paths["worldcup_2022_report_csv"]), matches_2022)

    print(
        json.dumps(
            {
                "phase": "combined_2018_2022_world_cup",
                "run_id": run.id,
                "outputs": paths,
                "overall": report["overall"],
                "conclusion": report["conclusion"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
