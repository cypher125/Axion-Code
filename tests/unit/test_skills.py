"""Tests for skill loading and execution."""

from pathlib import Path

from claw.runtime.skills import SkillDefinition, execute_skill, load_skill, resolve_skill


def test_load_skill_with_frontmatter(tmp_path):
    skill_file = tmp_path / "commit.md"
    skill_file.write_text(
        "---\n"
        "name: commit\n"
        "description: Create a git commit\n"
        "---\n"
        "Review changes and create a commit.\n"
        "Args: {{args}}\n"
    )
    skill = load_skill(skill_file)
    assert skill.name == "commit"
    assert "Create a git commit" in skill.description
    assert "Review changes" in skill.content


def test_load_skill_without_frontmatter(tmp_path):
    skill_file = tmp_path / "review.md"
    skill_file.write_text("Review the code for bugs.\n")
    skill = load_skill(skill_file)
    assert skill.name == "review"
    assert "Review the code" in skill.content


def test_execute_skill_with_args():
    skill = SkillDefinition(
        name="test",
        description="test skill",
        content="Fix the bug in {{args}}",
        source_path=Path("/tmp/test.md"),
    )
    result = execute_skill(skill, "main.py")
    assert "main.py" in result


def test_execute_skill_without_args():
    skill = SkillDefinition(
        name="test",
        description="test skill",
        content="Run all tests",
        source_path=Path("/tmp/test.md"),
    )
    result = execute_skill(skill, "")
    assert "Run all tests" in result


def test_resolve_skill_found(tmp_path):
    skills_dir = tmp_path / ".claude" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "deploy.md").write_text("Deploy the app")
    found = resolve_skill("deploy", tmp_path)
    assert found is not None
    assert found.name == "deploy.md"


def test_resolve_skill_not_found(tmp_path):
    assert resolve_skill("nonexistent", tmp_path) is None


def test_resolve_skill_legacy_commands_dir(tmp_path):
    cmds_dir = tmp_path / ".claude" / "commands"
    cmds_dir.mkdir(parents=True)
    (cmds_dir / "lint.md").write_text("Run linter")
    found = resolve_skill("lint", tmp_path)
    assert found is not None
