"""Application configuration.

All settings are environment-variable driven. Local development values are
provided as defaults so the project boots without a .env file, while
production deployments must override SECRET_KEY and DB_PASSWORD.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Test database suffix. Any database whose name ends with this suffix is
# considered disposable and may be dropped/recreated by the test suite.
TEST_DB_SUFFIX = "_test"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env", "../../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    PROJECT_NAME: str = "Manufacturing ERP Lite"
    VERSION: str = "0.1.0"
    ENV: Literal["dev", "test", "prod"] = "dev"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    DOCS_URL: str = "/docs"
    OPENAPI_URL: str = "/openapi.json"

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = "erp_lite_dev"
    DB_NAME: str = "erp_lite"
    DB_CHARSET: str = "utf8mb4"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE: int = 1800
    SQL_ECHO: bool = False

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------
    SECRET_KEY: str = "dev-only-secret-key-change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8
    BCRYPT_ROUNDS: int = 12

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------
    DEFAULT_PAGE_SIZE: int = Field(default=20, ge=1, le=200)
    MAX_PAGE_SIZE: int = Field(default=200, ge=1, le=1000)

    # ------------------------------------------------------------------
    # Business defaults
    # ------------------------------------------------------------------
    # Decimal precision shared by quantities and amounts: DECIMAL(18, 4)
    MONEY_SCALE: int = 4
    MONEY_PRECISION: int = 18

    @model_validator(mode="after")
    def _guard_database_name(self) -> "Settings":
        """Prevent a dev/prod run from pointing at a disposable test database."""
        is_test = self.ENV == "test"
        name_ends_with_suffix = self.DB_NAME.endswith(TEST_DB_SUFFIX)

        if not is_test and name_ends_with_suffix:
            raise ValueError(
                f"ENV={self.ENV!r} must not use a '{TEST_DB_SUFFIX}' database "
                f"(got {self.DB_NAME!r}). Refusing to start."
            )
        return self

    @property
    def is_testing(self) -> bool:
        return self.ENV == "test"

    @property
    def database_name(self) -> str:
        """Effective database name, forced to the test database when ENV=test."""
        if self.is_testing and not self.DB_NAME.endswith(TEST_DB_SUFFIX):
            return f"{self.DB_NAME}{TEST_DB_SUFFIX}"
        return self.DB_NAME

    @property
    def sqlalchemy_database_uri(self) -> str:
        """Async-free MySQL URI built for PyMySQL."""
        return (
            f"mysql+pymysql://{self.DB_USER}:{quote_plus(self.DB_PASSWORD)}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.database_name}"
            f"?charset={self.DB_CHARSET}"
        )

    @property
    def server_dsn(self) -> str:
        """URI without a database, used for CREATE DATABASE bootstrap."""
        return (
            f"mysql+pymysql://{self.DB_USER}:{quote_plus(self.DB_PASSWORD)}"
            f"@{self.DB_HOST}:{self.DB_PORT}/?charset={self.DB_CHARSET}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
