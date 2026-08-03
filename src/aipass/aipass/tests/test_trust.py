# =================== AIPass ====================
# Name: test_trust.py
# Description: Tests for trust CLI commands, init enrollment, setup.sh enrollment
# Version: 1.1.0
# Created: 2026-07-15
# Modified: 2026-08-02
# =============================================

"""Tests for trust/revoke CLI commands and init auto-enrollment.

All tests use tmp dirs + monkeypatch REGISTRY_PATH so they never
touch the real ~/.aipass registry.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from aipass.hooks.apps.handlers.config.trust_registry import (
    enroll,
    is_trusted,
    read_registry,
    revoke,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
SETUP_SH = REPO_ROOT / "setup.sh"


@pytest.fixture(autouse=True)
def _isolate_registry(tmp_path, monkeypatch):
    """Redirect REGISTRY_PATH to a tmp dir so tests never touch ~/.aipass."""
    fake_registry = tmp_path / "trusted_projects.json"
    monkeypatch.setattr(
        "aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH",
        fake_registry,
    )


# ---------------------------------------------------------------------------
# trust_registry direct tests
# ---------------------------------------------------------------------------


def test_enroll_project(tmp_path):
    """enroll() registers a project with .aipass/hooks.json."""
    project = tmp_path / "myproject"
    project.mkdir()
    hooks_dir = project / ".aipass"
    hooks_dir.mkdir()
    hooks_file = hooks_dir / "hooks.json"
    hooks_file.write_text('{"hooks_enabled": true}', encoding="utf-8")

    assert enroll(str(project)) is True
    assert is_trusted(str(project)) is True


def test_enroll_no_hooks_json(tmp_path):
    """enroll() returns False when .aipass/hooks.json is missing."""
    project = tmp_path / "empty"
    project.mkdir()
    assert enroll(str(project)) is False


def test_revoke_project(tmp_path):
    """revoke() removes a previously enrolled project."""
    project = tmp_path / "myproject"
    project.mkdir()
    hooks_dir = project / ".aipass"
    hooks_dir.mkdir()
    hooks_file = hooks_dir / "hooks.json"
    hooks_file.write_text('{"hooks_enabled": true}', encoding="utf-8")

    enroll(str(project))
    assert is_trusted(str(project)) is True

    assert revoke(str(project)) is True
    assert is_trusted(str(project)) is False


def test_revoke_not_enrolled(tmp_path):
    """revoke() returns False cleanly for a non-enrolled project."""
    project = tmp_path / "never_enrolled"
    project.mkdir()
    assert revoke(str(project)) is False


def test_is_trusted_hash_mismatch(tmp_path):
    """is_trusted() returns False when hooks.json content changed after enrollment."""
    project = tmp_path / "myproject"
    project.mkdir()
    hooks_dir = project / ".aipass"
    hooks_dir.mkdir()
    hooks_file = hooks_dir / "hooks.json"
    hooks_file.write_text('{"hooks_enabled": true}', encoding="utf-8")

    enroll(str(project))
    assert is_trusted(str(project)) is True

    hooks_file.write_text('{"hooks_enabled": false, "modified": true}', encoding="utf-8")
    assert is_trusted(str(project)) is False


# ---------------------------------------------------------------------------
# trust CLI module tests
# ---------------------------------------------------------------------------


def test_trust_command_enrolls(tmp_path):
    """aipass trust <path> enrolls the project."""
    from aipass.aipass.apps.modules.trust import handle_command

    project = tmp_path / "proj"
    project.mkdir()
    hooks_dir = project / ".aipass"
    hooks_dir.mkdir()
    (hooks_dir / "hooks.json").write_text("{}", encoding="utf-8")

    assert handle_command("trust", [str(project)]) is True
    assert is_trusted(str(project)) is True


def test_revoke_command_removes(tmp_path):
    """aipass revoke <path> removes enrollment."""
    from aipass.aipass.apps.modules.trust import handle_command

    project = tmp_path / "proj"
    project.mkdir()
    hooks_dir = project / ".aipass"
    hooks_dir.mkdir()
    (hooks_dir / "hooks.json").write_text("{}", encoding="utf-8")

    enroll(str(project))
    assert handle_command("revoke", [str(project)]) is True
    assert is_trusted(str(project)) is False


def test_trust_command_no_hooks_json(tmp_path):
    """aipass trust <path> prints error when hooks.json is missing."""
    from aipass.aipass.apps.modules.trust import handle_command

    project = tmp_path / "bare"
    project.mkdir()
    assert handle_command("trust", [str(project)]) is True
    assert is_trusted(str(project)) is False


def test_revoke_command_not_enrolled(tmp_path):
    """aipass revoke <path> handles non-enrolled project cleanly."""
    from aipass.aipass.apps.modules.trust import handle_command

    project = tmp_path / "ghost"
    project.mkdir()
    assert handle_command("revoke", [str(project)]) is True


def test_trust_command_help():
    """aipass trust --help returns True (handled)."""
    from aipass.aipass.apps.modules.trust import handle_command

    assert handle_command("trust", ["--help"]) is True
    assert handle_command("trust", []) is True


def test_trust_ignores_unrelated_command():
    """handle_command returns False for unrelated commands."""
    from aipass.aipass.apps.modules.trust import handle_command

    assert handle_command("doctor", []) is False


def test_trust_not_a_directory(tmp_path):
    """aipass trust <file> prints error."""
    from aipass.aipass.apps.modules.trust import handle_command

    fake = tmp_path / "not_a_dir.txt"
    fake.write_text("hi", encoding="utf-8")
    assert handle_command("trust", [str(fake)]) is True
    assert is_trusted(str(fake)) is False


# ---------------------------------------------------------------------------
# init enrollment tests
# ---------------------------------------------------------------------------


def test_init_project_enrolls(tmp_path, monkeypatch):
    """init_project auto-enrolls after copying hooks.json."""
    from aipass.aipass.apps.handlers.init.bootstrap import init_project

    monkeypatch.setattr(
        "aipass.aipass.apps.handlers.init.bootstrap.is_throwaway_path",
        lambda p: False,
    )
    monkeypatch.setattr(
        "aipass.aipass.shared.project_home.is_throwaway_path",
        lambda p: False,
    )

    aipass_home = tmp_path / "aipass_home"
    aipass_home.mkdir()
    aipass_dir = aipass_home / ".aipass"
    aipass_dir.mkdir()
    template = aipass_dir / "project_hooks.json"
    template.write_text('{"hooks_enabled": true}', encoding="utf-8")
    (aipass_home / "CLAUDE.md").write_text("# Test", encoding="utf-8")
    monkeypatch.setattr(
        "aipass.aipass.apps.handlers.init.bootstrap._detect_aipass_home",
        lambda: str(aipass_home),
    )

    target = tmp_path / "newproject"
    target.mkdir()
    init_project(target, project_name="test")

    assert is_trusted(str(target.resolve())) is True


def test_init_update_rehashes(tmp_path, monkeypatch):
    """init update re-enrolls after merging hooks.json (hash tracks new content)."""
    from aipass.aipass.apps.handlers.init.bootstrap import init_project, update_project

    monkeypatch.setattr(
        "aipass.aipass.apps.handlers.init.bootstrap.is_throwaway_path",
        lambda p: False,
    )
    monkeypatch.setattr(
        "aipass.aipass.shared.project_home.is_throwaway_path",
        lambda p: False,
    )

    aipass_home = tmp_path / "aipass_home"
    aipass_home.mkdir()
    aipass_dir = aipass_home / ".aipass"
    aipass_dir.mkdir()
    template = aipass_dir / "project_hooks.json"
    template.write_text('{"hooks_enabled": true}', encoding="utf-8")
    (aipass_home / "CLAUDE.md").write_text("# Test", encoding="utf-8")
    monkeypatch.setattr(
        "aipass.aipass.apps.handlers.init.bootstrap._detect_aipass_home",
        lambda: str(aipass_home),
    )

    target = tmp_path / "updproj"
    target.mkdir()
    init_project(target, project_name="test")
    assert is_trusted(str(target.resolve())) is True

    old_reg = read_registry()
    old_hash = old_reg["projects"][str(target.resolve())]["config_hash"]

    new_template = (
        '{"hooks_enabled": true, "SessionStart": '
        '{"new_hook": {"handler": "aipass.hooks.apps.handlers.test.handle", "enabled": true}}}'
    )
    template.write_text(new_template, encoding="utf-8")
    update_project(target)

    new_reg = read_registry()
    new_hash = new_reg["projects"][str(target.resolve())]["config_hash"]
    assert new_hash != old_hash
    assert is_trusted(str(target.resolve())) is True


def test_enroll_project_skips_throwaway_path(tmp_path):
    """_enroll_project() refuses to enroll a pytest/temp-dir path (GH-712 leak fix)."""
    from aipass.aipass.shared.project_home import _enroll_project

    project = tmp_path / "throwaway"
    project.mkdir()
    hooks_dir = project / ".aipass"
    hooks_dir.mkdir()
    (hooks_dir / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")

    assert _enroll_project(project) is False
    assert is_trusted(str(project.resolve())) is False


def test_update_project_reports_trust_enrolled(tmp_path, monkeypatch):
    """update_project()'s result dict flags whether enrollment happened."""
    from aipass.aipass.apps.handlers.init.bootstrap import init_project, update_project

    monkeypatch.setattr(
        "aipass.aipass.apps.handlers.init.bootstrap.is_throwaway_path",
        lambda p: False,
    )
    monkeypatch.setattr(
        "aipass.aipass.shared.project_home.is_throwaway_path",
        lambda p: False,
    )

    aipass_home = tmp_path / "aipass_home"
    aipass_home.mkdir()
    aipass_dir = aipass_home / ".aipass"
    aipass_dir.mkdir()
    template = aipass_dir / "project_hooks.json"
    template.write_text('{"hooks_enabled": true}', encoding="utf-8")
    (aipass_home / "CLAUDE.md").write_text("# Test", encoding="utf-8")
    monkeypatch.setattr(
        "aipass.aipass.apps.handlers.init.bootstrap._detect_aipass_home",
        lambda: str(aipass_home),
    )

    target = tmp_path / "reportproj"
    target.mkdir()
    init_project(target, project_name="test")

    new_template = (
        '{"hooks_enabled": true, "SessionStart": '
        '{"new_hook": {"handler": "aipass.hooks.apps.handlers.test.handle", "enabled": true}}}'
    )
    template.write_text(new_template, encoding="utf-8")
    result = update_project(target)

    assert result["trust_enrolled"] is True


