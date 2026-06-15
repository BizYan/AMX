"""Graphify Provider Adapter

Implements GraphifyContract with fixture backing for testing.
"""

import json
from pathlib import Path
from typing import Any

from app.domains.providers.contracts import GraphifyContract, GraphifyOutput, ProviderError


class GraphifyProvider(GraphifyContract):
    """Graphify provider with fixture support for testing.

    If fixture_data is provided, uses it instead of calling the actual endpoint.
    This allows for deterministic testing without external dependencies.
    """

    def __init__(self, config: dict[str, Any], fixture_data: dict[str, Any] | None = None):
        """Initialize Graphify provider.

        Args:
            config: Provider configuration containing:
                - endpoint: Graphify API endpoint URL
                - api_key: Optional API key
                - timeout: Request timeout in seconds
            fixture_data: Optional fixture data to use instead of real API calls
        """
        self.config = config
        self.endpoint = self._configured_endpoint(config)
        self.api_key = config.get("api_key")
        self.timeout = config.get("timeout", 30)
        self.fixture_data = fixture_data

    async def extract_graph(
        self,
        document_id: str,
        content: str,
        params: dict[str, Any] | None = None,
    ) -> GraphifyOutput:
        """Extract a knowledge graph from document content.

        Args:
            document_id: Unique identifier for the source document
            content: The document content to analyze
            params: Extraction parameters (extraction_type, max_nodes, etc.)

        Returns:
            GraphifyOutput with nodes, edges, and relationships

        Raises:
            ProviderError: If extraction fails
        """
        params = params or {}

        # Use fixture data if available
        if self.fixture_data is not None:
            return self._process_fixture(self.fixture_data, document_id)

        # Call actual Graphify endpoint
        return await self._call_graphify_api(document_id, content, params)

    @staticmethod
    def _configured_endpoint(config: dict[str, Any]) -> str | None:
        for key in ("endpoint", "base_url", "server_url", "api_url", "url"):
            value = config.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().rstrip("/")
        return None

    def _process_fixture(self, fixture: dict[str, Any], document_id: str) -> GraphifyOutput:
        """Process fixture data and inject document_id.

        Args:
            fixture: Fixture data dictionary
            document_id: Document ID to attach to nodes

        Returns:
            GraphifyOutput with fixture data
        """
        nodes = fixture.get("nodes", [])
        edges = fixture.get("edges", [])
        relationships = fixture.get("relationships", [])

        # Inject document_id into node properties
        for node in nodes:
            if "properties" not in node:
                node["properties"] = {}
            node["properties"]["source_document_id"] = document_id

        return GraphifyOutput(
            nodes=nodes,
            edges=edges,
            relationships=relationships,
            metadata=fixture.get("metadata", {}),
        )

    async def _call_graphify_api(
        self,
        document_id: str,
        content: str,
        params: dict[str, Any],
    ) -> GraphifyOutput:
        """Call the Graphify API endpoint.

        Args:
            document_id: Document identifier
            content: Document content
            params: Extraction parameters

        Returns:
            GraphifyOutput from API response

        Raises:
            ProviderError: If API call fails
        """
        import httpx

        if not self.endpoint:
            raise ProviderError(message="Graphify endpoint is required")

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "document_id": document_id,
            "content": content,
            "params": params,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.endpoint}/extract",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()

                return GraphifyOutput(
                    nodes=data.get("nodes", []),
                    edges=data.get("edges", []),
                    relationships=data.get("relationships", []),
                    metadata=data.get("metadata"),
                )
        except httpx.HTTPStatusError as e:
            raise ProviderError(
                message=f"Graphify API error: {e.response.status_code}",
                details={"status_code": e.response.status_code, "response": e.response.text},
            )
        except httpx.RequestError as e:
            raise ProviderError(message=f"Graphify request failed: {str(e)}")
        except json.JSONDecodeError as e:
            raise ProviderError(message=f"Invalid JSON from Graphify: {str(e)}")


def load_fixture(fixture_path: str | Path) -> dict[str, Any]:
    """Load fixture data from a JSON file.

    Args:
        fixture_path: Path to fixture JSON file

    Returns:
        Fixture data dictionary

    Raises:
        FileNotFoundError: If fixture file doesn't exist
        json.JSONDecodeError: If fixture is not valid JSON
    """
    path = Path(fixture_path)
    if not path.exists():
        raise FileNotFoundError(f"Fixture file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# Default fixture paths
DEFAULT_FIXTURES_PATH = Path(__file__).parent.parent.parent.parent / "tests" / "fixtures" / "graphify"
