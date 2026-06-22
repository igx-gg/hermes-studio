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
| MCP/browser runtime | none | `docs/ops/mcp-runtime.md` |

## Still Needs Confirmation Before Full Migration

These values are not fully persisted yet and should be exported from Dokploy or
the running server before a full server migration:

- Temporal PostgreSQL database name, username, password, and volume mapping.
- Hermes persistent volume mapping for `/home/agent/.hermes`.
- Hermes Web UI persistent data mapping for `/home/agent/.hermes-web-ui`.
- 3UE/Semrush credentials, if automatic login recovery is required.
- VNC/noVNC credentials, if the server-side browser display needs direct access.
- Any provider API keys configured only in Dokploy environment variables.

## Verification Order

After migration or redeploy:

1. Open Dokploy.
2. Verify Hermes `/health`.
3. Login to Hermes Agent.
4. Verify `/api/hermes/temporal/status`.
5. Verify MCP server list and per-server tool list.
6. Run one known MCP smoke test, such as Google Trends or Semrush keyword query.
