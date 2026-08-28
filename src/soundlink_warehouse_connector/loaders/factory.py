from __future__ import annotations

from soundlink_warehouse_connector.config import Destination, Settings
from soundlink_warehouse_connector.loaders.base import WarehouseLoader
from soundlink_warehouse_connector.loaders.duckdb import DuckDbLoader


def build_loader(settings: Settings) -> WarehouseLoader:
    if settings.destination == Destination.DUCKDB:
        return DuckDbLoader(settings.duckdb_path)
    if settings.destination == Destination.BIGQUERY:
        if not settings.bigquery_project or not settings.bigquery_dataset:
            raise ValueError(
                "BIGQUERY_PROJECT and BIGQUERY_DATASET are required when DESTINATION=bigquery"
            )
        try:
            from soundlink_warehouse_connector.loaders.bigquery import BigQueryLoader
        except ImportError as exc:
            raise ImportError(
                "BigQuery support requires the optional dependency. "
                "Install with: uv sync --extra bigquery "
                "or: pip install 'soundlink-warehouse-connector[bigquery]'"
            ) from exc
        return BigQueryLoader(
            project=settings.bigquery_project,
            dataset=settings.bigquery_dataset,
            location=settings.bigquery_location,
        )
    raise ValueError(f"Unsupported destination: {settings.destination}")
