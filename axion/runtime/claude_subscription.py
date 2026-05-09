"""Claude Pro/Max subscription OAuth — bypass API billing using your subscription.

This is the same OAuth flow Claude Code uses. When authenticated via subscription,
requests are billed against your Claude Pro/Max plan instead of pay-per-token API.

Flow (paste-style, like Claude Code):
  1. Open https://claude.ai/oauth/authorize?...&redirect_uri=https://platform.claude.com/oauth/code/success?app=claude-code
  2. User logs in and authorizes
  3. claude.ai redirects to platform.claude.com/oauth/code/success which displays the code
  4. User copies the code and pastes it into the CLI
  5. We exchange the code for an access token at console.anthropic.com
  6. Use the token as `Authorization: Bearer <token>` with `anthropic-beta: oauth-2025-04-20`

Tokens are saved to ~/.axion/credentials/anthropic-oauth.json and auto-refreshed.
"""

from __future__ import annotations

import logging
import time
import urllib.parse
from dataclasses import dataclass

from axion.runtime.oauth import (
    OAuthTokenSet,
    PkceCodePair,
    clear_oauth_credentials,
    generate_pkce_pair,
    generate_state,
    load_oauth_credentials,
    open_browser,
    save_oauth_credentials,
)

logger = logging.getLogger(__name__)

# Claude Code's well-known OAuth client ID for subscription auth
CLAUDE_CODE_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"

# Subscription OAuth endpoints
CLAUDE_AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
CLAUDE_TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"

# Registered redirect URI for Claude Code's OAuth client.
# When `code=true` is set in the authorize URL, claude.ai displays the code
# on https://platform.claude.com/oauth/code/success?app=claude-code instead
# of actually redirecting — but the OAuth `redirect_uri` parameter must still
# match what's registered for this client.
CLAUDE_REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"

# OAuth requires this beta header on Messages API requests
SUBSCRIPTION_BETA_HEADER = "oauth-2025-04-20"

# Scopes required for subscription-based inference
SUBSCRIPTION_SCOPES = ["org:create_api_key", "user:profile", "user:inference"]

# Provider key for credential storage
SUBSCRIPTION_PROVIDER = "anthropic-oauth"


@dataclass
class SubscriptionAuthResult:
    """Result of a subscription OAuth login attempt."""

    success: bool
    token_set: OAuthTokenSet | None = None
    error: str | None = None


def build_subscription_authorize_url(pkce: PkceCodePair, state: str) -> str:
    """Build the claude.ai authorize URL for subscription auth."""
    params = {
        "code": "true",  # Tells claude.ai this is for paste-style flow
        "client_id": CLAUDE_CODE_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": CLAUDE_REDIRECT_URI,
        "scope": " ".join(SUBSCRIPTION_SCOPES),
        "state": state,
        "code_challenge": pkce.code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{CLAUDE_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def parse_pasted_code(pasted: str) -> tuple[str, str | None]:
    """Parse the code from whatever the user pasted.

    Handles all common paste formats:
      - `code` — just the code
      - `code#state` — Claude's success page format ("Paste this into Claude Code")
      - `https://platform.claude.com/oauth/code/callback?code=ABC&state=XYZ` — full URL
      - `?code=ABC&state=XYZ` — query string only
      - URLs with the authorize endpoint (user pasted wrong thing) — return empty
    """
    pasted = pasted.strip()

    if not pasted:
        return "", None

    # If they pasted the AUTHORIZE URL by mistake, reject it
    if "/oauth/authorize" in pasted:
        return "", None

    # If they pasted a full URL or query string, extract code & state
    if pasted.startswith(("http://", "https://", "?")):
        from urllib.parse import urlparse, parse_qs

        if pasted.startswith("?"):
            # Just a query string
            qs = pasted[1:]
        else:
            qs = urlparse(pasted).query

        params = parse_qs(qs)
        code = (params.get("code") or [""])[0].strip()
        state = (params.get("state") or [None])[0]
        if state:
            state = state.strip() or None
        return code, state

    # Claude's success page format: code#state
    if "#" in pasted:
        code, _, state = pasted.partition("#")
        return code.strip(), state.strip() or None

    # Plain code
    return pasted, None


async def exchange_subscription_code(
    code: str,
    code_verifier: str,
    state: str,
) -> OAuthTokenSet:
    """Exchange an authorization code for subscription tokens."""
    import httpx

    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": code_verifier,
        "client_id": CLAUDE_CODE_CLIENT_ID,
        "redirect_uri": CLAUDE_REDIRECT_URI,
        "state": state,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            CLAUDE_TOKEN_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Token exchange failed ({response.status_code}): {response.text[:500]}"
            )
        data = response.json()

    expires_in = data.get("expires_in")
    expires_at = int(time.time()) + expires_in if expires_in else None

    return OAuthTokenSet(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_at=expires_at,
        scopes=data.get("scope", "").split() if data.get("scope") else SUBSCRIPTION_SCOPES,
    )


async def refresh_subscription_token(refresh_token_str: str) -> OAuthTokenSet:
    """Refresh an expired subscription access token."""
    import httpx

    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token_str,
        "client_id": CLAUDE_CODE_CLIENT_ID,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            CLAUDE_TOKEN_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Token refresh failed ({response.status_code}): {response.text[:500]}"
            )
        data = response.json()

    expires_in = data.get("expires_in")
    expires_at = int(time.time()) + expires_in if expires_in else None

    return OAuthTokenSet(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", refresh_token_str),
        expires_at=expires_at,
        scopes=data.get("scope", "").split() if data.get("scope") else SUBSCRIPTION_SCOPES,
    )


