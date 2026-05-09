"""ChatGPT subscription OAuth — bypass API billing using your ChatGPT plan.

This is the same OAuth flow OpenAI's codex CLI uses. When authenticated via
subscription, requests against /v1/responses are billed against your
ChatGPT Plus / Pro / Business plan instead of pay-per-token API.

Flow (local-callback style, like the codex CLI):
  1. Open https://auth.openai.com/oauth/authorize?client_id=...&...
  2. User logs in with their ChatGPT account
  3. auth.openai.com redirects to http://localhost:1455/auth/callback?code=...
  4. We exchange the code at https://auth.openai.com/oauth/token
  5. The token response includes both `access_token` and `id_token` (JWT).
     We use the access_token as a Bearer header on Responses API requests.

Tokens are saved to ~/.axion/credentials/openai-oauth.json and auto-refreshed.

NOTE: ChatGPT subscription tokens only work against the /v1/responses
endpoint with Codex models (gpt-5-codex, gpt-5-codex-mini). They do NOT
authorize regular Chat Completions or arbitrary API access. This is by
design — the subscription is scoped to the codex agent product.
"""

from __future__ import annotations

import http.server
import logging
import threading
import time
import urllib.parse
from dataclasses import dataclass

from axion.runtime.oauth import (
    OAuthCallbackParams,
    OAuthTokenSet,
    PkceCodePair,
    _OAuthCallbackHandler,
    clear_oauth_credentials,
    generate_pkce_pair,
    generate_state,
    load_oauth_credentials,
    open_browser,
    save_oauth_credentials,
)

logger = logging.getLogger(__name__)

# Codex CLI's well-known OAuth client ID (from openai/codex-cli source)
OPENAI_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"

# Subscription OAuth endpoints
OPENAI_AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
OPENAI_TOKEN_URL = "https://auth.openai.com/oauth/token"

# Local callback (codex CLI uses port 1455)
CALLBACK_PORT = 1455
CALLBACK_PATH = "/auth/callback"
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}"

# Scopes — OpenID Connect + offline access for refresh tokens
OPENAI_SCOPES = ["openid", "profile", "email", "offline_access"]

# Provider key for credential storage
SUBSCRIPTION_PROVIDER = "openai-oauth"


@dataclass
class OpenAiSubscriptionAuthResult:
    """Result of an OpenAI subscription OAuth login attempt."""

    success: bool
    token_set: OAuthTokenSet | None = None
    error: str | None = None
    plan: str | None = None  # "Plus" / "Pro" / "Business" / etc, parsed from id_token


def build_openai_authorize_url(pkce: PkceCodePair, state: str) -> str:
    """Build the auth.openai.com authorize URL for subscription auth."""
    params = {
        "client_id": OPENAI_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(OPENAI_SCOPES),
        "state": state,
        "code_challenge": pkce.code_challenge,
        "code_challenge_method": "S256",
        # Codex-specific identifier so OpenAI knows this is a CLI request
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
    }
    return f"{OPENAI_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


async def exchange_authorization_code(
    code: str,
    code_verifier: str,
) -> OAuthTokenSet:
    """Exchange an authorization code for ChatGPT subscription tokens."""
    import httpx

    # OAuth token endpoint accepts form-encoded body
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": code_verifier,
        "client_id": OPENAI_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            OPENAI_TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Token exchange failed ({response.status_code}): {response.text[:500]}"
            )
        data = response.json()

    expires_in = data.get("expires_in")
    expires_at = int(time.time()) + expires_in if expires_in else None

    # Save the id_token alongside the access_token in the scopes field as a hack
    # so we can extract subscription plan info later. (OAuthTokenSet doesn't
    # have a dedicated id_token slot.)
    scopes = data.get("scope", "").split() if data.get("scope") else OPENAI_SCOPES
    id_token = data.get("id_token")
    if id_token:
        scopes = scopes + [f"id_token:{id_token}"]

    return OAuthTokenSet(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_at=expires_at,
        scopes=scopes,
    )


async def refresh_openai_token(refresh_token_str: str) -> OAuthTokenSet:
    """Refresh an expired ChatGPT subscription access token."""
    import httpx

    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token_str,
        "client_id": OPENAI_CLIENT_ID,
        "scope": " ".join(OPENAI_SCOPES),
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            OPENAI_TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Token refresh failed ({response.status_code}): {response.text[:500]}"
            )
        data = response.json()

    expires_in = data.get("expires_in")
    expires_at = int(time.time()) + expires_in if expires_in else None

    scopes = data.get("scope", "").split() if data.get("scope") else OPENAI_SCOPES
    id_token = data.get("id_token")
    if id_token:
        scopes = scopes + [f"id_token:{id_token}"]

    return OAuthTokenSet(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", refresh_token_str),
        expires_at=expires_at,
        scopes=scopes,
    )


