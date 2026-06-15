"""Provider Contract Tests

Tests for verifying provider contract implementations.
"""

import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.domains.providers.contracts import (
    GraphifyContract,
    GitNexusContract,
    GraphifyOutput,
    GitNexusOutput,
    ProviderError,
)
from app.integrations.graphify.adapter import GraphifyProvider, load_fixture
from app.integrations.gitnexus.adapter import GitNexusProvider, load_fixture


# Fixture paths
GRAPHIFY_FIXTURES = Path(__file__).parent.parent / "fixtures" / "graphify"
GITNEXUS_FIXTURES = Path(__file__).parent.parent / "fixtures" / "gitnexus"


class TestGraphifyContract:
    """Tests for GraphifyContract implementation."""

    @pytest.fixture
    def graphify_provider(self):
        """Create GraphifyProvider with fixture data."""
        config = {
            "endpoint": "http://localhost:8000",
            "api_key": "test-key",
            "timeout": 30,
        }
        return GraphifyProvider(config)

    @pytest.fixture
    def graphify_with_happy_fixture(self, graphify_provider):
        """Create provider with happy path fixture loaded."""
        fixture_path = GRAPHIFY_FIXTURES / "happy_path.json"
        fixture_data = load_fixture(fixture_path)
        graphify_provider.fixture_data = fixture_data
        return graphify_provider

    def test_graphify_provider_implements_contract(self, graphify_provider):
        """Verify GraphifyProvider implements GraphifyContract."""
        assert isinstance(graphify_provider, GraphifyContract)

    @pytest.mark.asyncio
    async def test_graphify_provider_requires_configured_endpoint_without_fixture(self):
        """Graphify must not fall back to localhost when runtime config is missing."""
        provider = GraphifyProvider(config={})

        with pytest.raises(ProviderError, match="endpoint"):
            await provider.extract_graph(document_id="doc", content="content", params={})

    @pytest.mark.asyncio
    async def test_extract_graph_with_fixture(self, graphify_with_happy_fixture):
        """Test graph extraction with happy path fixture."""
        provider = graphify_with_happy_fixture

        result = await provider.extract_graph(
            document_id="test-doc-001",
            content="Sample document content",
            params={},
        )

        assert isinstance(result, GraphifyOutput)
        assert len(result.nodes) > 0
        assert len(result.edges) > 0
        # Verify document_id was injected
        for node in result.nodes:
            props = node.get("properties", {})
            assert props.get("source_document_id") == "test-doc-001"

    @pytest.mark.asyncio
    async def test_extract_graph_happy_path_nodes(self, graphify_with_happy_fixture):
        """Verify happy path fixture produces expected node types."""
        provider = graphify_with_happy_fixture

        result = await provider.extract_graph(
            document_id="test-doc",
            content="Test",
            params={},
        )

        node_types = {n.get("type") for n in result.nodes}
        assert "person" in node_types
        assert "organization" in node_types
        assert "project" in node_types
        assert "concept" in node_types

    @pytest.mark.asyncio
    async def test_extract_graph_happy_path_edges(self, graphify_with_happy_fixture):
        """Verify happy path fixture produces expected edge types."""
        provider = graphify_with_happy_fixture

        result = await provider.extract_graph(
            document_id="test-doc",
            content="Test",
            params={},
        )

        edge_types = {e.get("type") for e in result.edges}
        assert "works_for" in edge_types
        assert "leads" in edge_types
        assert "uses" in edge_types
        assert "reports_to" in edge_types


