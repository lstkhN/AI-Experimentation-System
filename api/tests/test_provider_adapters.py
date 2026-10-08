import httpx

from app.services.openai_orchestrator import OpenAIOrchestrator
from app.services.research import TavilyResearchProvider


class FailingClient:
    def __getattr__(self, _name):
        raise AssertionError("a provider client must not be used without an API key")


def test_no_key_providers_are_safe_noops():
    research = TavilyResearchProvider(api_key="", client=FailingClient())
    llm = OpenAIOrchestrator(api_key="", client=FailingClient())

    assert research.search("customer research") == []
    assert llm.generate_hypotheses({"name": "Test"}, []) == []


def test_tavily_provider_posts_and_parses_results():
    request_payload = {}

    def handler(request: httpx.Request) -> httpx.Response:
        request_payload.update(__import__("json").loads(request.content))
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "Market report", "url": "https://example.test/report", "content": "Demand is growing", "score": 0.91},
                    {"title": "Incomplete"},
                ]
            },
        )

    provider = TavilyResearchProvider(
        api_key="test-key",
        base_url="https://search.test/search",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = provider.search("market demand", max_results=3)[0]
    assert result.to_dict() | {"fetched_at": "captured"} == {
        "title": "Market report",
        "url": "https://example.test/report",
        "content": "Demand is growing",
        "score": 0.91,
        "fetched_at": "captured",
        "source_metadata": {"provider": "tavily"},
        "content_truncated": False,
        "original_content_length": len("Demand is growing"),
    }
    assert request_payload["api_key"] == "test-key"
    assert request_payload["query"] == "market demand"
    assert request_payload["max_results"] == 3


def test_openai_orchestrator_parses_structured_hypotheses():
    assert OpenAIOrchestrator.parse_hypotheses(
        '{"hypotheses": [{"category": "problem", "statement": "Teams spend hours preparing proposals."}, {"statement": "invalid"}]}'
    ) == [{"category": "problem", "statement": "Teams spend hours preparing proposals."}]
