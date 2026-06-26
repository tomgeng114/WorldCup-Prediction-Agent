from __future__ import annotations

import json
from pathlib import Path

from app.db import SessionLocal
from app.services.worldcup_draw_audit import build_worldcup_draw_audit, write_worldcup_draw_audit_outputs


def main() -> None:
    years = [2018, 2022]
    with SessionLocal() as db:
        report = build_worldcup_draw_audit(db, years)
        output_dir = Path(__file__).resolve().parents[1] / "reports" / "worldcup_draw_audit"
        paths = write_worldcup_draw_audit_outputs(report, output_dir)

    print(
        json.dumps(
            {
                "phase": "worldcup_draw_audit",
                "outputs": paths,
                "draw_audit_summary": report["draw_audit_summary"],
                "conclusion": report["conclusion"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
