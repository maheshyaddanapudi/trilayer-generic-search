"""Generic JSON array REST API connector.

Fetches any URL that returns a JSON array and yields RawEntity objects.
The only thing specific to a particular API is _parse_record() — everything
else (HTTP, timeout, in-memory buffering) is reusable across domains.
Subclass and override _parse_record() to adapt to a new JSON API.
"""
from __future__ import annotations

import logging
from typing import Iterator

import httpx

from src.domain.connector import SourceConnector
from src.models.core import RawEntity

log = logging.getLogger(__name__)


class JsonApiConnector(SourceConnector):
    """Fetches a JSON array from a URL and maps each record to a RawEntity.

    Parameters
    ----------
    base_url:
        Full URL that returns a JSON array, e.g.
        ``https://jsonplaceholder.typicode.com/posts``
    domain_id:
        The domain this connector belongs to (e.g. ``"posts"``).
    timeout_s:
        HTTP request timeout in seconds.
    """

    supports_incremental = False  # API has no updated_at field to filter on

    def __init__(self, base_url: str, domain_id: str, timeout_s: float = 30.0) -> None:
        self._base_url = base_url
        self._domain_id = domain_id
        self._timeout_s = timeout_s
        self._records: list[dict] = []

    # ── SourceConnector interface ─────────────────────────────────────────────

    def connect(self) -> None:
        """Fetch all records from the API and hold them in memory."""
        log.info("Fetching records from %s", self._base_url)
        response = httpx.get(self._base_url, timeout=self._timeout_s)
        response.raise_for_status()
        self._records = response.json()
        log.info("Fetched %d records", len(self._records))

    def disconnect(self) -> None:
        self._records = []

    def fetch_all(self) -> Iterator[RawEntity]:
        for record in self._records:
            yield self._parse_record(record)

    # ── Private ───────────────────────────────────────────────────────────────

    def _parse_record(self, record: dict) -> RawEntity:
        """Map one API record to a RawEntity.

        Adapt this method when switching to a different JSON API — only the
        field names change; the RawEntity contract stays the same.
        """
        post_id = str(record["id"])
        user_id = str(record.get("userId", ""))
        title   = record.get("title", "").strip()
        body    = record.get("body", "").replace("\n", " ").strip()

        return RawEntity(
            entity_id   = post_id,
            entity_type = "Post",
            domain_id   = self._domain_id,
            name        = title,
            description = body,
            # parent_id groups posts under their author — enables graph edges
            parent_id   = f"user_{user_id}",
            properties  = {
                "post_id": post_id,
                "user_id": user_id,
                "title":   title,
                "body":    body,
            },
        )
