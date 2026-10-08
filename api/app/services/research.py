"""Research-provider interfaces and a Tavily-compatible HTTP implementation."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx


@dataclass(frozen=True)
class ResearchResult:
    """A normalized result returned by an external search provider."""

    title: str
    url: str
    content: str
    score: float | None = None
    # Provenance is captured at fetch time so normalization replays do not
    # manufacture a new retrieval time.
    fetched_at: str | None = None
    source_metadata: dict[str, Any] | None = None
    content_truncated: bool = False
    original_content_length: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResearchProvider(Protocol):
    def search(self, query: str, *, max_results: int = 5) -> list[ResearchResult]:
        """Return normalized search results for *query*."""


MAX_RESULTS = 10
MAX_QUERY_LENGTH = 500
MAX_CONTENT_LENGTH = 4000

class TavilyResearchProvider:
    """Adapter for Tavily's ``/search``-style JSON API.

    The adapter deliberately becomes a no-op when no key is configured.  This
    keeps local development and starter-mode runs from making accidental
    external requests.
    """

    DEFAULT_URL = "https://api.tavily.com/search"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("SEARCH_API_KEY")
        self.base_url = base_url or os.getenv("SEARCH_API_URL", self.DEFAULT_URL)
        self._client = client

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def search(self, query: str, *, max_results: int = 5) -> list[ResearchResult]:
        query = query.strip()[:MAX_QUERY_LENGTH]
        max_results = max(1, min(max_results, MAX_RESULTS))
        if not self.is_configured or not query:
            return []

        payload = {
            "api_key": self.api_key,
            "query": query,
            "max_results": max_results,
            "include_answer": False,
        }
        if self._client is not None:
            response = self._client.post(self.base_url, json=payload)
            response.raise_for_status()
            return self.parse_results(response.json())

        # A short timeout prevents an analysis request from hanging indefinitely.
        with httpx.Client(timeout=10.0) as client:
            response = client.post(self.base_url, json=payload)
            response.raise_for_status()
            return self.parse_results(response.json())

    @staticmethod
    def parse_results(payload: Any) -> list[ResearchResult]:
        """Normalize a Tavily-like response, ignoring incomplete result items."""
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            return []

        parsed: list[ResearchResult] = []
        for item in payload["results"][:MAX_RESULTS]:
            if not isinstance(item, dict):
                continue
            title = item.get("title")
            url = item.get("url")
            content = item.get("content", item.get("snippet", ""))
            if not isinstance(title, str) or not isinstance(url, str) or not title or not url:
                continue
            title = title[:500]
            url = url[:2000]
            score = item.get("score")
            raw_content = content if isinstance(content, str) else ""
            parsed.append(
                ResearchResult(
                    title=title,
                    url=url,
                    content=raw_content[:MAX_CONTENT_LENGTH],
                    score=float(score) if isinstance(score, (int, float)) else None,
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    source_metadata={"provider": "tavily"},
                    content_truncated=len(raw_content) > MAX_CONTENT_LENGTH,
                    original_content_length=len(raw_content),
                )
            )
        return parsed[:MAX_RESULTS]
