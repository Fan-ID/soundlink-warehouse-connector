from __future__ import annotations

import pytest
from pydantic import ValidationError

from soundlink_warehouse_connector.config import Destination, Settings
from soundlink_warehouse_connector.loaders.duckdb import DuckDbLoader
from soundlink_warehouse_connector.loaders.factory import build_loader


def test_build_loader_duckdb(tmp_path) -> None:
    settings = Settings(
        soundlink_api_key="sk_test_ok",
        destination=Destination.DUCKDB,
        duckdb_path=tmp_path / "t.duckdb",
    )
    loader = build_loader(settings)
    assert isinstance(loader, DuckDbLoader)
    loader.close()


def test_bigquery_settings_require_project_dataset() -> None:
    with pytest.raises(ValidationError, match="BIGQUERY_PROJECT"):
        Settings(
            soundlink_api_key="sk_test_ok",
            destination=Destination.BIGQUERY,
        )


def test_build_loader_bigquery(monkeypatch) -> None:
    settings = Settings(
        soundlink_api_key="sk_test_ok",
        destination=Destination.BIGQUERY,
        bigquery_project="p",
        bigquery_dataset="d",
    )

    class FakeBQ:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def close(self) -> None:
            return None

    import soundlink_warehouse_connector.loaders.bigquery as bq_mod

    monkeypatch.setattr(bq_mod, "BigQueryLoader", FakeBQ)
    loader = build_loader(settings)
    assert isinstance(loader, FakeBQ)
    assert loader.kwargs["project"] == "p"
    assert loader.kwargs["dataset"] == "d"
    assert loader.kwargs["location"] == "US"
