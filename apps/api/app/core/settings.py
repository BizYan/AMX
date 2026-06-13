"""Application Settings Module

Pydantic v2 BaseSettings with typed fields for all configuration.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    DEBUG: bool = False
    APP_NAME: str = "Consultant AI Workbench"
    API_V1_PREFIX: str = "/api/v1"

    # Bootstrap Admin (required for initial setup)
    BOOTSTRAP_ADMIN_EMAIL: str = Field(default="", description="Admin email for initial setup")
    BOOTSTRAP_ADMIN_PASSWORD: str = Field(default="", description="Admin password for initial setup")
    BOOTSTRAP_ADMIN_NAME: str = Field(default="", description="Admin full name for initial setup")

    # Database
    DATABASE_URL: str = Field(
        default="",
        description="PostgreSQL connection URL for async operations",
    )

    # Redis
    REDIS_URL: str = Field(default="", description="Redis connection URL")
    ARQ_REDIS_URL: str = Field(default="redis://localhost/1", description="Redis URL for ARQ worker queue")

    # JWT
    JWT_SECRET_KEY: str = Field(default="", description="Secret key for JWT signing")
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:8080"

    # OpenAI / LLM Provider
    OPENAI_BASE_URL: str = "https://api.minimax.chat/v1"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "MiniMax-Text-01"

    # Fallback LLM Provider (optional, used when primary fails)
    LLM_FALLBACK_API_KEY: str = ""
    LLM_FALLBACK_BASE_URL: str = "https://api.openai.com/v1"
    LLM_FALLBACK_MODEL: str = "gpt-4o"

    # Storage
    STORAGE_BACKEND: Literal["local", "s3"] = "local"
    STORAGE_LOCAL_PATH: str = "/data/storage"

    # Vector Store
    VECTOR_STORE_PROVIDER: Literal["pgvector", "qdrant", "milvus"] = "pgvector"
    SEARCH_PROVIDER: Literal["postgresql", "elasticsearch"] = "postgresql"
    GRAPH_STORE_PROVIDER: Literal["postgresql", "neptune"] = "postgresql"

    # AWS S3
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"
    S3_BUCKET: str = ""
    S3_ENDPOINT_URL: str | None = None

    # SMTP Email
    SMTP_HOST: str = Field(default="", description="SMTP server hostname")
    SMTP_PORT: int = Field(default=587, description="SMTP server port")
    SMTP_USER: str = Field(default="", description="SMTP username")
    SMTP_PASSWORD: str = Field(default="", description="SMTP password")
    SMTP_FROM_EMAIL: str = Field(default="", description="From email address")
    SMTP_FROM_NAME: str = Field(default="Consultant AI Workbench", description="From display name")
    SMTP_USE_TLS: bool = Field(default=True, description="Use TLS/STARTTLS")

    # Logging
    LOG_LEVEL: str = "INFO"


@lru_cache()
def get_settings() -> Settings:
    """Get cached singleton settings instance.

    Returns:
        Settings: Cached settings singleton
    """
    return Settings()


# Convenience instance
settings = get_settings()