#!/usr/bin/env python3
"""MCP tools for the Hermes Google Trends monitor."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP


ROOT = Path("/home/agent/.hermes/scripts/google-trends-monitor")
CONFIG = ROOT / "keywords.json"
MONITOR = ROOT / "google_trends_monitor.py"
DATA_DIR = Path("/home/agent/.hermes/trends")
PYTHON = "/opt/hermes/.venv/bin/python"

mcp = FastMCP("google-trends-cloak")


def _run(args: list[str], timeout: int = 180) -> str:
    proc = subprocess.run(
        [PYTHON, str(MONITOR), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "monitor failed").strip())
    return proc.stdout.strip()


@mcp.tool()
def monitor_google_trends(
    keywords: list[str] | None = None,
    geo: str = "",
    timeframe: str = "",
    use_cloak: bool = False,
) -> str:
    """Collect current Google Trends scores and return a Markdown report."""
    args: list[str] = []
    if keywords:
        args.extend(["--keywords", ",".join(keywords)])
    if geo:
        args.extend(["--geo", geo])
    if timeframe:
        args.extend(["--timeframe", timeframe])
    if use_cloak:
        args.append("--use-cloak")
    return _run(args)


@mcp.tool()
def read_google_trends_history(limit: int = 5) -> str:
    """Read recent saved Google Trends monitor runs."""
    files = sorted(DATA_DIR.glob("*.json"), reverse=True)[: max(1, min(limit, 20))]
    payload: list[dict[str, Any]] = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            payload.append(
                {
                    "file": path.name,
                    "run_at": data.get("run_at"),
                    "geo": data.get("geo"),
                    "timeframe": data.get("timeframe"),
                    "summaries": [
                        {
                            "keyword": item.get("keyword"),
                            "status": item.get("status"),
                            "latest": item.get("latest"),
                            "avg_7": item.get("avg_7"),
                            "avg_30": item.get("avg_30"),
                            "avg_7_vs_30_pct": item.get("avg_7_vs_30_pct"),
                        }
                        for item in data.get("summaries", [])
                    ],
                    "errors": data.get("errors", []),
                }
            )
        except Exception as exc:
            payload.append({"file": path.name, "error": str(exc)})
    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool()
def update_google_trends_keywords(
    keywords: list[str],
    geo: str = "US",
    timeframe: str = "now 7-d",
) -> str:
    """Replace the monitored keyword roots in keywords.json."""
    clean = [str(item).strip() for item in keywords if str(item).strip()]
    if not clean:
        raise ValueError("keywords must not be empty")
    current = {}
    if CONFIG.exists():
        current = json.loads(CONFIG.read_text(encoding="utf-8"))
    current.update({"keywords": clean, "geo": geo, "timeframe": timeframe})
    CONFIG.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return f"Updated {len(clean)} Google Trends keywords: {', '.join(clean)}"


if __name__ == "__main__":
    mcp.run()