async def begin_subscription_login(
    *, open_browser_automatically: bool = True
) -> tuple[str, PkceCodePair, str]:
    """Start the subscription login flow.

    Returns (auth_url, pkce_pair, state). Caller should:
      1. Tell the user to open auth_url (we try to open the browser)
      2. After authorizing, the user will see a code on the success page
      3. Caller prompts the user to paste the code
      4. Caller calls complete_subscription_login(code, pkce, state)
    """
    pkce = generate_pkce_pair()
    state = generate_state()
    auth_url = build_subscription_authorize_url(pkce, state)

    if open_browser_automatically:
        open_browser(auth_url)

    return auth_url, pkce, state


async def complete_subscription_login(
    pasted: str,
    pkce: PkceCodePair,
    expected_state: str,
) -> SubscriptionAuthResult:
    """Finish subscription login using the pasted code from the success page."""
    # Detect if user pasted the authorize URL by mistake
    if "/oauth/authorize" in pasted:
        return SubscriptionAuthResult(
            success=False,
            error="That's the authorize URL, not the code. After logging in, the success "
                  "page shows an 'Authentication Code'. Copy that and paste it here.",
        )

    code, pasted_state = parse_pasted_code(pasted)

    if not code:
        return SubscriptionAuthResult(
            success=False,
            error="No code found in what you pasted. Copy the value from the "
                  "'Authentication Code' box on the success page.",
        )

    # If the user pasted code#state, verify state for CSRF protection
    if pasted_state and pasted_state != expected_state:
        return SubscriptionAuthResult(
            success=False,
            error="State mismatch — the code didn't come from the login you started. "
                  "Try again from scratch.",
        )

    try:
        token_set = await exchange_subscription_code(
            code=code,
            code_verifier=pkce.code_verifier,
            state=expected_state,
        )
    except Exception as exc:
        return SubscriptionAuthResult(
            success=False,
            error=f"Token exchange failed: {exc}",
        )

    save_oauth_credentials(SUBSCRIPTION_PROVIDER, token_set)
    return SubscriptionAuthResult(success=True, token_set=token_set)


async def get_valid_subscription_token() -> str | None:
    """Get a valid subscription access token, refreshing if needed.

    Returns None if no subscription credentials are saved.
    """
    creds = load_oauth_credentials(SUBSCRIPTION_PROVIDER)
    if creds is None:
        return None

    # If expired, refresh
    if creds.is_expired() and creds.refresh_token:
        try:
            new_creds = await refresh_subscription_token(creds.refresh_token)
            save_oauth_credentials(SUBSCRIPTION_PROVIDER, new_creds)
            return new_creds.access_token
        except Exception as exc:
            logger.warning("Subscription token refresh failed: %s", exc)
            return None

    return creds.access_token


def has_subscription_credentials() -> bool:
    """Check if subscription credentials are saved (without validating)."""
    return load_oauth_credentials(SUBSCRIPTION_PROVIDER) is not None


def logout_subscription() -> None:
    """Remove subscription credentials."""
    clear_oauth_credentials(SUBSCRIPTION_PROVIDER)
