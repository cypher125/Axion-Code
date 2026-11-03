"""Tests for command parsing."""

from axion.commands.parsing import (
    CommandParseError,
    ParsedCommand,
    parse_slash_command,
    render_help,
)
from axion.commands.registry import CommandRegistry


def test_parse_help():
    result = parse_slash_command("/help")
    assert isinstance(result, ParsedCommand)
    assert result.name == "help"


def test_parse_with_args():
    result = parse_slash_command("/model claude-opus-4-6")
    assert isinstance(result, ParsedCommand)
    assert result.name == "model"
    assert result.args == "claude-opus-4-6"


def test_parse_alias():
    result = parse_slash_command("/q")
    assert isinstance(result, ParsedCommand)
    assert result.name == "quit"


def test_parse_unknown():
    result = parse_slash_command("/foobar")
    assert isinstance(result, CommandParseError)
    assert "Unknown command" in result.message


def test_not_slash_command():
    result = parse_slash_command("hello world")
    assert isinstance(result, CommandParseError)


def test_render_help():
    text = render_help()
    assert "Available commands" in text
    assert "/help" in text
    assert "/quit" in text


def test_command_registry():
    reg = CommandRegistry()
    assert reg.get("help") is not None
    assert reg.get("nonexistent") is None
    assert len(reg.all_specs()) > 10




def test_help_lists_skills_and_no_duplicate_review():
    from axion.commands.parsing import render_help, render_help_detail
    from axion.commands.registry import CommandRegistry
    reg = CommandRegistry()
    reg.register_skill_command("mydeploy", "deploy the app")
    h = render_help(reg)
    assert "mydeploy" in h and "deploy the app" in h        # skill shows in /help
    assert h.count("/review") == 1                          # no duplicate review
    # detail lookup works and shows usage
    d = render_help_detail("rewind", reg)
    assert d and "Usage:" in d
