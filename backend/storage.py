"""Azure Blob Storage adapter used by the backend signer and verifier."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote


@dataclass(frozen=True)
class UploadLease:
    url: str
    headers: dict[str, str]
    expires_in_seconds: int


def _connection_string_parts(connection_string: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    for component in connection_string.split(";"):
        if not component or "=" not in component:
            continue
        key, value = component.split("=", 1)
        parts[key.strip().lower()] = value.strip()
    return parts


class AzureBlobStorage:
    def __init__(
        self,
        *,
        connection_string: str,
        container: str,
        public_blob_endpoint: str | None = None,
        create_container: bool = False,
    ) -> None:
        try:
            from azure.core.exceptions import ResourceExistsError
            from azure.storage.blob import BlobServiceClient
        except ImportError as exc:
            raise RuntimeError("azure-storage-blob is required for evidence storage") from exc

        connection_parts = _connection_string_parts(connection_string)
        self.account_name = connection_parts.get("accountname", "")
        self.account_key = connection_parts.get("accountkey", "")
        if not self.account_name or not self.account_key:
            raise ValueError(
                "AZURE_STORAGE_CONNECTION_STRING must contain AccountName and AccountKey"
            )

        self.container = container
        self.public_blob_endpoint = (
            public_blob_endpoint.rstrip("/") if public_blob_endpoint else None
        )
        self.client = BlobServiceClient.from_connection_string(
            connection_string, api_version="2025-11-05"
        )
        self.container_client = self.client.get_container_client(container)
        if create_container:
            try:
                self.container_client.create_container()
            except ResourceExistsError:
                pass

    def _blob_url(self, key: str) -> str:
        if self.public_blob_endpoint:
            return (
                f"{self.public_blob_endpoint}/{quote(self.container, safe='')}"
                f"/{quote(key, safe='/')}"
            )
        return self.container_client.get_blob_client(key).url

    def create_upload_lease(
        self, key: str, content_type: str, expires_seconds: int
    ) -> UploadLease:
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas

        now = datetime.now(timezone.utc)
        token = generate_blob_sas(
            account_name=self.account_name,
            container_name=self.container,
            blob_name=key,
            account_key=self.account_key,
            permission=BlobSasPermissions(create=True, write=True),
            start=now - timedelta(minutes=5),
            expiry=now + timedelta(seconds=expires_seconds),
        )
        return UploadLease(
            url=f"{self._blob_url(key)}?{token}",
            headers={
                "Content-Type": content_type,
                "x-ms-blob-type": "BlockBlob",
                "x-ms-blob-content-type": content_type,
            },
            expires_in_seconds=expires_seconds,
        )

    def create_download_url(self, key: str, expires_seconds: int) -> str:
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas

        now = datetime.now(timezone.utc)
        token = generate_blob_sas(
            account_name=self.account_name,
            container_name=self.container,
            blob_name=key,
            account_key=self.account_key,
            permission=BlobSasPermissions(read=True),
            start=now - timedelta(minutes=5),
            expiry=now + timedelta(seconds=expires_seconds),
        )
        return f"{self._blob_url(key)}?{token}"

    def head(self, key: str) -> dict[str, object]:
        properties = self.container_client.get_blob_client(key).get_blob_properties()
        return {
            "size_bytes": int(properties.size),
            "etag": str(properties.etag).strip('"') or None,
            "content_type": properties.content_settings.content_type,
        }
