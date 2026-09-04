from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import date
from typing import Any

import httpx
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from soundlink_warehouse_connector import __version__
from soundlink_warehouse_connector.client.models import (
    EXPECTED_SCHEMA_VERSION,
    CampaignSummary,
    Pagination,
    SoundlinkSummary,
    validate_breakdown_row,
    validate_engagement_row,
    validate_soundlink_breakdown_row,
    validate_soundlink_engagement_row,
)

logger = logging.getLogger(__name__)

DEFAULT_CAMPAIGNS_PAGE_SIZE = 25
DEFAULT_SOUNDLINKS_PAGE_SIZE = 25


class SoundlinkApiError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: str | None = None,
        retry_after: float | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.retry_after = retry_after
        self.retryable = retryable


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, SoundlinkApiError):
        if exc.retryable:
            return True
        if exc.status_code is not None:
            return exc.status_code == 429 or exc.status_code >= 500
    return False


def _parse_retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(float(raw), 0.0)
    except ValueError:
        return 60.0


def _wait_retry_after_or_backoff(retry_state: RetryCallState) -> float:
    if retry_state.outcome is not None:
        exc = retry_state.outcome.exception()
        if isinstance(exc, SoundlinkApiError) and exc.retry_after is not None:
            logger.warning("Rate limited; waiting %.0fs (Retry-After)", exc.retry_after)
            return exc.retry_after
    return wait_exponential_jitter(initial=1, max=60)(retry_state)


def _warn_schema_version(row: dict[str, Any], *, kind: str) -> None:
    version = row.get("schema_version")
    if version is not None and version != EXPECTED_SCHEMA_VERSION:
        logger.warning(
            "Unexpected %s schema_version=%r (expected %r)",
            kind,
            version,
            EXPECTED_SCHEMA_VERSION,
        )


def _unwrap_data(envelope: dict[str, Any], *, path: str) -> Any:
    if "data" not in envelope:
        raise SoundlinkApiError(f"Response for {path} missing top-level 'data' field")
    return envelope["data"]


