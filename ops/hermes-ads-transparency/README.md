# Hermes Google Ads Transparency Tool

Query Google Ads Transparency Center by domain, website URL, Ads Transparency URL, or advertiser URL.

Examples:

```bash
/opt/hermes/.venv/bin/python /home/agent/.hermes/scripts/google-ads-transparency/google_ads_transparency.py \
  "https://adstransparency.google.com/?region=anywhere&domain=aiimagetovideo.ai" \
  --region anywhere --max-ads 200
```

The tool outputs:

- estimated ad count from Google Ads Transparency Center
- fetched creative count
- advertiser account count
- observed ad group IDs when visible in preview URLs
- product domains per advertiser
- creative list with format, first shown, last shown, days shown, and details URL

Saved JSON runs are written to:

`/home/agent/.hermes/ads-transparency/runs`
