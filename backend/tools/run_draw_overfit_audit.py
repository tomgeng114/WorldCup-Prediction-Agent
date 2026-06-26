from __future__ import annotations

import json
from pathlib import Path

from app.db import SessionLocal
from app.services.draw_overfit_audit import build_draw_overfit_audit, write_draw_overfit_outputs


def main() -> None:
    years = [2018, 2022]
    with SessionLocal() as db:
        report = build_draw_overfit_audit(db, years)
        output_dir = Path(__file__).resolve().parents[1] / "reports" / "draw_overfit_audit"
        paths = write_draw_overfit_outputs(report, output_dir)

    print(
        json.dumps(
            {
                "phase": "draw_overfit_audit",
                "outputs": paths,
                "prediction_type_stats": report["prediction_type_stats"],
                "draw_pick_summary": report["draw_pick_summary"],
                "roi_by_prediction_type": report["roi_by_prediction_type"],
                "overfit_detection": report["overfit_detection"],
                "conclusion": report["conclusion"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
