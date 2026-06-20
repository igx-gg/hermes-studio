#!/usr/bin/env python3
"""Google Ads Transparency Center domain/ad account reporter.

The script uses Google's public Ads Transparency Center RPC endpoints for speed.
CloakBrowser can be used as a page-level fallback/check when the site changes or
the direct endpoint is challenged.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

import requests


SEARCH_CREATIVES_URL = (
    "https://adstransparency.google.com/anji/_/rpc/"
    "SearchService/SearchCreatives?authuser="
)
GET_ADVERTISER_URL = (
    "https://adstransparency.google.com/anji/_/rpc/"
    "LookupService/GetAdvertiserById?authuser="
)

DEFAULT_HEADERS = {
    "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
    "referer": "https://adstransparency.google.com/",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
    ),
}

FORMAT_LABELS = {
    1: "text",
    2: "image",
    3: "video",
}

REGION_CODES = {
    "anywhere": 2840,
    "us": 2840,
}


class AdsTransparencyError(RuntimeError):
    pass


def normalize_target(target: str) -> dict[str, str]:
    value = (target or "").strip()
    if not value:
        raise AdsTransparencyError("Target domain or URL is required.")

    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = (parsed.netloc or "").lower()

    if host == "adstransparency.google.com":
        query = parse_qs(parsed.query)
        if query.get("domain"):
            domain = query["domain"][0].strip().lower()
            return {"kind": "domain", "value": domain, "source": value}
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] == "advertiser" and parts[1].startswith("AR"):
            return {"kind": "advertiser", "value": parts[1], "source": value}
        raise AdsTransparencyError(
            "Ads Transparency URL must include ?domain=... or /advertiser/AR..."
        )

    domain = host or parsed.path
    domain = domain.strip().lower()
    if domain.startswith("www."):
        domain = domain[4:]
    domain = domain.split("/")[0]
    if not domain or "." not in domain:
        raise AdsTransparencyError(f"Cannot extract a domain from {target!r}.")
    return {"kind": "domain", "value": domain, "source": value}


def timestamp_to_date(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    seconds = value.get("1")
    if not seconds:
        return None
    try:
        dt = datetime.fromtimestamp(int(seconds), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
    return dt.strftime("%Y-%m-%d")


def post_rpc(
    session: requests.Session,
    url: str,
    payload: dict[str, Any],
    timeout: int = 30,
    retries: int = 2,
) -> dict[str, Any]:
    body = {"f.req": json.dumps(payload, separators=(",", ":"))}
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = session.post(url, data=body, headers=DEFAULT_HEADERS, timeout=timeout)
            if response.status_code != 200:
                raise AdsTransparencyError(
                    f"Google RPC returned HTTP {response.status_code}: {response.text[:200]}"
                )
            if not response.text.strip():
                return {}
            return response.json()
        except Exception as exc:  # noqa: BLE001 - preserve exact provider error.
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise AdsTransparencyError(str(last_error))


def build_search_payload(
    *,
    domain: str | None,
    advertiser_ids: list[str] | None,
    page_size: int,
    region_code: int,
    page_token: str | None = None,
) -> dict[str, Any]:
    criteria: dict[str, Any] = {"12": {"1": domain or "", "2": True}}
    if advertiser_ids:
        criteria["13"] = {"1": advertiser_ids}

    payload: dict[str, Any] = {
        "2": page_size,
        "3": criteria,
        "7": {"1": 1, "2": 0, "3": region_code},
    }
    if page_token:
        payload["4"] = page_token
    return payload


def collect_strings(value: Any, found: list[str]) -> None:
    if isinstance(value, dict):
        for inner in value.values():
            collect_strings(inner, found)
    elif isinstance(value, list):
        for inner in value:
            collect_strings(inner, found)
    elif isinstance(value, str):
        found.append(html.unescape(value))


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            out.append(value)
            seen.add(value)
    return out


def parse_creative_assets(raw: Any) -> dict[str, Any]:
    strings: list[str] = []
    collect_strings(raw, strings)

    urls: list[str] = []
    image_urls: list[str] = []
    ad_group_ids: list[str] = []
    text_fragments: list[str] = []

    for raw_text in strings:
        text = html.unescape(raw_text)
        for match in re.findall(r"https?://[^\s\"'<>]+", text):
            clean = unquote(match).rstrip(").,")
            urls.append(clean)
            parsed = urlparse(clean)
            query = parse_qs(parsed.query)
            if query.get("adGroupId"):
                ad_group_ids.extend(query["adGroupId"])
        for match in re.findall(r"<img[^>]+src=[\"']([^\"']+)", text, flags=re.I):
            image_urls.append(html.unescape(match))
        plain = re.sub(r"<[^>]+>", " ", text)
        plain = re.sub(r"\s+", " ", plain).strip()
        if plain and "http" not in plain and len(plain) >= 3:
            text_fragments.append(plain)

    return {
        "preview_urls": unique(urls),
        "image_urls": unique(image_urls),
        "ad_group_ids": unique(ad_group_ids),
        "text_fragments": unique(text_fragments)[:12],
    }


def parse_ad(item: dict[str, Any], region: str, default_domain: str | None) -> dict[str, Any]:
    assets = parse_creative_assets(item.get("3") or {})
    advertiser_id = item.get("1")
    creative_id = item.get("2")
    return {
        "advertiser_id": advertiser_id,
        "advertiser_name": item.get("12") or "",
        "creative_id": creative_id,
        "format_code": item.get("4"),
        "format": FORMAT_LABELS.get(item.get("4"), f"unknown:{item.get('4')}"),
        "first_shown": timestamp_to_date(item.get("6")),
        "last_shown": timestamp_to_date(item.get("7")),
        "days_shown": item.get("13"),
        "product_domain": item.get("14") or default_domain or "",
        "ad_group_ids": assets["ad_group_ids"],
        "preview_urls": assets["preview_urls"],
        "image_urls": assets["image_urls"],
        "text_fragments": assets["text_fragments"],
        "details_url": (
            "https://adstransparency.google.com/advertiser/"
            f"{advertiser_id}/creative/{creative_id}?region={quote(region)}"
            if advertiser_id and creative_id
            else ""
        ),
    }


def fetch_advertiser(session: requests.Session, advertiser_id: str) -> dict[str, Any]:
    payload = {"1": advertiser_id, "3": {"1": 1}}
    data = post_rpc(session, GET_ADVERTISER_URL, payload)
    raw = data.get("1") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {"advertiser_id": advertiser_id}
    legal = raw.get("9") or {}
    return {
        "advertiser_id": raw.get("1") or advertiser_id,
        "name": raw.get("2") or "",
        "country": raw.get("3") or raw.get("11") or "",
        "legal_name": legal.get("1") or legal.get("2") or "",
        "verification_country": raw.get("11") or "",
    }


async def cloak_page_text(target: str, region: str) -> str:
    from cloakbrowser import launch_async

    normalized = normalize_target(target)
    if normalized["kind"] == "domain":
        url = (
            "https://adstransparency.google.com/"
            f"?region={quote(region)}&domain={quote(normalized['value'])}"
        )
    else:
        url = f"https://adstransparency.google.com/advertiser/{normalized['value']}?region={quote(region)}"

    browser = await launch_async(
        headless=True,
        humanize=True,
        locale="en-US",
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    page = await browser.new_page(viewport={"width": 1440, "height": 1100})
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(8000)
    text = await page.locator("body").inner_text(timeout=10000)
    await browser.close()
    return text


def estimate_display(first_response: dict[str, Any], fetched_count: int) -> str:
    upper = first_response.get("5")
    lower = first_response.get("4")
    if upper:
        try:
            value = int(upper)
            if value >= 1000:
                return f"~{value // 1000}K" if value % 1000 == 0 else f"~{value}"
            return str(value)
        except (TypeError, ValueError):
            return str(upper)
    if lower:
        return str(lower)
    return str(fetched_count)


def query_ads_transparency(
    target: str,
    *,
    region: str = "anywhere",
    max_ads: int = 200,
    page_size: int = 40,
    cloak_check: bool = False,
    output_dir: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_target(target)
    region_code = REGION_CODES.get(region.lower(), REGION_CODES["anywhere"])
    page_size = max(1, min(page_size, 40))
    max_ads = max(0, max_ads)

    session = requests.Session()
    domain = normalized["value"] if normalized["kind"] == "domain" else None
    advertiser_ids = [normalized["value"]] if normalized["kind"] == "advertiser" else None

    ads: list[dict[str, Any]] = []
    seen_creatives: set[str] = set()
    page_token: str | None = None
    first_response: dict[str, Any] = {}

    while True:
        payload = build_search_payload(
            domain=domain,
            advertiser_ids=advertiser_ids,
            page_size=page_size,
            region_code=region_code,
            page_token=page_token,
        )
        data = post_rpc(session, SEARCH_CREATIVES_URL, payload)
        if not first_response:
            first_response = data
        raw_items = data.get("1") or []
        if not raw_items:
            break
        for item in raw_items:
            ad = parse_ad(item, region, domain)
            creative_id = ad.get("creative_id")
            if creative_id and creative_id in seen_creatives:
                continue
            if creative_id:
                seen_creatives.add(creative_id)
            ads.append(ad)
            if len(ads) >= max_ads:
                break
        if len(ads) >= max_ads:
            break
        page_token = data.get("2")
        if not page_token:
            break

    advertiser_ids_found = sorted({ad["advertiser_id"] for ad in ads if ad.get("advertiser_id")})
    advertiser_details = {
        advertiser_id: fetch_advertiser(session, advertiser_id)
        for advertiser_id in advertiser_ids_found
    }

    accounts: dict[str, dict[str, Any]] = {}
    all_ad_group_ids: set[str] = set()
    unknown_ad_group_count = 0
    product_domains: set[str] = set()

    for ad in ads:
        advertiser_id = ad.get("advertiser_id") or "unknown"
        detail = advertiser_details.get(advertiser_id, {})
        account = accounts.setdefault(
            advertiser_id,
            {
                "advertiser_id": advertiser_id,
                "advertiser_name": detail.get("name") or ad.get("advertiser_name") or "",
                "legal_name": detail.get("legal_name") or "",
                "country": detail.get("country") or "",
                "ads_count": 0,
                "formats": Counter(),
                "product_domains": set(),
                "ad_group_ids": set(),
                "ads": [],
            },
        )
        account["ads_count"] += 1
        account["formats"][ad.get("format") or "unknown"] += 1
        if ad.get("product_domain"):
            account["product_domains"].add(ad["product_domain"])
            product_domains.add(ad["product_domain"])
        if ad.get("ad_group_ids"):
            account["ad_group_ids"].update(ad["ad_group_ids"])
            all_ad_group_ids.update(ad["ad_group_ids"])
        else:
            unknown_ad_group_count += 1
        account["ads"].append(ad)

    account_list: list[dict[str, Any]] = []
    for account in sorted(accounts.values(), key=lambda item: item["ads_count"], reverse=True):
        account_list.append(
            {
                "advertiser_id": account["advertiser_id"],
                "advertiser_name": account["advertiser_name"],
                "legal_name": account["legal_name"],
                "country": account["country"],
                "ads_count": account["ads_count"],
                "formats": dict(account["formats"]),
                "product_domains": sorted(account["product_domains"]),
                "observed_ad_group_count": len(account["ad_group_ids"]),
                "observed_ad_group_ids": sorted(account["ad_group_ids"]),
                "ads": account["ads"],
            }
        )

    result: dict[str, Any] = {
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target": target,
        "query_kind": normalized["kind"],
        "query_value": normalized["value"],
        "region": region,
        "estimated_ads_count": estimate_display(first_response, len(ads)),
        "estimated_ads_lower_bound": first_response.get("4"),
        "estimated_ads_upper_bound": first_response.get("5"),
        "fetched_ads_count": len(ads),
        "truncated": bool(first_response.get("2")) and len(ads) >= max_ads,
        "max_ads": max_ads,
        "advertiser_accounts_count": len(account_list),
        "observed_ad_group_count": len(all_ad_group_ids),
        "ads_without_observed_ad_group": unknown_ad_group_count,
        "product_domains": sorted(product_domains),
        "accounts": account_list,
        "source_url": (
            "https://adstransparency.google.com/"
            f"?region={quote(region)}&domain={quote(normalized['value'])}"
            if normalized["kind"] == "domain"
            else f"https://adstransparency.google.com/advertiser/{normalized['value']}?region={quote(region)}"
        ),
    }

    if cloak_check:
        try:
            result["cloak_page_text_excerpt"] = asyncio.run(cloak_page_text(target, region))[:2000]
        except Exception as exc:  # noqa: BLE001
            result["cloak_page_error"] = str(exc)

    if output_dir:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", normalized["value"])
        out_path = out_dir / f"{safe_name}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["output_path"] = str(out_path)

    return result


def format_markdown(result: dict[str, Any], list_limit: int = 80) -> str:
    lines: list[str] = []
    lines.append("# Google Ads Transparency report")
    lines.append("")
    lines.append(f"- Target: `{result['query_value']}`")
    lines.append(f"- Region: `{result['region']}`")
    lines.append(f"- Source: {result['source_url']}")
    lines.append(f"- Estimated ads: `{result['estimated_ads_count']}`")
    lines.append(f"- Fetched ads: `{result['fetched_ads_count']}`")
    lines.append(f"- Advertiser accounts: `{result['advertiser_accounts_count']}`")
    lines.append(f"- Observed ad groups: `{result['observed_ad_group_count']}`")
    if result.get("ads_without_observed_ad_group"):
        lines.append(f"- Ads without visible adGroupId: `{result['ads_without_observed_ad_group']}`")
    if result.get("truncated"):
        lines.append(f"- Note: result is capped at `{result['max_ads']}` ads; increase max_ads to fetch more.")
    if result.get("output_path"):
        lines.append(f"- JSON output: `{result['output_path']}`")
    lines.append("")

    lines.append("## Advertiser accounts")
    if not result["accounts"]:
        lines.append("")
        lines.append("No active ads or advertiser accounts were returned for this query.")
    else:
        lines.append("")
        lines.append("| Account | Advertiser ID | Ads | Products | Formats | Ad groups |")
        lines.append("|---|---:|---:|---|---|---:|")
        for account in result["accounts"]:
            products = ", ".join(account["product_domains"]) or "-"
            formats = ", ".join(f"{k}:{v}" for k, v in sorted(account["formats"].items())) or "-"
            lines.append(
                "| {name} | `{aid}` | {ads} | {products} | {formats} | {groups} |".format(
                    name=account["advertiser_name"] or "-",
                    aid=account["advertiser_id"],
                    ads=account["ads_count"],
                    products=products,
                    formats=formats,
                    groups=account["observed_ad_group_count"],
                )
            )

    lines.append("")
    lines.append("## Ads")
    ads = [ad for account in result["accounts"] for ad in account["ads"]]
    if not ads:
        lines.append("")
        lines.append("No ads found.")
    else:
        lines.append("")
        lines.append("| # | Account | Product | Format | Creative ID | Ad group | First | Last | Days |")
        lines.append("|---:|---|---|---|---|---|---|---|---:|")
        for index, ad in enumerate(ads[:list_limit], start=1):
            groups = ", ".join(ad["ad_group_ids"][:2]) if ad["ad_group_ids"] else "-"
            if len(ad["ad_group_ids"]) > 2:
                groups += f" +{len(ad['ad_group_ids']) - 2}"
            lines.append(
                "| {idx} | {account} | {product} | {fmt} | [{cid}]({url}) | {groups} | {first} | {last} | {days} |".format(
                    idx=index,
                    account=ad.get("advertiser_name") or "-",
                    product=ad.get("product_domain") or "-",
                    fmt=ad.get("format") or "-",
                    cid=ad.get("creative_id") or "-",
                    url=ad.get("details_url") or result["source_url"],
                    groups=groups,
                    first=ad.get("first_shown") or "-",
                    last=ad.get("last_shown") or "-",
                    days=ad.get("days_shown") if ad.get("days_shown") is not None else "-",
                )
            )
        if len(ads) > list_limit:
            lines.append("")
            lines.append(f"... {len(ads) - list_limit} more ads are in the JSON output.")

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query Google Ads Transparency Center by domain or advertiser URL.")
    parser.add_argument("target", help="Domain, website URL, Ads Transparency URL, or advertiser URL.")
    parser.add_argument("--region", default="anywhere", help="Region label. Default: anywhere.")
    parser.add_argument("--max-ads", type=int, default=200, help="Maximum ads to fetch. Default: 200.")
    parser.add_argument("--page-size", type=int, default=40, help="Page size, capped at 40.")
    parser.add_argument("--list-limit", type=int, default=80, help="Maximum ads to show in markdown.")
    parser.add_argument("--cloak-check", action="store_true", help="Also open the public page with CloakBrowser.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of markdown.")
    parser.add_argument(
        "--output-dir",
        default="/home/agent/.hermes/ads-transparency/runs",
        help="Directory for JSON run output. Set empty string to disable.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = query_ads_transparency(
            args.target,
            region=args.region,
            max_ads=args.max_ads,
            page_size=args.page_size,
            cloak_check=args.cloak_check,
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
