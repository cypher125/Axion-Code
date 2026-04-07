"""Tests for OAuth flow."""

from axion.runtime.oauth import (
    OAuthConfig,
    OAuthTokenSet,
    build_authorization_url,
    clear_oauth_credentials,
    generate_pkce_pair,
    generate_state,
    load_oauth_credentials,
    save_oauth_credentials,
)


def test_generate_pkce_pair():
    pair = generate_pkce_pair()
    assert len(pair.code_verifier) > 40
    assert len(pair.code_challenge) > 20
    assert pair.code_verifier != pair.code_challenge


def test_generate_state():
    state = generate_state()
    assert len(state) > 20


def test_build_authorization_url():
    config = OAuthConfig(
        client_id="test-client",
        authorize_url="https://example.com/auth",
        callback_port=4545,
        scopes=["user:inference"],
    )
    pkce = generate_pkce_pair()
    state = generate_state()
    url = build_authorization_url(config, pkce, state)

    assert "https://example.com/auth?" in url
    assert "client_id=test-client" in url
    assert "code_challenge=" in url
    assert "state=" in url


def test_token_expiry():
    import time

    token = OAuthTokenSet(
        access_token="test",
        expires_at=int(time.time()) - 100,
    )
    assert token.is_expired()

    token2 = OAuthTokenSet(
        access_token="test",
        expires_at=int(time.time()) + 3600,
    )
    assert not token2.is_expired()


def test_credential_persistence(tmp_path, monkeypatch):
    # Redirect home to tmp_path
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    token = OAuthTokenSet(
        access_token="sk-test-123",
        refresh_token="rt-456",
        expires_at=9999999999,
        scopes=["read"],
    )
    save_oauth_credentials("test-provider", token)
    loaded = load_oauth_credentials("test-provider")

    assert loaded is not None
    assert loaded.access_token == "sk-test-123"
    assert loaded.refresh_token == "rt-456"

    clear_oauth_credentials("test-provider")
    assert load_oauth_credentials("test-provider") is None