# ---------------------------------------------------------------------------
# trust prune
# ---------------------------------------------------------------------------


def test_prune_removes_stale_entries(tmp_path):
    """aipass trust prune drops entries whose project path no longer exists."""
    from aipass.aipass.apps.modules.trust import handle_command

    live = tmp_path / "live"
    live.mkdir()
    hooks_dir = live / ".aipass"
    hooks_dir.mkdir()
    (hooks_dir / "hooks.json").write_text("{}", encoding="utf-8")
    enroll(str(live))

    gone = tmp_path / "gone"
    gone.mkdir()
    gone_hooks = gone / ".aipass"
    gone_hooks.mkdir()
    (gone_hooks / "hooks.json").write_text("{}", encoding="utf-8")
    enroll(str(gone))
    shutil.rmtree(gone)

    assert handle_command("trust", ["prune"]) is True
    registry = read_registry()
    assert str(live.resolve()) in registry["projects"]
    assert str(gone.resolve()) not in registry["projects"]


def test_enroll_is_idempotent(tmp_path):
    """Enrolling the same project twice leaves exactly ONE entry, not a duplicate.

    setup.sh enrolls the repo it installs on every run (compass #221), so a
    re-install must refresh the existing entry rather than grow the registry.
    """
    project = tmp_path / "reinstalled"
    project.mkdir()
    hooks_dir = project / ".aipass"
    hooks_dir.mkdir()
    (hooks_dir / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")

    assert enroll(str(project)) is True
    assert enroll(str(project)) is True
    assert enroll(str(project)) is True

    registry = read_registry()
    assert list(registry["projects"]) == [str(project.resolve())]
    assert is_trusted(str(project)) is True


def test_enroll_missing_hooks_json_leaves_registry_intact(tmp_path):
    """A failed enroll returns False and does not corrupt/erase existing entries."""
    good = tmp_path / "good"
    good.mkdir()
    good_hooks = good / ".aipass"
    good_hooks.mkdir()
    (good_hooks / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")
    assert enroll(str(good)) is True

    bare = tmp_path / "bare"
    bare.mkdir()
    assert enroll(str(bare)) is False

    registry = read_registry()
    assert list(registry["projects"]) == [str(good.resolve())]
    assert is_trusted(str(good)) is True
    assert is_trusted(str(bare)) is False


# ---------------------------------------------------------------------------
# setup.sh install-time enrollment (compass #221)
#
# These run the REAL bash lines lifted out of setup.sh — not a paraphrase —
# with SCRIPT_DIR/VENV_PYTHON supplied and $HOME redirected at a tmp dir so
# the registry written is a throwaway one.
# ---------------------------------------------------------------------------

_ENROLL_ANCHOR = 'echo "Enrolling this install in the hook trust registry ..."'

# setup.sh is a POSIX installer. On Windows, shutil.which("bash") finds
# System32\bash.exe — the WSL launcher, which exits 1 with no distro installed —
# so a which() check alone does not prove a usable shell.
_NEEDS_POSIX_BASH = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="needs a POSIX bash (Windows 'bash' is the WSL launcher)",
)


def _extract_enroll_block() -> str:
    """Lift setup.sh's enroll block (anchor line -> closing `fi`) verbatim."""
    lines = SETUP_SH.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == _ENROLL_ANCHOR)
    end = next(i for i in range(start, len(lines)) if lines[i] == "fi")
    return "\n".join(lines[start : end + 1])


