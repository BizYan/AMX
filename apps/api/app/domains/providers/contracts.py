"""Provider Contract Interfaces

Defines interfaces that all providers must implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class LLMResponse:
    """Response from LLM text generation."""
    text: str
    model: str
    usage: dict[str, int]  # prompt_tokens, completion_tokens, total_tokens
    finish_reason: str
    raw_response: dict[str, Any] | None = None


@dataclass
class EmbedResponse:
    """Response from text embedding."""
    embeddings: list[list[float]]  # list of embedding vectors
    model: str
    usage: dict[str, int]  # tokens per input
    raw_response: dict[str, Any] | None = None


@dataclass
class GraphifyOutput:
    """Output from Graphify graph extraction."""
    nodes: list[dict[str, Any]]  # list of node objects
    edges: list[dict[str, Any]]  # list of edge objects
    relationships: list[dict[str, Any]]  # list of relationship objects
    metadata: dict[str, Any] | None = None


@dataclass
class GitNexusOutput:
    """Output from GitNexus operations."""
    data: list[dict[str, Any]]  # list of commits or issues
    metadata: dict[str, Any] | None = None


class LLMContract(ABC):
    """Contract for LLM providers.

    All LLM providers must implement this interface.
    """

    @abstractmethod
    async def generate(self, prompt: str, params: dict[str, Any]) -> LLMResponse:
        """Generate text from a prompt.

        Args:
            prompt: The input prompt text
            params: Generation parameters (temperature, max_tokens, top_p, etc.)

        Returns:
            LLMResponse with generated text and usage information

        Raises:
            ProviderError: If generation fails
        """
        ...

    @abstractmethod
    async def embed(self, texts: list[str]) -> EmbedResponse:
        """Generate embeddings for texts.

        Args:
            texts: List of input texts to embed

        Returns:
            EmbedResponse with embedding vectors and usage information

        Raises:
            ProviderError: If embedding fails
        """
        ...


class GraphifyContract(ABC):
    """Contract for Graphify providers.

    Graphify providers extract knowledge graphs from documents.
    """

    @abstractmethod
    async def extract_graph(self, document_id: str, content: str, params: dict[str, Any]) -> GraphifyOutput:
        """Extract a knowledge graph from document content.

        Args:
            document_id: Unique identifier for the source document
            content: The document content to analyze
            params: Extraction parameters

        Returns:
            GraphifyOutput with nodes, edges, and relationships

        Raises:
            ProviderError: If extraction fails
        """
        ...


class GitNexusContract(ABC):
    """Contract for GitNexus providers.

    GitNexus providers fetch data from Git repositories.
    """

    @abstractmethod
    async def fetch_commits(self, repo_url: str, params: dict[str, Any]) -> GitNexusOutput:
        """Fetch commits from a repository.

        Args:
            repo_url: URL of the repository
            params: Query parameters (branch, since, until, limit, etc.)

        Returns:
            GitNexusOutput with commit data

        Raises:
            ProviderError: If fetch fails
        """
        ...

    @abstractmethod
    async def fetch_issues(self, repo_url: str, params: dict[str, Any]) -> GitNexusOutput:
        """Fetch issues from a repository.

        Args:
            repo_url: URL of the repository
            params: Query parameters (state, labels, assignee, etc.)

        Returns:
            GitNexusOutput with issue data

        Raises:
            ProviderError: If fetch fails
        """
        ...


class ProviderError(Exception):
    """Base exception for provider errors."""

    def __init__(self, message: str, provider: str | None = None, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.provider = provider
        self.details = details or {}


class RateLimitError(ProviderError):
    """Raised when provider rate limit is exceeded."""
    pass


class TimeoutError(ProviderError):
    """Raised when provider request times out."""
    pass


class AuthenticationError(ProviderError):
    """Raised when provider authentication fails."""
    pass


class ValidationError(ProviderError):
    """Raised when request validation fails."""
    pass