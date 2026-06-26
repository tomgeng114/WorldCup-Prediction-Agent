from __future__ import annotations

import json
from pathlib import Path

from app.db import SessionLocal
from app.services.backtest_engine import BacktestEngine
from app.services.worldcup_historical_audit import (
    build_worldcup_historical_audit,
    latest_run_for_years,
    write_worldcup_audit_outputs,
)


def main() -> None:
    years = [2022]
    with SessionLocal() as db:
        run = latest_run_for_years(db, years)
        if run is None or run.total_matches != 64:
            run = BacktestEngine(db, score_mode="calibrated", use_warmup=True).run(years=years)
        report = build_worldcup_historical_audit(db, run.id)
        report["metadata"]["phase"] = "phase1_2022_world_cup"
        report["metadata"]["phase_label"] = "Phase 1: 2022 FIFA World Cup"
        report["conclusion"]["sample_warning"] = "Phase 1 only uses 2022 World Cup 64 matches; validate again with 2018 before final deployment."
        output_dir = Path(__file__).resolve().parents[1] / "reports" / "worldcup_historical_audit_phase1"
        paths = write_worldcup_audit_outputs(report, output_dir, match_report_name="worldcup_2022_report.csv")

    print(
        json.dumps(
            {
                "phase": "phase1_2022_world_cup",
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
