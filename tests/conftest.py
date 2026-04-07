"""Shared test fixtures for axion-code test suite."""

import pytest


@pytest.fixture
def tmp_session_dir(tmp_path):
    """Provide a temporary directory for session persistence."""
    session_dir = tmp_path / ".axion" / "sessions"
    session_dir.mkdir(parents=True)
    return session_dir
