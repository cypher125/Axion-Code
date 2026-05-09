"""Image utilities — clipboard capture, file loading, base64 encoding.

Supports:
- Grabbing screenshots/images from clipboard (Win32, macOS, Linux)
- Loading image files from disk (png, jpg, gif, webp)
- Converting to base64 for API submission
"""

from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path

logger = logging.getLogger(__name__)

# Supported image extensions
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}

# Max image size: 5MB (Anthropic limit is ~20MB but we cap lower for speed)
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def is_image_path(text: str) -> bool:
    """Check if text looks like an image file path."""
    text = text.strip().strip('"').strip("'")
    try:
        p = Path(text)
        return p.suffix.lower() in IMAGE_EXTENSIONS and p.exists()
    except (OSError, ValueError):
        return False


def load_image_file(path: str) -> tuple[str, str] | None:
    """Load an image file and return (media_type, base64_data) or None."""
    p = Path(path.strip().strip('"').strip("'"))
    if not p.exists():
        return None

    suffix = p.suffix.lower()
    media_type = MIME_TYPES.get(suffix)
    if not media_type:
        return None

    try:
        data = p.read_bytes()
        if len(data) > MAX_IMAGE_BYTES:
            logger.warning("Image too large: %d bytes (max %d)", len(data), MAX_IMAGE_BYTES)
            return None
        b64 = base64.b64encode(data).decode("ascii")
        return media_type, b64
    except (OSError, IOError) as exc:
        logger.warning("Failed to read image %s: %s", path, exc)
        return None


def grab_clipboard_image() -> tuple[str, str] | None:
    """Grab an image from the system clipboard.

    Returns (media_type, base64_data) or None if no image on clipboard.
    Works on Windows, macOS, and Linux (with xclip).
    """
    import sys

    if sys.platform == "win32":
        return _clipboard_win32()
    elif sys.platform == "darwin":
        return _clipboard_macos()
    else:
        return _clipboard_linux()


def _clipboard_win32() -> tuple[str, str] | None:
    """Grab clipboard image on Windows using win32clipboard or Pillow."""
    try:
        # Try Pillow's ImageGrab (most reliable on Windows)
        from PIL import ImageGrab
        import io

        img = ImageGrab.grabclipboard()
        if img is None:
            return None

        # Convert to PNG bytes
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()

        if len(data) > MAX_IMAGE_BYTES:
            return None

        b64 = base64.b64encode(data).decode("ascii")
        return "image/png", b64
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("Pillow clipboard grab failed: %s", exc)

    # Fallback: try PowerShell
    try:
        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name

        # PowerShell one-liner to save clipboard image
        ps_cmd = (
            f'Add-Type -AssemblyName System.Windows.Forms; '
            f'$img = [System.Windows.Forms.Clipboard]::GetImage(); '
            f'if ($img) {{ $img.Save("{tmp_path}") }} '
            f'else {{ exit 1 }}'
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, timeout=5,
        )

        if result.returncode == 0:
            p = Path(tmp_path)
            if p.exists() and p.stat().st_size > 0:
                data = p.read_bytes()
                p.unlink(missing_ok=True)
                if len(data) <= MAX_IMAGE_BYTES:
                    b64 = base64.b64encode(data).decode("ascii")
                    return "image/png", b64
            p.unlink(missing_ok=True)
    except Exception as exc:
        logger.debug("PowerShell clipboard grab failed: %s", exc)

    return None


def _clipboard_macos() -> tuple[str, str] | None:
    """Grab clipboard image on macOS using pbpaste/osascript."""
    try:
        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name

        result = subprocess.run(
            ["osascript", "-e",
             f'set fp to POSIX file "{tmp_path}"\n'
             f'try\n'
             f'  set img to the clipboard as «class PNGf»\n'
             f'  set fh to open for access fp with write permission\n'
             f'  write img to fh\n'
             f'  close access fh\n'
             f'on error\n'
             f'  return "no image"\n'
             f'end try'],
            capture_output=True, timeout=5,
        )

        p = Path(tmp_path)
        if p.exists() and p.stat().st_size > 0:
            data = p.read_bytes()
            p.unlink(missing_ok=True)
            if len(data) <= MAX_IMAGE_BYTES:
                b64 = base64.b64encode(data).decode("ascii")
                return "image/png", b64
        p.unlink(missing_ok=True)
    except Exception as exc:
        logger.debug("macOS clipboard grab failed: %s", exc)

    return None


def _clipboard_linux() -> tuple[str, str] | None:
    """Grab clipboard image on Linux using xclip."""
    try:
        import subprocess

        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
            capture_output=True, timeout=5,
        )

        if result.returncode == 0 and result.stdout:
            data = result.stdout
            if len(data) <= MAX_IMAGE_BYTES:
                b64 = base64.b64encode(data).decode("ascii")
                return "image/png", b64
    except FileNotFoundError:
        logger.debug("xclip not found — install xclip for clipboard image support")
    except Exception as exc:
        logger.debug("Linux clipboard grab failed: %s", exc)

    return None


def image_size_description(b64_data: str) -> str:
    """Human-readable size of a base64-encoded image."""
    raw_bytes = len(b64_data) * 3 // 4  # approximate
    if raw_bytes < 1024:
        return f"{raw_bytes} bytes"
    elif raw_bytes < 1024 * 1024:
        return f"{raw_bytes / 1024:.1f} KB"
    else:
        return f"{raw_bytes / (1024 * 1024):.1f} MB"
