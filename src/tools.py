"""
Tool handlers for Obsidian Graph.

Transport-agnostic tool implementations that validate inputs, call engine
components, and return structured results. Used by server.py (MCP) and
can be reused by future transports (CLI, REST).
"""

from dataclasses import dataclass
from typing import Any

from .embedder import VoyageEmbedder
from .exceptions import EmbeddingError
from .graph_builder import GraphBuilder
from .hub_analyzer import HubAnalyzer
from .security_utils import validate_note_path_parameter
from .validation import (
    validate_connection_graph_args,
    validate_hub_notes_args,
    validate_orphaned_notes_args,
    validate_search_notes_args,
    validate_similar_notes_args,
)
from .vector_store import PostgreSQLVectorStore


@dataclass
class ToolContext:
    """Dependencies needed by tool handlers."""

    store: PostgreSQLVectorStore
    embedder: VoyageEmbedder
    graph_builder: GraphBuilder
    hub_analyzer: HubAnalyzer
    vault_path: str = "/vault"


class ToolError(Exception):
    """Raised when a tool handler fails. Contains a user-facing message."""

    pass


async def search_notes(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Semantic search across vault.

    Returns:
        {"results": [{"path", "title", "content", "similarity"}, ...]}
    """
    validated = validate_search_notes_args(arguments)

    try:
        query_embedding = await ctx.embedder.embed(validated["query"], input_type="query")
    except EmbeddingError as e:
        raise ToolError(f"Failed to generate query embedding: {e}") from e

    results = await ctx.store.search(query_embedding, validated["limit"], validated["threshold"])

    return {
        "results": [
            {
                "path": r.path,
                "title": r.title,
                "content": r.content,
                "similarity": r.similarity,
            }
            for r in results
        ]
    }


async def get_similar_notes(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Find notes similar to a given note.

    Returns:
        {"note_path": str, "results": [{"path", "title", "similarity"}, ...]}
    """
    validated = validate_similar_notes_args(arguments)
    note_path = validate_note_path_parameter(validated["note_path"], vault_path=ctx.vault_path)

    results = await ctx.store.get_similar_notes(
        note_path, validated["limit"], validated["threshold"]
    )

    return {
        "note_path": note_path,
        "results": [
            {
                "path": r.path,
                "title": r.title,
                "similarity": r.similarity,
            }
            for r in results
        ],
    }


async def get_connection_graph(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Build multi-hop connection graph from a starting note.

    Returns:
        The graph dict from GraphBuilder (root, nodes, edges, stats).
    """
    validated = validate_connection_graph_args(arguments)
    note_path = validate_note_path_parameter(validated["note_path"], vault_path=ctx.vault_path)

    return await ctx.graph_builder.build_connection_graph(
        note_path, validated["depth"], validated["max_per_level"], validated["threshold"]
    )


async def get_hub_notes(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Identify highly connected hub notes.

    Returns:
        {"min_connections": int, "threshold": float, "results": [{"path", "title", "connection_count"}, ...]}
    """
    validated = validate_hub_notes_args(arguments)

    hubs = await ctx.hub_analyzer.get_hub_notes(
        validated["min_connections"], validated["threshold"], validated["limit"]
    )

    return {
        "min_connections": validated["min_connections"],
        "threshold": validated["threshold"],
        "results": hubs,
    }


async def get_orphaned_notes(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Find isolated notes with few connections.

    Returns:
        {"max_connections": int, "results": [{"path", "title", "connection_count", "modified_at"}, ...]}
    """
    validated = validate_orphaned_notes_args(arguments)

    orphans = await ctx.hub_analyzer.get_orphaned_notes(
        validated["max_connections"], validated["threshold"], validated["limit"]
    )

    return {
        "max_connections": validated["max_connections"],
        "results": orphans,
    }


# Tool dispatch table
TOOLS = {
    "search_notes": search_notes,
    "get_similar_notes": get_similar_notes,
    "get_connection_graph": get_connection_graph,
    "get_hub_notes": get_hub_notes,
    "get_orphaned_notes": get_orphaned_notes,
}