class SoundlinkClient:
    """HTTP client for the Soundlink Public API (api.getsoundlink.com)."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.getsoundlink.com",
        timeout_seconds: float = 120.0,
        max_retries: int = 5,
        campaigns_page_size: int = DEFAULT_CAMPAIGNS_PAGE_SIZE,
        soundlinks_page_size: int = DEFAULT_SOUNDLINKS_PAGE_SIZE,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._campaigns_page_size = campaigns_page_size
        self._soundlinks_page_size = soundlinks_page_size
        self._client = httpx.Client(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "User-Agent": f"soundlink-warehouse-connector/{__version__}",
            },
            timeout=httpx.Timeout(timeout_seconds),
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SoundlinkClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        @retry(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(self._max_retries + 1),
            wait=_wait_retry_after_or_backoff,
            reraise=True,
        )
        def _do() -> httpx.Response:
            response = self._client.request(method, path, **kwargs)
            if response.status_code >= 400:
                raise SoundlinkApiError(
                    f"{method} {path} failed with {response.status_code}",
                    status_code=response.status_code,
                    body=response.text[:2000],
                    retry_after=_parse_retry_after(response)
                    if response.status_code == 429
                    else None,
                )
            return response

        return _do()

    def ping(self) -> dict[str, Any]:
        response = self._request("GET", "/v1/ping")
        data = _unwrap_data(response.json(), path="/v1/ping")
        if not isinstance(data, dict):
            raise SoundlinkApiError("GET /v1/ping returned non-object data")
        return data

    def get_campaign(self, campaign_id: str) -> CampaignSummary:
        path = f"/v1/campaigns/{campaign_id}"
        response = self._request("GET", path)
        data = _unwrap_data(response.json(), path=path)
        return CampaignSummary.model_validate(data)

    def list_campaigns_page(
        self, *, page: int = 1, page_size: int | None = None
    ) -> tuple[list[CampaignSummary], Pagination]:
        size = page_size if page_size is not None else self._campaigns_page_size
        response = self._request(
            "GET",
            "/v1/campaigns",
            params={"page": page, "pageSize": size},
        )
        data = _unwrap_data(response.json(), path="/v1/campaigns")
        items = [CampaignSummary.model_validate(item) for item in data["items"]]
        pagination = Pagination.model_validate(data["pagination"])
        return items, pagination

    def iter_campaigns(self, *, page_size: int | None = None) -> Iterator[CampaignSummary]:
        size = page_size if page_size is not None else self._campaigns_page_size
        page = 1
        while True:
            items, pagination = self.list_campaigns_page(page=page, page_size=size)
            yield from items
            if page >= pagination.total_pages:
                break
            page += 1

    def get_soundlink(self, soundlink_id: str) -> SoundlinkSummary:
        path = f"/v1/soundlinks/{soundlink_id}"
        response = self._request("GET", path)
        data = _unwrap_data(response.json(), path=path)
        return SoundlinkSummary.model_validate(data)

    def list_soundlinks_page(
        self, *, page: int = 1, page_size: int | None = None
    ) -> tuple[list[SoundlinkSummary], Pagination]:
        size = page_size if page_size is not None else self._soundlinks_page_size
        response = self._request(
            "GET",
            "/v1/soundlinks",
            params={"page": page, "pageSize": size},
        )
        data = _unwrap_data(response.json(), path="/v1/soundlinks")
        items = [SoundlinkSummary.model_validate(item) for item in data["items"]]
        pagination = Pagination.model_validate(data["pagination"])
        return items, pagination

    def iter_soundlinks(self, *, page_size: int | None = None) -> Iterator[SoundlinkSummary]:
        size = page_size if page_size is not None else self._soundlinks_page_size
        page = 1
        while True:
            items, pagination = self.list_soundlinks_page(page=page, page_size=size)
            yield from items
            if page >= pagination.total_pages:
                break
            page += 1

    def export_metrics_jsonl(
        self,
        *,
        kind: str,
        start_date: date,
        end_date: date,
        campaign_id: str | None = None,
        soundlink_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int | None]:
        """Stream JSONL metrics; retries transport errors and X-Row-Count mismatch."""
        if (campaign_id is None) == (soundlink_id is None):
            raise ValueError("Pass exactly one of campaign_id or soundlink_id")

        if campaign_id is not None:
            entity_id = campaign_id
            if kind == "breakdown":
                path = f"/v1/campaigns/{campaign_id}/metrics/breakdown/export"
                validate = validate_breakdown_row
            elif kind == "engagement":
                path = f"/v1/campaigns/{campaign_id}/metrics/engagement/export"
                validate = validate_engagement_row
            else:
                raise ValueError(f"Unknown export kind: {kind}")
        else:
            assert soundlink_id is not None
            entity_id = soundlink_id
            if kind == "breakdown":
                path = f"/v1/soundlinks/{soundlink_id}/metrics/breakdown/export"
                validate = validate_soundlink_breakdown_row
            elif kind == "engagement":
                path = f"/v1/soundlinks/{soundlink_id}/metrics/engagement/export"
                validate = validate_soundlink_engagement_row
            else:
                raise ValueError(f"Unknown export kind: {kind}")

        params: dict[str, str] = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
        }

        @retry(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(self._max_retries + 1),
            wait=_wait_retry_after_or_backoff,
            reraise=True,
        )
        def _fetch() -> tuple[list[dict[str, Any]], int | None]:
            request = self._client.build_request(
                "GET",
                path,
                params=params,
                headers={"Accept": "application/x-ndjson"},
            )
            response = self._client.send(request, stream=True)
            if response.status_code >= 400:
                body = response.read().decode("utf-8", errors="replace")[:2000]
                retry_after = (
                    _parse_retry_after(response) if response.status_code == 429 else None
                )
                response.close()
                raise SoundlinkApiError(
                    f"GET {path} failed with {response.status_code}",
                    status_code=response.status_code,
                    body=body,
                    retry_after=retry_after,
                )

            try:
                header_count = response.headers.get("X-Row-Count")
                expected = int(header_count) if header_count is not None else None

                rows: list[dict[str, Any]] = []
                for line in response.iter_lines():
                    if not line or not line.strip():
                        continue
                    raw = json.loads(line)
                    validate(raw)
                    _warn_schema_version(raw, kind=kind)
                    rows.append(raw)

                if expected is not None and expected != len(rows):
                    raise SoundlinkApiError(
                        f"X-Row-Count mismatch for {kind} {entity_id}: "
                        f"header={expected} parsed={len(rows)}",
                        retryable=True,
                    )
                return rows, expected
            finally:
                response.close()

        return _fetch()
