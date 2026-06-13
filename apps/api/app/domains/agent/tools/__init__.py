"""Agent Tool Adapters

This module contains tool adapters that handle tool execution
in the agent system. Each adapter implements BaseToolAdapter
and handles a specific tool type.
"""

from app.domains.agent.tools.base import BaseToolAdapter, ToolExecutionError
from app.domains.agent.tools.knowledge_graph import KnowledgeGraphToolAdapter
from app.domains.agent.tools.document_export import DocumentExportToolAdapter
from app.domains.agent.tools.web_search import WebSearchToolAdapter

# Registry of all tool adapters
TOOL_ADAPTERS = {
    "knowledge_graph": KnowledgeGraphToolAdapter,
    "document_export": DocumentExportToolAdapter,
    "web_search": WebSearchToolAdapter,
}

__all__ = [
    "BaseToolAdapter",
    "ToolExecutionError",
    "KnowledgeGraphToolAdapter",
    "DocumentExportToolAdapter",
    "WebSearchToolAdapter",
    "TOOL_ADAPTERS",
]