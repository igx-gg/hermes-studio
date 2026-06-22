#!/usr/bin/env python3
"""Install and register the Semrush Keyword MCP server for Hermes Agent."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


DEFAULT_HERMES_HOME = Path("/home/agent/.hermes")
DEFAULT_PYTHON = "/opt/hermes/.venv/bin/python"
SERVER_NAME = "semrush-keyword"
SCRIPT_FILES = (
    "install_semrush_keyword_mcp.py",
    "semrush_keyword.py",
    "semrush_keyword_auto.py",
    "semrush_backlinks.py",
    "semrush_keyword_mcp.py",
    "display_watchdog.py",
    "start_display_watchdog.sh",
    "README.md",
)


class InstallError(RuntimeError):
    pass


def script_dir() -> Path:
    return Path(__file__).resolve().parent


def profile_dir(hermes_home: Path, profile: str) -> Path:
    profile = (profile or "default").strip() or "default"
    if profile == "default":
        return hermes_home
    candidate = hermes_home / "profiles" / profile
    return candidate if candidate.exists() else hermes_home / "profiles" / profile


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml
    except Exception as exc:  # noqa: BLE001
        raise InstallError("PyYAML is required to update Hermes config.yaml") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise InstallError(f"Expected a YAML object in {path}")
    return data


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    try:
        import yaml
    except Exception as exc:  # noqa: BLE001
        raise InstallError("PyYAML is required to update Hermes config.yaml") from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = path.with_name(f"{path.name}.bak.{stamp}")
        shutil.copy2(path, backup)

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    tmp.replace(path)


def extract_proxy_info(proxy_url: str | None, gmitm_token: str | None, base_url: str | None) -> tuple[str | None, str | None]:
    token = (gmitm_token or "").strip() or None
    base = (base_url or "").strip() or None
    raw = (proxy_url or "").strip()
    if raw:
        parsed = urlparse(raw)
        if parsed.scheme and parsed.netloc:
            base = base or f"{parsed.scheme}://{parsed.netloc}"
            query = parse_qs(parsed.query)
            token = token or (query.get("__gmitm") or [None])[0]
    return base, token


def copy_scripts(target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    src = script_dir()
    for name in SCRIPT_FILES:
        source_path = src / name
        if not source_path.exists():
            raise InstallError(f"Missing source file: {source_path}")
        shutil.copy2(source_path, target_dir / name)


def build_server_config(
    *,
    hermes_home: Path,
    python_bin: str,
    mcp_script: Path,
    base_url: str | None,
    gmitm_token: str | None,
    env_inherit: bool,
) -> dict[str, Any]:
    env: dict[str, str] = {
        "PYTHONUNBUFFERED": "1",
        "HERMES_ENV_FILE": os.getenv("HERMES_ENV_FILE", str(hermes_home / ".env")),
        "SEMRUSH_USE_DISPLAY_BROWSER": os.getenv("SEMRUSH_USE_DISPLAY_BROWSER", "1"),
        "SEMRUSH_CDP_URL": os.getenv("SEMRUSH_CDP_URL", "http://127.0.0.1:9222"),
        "SEMRUSH_3UE_STATE_DIR": os.getenv(
            "SEMRUSH_3UE_STATE_DIR",
            str(hermes_home / "semrush-keyword" / "browser-state"),
        ),
    }
    if base_url:
        env["SEMRUSH_3UE_BASE_URL"] = base_url
    if gmitm_token:
        env["SEMRUSH_3UE_GMITM_TOKEN"] = gmitm_token
    elif not env_inherit:
        env["SEMRUSH_3UE_GMITM_TOKEN"] = ""

    return {
        "command": python_bin,
        "args": [str(mcp_script)],
        "env": env,
        "enabled": True,
    }


def register_mcp_server(
    *,
    config_path: Path,
    server_config: dict[str, Any],
    server_name: str = SERVER_NAME,
) -> dict[str, Any]:
    config = load_yaml(config_path)
    mcp_servers = config.get("mcp_servers")
    if not isinstance(mcp_servers, dict):
        mcp_servers = {}
        config["mcp_servers"] = mcp_servers
    mcp_servers[server_name] = server_config
    save_yaml(config_path, config)
    return {
        "config_path": str(config_path),
        "server_name": server_name,
        "server_config": server_config,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install and register Semrush Keyword MCP for Hermes Agent.")
    parser.add_argument("--hermes-home", default=os.getenv("HERMES_HOME") or str(DEFAULT_HERMES_HOME))
    parser.add_argument("--profile", default=os.getenv("HERMES_WEB_UI_PROFILE") or "default")
    parser.add_argument("--python-bin", default=os.getenv("HERMES_PYTHON") or DEFAULT_PYTHON)
    parser.add_argument("--install-dir", default="", help="Default: <HERMES_HOME>/scripts/semrush-keyword")
    parser.add_argument("--proxy-url", default=os.getenv("SEMRUSH_3UE_URL") or "")
    parser.add_argument("--base-url", default=os.getenv("SEMRUSH_3UE_BASE_URL") or "")
    parser.add_argument("--gmitm-token", default=os.getenv("SEMRUSH_3UE_GMITM_TOKEN") or os.getenv("SEMRUSH_3UE_TOKEN") or "")
    parser.add_argument(
        "--no-copy",
        action="store_true",
        help="Register the MCP server against the current script directory instead of copying into HERMES_HOME.",
    )
    parser.add_argument(
        "--require-token",
        action="store_true",
        help="Fail if no 3UE token is provided by args or environment.",
    )
    parser.add_argument(
        "--no-env-inherit",
        action="store_true",
        help="Write an empty SEMRUSH_3UE_GMITM_TOKEN when no token is provided.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        hermes_home = Path(args.hermes_home).expanduser().resolve()
        target_profile_dir = profile_dir(hermes_home, args.profile).resolve()
        install_dir = (
            Path(args.install_dir).expanduser().resolve()
            if args.install_dir
            else hermes_home / "scripts" / "semrush-keyword"
        )
        runtime_dir = script_dir() if args.no_copy else install_dir
        if not args.no_copy:
            copy_scripts(runtime_dir)

        base_url, token = extract_proxy_info(args.proxy_url, args.gmitm_token, args.base_url)
        if args.require_token and not token:
            raise InstallError("No 3UE token provided. Pass --gmitm-token, --proxy-url, or SEMRUSH_3UE_GMITM_TOKEN.")

        mcp_script = runtime_dir / "semrush_keyword_mcp.py"
        server_config = build_server_config(
            hermes_home=hermes_home,
            python_bin=args.python_bin,
            mcp_script=mcp_script,
            base_url=base_url or None,
            gmitm_token=token or None,
            env_inherit=not args.no_env_inherit,
        )
        result = register_mcp_server(
            config_path=target_profile_dir / "config.yaml",
            server_config=server_config,
        )
        result.update(
            {
                "ok": True,
                "profile": args.profile,
                "installed_dir": str(runtime_dir),
                "token_configured": bool(token),
                "next_step": "Reload MCP in Hermes Studio or call POST /api/hermes/mcp/reload?server=semrush-keyword.",
            }
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
