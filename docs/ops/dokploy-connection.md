# Dokploy Connection

This project is currently deployed through Dokploy.

## Dashboard

- Dokploy URL: `http://32.192.57.245:3000/`
- Deployment repository: `https://github.com/igx-gg/hermes-studio`
- Branch: `main`
- Hermes public URL: `http://hermes-studio-hermes-webui-om9sur-c8d2e3-32-192-57-245.sslip.io/`
- Temporal UI URL: `http://temporal-ui-temporal-stack-nblkeh-32-192-57-245.sslip.io/`

## Credentials

Do not commit Dokploy credentials to this repository.

On the current workstation, the local-only credential file is:

```text
C:\Users\YI\Documents\Hermes\ops\dokploy\dokploy.env.local
```

That file contains `DOKPLOY_URL`, `DOKPLOY_EMAIL`, and `DOKPLOY_PASSWORD`.

## Operating Notes

- Use Dokploy to redeploy Hermes after pushing changes to `igx-gg/hermes-studio`.
- Keep runtime secrets and admin passwords in Dokploy environment variables or
  local ignored files only.
- If this repository is migrated to another server, recreate the Dokploy app
  from the forked GitHub repository and restore the persistent volumes for
  Hermes data, Temporal PostgreSQL, and any MCP browser state.
