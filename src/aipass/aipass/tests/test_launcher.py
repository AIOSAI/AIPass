# =================== AIPass ====================
# Name: test_launcher.py
# Description: Tests for the repo-root ./aipass cold-clone launcher
# Version: 1.0.0
# Created: 2026-07-05
# Modified: 2026-07-05
# =============================================

"""Tests for the repo-root ./aipass cold-clone launcher (bash script)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="bash launcher requires Unix")

REPO_ROOT = Path(__file__).resolve().parents[4]
LAUNCHER = REPO_ROOT / "aipass"

_EXEC_BITS = 0o111


def _make_executable(path: Path) -> None:
    """Set executable bits on a file."""
    path.chmod(path.stat().st_mode | _EXEC_BITS)


def _isolated_launcher(tmp_path: Path) -> Path:
    """Copy the launcher to a temp dir (isolated from real .venv)."""
    dest = tmp_path / "aipass"
    shutil.copy2(LAUNCHER, dest)
    _make_executable(dest)
    return dest


def _fake_venv_binary(tmp_path: Path, body: str) -> Path:
    """Create a fake .venv/bin/aipass that runs the given bash body."""
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    fake = venv_bin / "aipass"
    fake.write_text(f"#!/usr/bin/env bash\n{body}\n")
    _make_executable(fake)
    return fake


class TestLauncherProperties:
    """Verify the launcher file's basic properties."""

    def test_exists(self):
        """Launcher file exists at repo root."""
        assert LAUNCHER.is_file()

    def test_executable(self):
        """Launcher has executable permission."""
        assert os.access(LAUNCHER, os.X_OK)

    def test_shebang(self):
        """Launcher starts with bash shebang."""
        first_line = LAUNCHER.read_text().splitlines()[0]
        assert first_line == "#!/usr/bin/env bash"

    def test_no_python_imports(self):
        """Launcher contains no Python imports (stdlib-only bash)."""
        content = LAUNCHER.read_text()
        assert "import " not in content
        assert "from " not in content


class TestPreSetupHelp:
    """Pre-setup (no venv): bare ./aipass prints help text."""

    def test_no_args_shows_help(self, tmp_path):
        """No args and no venv prints setup instructions."""
        launcher = _isolated_launcher(tmp_path)
        result = subprocess.run(
            ["bash", str(launcher)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert "not set up yet" in result.stdout
        assert "./aipass install" in result.stdout

    def test_unknown_verb_shows_help(self, tmp_path):
        """Unknown verb pre-setup prints help, not an error."""
        launcher = _isolated_launcher(tmp_path)
        result = subprocess.run(
            ["bash", str(launcher), "doctor"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert "not set up yet" in result.stdout

    def test_help_mentions_quick_start(self, tmp_path):
        """Help text includes the Quick start snippet."""
        launcher = _isolated_launcher(tmp_path)
        result = subprocess.run(
            ["bash", str(launcher)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert "Quick start" in result.stdout
        assert "git clone" in result.stdout


class TestPreSetupInstall:
    """Pre-setup: ./aipass install delegates to setup.sh."""

    def test_install_calls_setup_sh(self, tmp_path):
        """./aipass install execs setup.sh in the same directory."""
        launcher = _isolated_launcher(tmp_path)
        setup = tmp_path / "setup.sh"
        setup.write_text('#!/usr/bin/env bash\necho "SETUP_CALLED $@"\n')
        _make_executable(setup)

        result = subprocess.run(
            ["bash", str(launcher), "install"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert "SETUP_CALLED" in result.stdout

    def test_install_passes_flags(self, tmp_path):
        """Flags after 'install' pass through to setup.sh."""
        launcher = _isolated_launcher(tmp_path)
        setup = tmp_path / "setup.sh"
        setup.write_text('#!/usr/bin/env bash\necho "FLAGS:$@"\n')
        _make_executable(setup)

        result = subprocess.run(
            ["bash", str(launcher), "install", "--no-chat"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert "--no-chat" in result.stdout

    def test_install_passes_path_flag(self, tmp_path):
        """--path and its value pass through to setup.sh."""
        launcher = _isolated_launcher(tmp_path)
        setup = tmp_path / "setup.sh"
        setup.write_text('#!/usr/bin/env bash\necho "FLAGS:$@"\n')
        _make_executable(setup)

        result = subprocess.run(
            ["bash", str(launcher), "install", "--path", str(tmp_path / "home")],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert "--path" in result.stdout


class TestPostSetupForwarding:
    """Post-setup: forwards to the venv binary."""

    def test_forwards_to_venv_binary(self, tmp_path):
        """With venv binary present, verbs forward to it."""
        launcher = _isolated_launcher(tmp_path)
        _fake_venv_binary(tmp_path, 'echo "VENV_AIPASS $@"')

        result = subprocess.run(
            ["bash", str(launcher), "doctor"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert "VENV_AIPASS doctor" in result.stdout

    def test_forwards_install_post_setup(self, tmp_path):
        """Post-setup ./aipass install goes to venv binary, not setup.sh."""
        launcher = _isolated_launcher(tmp_path)
        _fake_venv_binary(tmp_path, 'echo "VENV_AIPASS $@"')

        result = subprocess.run(
            ["bash", str(launcher), "install"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert "VENV_AIPASS install" in result.stdout

    def test_no_args_forwards_post_setup(self, tmp_path):
        """Post-setup bare ./aipass forwards to venv binary."""
        launcher = _isolated_launcher(tmp_path)
        _fake_venv_binary(tmp_path, 'echo "VENV_AIPASS_NOARGS"')

        result = subprocess.run(
            ["bash", str(launcher)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert "VENV_AIPASS_NOARGS" in result.stdout
