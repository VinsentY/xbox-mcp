"""Microsoft / Xbox Live OAuth2 authentication and local token persistence."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import http.server
import os
from pathlib import Path
import queue
import socketserver
import threading
from typing import AsyncIterator, Optional
from urllib.parse import parse_qs, urlparse
import webbrowser

from xbox.webapi.api.client import XboxLiveClient
from xbox.webapi.api.language import DefaultXboxLiveLanguages
from xbox.webapi.authentication.manager import AuthenticationManager
from xbox.webapi.authentication.models import OAuth2TokenResponse
from xbox.webapi.common.signed_session import SignedSession
from xbox.webapi.scripts import (
    CLIENT_ID as DEFAULT_CLIENT_ID,
    CLIENT_SECRET as DEFAULT_CLIENT_SECRET,
    REDIRECT_URI as DEFAULT_REDIRECT_URI,
    TOKENS_FILE as DEFAULT_XBOX_WEBAPI_TOKENS_FILE,
)


class AuthRequiredError(RuntimeError):
    """Raised when no valid Xbox Live OAuth tokens are available."""


def get_client_id() -> str:
    return os.environ.get("XBOX_CLIENT_ID") or DEFAULT_CLIENT_ID


def get_client_secret() -> str:
    return os.environ.get("XBOX_CLIENT_SECRET") or DEFAULT_CLIENT_SECRET


def get_redirect_uri() -> str:
    return os.environ.get("XBOX_REDIRECT_URI") or DEFAULT_REDIRECT_URI


def get_tokens_path() -> Path:
    env_path = os.environ.get("XBOX_TOKENS_FILE")
    if env_path:
        return Path(env_path).expanduser()
    return Path(DEFAULT_XBOX_WEBAPI_TOKENS_FILE).expanduser()


def save_oauth_tokens(oauth: OAuth2TokenResponse, path: Optional[Path] = None) -> Path:
    token_path = path or get_tokens_path()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = token_path.with_suffix(".tmp")
    tmp_path.write_text(oauth.model_dump_json(indent=2), encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(token_path)
    os.chmod(token_path, 0o600)
    return token_path


def load_oauth_tokens(path: Optional[Path] = None) -> Optional[OAuth2TokenResponse]:
    token_path = path or get_tokens_path()
    if not token_path.exists():
        return None
    raw = token_path.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    return OAuth2TokenResponse.model_validate_json(raw)


def generate_auth_url() -> str:
    """Generate the Microsoft OAuth2 authorization URL without network I/O."""
    auth_mgr = AuthenticationManager(
        SignedSession(),
        get_client_id(),
        get_client_secret(),
        get_redirect_uri(),
    )
    return auth_mgr.generate_authorization_url()


def extract_auth_code(callback_url_or_code: str) -> str:
    """Extract OAuth2 `code` from either a full redirect URL or a raw code string."""
    value = callback_url_or_code.strip()
    if "://" in value or "?" in value:
        parsed = urlparse(value)
        qs = parse_qs(parsed.query)
        if qs.get("error"):
            err = qs.get("error_description", qs["error"])[0]
            raise ValueError(f"OAuth authorization failed: {err}")
        codes = qs.get("code")
        if not codes or not codes[0]:
            raise ValueError("No 'code' query parameter found in the callback URL.")
        return codes[0]
    if not value:
        raise ValueError("Authorization code cannot be empty.")
    return value


async def exchange_code_and_save(callback_url_or_code: str) -> dict:
    """Exchange an authorization code for OAuth2 + XBL + XSTS tokens and persist them."""
    code = extract_auth_code(callback_url_or_code)
    async with SignedSession() as session:
        auth_mgr = AuthenticationManager(
            session,
            get_client_id(),
            get_client_secret(),
            get_redirect_uri(),
        )
        await auth_mgr.request_tokens(code)
        token_path = save_oauth_tokens(auth_mgr.oauth)
        xuid = auth_mgr.xsts_token.xuid
        gamertag = auth_mgr.xsts_token.gamertag
        return {
            "authenticated": True,
            "xuid": xuid,
            "gamertag": gamertag,
            "tokens_path": str(token_path),
        }


@asynccontextmanager
async def get_xbox_client() -> AsyncIterator[XboxLiveClient]:
    """Yield an authenticated XboxLiveClient, automatically refreshing & saving tokens."""
    token_path = get_tokens_path()
    oauth = load_oauth_tokens(token_path)
    if oauth is None:
        raise AuthRequiredError(
            f"Xbox Live authentication required. No token file found at '{token_path}'. "
            "Run `uv run xbox-auth` or open the login URL from `get_auth_status` and call `complete_auth`."
        )

    async with SignedSession() as session:
        auth_mgr = AuthenticationManager(
            session,
            get_client_id(),
            get_client_secret(),
            get_redirect_uri(),
        )
        auth_mgr.oauth = oauth
        prev_access = oauth.access_token
        prev_refresh = oauth.refresh_token
        try:
            await auth_mgr.refresh_tokens()
        except Exception as exc:
            raise AuthRequiredError(
                f"Failed to refresh Xbox Live tokens ({exc}). Please re-authenticate via `uv run xbox-auth` or `complete_auth`."
            ) from exc

        if (
            auth_mgr.oauth.access_token != prev_access
            or auth_mgr.oauth.refresh_token != prev_refresh
        ):
            save_oauth_tokens(auth_mgr.oauth, token_path)

        client = XboxLiveClient(auth_mgr, language=DefaultXboxLiveLanguages.United_States)
        yield client


async def _run_interactive_auth(port: int = 8080, open_browser: bool = True) -> None:
    code_queue: queue.Queue[str] = queue.Queue(maxsize=1)

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:
            return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            if qs.get("error"):
                desc = qs.get("error_description", qs["error"])[0]
                body = f"<h2>Xbox Auth Failed</h2><p>{desc}</p>".encode("utf-8")
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            codes = qs.get("code")
            if not codes:
                body = b"<h2>Missing authorization code</h2>"
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            code_queue.put(codes[0])
            body = (
                "<html><body style='font-family:sans-serif;padding:40px;text-align:center'>"
                "<h2>Xbox Live 授权成功！</h2>"
                "<p>可以关闭此页面并返回终端或 Antigravity。</p>"
                "</body></html>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    auth_url = generate_auth_url()

    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    with ReusableTCPServer(("127.0.0.1", port), CallbackHandler) as httpd:
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        print(f"Listening for OAuth callback on http://localhost:{port}/auth/callback")
        print(f"\nOpen this URL to sign in with your Microsoft / Xbox account:\n{auth_url}\n")
        if open_browser:
            webbrowser.open(auth_url)

        code = await asyncio.to_thread(code_queue.get)
        result = await exchange_code_and_save(code)
        print(
            f"Authenticated as {result['gamertag']} (XUID: {result['xuid']})\n"
            f"Tokens saved securely to: {result['tokens_path']}"
        )
        httpd.shutdown()


def cli_main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Authenticate locally with Microsoft Xbox Live for xbox-mcp."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Local callback port (default: 8080).",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the login URL instead of automatically opening a browser.",
    )
    parser.add_argument(
        "--code",
        type=str,
        default=None,
        help="Directly exchange a callback URL or authorization code without starting an HTTP server.",
    )
    args = parser.parse_args()

    if args.code:
        result = asyncio.run(exchange_code_and_save(args.code))
        print(
            f"Authenticated as {result['gamertag']} (XUID: {result['xuid']})\n"
            f"Tokens saved securely to: {result['tokens_path']}"
        )
    else:
        asyncio.run(_run_interactive_auth(port=args.port, open_browser=not args.no_browser))
