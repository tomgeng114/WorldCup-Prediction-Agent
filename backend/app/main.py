from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db import Base, ensure_runtime_schema, engine
from app.routers import backtest, calibration, dashboard, data_sources, draw_analysis, evaluation, exports, history, lineups, market_backtest, matches, odds, phase5, phase71, phase72, phase8, predict, predictions, statistics, value_engine, world_cup_specialist
from app.services.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_runtime_schema()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": settings.app_name}


app.include_router(matches.router, prefix=settings.api_prefix)
app.include_router(odds.router, prefix=settings.api_prefix)
app.include_router(predict.router, prefix=settings.api_prefix)
app.include_router(dashboard.router, prefix=settings.api_prefix)
app.include_router(history.router, prefix=settings.api_prefix)
app.include_router(predictions.router, prefix=settings.api_prefix)
app.include_router(exports.router, prefix=settings.api_prefix)
app.include_router(data_sources.router, prefix=settings.api_prefix)
app.include_router(draw_analysis.router, prefix=settings.api_prefix)
app.include_router(statistics.statistics_router, prefix=settings.api_prefix)
app.include_router(statistics.roi_router, prefix=settings.api_prefix)
app.include_router(statistics.results_router, prefix=settings.api_prefix)
app.include_router(backtest.router, prefix=settings.api_prefix)
app.include_router(market_backtest.router, prefix=settings.api_prefix)
app.include_router(phase5.router, prefix=settings.api_prefix)
app.include_router(calibration.router, prefix=settings.api_prefix)
app.include_router(value_engine.router, prefix=settings.api_prefix)
app.include_router(world_cup_specialist.router, prefix=settings.api_prefix)
app.include_router(phase71.router, prefix=settings.api_prefix)
app.include_router(phase72.router, prefix=settings.api_prefix)
app.include_router(phase8.router, prefix=settings.api_prefix)
app.include_router(lineups.router, prefix=settings.api_prefix)
app.include_router(evaluation.router, prefix=settings.api_prefix)
