from __future__ import annotations

import json
from pathlib import Path

from app.db import SessionLocal
from app.services.cold_alert_audit import build_cold_alert_audit, write_cold_alert_audit_outputs


def main() -> None:
    years = [2018, 2022]
    with SessionLocal() as db:
        report = build_cold_alert_audit(db, years)
        output_dir = Path(__file__).resolve().parents[1] / "reports" / "cold_alert_audit"
        paths = write_cold_alert_audit_outputs(report, output_dir)

    print(
        json.dumps(
            {
                "phase": "cold_alert_audit",
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
