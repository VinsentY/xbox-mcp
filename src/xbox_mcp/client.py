"""High-level Xbox Live API helpers built on top of xbox-webapi."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

from xbox.webapi.api.client import XboxLiveClient


TITLEHUB_URL = "https://titlehub.xboxlive.com"
USERSTATS_URL = "https://userstats.xboxlive.com"
ACHIEVEMENTS_URL = "https://achievements.xboxlive.com"
PEOPLE_URL = "https://peoplehub.xboxlive.com"


def get_accept_language() -> str:
    """Return the Accept-Language locale for Xbox Live API requests (e.g., en-US, zh-CN)."""
    return os.environ.get("XBOX_LANGUAGE") or "en-US"


def format_minutes(minutes: Optional[int]) -> str:
    if minutes is None or minutes <= 0:
        return "0m"
    hours, mins = divmod(int(minutes), 60)
    if hours == 0:
        return f"{mins}m"
    return f"{hours}h {mins}m" if mins > 0 else f"{hours}h"


async def resolve_xuid(
    client: XboxLiveClient,
    xuid: Optional[str] = None,
    gamertag: Optional[str] = None,
) -> str:
    if xuid:
        return str(xuid).strip()
    if gamertag:
        prof = await client.profile.get_profile_by_gamertag(gamertag.strip())
        if not prof.profile_users:
            raise ValueError(f"No Xbox Live user found for gamertag '{gamertag}'.")
        return prof.profile_users[0].id
    return str(client.xuid)


async def fetch_profile(
    client: XboxLiveClient,
    xuid: Optional[str] = None,
    gamertag: Optional[str] = None,
) -> dict[str, Any]:
    if gamertag and not xuid:
        prof = await client.profile.get_profile_by_gamertag(gamertag.strip())
    else:
        target_xuid = await resolve_xuid(client, xuid=xuid)
        prof = await client.profile.get_profile_by_xuid(target_xuid)

    if not prof.profile_users:
        raise ValueError("Xbox Live profile not found.")

    user = prof.profile_users[0]
    settings = {s.id: s.value for s in user.settings}
    gamerscore_raw = settings.get("Gamerscore", "0")
    try:
        gamerscore = int(gamerscore_raw)
    except ValueError:
        gamerscore = gamerscore_raw

    return {
        "xuid": user.id,
        "gamertag": settings.get("Gamertag"),
        "modern_gamertag": settings.get("ModernGamertag"),
        "unique_modern_gamertag": settings.get("UniqueModernGamertag"),
        "gamerscore": gamerscore,
        "account_tier": settings.get("AccountTier"),
        "tenure_years": settings.get("TenureLevel"),
        "reputation": settings.get("XboxOneRep"),
        "location": settings.get("Location") or None,
        "bio": settings.get("Bio") or None,
        "real_name": settings.get("RealNameOverride") or None,
        "avatar": settings.get("GameDisplayPicRaw"),
    }


async def fetch_presence(
    client: XboxLiveClient,
    xuid: Optional[str] = None,
    gamertag: Optional[str] = None,
) -> dict[str, Any]:
    target_xuid = await resolve_xuid(client, xuid=xuid, gamertag=gamertag)
    url = f"https://userpresence.xboxlive.com/users/xuid({target_xuid})?level=all"
    resp = await client.session.get(
        url,
        headers={"x-xbl-contract-version": "3", "Accept": "application/json"},
    )
    resp.raise_for_status()
    raw = resp.json()

    devices = []
    for dev in raw.get("devices") or []:
        titles = []
        for t in dev.get("titles") or []:
            titles.append(
                {
                    "title_id": t.get("id"),
                    "name": t.get("name"),
                    "state": t.get("state"),
                    "placement": t.get("placement"),
                    "rich_presence": (t.get("activity") or {}).get("richPresence")
                    if isinstance(t.get("activity"), dict)
                    else None,
                    "last_modified": t.get("lastModified"),
                }
            )
        devices.append({"device_type": dev.get("type"), "titles": titles})

    return {
        "xuid": raw.get("xuid", target_xuid),
        "state": raw.get("state"),
        "last_seen": raw.get("lastSeen"),
        "devices": devices,
    }


async def fetch_title_history_raw(
    client: XboxLiveClient,
    xuid: str,
    max_items: int = 1000,
    include_detail: bool = False,
) -> list[dict[str, Any]]:
    fields = ["achievement", "scid", "stats", "gamepass"]
    if include_detail:
        fields.append("detail")
    decoration = ",".join(fields)
    url = f"{TITLEHUB_URL}/users/xuid({xuid})/titles/titlehistory/decoration/{decoration}"
    headers = {
        "x-xbl-contract-version": "2",
        "x-xbl-client-name": "XboxApp",
        "x-xbl-client-type": "UWA",
        "x-xbl-client-version": "39.39.22001.0",
        "Accept-Language": get_accept_language(),
    }
    resp = await client.session.get(url, params={"maxItems": max_items}, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    return data.get("titles") or []


async def fetch_minutes_played_batch(
    client: XboxLiveClient,
    xuid: str,
    title_ids: list[str],
    chunk_size: int = 50,
) -> dict[str, int]:
    """Batch-fetch MinutesPlayed for many title IDs via Xbox Live userstats/batch."""
    unique_ids = [str(tid) for tid in dict.fromkeys(title_ids) if tid]
    if not unique_ids:
        return {}

    headers = {"x-xbl-contract-version": "2"}
    url = f"{USERSTATS_URL}/batch"
    results: dict[str, int] = {}
    semaphore = asyncio.Semaphore(4)

    async def query_chunk(chunk: list[str]) -> None:
        post_data = {
            "arrangebyfield": "xuid",
            "stats": [{"name": "MinutesPlayed", "titleId": tid} for tid in chunk],
            "xuids": [str(xuid)],
        }
        async with semaphore:
            resp = await client.session.post(url, json=post_data, headers=headers)
            if resp.status_code != 200:
                return
            payload = resp.json()
            for col in payload.get("statlistscollection") or []:
                for stat in col.get("stats") or []:
                    tid = str(stat.get("titleid") or stat.get("titleId") or "")
                    val = stat.get("value")
                    if tid and val is not None:
                        try:
                            results[tid] = int(float(val))
                        except (TypeError, ValueError):
                            pass

    chunks = [
        unique_ids[i : i + chunk_size] for i in range(0, len(unique_ids), chunk_size)
    ]
    await asyncio.gather(*(query_chunk(c) for c in chunks))
    return results


def _normalize_title_entry(
    raw: dict[str, Any], minutes_map: dict[str, int]
) -> dict[str, Any]:
    title_id = str(raw.get("titleId") or "")
    minutes = minutes_map.get(title_id)
    ach = raw.get("achievement") or {}
    history = raw.get("titleHistory") or {}
    game_pass = raw.get("gamePass") or {}
    detail = raw.get("detail") or {}

    devices = raw.get("devices") or []
    is_pc = any(d in ("PC", "Win32") for d in devices)
    is_xbox_console = any(
        d in ("XboxOne", "XboxSeries", "Xbox360", "Scarlett", "Durango")
        for d in devices
    )
    is_win32_footprint = (
        devices == ["Win32"]
        and minutes is None
        and not (ach.get("totalGamerscore") or 0)
    )

    entry: dict[str, Any] = {
        "title_id": title_id,
        "scid": raw.get("serviceConfigId"),
        "name": raw.get("name"),
        "type": raw.get("type"),
        "devices": devices,
        "is_pc": is_pc,
        "is_xbox_console": is_xbox_console,
        "is_win32_footprint": is_win32_footprint,
        "is_game_pass": bool(game_pass.get("isGamePass", False)),
        "playtime_minutes": minutes,
        "playtime_hours": round(minutes / 60, 2) if minutes is not None else None,
        "playtime_formatted": format_minutes(minutes) if minutes is not None else None,
        "last_played": history.get("lastTimePlayed"),
        "achievements_unlocked": ach.get("currentAchievements"),
        "achievements_total": ach.get("totalAchievements"),
        "gamerscore_earned": ach.get("currentGamerscore"),
        "gamerscore_total": ach.get("totalGamerscore"),
        "achievement_progress_percent": ach.get("progressPercentage"),
    }
    if detail:
        entry["genres"] = detail.get("genres") or []
        entry["developer"] = detail.get("developerName")
        entry["publisher"] = detail.get("publisherName")
        entry["release_date"] = detail.get("releaseDate")
    return entry


async def fetch_enriched_library(
    client: XboxLiveClient,
    xuid: str,
    games_only: bool = True,
    max_items: int = 1000,
    include_detail: bool = False,
) -> list[dict[str, Any]]:
    raw_titles = await fetch_title_history_raw(
        client, xuid=xuid, max_items=max_items, include_detail=include_detail
    )
    if games_only:
        raw_titles = [
            t
            for t in raw_titles
            if (t.get("type") or "").lower() == "game"
            or (t.get("achievement") or {}).get("totalGamerscore", 0) > 0
        ]

    title_ids = [str(t.get("titleId")) for t in raw_titles if t.get("titleId")]
    minutes_map = await fetch_minutes_played_batch(client, xuid=xuid, title_ids=title_ids)
    return [_normalize_title_entry(t, minutes_map) for t in raw_titles]


async def fetch_game_stats(
    client: XboxLiveClient,
    xuid: str,
    title_id: Optional[str] = None,
    scid: Optional[str] = None,
) -> dict[str, Any]:
    if not title_id and not scid:
        raise ValueError("Provide either 'title_id' or 'scid'.")

    headers = {"x-xbl-contract-version": "2"}
    url = f"{USERSTATS_URL}/batch"
    group = {"name": "Hero"}
    stat_req = {"name": "MinutesPlayed"}
    if title_id:
        group["titleId"] = str(title_id)
        stat_req["titleId"] = str(title_id)
    else:
        group["scid"] = str(scid)
        stat_req["scid"] = str(scid)

    post_data = {
        "arrangebyfield": "xuid",
        "groups": [group],
        "stats": [stat_req],
        "xuids": [str(xuid)],
    }
    resp = await client.session.post(url, json=post_data, headers=headers)
    resp.raise_for_status()
    payload = resp.json()

    minutes_played = None
    for col in payload.get("statlistscollection") or []:
        for stat in col.get("stats") or []:
            if stat.get("name") == "MinutesPlayed" and stat.get("value") is not None:
                try:
                    minutes_played = int(float(stat["value"]))
                except (TypeError, ValueError):
                    pass

    hero_stats = []
    for grp in payload.get("groups") or []:
        for col in grp.get("statlistscollection") or []:
            for stat in col.get("stats") or []:
                gp = stat.get("groupproperties") or {}
                props = stat.get("properties") or {}
                hero_stats.append(
                    {
                        "name": stat.get("name"),
                        "display_name": gp.get("DisplayName") or props.get("DisplayName"),
                        "value": stat.get("value"),
                        "type": stat.get("type"),
                    }
                )

    return {
        "xuid": xuid,
        "title_id": title_id,
        "scid": scid,
        "minutes_played": minutes_played,
        "playtime_formatted": format_minutes(minutes_played)
        if minutes_played is not None
        else None,
        "hero_stats": hero_stats,
    }


async def fetch_game_achievements(
    client: XboxLiveClient,
    xuid: str,
    title_id: str,
) -> dict[str, Any]:
    """Fetch Xbox One/Series/PC achievements (with rarity), falling back to Xbox 360."""
    locale = get_accept_language()
    url_v2 = f"{ACHIEVEMENTS_URL}/users/xuid({xuid})/achievements"
    resp = await client.session.get(
        url_v2,
        params={"titleId": str(title_id), "maxItems": 1000},
        headers={"x-xbl-contract-version": "4", "Accept-Language": locale},
    )
    if resp.status_code == 200:
        data = resp.json()
        raw_achs = data.get("achievements") or []
        if raw_achs:
            parsed = []
            unlocked_count = 0
            earned_gs = 0
            total_gs = 0
            for a in raw_achs:
                unlocked = a.get("progressState") == "Achieved"
                if unlocked:
                    unlocked_count += 1
                gs = 0
                for rew in a.get("rewards") or []:
                    if rew.get("type") == "Gamerscore":
                        try:
                            gs = int(rew.get("value", 0))
                        except (TypeError, ValueError):
                            gs = 0
                total_gs += gs
                if unlocked:
                    earned_gs += gs
                rarity = a.get("rarity") or {}
                prog = a.get("progression") or {}
                parsed.append(
                    {
                        "id": a.get("id"),
                        "name": a.get("name"),
                        "description": a.get("description")
                        if unlocked
                        else a.get("lockedDescription"),
                        "unlocked": unlocked,
                        "unlock_time": prog.get("timeUnlocked") if unlocked else None,
                        "gamerscore": gs,
                        "rarity_percent": rarity.get("currentPercentage"),
                        "rarity_category": rarity.get("currentCategory"),
                        "is_secret": bool(a.get("isSecret", False)),
                    }
                )
            return {
                "xuid": xuid,
                "title_id": str(title_id),
                "platform_generation": "XboxOne/Series/PC",
                "total_achievements": len(parsed),
                "unlocked": unlocked_count,
                "completion_percent": round(unlocked_count / len(parsed) * 100, 1)
                if parsed
                else 0.0,
                "gamerscore_earned": earned_gs,
                "gamerscore_total": total_gs,
                "achievements": parsed,
            }

    # Fallback: Xbox 360 title achievements
    url_360 = f"{ACHIEVEMENTS_URL}/users/xuid({xuid})/titleachievements"
    resp360 = await client.session.get(
        url_360,
        params={"titleId": str(title_id), "maxItems": 1000},
        headers={"x-xbl-contract-version": "1", "Accept-Language": locale},
    )
    resp360.raise_for_status()
    data360 = resp360.json()
    raw_360 = data360.get("achievements") or []
    parsed_360 = []
    unlocked_count = 0
    earned_gs = 0
    total_gs = 0
    for a in raw_360:
        unlocked = bool(a.get("unlocked") or a.get("unlockedOnline"))
        gs = int(a.get("gamerscore") or 0)
        total_gs += gs
        if unlocked:
            unlocked_count += 1
            earned_gs += gs
        parsed_360.append(
            {
                "id": str(a.get("id")),
                "name": a.get("name"),
                "description": a.get("description")
                if unlocked
                else a.get("lockedDescription"),
                "unlocked": unlocked,
                "unlock_time": a.get("timeUnlocked") if unlocked else None,
                "gamerscore": gs,
                "rarity_percent": None,
                "rarity_category": None,
                "is_secret": bool(a.get("isSecret", False)),
            }
        )
    return {
        "xuid": xuid,
        "title_id": str(title_id),
        "platform_generation": "Xbox360",
        "total_achievements": len(parsed_360),
        "unlocked": unlocked_count,
        "completion_percent": round(unlocked_count / len(parsed_360) * 100, 1)
        if parsed_360
        else 0.0,
        "gamerscore_earned": earned_gs,
        "gamerscore_total": total_gs,
        "achievements": parsed_360,
    }


async def fetch_friends(client: XboxLiveClient) -> dict[str, Any]:
    decoration = "detail,presenceDetail,titlePresence"
    url = f"{PEOPLE_URL}/users/me/people/social/decoration/{decoration}"
    resp = await client.session.get(
        url,
        headers={
            "x-xbl-contract-version": "5",
            "Accept-Language": get_accept_language(),
        },
    )
    resp.raise_for_status()
    data = resp.json()
    people = data.get("people") or []

    friends = []
    for p in people:
        tp = p.get("titlePresence") or {}
        detail = p.get("detail") or {}
        friends.append(
            {
                "xuid": p.get("xuid"),
                "gamertag": p.get("gamertag"),
                "modern_gamertag": p.get("uniqueModernGamertag") or p.get("modernGamertag"),
                "gamerscore": p.get("gamerScore"),
                "is_favorite": bool(p.get("isFavorite", False)),
                "presence_state": p.get("presenceState"),
                "presence_text": p.get("presenceText"),
                "currently_playing": tp.get("TitleName") if tp.get("IsCurrentlyPlaying") else None,
                "added_date": p.get("addedDateTimeUtc"),
                "last_seen": p.get("lastSeenDateTimeUtc"),
                "has_game_pass": detail.get("hasGamePass"),
            }
        )
    return {
        "xuid": str(client.xuid),
        "total_friends": len(friends),
        "friends": friends,
    }
