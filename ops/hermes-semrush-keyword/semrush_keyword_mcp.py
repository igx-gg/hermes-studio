#!/usr/bin/env python3
"""Hermes MCP tools for Semrush Keyword Overview queries."""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from semrush_backlinks import format_backlinks_markdown, query_semrush_backlinks_async
from semrush_keyword import format_markdown
from semrush_keyword_auto import format_login_result, prepare_3ue_login, query_semrush_keyword_async


mcp = FastMCP("semrush-keyword")


@mcp.tool()
async def prepare_semrush_3ue_login_tool(
    wait_seconds: int = 300,
    headless: bool = False,
) -> str:
    """Open 3UE in the Hermes server-side CloakBrowser and save login state.

    Use this once when the server-side browser is not logged in. Complete the
    3UE login in the opened server-side browser before wait_seconds expires.
    """

    result = await prepare_3ue_login(wait_seconds=wait_seconds, headless=headless)
    return format_login_result(result)


@mcp.tool()
async def query_semrush_keyword_tool(
    keyword: str,
    database: str = "us",
    device: str = "desktop",
    proxy_url: str = "",
    gmitm_token: str = "",
    date: str = "",
    wait_ms: int = 15000,
    list_limit: int = 10,
    output_format: str = "markdown",
    auto_login: bool = True,
    interactive_login_wait_seconds: int = 0,
    headless: bool = True,
) -> str:
    """Query Semrush Keyword Overview through the 3UE relay.

    By default this opens 3UE from the Hermes server-side CloakBrowser, reuses
    the saved server-side login state, clicks the SEO Tools open button, and
    queries Semrush in that same server browser context.
    """

    result = await query_semrush_keyword_async(
        keyword,
        database=database,
        device=device,
        date=date or None,
        proxy_url=proxy_url or None,
        gmitm_token=gmitm_token or None,
        wait_ms=wait_ms,
        output_dir="/home/agent/.hermes/semrush-keyword/runs",
        list_limit=list_limit,
        auto_login=auto_login,
        interactive_login_wait_seconds=interactive_login_wait_seconds,
        headless=headless,
    )
    if output_format.lower() == "json":
        import json

        return json.dumps(result, ensure_ascii=False, indent=2)
    return format_markdown(result, list_limit=list_limit)


@mcp.tool()
def read_semrush_keyword_run(path: str) -> str:
    """Read a saved Semrush Keyword Overview JSON run from disk."""

    file_path = Path(path)
    if not file_path.exists():
        return f"File not found: {path}"
    return file_path.read_text(encoding="utf-8")


@mcp.tool()
async def query_semrush_backlinks_tool(
    target: str,
    search_type: str = "domain",
    wait_ms: int = 20000,
    row_limit: int = 0,
    dedupe_by_domain: bool = True,
    scroll_count: int = 0,
    page_limit: int = 1,
    output_format: str = "markdown",
    headless: bool = True,
) -> str:
    """Query Semrush Backlink Analytics and return backlink rows.

    Use this when the user needs the actual backlink/source page URLs rather
    than referring domains. For a domain query, this opens
    /analytics/backlinks/backlinks/ and parses the first visible backlink row.
    """

    result = await query_semrush_backlinks_async(
        target=target,
        search_type=search_type,
        wait_ms=wait_ms,
        row_limit=row_limit,
        dedupe_by_domain=dedupe_by_domain,
        scroll_count=scroll_count,
        page_limit=page_limit,
        output_dir="/home/agent/.hermes/semrush-keyword/runs",
        headless=headless,
    )
    if output_format.lower() == "json":
        import json

        return json.dumps(result, ensure_ascii=False, indent=2)
    return format_backlinks_markdown(result)


if __name__ == "__main__":
    mcp.run()
