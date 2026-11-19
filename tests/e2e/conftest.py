# =================== AIPass ====================
# Name: conftest.py
# Description: Session-scoped fixtures for the e2e wiring harness
# Version: 1.0.0
# Created: 2026-06-03
# =============================================

"""Session-scoped pytest fixtures for the end-to-end WIRING harness.

These fixtures build the aipass wheel and install it into a FRESH, clean venv
(never the repo .venv, never ``pip install -e``) so the tests in this package
exercise the real installed package the way a fresh install would.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

# Repo root = three levels up from this file: <repo>/tests/e2e/conftest.py
REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class CleanVenv:
    """Paths into a clean venv with the aipass wheel installed."""

    root: Path
    python: Path
    pip: Path
    aipass: Path
    drone: Path
    site_packages: Path


@pytest.fixture(scope="session")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the aipass wheel from the repo root and return its path.

    Uses ``python -m build --wheel`` (build backend = hatchling, package =
    aipass 2.5.0). The outer environment running pytest only needs ``build``
    and ``pytest`` installed — this fixture produces the wheel that the
    clean-venv fixture then installs.
    """
    dist_dir = tmp_path_factory.mktemp("wheel_dist")
    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(dist_dir), str(REPO_ROOT)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"wheel build failed (exit {result.returncode}).\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    wheels = sorted(dist_dir.glob("*.whl"))
    if not wheels:
        raise RuntimeError(f"no wheel produced in {dist_dir}. build output:\n{result.stdout}")
    return wheels[0]


@pytest.fixture(scope="session")
def clean_venv(wheel: Path, tmp_path_factory: pytest.TempPathFactory) -> CleanVenv:
    """Create a fresh venv and install the wheel into it.

    NOT the repo .venv, NOT an editable install — a brand-new venv with the
    built wheel installed, so we test the wiring of the real package.
    """
    venv_root = tmp_path_factory.mktemp("clean_venv")

    # Build the venv with the current interpreter — no hardcoded "python".
    result = subprocess.run(
        [sys.executable, "-m", "venv", str(venv_root)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"venv creation failed:\n{result.stdout}\n{result.stderr}")

    bin_dir = venv_root / "bin"
    py = bin_dir / "python"
    pip = bin_dir / "pip"

    install = subprocess.run(
        [str(py), "-m", "pip", "install", str(wheel)],
        capture_output=True,
        text=True,
    )
    if install.returncode != 0:
        raise RuntimeError(
            f"wheel install into clean venv failed:\nSTDOUT:\n{install.stdout}\nSTDERR:\n{install.stderr}"
        )

    # Resolve site-packages from the venv's own interpreter — portable across
    # python minor versions instead of guessing lib/pythonX.Y.
    sp = subprocess.run(
        [str(py), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        capture_output=True,
        text=True,
    )
    if sp.returncode != 0:
        raise RuntimeError(f"could not resolve site-packages:\n{sp.stdout}\n{sp.stderr}")
    site_packages = Path(sp.stdout.strip())

    return CleanVenv(
        root=venv_root,
        python=py,
        pip=pip,
        aipass=bin_dir / "aipass",
        drone=bin_dir / "drone",
        site_packages=site_packages,
    )
