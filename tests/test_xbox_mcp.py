"""Unit tests for xbox-mcp helper utilities."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from xbox_mcp.auth import extract_auth_code, generate_auth_url
from xbox_mcp.client import (
    _normalize_title_entry,
    format_minutes,
    get_accept_language,
)


class TestXboxMcpHelpers(unittest.TestCase):
    def test_format_minutes(self) -> None:
        self.assertEqual(format_minutes(None), "0m")
        self.assertEqual(format_minutes(0), "0m")
        self.assertEqual(format_minutes(45), "45m")
        self.assertEqual(format_minutes(60), "1h")
        self.assertEqual(format_minutes(125), "2h 5m")

    def test_extract_auth_code_from_url_and_raw(self) -> None:
        url = "http://localhost:8080/auth/callback?code=M.C501_BAY.2.U.abc123&state=xyz"
        self.assertEqual(extract_auth_code(url), "M.C501_BAY.2.U.abc123")
        self.assertEqual(extract_auth_code("raw_code_456"), "raw_code_456")

        with self.assertRaises(ValueError):
            extract_auth_code("http://localhost:8080/auth/callback?error=access_denied")
        with self.assertRaises(ValueError):
            extract_auth_code("   ")

    def test_generate_auth_url(self) -> None:
        url = generate_auth_url()
        self.assertIn("login.live.com/oauth20_authorize.srf", url)
        self.assertIn("Xboxlive.signin", url)
        self.assertIn("Xboxlive.offline_access", url)

    def test_normalize_title_entry_xbox_and_win32(self) -> None:
        xbox_raw = {
            "titleId": "1668241504",
            "serviceConfigId": "00000000-0000-0000-0000-000000000001",
            "name": "Sample Game",
            "type": "Game",
            "devices": ["PC", "XboxSeries"],
            "gamePass": {"isGamePass": True},
            "titleHistory": {"lastTimePlayed": "2026-06-01T10:00:00Z"},
            "achievement": {
                "currentAchievements": 10,
                "totalAchievements": 50,
                "currentGamerscore": 200,
                "totalGamerscore": 1000,
                "progressPercentage": 20.0,
            },
        }
        norm = _normalize_title_entry(xbox_raw, {"1668241504": 150})
        self.assertEqual(norm["playtime_hours"], 2.5)
        self.assertEqual(norm["playtime_formatted"], "2h 30m")
        self.assertTrue(norm["is_pc"])
        self.assertTrue(norm["is_xbox_console"])
        self.assertTrue(norm["is_game_pass"])
        self.assertFalse(norm["is_win32_footprint"])

        win32_raw = {
            "titleId": "999999",
            "name": "Third-Party Win32 Game",
            "type": "Game",
            "devices": ["Win32"],
            "achievement": {"totalGamerscore": 0},
        }
        win32_norm = _normalize_title_entry(win32_raw, {})
        self.assertTrue(win32_norm["is_win32_footprint"])
        self.assertIsNone(win32_norm["playtime_minutes"])

    def test_accept_language_env(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XBOX_LANGUAGE", None)
            self.assertEqual(get_accept_language(), "en-US")
        with patch.dict(os.environ, {"XBOX_LANGUAGE": "zh-CN"}):
            self.assertEqual(get_accept_language(), "zh-CN")


if __name__ == "__main__":
    unittest.main()
