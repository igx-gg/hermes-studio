#!/usr/bin/env python3
"""Semrush Backlinks reporter for Hermes.

This module reuses the server-side 3UE/CloakBrowser state created by the
Semrush keyword tool, then reads the Backlink Analytics "Backlinks" table.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlencode

from semrush_keyword import DEFAULT_BASE_URL, SemrushKeywordError, md_escape, safe_name
from semrush_keyword_auto import (
    DEFAULT_STATE_DIR,
    body_text,
    launch_semrush_browser,
    new_semrush_page,
)


DEFAULT_OUTPUT_DIR = "/home/agent/.hermes/semrush-keyword/runs"


def build_backlinks_url(
    target: str,
    *,
    search_type: str = "domain",
    base_url: str | None = None,
    gmitm_token: str | None = None,
) -> str:
    target = (target or "").strip()
    if not target:
        raise SemrushKeywordError("target is required")
    base = (base_url or os.getenv("SEMRUSH_3UE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    params = {
        "q": target,
        "searchType": (search_type or "domain").strip() or "domain",
    }
    token = (gmitm_token or os.getenv("SEMRUSH_3UE_GMITM_TOKEN") or "").strip()
    if token:
        params["__gmitm"] = token
    return f"{base}/analytics/backlinks/backlinks/?{urlencode(params)}"


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def domain_from_url(value: str) -> str:
    raw = _clean(value)
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    host = (urlparse(raw).hostname or "").lower().strip(".")
    return host[4:] if host.startswith("www.") else host


def _external_links(links: list[dict[str, str]]) -> list[str]:
    hrefs: list[str] = []
    for link in links:
        href = _clean(link.get("href"))
        if not href:
            continue
        if "semrush.com/analytics/" in href:
            continue
        hrefs.append(href)
    return hrefs


def _semrush_report_link(links: list[dict[str, str]], *, text_contains: str) -> str:
    needle = text_contains.lower()
    for link in links:
        text = _clean(link.get("text"))
        href = _clean(link.get("href"))
        if "semrush.com/analytics/" not in href:
            continue
        if needle and needle not in text.lower() and needle not in href.lower():
            continue
        return href
    return ""


def parse_backlink_row(row: dict[str, Any], *, target: str) -> dict[str, Any]:
    text = _clean(row.get("text"))
    links = row.get("links") or []
    target_domain = domain_from_url(target)
    external_links = _external_links(links)
    source_url = ""
    target_url = ""
    for href in external_links:
        href_domain = domain_from_url(href)
        if href_domain == target_domain:
            target_url = target_url or href
        elif href_domain:
            source_url = source_url or href
    source_report_url = _semrush_report_link(links, text_contains="")
    target_report_url = _semrush_report_link(links, text_contains=target)

    # The row text begins with page AS, then title/source, external/internal
    # link counts, anchor/target, link metadata, and dates. Preserve raw text as
    # the fallback because Semrush localizes table labels.
    page_as = None
    match = re.match(r"^(\d+)\s+", text)
    if match:
        page_as = int(match.group(1))

    discovery_dates = re.findall(r"\d{4}年\d{1,2}月\d{1,2}日|\d+\s*(?:天|小时|分钟)前", text)
    return {
        "row_index": row.get("i"),
        "page_as": page_as,
        "source_domain": domain_from_url(source_url),
        "target_domain": domain_from_url(target_url),
        "source_url": source_url,
        "target_url": target_url,
        "source_semrush_url": source_report_url,
        "target_semrush_url": target_report_url,
        "raw_text": text,
        "discovery_dates": discovery_dates,
        "links": links,
    }


async def query_semrush_backlinks_async(
    target: str,
    *,
    search_type: str = "domain",
    base_url: str | None = None,
    gmitm_token: str | None = None,
    wait_ms: int = 20000,
    row_limit: int = 0,
    dedupe_by_domain: bool = True,
    scroll_count: int = 0,
    page_limit: int = 1,
    headless: bool = True,
    state_path: str | None = None,
    output_dir: str | None = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    url = build_backlinks_url(target, search_type=search_type, base_url=base_url, gmitm_token=gmitm_token)
    browser = await launch_semrush_browser(headless=headless, state_path=state_path or DEFAULT_STATE_DIR)
    try:
        page = await new_semrush_page(browser, state_path=state_path or DEFAULT_STATE_DIR)
        await page.goto(url, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(max(1000, wait_ms))

        text = await body_text(page, timeout_ms=20000)
        for _ in range(5):
            low = text.lower()
            if text and "loading" not in low and "加载" not in text and len(text) > 500:
                break
            await page.wait_for_timeout(4000)
            text = await body_text(page, timeout_ms=20000)

        async def collect_rows() -> list[dict[str, Any]]:
            return await page.evaluate(
                r"""() => {
                    const clean = s => (s || '').replace(/\s+/g, ' ').trim();
                    return Array.from(document.querySelectorAll('[role="row"], tr')).map((r, i) => ({
                        i,
                        text: clean(r.innerText || r.textContent),
                        links: Array.from(r.querySelectorAll('a')).map(a => ({
                            text: clean(a.innerText || a.textContent),
                            href: a.href
                        })).filter(x => x.text || x.href)
                    })).filter(x => x.text);
                }"""
            )

        async def click_next_page() -> bool:
            return bool(await page.evaluate(
                r"""() => {
                    const visible = el => {
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
                    };
                    const disabled = el => {
                        const aria = (el.getAttribute('aria-disabled') || '').toLowerCase();
                        return el.disabled || aria === 'true' || el.classList.contains('disabled');
                    };
                    const candidates = Array.from(document.querySelectorAll('button, a, [role="button"]'));
                    for (const el of candidates) {
                        if (!visible(el) || disabled(el)) continue;
                        const label = [
                            el.innerText,
                            el.textContent,
                            el.getAttribute('aria-label'),
                            el.getAttribute('title'),
                            el.getAttribute('data-testid'),
                            el.getAttribute('class')
                        ].filter(Boolean).join(' ').replace(/\s+/g, ' ').trim().toLowerCase();
                        if (/(next|下一页|下页|后一页|›|»|>)/i.test(label)) {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }"""
            ))

        rows_by_key: dict[str, dict[str, Any]] = {}
        pages_collected = 0
        max_pages = int(page_limit or 0)
        while True:
            pages_collected += 1
            for idx in range(max(1, int(scroll_count) + 1)):
                for row in await collect_rows():
                    key = f"{row.get('text', '')}|{json.dumps(row.get('links') or [], sort_keys=True, ensure_ascii=False)}"
                    rows_by_key.setdefault(key, row)
                if idx < int(scroll_count):
                    await page.mouse.wheel(0, 2500)
                    await page.wait_for_timeout(1500)
            if max_pages > 0 and pages_collected >= max_pages:
                break
            if not await click_next_page():
                break
            await page.wait_for_timeout(3500)
        rows = list(rows_by_key.values())

        data_rows = [
            row for row in rows
            if row.get("links") and not str(row.get("text", "")).startswith("页面 AS ")
        ]
        parsed_backlinks = [
            item for item in (parse_backlink_row(row, target=target) for row in data_rows)
            if item.get("source_domain") and item.get("target_domain") and item.get("source_domain") != item.get("target_domain")
        ]
        backlinks: list[dict[str, Any]] = []
        seen_domains: set[str] = set()
        limit = int(row_limit or 0)
        for item in parsed_backlinks:
            source_domain = str(item.get("source_domain") or "")
            if dedupe_by_domain:
                if source_domain in seen_domains:
                    continue
                seen_domains.add(source_domain)
            backlinks.append(item)
            if limit > 0 and len(backlinks) >= limit:
                break
        result = {
            "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "target": target,
            "search_type": search_type,
            "dedupe_by_domain": bool(dedupe_by_domain),
            "row_limit": row_limit,
            "scroll_count": scroll_count,
            "page_limit": page_limit,
            "pages_collected": pages_collected,
            "raw_row_count": len(rows),
            "parsed_backlink_count": len(parsed_backlinks),
            "returned_backlink_count": len(backlinks),
            "unique_source_domain_count": len({str(item.get("source_domain") or "") for item in parsed_backlinks if item.get("source_domain")}),
            "query_url": url,
            "semrush_url": page.url or url,
            "page_title": await page.title(),
            "total_text_excerpt": text[:5000],
            "first_backlink": backlinks[0] if backlinks else None,
            "backlinks": backlinks,
        }
    finally:
        await browser.close()

    if output_dir:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{safe_name(target)}-backlinks-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["output_path"] = str(out_path)
    return result


def query_semrush_backlinks(**kwargs: Any) -> dict[str, Any]:
    return asyncio.run(query_semrush_backlinks_async(**kwargs))


def format_backlinks_markdown(result: dict[str, Any]) -> str:
    first = result.get("first_backlink") or {}
    lines = [
        "# Semrush Backlinks",
        "",
        f"- Target: `{result.get('target')}`",
        f"- Search type: `{result.get('search_type')}`",
        f"- Dedupe by domain: `{result.get('dedupe_by_domain')}`",
        f"- Pages collected: `{result.get('pages_collected')}`",
        f"- Returned backlinks: `{result.get('returned_backlink_count')}`",
        f"- Unique source domains found: `{result.get('unique_source_domain_count')}`",
        f"- Semrush URL: {result.get('semrush_url') or result.get('source_url')}",
    ]
    if result.get("output_path"):
        lines.append(f"- JSON output: `{result['output_path']}`")
    lines.extend(["", "## First backlink", ""])
    if not first:
        lines.append("No backlink rows were found.")
        return "\n".join(lines)
    lines.append(f"- Source page: {first.get('source_url') or '-'}")
    lines.append(f"- Target URL: {first.get('target_url') or '-'}")
    lines.append(f"- Page AS: `{first.get('page_as') if first.get('page_as') is not None else '-'}`")
    dates = first.get("discovery_dates") or []
    if dates:
        lines.append(f"- Dates: `{', '.join(dates[:4])}`")
    lines.extend(["", "## Raw first row", "", first.get("raw_text") or "-"])

    rows = result.get("backlinks") or []
    if len(rows) > 1:
        lines.extend(["", "## Top rows", "", "| # | Source page | Target URL | AS |", "|---:|---|---|---:|"])
        for idx, row in enumerate(rows[:10], 1):
            lines.append(
                f"| {idx} | {md_escape(row.get('source_url'))} | {md_escape(row.get('target_url'))} | {md_escape(row.get('page_as'))} |"
            )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query Semrush Backlinks through the 3UE relay.")
    parser.add_argument("target", help="Domain or URL to query.")
    parser.add_argument("--search-type", default="domain", help="domain, root_domain, url, etc. Default: domain.")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--gmitm-token", default=None)
    parser.add_argument("--wait-ms", type=int, default=20000)
    parser.add_argument("--row-limit", type=int, default=0, help="Maximum deduped backlink rows to return. Use 0 for no row limit within collected pages.")
    parser.add_argument("--no-dedupe-by-domain", action="store_true", help="Return multiple backlinks from the same source domain.")
    parser.add_argument("--scroll-count", type=int, default=0, help="Scroll the result table before parsing more loaded rows.")
    parser.add_argument("--page-limit", type=int, default=1, help="Maximum Semrush result pages to collect. Use 0 to keep going until no next page is found.")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = query_semrush_backlinks(
        target=args.target,
        search_type=args.search_type,
        base_url=args.base_url,
        gmitm_token=args.gmitm_token,
        wait_ms=args.wait_ms,
        row_limit=args.row_limit,
        dedupe_by_domain=not args.no_dedupe_by_domain,
        scroll_count=args.scroll_count,
        page_limit=args.page_limit,
        headless=not args.headed,
        output_dir=args.output_dir or None,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_backlinks_markdown(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
