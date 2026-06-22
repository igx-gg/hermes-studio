#!/usr/bin/env python3
"""Keep the Hermes server-side browser display available for noVNC.

This script is intentionally self-contained because it runs inside the remote
Hermes container, where systemd may not be available. It keeps these pieces up:

- Xvfb display :99
- Openbox window manager
- visible Chromium on the 3UE login/dashboard page
- x11vnc on 127.0.0.1:5900
- websockify/noVNC on 0.0.0.0:6080
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
from pathlib import Path


ENV_PATH = Path(os.getenv("HERMES_ENV_FILE", "/home/agent/.hermes/.env"))
DISPLAY = os.getenv("HERMES_DISPLAY", ":99")
SCREEN = os.getenv("HERMES_DISPLAY_SCREEN", "1600x1000x24")
BASE_DIR = Path(os.getenv("HERMES_DISPLAY_DIR", "/home/agent/.hermes/display"))
STATE_DIR = Path(os.getenv("SEMRUSH_3UE_STATE_DIR", "/home/agent/.hermes/semrush-keyword/browser-state"))
PROFILE_DIR = STATE_DIR / "profile"
LOG_DIR = BASE_DIR / "logs"
VNC_PASS = BASE_DIR / "vnc.pass"
URL = os.getenv("HERMES_3UE_URL", "https://dash.3ue.co/zh-Hans/#/page/m/home")
CHROME_GLOB = "/home/agent/.cloakbrowser/chromium-*/chrome"


def load_dotenv(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def ensure_dirs() -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    Path("/tmp/hermes-runtime-root").mkdir(parents=True, exist_ok=True)


def sh(command: str, *, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        shell=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    )


def pgrep(pattern: str) -> bool:
    return sh(f"pgrep -f {quote(pattern)} >/dev/null 2>&1").returncode == 0


def quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def start_detached(name: str, command: str) -> None:
    log_path = LOG_DIR / f"{name}.log"
    with log_path.open("ab", buffering=0) as log:
        subprocess.Popen(
            ["bash", "-lc", f"exec {command}"],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
            close_fds=True,
        )


def latest_chrome() -> str:
    result = sh(f"ls -1 {CHROME_GLOB} 2>/dev/null | tail -1")
    path = result.stdout.strip()
    if not path:
        raise RuntimeError("CloakBrowser Chromium binary was not found")
    return path


def ensure_vnc_password() -> None:
    password = os.getenv("HERMES_VNC_PASSWORD") or os.getenv("VNC_PASSWORD") or ""
    if not password:
        return
    sh(f"x11vnc -storepasswd {quote(password[:8])} {quote(str(VNC_PASS))} >/dev/null 2>&1 || true")
    try:
        VNC_PASS.chmod(0o600)
    except OSError:
        pass


def ensure_xvfb() -> None:
    if pgrep(f"Xvfb {DISPLAY}"):
        return
    start_detached("xvfb", f"Xvfb {quote(DISPLAY)} -screen 0 {quote(SCREEN)} -ac +extension RANDR")
    time.sleep(1.5)


def ensure_openbox() -> None:
    if pgrep("openbox"):
        return
    start_detached("openbox", f"env DISPLAY={quote(DISPLAY)} openbox")
    time.sleep(1)


def ensure_chrome() -> None:
    if pgrep("remote-debugging-port=9222") and port_open("127.0.0.1", 9222):
        return
    sh("pkill -9 -f 'remote-debugging-port=9222' 2>/dev/null || true")
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        try:
            (PROFILE_DIR / name).unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
    chrome = latest_chrome()
    start_detached(
        "chrome",
        " ".join(
            [
                "env",
                f"DISPLAY={quote(DISPLAY)}",
                "XDG_RUNTIME_DIR=/tmp/hermes-runtime-root",
                "NO_AT_BRIDGE=1",
                quote(chrome),
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-setuid-sandbox",
                "--no-first-run",
                "--no-default-browser-check",
                "--password-store=basic",
                "--use-mock-keychain",
                "--ozone-platform=x11",
                "--disable-gpu",
                "--disable-gpu-compositing",
                "--disable-accelerated-2d-canvas",
                "--disable-accelerated-video-decode",
                "--disable-vulkan",
                "--enable-unsafe-swiftshader",
                "--use-gl=swiftshader",
                "--disable-features=Vulkan,UseSkiaRenderer,CanvasOopRasterization",
                f"--user-data-dir={quote(str(PROFILE_DIR))}",
                "--remote-debugging-address=127.0.0.1",
                "--remote-debugging-port=9222",
                "--window-size=1360,900",
                "--window-position=40,40",
                "--new-window",
                quote(URL),
            ]
        ),
    )
    time.sleep(4)


def ensure_x11vnc() -> None:
    if pgrep("x11vnc -display :99") and port_open("127.0.0.1", 5900):
        return
    sh("pkill -9 -f 'x11vnc -display :99' 2>/dev/null || true")
    auth = f"-rfbauth {quote(str(VNC_PASS))}" if VNC_PASS.exists() else "-nopw"
    start_detached(
        "x11vnc",
        " ".join(
            [
                "x11vnc",
                f"-display {quote(DISPLAY)}",
                "-forever",
                "-shared",
                auth,
                "-listen 127.0.0.1",
                "-rfbport 5900",
                "-xkb",
                "-noxrecord",
                "-noxfixes",
                "-noxdamage",
                "-ncache 0",
                "-repeat",
                "-wait 10",
                "-defer 10",
                f"-o {quote(str(LOG_DIR / 'x11vnc-runtime.log'))}",
            ]
        ),
    )
    time.sleep(1)


def ensure_websockify() -> None:
    if pgrep("websockify --web=/usr/share/novnc") and port_open("127.0.0.1", 6080):
        return
    sh("pkill -9 -f 'websockify --web=/usr/share/novnc' 2>/dev/null || true")
    start_detached("websockify", "websockify --web=/usr/share/novnc 0.0.0.0:6080 127.0.0.1:5900")
    time.sleep(1)


def write_heartbeat() -> None:
    (BASE_DIR / "watchdog.heartbeat").write_text(str(int(time.time())), encoding="utf-8")


def once() -> None:
    load_dotenv()
    ensure_dirs()
    ensure_vnc_password()
    ensure_xvfb()
    ensure_openbox()
    sh(f"DISPLAY={quote(DISPLAY)} xsetroot -solid '#303030' 2>/dev/null || true")
    ensure_chrome()
    ensure_x11vnc()
    ensure_websockify()
    write_heartbeat()


def main() -> int:
    stop = False

    def handle_stop(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)
    while not stop:
        try:
            once()
        except Exception as exc:
            ensure_dirs()
            with (LOG_DIR / "watchdog-error.log").open("a", encoding="utf-8") as log:
                log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {exc!r}\n")
        time.sleep(15)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
