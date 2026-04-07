"""ToolSearch - deferred tool schema loading.

When tools are too numerous to include in every request, ToolSearch
lets the model discover tools by keyword, then fetch their full schemas
on demand. This keeps the context window lean while still exposing a
large tool surface.

Usage by the model:
  1. Call ToolSearch with a query like "notebook" or "select:Read,Edit"
  2. Get back matching tool names + descriptions
  3. Call ToolSearch with "select:ToolName" to fetch full schema
  4. Now the tool can be invoked normally
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from axion.tools.registry import GlobalToolRegistry, ToolSpec, get_tool_registry


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class ToolSearchResult:
    """A single tool match from a search."""

    name: str
    description: str
    score: float = 0.0


@dataclass
class ToolSearchOutput:
    """Output from a ToolSearch query."""

    query: str
    results: list[ToolSearchResult] = field(default_factory=list)
    schemas: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""


# ---------------------------------------------------------------------------
# Deferred tool registry
# ---------------------------------------------------------------------------

class DeferredToolRegistry:
    """Manages tools that are loaded on demand.

    Tools can be registered as "deferred" — only their name and description
    are included in the system prompt. Their full schema is fetched via
    ToolSearch when the model needs them.
    """

    def __init__(self, full_registry: GlobalToolRegistry | None = None) -> None:
        self._full_registry = full_registry or get_tool_registry()
        self._deferred: dict[str, ToolSpec] = {}
        self._active: set[str] = set()  # Tools whose schemas are active

    def defer_tool(self, name: str) -> None:
        """Mark a tool as deferred (schema not included by default)."""
        tool = self._full_registry.get(name)
        if tool:
            self._deferred[name] = tool.spec
            self._active.discard(name)

    def activate_tool(self, name: str) -> ToolSpec | None:
        """Activate a deferred tool (include its schema)."""
        if name in self._deferred:
            self._active.add(name)
            return self._deferred[name]
        # Also check full registry
        tool = self._full_registry.get(name)
        if tool:
            self._active.add(name)
            return tool.spec
        return None

    def deferred_tool_names(self) -> list[str]:
        """Get names of tools that are deferred but not yet active."""
        return [n for n in self._deferred if n not in self._active]

    def active_tool_names(self) -> list[str]:
        """Get names of tools whose schemas are currently active."""
        return list(self._active)

    def is_active(self, name: str) -> bool:
        return name in self._active


# ---------------------------------------------------------------------------
# Search implementation
# ---------------------------------------------------------------------------

def tool_search(
    query: str,
    registry: GlobalToolRegistry | None = None,
    max_results: int = 5,
) -> ToolSearchOutput:
    """Search for tools by query.

    Query formats:
    - "select:Read,Edit,Grep" — fetch exact tools by name (returns full schemas)
    - "notebook jupyter" — keyword search, returns top matches by relevance
    - "+slack send" — require "slack" in name, rank by remaining terms
    """
    reg = registry or get_tool_registry()
    all_tools = reg.all_tools()

    # Parse query
    query = query.strip()

    # Direct selection: "select:Tool1,Tool2"
    if query.lower().startswith("select:"):
        names = [n.strip() for n in query[7:].split(",") if n.strip()]
        return _select_tools(names, reg)

    # Required name prefix: "+prefix keyword"
    required_prefix = None
    search_terms = query.lower().split()
    if search_terms and search_terms[0].startswith("+"):
        required_prefix = search_terms[0][1:]
        search_terms = search_terms[1:]

    # Keyword search
    results: list[ToolSearchResult] = []

    for tool_def in all_tools:
        spec = tool_def.spec
        name_lower = spec.name.lower()
        desc_lower = spec.description.lower()

        # Required prefix filter
        if required_prefix and required_prefix not in name_lower:
            continue

        # Score by keyword matches
        score = 0.0
        for term in search_terms:
            if term in name_lower:
                score += 2.0  # Name match worth more
            if term in desc_lower:
                score += 1.0

        # Also match if query is substring of name
        if query.lower() in name_lower:
            score += 3.0

        if score > 0:
            results.append(ToolSearchResult(
                name=spec.name,
                description=spec.description[:200],
                score=score,
            ))

    # Sort by score descending
    results.sort(key=lambda r: r.score, reverse=True)
    results = results[:max_results]

    return ToolSearchOutput(
        query=query,
        results=results,
        message=f"Found {len(results)} tool(s) matching '{query}'",
    )


def _select_tools(
    names: list[str], registry: GlobalToolRegistry
) -> ToolSearchOutput:
    """Fetch full schemas for specific tools by name."""
    schemas: list[dict[str, Any]] = []
    not_found: list[str] = []

    for name in names:
        tool = registry.get(name)
        if tool:
            schemas.append({
                "name": tool.spec.name,
                "description": tool.spec.description,
                "input_schema": tool.spec.input_schema,
            })
        else:
            not_found.append(name)

    msg = f"Loaded {len(schemas)} tool schema(s)"
    if not_found:
        msg += f". Not found: {', '.join(not_found)}"

    return ToolSearchOutput(
        query=f"select:{','.join(names)}",
        schemas=schemas,
        message=msg,
    )


# ---------------------------------------------------------------------------
# Tool spec for ToolSearch itself
# ---------------------------------------------------------------------------

TOOL_SEARCH_SPEC = ToolSpec(
    name="ToolSearch",
    description=(
        "Fetches full schema definitions for deferred tools so they can be called. "
        "Use 'select:Read,Edit' for exact selection, or keywords to search."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Query to find tools. Use 'select:<name>' for direct selection, "
                    "or keywords to search."
                ),
            },
            "max_results": {
                "type": "number",
                "description": "Maximum results (default 5)",
            },
        },
        "required": ["query"],
    },
    required_permission="read-only",
)
