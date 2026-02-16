from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import SharePointSettings, load_sharepoint_settings, save_sharepoint_settings
from app.models.portfolio import AggregatedOverview, ClientPortfolio, SyncStatus, TransactionInfo
from app.sharepoint.client import SharePointClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# These get set by main.py at startup
aggregator = None
sync_service = None


@router.get("/overview", response_model=AggregatedOverview)
async def get_overview():
    return aggregator.overview


@router.get("/clients", response_model=list[ClientPortfolio])
async def get_clients():
    clients = list(aggregator.clients.values())
    # Return without full transaction lists
    result = []
    for c in clients:
        summary = c.model_copy()
        summary.all_transactions = []
        result.append(summary)
    result.sort(key=lambda c: c.total_value, reverse=True)
    return result


@router.get("/clients/{filename}", response_model=ClientPortfolio)
async def get_client(filename: str):
    client = aggregator.get_client(filename)
    if not client:
        raise HTTPException(status_code=404, detail=f"Client '{filename}' not found")
    return client


@router.get("/clients/{filename}/transactions", response_model=list[TransactionInfo])
async def get_client_transactions(filename: str, limit: int = 100, offset: int = 0):
    client = aggregator.get_client(filename)
    if not client:
        raise HTTPException(status_code=404, detail=f"Client '{filename}' not found")
    return client.all_transactions[offset : offset + limit]


@router.get("/sync/status", response_model=SyncStatus)
async def get_sync_status():
    return sync_service.status


@router.post("/sync/trigger")
async def trigger_sync():
    await sync_service.trigger_sync()
    aggregator.load_all(aggregator._data_dir)
    return {"status": "ok", "message": "Sync triggered"}


# ── Settings API ──

class SettingsResponse(BaseModel):
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret_set: bool = False
    sharepoint_site_id: str = ""
    sharepoint_folder_path: str = ""
    sync_interval: int = 300
    connected: bool = False


class SettingsUpdate(BaseModel):
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""
    sharepoint_site_id: str = ""
    sharepoint_folder_path: str = ""
    sync_interval: int = 300


@router.get("/settings")
async def get_settings() -> SettingsResponse:
    sp = load_sharepoint_settings()
    return SettingsResponse(
        azure_tenant_id=sp.azure_tenant_id,
        azure_client_id=sp.azure_client_id,
        azure_client_secret_set=bool(sp.azure_client_secret),
        sharepoint_site_id=sp.sharepoint_site_id,
        sharepoint_folder_path=sp.sharepoint_folder_path,
        sync_interval=sp.sync_interval,
        connected=sp.connected,
    )


@router.post("/settings")
async def update_settings(update: SettingsUpdate):
    current = load_sharepoint_settings()
    # If secret is empty string, keep the existing one
    secret = update.azure_client_secret if update.azure_client_secret else current.azure_client_secret
    has_creds = bool(update.azure_tenant_id and update.azure_client_id and secret)

    sp = SharePointSettings(
        azure_tenant_id=update.azure_tenant_id,
        azure_client_id=update.azure_client_id,
        azure_client_secret=secret,
        sharepoint_site_id=update.sharepoint_site_id,
        sharepoint_folder_path=update.sharepoint_folder_path,
        sync_interval=update.sync_interval,
        connected=has_creds,
    )
    save_sharepoint_settings(sp)

    # Reconfigure the sync service with new settings
    await sync_service.reconfigure(sp)

    return {"status": "ok", "message": "Einstellungen gespeichert"}


@router.post("/settings/test")
async def test_connection():
    sp = load_sharepoint_settings()
    if not all([sp.azure_tenant_id, sp.azure_client_id, sp.azure_client_secret]):
        raise HTTPException(status_code=400, detail="SharePoint-Zugangsdaten nicht konfiguriert")

    client = SharePointClient(
        tenant_id=sp.azure_tenant_id,
        client_id=sp.azure_client_id,
        client_secret=sp.azure_client_secret,
        site_id=sp.sharepoint_site_id,
    )
    try:
        files = await client.list_portfolio_files(sp.sharepoint_folder_path)
        await client.close()
        return {
            "status": "ok",
            "message": f"Verbindung erfolgreich! {len(files)} .portfolio Datei(en) gefunden.",
            "files": [f["name"] for f in files],
        }
    except Exception as e:
        await client.close()
        logger.error("SharePoint connection test failed: %s", e)
        raise HTTPException(status_code=400, detail=f"Verbindung fehlgeschlagen: {e}")


@router.get("/settings/browse")
async def browse_sharepoint(path: str = ""):
    """Browse SharePoint drives and folders to find the right path."""
    sp = load_sharepoint_settings()
    if not all([sp.azure_tenant_id, sp.azure_client_id, sp.azure_client_secret, sp.sharepoint_site_id]):
        raise HTTPException(status_code=400, detail="SharePoint-Zugangsdaten nicht konfiguriert")

    client = SharePointClient(
        tenant_id=sp.azure_tenant_id,
        client_id=sp.azure_client_id,
        client_secret=sp.azure_client_secret,
        site_id=sp.sharepoint_site_id,
    )
    try:
        result = await client.browse(path)
        await client.close()
        return result
    except Exception as e:
        await client.close()
        logger.error("SharePoint browse failed: %s", e)
        raise HTTPException(status_code=400, detail=f"Fehler: {e}")
