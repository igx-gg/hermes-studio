#!/usr/bin/env python3
"""Meta Ads Library reporter powered by CloakBrowser.

This uses the public Meta Ads Library page and parses rendered ad cards. Meta's
public library exposes Library IDs and page/advertiser names, but it does not
expose internal campaign/ad set/ad group IDs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse


DEFAULT_OUTPUT_DIR = "/home/agent/.hermes/meta-ads-library/runs"
META_ADS_LIBRARY_BASE = "https://www.facebook.com/ads/library/"


class MetaAdsLibraryError(RuntimeError):
    pass


def normalize_query(target: str) -> dict[str, Any]:
    raw = (target or "").strip()
    if not raw:
        raise MetaAdsLibraryError("Target URL/domain/keyword is required.")

    if "facebook.com/ads/library" in raw:
        parsed = urlparse(raw)
        query = parse_qs(parsed.query)
        q = (query.get("q") or [""])[0]
        return {
            "source": raw,
            "query": q.strip(),
            "country": (query.get("country") or ["ALL"])[0],
            "active_status": (query.get("active_status") or ["active"])[0],
            "ad_type": (query.get("ad_type") or ["all"])[0],
            "media_type": (query.get("media_type") or ["all"])[0],
            "search_type": (query.get("search_type") or ["keyword_exact_phrase"])[0],
        }

    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.netloc or "").lower()
    if host:
        if host.startswith("www."):
            host = host[4:]
        return {
            "source": raw,
            "query": host,
            "country": "ALL",
            "active_status": "active",
            "ad_type": "all",
            "media_type": "all",
            "search_type": "keyword_exact_phrase",
        }

    return {
        "source": raw,
        "query": raw,
        "country": "ALL",
        "active_status": "active",
        "ad_type": "all",
        "media_type": "all",
        "search_type": "keyword_exact_phrase",
    }


def build_library_url(
    *,
    query: str,
    country: str = "ALL",
    active_status: str = "active",
    ad_type: str = "all",
    media_type: str = "all",
    search_type: str = "keyword_exact_phrase",
) -> str:
    params = {
        "active_status": active_status,
        "ad_type": ad_type,
        "country": country,
        "is_targeted_country": "false",
        "media_type": media_type,
        "q": query,
        "search_type": search_type,
        "sort_data[direction]": "desc",
        "sort_data[mode]": "total_impressions",
    }
    return META_ADS_LIBRARY_BASE + "?" + urlencode(params)


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "meta-ads"


def extract_result_count(text: str) -> str:
    match = re.search(r"(?m)^([>~]?\s?[\d,]+(?:\+|K|M)? results)$", text)
    if match:
        return match.group(1).strip()
    if "No ads match your search criteria" in text:
        return "0"
    return "unknown"


def find_domains(lines: list[str]) -> list[str]:
    domains: list[str] = []
    for line in lines:
        value = line.strip()
        if len(value) > 120:
            continue
        if not re.search(r"\.[A-Za-z]{2,}", value):
            continue
        if " " in value and not value.startswith(("http://", "https://")):
            continue
        cleaned = value
        cleaned = re.sub(r"^https?://", "", cleaned, flags=re.I)
        cleaned = cleaned.split("/")[0].strip()
        cleaned = cleaned.strip(".,;:()[]{}")
        if "." in cleaned:
            domains.append(cleaned.lower())
    seen: set[str] = set()
    out: list[str] = []
    for domain in domains:
        if domain not in seen:
            out.append(domain)
            seen.add(domain)
    return out


def parse_ad_block(status: str, block: str) -> dict[str, Any] | None:
    lines = [line.strip() for line in block.splitlines() if line.strip() and line.strip() != "\u200b"]
    if not lines:
        return None
    library_id = lines[0].strip()
    if not re.match(r"^\d{6,}$", library_id):
        return None

    started = None
    for line in lines:
        if line.startswith("Started running on "):
            started = line.replace("Started running on ", "", 1).strip()
            break

    detail_index = None
    detail_label = ""
    for i, line in enumerate(lines):
        if line in {"See ad details", "See summary details"}:
            detail_index = i
            detail_label = line
            break

    page_name = ""
    if detail_index is not None and detail_index + 1 < len(lines):
        page_name = lines[detail_index + 1]

    sponsored_index = None
    for i, line in enumerate(lines):
        if line == "Sponsored":
            sponsored_index = i
            break
    if not page_name and sponsored_index is not None and sponsored_index > 0:
        page_name = lines[sponsored_index - 1]

    content_start = sponsored_index + 1 if sponsored_index is not None else (detail_index + 2 if detail_index is not None else 0)
    content_lines = lines[content_start:]
    domains = find_domains(content_lines)

    cta_values = {
        "Apply now",
        "Book Now",
        "Chat With Us",
        "Contact us",
        "Download",
        "Get offer",
        "Install now",
        "Learn More",
        "Listen Now",
        "Order Now",
        "Play Game",
        "Request Time",
        "See Menu",
        "Send message",
        "Shop Now",
        "Sign Up",
        "Subscribe",
        "Use App",
        "Watch More",
    }
    cta = next((line for line in reversed(content_lines) if line in cta_values), "")

    version_note = ""
    for line in lines:
        if "ads use this creative and text" in line or "This ad has multiple versions" in line:
            version_note = line
            break

    text_parts = []
    for line in content_lines:
        if line in cta_values or re.match(r"^\d+:\d+ / \d+:\d+", line):
            continue
        if re.search(r"^[A-Z0-9.-]+\.[A-Z]{2,}$", line):
            continue
        text_parts.append(line)
    ad_text = "\n".join(text_parts).strip()

    return {
        "library_id": library_id,
        "status": status,
        "started_running": started,
        "page_name": page_name,
        "detail_type": detail_label,
        "destination_domains": domains,
        "cta": cta,
        "version_note": version_note,
        "text_excerpt": ad_text[:1200],
        "raw_lines": lines[:120],
        "details_url": f"https://www.facebook.com/ads/library/?id={library_id}",
    }


def parse_ads_from_text(text: str) -> list[dict[str, Any]]:
    ads: list[dict[str, Any]] = []
    pattern = re.compile(r"(?m)^(Active|Inactive)\nLibrary ID: ")
    matches = list(pattern.finditer(text))
    for idx, match in enumerate(matches):
        status = match.group(1)
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        block = text[start:end]
        ad = parse_ad_block(status, block)
        if ad:
            ads.append(ad)

    seen: set[str] = set()
    unique_ads: list[dict[str, Any]] = []
    for ad in ads:
        if ad["library_id"] in seen:
            continue
        unique_ads.append(ad)
        seen.add(ad["library_id"])
    return unique_ads


async def fetch_rendered_text(url: str, *, scrolls: int, wait_ms: int) -> dict[str, Any]:
    from cloakbrowser import launch_async

    browser = await launch_async(
        headless=True,
        humanize=True,
        locale="en-US",
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    page = await browser.new_page(viewport={"width": 1440, "height": 1400})
    requests: list[dict[str, str]] = []

    async def on_request(req: Any) -> None:
        if "api/graphql" in req.url:
            requests.append({"method": req.method, "url": req.url, "post": (req.post_data or "")[:1200]})

    page.on("request", lambda req: asyncio.create_task(on_request(req)))
    await page.goto(url, wait_until="domcontentloaded", timeout=90000)
    await page.wait_for_timeout(wait_ms)
    for _ in range(max(0, scrolls)):
        await page.mouse.wheel(0, 1600)
        await page.wait_for_timeout(3500)
    title = await page.title()
    text = await page.locator("body").inner_text(timeout=20000)
    await browser.close()
    return {"title": title, "text": text, "requests": requests}


def summarize(ads: list[dict[str, Any]]) -> dict[str, Any]:
    accounts: dict[str, dict[str, Any]] = {}
    domains: set[str] = set()
    for ad in ads:
        account = ad.get("page_name") or "Unknown"
        item = accounts.setdefault(
            account,
            {
                "account_name": account,
                "ads_count": 0,
                "active_count": 0,
                "inactive_count": 0,
                "destination_domains": set(),
                "library_ids": [],
                "ctas": Counter(),
            },
        )
        item["ads_count"] += 1
        if ad.get("status") == "Active":
            item["active_count"] += 1
        elif ad.get("status") == "Inactive":
            item["inactive_count"] += 1
        item["library_ids"].append(ad["library_id"])
        for domain in ad.get("destination_domains") or []:
            item["destination_domains"].add(domain)
            domains.add(domain)
        if ad.get("cta"):
            item["ctas"][ad["cta"]] += 1

    account_list = []
    for item in sorted(accounts.values(), key=lambda row: row["ads_count"], reverse=True):
        account_list.append(
            {
                "account_name": item["account_name"],
                "ads_count": item["ads_count"],
                "active_count": item["active_count"],
                "inactive_count": item["inactive_count"],
                "destination_domains": sorted(item["destination_domains"]),
                "library_ids": item["library_ids"],
                "ctas": dict(item["ctas"]),
            }
        )

    return {
        "advertiser_accounts_count": len(account_list),
        "observed_ads_count": len(ads),
        "meta_public_ad_group_note": "Meta Ads Library public pages expose Library IDs, not internal ad group/ad set IDs.",
        "observed_library_id_count": len({ad["library_id"] for ad in ads}),
        "destination_domains": sorted(domains),
        "accounts": account_list,
    }


def query_meta_ads_library(
    target: str,
    *,
    country: str | None = None,
    active_status: str | None = None,
    search_type: str | None = None,
    media_type: str | None = None,
    scrolls: int = 5,
    wait_ms: int = 10000,
    output_dir: str | None = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    normalized = normalize_query(target)
    country = country or normalized["country"]
    active_status = active_status or normalized["active_status"]
    search_type = search_type or normalized["search_type"]
    media_type = media_type or normalized["media_type"]
    url = build_library_url(
        query=normalized["query"],
        country=country,
        active_status=active_status,
        ad_type=normalized.get("ad_type") or "all",
        media_type=media_type,
        search_type=search_type,
    )

    page = asyncio.run(fetch_rendered_text(url, scrolls=scrolls, wait_ms=wait_ms))
    text = page["text"]
    ads = parse_ads_from_text(text)
    summary = summarize(ads)

    result: dict[str, Any] = {
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target": target,
        "query": normalized["query"],
        "country": country,
        "active_status": active_status,
        "search_type": search_type,
        "media_type": media_type,
        "source_url": url,
        "page_title": page["title"],
        "displayed_result_count": extract_result_count(text),
        **summary,
        "ads": ads,
        "raw_text_excerpt": text[:4000],
    }

    if output_dir:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{safe_name(normalized['query'])}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["output_path"] = str(out_path)
    return result


def format_markdown(result: dict[str, Any], *, list_limit: int = 50) -> str:
    lines: list[str] = []
    lines.append("# Meta Ads Library report")
    lines.append("")
    lines.append(f"- Query: `{result['query']}`")
    lines.append(f"- Source: {result['source_url']}")
    lines.append(f"- Displayed result count: `{result['displayed_result_count']}`")
    lines.append(f"- Observed ads loaded: `{result['observed_ads_count']}`")
    lines.append(f"- Advertiser/Page accounts: `{result['advertiser_accounts_count']}`")
    lines.append(f"- Observed Library IDs: `{result['observed_library_id_count']}`")
    lines.append("- Ad group note: Meta public Ads Library does not expose internal ad group/ad set IDs.")
    lines.append(f"- Destination domains: `{', '.join(result['destination_domains']) or '-'}`")
    if result.get("output_path"):
        lines.append(f"- JSON output: `{result['output_path']}`")
    lines.append("")

    lines.append("## Advertiser/Page accounts")
    if not result["accounts"]:
        lines.append("")
        lines.append("No ads match the current search/filter criteria.")
    else:
        lines.append("")
        lines.append("| Account/Page | Ads | Active | Inactive | Destination domains | CTAs |")
        lines.append("|---|---:|---:|---:|---|---|")
        for account in result["accounts"]:
            ctas = ", ".join(f"{k}:{v}" for k, v in sorted(account["ctas"].items())) or "-"
            lines.append(
                f"| {account['account_name']} | {account['ads_count']} | {account['active_count']} | "
                f"{account['inactive_count']} | {', '.join(account['destination_domains']) or '-'} | {ctas} |"
            )

    lines.append("")
    lines.append("## Ads")
    if not result["ads"]:
        lines.append("")
        lines.append("No ad cards were loaded.")
    else:
        lines.append("")
        lines.append("| # | Status | Library ID | Account/Page | Started | Destination | CTA |")
        lines.append("|---:|---|---|---|---|---|---|")
        for idx, ad in enumerate(result["ads"][:list_limit], start=1):
            lines.append(
                f"| {idx} | {ad['status']} | [{ad['library_id']}]({ad['details_url']}) | "
                f"{ad.get('page_name') or '-'} | {ad.get('started_running') or '-'} | "
                f"{', '.join(ad.get('destination_domains') or []) or '-'} | {ad.get('cta') or '-'} |"
            )
        if len(result["ads"]) > list_limit:
            lines.append("")
            lines.append(f"... {len(result['ads']) - list_limit} more loaded ads are in the JSON output.")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query Meta Ads Library using CloakBrowser.")
    parser.add_argument("target", help="Meta Ads Library URL, domain, website URL, or keyword.")
    parser.add_argument("--country", default=None, help="Country filter, default from URL or ALL.")
    parser.add_argument("--active-status", default=None, help="active, inactive, or all. Default from URL or active.")
    parser.add_argument("--search-type", default=None, help="keyword_exact_phrase or keyword_unordered.")
    parser.add_argument("--media-type", default=None, help="all, image, video, meme, etc. Default all.")
    parser.add_argument("--scrolls", type=int, default=5, help="Number of scrolls to load more cards.")
    parser.add_argument("--wait-ms", type=int, default=10000, help="Initial wait after page load.")
    parser.add_argument("--list-limit", type=int, default=50, help="Ads to show in markdown.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of markdown.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Directory for JSON output. Empty disables saving.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = query_meta_ads_library(
            args.target,
            country=args.country,
            active_status=args.active_status,
            search_type=args.search_type,
            media_type=args.media_type,
            scrolls=args.scrolls,
            wait_ms=args.wait_ms,
            output_dir=args.output_dir or None,
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
