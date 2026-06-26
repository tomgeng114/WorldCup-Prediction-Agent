from __future__ import annotations

import json
from pathlib import Path

from app.db import SessionLocal
from app.services.draw_miss_deep_audit import build_draw_miss_deep_audit, write_draw_miss_deep_outputs


def main() -> None:
    years = [2018, 2022]
    with SessionLocal() as db:
        report = build_draw_miss_deep_audit(db, years)
        output_dir = Path(__file__).resolve().parents[1] / "reports" / "draw_miss_deep_audit"
        paths = write_draw_miss_deep_outputs(report, output_dir)

    print(
        json.dumps(
            {
                "phase": "draw_miss_deep_audit",
                "outputs": paths,
                "summary": report["summary"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
