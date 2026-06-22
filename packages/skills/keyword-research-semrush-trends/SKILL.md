---
name: keyword-research-semrush-trends
description: Research SEO keywords with both Semrush Keyword Overview through the semrush-keyword MCP server and Google Trends through the google-trends-cloak MCP server. Use when the user asks to query, analyze, compare, or research a keyword, SEO keyword, search volume, keyword difficulty, CPC, intent, trend, rising demand, Google Trends signal, or Semrush data; also trigger for Chinese requests such as "查询关键词", "关键词研究", "查一下某个词", "看趋势", or "Semrush + Google Trends".
keywords:
  - keyword
  - keywords
  - keyword research
  - seo keyword
  - semrush
  - semrush keyword
  - google trends
  - search volume
  - keyword difficulty
  - CPC
  - intent
  - 关键词
  - 查询关键词
  - 关键词查询
  - 关键词研究
  - 关键词情况
  - 搜索量
  - 关键词难度
  - 谷歌趋势
  - 趋势
---

# Keyword Research Semrush Trends

Use this skill to turn a user keyword request into a combined Semrush + Google Trends report.

## Required MCP Tools

Use these MCP servers when they are connected:

- `semrush-keyword`
  - Query tool: `mcp_semrush_keyword_query_semrush_keyword_tool`
  - Login preparation fallback: `mcp_semrush_keyword_prepare_semrush_3ue_login_tool`
- `google-trends-cloak`
  - Trends collection tool: `mcp_google_trends_cloak_monitor_google_trends`
  - History tool, only when needed: `mcp_google_trends_cloak_read_google_trends_history`

If the exact registered tool name differs, find the matching tool by server and base function name.

## Defaults

- Semrush database: `us`
- Semrush device: `desktop`
- Semrush wait: `45000` ms
- Semrush output format: `json` when you need to merge fields; `markdown` when the user only wants a readable report.
- Semrush auth mode: use the server-side persisted CloakBrowser session through the `semrush-keyword` MCP. Do not ask the user for a local `__gmitm` token or browser cookie.
- Semrush query flags: pass `auto_login=true`, `headless=true`, and leave `gmitm_token` empty unless the user explicitly provides a relay token for a one-off fallback.
- Google Trends geo: `US`
- Google Trends timeframe: `now 7-d`
- Google Trends cloak: `true`
- Keep the user's original keyword text exactly, except trim surrounding whitespace.

If the user specifies a country or market, map it consistently:

- Semrush uses lowercase databases such as `us`, `uk`, `ca`, `au`, `de`, `fr`, `jp`.
- Google Trends uses uppercase geo codes such as `US`, `GB`, `CA`, `AU`, `DE`, `FR`, `JP`.

## Workflow

1. Extract the primary keyword from the user request.
2. If the request includes comparison keywords, query each keyword separately in both tools.
3. Call Semrush first:
   - Use `mcp_semrush_keyword_query_semrush_keyword_tool`.
   - Pass `keyword`, `database`, `device`, `wait_ms`, `list_limit=10`, `auto_login=true`, `headless=true`, and `output_format=json`.
   - Rely on the MCP server's persisted display-browser/CDP mode. It connects to the server-side CloakBrowser that is already logged into 3UE/Semrush.
4. If Semrush says 3UE login is required:
   - Call `mcp_semrush_keyword_prepare_semrush_3ue_login_tool` with `wait_seconds=1800` and `headless=false`.
   - Tell the user to complete 3UE login in the server noVNC browser.
   - Retry the Semrush query after login is ready.
5. Call Google Trends:
   - Use `mcp_google_trends_cloak_monitor_google_trends`.
   - Pass `keywords=[keyword]`, `geo`, `timeframe`, and `use_cloak=true`.
6. Combine both outputs into one concise keyword brief.

## Report Format

Return a compact report with these sections:

1. Semrush summary: volume, global volume, keyword difficulty, KD label, intent, CPC, competition, data date.
2. Google Trends summary: latest score, short-term average, 7-day vs 30-day movement if available, and any errors.
3. Keyword ideas: top Semrush variations and questions, limited to 5 each unless the user asks for more.
4. Interpretation: explain whether the keyword is attractive, competitive, seasonal, rising, or saturated.
5. Next actions: suggest 2-4 practical SEO actions, such as content angle, cluster opportunity, comparison query, or long-tail target.

When data is missing from one tool, still report the other tool and clearly mark the missing source.

## Output Rules

- Do not claim live trend movement unless Google Trends returned it.
- Do not expose login tokens, `__gmitm` tokens, cookies, or raw credentials.
- Mention saved Semrush JSON paths when the Semrush tool returns `output_path`.
- Keep Chinese user requests answered in Chinese unless the user asks otherwise.
