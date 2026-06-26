import csv
import io

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models import Match

router = APIRouter(prefix="/exports", tags=["exports"])


@router.get("/history.csv")
def export_history_csv(db: Session = Depends(get_db)) -> StreamingResponse:
    matches = db.scalars(
        select(Match)
        .where(Match.status == "finished")
        .options(joinedload(Match.home_team), joinedload(Match.away_team), joinedload(Match.prediction))
        .order_by(Match.kickoff_time.desc())
    ).unique().all()

    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(
        [
            "Date",
            "Competition",
            "Home Team",
            "Away Team",
            "Predicted Result",
            "Predicted Score",
            "Actual Score",
        ]
    )
    for match in matches:
        writer.writerow(
            [
                match.kickoff_time.isoformat(),
                match.competition,
                match.home_team.name,
                match.away_team.name,
                match.prediction.predicted_result,
                match.prediction.predicted_score,
                f"{match.home_score}-{match.away_score}",
            ]
        )
    stream.seek(0)
    return StreamingResponse(
        iter([stream.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="worldcup-history.csv"'},
    )


@router.get("/pre-match-report/{match_id}", response_class=HTMLResponse)
def export_pre_match_report(match_id: int, db: Session = Depends(get_db)) -> str:
    match = db.scalar(
        select(Match)
        .where(Match.id == match_id)
        .options(joinedload(Match.home_team), joinedload(Match.away_team), joinedload(Match.prediction), joinedload(Match.odds))
    )
    if not match or not match.prediction:
        return "<h1>Report not found</h1>"

    return f"""
    <html>
      <head>
        <title>Pre-match Report</title>
        <style>
          body {{ font-family: Segoe UI, sans-serif; background: #08101d; color: #f1f5f9; padding: 32px; }}
          .card {{ max-width: 900px; margin: 0 auto; background: #0f1a2f; border: 1px solid #22304c; border-radius: 24px; padding: 24px; }}
          h1, h2 {{ margin: 0 0 12px; }}
          p {{ line-height: 1.7; color: #cbd5e1; }}
        </style>
      </head>
      <body>
        <div class="card">
          <h1>{match.home_team.name} vs {match.away_team.name}</h1>
          <h2>AI Pre-match Report</h2>
          <p>{match.prediction.report_preview}</p>
          <p>Main pick: {match.prediction.predicted_result}</p>
          <p>Projected score: {match.prediction.predicted_score}</p>
          <p>Backup scores: {match.prediction.backup_scores}</p>
          <p>Confidence: {match.prediction.confidence:.2f}/5</p>
          <p>Odds snapshot: home {match.odds.home_win_odds}, draw {match.odds.draw_odds}, away {match.odds.away_win_odds}</p>
          <p>Model explanation: {match.prediction.explanation}</p>
        </div>
      </body>
    </html>
    """
