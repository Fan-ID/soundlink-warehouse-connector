from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

EXPECTED_SCHEMA_VERSION = "1.0"


class Pagination(BaseModel):
    """Matches Public API `Pagination` schema: page, pageSize, totalCount, totalPages."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    page: int
    page_size: int = Field(alias="pageSize")
    total_count: int = Field(alias="totalCount")
    total_pages: int = Field(alias="totalPages")


class CampaignSummary(BaseModel):
    """Public API campaign list/detail row (camelCase). Extra fields ignored."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    campaign_id: str = Field(alias="campaignId")
    organization_id: str = Field(alias="organizationId")
    status: str
    social_platform: str = Field(alias="socialPlatform")
    daily_budget: float = Field(alias="dailyBudget")
    total_budget: float = Field(alias="totalBudget")
    campaign_duration: int = Field(alias="campaignDuration")
    generation: int
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    strategy_type: str | None = Field(default=None, alias="strategyType")

    @property
    def created_date(self) -> date:
        return self.created_at.date()


class BreakdownRow(BaseModel):
    """Public API `campaign_country_daily` v1.0 — required PK fields validated."""

    model_config = ConfigDict(extra="allow")

    provider: str
    account_id: str
    report_date: date
    campaign_id: str
    country_code: str
    schema_version: str | None = None


class EngagementRow(BaseModel):
    """Public API `campaign_engagement_daily` v1.0 — required PK fields validated."""

    model_config = ConfigDict(extra="allow")

    provider: str
    account_id: str
    report_date: date
    campaign_id: str
    engagement_context: str
    country_code: str
    engaged_spotify_track_id: str
    schema_version: str | None = None


def validate_breakdown_row(data: dict[str, Any]) -> dict[str, Any]:
    BreakdownRow.model_validate(data)
    return data


def validate_engagement_row(data: dict[str, Any]) -> dict[str, Any]:
    EngagementRow.model_validate(data)
    return data
