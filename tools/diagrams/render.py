# =================== AIPass ====================
# Name: render.py
# Description: Diagram kit rasteriser - SVG file to PNG via headless Chrome, Inkscape fallback
# Version: 1.0.0
# Created: 2026-10-19
# Modified: 2026-10-19
# =============================================

"""SVG text to PNG.

Headless Chrome (or Chromium or Edge) renders first because it draws the glow
filters exactly as a browser shows the SVG. Inkscape is used only when no
Chrome-family binary is on PATH. When neither exists, or the chosen renderer
fails, RenderError says so; nothing falls back silently.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

CHROME_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge")
INKSCAPE_NAME = "inkscape"
TIMEOUT_S = 120


class RenderError(RuntimeError):
    """No renderer is available, or the renderer did not produce the PNG."""


def find_renderer() -> tuple[str, str]:
    """Return (kind, executable path) for the first available renderer."""
    for name in CHROME_NAMES:
        found = shutil.which(name)
        if found:
            return "chrome", found
    found = shutil.which(INKSCAPE_NAME)
    if found:
        return "inkscape", found
    tried = ", ".join((*CHROME_NAMES, INKSCAPE_NAME))
    raise RenderError(f"no SVG renderer found on PATH (tried: {tried}); install Chrome/Chromium or Inkscape")


def _chrome_command(exe: str, svg: Path, png: Path, width: int, height: int, profile: Path) -> list[str]:
    """Headless screenshot of the SVG file at exactly width x height, with a throwaway profile."""
    return [
        exe,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-first-run",
        "--no-default-browser-check",
        "--force-device-scale-factor=1",
        f"--user-data-dir={profile}",
        f"--window-size={width},{height}",
        f"--screenshot={png}",
        svg.resolve().as_uri(),
    ]


def _inkscape_command(exe: str, svg: Path, png: Path, width: int, height: int) -> list[str]:
    """Inkscape 1.x export of the SVG to a PNG of width x height."""
    return [
        exe,
        str(svg),
        "--export-type=png",
        f"--export-filename={png}",
        f"--export-width={width}",
        f"--export-height={height}",
    ]


def render(svg: Path, png: Path, width: int, height: int) -> str:
    """Rasterise svg into png at width x height. Returns a one-line description of the renderer used."""
    kind, exe = find_renderer()
    png.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="aipass-diagram-") as tmp:
        out = Path(tmp) / "out.png"
        if kind == "chrome":
            cmd = _chrome_command(exe, svg, out, width, height, Path(tmp) / "profile")
        else:
            cmd = _inkscape_command(exe, svg, out, width, height)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S, check=False)
        except subprocess.TimeoutExpired as exc:
            raise RenderError(f"{kind} ({exe}) timed out after {TIMEOUT_S}s rendering {svg}") from exc
        if proc.returncode != 0 or not out.exists():
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()[-5:]
            raise RenderError(f"{kind} ({exe}) failed on {svg} (exit {proc.returncode}): " + " | ".join(detail))
        png.write_bytes(out.read_bytes())
    return f"{kind}: {exe}"


# =================== END AIPass ====================
