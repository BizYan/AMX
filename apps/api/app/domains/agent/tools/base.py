"""Base Tool Adapter

Abstract base class for all tool adapters in the system.
All tool adapters must implement this interface.
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseToolAdapter(ABC):
    """Base class for all tool adapters.

    Tool adapters are responsible for executing specific tools
    in the agent system. Each adapter handles a specific tool type
    and implements the contract defined in ToolContractSchema.
    """

    @property
    @abstractmethod
    def tool_name(self) -> str:
        """Return the name of the tool this adapter handles.

        Returns:
            Tool name string
        """
        pass

    @abstractmethod
    async def execute(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Execute the tool with given input.

        Args:
            input_data: Tool input data conforming to tool's input_schema

        Returns:
            Tool output data conforming to tool's output_schema

        Raises:
            ToolExecutionError: If tool execution fails
        """
        pass

    async def validate_input(self, input_data: dict[str, Any]) -> bool:
        """Validate input data against tool's input schema.

        Args:
            input_data: Input data to validate

        Returns:
            True if valid, False otherwise
        """
        return True  # Default implementation, override for schema validation


class ToolExecutionError(Exception):
    """Error raised when tool execution fails."""

    def __init__(
        self,
        message: str,
        tool_name: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.tool_name = tool_name
        self.details = details or {}