"""OAuth PKCE flow with HTTP callback server, token refresh, and browser launch.

Maps to: rust/crates/runtime/src/oauth.rs
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import http.server
import json
import logging
import os
import platform
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_OAUTH_CALLBACK_PORT = 4545
DEFAULT_CALLBACK_PATH = "/oauth/callback"


@dataclass
class OAuthTokenSet:
    access_token: str
    refresh_token: str | None = None
    expires_at: int | None = None
    scopes: list[str] = field(default_factory=list)

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return int(time.time()) >= self.expires_at


@dataclass
class OAuthConfig:
    client_id: str = ""
    authorize_url: str = "https://console.anthropic.com/oauth/authorize"
    token_url: str = "https://console.anthropic.com/oauth/token"
    callback_port: int = DEFAULT_OAUTH_CALLBACK_PORT
    scopes: list[str] = field(default_factory=lambda: ["user:inference"])


@dataclass
class PkceCodePair:
    code_verifier: str
    code_challenge: str


@dataclass
class OAuthCallbackParams:
    code: str | None = None
    state: str | None = None
    error: str | None = None
    error_description: str | None = None


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------

def generate_pkce_pair() -> PkceCodePair:
    """Generate a PKCE code verifier and S256 challenge."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return PkceCodePair(code_verifier=verifier, code_challenge=challenge)


def generate_state() -> str:
    """Generate a random OAuth state parameter."""
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Credential persistence
# ---------------------------------------------------------------------------

def _credentials_path(provider: str) -> Path:
    return Path.home() / ".axion" / "credentials" / f"{provider}.json"


def save_oauth_credentials(provider: str, token_set: OAuthTokenSet) -> None:
    """Save OAuth credentials to disk."""
    path = _credentials_path(provider)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "access_token": token_set.access_token,
        "refresh_token": token_set.refresh_token,
        "expires_at": token_set.expires_at,
        "scopes": token_set.scopes,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_oauth_credentials(provider: str) -> OAuthTokenSet | None:
    """Load OAuth credentials from disk."""
    path = _credentials_path(provider)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return OAuthTokenSet(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=data.get("expires_at"),
            scopes=data.get("scopes", []),
        )
    except (json.JSONDecodeError, KeyError, OSError):
        return None


def clear_oauth_credentials(provider: str) -> None:
    """Remove OAuth credentials from disk."""
    path = _credentials_path(provider)
    if path.exists():
        path.unlink()


# ---------------------------------------------------------------------------
# Browser launch (platform-specific)
# ---------------------------------------------------------------------------

def open_browser(url: str) -> bool:
    """Open a URL in the default browser. Returns True on success."""
    system = platform.system().lower()
    try:
        if system == "darwin":
            subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        elif system == "windows":
            subprocess.Popen(
                ["cmd", "/C", "start", "", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        elif system == "linux":
            subprocess.Popen(
                ["xdg-open", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
    except (FileNotFoundError, OSError) as exc:
        logger.warning("Failed to open browser: %s", exc)
    return False


# ---------------------------------------------------------------------------
# OAuth callback HTTP server
# ---------------------------------------------------------------------------

class _OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler that captures the OAuth callback parameters."""

    callback_result: OAuthCallbackParams | None = None

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        result = OAuthCallbackParams(
            code=params.get("code", [None])[0],
            state=params.get("state", [None])[0],
            error=params.get("error", [None])[0],
            error_description=params.get("error_description", [None])[0],
        )
        _OAuthCallbackHandler.callback_result = result

        # Send response
        if result.error:
            body = f"<h1>OAuth Error</h1><p>{result.error}: {result.error_description}</p>"
            self.send_response(400)
        else:
            body = "<h1>Success!</h1><p>You can close this window and return to Axion Code.</p>"
            self.send_response(200)

        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress default logging
        pass


def wait_for_oauth_callback(
    port: int = DEFAULT_OAUTH_CALLBACK_PORT,
    timeout: float = 120.0,
) -> OAuthCallbackParams | None:
    """Start a local HTTP server and wait for the OAuth callback.

    Returns the callback parameters or None on timeout.
    """
    _OAuthCallbackHandler.callback_result = None

    server = http.server.HTTPServer(("127.0.0.1", port), _OAuthCallbackHandler)
    server.timeout = timeout

    # Run in a thread with timeout
    result: OAuthCallbackParams | None = None

    def serve() -> None:
        nonlocal result
        server.handle_request()  # Handle exactly one request
        result = _OAuthCallbackHandler.callback_result

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    server.server_close()
    return result


# ---------------------------------------------------------------------------
# Token exchange and refresh
# ---------------------------------------------------------------------------

async def exchange_authorization_code(
    token_url: str,
    code: str,
    code_verifier: str,
    client_id: str,
    redirect_uri: str,
) -> OAuthTokenSet:
    """Exchange an authorization code for tokens."""
    import httpx

    async with httpx.AsyncClient() as client:
        response = await client.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
                "client_id": client_id,
                "redirect_uri": redirect_uri,
            },
        )
        response.raise_for_status()
        data = response.json()

    expires_in = data.get("expires_in")
    expires_at = int(time.time()) + expires_in if expires_in else None

    return OAuthTokenSet(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_at=expires_at,
        scopes=data.get("scope", "").split() if data.get("scope") else [],
    )


async def refresh_token(
    token_url: str,
    refresh_token_str: str,
    client_id: str,
) -> OAuthTokenSet:
    """Refresh an expired OAuth token."""
    import httpx

    async with httpx.AsyncClient() as client:
        response = await client.post(
            token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token_str,
                "client_id": client_id,
            },
        )
        response.raise_for_status()
        data = response.json()

    expires_in = data.get("expires_in")
    expires_at = int(time.time()) + expires_in if expires_in else None

    return OAuthTokenSet(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", refresh_token_str),
        expires_at=expires_at,
        scopes=data.get("scope", "").split() if data.get("scope") else [],
    )


# ---------------------------------------------------------------------------
# Full login flow
# ---------------------------------------------------------------------------

def build_authorization_url(
    config: OAuthConfig,
    pkce: PkceCodePair,
    state: str,
) -> str:
    """Build the full OAuth authorization URL."""
    params = {
        "client_id": config.client_id,
        "response_type": "code",
        "redirect_uri": f"http://127.0.0.1:{config.callback_port}{DEFAULT_CALLBACK_PATH}",
        "state": state,
        "code_challenge": pkce.code_challenge,
        "code_challenge_method": "S256",
    }
    if config.scopes:
        params["scope"] = " ".join(config.scopes)

    return f"{config.authorize_url}?{urllib.parse.urlencode(params)}"
