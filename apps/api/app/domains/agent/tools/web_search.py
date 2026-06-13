"""Web search tool adapter backed by live HTTP search and page extraction."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx

from app.domains.agent.tools.base import BaseToolAdapter, ToolExecutionError


SEARCH_ENDPOINT = "https://duckduckgo.com/html/"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; AMX/1.0; +https://amx.yuanda.win)"
)


class _DuckDuckGoResultParser(HTMLParser):
    """Small DuckDuckGo HTML result parser without extra dependencies."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._snippets: list[str] = []
        self._fallback_links: list[dict[str, str]] = []
        self._current_link: dict[str, Any] | None = None
        self._current_snippet: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        classes = attr.get("class", "")
        href = attr.get("href", "")

        if tag == "a" and href:
            if "result__a" in classes:
                self._current_link = {"href": href, "text": []}
            elif href.startswith("http"):
                self._fallback_links.append({"title": "", "url": href, "snippet": ""})

        if tag in {"a", "div", "span"} and "result__snippet" in classes:
            self._current_snippet = []

    def handle_data(self, data: str) -> None:
        if self._current_link is not None:
            self._current_link["text"].append(data)
        if self._current_snippet is not None:
            self._current_snippet.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current_link is not None:
            title = _clean_text(" ".join(self._current_link["text"]))
            url = _normalize_result_url(str(self._current_link["href"]))
            if title and url:
                self.results.append({"title": title, "url": url, "snippet": ""})
            self._current_link = None

        if tag in {"a", "div", "span"} and self._current_snippet is not None:
            snippet = _clean_text(" ".join(self._current_snippet))
            if snippet:
                self._snippets.append(snippet)
            self._current_snippet = None

    def parsed_results(self, limit: int) -> list[dict[str, str]]:
        for index, snippet in enumerate(self._snippets):
            if index < len(self.results):
                self.results[index]["snippet"] = snippet

        results = self.results or self._fallback_links
        unique: list[dict[str, str]] = []
        seen: set[str] = set()
        for result in results:
            url = result.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            unique.append(
                {
                    "title": result.get("title") or urlparse(url).netloc or url,
                    "url": url,
                    "snippet": result.get("snippet", ""),
                }
            )
            if len(unique) >= limit:
                break
        return unique


class _ReadableTextParser(HTMLParser):
    """Extract readable text from a web page with noisy tags skipped."""

    SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "header"}
    BLOCK_TAGS = {"p", "div", "section", "article", "main", "li", "br", "h1", "h2", "h3"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag in self.BLOCK_TAGS and self.parts:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag in self.BLOCK_TAGS and self.parts:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = _clean_text(data)
        if text:
            self.parts.append(text)

    def text(self, max_chars: int = 5000) -> str:
        return _clean_text(" ".join(self.parts))[:max_chars]


class WebSearchToolAdapter(BaseToolAdapter):
    """Tool adapter for web search and optional page content extraction."""

    @property
    def tool_name(self) -> str:
        return "web_search"

    async def execute(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Execute a live web search.

        Input:
            query: search query.
            limit: maximum results, default 5, max 10.
            fetch_content: whether to fetch readable content for top results.
            fetch_content_limit: number of result pages to fetch, default 2.
            search_url: optional compatible search endpoint override for tests/self-hosted proxies.
        """
        query = _clean_text(str(input_data.get("query") or ""))
        if not query:
            raise ToolExecutionError("query is required", tool_name=self.tool_name)

        limit = _coerce_int(input_data.get("limit"), default=5, minimum=1, maximum=10)
        fetch_content = bool(input_data.get("fetch_content", False))
        fetch_content_limit = _coerce_int(
            input_data.get("fetch_content_limit"),
            default=2,
            minimum=0,
            maximum=limit,
        )
        search_url = str(input_data.get("search_url") or SEARCH_ENDPOINT)

        try:
            return await self._perform_search(
                query=query,
                limit=limit,
                fetch_content=fetch_content,
                fetch_content_limit=fetch_content_limit,
                search_url=search_url,
            )
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise ToolExecutionError(
                str(exc),
                tool_name=self.tool_name,
                details={"query": query, "provider": "duckduckgo_html"},
            )

    async def _perform_search(
        self,
        query: str,
        limit: int,
        fetch_content: bool,
        fetch_content_limit: int,
        search_url: str,
    ) -> dict[str, Any]:
        headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:
            response = await client.get(search_url, params={"q": query})
            response.raise_for_status()
            results = self._parse_search_results(response.text, limit=limit, base_url=search_url)
            if not results:
                raise ToolExecutionError(
                    "No search results could be parsed from provider response",
                    tool_name=self.tool_name,
                    details={"query": query, "provider": "duckduckgo_html", "status_code": response.status_code},
                )

            fetched_count = 0
            if fetch_content and fetch_content_limit > 0:
                for result in results[:fetch_content_limit]:
                    page = await self._fetch_page_content(result["url"], client=client)
                    if page.get("success"):
                        result["content"] = page["data"]["content"]
                        result["content_status_code"] = page["data"]["status_code"]
                        fetched_count += 1
                    else:
                        result["content_error"] = page.get("error", "content fetch failed")

        return {
            "success": True,
            "summary": f"Found {len(results)} live web result(s) for: {query}",
            "data": {
                "query": query,
                "provider": "duckduckgo_html",
                "results": results,
                "total_results": len(results),
                "fetch_content_requested": fetch_content,
                "fetched_content_count": fetched_count,
            },
            "evidence": [
                {
                    "source": "web_search",
                    "provider": "duckduckgo_html",
                    "query": query,
                    "result_count": len(results),
                    "fetched_content_count": fetched_count,
                }
            ],
        }

    def _parse_search_results(self, html: str, limit: int, base_url: str) -> list[dict[str, str]]:
        parser = _DuckDuckGoResultParser()
        parser.feed(html)
        results = parser.parsed_results(limit=limit)
        for result in results:
            result["url"] = urljoin(base_url, result["url"])
            result["url"] = _normalize_result_url(result["url"])
        return results

    async def _fetch_page_content(
        self,
        url: str,
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Fetch and extract readable page content."""

        async def fetch(active_client: httpx.AsyncClient) -> httpx.Response:
            response = await active_client.get(url)
            response.raise_for_status()
            return response

        try:
            if client is None:
                async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as new_client:
                    response = await fetch(new_client)
            else:
                response = await fetch(client)

            parser = _ReadableTextParser()
            parser.feed(response.text)
            content = parser.text(max_chars=5000)
            return {
                "success": True,
                "data": {
                    "url": url,
                    "content": content,
                    "status_code": response.status_code,
                },
            }
        except Exception as exc:
            return {"success": False, "error": f"Failed to fetch {url}: {exc}"}


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def _coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _normalize_result_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(unescape(url))
    if parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    return unquote(url)
