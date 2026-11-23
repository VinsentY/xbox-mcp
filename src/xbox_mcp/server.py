"""MCP Server for official Microsoft Xbox Live APIs."""

from __future__ import annotations

import json
import logging
from typing import Any, Literal, Optional

import httpx
from mcp.server.mcpserver import MCPServer

from .auth import (
    AuthRequiredError,
    exchange_code_and_save,
    generate_auth_url,
    get_tokens_path,
    get_xbox_client,
)
from .client import (
    fetch_enriched_library,
    fetch_friends,
    fetch_game_achievements,
    fetch_game_stats,
    fetch_presence,
    fetch_profile,
    format_minutes,
    resolve_xuid,
)

mcp = MCPServer(
    name="xbox-mcp",
    title="Xbox Live MCP",
    version="0.1.0",
    description=(
        "Local MCP server connecting directly to official Microsoft Xbox Live APIs "
        "for Xbox & PC Game Pass playtime, achievements, rarity, presence, and friends."
    ),
    website_url="https://github.com/VinsentY/xbox-mcp",
    instructions=(
        "Local MCP Server connecting directly to official Microsoft Xbox Live APIs. "
        "Use `get_auth_status` first if authentication fails, or `complete_auth` with the Microsoft OAuth redirect URL/code."
    ),
)


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _auth_error_payload(err: AuthRequiredError) -> str:
    return _json(
        {
            "authenticated": False,
            "error": str(err),
            "tokens_path": str(get_tokens_path()),
            "login_url": generate_auth_url(),
            "how_to_authenticate": [
                "Option 1 (CLI): Run `uv run xbox-auth` inside the xbox-mcp directory and sign in via browser.",
                "Option 2 (In-chat): Open `login_url` in your browser, sign in with your Microsoft/Xbox account, copy the redirected `http://localhost:8080/auth/callback?code=...` URL from the address bar, and pass it to `complete_auth`.",
            ],
        }
    )


