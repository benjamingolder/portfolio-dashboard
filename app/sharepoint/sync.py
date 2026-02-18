from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.config import SharePointSettings, load_sharepoint_settings, settings
from app.models.portfolio import SyncStatus
from app.sharepoint.client import SharePointClient

logger = logging.getLogger(__name__)


MANIFEST_FILE = Path(settings.data_dir) / ".sp_manifest.json"


def _load_manifest() -> dict[str, str]:
    """Load the persisted SharePoint file manifest from disk."""
    try:
        if MANIFEST_FILE.exists():
            return json.loads(MANIFEST_FILE.read_text())
    except Exception:
        pass
    return {}


def _save_manifest(timestamps: dict[str, str]) -> None:
    """Persist the SharePoint file manifest to disk."""
    try:
        MANIFEST_FILE.parent.mkdir(exist_ok=True)
        MANIFEST_FILE.write_text(json.dumps(timestamps, indent=2))
    except Exception as e:
        logger.warning("Could not save sync manifest: %s", e)


class SyncService:
    def __init__(self) -> None:
        self.status = SyncStatus()
        self._client: SharePointClient | None = None
        self._task: asyncio.Task | None = None
        self._file_timestamps: dict[str, str] = _load_manifest()
        self._on_sync_complete: list = []  # callbacks
        self._sp_settings: SharePointSettings | None = None
        self.finance_service = None  # set by main.py

    def on_sync_complete(self, callback) -> None:
        self._on_sync_complete.append(callback)

    def start(self) -> None:
        sp = load_sharepoint_settings()
        self._sp_settings = sp
        if not all([sp.azure_tenant_id, sp.azure_client_id, sp.azure_client_secret]):
            logger.warning("SharePoint credentials not configured, sync disabled. Place .portfolio files in data/ manually.")
            self.status.connected = False
            return
        self._client = SharePointClient(
            tenant_id=sp.azure_tenant_id,
            client_id=sp.azure_client_id,
            client_secret=sp.azure_client_secret,
            site_id=sp.sharepoint_site_id,
        )
        self.status.connected = True
        self._task = asyncio.create_task(self._sync_loop())
        logger.info("SharePoint sync service started (interval: %ds)", sp.sync_interval)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.close()
            self._client = None
        self._task = None

    async def reconfigure(self, sp: SharePointSettings) -> None:
        """Stop current sync and restart with new settings."""
        await self.stop()
        self._sp_settings = sp
        self._file_timestamps.clear()
        _save_manifest(self._file_timestamps)
        if not all([sp.azure_tenant_id, sp.azure_client_id, sp.azure_client_secret]):
            logger.info("SharePoint credentials cleared, sync disabled.")
            self.status.connected = False
            return
        self._client = SharePointClient(
            tenant_id=sp.azure_tenant_id,
            client_id=sp.azure_client_id,
            client_secret=sp.azure_client_secret,
            site_id=sp.sharepoint_site_id,
        )
        self.status.connected = True
        self._task = asyncio.create_task(self._sync_loop())
        logger.info("SharePoint sync reconfigured (interval: %ds)", sp.sync_interval)

    async def trigger_sync(self) -> None:
        await self._do_sync()

    async def _sync_loop(self) -> None:
        interval = self._sp_settings.sync_interval if self._sp_settings else 300
        while True:
            try:
                await self._do_sync()
            except Exception:
                logger.exception("Sync error")
            await asyncio.sleep(interval)

    async def _do_sync(self) -> None:
        if not self._client or not self._sp_settings:
            return
        self.status.is_syncing = True
        self.status.errors = []
        data_dir = Path(settings.data_dir)
        data_dir.mkdir(exist_ok=True)

        try:
            try:
                files = await self._client.list_portfolio_files(self._sp_settings.sharepoint_folder_path)
                sp_names = {f["name"] for f in files}
                changed = False

                # Download new or changed files
                for f in files:
                    name = f["name"]
                    last_mod = f["lastModified"]
                    if self._file_timestamps.get(name) == last_mod:
                        continue
                    logger.info("Downloading %s (modified: %s)", name, last_mod)
                    try:
                        content = await self._client.download_file(f["id"])
                        (data_dir / name).write_bytes(content)
                        self._file_timestamps[name] = last_mod
                        changed = True
                    except Exception as e:
                        logger.error("Failed to download %s: %s", name, e)
                        self.status.errors.append(f"Download failed: {name}: {e}")

                # Delete any local .portfolio file not present in SharePoint
                for local_file in data_dir.glob("*.portfolio"):
                    if local_file.name not in sp_names:
                        local_file.unlink()
                        self._file_timestamps.pop(local_file.name, None)
                        logger.info("Deleted local file not in SharePoint: %s", local_file.name)
                        changed = True

                _save_manifest(self._file_timestamps)
                self.status.files_synced = len(self._file_timestamps)
                self.status.last_sync = datetime.now(timezone.utc)

                if changed:
                    for cb in self._on_sync_complete:
                        try:
                            await cb()
                        except Exception:
                            logger.exception("Sync callback error")
            except Exception as e:
                logger.error("Sync failed: %s", e)
                self.status.errors.append(str(e))

            # Sync finance data from SharePoint list
            if self.finance_service and self._sp_settings and self._sp_settings.finance_site_id:
                try:
                    await self.finance_service.sync(
                        client=self._client,
                        site_id=self._sp_settings.finance_site_id,
                        list_name=self._sp_settings.finance_list_name or "Kontobewegungen",
                    )
                except Exception as e:
                    logger.error("Finance sync failed: %s", e)
                    self.status.errors.append(f"Finance: {e}")
        finally:
            self.status.is_syncing = False
