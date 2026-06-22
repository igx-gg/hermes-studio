# Temporal Connection

Hermes is connected to Temporal for workflow state, scheduling, retries, and UI
inspection.

## Endpoints

- Temporal UI: `http://temporal-ui-temporal-stack-nblkeh-32-192-57-245.sslip.io/`
- Hermes status endpoint: `/api/hermes/temporal/status`
- Internal Temporal address: `temporal-server:7233`
- Namespace: `default`
- Task queue: `hermes-default`

## Credentials

Do not commit Temporal UI credentials or database passwords to this repository.

On the current workstation, the local-only credential file is:

```text
C:\Users\YI\Documents\Hermes\ops\temporal\temporal.env.local
```

That file contains the Temporal UI basic-auth credentials and the Hermes
Temporal runtime settings.

## Hermes Environment

Hermes should keep these variables configured in Dokploy:

```text
TEMPORAL_ADDRESS=temporal-server:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_TASK_QUEUE=hermes-default
```

## Migration Notes

- Restore the Temporal PostgreSQL volume before starting Temporal Server on a
  new host.
- Recreate the Temporal Server and Temporal UI services in Dokploy.
- Reapply UI basic auth.
- Reapply Hermes Temporal environment variables.
- Verify from Hermes through `/api/hermes/temporal/status`.

The Temporal PostgreSQL database name, username, and password should be
reconfirmed from Dokploy before a full server migration.
