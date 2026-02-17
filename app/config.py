from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

SETTINGS_FILE = Path("data/settings.json")


class Settings(BaseSettings):
    """Boot-time settings from env (fallback only)."""
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""
    sharepoint_site_id: str = ""
    sharepoint_folder_path: str = ""
    sync_interval: int = 300
    base_currency: str = "CHF"
    data_dir: str = "data"

    # CloudFlare Access
    cf_access_enabled: bool = False
    cf_access_team_domain: str = ""  # e.g. "golders" for golders.cloudflareaccess.com
    cf_access_aud: str = ""  # Audience tag from the Access policy

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


class SharePointSettings(BaseModel):
    """User-configurable SharePoint settings, persisted to JSON."""
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""
    sharepoint_site_id: str = ""
    sharepoint_folder_path: str = ""
    sync_interval: int = 300
    connected: bool = False
    finance_site_id: str = ""
    finance_list_name: str = "Kontobewegungen"


def load_sharepoint_settings() -> SharePointSettings:
    """Load settings from JSON file, falling back to env vars."""
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
            return SharePointSettings(**data)
        except Exception:
            logger.warning("Failed to read settings.json, using defaults")

    # Fall back to env-based settings
    env = Settings()
    return SharePointSettings(
        azure_tenant_id=env.azure_tenant_id,
        azure_client_id=env.azure_client_id,
        azure_client_secret=env.azure_client_secret,
        sharepoint_site_id=env.sharepoint_site_id,
        sharepoint_folder_path=env.sharepoint_folder_path,
        sync_interval=env.sync_interval,
        connected=bool(env.azure_tenant_id and env.azure_client_id and env.azure_client_secret),
    )


def save_sharepoint_settings(sp: SharePointSettings) -> None:
    """Persist settings to JSON file."""
    SETTINGS_FILE.parent.mkdir(exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(sp.model_dump(), indent=2))
    logger.info("SharePoint settings saved")


# Global boot-time settings (for data_dir etc.)
settings = Settings()
