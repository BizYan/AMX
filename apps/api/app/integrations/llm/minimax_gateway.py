"""MiniMax LLM Gateway

OpenAI-compatible gateway for MiniMax LLM API.
"""

import json
from typing import Any, AsyncIterator

import httpx
from pydantic import BaseModel

from app.domains.providers.contracts import LLMResponse, EmbedResponse, ProviderError


class MiniMaxGateway:
    """MiniMax LLM Gateway using OpenAI-compatible API.

    Provides text generation and embedding capabilities via MiniMax API.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.minimax.chat/v1",
        model: str = "MiniMax-Text-01",
    ):
        """Initialize MiniMax gateway.

        Args:
            api_key: MiniMax API key
            base_url: Base URL for API (OpenAI-compatible)
            model: Model name to use
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client.

        Returns:
            Configured httpx AsyncClient
        """
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def generate(
        self,
        prompt: str,
        params: dict[str, Any] | None = None,
        stream: bool = False,
    ) -> LLMResponse:
        """Generate text from a prompt.

        Args:
            prompt: Input prompt text
            params: Generation parameters (temperature, max_tokens, top_p, etc.)
            stream: Whether to stream the response

        Returns:
            LLMResponse with generated text and usage

        Raises:
            ProviderError: If generation fails
        """
        params = params or {}
        client = await self._get_client()

        payload = {
            "model": params.get("model", self.model),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": params.get("temperature", 0.7),
            "max_tokens": params.get("max_tokens", 2048),
            "top_p": params.get("top_p", 0.95),
            "stream": stream,
        }

        # Remove None values
        payload = {k: v for k, v in payload.items() if v is not None}

        try:
            response = await client.post("/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()

            return LLMResponse(
                text=data["choices"][0]["message"]["content"],
                model=data.get("model", self.model),
                usage={
                    "prompt_tokens": data.get("usage", {}).get("prompt_tokens", 0),
                    "completion_tokens": data.get("usage", {}).get("completion_tokens", 0),
                    "total_tokens": data.get("usage", {}).get("total_tokens", 0),
                },
                finish_reason=data["choices"][0].get("finish_reason", "stop"),
                raw_response=data,
            )
        except httpx.HTTPStatusError as e:
            raise ProviderError(
                message=f"HTTP error during generation: {e.response.status_code}",
                details={"status_code": e.response.status_code, "response": e.response.text},
            )
        except httpx.RequestError as e:
            raise ProviderError(message=f"Request error during generation: {str(e)}")
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise ProviderError(message=f"Invalid response format: {str(e)}")

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> EmbedResponse:
        """Generate embeddings for texts.

        Args:
            texts: List of texts to embed
            model: Optional embedding model override

        Returns:
            EmbedResponse with embedding vectors

        Raises:
            ProviderError: If embedding fails
        """
        client = await self._get_client()
        embed_model = model or "embo-01"

        payload = {
            "model": embed_model,
            "texts": texts,
        }

        try:
            response = await client.post("/embeddings", json=payload)
            response.raise_for_status()
            data = response.json()

            embeddings = [item["embedding"] for item in data.get("data", [])]

            return EmbedResponse(
                embeddings=embeddings,
                model=data.get("model", embed_model),
                usage={
                    "total_tokens": data.get("usage", {}).get("total_tokens", 0),
                },
                raw_response=data,
            )
        except httpx.HTTPStatusError as e:
            raise ProviderError(
                message=f"HTTP error during embedding: {e.response.status_code}",
                details={"status_code": e.response.status_code, "response": e.response.text},
            )
        except httpx.RequestError as e:
            raise ProviderError(message=f"Request error during embedding: {str(e)}")
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise ProviderError(message=f"Invalid response format: {str(e)}")

    async def stream_generate(
        self,
        prompt: str,
        params: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Stream generate text from a prompt.

        Args:
            prompt: Input prompt text
            params: Generation parameters

        Yields:
            Text chunks as they are generated

        Raises:
            ProviderError: If generation fails
        """
        params = params or {}

        client = await self._get_client()

        payload = {
            "model": params.get("model", self.model),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": params.get("temperature", 0.7),
            "max_tokens": params.get("max_tokens", 2048),
            "top_p": params.get("top_p", 0.95),
            "stream": True,
        }

        payload = {k: v for k, v in payload.items() if v is not None}

        try:
            async with client.stream("POST", "/chat/completions", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        data = json.loads(data_str)
                        if "choices" in data and len(data["choices"]) > 0:
                            delta = data["choices"][0].get("delta", {})
                            if "content" in delta:
                                yield delta["content"]
        except httpx.HTTPStatusError as e:
            raise ProviderError(
                message=f"HTTP error during streaming: {e.response.status_code}",
                details={"status_code": e.response.status_code, "response": e.response.text},
            )
        except httpx.RequestError as e:
            raise ProviderError(message=f"Request error during streaming: {str(e)}")

    def count_tokens(self, text: str) -> int:
        """Estimate token count for text.

        Simple estimation: ~4 characters per token for English.
        More accurate counting requires tiktoken or similar.

        Args:
            text: Input text

        Returns:
            Estimated token count
        """
        # Simple estimation - should use proper tokenization in production
        return len(text) // 4