"""Build script for Axion Code — compiles to standalone executable using Nuitka.

Usage:
    python build.py             # Build for current platform
    python build.py --onefile   # Single exe (slower startup, easier distribution)

Requirements:
    pip install nuitka ordered-set

Output:
    dist/axion.exe (Windows)
    dist/axion (Linux/Mac)
"""

import subprocess
import sys
from pathlib import Path


def build(onefile: bool = False) -> None:
    """Build Axion Code as a standalone executable."""
    print("Building Axion Code...")
    print(f"  Platform: {sys.platform}")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  Mode: {'onefile' if onefile else 'standalone'}")
    print()

    cmd = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        "--output-dir=dist",
        "--output-filename=axion",

        # Include all axion packages
        "--include-package=axion",
        "--include-package=axion.api",
        "--include-package=axion.cli",
        "--include-package=axion.commands",
        "--include-package=axion.commands.handlers",
        "--include-package=axion.plugins",
        "--include-package=axion.runtime",
        "--include-package=axion.runtime.mcp",
        "--include-package=axion.telemetry",
        "--include-package=axion.tools",
        "--include-package=axion.compat_harness",

        # Include dependencies
        "--include-package=httpx",
        "--include-package=rich",
        "--include-package=click",
        "--include-package=prompt_toolkit",
        "--include-package=pydantic",

        # Disable console window on Windows (optional)
        # "--windows-disable-console",

        # Company info
        "--company-name=Cyrus",
        "--product-name=Axion Code",
        "--file-version=0.1.0",
        "--product-version=0.1.0",
        "--file-description=AI Coding Assistant CLI",

        # Entry point
        "axion/cli/main.py",
    ]

    if onefile:
        cmd.insert(2, "--onefile")

    print(f"  Command: {' '.join(cmd[:5])}...")
    print()

    result = subprocess.run(cmd)

    if result.returncode == 0:
        print()
        print("Build successful!")
        print(f"  Output: dist/axion{'.exe' if sys.platform == 'win32' else ''}")
    else:
        print()
        print(f"Build failed with exit code {result.returncode}")
        sys.exit(1)


if __name__ == "__main__":
    onefile = "--onefile" in sys.argv
    build(onefile=onefile)
