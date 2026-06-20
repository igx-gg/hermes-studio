#!/usr/bin/env python3
"""Hermes MCP tools for Google Ads Transparency Center reporting."""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from google_ads_transparency import format_markdown, query_ads_transparency


mcp = FastMCP("google-ads-transparency")


@mcp.tool()
def query_google_ads_transparency(
    target: str,
    region: str = "anywhere",
    max_ads: int = 200,
    list_limit: int = 80,
    output_format: str = "markdown",
    cloak_check: bool = False,
) -> str:
    """Query Google Ads Transparency Center for a domain or advertiser URL.

    Returns advertiser account count, estimated ad count, observed ad group IDs,
    product domains, and a creative list grouped by advertiser.
    """

    result = query_ads_transparency(
        target,
        region=region,
        max_ads=max_ads,
        cloak_check=cloak_check,
        output_dir="/home/agent/.hermes/ads-transparency/runs",
    )
    if output_format.lower() == "json":
        return json.dumps(result, ensure_ascii=False, indent=2)
    return format_markdown(result, list_limit=list_limit)


@mcp.tool()
def read_ads_transparency_run(path: str) -> str:
    """Read a saved Ads Transparency JSON run from disk."""

    file_path = Path(path)
    if not file_path.exists():
        return f"File not found: {path}"
    return file_path.read_text(encoding="utf-8")


if __name__ == "__main__":
    mcp.run()
