# Hermes Agent Connection

This project is connected to a deployed Hermes Studio instance.

## Web UI

- Hermes URL: `http://hermes-studio-hermes-webui-om9sur-c8d2e3-32-192-57-245.sslip.io/`
- Default profile: `default`
- Default model: `glm-5.2`
- Default provider: `zai`

## Credentials

Do not commit Hermes admin credentials or bearer tokens to this repository.

On the current workstation, the local-only credential file is:

```text
C:\Users\YI\Documents\Hermes\ops\hermes-agent\hermes-agent.env.local
```

That file contains `HERMES_BASE_URL`, `HERMES_ADMIN_USERNAME`,
`HERMES_ADMIN_PASSWORD`, the default profile/model values, and common endpoint
URLs.

## API Flow

1. Login with `POST /api/auth/login`.
2. Use the returned token as `Authorization: Bearer <token>`.
3. Run one-shot Agent tasks with `POST /api/chat-run/runs`.
4. For streaming tasks, connect Socket.IO to `/chat-run` with the same token
   and `profile=default`.

## Common Endpoints

- Health: `/health`
- Login: `/api/auth/login`
- One-shot Agent run: `/api/chat-run/runs`
- MCP servers: `/api/hermes/mcp/servers`
- MCP tools: `/api/hermes/mcp/tools`
- MCP reload: `/api/hermes/mcp/reload`
- Temporal status: `/api/hermes/temporal/status`
- Available models: `/api/hermes/available-models`
- Sessions: `/api/hermes/sessions/conversations`

## One-Shot Run Payload

```json
{
  "input": "Run the requested Hermes Agent task here.",
  "session_id": "stable-session-id",
  "profile": "default",
  "include_events": true,
  "timeout_ms": 600000
}
```

## Migration Notes

- Restore Hermes persistent data before expecting old skills, sessions, MCP
  server config, browser state, or credentials to work.
- Verify MCP server health after migration through `/api/hermes/mcp/servers`
  and per-server `/test` endpoints.
- Verify Temporal connectivity through `/api/hermes/temporal/status`.
