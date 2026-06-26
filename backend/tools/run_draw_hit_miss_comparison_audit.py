from __future__ import annotations

import json
from pathlib import Path

from app.db import SessionLocal
from app.services.draw_hit_miss_comparison_audit import (
    build_draw_hit_miss_comparison_audit,
    write_draw_hit_miss_comparison_outputs,
)


def main() -> None:
    years = [2018, 2022]
    with SessionLocal() as db:
        report = build_draw_hit_miss_comparison_audit(db, years)
        output_dir = Path(__file__).resolve().parents[1] / "reports" / "draw_hit_miss_comparison_audit"
        paths = write_draw_hit_miss_comparison_outputs(report, output_dir)

    print(
        json.dumps(
            {
                "phase": "draw_hit_miss_comparison_audit",
                "outputs": paths,
                "summary": report["summary"],
                "profiles": report["profiles"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
