# GitHub Deployment Link

Dokploy deploys this Hermes Studio instance from the forked GitHub repository.

## Repositories

- Deployment fork: `https://github.com/igx-gg/hermes-studio`
- Upstream source: `https://github.com/EKKOLearnAI/hermes-studio`
- Branch: `main`

## Local Remotes

```text
fork    https://github.com/igx-gg/hermes-studio.git
origin  https://github.com/EKKOLearnAI/hermes-studio.git
```

The local `main` branch tracks `fork/main`.

## Deploy Flow

1. Commit changes locally.
2. Push to `fork/main`.
3. Dokploy pulls from `igx-gg/hermes-studio` and redeploys the app.
4. Verify Hermes `/health`, MCP tools, and Temporal connectivity.

## Credentials

No GitHub token or password is stored in this repository.

If push fails, authenticate the local GitHub session as an account with write
access to `igx-gg/hermes-studio`.
