#!/usr/bin/env python3
"""Daily Google Trends monitor for Hermes cron and MCP.

The script prefers Google Trends' public widget endpoints for reliable numeric
data and can fall back to CloakBrowser when direct requests are challenged.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import requests


DEFAULT_ROOT = Path("/home/agent/.hermes/scripts/google-trends-monitor")
DEFAULT_CONFIG = DEFAULT_ROOT / "keywords.json"
DEFAULT_DATA_DIR = Path("/home/agent/.hermes/trends")


class TrendsError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def strip_google_prefix(text: str) -> str:
    idx = text.find("{")
    if idx < 0:
        raise TrendsError("Google Trends returned a non-JSON response")
    return text[idx:]


def load_json_response(text: str) -> dict[str, Any]:
    return json.loads(strip_google_prefix(text))


def read_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_keywords(value: Any) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def trend_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "referer": "https://trends.google.com/trends/",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/146.0.0.0 Safari/537.36"
            ),
        }
    )
    return session


def build_explore_req(keyword: str, geo: str, timeframe: str, prop: str = "") -> dict[str, Any]:
    return {
        "comparisonItem": [
            {
                "keyword": keyword,
                "geo": geo,
                "time": timeframe,
            }
        ],
        "category": 0,
        "property": prop,
    }


def trends_get(session: requests.Session, url: str, params: dict[str, Any]) -> dict[str, Any]:
    response = session.get(url, params=params, timeout=35)
    if response.status_code == 429:
        raise TrendsError("Google Trends rate limited the request")
    if response.status_code >= 400:
        raise TrendsError(f"Google Trends HTTP {response.status_code}: {response.text[:200]}")
    return load_json_response(response.text)


def fetch_term_direct(
    keyword: str,
    *,
    geo: str,
    timeframe: str,
    hl: str,
    tz: int,
    prop: str,
) -> list[dict[str, Any]]:
    session = trend_session()
    req = build_explore_req(keyword, geo, timeframe, prop)
    explore = trends_get(
        session,
        "https://trends.google.com/trends/api/explore",
        {
            "hl": hl,
            "tz": str(tz),
            "req": json.dumps(req, separators=(",", ":")),
        },
    )

    widgets = explore.get("widgets") or []
    widget = next((item for item in widgets if item.get("id") == "TIMESERIES"), None)
    if not widget:
        raise TrendsError(f"No TIMESERIES widget returned for {keyword!r}")

    data = trends_get(
        session,
        "https://trends.google.com/trends/api/widgetdata/multiline",
        {
            "hl": hl,
            "tz": str(tz),
            "req": json.dumps(widget.get("request") or {}, separators=(",", ":")),
            "token": widget.get("token"),
        },
    )

    timeline = data.get("default", {}).get("timelineData") or []
    points: list[dict[str, Any]] = []
    for row in timeline:
        values = row.get("value") or []
        if not values:
            continue
        points.append(
            {
                "time": int(row.get("time", 0) or 0),
                "label": row.get("formattedAxisTime") or row.get("formattedTime") or "",
                "value": int(values[0]),
            }
        )
    if not points:
        raise TrendsError(f"No timeline values returned for {keyword!r}")
    return points


def cloak_fetch_text(url: str) -> str:
    from cloakbrowser import launch

    browser = launch(headless=True, humanize=True)
    try:
        page = browser.new_page()
        page.goto("https://trends.google.com/trends/", wait_until="domcontentloaded", timeout=60000)
        time.sleep(1.5)
        return page.evaluate(
            """async (url) => {
                const response = await fetch(url, { credentials: 'include' });
                return await response.text();
            }""",
            url,
        )
    finally:
        browser.close()


def fetch_term_with_cloak(
    keyword: str,
    *,
    geo: str,
    timeframe: str,
    hl: str,
    tz: int,
    prop: str,
) -> list[dict[str, Any]]:
    req = build_explore_req(keyword, geo, timeframe, prop)
    explore_url = (
        "https://trends.google.com/trends/api/explore?"
        + urlencode({"hl": hl, "tz": str(tz), "req": json.dumps(req, separators=(",", ":"))})
    )
    explore = load_json_response(cloak_fetch_text(explore_url))
    widget = next((item for item in (explore.get("widgets") or []) if item.get("id") == "TIMESERIES"), None)
    if not widget:
        raise TrendsError(f"No TIMESERIES widget returned for {keyword!r} via CloakBrowser")
    data_url = (
        "https://trends.google.com/trends/api/widgetdata/multiline?"
        + urlencode(
            {
                "hl": hl,
                "tz": str(tz),
                "req": json.dumps(widget.get("request") or {}, separators=(",", ":")),
                "token": widget.get("token"),
            }
        )
    )
    data = load_json_response(cloak_fetch_text(data_url))
    points = []
    for row in data.get("default", {}).get("timelineData") or []:
        values = row.get("value") or []
        if values:
            points.append(
                {
                    "time": int(row.get("time", 0) or 0),
                    "label": row.get("formattedAxisTime") or row.get("formattedTime") or "",
                    "value": int(values[0]),
                }
            )
    if not points:
        raise TrendsError(f"No timeline values returned for {keyword!r} via CloakBrowser")
    return points


def average(values: list[int]) -> float:
    return round(float(statistics.mean(values)), 2) if values else 0.0


def pct_change(new: float, old: float) -> float | None:
    if old <= 0:
        return None
    return round(((new - old) / old) * 100, 2)


def summarize(keyword: str, points: list[dict[str, Any]], alert: dict[str, Any]) -> dict[str, Any]:
    values = [int(point["value"]) for point in points]
    latest = values[-1]
    previous = values[-2] if len(values) >= 2 else latest
    avg_7 = average(values[-7:])
    avg_30 = average(values[-30:])
    change_pct = pct_change(avg_7, avg_30)
    latest_min = int(alert.get("latest_min", 70) or 70)
    pct_min = float(alert.get("pct_increase_min", 25) or 25)

    if latest >= latest_min and (change_pct is None or change_pct >= pct_min or latest - previous >= 20):
        status = "spiking"
    elif change_pct is not None and change_pct >= 10:
        status = "rising"
    elif change_pct is not None and change_pct <= -20:
        status = "cooling"
    else:
        status = "stable"

    return {
        "keyword": keyword,
        "latest": latest,
        "previous": previous,
        "latest_delta": latest - previous,
        "avg_7": avg_7,
        "avg_30": avg_30,
        "avg_7_vs_30_pct": change_pct,
        "status": status,
        "last_label": points[-1].get("label", ""),
        "points": points,
    }


def write_artifacts(result: dict[str, Any], data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    stamp = result["run_at"].replace(":", "-")
    (data_dir / f"{stamp}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = data_dir / "daily_summary.csv"
    exists = csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "run_at",
                "keyword",
                "geo",
                "timeframe",
                "latest",
                "previous",
                "latest_delta",
                "avg_7",
                "avg_30",
                "avg_7_vs_30_pct",
                "status",
                "last_label",
            ],
        )
        if not exists:
            writer.writeheader()
        for item in result["summaries"]:
            row = {key: item.get(key) for key in writer.fieldnames}
            row["run_at"] = result["run_at"]
            row["geo"] = result["geo"]
            row["timeframe"] = result["timeframe"]
            writer.writerow(row)


def markdown_report(result: dict[str, Any]) -> str:
    rows = sorted(
        result["summaries"],
        key=lambda item: ({"spiking": 0, "rising": 1, "stable": 2, "cooling": 3}.get(item["status"], 9), -item["latest"]),
    )
    lines = [
        "# Google Trends daily monitor",
        "",
        f"- Run time UTC: `{result['run_at']}`",
        f"- Geo: `{result['geo']}`",
        f"- Timeframe: `{result['timeframe']}`",
        f"- CloakBrowser used: `{result['cloak_used']}`",
        "",
        "| Keyword | Status | Latest | Delta | Avg 7 | Avg 30 | Avg7 vs Avg30 | Last point |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in rows:
        pct = "" if item["avg_7_vs_30_pct"] is None else f"{item['avg_7_vs_30_pct']}%"
        lines.append(
            f"| {item['keyword']} | {item['status']} | {item['latest']} | {item['latest_delta']} | "
            f"{item['avg_7']} | {item['avg_30']} | {pct} | {item['last_label']} |"
        )

    spiking = [item for item in rows if item["status"] == "spiking"]
    rising = [item for item in rows if item["status"] == "rising"]
    lines.extend(["", "## Signals", ""])
    if spiking:
        lines.append("Spiking terms: " + ", ".join(f"`{item['keyword']}`" for item in spiking))
    elif rising:
        lines.append("Rising terms: " + ", ".join(f"`{item['keyword']}`" for item in rising))
    else:
        lines.append("No spike-level movement detected in this run.")

    if result.get("errors"):
        lines.extend(["", "## Collection Errors", ""])
        for err in result["errors"]:
            lines.append(f"- `{err['keyword']}`: {err['error']}")

    lines.extend(
        [
            "",
            "Note: Google Trends scores are relative 0-100 values within each keyword's selected timeframe.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_monitor(args: argparse.Namespace) -> dict[str, Any]:
    config = read_config(Path(args.config))
    keywords = normalize_keywords(args.keywords) or normalize_keywords(config.get("keywords"))
    if not keywords:
        raise TrendsError("No keywords configured")

    geo = args.geo or str(config.get("geo") or "")
    timeframe = args.timeframe or str(config.get("timeframe") or "now 7-d")
    hl = args.hl or str(config.get("hl") or "en-US")
    tz = int(args.tz if args.tz is not None else config.get("tz", 0))
    prop = args.property if args.property is not None else str(config.get("property") or "")
    use_cloak = bool(args.use_cloak or config.get("use_cloak"))
    cloak_fallback = bool(args.cloak_fallback or config.get("cloak_fallback", True))
    alert = config.get("alert") if isinstance(config.get("alert"), dict) else {}

    summaries: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    cloak_used = False

    for keyword in keywords:
        try:
            if use_cloak:
                points = fetch_term_with_cloak(keyword, geo=geo, timeframe=timeframe, hl=hl, tz=tz, prop=prop)
                cloak_used = True
            else:
                try:
                    points = fetch_term_direct(keyword, geo=geo, timeframe=timeframe, hl=hl, tz=tz, prop=prop)
                except Exception:
                    if not cloak_fallback:
                        raise
                    points = fetch_term_with_cloak(keyword, geo=geo, timeframe=timeframe, hl=hl, tz=tz, prop=prop)
                    cloak_used = True
            summaries.append(summarize(keyword, points, alert))
            time.sleep(0.5)
        except Exception as exc:
            errors.append({"keyword": keyword, "error": str(exc)})

    result = {
        "run_at": utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "geo": geo,
        "timeframe": timeframe,
        "hl": hl,
        "tz": tz,
        "property": prop,
        "cloak_used": cloak_used,
        "summaries": summaries,
        "errors": errors,
    }
    if not summaries:
        raise TrendsError("No keyword data was collected: " + "; ".join(f"{e['keyword']}: {e['error']}" for e in errors))
    return result


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor Google Trends keyword roots.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--keywords", default="")
    parser.add_argument("--geo", default="")
    parser.add_argument("--timeframe", default="")
    parser.add_argument("--hl", default="")
    parser.add_argument("--tz", type=int, default=None)
    parser.add_argument("--property", default=None)
    parser.add_argument("--use-cloak", action="store_true")
    parser.add_argument("--cloak-fallback", action="store_true")
    parser.add_argument("--data-dir", default="")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        result = run_monitor(args)
        config = read_config(Path(args.config))
        data_dir = Path(args.data_dir or config.get("data_dir") or DEFAULT_DATA_DIR)
        write_artifacts(result, data_dir)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(markdown_report(result))
        return 0
    except Exception as exc:
        print(f"Google Trends monitor failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
