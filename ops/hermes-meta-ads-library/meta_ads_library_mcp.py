#!/usr/bin/env python3
"""Hermes MCP tools for Meta Ads Library queries."""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from meta_ads_library import format_markdown, query_meta_ads_library


mcp = FastMCP("meta-ads-library")


@mcp.tool()
def query_meta_ads_library_tool(
    target: str,
    country: str = "ALL",
    active_status: str = "active",
    search_type: str = "keyword_exact_phrase",
    media_type: str = "all",
    scrolls: int = 5,
    list_limit: int = 50,
    output_format: str = "markdown",
) -> str:
    """Query Meta Ads Library for a domain, keyword, or Ads Library URL."""

    result = query_meta_ads_library(
        target,
        country=country,
        active_status=active_status,
        search_type=search_type,
        media_type=media_type,
        scrolls=scrolls,
        output_dir="/home/agent/.hermes/meta-ads-library/runs",
    )
    if output_format.lower() == "json":
        return json.dumps(result, ensure_ascii=False, indent=2)
    return format_markdown(result, list_limit=list_limit)


@mcp.tool()
def read_meta_ads_library_run(path: str) -> str:
    """Read a saved Meta Ads Library JSON run from disk."""

    file_path = Path(path)
    if not file_path.exists():
        return f"File not found: {path}"
    return file_path.read_text(encoding="utf-8")


if __name__ == "__main__":
    mcp.run()