def _api_error_payload(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return _json(
            {
                "error": f"Xbox Live API HTTP {exc.response.status_code}",
                "detail": exc.response.text[:300] or str(exc),
            }
        )
    return _json({"error": str(exc)})


@mcp.tool()
async def get_auth_status() -> str:
    """Check whether Xbox Live OAuth tokens exist locally and are valid. If not, returns the Microsoft login URL."""
    try:
        async with get_xbox_client() as client:
            profile = await fetch_profile(client)
            return _json(
                {
                    "authenticated": True,
                    "tokens_path": str(get_tokens_path()),
                    "xuid": profile["xuid"],
                    "gamertag": profile["gamertag"],
                    "unique_modern_gamertag": profile["unique_modern_gamertag"],
                    "gamerscore": profile["gamerscore"],
                }
            )
    except AuthRequiredError as err:
        return _auth_error_payload(err)
    except Exception as exc:
        return _api_error_payload(exc)


@mcp.tool()
async def complete_auth(callback_url_or_code: str) -> str:
    """Complete Microsoft Xbox Live OAuth2 login by exchanging a redirected callback URL (http://localhost:8080/auth/callback?code=...) or raw authorization code and saving tokens locally."""
    try:
        result = await exchange_code_and_save(callback_url_or_code)
        return _json(result)
    except Exception as exc:
        return _json({"authenticated": False, "error": str(exc)})


@mcp.tool()
async def get_profile(
    gamertag: Optional[str] = None,
    xuid: Optional[str] = None,
) -> str:
    """Get Xbox Live profile information (Gamertag, Gamerscore, Account Tier, Tenure, Bio, Location). Defaults to the authenticated user."""
    try:
        async with get_xbox_client() as client:
            data = await fetch_profile(client, xuid=xuid, gamertag=gamertag)
            return _json(data)
    except AuthRequiredError as err:
        return _auth_error_payload(err)
    except Exception as exc:
        return _api_error_payload(exc)


@mcp.tool()
async def get_presence(
    gamertag: Optional[str] = None,
    xuid: Optional[str] = None,
) -> str:
    """Get Xbox Live online status and currently playing game/device (Xbox console, PC, Cloud). Defaults to the authenticated user."""
    try:
        async with get_xbox_client() as client:
            data = await fetch_presence(client, xuid=xuid, gamertag=gamertag)
            return _json(data)
    except AuthRequiredError as err:
        return _auth_error_payload(err)
    except Exception as exc:
        return _api_error_payload(exc)


@mcp.tool()
async def get_game_library(
    gamertag: Optional[str] = None,
    xuid: Optional[str] = None,
    sort_by: Literal["playtime", "recent", "achievements", "name"] = "playtime",
    platform: Literal["all", "xbox", "pc"] = "all",
    game_pass_only: bool = False,
    tracked_only: bool = False,
    exclude_win32_footprints: bool = False,
    games_only: bool = True,
    include_detail: bool = False,
    limit: int = 100,
) -> str:
    """Get full Xbox / PC Game Pass game history enriched with exact MinutesPlayed playtime and achievement stats. Set `exclude_win32_footprints=True` to hide third-party Win32 PC games detected by Windows Game Bar."""
    try:
        async with get_xbox_client() as client:
            target_xuid = await resolve_xuid(client, xuid=xuid, gamertag=gamertag)
            titles = await fetch_enriched_library(
                client,
                xuid=target_xuid,
                games_only=games_only,
                max_items=1000,
                include_detail=include_detail,
            )

            if exclude_win32_footprints:
                titles = [t for t in titles if not t["is_win32_footprint"]]

            if tracked_only:
                titles = [t for t in titles if (t["playtime_minutes"] or 0) > 0]

            if platform == "xbox":
                titles = [t for t in titles if t["is_xbox_console"]]
            elif platform == "pc":
                titles = [t for t in titles if t["is_pc"]]

            if game_pass_only:
                titles = [t for t in titles if t["is_game_pass"]]

            if sort_by == "playtime":
                titles.sort(
                    key=lambda t: (
                        t["playtime_minutes"] if t["playtime_minutes"] is not None else -1,
                        t["last_played"] or "",
                    ),
                    reverse=True,
                )
            elif sort_by == "recent":
                titles.sort(key=lambda t: t["last_played"] or "", reverse=True)
            elif sort_by == "achievements":
                titles.sort(
                    key=lambda t: (
                        t["achievement_progress_percent"] or 0,
                        t["gamerscore_earned"] or 0,
                    ),
                    reverse=True,
                )
            elif sort_by == "name":
                titles.sort(key=lambda t: (t["name"] or "").lower())

            total_count = len(titles)
            total_minutes = sum(t["playtime_minutes"] or 0 for t in titles)
            clamped_limit = max(1, min(limit, 500))
            shown = titles[:clamped_limit]

            return _json(
                {
                    "xuid": target_xuid,
                    "total_titles": total_count,
                    "showing": len(shown),
                    "total_playtime_hours": round(total_minutes / 60, 1),
                    "total_playtime_formatted": format_minutes(total_minutes),
                    "titles_with_playtime": sum(
                        1 for t in titles if (t["playtime_minutes"] or 0) > 0
                    ),
                    "win32_gamebar_footprints": sum(
                        1 for t in titles if t["is_win32_footprint"]
                    ),
                    "games": shown,
                }
            )
    except AuthRequiredError as err:
        return _auth_error_payload(err)
    except Exception as exc:
        return _api_error_payload(exc)


@mcp.tool()
async def get_recently_played(
    gamertag: Optional[str] = None,
    xuid: Optional[str] = None,
    exclude_win32_footprints: bool = False,
    limit: int = 20,
) -> str:
    """Get the most recently played Xbox / PC Game Pass games with exact playtime, last played timestamp, and achievement progress."""
    return await get_game_library(
        gamertag=gamertag,
        xuid=xuid,
        sort_by="recent",
        exclude_win32_footprints=exclude_win32_footprints,
        limit=max(1, min(limit, 100)),
    )


@mcp.tool()
async def get_playtime_summary(
    gamertag: Optional[str] = None,
    xuid: Optional[str] = None,
) -> str:
    """Compute an aggregate playtime, platform split (Xbox console vs PC), Game Pass share, gamerscore, Win32 footprint count, and top games summary across the entire Xbox library."""
    try:
        async with get_xbox_client() as client:
            target_xuid = await resolve_xuid(client, xuid=xuid, gamertag=gamertag)
            profile = await fetch_profile(client, xuid=target_xuid)
            titles = await fetch_enriched_library(
                client, xuid=target_xuid, games_only=True, max_items=1000
            )

            win32_footprints = [t for t in titles if t["is_win32_footprint"]]
            xbox_titles = [t for t in titles if not t["is_win32_footprint"]]

            total_minutes = sum(t["playtime_minutes"] or 0 for t in xbox_titles)
            pc_minutes = sum(
                t["playtime_minutes"] or 0 for t in xbox_titles if t["is_pc"]
            )
            console_minutes = sum(
                t["playtime_minutes"] or 0 for t in xbox_titles if t["is_xbox_console"]
            )
            gp_titles = [t for t in xbox_titles if t["is_game_pass"]]
            gp_minutes = sum(t["playtime_minutes"] or 0 for t in gp_titles)

            buckets = {
                "100h+": sum(1 for t in xbox_titles if (t["playtime_minutes"] or 0) >= 6000),
                "50-100h": sum(
                    1 for t in xbox_titles if 3000 <= (t["playtime_minutes"] or 0) < 6000
                ),
                "20-50h": sum(
                    1 for t in xbox_titles if 1200 <= (t["playtime_minutes"] or 0) < 3000
                ),
                "5-20h": sum(
                    1 for t in xbox_titles if 300 <= (t["playtime_minutes"] or 0) < 1200
                ),
                "1m-5h": sum(
                    1 for t in xbox_titles if 0 < (t["playtime_minutes"] or 0) < 300
                ),
                "0m_or_untracked": sum(
                    1 for t in xbox_titles if not t["playtime_minutes"]
                ),
            }

            by_playtime = sorted(
                xbox_titles,
                key=lambda t: t["playtime_minutes"] or 0,
                reverse=True,
            )
            completed_100 = [
                {
                    "name": t["name"],
                    "title_id": t["title_id"],
                    "playtime_formatted": t["playtime_formatted"],
                    "gamerscore_earned": t["gamerscore_earned"],
                }
                for t in by_playtime
                if (t["achievement_progress_percent"] or 0) >= 100
                and (t["achievements_total"] or 0) > 0
            ]

            return _json(
                {
                    "profile": {
                        "xuid": profile["xuid"],
                        "gamertag": profile["gamertag"],
                        "gamerscore": profile["gamerscore"],
                        "tenure_years": profile["tenure_years"],
                    },
                    "total_titles_in_history": len(titles),
                    "xbox_ecosystem_games": len(xbox_titles),
                    "games_with_tracked_playtime": sum(
                        1 for t in xbox_titles if (t["playtime_minutes"] or 0) > 0
                    ),
                    "win32_gamebar_footprints": len(win32_footprints),
                    "total_playtime_hours": round(total_minutes / 60, 1),
                    "total_playtime_formatted": format_minutes(total_minutes),
                    "platform_playtime_hours": {
                        "xbox_console_hours": round(console_minutes / 60, 1),
                        "pc_hours": round(pc_minutes / 60, 1),
                        "note": "Cross-platform titles played on both Xbox and PC count in both platform totals.",
                    },
                    "game_pass": {
                        "titles_count": len(gp_titles),
                        "playtime_hours": round(gp_minutes / 60, 1),
                    },
                    "playtime_buckets": buckets,
                    "completed_100_percent_games": completed_100,
                    "top_20_games": [
                        {
                            "name": t["name"],
                            "title_id": t["title_id"],
                            "playtime_formatted": t["playtime_formatted"],
                            "playtime_hours": t["playtime_hours"],
                            "devices": t["devices"],
                            "is_game_pass": t["is_game_pass"],
                            "achievement_progress_percent": t[
                                "achievement_progress_percent"
                            ],
                            "last_played": t["last_played"],
                        }
                        for t in by_playtime[:20]
                    ],
                }
            )
    except AuthRequiredError as err:
        return _auth_error_payload(err)
    except Exception as exc:
        return _api_error_payload(exc)


@mcp.tool()
async def get_game_achievements(
    title_id: str,
    gamertag: Optional[str] = None,
    xuid: Optional[str] = None,
    unlocked_only: bool = False,
    sort_by: Literal["default", "rarity", "gamerscore", "unlock_time"] = "default",
) -> str:
    """Get achievements (unlock status, unlock timestamps, gamerscore, and global rarity percentage) for a specific Xbox title_id."""
    try:
        async with get_xbox_client() as client:
            target_xuid = await resolve_xuid(client, xuid=xuid, gamertag=gamertag)
            data = await fetch_game_achievements(
                client, xuid=target_xuid, title_id=str(title_id)
            )
            achs = data["achievements"]
            if unlocked_only:
                achs = [a for a in achs if a["unlocked"]]

            if sort_by == "rarity":
                achs.sort(
                    key=lambda a: (
                        a["rarity_percent"]
                        if a["rarity_percent"] is not None
                        else 999.0
                    )
                )
            elif sort_by == "gamerscore":
                achs.sort(key=lambda a: a["gamerscore"] or 0, reverse=True)
            elif sort_by == "unlock_time":
                achs.sort(key=lambda a: a["unlock_time"] or "", reverse=True)

            data["achievements"] = achs
            return _json(data)
    except AuthRequiredError as err:
        return _auth_error_payload(err)
    except Exception as exc:
        return _api_error_payload(exc)


@mcp.tool()
async def get_game_stats(
    title_id: Optional[str] = None,
    scid: Optional[str] = None,
    gamertag: Optional[str] = None,
    xuid: Optional[str] = None,
) -> str:
    """Get MinutesPlayed and Hero stats for a specific Xbox game using either its title_id or scid."""
    try:
        async with get_xbox_client() as client:
            target_xuid = await resolve_xuid(client, xuid=xuid, gamertag=gamertag)
            data = await fetch_game_stats(
                client, xuid=target_xuid, title_id=title_id, scid=scid
            )
            return _json(data)
    except AuthRequiredError as err:
        return _auth_error_payload(err)
    except Exception as exc:
        return _api_error_payload(exc)


@mcp.tool()
async def get_friends_list() -> str:
    """Get the authenticated user's Xbox Live friends list, online status, currently playing games, and gamerscore."""
    try:
        async with get_xbox_client() as client:
            data = await fetch_friends(client)
            return _json(data)
    except AuthRequiredError as err:
        return _auth_error_payload(err)
    except Exception as exc:
        return _api_error_payload(exc)


def main() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
