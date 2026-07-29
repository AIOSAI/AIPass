# =================== AIPass ====================
# Name: test_trust.py
# Description: Tests for trust CLI commands and init enrollment (DPLAN-0244)
# Version: 1.0.0
# Created: 2026-07-15
# Modified: 2026-07-15
# =============================================

"""Tests for trust/revoke CLI commands and init auto-enrollment.

All tests use tmp dirs + monkeypatch REGISTRY_PATH so they never
touch the real ~/.aipass registry.
"""

import pytest  # pyright: ignore[reportMissingImports]

from aipass.hooks.apps.handlers.config.trust_registry import (
    enroll,
    is_trusted,
    read_registry,
    revoke,
)


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
    import shutil

    shutil.rmtree(gone)

    assert handle_command("trust", ["prune"]) is True
    registry = read_registry()
    assert str(live.resolve()) in registry["projects"]
    assert str(gone.resolve()) not in registry["projects"]


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
