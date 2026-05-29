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
        path = self._debug_path(name)
        try:
            return await self.read_json(path)
        except Exception:
            pass

        # Try the SDK-returned private URL form for the same object.
        private_url = f"https://{os.getenv('BLOB_STORE_ID', '').replace('store_', '').lower()}.private.blob.vercel-storage.com/{path}"
        if private_url and "https://.private.blob.vercel-storage.com/" not in private_url:
            try:
                return await self.read_json(private_url)
            except Exception as exc:
                raise HTTPException(status_code=404, detail=f"Blob not found or unreadable: {path}") from exc

        raise HTTPException(status_code=404, detail=f"Blob not found or unreadable: {path}")

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
            async with AsyncBlobClient() as blob_client:
                blob = await blob_client.get(
                    path,
                    access="private",
                    token=os.getenv("BLOB_READ_WRITE_TOKEN"),
                )
            if blob is None:
                raise HTTPException(status_code=404, detail=f"Blob not found: {path}")
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
        except HTTPException:
            raise
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

    async def read_latest_domain_frame(self, domain: str) -> pd.DataFrame:
        self._require_token()
        path = self._metadata_path("latest_manifest")
        manifest = await self.read_json(path)
        domain_path = (manifest or {}).get("domains", {}).get(domain, {}).get("path")
        if not domain_path:
            raise HTTPException(status_code=404, detail=f"No Blob data found for domain '{domain}'")

        try:
            async with AsyncBlobClient() as blob_client:
                blob = await blob_client.get(
                    domain_path,
                    access="private",
                    token=os.getenv("BLOB_READ_WRITE_TOKEN"),
                )
            if blob is None:
                raise HTTPException(status_code=404, detail=f"Blob not found: {domain_path}")
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
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"Blob not found: {domain_path}") from exc

        raise HTTPException(status_code=500, detail=f"Unsupported blob payload type for '{domain}'")