class TestGitNexusContract:
    """Tests for GitNexusContract implementation."""

    @pytest.fixture
    def gitnexus_provider(self):
        """Create GitNexusProvider with fixture data."""
        config = {
            "endpoint": "http://localhost:8001",
            "api_key": "test-key",
            "timeout": 30,
        }
        return GitNexusProvider(config)

    @pytest.fixture
    def gitnexus_with_commits_fixture(self, gitnexus_provider):
        """Create provider with commits fixture loaded."""
        fixture_path = GITNEXUS_FIXTURES / "happy_path_commits.json"
        fixture_data = load_fixture(fixture_path)
        gitnexus_provider.fixture_data = fixture_data
        return gitnexus_provider

    @pytest.fixture
    def gitnexus_with_issues_fixture(self, gitnexus_provider):
        """Create provider with issues fixture loaded."""
        fixture_path = GITNEXUS_FIXTURES / "happy_path_issues.json"
        fixture_data = load_fixture(fixture_path)
        gitnexus_provider.fixture_data = fixture_data
        return gitnexus_provider

    def test_gitnexus_provider_implements_contract(self, gitnexus_provider):
        """Verify GitNexusProvider implements GitNexusContract."""
        assert isinstance(gitnexus_provider, GitNexusContract)

    def test_gitnexus_provider_accepts_registration_config_aliases(self):
        """AMX registration config must be enough for the runtime adapter."""
        provider = GitNexusProvider(
            {
                "base_url": "http://127.0.0.1:4747/",
                "service_key": "live-service-key",
                "health_path": "/api/health",
                "timeout": 15,
            }
        )

        assert provider.endpoint == "http://127.0.0.1:4747"
        assert provider.api_key == "live-service-key"
        assert provider.health_path == "/api/health"
        assert provider.timeout == 15

    def test_gitnexus_provider_requires_configured_endpoint(self):
        """GitNexus must not fall back to localhost when runtime config is missing."""
        with pytest.raises(ValueError, match="endpoint"):
            GitNexusProvider({})

    @pytest.mark.asyncio
    async def test_gitnexus_provider_health_check_uses_api_health_path(self):
        """GitNexus registration smoke tests should use the stable health endpoint."""
        calls = {}

        class FakeResponse:
            status_code = 200
            text = '{"status":"ok"}'

        class FakeClient:
            def __init__(self, timeout):
                calls["timeout"] = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def get(self, url, headers):
                calls["url"] = url
                calls["headers"] = headers
                return FakeResponse()

        provider = GitNexusProvider(
            {
                "endpoint": "http://gitnexus-server:4747/",
                "service_key": "live-service-key",
                "health_path": "/api/health",
                "timeout": 12,
            }
        )

        with patch("app.integrations.gitnexus.adapter.httpx.AsyncClient", FakeClient):
            result = await provider.check_health()

        assert result == {"status": "ok"}
        assert calls["timeout"] == 12
        assert calls["url"] == "http://gitnexus-server:4747/api/health"
        assert calls["headers"] == {"Authorization": "Bearer live-service-key"}

    @pytest.mark.asyncio
    async def test_fetch_commits_with_fixture(self, gitnexus_with_commits_fixture):
        """Test commit fetching with happy path fixture."""
        provider = gitnexus_with_commits_fixture

        result = await provider.fetch_commits(
            repo_url="https://github.com/example/project",
            params={},
        )

        assert isinstance(result, GitNexusOutput)
        assert len(result.data) > 0
        # Verify repo_url was injected
        for commit in result.data:
            meta = commit.get("metadata", {})
            assert meta.get("repo_url") == "https://github.com/example/project"

    @pytest.mark.asyncio
    async def test_fetch_commits_happy_path_structure(self, gitnexus_with_commits_fixture):
        """Verify commits fixture has expected structure."""
        provider = gitnexus_with_commits_fixture

        result = await provider.fetch_commits(
            repo_url="https://github.com/example/project",
            params={},
        )

        assert len(result.data) == 4
        commit = result.data[0]
        assert "sha" in commit
        assert "message" in commit
        assert "author" in commit
        assert "timestamp" in commit

    @pytest.mark.asyncio
    async def test_fetch_issues_with_fixture(self, gitnexus_with_issues_fixture):
        """Test issue fetching with happy path fixture."""
        provider = gitnexus_with_issues_fixture

        result = await provider.fetch_issues(
            repo_url="https://github.com/example/project",
            params={},
        )

        assert isinstance(result, GitNexusOutput)
        assert len(result.data) > 0
        # Verify repo_url was injected
        for issue in result.data:
            meta = issue.get("metadata", {})
            assert meta.get("repo_url") == "https://github.com/example/project"

    @pytest.mark.asyncio
    async def test_fetch_issues_happy_path_structure(self, gitnexus_with_issues_fixture):
        """Verify issues fixture has expected structure."""
        provider = gitnexus_with_issues_fixture

        result = await provider.fetch_issues(
            repo_url="https://github.com/example/project",
            params={},
        )

        assert len(result.data) == 3
        issue = result.data[0]
        assert "number" in issue
        assert "title" in issue
        assert "body" in issue
        assert "state" in issue
        assert "labels" in issue


class TestProviderError:
    """Tests for ProviderError exception."""

    def test_provider_error_creation(self):
        """Test ProviderError with all fields."""
        error = ProviderError(
            message="Test error",
            provider="test-provider",
            details={"code": "TEST_ERROR"},
        )
        assert str(error) == "Test error"
        assert error.provider == "test-provider"
        assert error.details == {"code": "TEST_ERROR"}

    def test_provider_error_defaults(self):
        """Test ProviderError with default values."""
        error = ProviderError(message="Simple error")
        assert error.provider is None
        assert error.details == {}


