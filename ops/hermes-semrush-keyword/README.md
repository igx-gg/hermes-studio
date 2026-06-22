# Hermes Semrush Keyword Tool

Query Semrush Keyword Overview through the 3UE relay.

3UE relay access is session-bound. A `__gmitm` token copied from a local
browser is usually not enough for a remote Hermes server, because the relay also
checks the server-side browser cookies/session. The stable mode is therefore:

`Hermes Agent -> semrush-keyword MCP -> server-side CloakBrowser over CDP -> 3UE/Semrush`

By default the MCP server connects to the visible server-side browser at
`http://127.0.0.1:9222`. That browser is kept alive by the display watchdog and
uses the persistent profile under:

`/home/agent/.hermes/semrush-keyword/browser-state/profile`

The manual login fallback is still available:

1. `prepare_semrush_3ue_login_tool(wait_seconds=300, headless=false)`
2. Complete the 3UE login in the Hermes server-side CloakBrowser before the wait
   window expires.
3. Run `query_semrush_keyword_tool(keyword="image", database="us")`.

The server-side login state is saved under:

`/home/agent/.hermes/semrush-keyword/browser-state`

## Register with server-side Hermes Agent

Run this inside the Hermes server/container:

```bash
/opt/hermes/.venv/bin/python /app/ops/hermes-semrush-keyword/install_semrush_keyword_mcp.py \
  --profile default \
  --proxy-url "https://sem.3ue.co/home/?__gmitm=..."
```

The installer copies the scripts to:

`/home/agent/.hermes/scripts/semrush-keyword`

and writes this MCP server into the selected profile's `config.yaml`:

```yaml
mcp_servers:
  semrush-keyword:
    command: /opt/hermes/.venv/bin/python
    args:
      - /home/agent/.hermes/scripts/semrush-keyword/semrush_keyword_mcp.py
    env:
      PYTHONUNBUFFERED: "1"
      HERMES_ENV_FILE: /home/agent/.hermes/.env
      SEMRUSH_USE_DISPLAY_BROWSER: "1"
      SEMRUSH_CDP_URL: http://127.0.0.1:9222
      SEMRUSH_3UE_STATE_DIR: /home/agent/.hermes/semrush-keyword/browser-state
    enabled: true
```

After registration, reload MCP from Hermes Studio's MCP manager, or call the
authenticated Web UI API:

```bash
curl -X POST "http://127.0.0.1:6060/api/hermes/mcp/reload?server=semrush-keyword"
```

Hermes Agent can then call:

`query_semrush_keyword_tool(keyword="image", database="us")`

For actual backlink source pages, call:

`query_semrush_backlinks_tool(target="ezbuff.com", search_type="domain", row_limit=0, dedupe_by_domain=true, output_format="json")`

Backlink results default to source-domain deduplication. If multiple backlinks
come from the same source domain, only the first collected source page is kept.
Use `row_limit=0` to return all deduped rows from the collected pages. Use
`page_limit=0` to keep paging until Semrush no longer exposes a next page, or
set a small number such as `page_limit=5` for a faster sample.

If the server-side 3UE session is not ready yet, call:

`prepare_semrush_3ue_login_tool(wait_seconds=300, headless=false)`

The stable server-browser mode does not need a copied local `__gmitm` token.
If you need the older direct-token fallback, set `SEMRUSH_3UE_GMITM_TOKEN` in
the server environment and run the installer with `--proxy-url` or
`--gmitm-token`.

Example:

```bash
SEMRUSH_3UE_GMITM_TOKEN="..." \
/opt/hermes/.venv/bin/python /home/agent/.hermes/scripts/semrush-keyword/semrush_keyword.py \
  "image" --database us
```

You can also pass a current relay URL and let the tool extract `__gmitm`:

```bash
/opt/hermes/.venv/bin/python /home/agent/.hermes/scripts/semrush-keyword/semrush_keyword.py \
  "image" --proxy-url "https://sem.3ue.co/home/?__gmitm=..."
```

The tool outputs:

- search volume
- keyword difficulty
- global volume and country volume split
- intent, CPC, and competition
- keyword variations
- question keywords
- keyword strategy clusters

Saved JSON runs are written to:

`/home/agent/.hermes/semrush-keyword/runs`

## Keep noVNC display alive

The Semrush login helper needs a server-side browser that stays visible through
noVNC. To keep the display from becoming black or losing the browser window,
install and start the watchdog on the Hermes server:

```bash
/home/agent/.hermes/scripts/semrush-keyword/start_display_watchdog.sh
```

The watchdog keeps `Xvfb :99`, Openbox, visible Chromium, `x11vnc`, and
`websockify` alive. Chromium is launched with software rendering flags to avoid
GPU crashes in headless server environments.

Secrets used by the display helper should live in:

`/home/agent/.hermes/.env`

Supported keys include:

```bash
HERMES_WEBUI_USERNAME=
HERMES_WEBUI_PASSWORD=
HERMES_VNC_PASSWORD=
SEMRUSH_USE_DISPLAY_BROWSER=1
SEMRUSH_CDP_URL=http://127.0.0.1:9222
SEMRUSH_3UE_STATE_DIR=/home/agent/.hermes/semrush-keyword/browser-state
SEMRUSH_3UE_USERNAME=
SEMRUSH_3UE_PASSWORD=
```

`HERMES_VNC_PASSWORD` is converted into the x11vnc password file automatically
by the watchdog. VNC only uses the first 8 characters of the password.
`SEMRUSH_3UE_USERNAME` and `SEMRUSH_3UE_PASSWORD` let the Semrush helper fill
the 3UE login page automatically when the server-side session expires.
