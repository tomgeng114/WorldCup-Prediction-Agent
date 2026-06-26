from __future__ import annotations

import json
from pathlib import Path

from app.db import SessionLocal
from app.services.draw_risk_threshold_audit import build_draw_risk_threshold_audit, write_draw_risk_threshold_outputs


def main() -> None:
    years = [2018, 2022]
    with SessionLocal() as db:
        report = build_draw_risk_threshold_audit(db, years)
        output_dir = Path(__file__).resolve().parents[1] / "reports" / "draw_risk_threshold_audit"
        paths = write_draw_risk_threshold_outputs(report, output_dir)

    print(
        json.dumps(
            {
                "phase": "draw_risk_threshold_audit",
                "outputs": paths,
                "summary": report["summary"],
                "ranking": report["ranking"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