class TestGraphNormalizer:
    """Tests for GraphNormalizer service."""

    @pytest.fixture
    def graph_normalizer(self):
        """Create GraphNormalizer instance."""
        from app.services.graph_normalizer import GraphNormalizer
        return GraphNormalizer()

    @pytest.fixture
    def sample_graphify_output(self):
        """Create sample GraphifyOutput for testing."""
        return GraphifyOutput(
            nodes=[
                {
                    "id": "person-1",
                    "type": "person",
                    "name": "Alice Chen",
                    "properties": {"role": "Engineer"},
                },
                {
                    "id": "org-1",
                    "type": "organization",
                    "name": "Acme Corp",
                    "properties": {"industry": "Tech"},
                },
            ],
            edges=[
                {
                    "id": "edge-1",
                    "source": "person-1",
                    "target": "org-1",
                    "type": "works_for",
                    "properties": {"since": "2022"},
                },
            ],
            relationships=[],
            metadata={"document_id": "doc-123"},
        )

    @pytest.mark.asyncio
    async def test_normalize_creates_nodes(
        self, graph_normalizer, sample_graphify_output
    ):
        """Test that normalize creates NormalizedGraphNode objects."""
        tenant_id = uuid4()
        project_id = uuid4()
        provider_id = uuid4()
        version_id = uuid4()

        nodes, edges, unresolved_edges = await graph_normalizer.normalize(
            provider_id=provider_id,
            version_id=version_id,
            raw_output=sample_graphify_output,
            tenant_id=tenant_id,
            project_id=project_id,
        )

        assert len(nodes) == 2
        assert all(hasattr(n, "entity_type") for n in nodes)
        assert all(hasattr(n, "entity_name") for n in nodes)
        assert all(hasattr(n, "properties_json") for n in nodes)

    @pytest.mark.asyncio
    async def test_normalize_creates_edges(
        self, graph_normalizer, sample_graphify_output
    ):
        """Test that normalize creates NormalizedGraphEdge objects."""
        tenant_id = uuid4()
        project_id = uuid4()
        provider_id = uuid4()
        version_id = uuid4()

        nodes, edges, unresolved_edges = await graph_normalizer.normalize(
            provider_id=provider_id,
            version_id=version_id,
            raw_output=sample_graphify_output,
            tenant_id=tenant_id,
            project_id=project_id,
        )

        assert len(edges) == 1
        edge = edges[0]
        assert hasattr(edge, "source_node_id")
        assert hasattr(edge, "target_node_id")
        assert hasattr(edge, "relationship_type")

    @pytest.mark.asyncio
    async def test_normalize_preserves_tenant_isolation(
        self, graph_normalizer, sample_graphify_output
    ):
        """Test that normalize preserves tenant_id in all entities."""
        tenant_id = uuid4()
        project_id = uuid4()
        provider_id = uuid4()
        version_id = uuid4()

        nodes, edges, unresolved_edges = await graph_normalizer.normalize(
            provider_id=provider_id,
            version_id=version_id,
            raw_output=sample_graphify_output,
            tenant_id=tenant_id,
            project_id=project_id,
        )

        for node in nodes:
            assert node.tenant_id == tenant_id
            assert node.project_id == project_id
            assert node.provider_id == provider_id

        for edge in edges:
            assert edge.tenant_id == tenant_id
            assert edge.project_id == project_id


class TestFixtureLoader:
    """Tests for fixture loading utilities."""

    def test_load_graphify_fixture(self):
        """Test loading Graphify fixture file."""
        fixture_path = GRAPHIFY_FIXTURES / "happy_path.json"
        data = load_fixture(fixture_path)

        assert "nodes" in data
        assert "edges" in data
        assert "relationships" in data
        assert len(data["nodes"]) > 0

    def test_load_gitnexus_commits_fixture(self):
        """Test loading GitNexus commits fixture file."""
        fixture_path = GITNEXUS_FIXTURES / "happy_path_commits.json"
        data = load_fixture(fixture_path)

        assert "commits" in data
        assert len(data["commits"]) > 0

    def test_load_gitnexus_issues_fixture(self):
        """Test loading GitNexus issues fixture file."""
        fixture_path = GITNEXUS_FIXTURES / "happy_path_issues.json"
        data = load_fixture(fixture_path)

        assert "issues" in data
        assert len(data["issues"]) > 0

    def test_load_fixture_file_not_found(self):
        """Test that loading non-existent fixture raises error."""
        with pytest.raises(FileNotFoundError):
            load_fixture("/nonexistent/path/fixture.json")
