from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import SharePointSettings, load_sharepoint_settings, save_sharepoint_settings
from app.models.finance import FinanceOverview, FinanceTransaction
from app.models.portfolio import AggregatedOverview, ClientPortfolio, SyncStatus, TransactionInfo
from app.sharepoint.client import SharePointClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# These get set by main.py at startup
aggregator = None
finance_service = None
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


# ── Finance API ──

@router.get("/finance/overview", response_model=FinanceOverview)
async def get_finance_overview():
    return finance_service.overview


@router.get("/finance/transactions", response_model=list[FinanceTransaction])
async def get_finance_transactions(
    search: str = "",
    kategorie: str = "",
    art: str = "",
    konto: str = "",
    start_datum: str = "",
    end_datum: str = "",
    sort_by: str = "datum",
    sort_dir: str = "desc",
    limit: int = 5000,
    offset: int = 0,
):
    filtered = finance_service.get_filtered(search, kategorie, art, konto, start_datum, end_datum)
    reverse = sort_dir == "desc"
    filtered.sort(key=lambda t: getattr(t, sort_by, t.datum), reverse=reverse)
    return filtered[offset : offset + limit]


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
    finance_site_id: str = ""
    finance_list_name: str = "Kontobewegungen"


class SettingsUpdate(BaseModel):
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""
    sharepoint_site_id: str = ""
    sharepoint_folder_path: str = ""
    sync_interval: int = 300
    finance_site_id: str = ""
    finance_list_name: str = "Kontobewegungen"


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
        finance_site_id=sp.finance_site_id,
        finance_list_name=sp.finance_list_name,
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
        finance_site_id=update.finance_site_id,
        finance_list_name=update.finance_list_name,
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


@router.get("/settings/lists")
async def list_sharepoint_lists(site_id: str = ""):
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
        target = site_id or sp.finance_site_id or sp.sharepoint_site_id
        lists = await client.list_lists(site_id=target)
        await client.close()
        return lists
    except Exception as e:
        await client.close()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/settings/resolve-site")
async def resolve_site(hostname: str, path: str):
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
        headers = await client._headers()
        url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:/{path}"
        resp = await client._http.get(url, headers=headers)
        resp.raise_for_status()
        body = resp.json()
        await client.close()
        return {"site_id": body.get("id"), "displayName": body.get("displayName"), "webUrl": body.get("webUrl"), "raw_id": body.get("id")}
    except Exception as e:
        await client.close()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/settings/debug-list")
async def debug_list(list_name: str = "Kontobewegungen"):
    """Debug: try to access a specific list and return raw response."""
    sp = load_sharepoint_settings()
    client = SharePointClient(
        tenant_id=sp.azure_tenant_id,
        client_id=sp.azure_client_id,
        client_secret=sp.azure_client_secret,
        site_id=sp.sharepoint_site_id,
    )
    headers = await client._headers()
    target_site = sp.finance_site_id or sp.sharepoint_site_id
    results = {}

    # 1) Try direct list by name
    url1 = f"https://graph.microsoft.com/v1.0/sites/{target_site}/lists/{list_name}"
    r1 = await client._http.get(url1, headers=headers)
    results["by_name"] = {"status": r1.status_code, "body": r1.json() if r1.status_code < 500 else r1.text}

    # 2) Try listing all lists with select=*
    url2 = f"https://graph.microsoft.com/v1.0/sites/{target_site}/lists?$select=id,displayName,name,webUrl,list"
    r2 = await client._http.get(url2, headers=headers)
    results["all_lists"] = {"status": r2.status_code, "body": r2.json() if r2.status_code < 500 else r2.text}

    # 3) Try filtering by displayName
    url3 = f"https://graph.microsoft.com/v1.0/sites/{target_site}/lists?$filter=displayName eq '{list_name}'"
    r3 = await client._http.get(url3, headers=headers)
    results["by_filter"] = {"status": r3.status_code, "body": r3.json() if r3.status_code < 500 else r3.text}

    # 4) Try including hidden lists
    url4 = f"https://graph.microsoft.com/v1.0/sites/{target_site}/lists?$select=id,displayName,name,webUrl,list&$filter=list/hidden eq false or list/hidden eq true"
    r4 = await client._http.get(url4, headers=headers)
    results["with_hidden"] = {"status": r4.status_code, "body": r4.json() if r4.status_code < 500 else r4.text}

    # 5) Check app permissions
    url5 = f"https://graph.microsoft.com/v1.0/sites/{target_site}/permissions"
    r5 = await client._http.get(url5, headers=headers)
    results["permissions"] = {"status": r5.status_code, "body": r5.json() if r5.status_code < 500 else r5.text}

    # 6) Try items endpoint directly
    url6 = f"https://graph.microsoft.com/v1.0/sites/{target_site}/lists/Kontobewegungen/items?$expand=fields&$top=5"
    r6 = await client._http.get(url6, headers=headers)
    results["items_by_name"] = {"status": r6.status_code, "body": r6.json() if r6.status_code < 500 else r6.text}

    # 7) Try items by list ID
    list_id = "aeda2da8-679c-484d-9d74-d30fe5272096"
    url7 = f"https://graph.microsoft.com/v1.0/sites/{target_site}/lists/{list_id}/items?$expand=fields&$top=5"
    r7 = await client._http.get(url7, headers=headers)
    results["items_by_id"] = {"status": r7.status_code, "body": r7.json() if r7.status_code < 500 else r7.text}

    await client.close()
    return results


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
