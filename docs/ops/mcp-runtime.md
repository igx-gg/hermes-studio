# MCP Runtime Connections

Hermes Agent uses several MCP servers for SEO, ads-library, trends, browser,
and internal Web UI automation.

## Known MCP Servers

- `hermes-studio-api`
- `hermes-studio-use`
- `hermes-studio-devices`
- `google-trends-cloak`
- `meta-ads-library`
- `semrush-keyword`
- `google-ads-transparency`

Verify with:

```text
/api/hermes/mcp/servers
/api/hermes/mcp/tools
```

Reload with:

```text
/api/hermes/mcp/reload
```

## Runtime Paths

These paths are inside the deployed Hermes container/server:

```text
/home/agent/.hermes/scripts/google-trends-monitor
/home/agent/.hermes/scripts/semrush-keyword
/home/agent/.hermes/semrush-keyword/browser-state
/home/agent/.hermes/semrush-keyword/runs
/home/agent/.hermes/trends
/home/agent/.hermes/.env
```

## Semrush Browser/CDP

Semrush uses a server-side CloakBrowser/Chromium session:

```text
SEMRUSH_USE_DISPLAY_BROWSER=1
SEMRUSH_CDP_URL=http://127.0.0.1:9222
SEMRUSH_3UE_STATE_DIR=/home/agent/.hermes/semrush-keyword/browser-state
```

The 3UE/Semrush and VNC recovery values are stored only in the local ignored
runtime file:

```text
C:\Users\YI\Documents\Hermes\ops\mcp-runtime\mcp-runtime.env.local
```

Required keys:

```text
SEMRUSH_3UE_USERNAME
SEMRUSH_3UE_PASSWORD
HERMES_VNC_PASSWORD
```

Note: x11vnc stores only the first 8 characters in the generated VNC password
file. Do not commit the source value or generated VNC password hash.

## Migration Notes

- Restore `/home/agent/.hermes` to preserve scripts, MCP config, skills,
  sessions, trends history, and browser state.
- Verify `cloakbrowser` and `playwright` are installed in `/opt/hermes/.venv`.
- Verify each MCP server can list tools after migration.
