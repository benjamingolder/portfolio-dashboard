from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class SharePointClient:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str, site_id: str):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.site_id = site_id
        self._token: str = ""
        self._token_expires: datetime = datetime.min.replace(tzinfo=timezone.utc)
        self._http = httpx.AsyncClient(timeout=60.0)

    async def _ensure_token(self) -> None:
        now = datetime.now(timezone.utc)
        if self._token and now < self._token_expires:
            return

        url = TOKEN_URL.format(tenant=self.tenant_id)
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
        }
        resp = await self._http.post(url, data=data)
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        self._token_expires = now.replace(second=0) + __import__("datetime").timedelta(
            seconds=body.get("expires_in", 3600) - 60
        )
        logger.info("SharePoint token refreshed")

    async def _headers(self) -> dict[str, str]:
        await self._ensure_token()
        return {"Authorization": f"Bearer {self._token}"}

    async def list_portfolio_files(self, folder_path: str) -> list[dict]:
        """List .portfolio files in a SharePoint folder."""
        headers = await self._headers()
        folder_path = folder_path.strip("/")
        if folder_path:
            url = f"{GRAPH_BASE}/sites/{self.site_id}/drive/root:/{folder_path}:/children"
        else:
            url = f"{GRAPH_BASE}/sites/{self.site_id}/drive/root/children"
        resp = await self._http.get(url, headers=headers)
        if resp.status_code == 404 and folder_path:
            # The path might be relative to the drive root — try without leading component
            # that matches the drive name (e.g. "Shared Documents/X" → just "X")
            parts = folder_path.split("/", 1)
            if len(parts) == 2:
                logger.info("Path not found, retrying with: %s", parts[1])
                url = f"{GRAPH_BASE}/sites/{self.site_id}/drive/root:/{parts[1]}:/children"
                resp = await self._http.get(url, headers=headers)
        resp.raise_for_status()
        items = resp.json().get("value", [])
        return [
            {
                "id": item["id"],
                "name": item["name"],
                "size": item.get("size", 0),
                "lastModified": item.get("lastModifiedDateTime", ""),
            }
            for item in items
            if item.get("name", "").endswith(".portfolio")
        ]

    async def download_file(self, item_id: str) -> bytes:
        """Download a file by its drive item ID."""
        headers = await self._headers()
        url = f"{GRAPH_BASE}/sites/{self.site_id}/drive/items/{item_id}/content"
        resp = await self._http.get(url, headers=headers, follow_redirects=True)
        resp.raise_for_status()
        return resp.content

    async def browse(self, path: str = "") -> dict:
        """Browse drives and folders. Empty path = list drives."""
        headers = await self._headers()
        if not path:
            # List all document libraries (drives) on the site
            url = f"{GRAPH_BASE}/sites/{self.site_id}/drives"
            resp = await self._http.get(url, headers=headers)
            resp.raise_for_status()
            drives = resp.json().get("value", [])
            return {
                "type": "drives",
                "items": [
                    {"name": d["name"], "id": d["id"], "webUrl": d.get("webUrl", "")}
                    for d in drives
                ],
            }
        elif path.startswith("drive:"):
            # List root of a specific drive by ID
            drive_id = path.split(":", 1)[1]
            url = f"{GRAPH_BASE}/sites/{self.site_id}/drives/{drive_id}/root/children"
            resp = await self._http.get(url, headers=headers)
            resp.raise_for_status()
            items = resp.json().get("value", [])
            return {
                "type": "folders",
                "drive_id": drive_id,
                "path": "/",
                "items": [
                    {
                        "name": item["name"],
                        "is_folder": "folder" in item,
                        "size": item.get("size", 0),
                    }
                    for item in items
                ],
            }
        else:
            # List children of a path (uses default drive)
            encoded_path = path.rstrip("/")
            url = f"{GRAPH_BASE}/sites/{self.site_id}/drive/root:{encoded_path}:/children"
            resp = await self._http.get(url, headers=headers)
            resp.raise_for_status()
            items = resp.json().get("value", [])
            return {
                "type": "folders",
                "path": path,
                "items": [
                    {
                        "name": item["name"],
                        "is_folder": "folder" in item,
                        "size": item.get("size", 0),
                    }
                    for item in items
                ],
            }

    async def get_list_items(
        self,
        list_name: str,
        site_id: str | None = None,
        select_fields: list[str] | None = None,
    ) -> list[dict]:
        """Read all items from a SharePoint list via Graph API with paging."""
        headers = await self._headers()
        target_site = site_id or self.site_id

        url = f"{GRAPH_BASE}/sites/{target_site}/lists/{list_name}/items"
        params: dict[str, str] | None = {"$expand": "fields", "$top": "500"}

        all_items: list[dict] = []
        while url:
            resp = await self._http.get(url, headers=headers, params=params)
            resp.raise_for_status()
            body = resp.json()
            for item in body.get("value", []):
                all_items.append(item.get("fields", {}))
            url = body.get("@odata.nextLink")
            params = None  # nextLink already includes params

        return all_items

    async def resolve_site_id(self, hostname: str, site_path: str) -> str:
        """Resolve a SharePoint site URL to its Graph API site ID."""
        headers = await self._headers()
        url = f"{GRAPH_BASE}/sites/{hostname}:/{site_path}"
        resp = await self._http.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()["id"]

    async def list_lists(self, site_id: str | None = None) -> list[dict]:
        """List all SharePoint lists on a site (including hidden)."""
        headers = await self._headers()
        target_site = site_id or self.site_id
        # Include all lists (including hidden ones) by using a broad filter
        url = f"{GRAPH_BASE}/sites/{target_site}/lists?$top=100"
        resp = await self._http.get(url, headers=headers)
        resp.raise_for_status()
        return [
            {"name": lst["name"], "displayName": lst.get("displayName", lst["name"]), "id": lst["id"],
             "template": lst.get("list", {}).get("template", "")}
            for lst in resp.json().get("value", [])
        ]

    async def close(self) -> None:
        await self._http.aclose()
