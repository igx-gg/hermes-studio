#!/usr/bin/env python3
"""Semrush Keyword Overview reporter for Hermes.

The tool opens Semrush through the 3UE relay and parses the rendered Keyword
Overview page. Provide the 3UE relay token at runtime with
SEMRUSH_3UE_GMITM_TOKEN, --gmitm-token, SEMRUSH_3UE_URL, or --proxy-url.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse


DEFAULT_BASE_URL = "https://sem.3ue.co"
DEFAULT_OUTPUT_DIR = "/home/agent/.hermes/semrush-keyword/runs"

DEVICE_CODES = {
    "desktop": "0",
    "0": "0",
    "mobile": "1",
    "1": "1",
}

KEYWORD_OVERVIEW_READY_MARKERS = (
    "关键词摘要",
    "Keyword Overview",
    "关键词难度",
)
PAGE_LOADING_MARKERS = (
    "Loading",
    "加载",
)


class SemrushKeywordError(RuntimeError):
    pass


def keyword_overview_ready(text: str) -> bool:
    return any(marker in text for marker in KEYWORD_OVERVIEW_READY_MARKERS) and not any(
        marker in text for marker in PAGE_LOADING_MARKERS
    )


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "semrush-keyword"


def clean_lines(text: str) -> list[str]:
    return [line.strip().strip('"') for line in text.splitlines() if line.strip()]


def resolve_relay(
    *,
    proxy_url: str | None = None,
    base_url: str | None = None,
    gmitm_token: str | None = None,
) -> tuple[str, str | None]:
    """Resolve the relay base URL and gmitm token from args or environment."""

    raw_proxy_url = proxy_url or os.getenv("SEMRUSH_3UE_URL") or ""
    raw_base = base_url or os.getenv("SEMRUSH_3UE_BASE_URL") or DEFAULT_BASE_URL
    raw_token = (
        gmitm_token
        or os.getenv("SEMRUSH_3UE_GMITM_TOKEN")
        or os.getenv("SEMRUSH_3UE_TOKEN")
        or None
    )

    if raw_proxy_url:
        parsed = urlparse(raw_proxy_url)
        if parsed.scheme and parsed.netloc:
            raw_base = f"{parsed.scheme}://{parsed.netloc}"
            query = parse_qs(parsed.query)
            raw_token = raw_token or (query.get("__gmitm") or [None])[0]

    parsed_base = urlparse(raw_base if "://" in raw_base else f"https://{raw_base}")
    if not parsed_base.netloc:
        raise SemrushKeywordError(f"Invalid Semrush relay base URL: {raw_base!r}")
    return f"{parsed_base.scheme}://{parsed_base.netloc}", raw_token


def build_keyword_url(
    keyword: str,
    *,
    database: str = "us",
    device: str = "desktop",
    date: str | None = None,
    proxy_url: str | None = None,
    base_url: str | None = None,
    gmitm_token: str | None = None,
) -> str:
    keyword = (keyword or "").strip()
    if not keyword:
        raise SemrushKeywordError("keyword is required")

    base, token = resolve_relay(proxy_url=proxy_url, base_url=base_url, gmitm_token=gmitm_token)
    device_code = DEVICE_CODES.get(str(device).strip().lower())
    if device_code is None:
        raise SemrushKeywordError("device must be desktop, mobile, 0, or 1")

    params: dict[str, str] = {
        "q": keyword,
        "db": (database or "us").strip().lower(),
    }
    if date:
        params["date"] = str(date).strip()
    if device_code != "0":
        params["device"] = device_code
    if token:
        params["__gmitm"] = token
    return f"{base}/analytics/keywordoverview/?{urlencode(params)}"


async def fetch_rendered_text(
    url: str,
    *,
    wait_ms: int = 15000,
    timeout_ms: int = 90000,
    headless: bool = True,
) -> dict[str, str]:
    """Open a Semrush URL with CloakBrowser and return rendered page text."""

    from cloakbrowser import launch_async

    browser = await launch_async(headless=headless, humanize=True)
    try:
        page = await browser.new_page(viewport={"width": 1440, "height": 1400})
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        await page.wait_for_timeout(max(1000, wait_ms))

        text = await page.locator("body").inner_text(timeout=20000)
        for _ in range(4):
            if keyword_overview_ready(text):
                break
            await page.wait_for_timeout(3000)
            text = await page.locator("body").inner_text(timeout=20000)

        return {
            "title": await page.title(),
            "url": page.url,
            "text": text,
        }
    finally:
        await browser.close()


def index_of(lines: list[str], value: str, start: int = 0) -> int:
    try:
        return lines.index(value, start)
    except ValueError:
        return -1


def find_next(lines: list[str], label: str, start: int = 0, end: int | None = None) -> str | None:
    end = len(lines) if end is None else end
    for idx in range(start, end):
        if lines[idx] == label:
            for value in lines[idx + 1 : end]:
                if value:
                    return value
    return None


def slice_between(lines: list[str], start_label: str, end_labels: list[str]) -> tuple[int, int]:
    start = index_of(lines, start_label)
    if start < 0:
        return -1, -1
    end = len(lines)
    for label in end_labels:
        idx = index_of(lines, label, start + 1)
        if idx >= 0:
            end = min(end, idx)
    return start, end


def parse_count_display(value: str | None) -> int | None:
    if not value:
        return None
    text = value.replace(",", "").strip()
    match = re.search(r"([\d.]+)\s*([KMB])?", text, flags=re.I)
    if not match:
        return None
    number = float(match.group(1))
    suffix = (match.group(2) or "").upper()
    multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(suffix, 1)
    return int(number * multiplier)


def parse_country_volumes(summary_lines: list[str]) -> list[dict[str, str]]:
    countries: list[dict[str, str]] = []
    global_idx = index_of(summary_lines, "全球搜索量")
    intent_idx = index_of(summary_lines, "意图")
    if global_idx < 0 or intent_idx < 0:
        return countries

    idx = global_idx + 2
    while idx < intent_idx:
        code = ""
        country = summary_lines[idx]
        volume = summary_lines[idx + 1] if idx + 1 < intent_idx else ""
        if re.fullmatch(r"[A-Z]{2}", country) and idx + 2 < intent_idx:
            code = country.lower()
            country = summary_lines[idx + 1]
            volume = summary_lines[idx + 2]
            idx += 3
        else:
            idx += 2
        if country and volume:
            countries.append(
                {
                    "country_code": code,
                    "country": country,
                    "volume": volume,
                    "volume_number": parse_count_display(volume),
                }
            )
    return countries


SECTION_TITLES = {"关键词变化", "问题", "关键词策略", "SERP 分析", "广告创意"}
TABLE_HEADERS = {"关键词", "搜索量", "KD (%)"}
UNAVAILABLE_VALUES = {"不可用", "N/A", "n/a", "-"}


def parse_keyword_section_stats(section_lines: list[str]) -> dict[str, str | None]:
    """Parse the aggregate counts above a keyword ideas table.

    Semrush omits these numbers for some sparse sections. In that case the
    table header appears immediately after the section title, so blindly taking
    section_lines[1] returns "关键词" instead of a real count.
    """

    total_keywords = None
    total_volume = find_next(section_lines, "总搜索量:")
    total_idx = index_of(section_lines, "总搜索量:")
    if total_idx > 1:
        candidate = section_lines[1]
        if candidate not in TABLE_HEADERS and candidate not in SECTION_TITLES and not candidate.startswith("查看全部"):
            total_keywords = candidate

    if total_keywords is None:
        for line in section_lines:
            match = re.search(r"查看全部\s+([\d,.]+)\s+个关键词", line)
            if match:
                total_keywords = match.group(1)
                break

    return {"total_keywords": total_keywords, "total_volume": total_volume}


def parse_keyword_rows(section_lines: list[str], *, limit: int = 20) -> list[dict[str, Any]]:
    header_idx = -1
    for idx in range(len(section_lines) - 2):
        if section_lines[idx : idx + 3] == ["关键词", "搜索量", "KD (%)"]:
            header_idx = idx + 3
            break
    if header_idx < 0:
        return []

    rows: list[dict[str, Any]] = []
    idx = header_idx
    while idx + 2 < len(section_lines) and len(rows) < limit:
        keyword, volume, kd = section_lines[idx : idx + 3]
        if keyword.startswith("查看全部") or keyword in SECTION_TITLES:
            break
        if kd.startswith("查看全部") or kd in SECTION_TITLES:
            break
        kd_value = int(kd) if re.fullmatch(r"\d+", kd) else None
        if kd_value is None and kd not in UNAVAILABLE_VALUES:
            break
        rows.append(
            {
                "keyword": keyword,
                "volume": volume,
                "volume_number": parse_count_display(volume),
                "keyword_difficulty": kd_value,
                "keyword_difficulty_display": kd,
            }
        )
        idx += 3
    return rows


def parse_keyword_ideas(lines: list[str], *, list_limit: int = 10) -> dict[str, Any]:
    start, end = slice_between(lines, "关键词意见", ["SERP 分析", "广告创意"])
    if start < 0:
        return {}
    section = lines[start:end]

    changes_idx = index_of(section, "关键词变化")
    questions_idx = index_of(section, "问题")
    strategy_idx = index_of(section, "关键词策略")

    def subsection(first: int, fallback_end: int) -> list[str]:
        return section[first:fallback_end] if first >= 0 else []

    changes_end = min([idx for idx in [questions_idx, strategy_idx, len(section)] if idx >= 0])
    questions_end = min([idx for idx in [strategy_idx, len(section)] if idx >= 0])

    changes_lines = subsection(changes_idx, changes_end)
    question_lines = subsection(questions_idx, questions_end)

    changes = {
        **parse_keyword_section_stats(changes_lines),
        "rows": parse_keyword_rows(changes_lines, limit=list_limit),
    }
    questions = {
        **parse_keyword_section_stats(question_lines),
        "rows": parse_keyword_rows(question_lines, limit=list_limit),
    }

    clusters: list[dict[str, str]] = []
    if strategy_idx >= 0:
        cursor = strategy_idx + 1
        while cursor < len(section):
            item = section[cursor]
            if item in {"自动获取主题、支柱和子页面", "查看所有群集"}:
                cursor += 1
                continue
            if item.startswith("意图:"):
                cursor += 1
                continue
            intent = ""
            if cursor + 1 < len(section) and section[cursor + 1].startswith("意图:"):
                intent = section[cursor + 1].replace("意图:", "", 1).strip()
                cursor += 2
            else:
                cursor += 1
            clusters.append({"keyword": item, "intent": intent})
            if len(clusters) >= list_limit:
                break

    return {
        "variations": changes,
        "questions": questions,
        "clusters": clusters,
    }


def parse_summary(lines: list[str]) -> dict[str, Any]:
    start, end = slice_between(lines, "关键词摘要", ["关键词意见", "SERP 分析", "广告创意"])
    if start < 0:
        raise SemrushKeywordError("Semrush keyword summary was not found in the rendered page.")
    summary_lines = lines[start:end]

    kd = find_next(summary_lines, "关键词难度")
    kd_idx = index_of(summary_lines, "关键词难度")
    kd_label = None
    kd_note = None
    if kd_idx >= 0:
        if kd_idx + 2 < len(summary_lines):
            kd_label = summary_lines[kd_idx + 2]
        if kd_idx + 3 < len(summary_lines) and summary_lines[kd_idx + 3] != "全球搜索量":
            kd_note = summary_lines[kd_idx + 3]

    return {
        "volume": find_next(summary_lines, "搜索量"),
        "volume_number": parse_count_display(find_next(summary_lines, "搜索量")),
        "keyword_difficulty": kd,
        "keyword_difficulty_number": int(kd.rstrip("%")) if kd and kd.rstrip("%").isdigit() else None,
        "keyword_difficulty_label": kd_label,
        "keyword_difficulty_note": kd_note,
        "global_volume": find_next(summary_lines, "全球搜索量"),
        "global_volume_number": parse_count_display(find_next(summary_lines, "全球搜索量")),
        "country_volumes": parse_country_volumes(summary_lines),
        "intent": find_next(summary_lines, "意图"),
        "cpc": find_next(summary_lines, "CPC"),
        "competition": find_next(summary_lines, "竞争激烈程度"),
        "google_shopping_ads": find_next(summary_lines, "谷歌购物广告"),
        "ads": find_next(summary_lines, "广告"),
    }


def parse_data_date(lines: list[str]) -> str | None:
    for line in lines:
        match = re.search(r"(\d{4}年\d{1,2}月\d{1,2}日)", line)
        if match:
            return match.group(1)
    return None


def parse_keyword_overview(
    text: str,
    *,
    keyword: str,
    database: str,
    device: str,
    source_url: str,
    page_title: str = "",
    list_limit: int = 10,
) -> dict[str, Any]:
    if not text.strip():
        raise SemrushKeywordError("Semrush rendered page text is empty.")
    if "关键词摘要" not in text and re.search(r"登录|Sign in|Log in", text, flags=re.I):
        raise SemrushKeywordError("Semrush relay appears to require login before keyword data can be read.")

    lines = clean_lines(text)
    summary = parse_summary(lines)
    ideas = parse_keyword_ideas(lines, list_limit=list_limit)

    return {
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "keyword": keyword,
        "database": database,
        "device": "mobile" if DEVICE_CODES.get(str(device).lower(), "0") == "1" else "desktop",
        "data_date": parse_data_date(lines),
        "source_url": source_url,
        "page_title": page_title,
        "summary": summary,
        "keyword_ideas": ideas,
        "raw_text_excerpt": text[:5000],
    }


def query_semrush_keyword(
    keyword: str,
    *,
    database: str = "us",
    device: str = "desktop",
    date: str | None = None,
    proxy_url: str | None = None,
    base_url: str | None = None,
    gmitm_token: str | None = None,
    wait_ms: int = 15000,
    output_dir: str | None = DEFAULT_OUTPUT_DIR,
    list_limit: int = 10,
    headless: bool = True,
) -> dict[str, Any]:
    url = build_keyword_url(
        keyword,
        database=database,
        device=device,
        date=date,
        proxy_url=proxy_url,
        base_url=base_url,
        gmitm_token=gmitm_token,
    )
    page = asyncio.run(fetch_rendered_text(url, wait_ms=wait_ms, headless=headless))
    result = parse_keyword_overview(
        page["text"],
        keyword=keyword,
        database=database,
        device=device,
        source_url=page["url"] or url,
        page_title=page["title"],
        list_limit=list_limit,
    )

    if output_dir:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{safe_name(keyword)}-{database}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["output_path"] = str(out_path)
    return result


def md_escape(value: Any) -> str:
    return str(value if value is not None else "-").replace("|", "\\|")


def format_markdown(result: dict[str, Any], *, list_limit: int = 10) -> str:
    summary = result.get("summary") or {}
    ideas = result.get("keyword_ideas") or {}

    lines: list[str] = []
    lines.append("# Semrush Keyword Overview")
    lines.append("")
    lines.append(f"- Keyword: `{result.get('keyword')}`")
    lines.append(f"- Database: `{result.get('database')}`")
    lines.append(f"- Device: `{result.get('device')}`")
    if result.get("data_date"):
        lines.append(f"- Data date: `{result['data_date']}`")
    lines.append(f"- Source: {result.get('source_url')}")
    lines.append(f"- Search volume: `{summary.get('volume') or '-'}`")
    lines.append(
        f"- Keyword difficulty: `{summary.get('keyword_difficulty') or '-'}`"
        f" ({summary.get('keyword_difficulty_label') or '-'})"
    )
    lines.append(f"- Global volume: `{summary.get('global_volume') or '-'}`")
    lines.append(f"- Intent: `{summary.get('intent') or '-'}`")
    lines.append(f"- CPC: `{summary.get('cpc') or '-'}`")
    lines.append(f"- Competition: `{summary.get('competition') or '-'}`")
    if result.get("output_path"):
        lines.append(f"- JSON output: `{result['output_path']}`")

    countries = summary.get("country_volumes") or []
    if countries:
        lines.append("")
        lines.append("## Country volumes")
        lines.append("")
        lines.append("| Country | Code | Volume |")
        lines.append("|---|---|---:|")
        for item in countries[:list_limit]:
            lines.append(
                f"| {md_escape(item.get('country'))} | {md_escape(item.get('country_code') or '-')} | {md_escape(item.get('volume'))} |"
            )

    variations = ideas.get("variations") or {}
    rows = variations.get("rows") or []
    lines.append("")
    lines.append("## Keyword variations")
    lines.append("")
    lines.append(f"- Total keywords: `{variations.get('total_keywords') or '-'}`")
    lines.append(f"- Total volume: `{variations.get('total_volume') or '-'}`")
    if rows:
        lines.append("")
        lines.append("| Keyword | Volume | KD |")
        lines.append("|---|---:|---:|")
        for row in rows[:list_limit]:
            kd = row.get("keyword_difficulty_display")
            if kd is None:
                kd = row.get("keyword_difficulty")
            lines.append(
                f"| {md_escape(row.get('keyword'))} | {md_escape(row.get('volume'))} | {md_escape(kd)} |"
            )

    questions = ideas.get("questions") or {}
    q_rows = questions.get("rows") or []
    lines.append("")
    lines.append("## Questions")
    lines.append("")
    lines.append(f"- Total keywords: `{questions.get('total_keywords') or '-'}`")
    lines.append(f"- Total volume: `{questions.get('total_volume') or '-'}`")
    if q_rows:
        lines.append("")
        lines.append("| Keyword | Volume | KD |")
        lines.append("|---|---:|---:|")
        for row in q_rows[:list_limit]:
            kd = row.get("keyword_difficulty_display")
            if kd is None:
                kd = row.get("keyword_difficulty")
            lines.append(
                f"| {md_escape(row.get('keyword'))} | {md_escape(row.get('volume'))} | {md_escape(kd)} |"
            )

    clusters = ideas.get("clusters") or []
    if clusters:
        lines.append("")
        lines.append("## Keyword strategy clusters")
        lines.append("")
        lines.append("| Cluster | Intent |")
        lines.append("|---|---|")
        for cluster in clusters[:list_limit]:
            lines.append(f"| {md_escape(cluster.get('keyword'))} | {md_escape(cluster.get('intent') or '-')} |")

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query Semrush Keyword Overview through the 3UE relay.")
    parser.add_argument("keyword", help="Keyword to query.")
    parser.add_argument("--database", "--db", default="us", help="Semrush database, default: us.")
    parser.add_argument("--device", default="desktop", choices=["desktop", "mobile", "0", "1"], help="Device database.")
    parser.add_argument("--date", default=None, help="Optional Semrush date in YYYYMM format.")
    parser.add_argument("--proxy-url", default=None, help="Current 3UE/Semrush relay URL; token is extracted from __gmitm.")
    parser.add_argument("--base-url", default=None, help="Relay base URL, default SEMRUSH_3UE_BASE_URL or https://sem.3ue.co.")
    parser.add_argument("--gmitm-token", default=None, help="3UE relay __gmitm token. Prefer env SEMRUSH_3UE_GMITM_TOKEN.")
    parser.add_argument("--wait-ms", type=int, default=15000, help="Wait after page load before parsing.")
    parser.add_argument("--list-limit", type=int, default=10, help="Rows to include in Markdown tables.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown.")
    parser.add_argument("--headed", action="store_true", help="Show the browser window when CloakBrowser supports it.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Directory for JSON output. Empty disables saving.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = query_semrush_keyword(
            args.keyword,
            database=args.database,
            device=args.device,
            date=args.date,
            proxy_url=args.proxy_url,
            base_url=args.base_url,
            gmitm_token=args.gmitm_token,
            wait_ms=args.wait_ms,
            output_dir=args.output_dir or None,
            list_limit=args.list_limit,
            headless=not args.headed,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_markdown(result, list_limit=args.list_limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
