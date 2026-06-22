#!/usr/bin/env python3
"""Server-side 3UE login flow for Semrush Keyword Overview.

This module keeps 3UE cookies in the Hermes server environment. A local browser
token is not enough for 3UE: the relay also depends on cookies, IP, and browser
session state. The flow here opens 3UE from CloakBrowser, persists that browser
state, clicks the active SEO Tools "open" button, then queries Semrush in the
same browser context.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from semrush_keyword import (
    DEFAULT_BASE_URL,
    DEFAULT_OUTPUT_DIR,
    DEVICE_CODES,
    SemrushKeywordError,
    build_keyword_url,
    fetch_rendered_text,
    format_markdown,
    keyword_overview_ready,
    parse_keyword_overview,
    safe_name,
)


DEFAULT_3UE_DASHBOARD_URL = "https://dash.3ue.co/zh-Hans/#/page/m/home"
DEFAULT_STATE_DIR = "/home/agent/.hermes/semrush-keyword/browser-state"
DEFAULT_ENV_FILE = "/home/agent/.hermes/.env"
DEFAULT_CDP_URL = "http://127.0.0.1:9222"
VIEWPORT = {"width": 1440, "height": 1400}
OPEN_TEXT = "\u6253\u5f00"
DASHBOARD_READY_MARKERS = (
    ("用户中心", "我的订阅"),
    ("User Center", "My Subscription"),
)


def load_dotenv(path: str | None = None) -> None:
    env_path = Path(path or os.getenv("HERMES_ENV_FILE") or DEFAULT_ENV_FILE)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def credentials_from_env() -> tuple[str, str]:
    load_dotenv()
    username = (
        os.getenv("SEMRUSH_3UE_USERNAME")
        or os.getenv("HERMES_3UE_USERNAME")
        or os.getenv("THREEUE_USERNAME")
        or ""
    ).strip()
    password = (
        os.getenv("SEMRUSH_3UE_PASSWORD")
        or os.getenv("HERMES_3UE_PASSWORD")
        or os.getenv("THREEUE_PASSWORD")
        or ""
    ).strip()
    return username, password


def state_dir(path: str | None = None) -> Path:
    root = Path(path or os.getenv("SEMRUSH_3UE_STATE_DIR") or DEFAULT_STATE_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


def storage_state_path(path: str | None = None) -> Path:
    return state_dir(path) / "storage_state.json"


def session_path(path: str | None = None) -> Path:
    return state_dir(path) / "relay_session.json"


def use_display_browser_for_queries() -> bool:
    value = os.getenv("SEMRUSH_USE_DISPLAY_BROWSER", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


async def launch_semrush_browser(*, headless: bool = True, state_path: str | None = None) -> Any:
    """Launch CloakBrowser, preferring a persistent browser profile when supported."""

    from cloakbrowser import launch_async

    root = state_dir(state_path)
    kwargs = {
        "headless": headless,
        "humanize": True,
        "args": ["--no-sandbox", "--disable-dev-shm-usage"],
    }
    if headless:
        return await launch_async(**kwargs)

    try:
        return await launch_async(user_data_dir=str(root / "profile"), **kwargs)
    except TypeError:
        return await launch_async(**kwargs)


async def new_semrush_page(browser: Any, *, state_path: str | None = None) -> Any:
    """Create a page and restore saved cookies/local storage where possible."""

    storage_path = storage_state_path(state_path)
    new_context = getattr(browser, "new_context", None)
    if callable(new_context):
        try:
            kwargs: dict[str, Any] = {"viewport": VIEWPORT}
            if storage_path.exists():
                kwargs["storage_state"] = str(storage_path)
            context = await browser.new_context(**kwargs)
            return await context.new_page()
        except Exception:
            pass

    page = await browser.new_page(viewport=VIEWPORT)
    if storage_path.exists():
        try:
            data = json.loads(storage_path.read_text(encoding="utf-8"))
            cookies = data.get("cookies") or []
            if cookies:
                await page.context.add_cookies(cookies)
        except Exception:
            pass
    return page


async def save_semrush_state(page: Any, *, state_path: str | None = None, relay_url: str = "") -> None:
    """Persist browser state and the last relay URL for later diagnostics."""

    storage_path = storage_state_path(state_path)
    try:
        await page.context.storage_state(path=str(storage_path))
    except TypeError:
        try:
            data = await page.context.storage_state()
            storage_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    except Exception:
        try:
            cookies = await page.context.cookies()
            storage_path.write_text(json.dumps({"cookies": cookies}, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    if relay_url:
        session_path(state_path).write_text(
            json.dumps(
                {
                    "relay_url": relay_url,
                    "saved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


async def body_text(page: Any, *, timeout_ms: int = 10000) -> str:
    try:
        return await page.locator("body").inner_text(timeout=timeout_ms)
    except Exception:
        return ""


async def dashboard_has_open_button(page: Any) -> bool:
    try:
        if await page.locator(f"button:has-text('{OPEN_TEXT}')").count() > 0:
            return True
        if await page.get_by_text(OPEN_TEXT, exact=True).count() > 0:
            return True
    except Exception:
        pass
    text = await body_text(page)
    return "我的订阅" in text and OPEN_TEXT in text


def looks_like_3ue_dashboard(text: str) -> bool:
    return any(all(marker in text for marker in markers) for markers in DASHBOARD_READY_MARKERS)


async def goto_semrush_keyword_url(page: Any, url: str, *, timeout_ms: int = 90000) -> None:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception as exc:
        if "ERR_ABORTED" not in str(exc):
            raise
        await page.wait_for_timeout(3000)


async def click_semrush_open_entry(page: Any) -> dict[str, Any]:
    """Click the first visible 3UE open entry, even when the text is nested."""

    for selector in (
        f"button:has-text('{OPEN_TEXT}')",
        f"a:has-text('{OPEN_TEXT}')",
        f"[role='button']:has-text('{OPEN_TEXT}')",
    ):
        try:
            locator = page.locator(selector)
            count = await locator.count()
            for idx in range(count):
                candidate = locator.nth(idx)
                if not await candidate.is_visible(timeout=1000):
                    continue
                await candidate.scroll_into_view_if_needed(timeout=3000)
                await candidate.click(timeout=5000)
                return {"clicked": True, "method": selector, "index": idx}
        except Exception:
            pass

    try:
        locator = page.get_by_text(OPEN_TEXT, exact=True)
        count = await locator.count()
        for idx in range(count):
            candidate = locator.nth(idx)
            if not await candidate.is_visible(timeout=1000):
                continue
            await candidate.scroll_into_view_if_needed(timeout=3000)
            await candidate.click(timeout=5000, force=True)
            return {"clicked": True, "method": "text", "index": idx}
    except Exception:
        pass

    return await page.evaluate(
        """
        (openText) => {
          const visible = (el) => {
            if (!el || !el.getBoundingClientRect) return false;
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return rect.width > 0 && rect.height > 0 &&
              style.display !== 'none' && style.visibility !== 'hidden' &&
              style.pointerEvents !== 'none';
          };
          const clickElement = (el, method, index) => {
            el.scrollIntoView({block: 'center', inline: 'center'});
            const rect = el.getBoundingClientRect();
            const x = rect.left + rect.width / 2;
            const y = rect.top + rect.height / 2;
            for (const type of ['mouseover', 'mousedown', 'mouseup', 'click']) {
              el.dispatchEvent(new MouseEvent(type, {
                bubbles: true,
                cancelable: true,
                view: window,
                clientX: x,
                clientY: y,
              }));
            }
            return {clicked: true, method, index, tag: el.tagName, text: el.innerText || el.textContent || ''};
          };

          const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
          const nodes = [];
          for (let node = walker.nextNode(); node; node = walker.nextNode()) {
            if ((node.nodeValue || '').trim() === openText) nodes.push(node);
          }

          for (let index = 0; index < nodes.length; index += 1) {
            let el = nodes[index].parentElement;
            for (let depth = 0; el && depth < 8; depth += 1, el = el.parentElement) {
              if (!visible(el)) continue;
              const role = el.getAttribute('role') || '';
              const cursor = window.getComputedStyle(el).cursor;
              if (['BUTTON', 'A'].includes(el.tagName) || role === 'button' || cursor === 'pointer' || el.onclick) {
                return clickElement(el, 'text-ancestor', index);
              }
            }
            if (nodes[index].parentElement && visible(nodes[index].parentElement)) {
              return clickElement(nodes[index].parentElement, 'text-parent', index);
            }
          }
          return {clicked: false, reason: 'open text not found', openText};
        }
        """,
        OPEN_TEXT,
    )


async def auto_login_3ue(page: Any) -> bool:
    """Fill the 3UE login page from .env credentials when available."""

    if await dashboard_has_open_button(page):
        return True

    username, password = credentials_from_env()
    if not username or not password:
        return False

    text = await body_text(page)
    if "/login" not in (page.url or "") and "用户名" not in text and "密码" not in text:
        return False

    try:
        password_input = page.locator("input[type='password']").first
        if await password_input.count() == 0:
            return False
        username_inputs = page.locator("input:not([type='password'])")
        if await username_inputs.count() == 0:
            return False
        await username_inputs.first.fill(username, timeout=5000)
        await password_input.fill(password, timeout=5000)
        try:
            await page.locator("button:has-text('登录')").first.click(timeout=5000)
        except Exception:
            try:
                await page.locator("button[type='submit']").first.click(timeout=5000)
            except Exception:
                await password_input.press("Enter")
        await page.wait_for_timeout(5000)
    except Exception:
        return False

    return await dashboard_has_open_button(page)


async def wait_for_3ue_login(page: Any, *, wait_seconds: int) -> bool:
    deadline = time.time() + max(0, wait_seconds)
    await auto_login_3ue(page)
    while time.time() <= deadline:
        if await dashboard_has_open_button(page):
            return True
        await page.wait_for_timeout(2000)
    return await dashboard_has_open_button(page)


async def open_semrush_from_dashboard(page: Any, *, timeout_ms: int = 30000) -> Any:
    click_result = await click_semrush_open_entry(page)
    if not click_result.get("clicked"):
        raise SemrushKeywordError(f"3UE dashboard open entry was not clickable: {click_result}")

    deadline = time.time() + (timeout_ms / 1000)
    while time.time() <= deadline:
        if "sem.3ue.co" in (page.url or ""):
            return page
        try:
            for candidate in page.context.pages:
                if "sem.3ue.co" in (candidate.url or ""):
                    return candidate
        except Exception:
            pass
        await page.wait_for_timeout(1000)
    raise SemrushKeywordError("3UE dashboard did not open Semrush. Check that the SEO Tools subscription is active.")


async def prepare_3ue_login(
    *,
    wait_seconds: int = 300,
    headless: bool = False,
    dashboard_url: str | None = None,
    state_path: str | None = None,
) -> dict[str, Any]:
    """Open 3UE in the server browser, wait for login, then save relay state."""

    browser = await launch_semrush_browser(headless=headless, state_path=state_path)
    try:
        page = await new_semrush_page(browser, state_path=state_path)
        await page.goto(dashboard_url or DEFAULT_3UE_DASHBOARD_URL, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(2500)
        await auto_login_3ue(page)

        if not await dashboard_has_open_button(page):
            if wait_seconds <= 0:
                raise SemrushKeywordError(
                    "3UE login is required in the Hermes server-side browser. "
                    "Run prepare_semrush_3ue_login_tool with wait_seconds > 0 and complete the login in that browser."
                )
            if not await wait_for_3ue_login(page, wait_seconds=wait_seconds):
                raise SemrushKeywordError("Timed out waiting for 3UE login on the server-side browser.")

        await save_semrush_state(page, state_path=state_path)
        semrush_page = await open_semrush_from_dashboard(page)
        relay_url = semrush_page.url
        await save_semrush_state(semrush_page, state_path=state_path, relay_url=relay_url)
        return {
            "ok": True,
            "relay_url": relay_url,
            "state_dir": str(state_dir(state_path)),
            "message": "3UE login state saved on the Hermes server. Semrush can now be queried from this server context.",
        }
    finally:
        await browser.close()


async def query_semrush_keyword_via_display_browser(
    keyword: str,
    *,
    database: str = "us",
    device: str = "desktop",
    date: str | None = None,
    base_url: str | None = None,
    wait_ms: int = 15000,
    list_limit: int = 10,
    state_path: str | None = None,
) -> dict[str, Any]:
    """Query through the existing server-side visible CloakBrowser.

    3UE's Semrush relay can reject newly launched headless contexts even when
    cookies are present. The Xvfb/noVNC browser keeps the real relay session
    warm, so automated keyword queries should prefer that browser via CDP.
    """

    from playwright.async_api import async_playwright

    cdp_url = os.getenv("SEMRUSH_CDP_URL") or DEFAULT_CDP_URL
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(cdp_url)
        try:
            context = browser.contexts[0] if browser.contexts else await browser.new_context(viewport=VIEWPORT)
            page = context.pages[0] if context.pages else await context.new_page()

            await page.goto(
                os.getenv("SEMRUSH_3UE_DASHBOARD_URL") or DEFAULT_3UE_DASHBOARD_URL,
                wait_until="domcontentloaded",
                timeout=90000,
            )
            await page.wait_for_timeout(3000)
            await auto_login_3ue(page)
            if not await dashboard_has_open_button(page):
                raise SemrushKeywordError("3UE login is required on the Hermes display browser.")
            await save_semrush_state(page, state_path=state_path)

            url = build_keyword_url(
                keyword,
                database=database,
                device=device,
                date=date,
                base_url=base_url or DEFAULT_BASE_URL,
            )
            await goto_semrush_keyword_url(page, url)

            text = ""
            attempts = max(4, min(24, int(wait_ms / 3000) + 4))
            for _ in range(attempts):
                await page.wait_for_timeout(3000)
                text = await body_text(page, timeout_ms=25000)
                if keyword_overview_ready(text):
                    break
                if looks_like_3ue_dashboard(text):
                    raise SemrushKeywordError(
                        "Semrush relay redirected back to the 3UE dashboard. "
                        "Check the server display browser session or selected 3UE node."
                    )

            result = parse_keyword_overview(
                text,
                keyword=keyword,
                database=database,
                device=device,
                source_url=page.url or url,
                page_title=await page.title(),
                list_limit=list_limit,
            )
            await save_semrush_state(page, state_path=state_path, relay_url=page.url)
            return result
        finally:
            await browser.close()


async def query_semrush_keyword_async(
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
    auto_login: bool = True,
    interactive_login_wait_seconds: int = 0,
    state_path: str | None = None,
) -> dict[str, Any]:
    """Query Semrush, optionally deriving relay auth from server-side 3UE login."""

    if not auto_login:
        url = build_keyword_url(
            keyword,
            database=database,
            device=device,
            date=date,
            proxy_url=proxy_url,
            base_url=base_url,
            gmitm_token=gmitm_token,
        )
        page = await fetch_rendered_text(url, wait_ms=wait_ms, headless=headless)
        result = parse_keyword_overview(
            page["text"],
            keyword=keyword,
            database=database,
            device=device,
            source_url=page["url"] or url,
            page_title=page["title"],
            list_limit=list_limit,
        )
    else:
        if use_display_browser_for_queries():
            result = await query_semrush_keyword_via_display_browser(
                keyword,
                database=database,
                device=device,
                date=date,
                base_url=base_url,
                wait_ms=wait_ms,
                list_limit=list_limit,
                state_path=state_path,
            )
        else:
            browser = await launch_semrush_browser(headless=headless, state_path=state_path)
            try:
                page = await new_semrush_page(browser, state_path=state_path)
                await page.goto(os.getenv("SEMRUSH_3UE_DASHBOARD_URL") or DEFAULT_3UE_DASHBOARD_URL, wait_until="domcontentloaded", timeout=90000)
                await page.wait_for_timeout(2500)
                await auto_login_3ue(page)
                if not await dashboard_has_open_button(page):
                    if interactive_login_wait_seconds <= 0:
                        raise SemrushKeywordError(
                            "3UE login is required on the Hermes server-side browser. "
                            "First run prepare_semrush_3ue_login_tool(wait_seconds=300, headless=False), "
                            "complete login there, then retry this keyword query."
                        )
                    if not await wait_for_3ue_login(page, wait_seconds=interactive_login_wait_seconds):
                        raise SemrushKeywordError("Timed out waiting for 3UE login on the server-side browser.")

                await save_semrush_state(page, state_path=state_path)
                page = await open_semrush_from_dashboard(page)
                relay_url = page.url
                await save_semrush_state(page, state_path=state_path, relay_url=relay_url)

                token = (parse_qs(urlparse(relay_url).query).get("__gmitm") or [None])[0]
                url = build_keyword_url(
                    keyword,
                    database=database,
                    device=device,
                    date=date,
                    base_url=base_url or DEFAULT_BASE_URL,
                    gmitm_token=token,
                )
                await goto_semrush_keyword_url(page, url)
                await page.wait_for_timeout(max(1000, wait_ms))
                text = await body_text(page, timeout_ms=25000)
                for _ in range(4):
                    if keyword_overview_ready(text):
                        break
                    await page.wait_for_timeout(3000)
                    text = await body_text(page, timeout_ms=25000)

                result = parse_keyword_overview(
                    text,
                    keyword=keyword,
                    database=database,
                    device=device,
                    source_url=page.url or url,
                    page_title=await page.title(),
                    list_limit=list_limit,
                )
            finally:
                await browser.close()

    if output_dir:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{safe_name(keyword)}-{database}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["output_path"] = str(out_path)
    return result


def format_login_result(result: dict[str, Any]) -> str:
    relay_url = result.get("relay_url") or ""
    redacted_url = relay_url
    if "__gmitm=" in redacted_url:
        redacted_url = redacted_url.split("__gmitm=", 1)[0] + "__gmitm=***"
    return "\n".join(
        [
            "# 3UE Server Login Ready",
            "",
            f"- Status: `{result.get('message') or 'ok'}`",
            f"- State dir: `{result.get('state_dir') or '-'}`",
            f"- Relay URL: `{redacted_url or '-'}`",
        ]
    )
