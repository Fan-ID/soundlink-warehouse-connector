from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx
from pydantic import ValidationError

from soundlink_warehouse_connector.client.soundlink import SoundlinkApiError, SoundlinkClient

FIXTURES = Path(__file__).parent / "fixtures"
BASE_URL = "https://api.test.local"
API_KEY = "sk_test_fixture_key_abc123"


@respx.mock
def test_ping() -> None:
    respx.get(f"{BASE_URL}/v1/ping").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"status": "ok", "organizationId": "org-1"}},
        )
    )
    with SoundlinkClient(api_key=API_KEY, base_url=BASE_URL, max_retries=0) as client:
        data = client.ping()
    assert data["status"] == "ok"


@respx.mock
def test_list_campaigns_pagination() -> None:
    payload = json.loads((FIXTURES / "campaigns.json").read_text(encoding="utf-8"))
    route = respx.get(f"{BASE_URL}/v1/campaigns").mock(
        return_value=httpx.Response(200, json=payload)
    )
    with SoundlinkClient(
        api_key=API_KEY, base_url=BASE_URL, max_retries=0, campaigns_page_size=25
    ) as client:
        items, pagination = client.list_campaigns_page(page=1)
        all_campaigns = list(client.iter_campaigns())

    assert route.called
    request = route.calls[0].request
    assert request.url.params["page"] == "1"
    assert request.url.params["pageSize"] == "25"
    assert len(items) == 1
    assert pagination.total_pages == 1
    assert pagination.total_count == 1
    assert all_campaigns[0].campaign_id == "f1e28d31-c358-4284-9bef-00a2334625fd"


@respx.mock
def test_retries_on_429_honoring_retry_after() -> None:
    route = respx.get(f"{BASE_URL}/v1/ping").mock(
        side_effect=[
            httpx.Response(
                429,
                headers={"Retry-After": "0"},
                json={"error": {"code": "rate_limited", "message": "slow down"}},
            ),
            httpx.Response(200, json={"data": {"status": "ok"}}),
        ]
    )
    with SoundlinkClient(api_key=API_KEY, base_url=BASE_URL, max_retries=2) as client:
        data = client.ping()
    assert data["status"] == "ok"
    assert route.call_count == 2


@respx.mock
def test_export_metrics_jsonl() -> None:
    campaign_id = "f1e28d31-c358-4284-9bef-00a2334625fd"
    breakdown_body = (FIXTURES / "breakdown.jsonl").read_text(encoding="utf-8")
    route = respx.get(
        f"{BASE_URL}/v1/campaigns/{campaign_id}/metrics/breakdown/export"
    ).mock(
        return_value=httpx.Response(
            200,
            headers={"X-Row-Count": "2", "Content-Type": "application/x-ndjson"},
            content=breakdown_body.encode(),
        )
    )
    with SoundlinkClient(api_key=API_KEY, base_url=BASE_URL, max_retries=0) as client:
        rows, count = client.export_metrics_jsonl(
            campaign_id=campaign_id,
            kind="breakdown",
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
        )

    assert count == 2
    assert len(rows) == 2
    assert rows[0]["country_code"] == "US"
    assert rows[1]["country_code"] == "DE"
    assert route.calls[0].request.headers["Accept"] == "application/x-ndjson"


@respx.mock
def test_export_soundlink_metrics_jsonl() -> None:
    soundlink_id = "V1StGXR8_Z5jdHi6B-myT"
    breakdown_body = (FIXTURES / "soundlink_breakdown.jsonl").read_text(encoding="utf-8")
    engagement_body = (FIXTURES / "soundlink_engagement.jsonl").read_text(
        encoding="utf-8"
    )
    breakdown_route = respx.get(
        f"{BASE_URL}/v1/soundlinks/{soundlink_id}/metrics/breakdown/export"
    ).mock(
        return_value=httpx.Response(
            200,
            headers={"X-Row-Count": "2", "Content-Type": "application/x-ndjson"},
            content=breakdown_body.encode(),
        )
    )
    engagement_route = respx.get(
        f"{BASE_URL}/v1/soundlinks/{soundlink_id}/metrics/engagement/export"
    ).mock(
        return_value=httpx.Response(
            200,
            headers={"X-Row-Count": "2", "Content-Type": "application/x-ndjson"},
            content=engagement_body.encode(),
        )
    )
    with SoundlinkClient(api_key=API_KEY, base_url=BASE_URL, max_retries=0) as client:
        breakdown_rows, breakdown_count = client.export_metrics_jsonl(
            soundlink_id=soundlink_id,
            kind="breakdown",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 28),
        )
        engagement_rows, engagement_count = client.export_metrics_jsonl(
            soundlink_id=soundlink_id,
            kind="engagement",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 28),
        )

    assert breakdown_count == 2
    assert len(breakdown_rows) == 2
    assert breakdown_rows[0]["soundlink_id"] == soundlink_id
    assert breakdown_rows[0]["country_code"] == "US"
    assert engagement_count == 2
    assert len(engagement_rows) == 2
    assert engagement_rows[0]["soundlink_id"] == soundlink_id
    assert breakdown_route.called
    assert engagement_route.called
    assert breakdown_route.calls[0].request.headers["Accept"] == "application/x-ndjson"


@respx.mock
def test_export_metrics_row_count_mismatch_fails() -> None:
    campaign_id = "f1e28d31-c358-4284-9bef-00a2334625fd"
    breakdown_body = (FIXTURES / "breakdown.jsonl").read_text(encoding="utf-8")
    respx.get(f"{BASE_URL}/v1/campaigns/{campaign_id}/metrics/breakdown/export").mock(
        return_value=httpx.Response(
            200,
            headers={"X-Row-Count": "99"},
            content=breakdown_body.encode(),
        )
    )
    with SoundlinkClient(api_key=API_KEY, base_url=BASE_URL, max_retries=0) as client:
        with pytest.raises(SoundlinkApiError, match="X-Row-Count mismatch"):
            client.export_metrics_jsonl(
                campaign_id=campaign_id,
                kind="breakdown",
                start_date=date(2026, 4, 1),
                end_date=date(2026, 4, 30),
            )


@respx.mock
def test_get_campaign() -> None:
    campaign_id = "f1e28d31-c358-4284-9bef-00a2334625fd"
    payload = json.loads((FIXTURES / "campaigns.json").read_text(encoding="utf-8"))
    item = payload["data"]["items"][0]
    respx.get(f"{BASE_URL}/v1/campaigns/{campaign_id}").mock(
        return_value=httpx.Response(200, json={"data": item})
    )
    with SoundlinkClient(api_key=API_KEY, base_url=BASE_URL, max_retries=0) as client:
        campaign = client.get_campaign(campaign_id)
    assert campaign.campaign_id == campaign_id
    assert campaign.strategy_type == "maximum_growth"


@respx.mock
def test_export_rejects_invalid_row() -> None:
    campaign_id = "f1e28d31-c358-4284-9bef-00a2334625fd"
    bad = json.dumps({"provider": "soundlink"})  # missing PK fields
    respx.get(f"{BASE_URL}/v1/campaigns/{campaign_id}/metrics/breakdown/export").mock(
        return_value=httpx.Response(
            200,
            headers={"X-Row-Count": "1"},
            content=f"{bad}\n".encode(),
        )
    )
    with SoundlinkClient(api_key=API_KEY, base_url=BASE_URL, max_retries=0) as client:
        with pytest.raises(ValidationError):
            client.export_metrics_jsonl(
                campaign_id=campaign_id,
                kind="breakdown",
                start_date=date(2026, 4, 1),
                end_date=date(2026, 4, 30),
            )
