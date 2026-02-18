from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import routes
from app.auth import CloudFlareAccessMiddleware
from app.config import settings
from app.services.aggregator import AggregationService
from app.services.finance import FinanceService
from app.sharepoint.sync import SyncService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

aggregator = AggregationService()
finance_service = FinanceService()
sync_service = SyncService()


async def _on_sync_complete():
    aggregator.load_all(settings.data_dir)


async def _watch_data_dir():
    """Background task: reload portfolios when files are added or removed."""
    while True:
        await asyncio.sleep(15)
        try:
            if aggregator.needs_reload(settings.data_dir):
                logger.info("Data directory changed – reloading portfolios")
                aggregator.load_all(settings.data_dir)
        except Exception:
            logger.exception("Error in data directory watcher")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    Path(settings.data_dir).mkdir(exist_ok=True)
    aggregator._data_dir = settings.data_dir

    # Initial load from local data
    aggregator.load_all(settings.data_dir)
    logger.info("Loaded %d client portfolios", len(aggregator.clients))

    # Start SharePoint sync
    sync_service.finance_service = finance_service
    sync_service.on_sync_complete(_on_sync_complete)
    sync_service.start()

    # Watch data directory for file changes (add/remove)
    watcher_task = asyncio.create_task(_watch_data_dir())

    # Wire up routes
    routes.aggregator = aggregator
    routes.finance_service = finance_service
    routes.sync_service = sync_service

    yield

    # Shutdown
    watcher_task.cancel()
    await sync_service.stop()


app = FastAPI(title="Portfolio Dashboard", lifespan=lifespan)

# CloudFlare Access JWT validation
if settings.cf_access_enabled:
    if settings.cf_access_team_domain and settings.cf_access_aud:
        app.add_middleware(
            CloudFlareAccessMiddleware,
            team_domain=settings.cf_access_team_domain,
            audience=settings.cf_access_aud,
        )
        logger.info("CloudFlare Access authentication enabled (team: %s)", settings.cf_access_team_domain)
    else:
        logger.warning("CF_ACCESS_ENABLED=true but team_domain or aud not set — auth disabled!")
else:
    logger.info("CloudFlare Access authentication disabled (set CF_ACCESS_ENABLED=true to enable)")

app.include_router(routes.router)

# Serve static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
