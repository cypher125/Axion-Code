"""Tests for git workflow operations."""

import subprocess

import pytest

from claw.runtime.git import (
    GitError,
    git_branch,
    git_commit,
    git_create_branch,
    git_log,
    git_status,
)


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repo for testing."""
    subprocess.run(["git", "init", "--quiet"], cwd=str(tmp_path), check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(tmp_path), check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(tmp_path), check=True,
    )
    # Create initial commit
    (tmp_path / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "README.md"], cwd=str(tmp_path), check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit", "--quiet"],
        cwd=str(tmp_path), check=True,
    )
    return tmp_path


def test_git_status(git_repo):
    status = git_status(git_repo)
    assert status.branch
    assert status.clean


def test_git_status_dirty(git_repo):
    (git_repo / "new_file.txt").write_text("hello")
    status = git_status(git_repo)
    assert not status.clean
    assert status.untracked >= 1


def test_git_branch(git_repo):
    branch = git_branch(git_repo)
    assert branch in ("main", "master")


def test_git_log(git_repo):
    commits = git_log(git_repo, n=5)
    assert len(commits) >= 1
    assert "Initial commit" in commits[0].message


def test_git_commit(git_repo):
    (git_repo / "feature.py").write_text("def hello(): pass\n")
    git_commit(git_repo, "Add feature", files=["feature.py"])

    commits = git_log(git_repo, n=5)
    assert "Add feature" in commits[0].message


def test_git_create_branch(git_repo):
    git_create_branch(git_repo, "feature-branch")
    branch = git_branch(git_repo)
    assert branch == "feature-branch"


def test_git_status_not_a_repo(tmp_path):
    with pytest.raises(GitError):
        git_status(tmp_path)
