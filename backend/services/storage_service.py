from __future__ import annotations

from fastapi import HTTPException

from backend.core.config import settings
from backend.storage import AzureBlobStorage, UploadLease


class StorageService:
    def __init__(self) -> None:
        self._client: AzureBlobStorage | None = None

    @staticmethod
    def is_configured() -> bool:
        return bool(
            settings.AZURE_STORAGE_CONNECTION_STRING
            and settings.AZURE_STORAGE_CONTAINER
        )

    def _get_client(self) -> AzureBlobStorage:
        if not self.is_configured():
            raise HTTPException(
                status_code=503, detail="Azure Blob Storage is not configured"
            )
        if self._client is None:
            try:
                self._client = AzureBlobStorage(
                    connection_string=settings.AZURE_STORAGE_CONNECTION_STRING,
                    container=settings.AZURE_STORAGE_CONTAINER,
                    public_blob_endpoint=(
                        settings.AZURE_STORAGE_PUBLIC_BLOB_ENDPOINT or None
                    ),
                    create_container=settings.AZURE_STORAGE_CREATE_CONTAINER,
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=503, detail="Azure Blob Storage signer unavailable"
                ) from exc
        return self._client

    def create_upload_lease(
        self, key: str, content_type: str, expires_seconds: int | None = None
    ) -> UploadLease:
        expires = expires_seconds or settings.AZURE_STORAGE_SAS_EXPIRES_SECONDS
        return self._get_client().create_upload_lease(key, content_type, expires)

    def generate_signed_download(
        self, key: str | None, expires_seconds: int = 3600
    ) -> str | None:
        if not key:
            return None
        return self._get_client().create_download_url(key, expires_seconds)

    def verify_uploaded_object(
        self, key: str, expected_size: int, expected_content_type: str
    ) -> dict[str, object]:
        try:
            metadata = self._get_client().head(key)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=503, detail="Azure Blob object verification failed"
            ) from exc
        if metadata["size_bytes"] != expected_size:
            raise HTTPException(status_code=409, detail="Blob object size does not match")
        content_type = metadata.get("content_type")
        if content_type and content_type != expected_content_type:
            raise HTTPException(
                status_code=409, detail="Blob object content type does not match"
            )
        return metadata

    def delete_object(self, key: str) -> None:
        """Delete an object during retention cleanup."""
        self._get_client().delete(key)


storage_service = StorageService()
