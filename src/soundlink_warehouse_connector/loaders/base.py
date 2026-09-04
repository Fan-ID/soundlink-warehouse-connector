from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from soundlink_warehouse_connector.client.models import CampaignSummary, SoundlinkSummary


class WarehouseLoader(ABC):
    @abstractmethod
    def ensure_schema(self) -> None: ...

    @abstractmethod
    def upsert_campaigns(self, campaigns: list[CampaignSummary]) -> int: ...

    @abstractmethod
    def upsert_breakdown_rows(self, rows: list[dict[str, Any]]) -> int: ...

    @abstractmethod
    def upsert_engagement_rows(self, rows: list[dict[str, Any]]) -> int: ...

    @abstractmethod
    def upsert_soundlinks(self, soundlinks: list[SoundlinkSummary]) -> int: ...

    @abstractmethod
    def upsert_soundlink_breakdown_rows(self, rows: list[dict[str, Any]]) -> int: ...

    @abstractmethod
    def upsert_soundlink_engagement_rows(self, rows: list[dict[str, Any]]) -> int: ...

    @abstractmethod
    def close(self) -> None: ...
