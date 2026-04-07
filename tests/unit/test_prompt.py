"""Tests for system prompt builder."""

from pathlib import Path

from axion.runtime.prompt import (
    SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
    ProjectContext,
    SystemPromptBuilder,
    discover_instruction_files,
)


def test_prompt_builder_basic():
    builder = SystemPromptBuilder()
    sections = builder.build()
    assert len(sections) >= 7
    rendered = builder.render()
    assert "interactive agent" in rendered
    assert "# System" in rendered
    assert "# Doing tasks" in rendered
    assert SYSTEM_PROMPT_DYNAMIC_BOUNDARY in rendered


def test_prompt_builder_with_project_context():
    ctx = ProjectContext(
        cwd=Path("/tmp/test"),
        current_date="2026-04-07",
        git_status="## main\n?? new_file.txt",
    )
    builder = SystemPromptBuilder(project_context=ctx)
    rendered = builder.render()
    # On Windows, path may render with backslashes
    assert "test" in rendered
    assert "2026-04-07" in rendered
    assert "new_file.txt" in rendered


def test_prompt_builder_with_output_style():
    builder = SystemPromptBuilder().with_output_style("Concise", "Be brief.")
    rendered = builder.render()
    assert "Output Style: Concise" in rendered
    assert "Be brief." in rendered


def test_instruction_file_discovery(tmp_path):
    # Create nested directories with CLAUDE.md files
    (tmp_path / "CLAUDE.md").write_text("Root instructions")
    nested = tmp_path / "apps" / "api"
    nested.mkdir(parents=True)
    (nested / "CLAUDE.md").write_text("API instructions")

    files = discover_instruction_files(nested)
    assert len(files) >= 2
    contents = [f.content for f in files]
    assert any("Root instructions" in c for c in contents)
    assert any("API instructions" in c for c in contents)


def test_instruction_file_deduplication(tmp_path):
    nested = tmp_path / "sub"
    nested.mkdir()
    (tmp_path / "CLAUDE.md").write_text("same rules")
    (nested / "CLAUDE.md").write_text("same rules")

    files = discover_instruction_files(nested)
    # Should deduplicate identical content
    assert len(files) == 1


def test_prompt_includes_instruction_files(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("Always use type hints.")
    ctx = ProjectContext.discover(tmp_path)
    builder = SystemPromptBuilder(project_context=ctx)
    rendered = builder.render()
    assert "Always use type hints" in rendered
    assert "Claude instructions" in rendered


def test_prompt_length():
    """System prompt should be substantial, not a stub."""
    builder = SystemPromptBuilder.for_cwd()
    rendered = builder.render()
    # Should be at least a few thousand chars with all sections
    assert len(rendered) > 2000
