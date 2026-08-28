from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from soundlink_warehouse_connector.client.models import CampaignSummary
from soundlink_warehouse_connector.loaders.duckdb import DuckDbLoader

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def loader(tmp_path: Path) -> DuckDbLoader:
    db = DuckDbLoader(tmp_path / "test.duckdb")
    db.ensure_schema()
    yield db
    db.close()


def _load_jsonl(name: str) -> list[dict]:
    lines = (FIXTURES / name).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_breakdown_upsert_is_idempotent(loader: DuckDbLoader, tmp_path: Path) -> None:
    rows = _load_jsonl("breakdown.jsonl")
    assert loader.upsert_breakdown_rows(rows) == 2

    updated = [{**rows[0], "streams": 999, "listeners": 888}]
    assert loader.upsert_breakdown_rows(updated) == 1

    conn = duckdb.connect(str(tmp_path / "test.duckdb"))
    count = conn.execute("SELECT COUNT(*) FROM campaign_country_daily").fetchone()[0]
    streams, cpl = conn.execute(
        "SELECT streams, cpl FROM campaign_country_daily WHERE country_code = 'US'"
    ).fetchone()
    conn.close()

    assert count == 2
    assert streams == 999
    assert cpl == 0.293


def test_engagement_upsert_is_idempotent(loader: DuckDbLoader, tmp_path: Path) -> None:
    rows = _load_jsonl("engagement.jsonl")
    assert loader.upsert_engagement_rows(rows) == 2
    assert loader.upsert_engagement_rows(rows) == 2

    conn = duckdb.connect(str(tmp_path / "test.duckdb"))
    count = conn.execute("SELECT COUNT(*) FROM campaign_engagement_daily").fetchone()[0]
    conn.close()
    assert count == 2


def test_campaign_upsert_stores_raw_json(loader: DuckDbLoader, tmp_path: Path) -> None:
    payload = json.loads((FIXTURES / "campaigns.json").read_text(encoding="utf-8"))
    item = payload["data"]["items"][0]
    campaign = CampaignSummary.model_validate(item)
    assert loader.upsert_campaigns([campaign]) == 1

    conn = duckdb.connect(str(tmp_path / "test.duckdb"))
    row = conn.execute(
        "SELECT campaign_id, raw_json->>'campaignId' FROM campaigns"
    ).fetchone()
    conn.close()

    assert row[0] == campaign.campaign_id
    assert row[1] == campaign.campaign_id
