"""Optional OpenAI orchestration for research-grounded hypotheses."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable

import httpx

from app.services.research import ResearchResult
from app.settings import AnalysisSettings


class OpenAIOrchestrator:
    """Generate normalized hypothesis objects from project and research context.

    Importing/creating the OpenAI client is deferred until a key is present so
    installations without credentials remain fully usable in starter mode.
    """

    def __init__(
        self, api_key: str | None = None, *, model: str | None = None, client: Any | None = None,
        settings: AnalysisSettings | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        # The fallback is deliberately opt-in: an operator decides which lower
        # capability/cheaper model is safe for non-critical synthesis.
        self.fallback_model = os.getenv("OPENAI_FALLBACK_MODEL", "").strip() or None
        self.max_retries = max(0, int(os.getenv("OPENAI_MAX_RETRIES", "2")))
        self._sleep: Callable[[float], None] = time.sleep
        self._client = client
        self.settings = settings or AnalysisSettings.from_env()
        self.last_usage: dict[str, int | float] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost_usd": 0.0}

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def generate_hypotheses(
        self, project_context: dict[str, Any], research: list[ResearchResult]
    ) -> list[dict[str, str]]:
        """Return ``[{category, statement}]`` parsed from the model's JSON reply.

        No client is constructed and no network call is attempted without an
        API key.  This is intentional rather than an error: callers can choose
        the deterministic starter generator in that case.
        """
        self.last_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost_usd": 0.0}
        if not self.is_configured:
            return []

        client = self._client or self._create_client()
        language = project_context.get("language") if isinstance(project_context.get("language"), str) else "en"
        context = {
            "project": project_context,
            "research": [result.to_dict() for result in research],
        }
        request = {
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Generate testable business hypotheses grounded only in the supplied context. "
                        f"Write every hypothesis statement in {'Russian' if language == 'ru' else 'English'}. "
                        'Return JSON exactly shaped as {"hypotheses": [{"category": string, "statement": string}]}. '
                        "Do not include markdown."
                    ),
                },
                {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
            ],
        }
        response = self._request_with_fallback(client, request)
        self.last_usage = self._usage_from_response(response)
        content = response.choices[0].message.content if response.choices else None
        return self.parse_hypotheses(content)

    def _request_with_fallback(self, client: Any, request: dict[str, Any]) -> Any:
        """Retry transient failures, then degrade to an operator-approved model."""
        models = [self.model]
        if self.fallback_model and self.fallback_model != self.model:
            models.append(self.fallback_model)
        last_error: Exception | None = None
        for model in models:
            for attempt in range(self.max_retries + 1):
                try:
                    return client.chat.completions.create(model=model, **request)
                except Exception as exc:
                    last_error = exc
                    if not self._is_transient(exc) or attempt >= self.max_retries:
                        break
                    self._sleep(0.25 * (2 ** attempt))
        assert last_error is not None
        raise last_error

    @staticmethod
    def _is_transient(exc: Exception) -> bool:
        if isinstance(exc, (TimeoutError, ConnectionError, httpx.TimeoutException, httpx.TransportError)):
            return True
        status = getattr(exc, "status_code", None)
        if status is None:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
        return isinstance(status, int) and (status in {408, 409, 429} or status >= 500)

    def _usage_from_response(self, response: Any) -> dict[str, int | float]:
        """Normalize SDK usage objects without coupling callers to the SDK type."""
        usage = getattr(response, "usage", None)
        if usage is None and isinstance(response, dict):
            usage = response.get("usage")

        def token(name: str) -> int:
            raw = usage.get(name, 0) if isinstance(usage, dict) else getattr(usage, name, 0)
            return int(raw) if isinstance(raw, (int, float)) and raw >= 0 else 0

        prompt_tokens, completion_tokens = token("prompt_tokens"), token("completion_tokens")
        total_tokens = token("total_tokens") or prompt_tokens + completion_tokens
        cost = (
            prompt_tokens * self.settings.openai_input_cost_per_million_usd
            + completion_tokens * self.settings.openai_output_cost_per_million_usd
        ) / 1_000_000
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost_usd": float(cost),
        }

    def _create_client(self) -> Any:
        # The official SDK is optional at import time only so no-key deployments
        # do not need to initialize it. It is declared in requirements.txt.
        from openai import OpenAI

        return OpenAI(api_key=self.api_key)

    @staticmethod
    def parse_hypotheses(content: str | dict[str, Any] | None) -> list[dict[str, str]]:
        """Parse and validate the JSON contract returned by the LLM."""
        if isinstance(content, str):
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                return []
        else:
            payload = content
        if not isinstance(payload, dict) or not isinstance(payload.get("hypotheses"), list):
            return []

        hypotheses: list[dict[str, str]] = []
        for item in payload["hypotheses"]:
            if not isinstance(item, dict):
                continue
            category = item.get("category")
            statement = item.get("statement")
            if not isinstance(category, str) or not isinstance(statement, str):
                continue
            category, statement = category.strip(), statement.strip()
            if category and statement:
                hypotheses.append({"category": category[:50], "statement": statement[:2000]})
        return hypotheses