def _run_enroll_block(script_dir: Path, home: Path) -> subprocess.CompletedProcess:
    """Execute the extracted block under `set -euo pipefail` with a fake HOME."""
    script = "\n".join(
        [
            "set -euo pipefail",
            f'SCRIPT_DIR="{script_dir}"',
            f'VENV_PYTHON="{sys.executable}"',
            "ACTION_NEEDED=()",
            _extract_enroll_block(),
            'echo "REACHED_END action_needed=${#ACTION_NEEDED[@]}"',
        ]
    )
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )


def test_setup_sh_has_enroll_block():
    """setup.sh calls trust_registry.enroll on the repo it just installed."""
    body = SETUP_SH.read_text(encoding="utf-8")
    assert _ENROLL_ANCHOR in body
    block = _extract_enroll_block()
    assert "from aipass.hooks.apps.handlers.config.trust_registry import enroll" in block
    assert "enroll(sys.argv[1])" in block
    # Only ever the repo being installed — never a blanket trust.
    assert '"$SCRIPT_DIR"' in block
    assert "ACTION_NEEDED+=" in block


@_NEEDS_POSIX_BASH
def test_setup_sh_enroll_block_trusts_the_install(tmp_path):
    """Running setup.sh's own enroll lines trusts SCRIPT_DIR, no manual step."""
    repo = tmp_path / "FakeAIPass"
    (repo / ".aipass").mkdir(parents=True)
    (repo / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()

    proc = _run_enroll_block(repo, home)

    assert proc.returncode == 0, proc.stderr
    assert "REACHED_END action_needed=0" in proc.stdout
    assert f"trusted -> {repo}" in proc.stdout
    registry = home / ".aipass" / "trusted_projects.json"
    assert registry.is_file()
    assert str(repo.resolve()) in registry.read_text(encoding="utf-8")


@_NEEDS_POSIX_BASH
def test_setup_sh_enroll_block_fails_honestly(tmp_path):
    """No hooks.json: warn + ACTION NEEDED, but never abort the install."""
    repo = tmp_path / "NoHooks"
    repo.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    proc = _run_enroll_block(repo, home)

    assert proc.returncode == 0, proc.stderr
    assert "REACHED_END action_needed=1" in proc.stdout
    assert "WARN: could not enroll" in proc.stdout
    assert f"trusted -> {repo}" not in proc.stdout


def test_prune_no_stale_entries(tmp_path):
    """aipass trust prune reports cleanly when nothing is stale."""
    from aipass.aipass.apps.modules.trust import handle_command

    live = tmp_path / "live"
    live.mkdir()
    hooks_dir = live / ".aipass"
    hooks_dir.mkdir()
    (hooks_dir / "hooks.json").write_text("{}", encoding="utf-8")
    enroll(str(live))

    assert handle_command("trust", ["prune"]) is True
    registry = read_registry()
    assert str(live.resolve()) in registry["projects"]
