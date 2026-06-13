from __future__ import annotations

import pytest
from types import SimpleNamespace

from app.domains.agent.tools.base import ToolExecutionError
from app.domains.agent.tools.knowledge_graph import KnowledgeGraphToolAdapter
from app.domains.agent.tools.web_search import WebSearchToolAdapter


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200, url: str = "https://duckduckgo.com/html/"):
        self.text = text
        self.status_code = status_code
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeAsyncClient:
    requests: list[tuple[str, dict]] = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, **kwargs):
        self.requests.append((url, kwargs))
        if "duckduckgo.com/html" in url:
            return FakeResponse(
                """
                <html><body>
                  <div class="result">
                    <a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.org%2Fcase-study&amp;rut=abc">Real case study</a>
                    <a class="result__snippet">A practical source about AI consulting delivery.</a>
                  </div>
                  <div class="result">
                    <a class="result__a" href="https://vendor.example/docs">Vendor docs</a>
                    <div class="result__snippet">Official implementation documentation.</div>
                  </div>
                </body></html>
                """
            )
        if "example.org/case-study" in url:
            return FakeResponse(
                "<html><head><title>Case Study</title></head><body><nav>skip</nav><main>AI consulting delivery uses source evidence and traceability.</main></body></html>",
                url=url,
            )
        return FakeResponse("<html><body>Vendor implementation documentation.</body></html>", url=url)


@pytest.mark.asyncio
async def test_web_search_uses_real_search_html_and_decodes_result_urls(monkeypatch):
    FakeAsyncClient.requests = []
    monkeypatch.setattr("app.domains.agent.tools.web_search.httpx.AsyncClient", FakeAsyncClient)

    result = await WebSearchToolAdapter().execute(
        {
            "query": "AI consulting delivery traceability",
            "limit": 2,
            "fetch_content": True,
            "fetch_content_limit": 1,
        }
    )

    assert result["success"] is True
    data = result["data"]
    assert data["provider"] == "duckduckgo_html"
    assert data["total_results"] == 2
    assert data["results"][0]["title"] == "Real case study"
    assert data["results"][0]["url"] == "https://example.org/case-study"
    assert data["results"][0]["snippet"] == "A practical source about AI consulting delivery."
    assert "AI consulting delivery uses source evidence" in data["results"][0]["content"]
    assert data["fetched_content_count"] == 1
    assert result["evidence"][0]["source"] == "web_search"
    assert "duckduckgo.com/html" in FakeAsyncClient.requests[0][0]


@pytest.mark.asyncio
async def test_web_search_raises_tool_error_when_provider_returns_no_results(monkeypatch):
    class EmptyClient(FakeAsyncClient):
        async def get(self, url: str, **kwargs):
            return FakeResponse("<html><body>No results</body></html>")

    monkeypatch.setattr("app.domains.agent.tools.web_search.httpx.AsyncClient", EmptyClient)

    with pytest.raises(ToolExecutionError) as exc:
        await WebSearchToolAdapter().execute({"query": "no hits"})

    assert "No search results" in str(exc.value)
    assert exc.value.details["provider"] == "duckduckgo_html"


def test_knowledge_graph_search_ranks_entries_with_explainable_lexical_scores():
    adapter = KnowledgeGraphToolAdapter()
    entries = [
        SimpleNamespace(
            id="entry-low",
            entry_type="text",
            content="Only traceability evidence is mentioned here.",
            metadata_json={"title": "Evidence note"},
        ),
        SimpleNamespace(
            id="entry-high",
            entry_type="text",
            content="AI consulting delivery traceability links source evidence to exported documents.",
            metadata_json={"title": "AI delivery traceability"},
        ),
        SimpleNamespace(
            id="entry-none",
            entry_type="text",
            content="Unrelated billing notes.",
            metadata_json={},
        ),
    ]

    ranked = adapter._rank_entries(entries, query_text="AI delivery traceability", limit=3)

    assert [entry.id for entry, _, _ in ranked] == ["entry-high", "entry-low"]
    assert ranked[0][1] > ranked[1][1]
    assert ranked[0][2] == ["ai", "delivery", "traceability"]
    assert ranked[1][2] == ["traceability"]
