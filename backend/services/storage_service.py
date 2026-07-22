from typing import Optional
from backend.storage import R2Storage


class StorageService:
    def __init__(self):
        self._r2_client = None

    def _get_client(self) -> Optional[R2Storage]:
        if self._r2_client is None:
            try:
                self._r2_client = R2Storage()
            except Exception:
                self._r2_client = None
        return self._r2_client

    def generate_presigned_url(self, key: Optional[str], expires_seconds: int = 3600) -> Optional[str]:
        if not key:
            return None
        client = self._get_client()
        if not client:
            return f"https://mock-storage.local/{key}"  # Fallback for dev/testing when R2 env not configured
        try:
            return client.presigned_url(key, expires_seconds=expires_seconds)
        except Exception:
            return f"https://mock-storage.local/{key}"


storage_service = StorageService()