async def login_with_openai_subscription(
    *,
    open_browser_automatically: bool = True,
    timeout_seconds: float = 300.0,
) -> OpenAiSubscriptionAuthResult:
    """Run the full ChatGPT subscription OAuth login flow.

    Spins up a local callback server on port 1455, opens the browser to
    auth.openai.com, waits for the redirect, exchanges the code, saves
    the tokens, and returns success/failure.
    """
    pkce = generate_pkce_pair()
    state = generate_state()
    auth_url = build_openai_authorize_url(pkce, state)

    # Reset the shared callback handler state
    _OAuthCallbackHandler.callback_result = None

    # Try to start the callback server
    try:
        server = http.server.HTTPServer(
            ("127.0.0.1", CALLBACK_PORT), _OAuthCallbackHandler
        )
    except OSError as exc:
        return OpenAiSubscriptionAuthResult(
            success=False,
            error=(
                f"Failed to start callback server on port {CALLBACK_PORT}: {exc}. "
                f"Is another process (codex CLI?) using this port?"
            ),
        )

    callback_result: list[OAuthCallbackParams | None] = [None]

    def serve() -> None:
        server.timeout = timeout_seconds
        server.handle_request()  # Handle exactly one request
        callback_result[0] = _OAuthCallbackHandler.callback_result

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()

    # Open the browser
    if open_browser_automatically:
        opened = open_browser(auth_url)
        if not opened:
            print(f"\nCould not open browser. Visit:\n{auth_url}\n")
    else:
        print(f"\nVisit this URL to log in:\n{auth_url}\n")

    # Wait for callback
    thread.join(timeout=timeout_seconds)
    server.server_close()

    cb = callback_result[0]
    if cb is None:
        return OpenAiSubscriptionAuthResult(
            success=False,
            error=f"Login timed out after {int(timeout_seconds)}s. Try again.",
        )

    if cb.error:
        return OpenAiSubscriptionAuthResult(
            success=False,
            error=f"OAuth error: {cb.error} - {cb.error_description or ''}",
        )

    if not cb.code:
        return OpenAiSubscriptionAuthResult(
            success=False,
            error="No authorization code returned in callback.",
        )

    if cb.state != state:
        return OpenAiSubscriptionAuthResult(
            success=False,
            error="State mismatch in OAuth callback (possible CSRF — try again).",
        )

    # Exchange code for tokens
    try:
        token_set = await exchange_authorization_code(
            code=cb.code,
            code_verifier=pkce.code_verifier,
        )
    except Exception as exc:
        return OpenAiSubscriptionAuthResult(
            success=False,
            error=f"Token exchange failed: {exc}",
        )

    # Save tokens
    save_oauth_credentials(SUBSCRIPTION_PROVIDER, token_set)
    plan = _extract_plan_from_token_set(token_set)
    return OpenAiSubscriptionAuthResult(success=True, token_set=token_set, plan=plan)


def _extract_plan_from_token_set(token_set: OAuthTokenSet) -> str | None:
    """Extract the ChatGPT subscription plan from the saved id_token JWT."""
    import base64
    import json

    id_token = None
    for scope in token_set.scopes:
        if scope.startswith("id_token:"):
            id_token = scope[len("id_token:"):]
            break
    if not id_token:
        return None

    # JWT is three base64url-encoded parts separated by dots
    parts = id_token.split(".")
    if len(parts) < 2:
        return None
    payload_b64 = parts[1]
    # Add padding if needed
    payload_b64 += "=" * (-len(payload_b64) % 4)
    try:
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        payload = json.loads(payload_bytes)
    except (ValueError, json.JSONDecodeError):
        return None

    # Look for plan/subscription claims (varies by provider)
    chatgpt_data = payload.get("https://api.openai.com/auth", {}) or {}
    plan = chatgpt_data.get("chatgpt_plan_type")
    if plan:
        return str(plan).title()  # "plus" -> "Plus"
    return None


async def get_valid_openai_subscription_token() -> str | None:
    """Return a valid ChatGPT subscription access token, refreshing if needed.

    Returns None if no subscription credentials are saved.
    """
    creds = load_oauth_credentials(SUBSCRIPTION_PROVIDER)
    if creds is None:
        return None

    if creds.is_expired() and creds.refresh_token:
        try:
            new_creds = await refresh_openai_token(creds.refresh_token)
            save_oauth_credentials(SUBSCRIPTION_PROVIDER, new_creds)
            return new_creds.access_token
        except Exception as exc:
            logger.warning("ChatGPT subscription token refresh failed: %s", exc)
            return None

    return creds.access_token


def has_openai_subscription_credentials() -> bool:
    """Check if ChatGPT subscription credentials are saved (without validating)."""
    return load_oauth_credentials(SUBSCRIPTION_PROVIDER) is not None


def get_openai_subscription_plan() -> str | None:
    """Get the saved ChatGPT plan name (Plus / Pro / Business / Team)."""
    creds = load_oauth_credentials(SUBSCRIPTION_PROVIDER)
    if creds is None:
        return None
    return _extract_plan_from_token_set(creds)


def logout_openai_subscription() -> None:
    """Remove ChatGPT subscription credentials."""
    clear_oauth_credentials(SUBSCRIPTION_PROVIDER)
