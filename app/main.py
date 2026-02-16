from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import routes
from app.config import settings
from app.services.aggregator import AggregationService
from app.sharepoint.sync import SyncService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

aggregator = AggregationService()
sync_service = SyncService()


async def _on_sync_complete():
    aggregator.load_all(settings.data_dir)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    Path(settings.data_dir).mkdir(exist_ok=True)
    aggregator._data_dir = settings.data_dir

    # Initial load from local data
    aggregator.load_all(settings.data_dir)
    logger.info("Loaded %d client portfolios", len(aggregator.clients))

    # Start SharePoint sync
    sync_service.on_sync_complete(_on_sync_complete)
    sync_service.start()

    # Wire up routes
    routes.aggregator = aggregator
    routes.sync_service = sync_service

    yield

    # Shutdown
    await sync_service.stop()


app = FastAPI(title="Portfolio Dashboard", lifespan=lifespan)
app.include_router(routes.router)

# Serve static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
