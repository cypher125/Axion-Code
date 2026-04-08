"""Built-in slash command handlers: /commit, /undo, /review, /test, /init-project.

These are high-value features that differentiate Axion from other tools.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# /commit — Auto-commit with AI-generated message
# ---------------------------------------------------------------------------

def handle_commit_command(args: str, cwd: Path | None = None) -> str:
    """Stage changes and commit with an AI-generated message.

    Usage:
        /commit              — auto-generate commit message from diff
        /commit fix auth bug — use provided message
    """
    actual_cwd = str(cwd or Path.cwd())

    # Check for uncommitted changes
    status = _run_git(["status", "--porcelain"], actual_cwd)
    if not status.strip():
        return "Nothing to commit — working tree is clean."

    # Stage all changes
    _run_git(["add", "-A"], actual_cwd)

    # Get diff for message generation
    diff = _run_git(["diff", "--cached", "--stat"], actual_cwd)

    if args.strip():
        # User provided a message
        message = args.strip()
    else:
        # Generate message from the diff
        diff_detail = _run_git(["diff", "--cached"], actual_cwd)
        message = _generate_commit_message(diff_detail[:2000])

    # Commit
    result = _run_git(["commit", "-m", message], actual_cwd)
    if "nothing to commit" in result.lower():
        return "Nothing to commit."

    return f"Committed:\n  {message}\n\n{diff.strip()}"


def _generate_commit_message(diff: str) -> str:
    """Generate a commit message from a diff (heuristic, no AI call)."""
    lines = diff.strip().splitlines()

    # Count additions/deletions
    additions = sum(1 for ln in lines if ln.startswith("+") and not ln.startswith("+++"))
    deletions = sum(1 for ln in lines if ln.startswith("-") and not ln.startswith("---"))

    # Get changed files
    files = set()
    for line in lines:
        if line.startswith("diff --git"):
            parts = line.split()
            if len(parts) >= 4:
                files.add(parts[3].lstrip("b/"))
        elif line.startswith("--- a/") or line.startswith("+++ b/"):
            path = line[6:]
            if path != "/dev/null":
                files.add(path)

    file_list = ", ".join(sorted(files)[:3])
    if len(files) > 3:
        file_list += f" (+{len(files) - 3} more)"

    if additions > 0 and deletions == 0:
        action = "Add"
    elif deletions > 0 and additions == 0:
        action = "Remove"
    else:
        action = "Update"

    return f"{action} {file_list} ({additions}+ {deletions}-)"


# ---------------------------------------------------------------------------
# /undo — Revert last AI change via git
# ---------------------------------------------------------------------------

def handle_undo_command(args: str, cwd: Path | None = None) -> str:
    """Undo the last change by reverting to previous git state.

    Usage:
        /undo         — undo last commit (soft reset)
        /undo hard    — undo and discard all changes
        /undo file.py — restore a specific file
    """
    actual_cwd = str(cwd or Path.cwd())
    target = args.strip()

    if not target or target == "last":
        # Soft reset — undoes the commit but keeps changes staged
        result = _run_git(["reset", "--soft", "HEAD~1"], actual_cwd)
        if "fatal" in result.lower():
            return f"Undo failed: {result}"
        return "Undone — last commit reverted (changes kept staged). Use /undo hard to discard."

    if target == "hard":
        # Hard reset — discard everything
        result = _run_git(["reset", "--hard", "HEAD~1"], actual_cwd)
        if "fatal" in result.lower():
            return f"Undo failed: {result}"
        return "Undone — last commit and all changes discarded."

    # Restore a specific file
    file_path = target
    result = _run_git(["checkout", "HEAD", "--", file_path], actual_cwd)
    if "error" in result.lower() or "fatal" in result.lower():
        # Try with restore instead
        result = _run_git(["restore", file_path], actual_cwd)
        if "error" in result.lower() or "fatal" in result.lower():
            return f"Could not restore {file_path}: {result}"
    return f"Restored {file_path} to last committed version."


# ---------------------------------------------------------------------------
# /review — Code review mode
# ---------------------------------------------------------------------------

def handle_review_command(args: str, cwd: Path | None = None) -> str:
    """Analyze recent changes for bugs, issues, and improvements.

    Returns a structured review prompt for the AI to process.

    Usage:
        /review           — review uncommitted changes
        /review HEAD~3    — review last 3 commits
        /review file.py   — review a specific file
    """
    actual_cwd = str(cwd or Path.cwd())
    target = args.strip()

    if not target:
        # Review uncommitted changes
        diff = _run_git(["diff"], actual_cwd)
        staged = _run_git(["diff", "--cached"], actual_cwd)
        combined = ""
        if staged.strip():
            combined += f"=== Staged Changes ===\n{staged}\n\n"
        if diff.strip():
            combined += f"=== Unstaged Changes ===\n{diff}\n\n"
        if not combined.strip():
            return "No changes to review. Make some changes first."

        # Truncate if too long
        if len(combined) > 5000:
            combined = combined[:5000] + "\n... (truncated)"

        return (
            "REVIEW_MODE: Please review these code changes for:\n"
            "1. Bugs or logic errors\n"
            "2. Security vulnerabilities\n"
            "3. Performance issues\n"
            "4. Missing error handling\n"
            "5. Code style improvements\n\n"
            f"{combined}\n\n"
            "Provide a structured review with severity ratings (critical/warning/info)."
        )

    if target.startswith("HEAD"):
        # Review specific commits
        diff = _run_git(["diff", f"{target}..HEAD"], actual_cwd)
        if not diff.strip():
            return f"No changes found in range {target}..HEAD"
        if len(diff) > 5000:
            diff = diff[:5000] + "\n... (truncated)"
        return (
            f"REVIEW_MODE: Review the changes from {target} to HEAD:\n\n"
            f"{diff}\n\n"
            "Check for bugs, security issues, and improvements."
        )

    # Review a specific file
    file_path = Path(actual_cwd) / target
    if not file_path.exists():
        return f"File not found: {target}"

    content = file_path.read_text(encoding="utf-8", errors="replace")
    if len(content) > 5000:
        content = content[:5000] + "\n... (truncated)"

    return (
        f"REVIEW_MODE: Review this file for bugs, security issues, and improvements:\n\n"
        f"File: {target}\n"
        f"```\n{content}\n```\n\n"
        "Provide a structured review with line numbers and severity ratings."
    )


# ---------------------------------------------------------------------------
# /test — Generate tests for a file
# ---------------------------------------------------------------------------

def handle_test_command(args: str, cwd: Path | None = None) -> str:
    """Generate tests for a file or module.

    Usage:
        /test src/auth.py           — generate tests for auth.py
        /test src/api/              — generate tests for all files in api/
        /test src/auth.py --pytest  — use pytest framework
    """
    actual_cwd = cwd or Path.cwd()
    target = args.strip()

    if not target:
        return (
            "Usage: /test <file_or_dir>\n"
            "  /test src/auth.py        — generate tests for a file\n"
            "  /test src/api/           — generate tests for a directory\n"
            "  /test src/auth.py pytest — use pytest framework"
        )

    # Parse framework preference
    framework = "pytest"  # default
    parts = target.split()
    if len(parts) > 1 and parts[-1] in ("pytest", "unittest", "jest", "mocha", "vitest"):
        framework = parts[-1]
        target = " ".join(parts[:-1])

    file_path = actual_cwd / target

    if file_path.is_file():
        content = file_path.read_text(encoding="utf-8", errors="replace")
        if len(content) > 4000:
            content = content[:4000] + "\n... (truncated)"

        return (
            f"TEST_MODE: Generate comprehensive {framework} tests for this file:\n\n"
            f"File: {target}\n"
            f"```\n{content}\n```\n\n"
            f"Requirements:\n"
            f"- Use {framework} framework\n"
            f"- Test all public functions/methods\n"
            f"- Include edge cases and error cases\n"
            f"- Use descriptive test names\n"
            f"- Write the test file to the appropriate tests/ directory"
        )

    if file_path.is_dir():
        files = list(file_path.rglob("*.py"))[:10]
        if not files:
            files = list(file_path.rglob("*.ts"))[:10]
        if not files:
            files = list(file_path.rglob("*.js"))[:10]

        file_list = "\n".join(f"  - {f.relative_to(actual_cwd)}" for f in files)
        return (
            f"TEST_MODE: Generate {framework} tests for these files:\n\n"
            f"{file_list}\n\n"
            f"Read each file, then generate comprehensive tests."
        )

    return f"Not found: {target}"


# ---------------------------------------------------------------------------
# /init-project — Project template scaffolding
# ---------------------------------------------------------------------------

TEMPLATES = {
    "react": {
        "name": "React + TypeScript",
        "questions": "What features? (auth/database/tailwind/none)",
        "description": "React app with TypeScript, Vite, and optional features",
    },
    "nextjs": {
        "name": "Next.js Full-Stack",
        "questions": "Database? (postgres/sqlite/none), Auth? (y/n)",
        "description": "Next.js with App Router, TypeScript, Tailwind",
    },
    "django": {
        "name": "Django REST API",
        "questions": "Database? (postgres/sqlite), Auth type? (jwt/session/oauth)",
        "description": "Django + DRF with PostgreSQL, JWT auth, Docker",
    },
    "fastapi": {
        "name": "FastAPI Backend",
        "questions": "Database? (postgres/sqlite), Add Docker? (y/n)",
        "description": "FastAPI with Pydantic, SQLAlchemy, async",
    },
    "express": {
        "name": "Express.js API",
        "questions": "TypeScript? (y/n), Database? (postgres/mongodb/none)",
        "description": "Node.js Express with optional TypeScript and database",
    },
    "cli": {
        "name": "Python CLI Tool",
        "questions": "Framework? (click/typer/argparse)",
        "description": "Python CLI with Click, tests, and packaging",
    },
    "flask": {
        "name": "Flask Web App",
        "questions": "Database? (postgres/sqlite), Add auth? (y/n)",
        "description": "Flask with Blueprints, SQLAlchemy, templates",
    },
    "chrome-ext": {
        "name": "Chrome Extension",
        "questions": "Manifest version? (v3), Need popup? (y/n)",
        "description": "Chrome extension with manifest v3",
    },
}


def handle_init_project_command(args: str, cwd: Path | None = None) -> str:
    """Scaffold a new project from a template with AI guidance.

    Usage:
        /init-project              — show available templates
        /init-project react        — create a React project
        /init-project fastapi      — create a FastAPI backend
    """
    template = args.strip().lower()

    if not template:
        lines = ["Available project templates:", ""]
        for key, info in TEMPLATES.items():
            lines.append(f"  /init-project {key:12} — {info['name']}: {info['description']}")
        lines.append("")
        lines.append("Example: /init-project react")
        return "\n".join(lines)

    if template not in TEMPLATES:
        available = ", ".join(TEMPLATES.keys())
        return f"Unknown template: {template}\nAvailable: {available}"

    info = TEMPLATES[template]
    return (
        f"INIT_PROJECT_MODE: Create a new {info['name']} project.\n\n"
        f"Template: {template}\n"
        f"Description: {info['description']}\n\n"
        f"Ask the user these questions first:\n"
        f"  - Project name?\n"
        f"  - {info['questions']}\n\n"
        f"Then create the complete project structure with working code:\n"
        f"1. Create all necessary config files\n"
        f"2. Create source files with real implementation (not just boilerplate)\n"
        f"3. Create a README.md with setup instructions\n"
        f"4. Create a .gitignore\n"
        f"5. If database needed, create initial schema/migrations\n"
        f"6. If auth needed, create working auth implementation\n"
    )


# ---------------------------------------------------------------------------
# Git helper
# ---------------------------------------------------------------------------

def _run_git(args: list[str], cwd: str) -> str:
    """Run a git command and return output."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True, text=True, cwd=cwd, timeout=15,
            encoding="utf-8", errors="replace",
        )
        return result.stdout + result.stderr
    except (subprocess.SubprocessError, FileNotFoundError):
        return "git command failed"
