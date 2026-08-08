import os
from typing import List

from pydantic import BaseModel


class Settings(BaseModel):
    PROJECT_NAME: str = "Industrial Safety AI Analytics API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"

    JWT_SECRET: str = os.getenv("JWT_SECRET", "local-jwt-secret-change-me")
    AI_SERVICE_TOKEN: str = os.getenv(
        "AI_SERVICE_TOKEN", "local-ai-service-token-change-me"
    )
    CONTROL_PLANE_BOOTSTRAP_TOKEN: str = os.getenv("CONTROL_PLANE_BOOTSTRAP_TOKEN", "")
    DEPLOYMENT_ROLE: str = os.getenv("DEPLOYMENT_ROLE", "customer-host")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:industrial_safety_dev@localhost:5432/industrial_safety",
    )

    AZURE_STORAGE_CONNECTION_STRING: str = os.getenv(
        "AZURE_STORAGE_CONNECTION_STRING", ""
    )
    AZURE_STORAGE_CONTAINER: str = os.getenv(
        "AZURE_STORAGE_CONTAINER", "industrial-safety-evidence"
    )
    AZURE_STORAGE_PUBLIC_BLOB_ENDPOINT: str = os.getenv(
        "AZURE_STORAGE_PUBLIC_BLOB_ENDPOINT", ""
    )
    AZURE_STORAGE_SAS_EXPIRES_SECONDS: int = int(
        os.getenv("AZURE_STORAGE_SAS_EXPIRES_SECONDS", "900")
    )
    AZURE_STORAGE_CREATE_CONTAINER: bool = os.getenv(
        "AZURE_STORAGE_CREATE_CONTAINER", "false"
    ).lower() in {"1", "true", "yes"}

    VIOLATION_RETENTION_DAYS: int = int(os.getenv("VIOLATION_RETENTION_DAYS", "3"))
    VIOLATION_MAX_COUNT: int = int(os.getenv("VIOLATION_MAX_COUNT", "1000"))
    VIOLATION_KEEP_COUNT: int = int(os.getenv("VIOLATION_KEEP_COUNT", "500"))
    VIOLATION_RETENTION_INTERVAL_SECONDS: int = int(
        os.getenv("VIOLATION_RETENTION_INTERVAL_SECONDS", "3600")
    )

    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ]


settings = Settings()
