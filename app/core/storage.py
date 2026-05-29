import io
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd
from fastapi import HTTPException
from vercel.blob import AsyncBlobClient


@dataclass
class BlobArtifact:
    path: str
    pathname: str


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

    def _blob_access_mode(self) -> str:
        mode = os.getenv("BLOB_ACCESS_MODE", "auto").strip().lower()
        if mode in {"public", "private"}:
            return mode
        return "auto"

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
        return BlobArtifact(path=blob_path, pathname=blob.pathname)

    async def write_debug_json(self, name: str, payload: Any) -> BlobArtifact:
        return await self.write_json(self._debug_path(name), payload, overwrite=True)

    async def read_debug_json(self, name: str) -> Any:
        return await self.read_json(self._debug_path(name))

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
        return BlobArtifact(path=path, pathname=blob.pathname)

    async def read_json(self, path: str) -> Any:
        self._require_token()
        last_error = None
        access_modes = [self._blob_access_mode()]
        if access_modes[0] == "auto":
            access_modes = ["private", "public"]

        for access_mode in access_modes:
            try:
                async with AsyncBlobClient() as blob_client:
                    blob = await blob_client.get(
                        path,
                        access=access_mode,
                        token=os.getenv("BLOB_READ_WRITE_TOKEN"),
                    )
                if blob is None:
                    continue
                if hasattr(blob, "download"):
                    content = await blob.download()
                elif hasattr(blob, "body"):
                    content = blob.body
                else:
                    content = blob
                if isinstance(content, bytes):
                    return json.loads(content.decode("utf-8"))
                if isinstance(content, str):
                    return json.loads(content)
            except Exception as exc:
                last_error = exc
                continue

        raise HTTPException(status_code=404, detail=f"Blob not found or unreadable: {path}") from last_error

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

    async def read_latest_domain_frame(self, domain: str) -> pd.DataFrame:
        self._require_token()
        try:
            async with AsyncBlobClient() as blob_client:
                listed = await blob_client.list(
                    prefix=f"{self.root_prefix}/{domain}/",
                    token=os.getenv("BLOB_READ_WRITE_TOKEN"),
                )
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"No Blob data found for domain '{domain}'") from exc

        blobs = []
        if isinstance(listed, list):
            blobs = listed
        elif hasattr(listed, "blobs"):
            blobs = list(listed.blobs)
        else:
            blobs = list(listed or [])

        def _path(item: Any) -> str:
            if isinstance(item, dict):
                return item.get("pathname") or item.get("path") or ""
            return getattr(item, "pathname", None) or getattr(item, "path", None) or ""

        csv_blobs = [b for b in blobs if _path(b).endswith(".csv")]
        if not csv_blobs:
            raise HTTPException(status_code=404, detail=f"No Blob data found for domain '{domain}'")

        domain_path = max(csv_blobs, key=_path)
        domain_path = _path(domain_path)

        last_error = None
        access_modes = [self._blob_access_mode()]
        if access_modes[0] == "auto":
            access_modes = ["private", "public"]

        for access_mode in access_modes:
            try:
                async with AsyncBlobClient() as blob_client:
                    blob = await blob_client.get(
                        domain_path,
                        access=access_mode,
                        token=os.getenv("BLOB_READ_WRITE_TOKEN"),
                    )
                if blob is None:
                    continue
                if hasattr(blob, "download"):
                    content = await blob.download()
                elif hasattr(blob, "body"):
                    content = blob.body
                else:
                    content = blob
                if isinstance(content, bytes):
                    return pd.read_csv(io.BytesIO(content))
                if isinstance(content, str):
                    return pd.read_csv(io.StringIO(content))
            except Exception as exc:
                last_error = exc
                continue

        raise HTTPException(status_code=404, detail=f"Blob not found: {domain_path}") from last_error
