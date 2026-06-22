# Connection Inventory

This is the current connection-persistence inventory for the deployed Hermes
environment.

## Persisted

| Area | Local secret file | Repository doc |
|---|---|---|
| Dokploy | `C:\Users\YI\Documents\Hermes\ops\dokploy\dokploy.env.local` | `docs/ops/dokploy-connection.md` |
| Hermes Agent | `C:\Users\YI\Documents\Hermes\ops\hermes-agent\hermes-agent.env.local` | `docs/ops/hermes-agent-connection.md` |
| Temporal | `C:\Users\YI\Documents\Hermes\ops\temporal\temporal.env.local` | `docs/ops/temporal-connection.md` |
| GitHub deployment | none | `docs/ops/github-deployment.md` |
| MCP/browser runtime | server: `/home/agent/.hermes/.env` | `docs/ops/mcp-runtime.md` |

## Confirmed MCP/Browser Runtime Values

MCP/browser runtime recovery values are persisted locally only:

```text
C:\Users\YI\Documents\Hermes\ops\mcp-runtime\mcp-runtime.env.local
```

Required keys:

```text
SEMRUSH_3UE_USERNAME
SEMRUSH_3UE_PASSWORD
HERMES_VNC_PASSWORD
```

Do not commit these values. x11vnc uses the first 8 characters when generating
its VNC password file, so keep the full source value only in the local ignored
file or the server runtime secret store.

## Still Needs Confirmation Before Full Migration

These values are not fully persisted yet and should be exported from Dokploy or
the running server before a full server migration:

- Temporal PostgreSQL database name, username, password, and volume mapping.
- Hermes persistent volume mapping for `/home/agent/.hermes`.
- Hermes Web UI persistent data mapping for `/home/agent/.hermes-web-ui`.
- Any provider API keys configured only in Dokploy environment variables.

## Verification Order

After migration or redeploy:

1. Open Dokploy.
2. Verify Hermes `/health`.
3. Login to Hermes Agent.
4. Verify `/api/hermes/temporal/status`.
5. Verify MCP server list and per-server tool list.
6. Run one known MCP smoke test, such as Google Trends or Semrush keyword query.
