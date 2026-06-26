from __future__ import annotations

import json
from pathlib import Path

from app.db import SessionLocal
from app.services.group_stage_failure_audit import build_group_stage_failure_audit, write_group_stage_failure_outputs


def main() -> None:
    years = [2018, 2022]
    with SessionLocal() as db:
        report = build_group_stage_failure_audit(db, years)
        output_dir = Path(__file__).resolve().parents[1] / "reports" / "group_stage_failure_audit"
        paths = write_group_stage_failure_outputs(report, output_dir)

    print(
        json.dumps(
            {
                "phase": "group_stage_failure_audit",
                "outputs": paths,
                "summary": report["summary"],
                "conclusion": report["conclusion"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
