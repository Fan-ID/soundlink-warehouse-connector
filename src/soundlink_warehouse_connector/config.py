from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Destination(StrEnum):
    DUCKDB = "duckdb"
    BIGQUERY = "bigquery"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    soundlink_api_key: str = Field(..., description="API key from Settings → Developer")
    soundlink_base_url: str = "https://api.getsoundlink.com"
    destination: Destination = Destination.DUCKDB
    duckdb_path: Path = Path("./data/soundlink.duckdb")
    bigquery_project: str | None = None
    bigquery_dataset: str | None = None
    bigquery_location: str = "US"
    incremental_lookback_days: int = Field(default=10, ge=1, le=90)
    campaigns_page_size: int = Field(
        default=25,
        ge=1,
        le=100,
        description="GET /v1/campaigns pageSize (smaller reduces 504 risk)",
    )
    request_timeout_seconds: float = Field(default=120.0, gt=0)
    max_retries: int = Field(default=5, ge=0, le=20)
    state_path: Path = Path("./data/sync_state.json")

    @field_validator("soundlink_api_key")
    @classmethod
    def _non_empty_key(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or cleaned.startswith("sk_YOUR_"):
            raise ValueError("Set SOUNDLINK_API_KEY to a real key from Settings → Developer")
        return cleaned

    @model_validator(mode="after")
    def _require_bigquery_fields(self) -> Settings:
        if self.destination == Destination.BIGQUERY:
            if not self.bigquery_project or not self.bigquery_dataset:
                raise ValueError(
                    "DESTINATION=bigquery requires BIGQUERY_PROJECT and BIGQUERY_DATASET"
                )
        return self

    @property
    def api_root(self) -> str:
        return self.soundlink_base_url.rstrip("/")
