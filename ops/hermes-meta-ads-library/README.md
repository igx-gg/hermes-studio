# Hermes Meta Ads Library Tool

Query Meta Ads Library with CloakBrowser.

Example:

```bash
/opt/hermes/.venv/bin/python /home/agent/.hermes/scripts/meta-ads-library/meta_ads_library.py \
  "https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=ALL&is_targeted_country=false&media_type=all&q=%22baloogames%22&search_type=keyword_exact_phrase"
```

Output includes:

- displayed result count
- loaded ad card count
- advertiser/page account count
- Library IDs
- destination domains
- account/page summaries
- ad list

Meta public Ads Library pages do not expose internal campaign/ad set/ad group IDs.
