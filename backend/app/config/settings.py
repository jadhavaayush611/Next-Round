import json
from typing import Any

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_ignore_empty=True, extra="ignore"
    )

    PROJECT_NAME: str = "NextRound API"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"

    # CORS
    BACKEND_CORS_ORIGINS: list[str] | str = []

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            if not v.strip():
                return []
            if v.startswith("[") and v.endswith("]"):
                try:
                    res = json.loads(v)
                    if isinstance(res, list):
                        return [str(item) for item in res]
                except Exception:
                    pass
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, list):
            return [str(item) for item in v]
        return []

    # Database
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "nextround_user"
    POSTGRES_PASSWORD: str = "nextround_password"
    POSTGRES_DB: str = "nextround_db"
    DATABASE_URL: str | None = None

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.DATABASE_URL:
            url = self.DATABASE_URL
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+psycopg://", 1)
            return url
        return f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    # Security
    JWT_SECRET: str = "dev_secret_key_change_in_production_123456789"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Storage & Uploads
    STORAGE_LOCAL_ROOT: str = "uploads"
    MAX_UPLOAD_SIZE_BYTES: int = 5 * 1024 * 1024  # 5 MB
    ALLOWED_RESUME_EXTENSIONS: list[str] = [".pdf", ".docx"]
    ALLOWED_RESUME_MIME_TYPES: list[str] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]

    @model_validator(mode="after")
    def validate_production_jwt_secret(self) -> "Settings":
        if self.ENVIRONMENT == "production":
            if (
                not self.JWT_SECRET
                or self.JWT_SECRET == "dev_secret_key_change_in_production_123456789"
                or self.JWT_SECRET == "change_me_in_production_jwt_secret_key_12345"
            ):
                raise ValueError(
                    "JWT_SECRET must be configured with a secure custom secret in production mode."
                )
        return self


settings = Settings()
