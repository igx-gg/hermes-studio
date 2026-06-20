# Hermes Google Trends Monitor

This folder contains the scripts installed into the Hermes container under:

`/home/agent/.hermes/scripts/google-trends-monitor`

Files:

- `google_trends_monitor.py`: collects Google Trends scores, stores JSON/CSV history, and prints a Markdown report for Hermes cron output.
- `google_trends_mcp.py`: exposes the monitor as MCP tools for Hermes Agent.
- `keywords.json`: editable keyword root list and defaults.

Default schedule in the deployed Hermes container is `0 1 * * *`, which is 09:00 Asia/Shanghai because the container runs in UTC.
