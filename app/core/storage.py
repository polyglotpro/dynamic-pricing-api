import io
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd
import httpx
from fastapi import HTTPException
from vercel.blob import AsyncBlobClient


@dataclass
class BlobArtifact:
    path: str
    pathname: str
    url: Optional[str] = None
    download_url: Optional[str] = None


class BlobStorage:
    """
    Thin storage adapter so route handlers do not talk to the filesystem or Blob directly.
    """

    def __init__(self, root_prefix: str = "data"):
        self.root_prefix = root_prefix.rstrip("/")

    def _require_token(self) -> None:
        if not os.getenv("BLOB_READ_WRITE_TOKEN"):
            raise HTTPException(status_code=500, detail="Missing BLOB_READ_WRITE_TOKEN environment variable")

    def _artifact_path(self, domain: str, brand: str, timestamp: str) -> str:
        return f"{self.root_prefix}/{domain}/{brand}_{domain}_{timestamp}.csv"

    def _debug_path(self, name: str) -> str:
        safe_name = name.strip().replace(" ", "_")
        return f"{self.root_prefix}/debug/{safe_name}.json"

    def _metadata_path(self, name: str = "upload_history") -> str:
        return f"{self.root_prefix}/metadata/{name}.json"

    def _latest_manifest_path(self) -> str:
        return f"{self.root_prefix}/metadata/latest_manifest.json"

    def _settings_path(self) -> str:
        return f"{self.root_prefix}/metadata/settings.json"

    def _approvals_path(self) -> str:
        return f"{self.root_prefix}/metadata/approvals.json"

    def _private_blob_url(self, path: str) -> str:
        store_id = os.getenv("BLOB_STORE_ID", "").strip()
        if not store_id:
            raise HTTPException(status_code=500, detail="BLOB_STORE_ID not set")
        host = store_id.replace("store_", "").lower()
        return f"https://{host}.private.blob.vercel-storage.com/{path}?download=1"

    async def write_domain_frame(self, domain: str, df: pd.DataFrame, brand: str, timestamp: Optional[str] = None) -> BlobArtifact:
        self._require_token()
        ts = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_buffer = io.StringIO()
        df.to_csv(output_buffer, index=False)
        csv_bytes = output_buffer.getvalue().encode("utf-8")
        blob_path = self._artifact_path(domain, brand, ts)
        async with AsyncBlobClient() as blob_client:
            blob = await blob_client.put(
                blob_path,
                csv_bytes,
                access="private",
                content_type="text/csv",
                add_random_suffix=False,
            )
        return BlobArtifact(
            path=blob_path,
            pathname=blob.pathname,
            url=getattr(blob, "url", None),
            download_url=getattr(blob, "download_url", None),
        )

    async def write_debug_json(self, name: str, payload: Any) -> BlobArtifact:
        return await self.write_json(self._debug_path(name), payload, overwrite=True)

    async def read_debug_json(self, name: str) -> Any:
        meta_path = self._debug_path(f"{name}_meta")
        meta = await self.read_json(meta_path)
        read_target = meta.get("download_url") or meta.get("url") or meta.get("path") or self._debug_path(name)
        try:
            return await self.read_json(read_target)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"Blob not found or unreadable: {self._debug_path(name)}") from exc

    async def debug_read_target(self, name: str) -> dict[str, Any]:
        meta_path = self._debug_path(f"{name}_meta")
        meta = await self.read_json(meta_path)
        read_target = meta.get("download_url") or meta.get("url") or meta.get("path") or self._debug_path(name)
        return {
            "meta_path": meta_path,
            "read_target": read_target,
            "meta": meta,
        }

    async def write_json(self, path: str, payload: Any, *, overwrite: bool = False) -> BlobArtifact:
        self._require_token()
        body = json.dumps(payload, indent=2).encode("utf-8")
        async with AsyncBlobClient() as blob_client:
            blob = await blob_client.put(
                path,
                body,
                access="private",
                content_type="application/json",
                add_random_suffix=False,
                overwrite=overwrite,
            )
        return BlobArtifact(
            path=path,
            pathname=blob.pathname,
            url=getattr(blob, "url", None),
            download_url=getattr(blob, "download_url", None),
        )

    async def read_json(self, path: str) -> Any:
        self._require_token()
        try:
            url = self._private_blob_url(path)
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {os.getenv('BLOB_READ_WRITE_TOKEN')}"},
                )
            if response.status_code != 200:
                raise HTTPException(status_code=404, detail=f"Blob not found or unreadable: {path}")
            return response.json()
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"Blob not found or unreadable: {path}") from exc

        raise HTTPException(status_code=500, detail=f"Unsupported blob payload type for '{path}'")

    async def write_latest_manifest(self, payload: dict[str, Any]) -> BlobArtifact:
        return await self.write_json(self._latest_manifest_path(), payload, overwrite=True)

    async def read_upload_history(self) -> list[dict[str, Any]]:
        try:
            payload = await self.read_json(self._metadata_path("upload_history"))
        except HTTPException as exc:
            if exc.status_code == 404:
                return []
            raise
        return payload if isinstance(payload, list) else []

    async def write_upload_history(self, history: list[dict[str, Any]]) -> BlobArtifact:
        return await self.write_json(self._metadata_path("upload_history"), history[:50], overwrite=True)

    async def read_settings(self) -> dict[str, Any]:
        try:
            payload = await self.read_json(self._settings_path())
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    async def write_settings(self, settings: dict[str, Any]) -> BlobArtifact:
        return await self.write_json(self._settings_path(), settings, overwrite=True)

    async def read_approvals(self) -> list[dict[str, Any]]:
        try:
            payload = await self.read_json(self._approvals_path())
        except HTTPException as exc:
            if exc.status_code == 404:
                return []
            raise
        return payload if isinstance(payload, list) else []

    async def write_approvals(self, approvals: list[dict[str, Any]]) -> BlobArtifact:
        return await self.write_json(self._approvals_path(), approvals[:500], overwrite=True)

    async def read_latest_domain_frame(self, domain: str) -> pd.DataFrame:
        self._require_token()
        path = self._metadata_path("latest_manifest")
        manifest = await self.read_json(path)
        domain_path = (manifest or {}).get("domains", {}).get(domain, {}).get("path")
        if not domain_path:
            raise HTTPException(status_code=404, detail=f"No Blob data found for domain '{domain}'")

        try:
            url = self._private_blob_url(domain_path)
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {os.getenv('BLOB_READ_WRITE_TOKEN')}"},
                )
            if response.status_code != 200:
                raise HTTPException(status_code=404, detail=f"Blob not found: {domain_path}")
            content = response.content
            return pd.read_csv(io.BytesIO(content))
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"Blob not found: {domain_path}") from exc

        raise HTTPException(status_code=500, detail=f"Unsupported blob payload type for '{domain}'")
