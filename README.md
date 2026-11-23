<!-- mcp-name: io.github.VinsentY/xbox-mcp -->

# xbox-mcp

[English](README.md) | [简体中文](README.zh-CN.md)

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Model%20Context%20Protocol-green.svg)](https://modelcontextprotocol.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A lightweight, local **Model Context Protocol (MCP)** server that connects directly to **official Microsoft Xbox Live APIs** — no third-party proxy API keys (like OpenXBL), no rate-limit paywalls, and all OAuth tokens stay strictly on your local machine.

Query your **Xbox console & PC Game Pass** game library, exact `MinutesPlayed` playtime, achievements & global rarity percentages, live online presence, friends list, and full playtime summaries right from your AI assistant.

---

## Highlights

- **Direct Official API Access**: Built on [`xbox-webapi`](https://github.com/OpenXbox/xbox-webapi-python) (`TitleHub`, `UserStats`, `Achievements`, `Profile`, `Presence`, `PeopleHub`).
- **Fast Batched Playtime Lookup**: Fetches `MinutesPlayed` in chunks of 50 titles per `userstats/batch` request so even large libraries resolve in ~1–2 seconds.
- **Xbox vs. Win32 Game Bar Separation**: Automatically distinguishes tracked Xbox / PC Game Pass games from third-party PC games (`Win32`) logged by Windows Xbox Game Bar.
- **Zero-Hassle Local Auth**: Supports both one-command CLI browser OAuth (`uv run xbox-auth`) and in-chat callback code exchange (`get_auth_status` + `complete_auth`), with automatic token refresh and `0600` file permissions.
- **Cross-Generation Achievements**: Supports Xbox One / Series X|S / PC achievements (with global unlock rarity percentages) and automatically falls back to Xbox 360 titles.

---

## Requirements

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** (recommended)
- A Microsoft / Xbox account

---

## Quick Start

### 1. Run via `uvx` (Recommended — No Clone Needed)

```bash
# Authenticate once with Microsoft / Xbox Live
uvx --from xbox-mcp xbox-auth

# Run the MCP server
uvx xbox-mcp
```

Or clone locally for development:

```bash
git clone https://github.com/VinsentY/xbox-mcp.git
cd xbox-mcp
uv sync
uv run xbox-auth
```

### 2. Authenticate with Microsoft / Xbox Live (One-Time Setup)

Choose either method:

#### Option A: CLI Auto-Callback (Recommended)

```bash
uv run xbox-auth
```

This starts a temporary local listener on `http://localhost:8080/auth/callback`, opens Microsoft's official OAuth2 sign-in page in your browser, exchanges the authorization code for OAuth2 + XBL + XSTS tokens, and saves them locally with `0600` permissions.

#### Option B: In-Chat / Manual Callback URL

If you prefer not to run a local HTTP listener (or port `8080` is occupied):

1. Ask your AI assistant to call `get_auth_status` — it returns the official Microsoft `login_url`.
2. Sign in in your browser. After consent, the browser redirects to `http://localhost:8080/auth/callback?code=...` (an unreachable localhost page is expected).
3. Copy the full URL from your browser's address bar and pass it to `complete_auth` (or run `uv run xbox-auth --code "<callback_url>"`).

> **Note on Token Storage & Auto-Refresh**
> Tokens are stored locally at `~/Library/Application Support/xbox/tokens.json` on macOS (or `~/.local/share/xbox/tokens.json` on Linux, overrideable via `XBOX_TOKENS_FILE`) with `0600` permissions. `xbox-mcp` automatically refreshes expired access/XSTS tokens and persists rotated refresh tokens back to disk.

---

## MCP Client Configuration

### Antigravity (`~/.gemini/config/mcp_config.json`) / Claude Desktop / Cursor

Using `uvx` (recommended — zero local clone required):

```json
{
  "mcpServers": {
    "xbox": {
      "command": "uvx",
      "args": ["xbox-mcp"],
      "env": {
        "XBOX_LANGUAGE": "en-US"
      }
    }
  }
}
```

Or using a local clone's virtual environment binary:

```json
{
  "mcpServers": {
    "xbox": {
      "command": "/absolute/path/to/xbox-mcp/.venv/bin/xbox-mcp",
      "args": [],
      "env": {
        "XBOX_LANGUAGE": "en-US"
      }
    }
  }
}
```

### Environment Variables (All Optional)

| Variable | Default | Description |
|---|---|---|
| `XBOX_TOKENS_FILE` | OS app data `xbox/tokens.json` | Custom path for local OAuth2 token persistence |
| `XBOX_LANGUAGE` | `en-US` | `Accept-Language` header for titles/achievements (e.g. `zh-CN`, `ja-JP`) |
| `XBOX_CLIENT_ID` | OpenXbox public client ID | Override with your own Azure App Registration Client ID |
| `XBOX_CLIENT_SECRET` | *(empty)* | Optional Azure App Client Secret if using a confidential app |
| `XBOX_REDIRECT_URI` | `http://localhost:8080/auth/callback` | Custom OAuth2 redirect URI matching your app registration |

---

## Available Tools (10)

| Tool | Description |
|---|---|
| `get_auth_status` | Verify local Xbox OAuth token validity; returns the Microsoft login URL if unauthenticated |
| `complete_auth` | Exchange an OAuth callback URL (`http://localhost:8080/auth/callback?code=...`) or raw code and save tokens locally |
| `get_profile` | Fetch Gamertag, Modern Gamertag, Gamerscore, Account Tier, Tenure, Bio, Location, and Avatar |
| `get_presence` | Check online status and currently playing title/device (Xbox console, PC, Cloud) |
| `get_game_library` | Fetch full Xbox / PC Game Pass history enriched with exact `MinutesPlayed`, sortable by `playtime`, `recent`, `achievements`, or `name`, with `platform`, `game_pass_only`, `tracked_only`, and `exclude_win32_footprints` filters |
| `get_recently_played` | Quick view of most recently played titles with playtime and achievement progress |
| `get_playtime_summary` | Aggregate report: total hours, Xbox console vs. PC breakdown, Game Pass share, playtime buckets, 100% completed games, Win32 footprint count, and Top 20 titles |
| `get_game_achievements` | Per-title achievement list with unlock timestamps, Gamerscore, and global rarity percentage (`sort_by`: `default`, `rarity`, `gamerscore`, `unlock_time`) |
| `get_game_stats` | Fetch `MinutesPlayed` and Hero stats for a specific `title_id` or `scid` |
| `get_friends_list` | List Xbox Live friends with Gamertags, Gamerscore, online status, and currently playing game |

---

## Example Prompts

- *"Summarize my Xbox and PC Game Pass playtime and build a gamer profile."*
- *"Show my top 20 most-played Xbox / Game Pass games, excluding Win32 Game Bar footprints."*
- *"What are my rarest unlocked achievements in Clair Obscur: Expedition 33?"*
- *"Compare my Steam library with my Xbox / Game Pass library and find games I've played on both."*
- *"Which of my Xbox friends are online right now and what are they playing?"*

---

## Troubleshooting

- **Passkey interstitial (`account.live.com/interrupt/passkey`) during login**: Click *Skip for now / Cancel* on the Microsoft Passkey prompt, then approve the Xbox Live consent screen until the browser redirects to `http://localhost:8080/auth/callback?code=...`.
- **`account.live.com` connection closed (`ERR_CONNECTION_CLOSED`)**: In regions with unstable routing to Microsoft Live endpoints, make sure `login.live.com`, `account.live.com`, and `*.xboxlive.com` route consistently through your network/proxy.
- **Win32 games showing `0m` / `null` playtime**: Windows Xbox Game Bar automatically records non-Xbox PC games (e.g., Steam, Riot, Battle.net titles) in TitleHub without `MinutesPlayed` telemetry. Pass `exclude_win32_footprints=true` or `tracked_only=true` to `get_game_library` to focus purely on Xbox / Game Pass titles.

---

## Development & Tests

```bash
uv sync
uv run python -m unittest discover -s tests -v
```

---

## Security & Privacy

- OAuth2 tokens are stored **only on your local machine** with `0600` file permissions and are never sent to any third-party service.
- `.gitignore` excludes `tokens.json`, `*tokens*.json`, and `.env*` by default.
- Never commit your local `tokens.json` file to version control.

## License

[MIT](LICENSE)
