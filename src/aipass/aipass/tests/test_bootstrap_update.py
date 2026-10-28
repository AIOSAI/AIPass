# =================== AIPass ====================
# Name: test_bootstrap_update.py
# Description: Tests for update_project: the plan, stamp-only, the retrofit, seeds and cleanup
# Version: 1.6.0
# Created: 2026-10-08
# Modified: 2026-10-28
# =============================================

"""Tests for apps/handlers/init/bootstrap.py: update_project and the plans it reads."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every module this file imports parses and imports

import json
import os
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from aipass.aipass.apps.handlers.init.bootstrap import (
    init_project,
    update_project,
)
from aipass.aipass.apps.handlers.init import bootstrap
from aipass.aipass.apps.handlers.init.scaffold_manifest import MANIFEST_REL, UpdateIgnoreUnreadable, read_manifest
from aipass.aipass.apps.handlers.init.scaffold_manifest import sha256_text as sc_sha256
from aipass.aipass.shared import scaffold_content as sc
from aipass.aipass.tests.support_bootstrap import _expected_aipass_home


def test_update_project_raises_if_no_registry(tmp_path):
    """ValueError when target has no *_REGISTRY.json (not an AIPass project)."""
    target = tmp_path / "bare"
    target.mkdir()

    with pytest.raises(ValueError, match="No AIPass project found"):
        update_project(target)


def test_update_project_return_dict_structure(tmp_path):
    """Return dict contains all required keys."""
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="upd")

    result = update_project(target)

    assert set(result.keys()) == {
        # Exact set: a key added without a decision is one @hooks and doctor may start reading.
        "project_name",
        "target",
        "aipass_home",
        "aipass_version",
        "stamped_version",
        "stamp_pending",
        "stamp_only",
        "applied",
        "pending",
        "files",
        "handlers",
        "trust_reenrol",
        "backup_dir",
        # Legacy shape — the CLI and older pins read these.
        "updated_files",
        "already_current",
        "kept_files",
        "ignored_files",
        "skipped_files",
        "removed_files",
        "trust_enrolled",
        "notes",
    }
    assert result["project_name"] == "UPD"
    assert result["target"] == str(target.resolve())
    assert isinstance(result["updated_files"], list)
    assert isinstance(result["already_current"], list)
    assert isinstance(result["skipped_files"], list)


def _windows_newline_world(monkeypatch):
    """Make this Linux process translate newlines the way Windows does.

    ``write_text`` with ``newline=None`` writes ``os.linesep``: a no-op here, ``\r\n`` on
    Windows. The fake translates only when ``newline`` is unset, so a writer pinning
    ``newline="\n"`` passes straight through.
    """
    real_write_text = Path.write_text

    def windows_write_text(self, data, encoding=None, errors=None, newline=None):
        if newline is None:
            # newline="" then stops the real writer translating a second time.
            return real_write_text(self, data.replace("\n", "\r\n"), encoding=encoding, errors=errors, newline="")
        return real_write_text(self, data, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(Path, "write_text", windows_write_text)


def test_managed_files_land_lf_even_where_the_platform_translates(tmp_path, monkeypatch):
    """Every file init writes holds LF bytes, on a platform that would give CRLF.

    The manifest hashes bytes on disk, the plan hashes the template string: they
    agree only if what lands on disk IS the string.
    """
    _windows_newline_world(monkeypatch)
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="crlf")

    for rel in read_manifest(target)["files"]:
        path = target / rel
        if path.is_file():
            assert b"\r\n" not in path.read_bytes(), f"{rel} landed with CRLF"

    prep = target / ".agents" / "skills" / "prep" / "SKILL.md"
    manifest = json.loads((target / ".aipass" / "scaffold_manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"][".agents/skills/prep/SKILL.md"] == sc_sha256(sc.prep_skill_md())
    assert prep.read_bytes() == sc.prep_skill_md().encode("utf-8")


def test_update_after_init_is_clean_where_the_platform_translates(tmp_path, monkeypatch):
    """Windows newlines, reproduced on Linux: a fresh project must be current, run after run."""
    _windows_newline_world(monkeypatch)
    monkeypatch.setattr(
        "aipass.aipass.apps.handlers.init.bootstrap.is_throwaway_path",
        lambda home: home != _expected_aipass_home(),
    )
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="crlfupd")

    first = update_project(target)
    second = update_project(target)

    assert first["updated_files"] == []
    assert first["kept_files"] == []
    assert second["updated_files"] == []
    assert not (target / ".agents" / "skills" / "prep" / "SKILL.md.aipass-new").exists()


def _age_the_stamp(target: Path) -> None:
    """Rewind a project's manifest to an older AIPass, leaving every file alone.

    The state after a release that changed no template: files current, record behind.
    """
    manifest_path = target / ".aipass" / "scaffold_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["aipass_version"] = "0.0.1"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def test_a_plan_that_only_moves_the_version_is_stamp_only(tmp_path):
    """Nothing written but the manifest -> stamp_only, still pending.

    The stamp IS a write, so exit 2 keeps meaning "a plan to read"; stamp_only says
    no FILE would change, which lets the plan apply without a go.
    """
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="stamponly")
    _age_the_stamp(target)

    plan = update_project(target, apply=False)

    assert plan["stamp_pending"] is True
    assert plan["pending"] is True
    assert plan["stamp_only"] is True
    assert not any(entry["writes"] for entry in plan["files"])
    assert plan["handlers"] == []


def test_a_current_project_is_not_stamp_only(tmp_path):
    """Nothing to write AND nothing to stamp is "current", not "stamp only".

    Pins the stamp half of the predicate, which every pin that ages the stamp first misses.
    """
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="current")

    plan = update_project(target, apply=False)

    assert plan["stamp_pending"] is False
    assert plan["pending"] is False
    assert plan["stamp_only"] is False


def test_a_kept_file_still_needing_its_sidecar_is_not_stamp_only(tmp_path):
    """A kept-local file with no sidecar yet means apply WOULD write: the plan still needs a go."""
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="keptnew")
    _age_the_stamp(target)
    (target / ".agents" / "skills" / "prep" / "SKILL.md").write_text("# my own prep\n", encoding="utf-8")

    plan = update_project(target, apply=False)

    kept = [e for e in plan["files"] if e["action"] == "kept-local"]
    assert len(kept) == 1 and kept[0]["writes"] is True
    assert plan["stamp_only"] is False


def test_a_kept_file_whose_sidecar_is_current_stays_stamp_only(tmp_path):
    """The Vera-Studio shape: kept files already settled beside their template.

    Kept is a standing decision, not a pending write, so settled sidecars stay stamp-only.
    """
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="keptold")
    (target / ".agents" / "skills" / "prep" / "SKILL.md").write_text("# my own prep\n", encoding="utf-8")
    update_project(target)  # writes the sidecar once
    _age_the_stamp(target)

    plan = update_project(target, apply=False)

    kept = [e for e in plan["files"] if e["action"] == "kept-local"]
    assert len(kept) == 1 and kept[0]["writes"] is False
    assert plan["stamp_only"] is True


def test_applying_a_stamp_only_plan_changes_nothing_but_the_stamp(tmp_path):
    """The receipt's promise on disk: tracked files byte-identical, no backup, the version moved."""
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="stampapply")
    _age_the_stamp(target)
    before = {rel: (target / rel).read_bytes() for rel in read_manifest(target)["files"] if (target / rel).is_file()}

    result = update_project(target)

    assert result["stamp_only"] is True
    assert result["updated_files"] == []
    assert result["backup_dir"] is None
    after = {rel: (target / rel).read_bytes() for rel in before}
    assert after == before
    manifest = json.loads((target / ".aipass" / "scaffold_manifest.json").read_text(encoding="utf-8"))
    assert manifest["aipass_version"] == result["aipass_version"] != "0.0.1"


def test_update_project_already_current_after_init(tmp_path, monkeypatch):
    """Running update immediately after init reports all managed files as already current."""
    monkeypatch.setattr(
        "aipass.aipass.apps.handlers.init.bootstrap.is_throwaway_path",
        lambda home: home != _expected_aipass_home(),
    )
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="fresh")

    result = update_project(target)

    assert len(result["updated_files"]) == 0
    assert len(result["already_current"]) >= 5


def test_update_project_idempotent(tmp_path, monkeypatch):
    """Running update twice in a row produces no changes on second run."""
    monkeypatch.setattr(
        "aipass.aipass.apps.handlers.init.bootstrap.is_throwaway_path",
        lambda home: home != _expected_aipass_home(),
    )
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="idem")

    result1 = update_project(target)
    result2 = update_project(target)

    assert result1["updated_files"] == result2["updated_files"]
    assert result1["already_current"] == result2["already_current"]


def test_update_project_keeps_a_managed_file_the_project_edited(tmp_path):
    """The conffile rule: an edited managed file is KEPT, template lands beside it.

    The update must never undo a manager's own work. the prep skill is generated locally,
    so the pin holds with or without a detectable AIPASS_HOME.
    """
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="mod")

    prep = target / ".agents" / "skills" / "prep" / "SKILL.md"
    prep.write_text("# My own prep\n", encoding="utf-8")

    result = update_project(target)

    assert str(prep.resolve()) in result["kept_files"]
    assert str(prep.resolve()) not in result["updated_files"]
    assert prep.read_text(encoding="utf-8") == "# My own prep\n"
    sidecar = prep.with_name("SKILL.md.aipass-new")
    assert sidecar.is_file()
    assert sidecar.read_text(encoding="utf-8") == sc.prep_skill_md()

    entry = next(e for e in result["files"] if e["path"] == ".agents/skills/prep/SKILL.md")
    assert entry["action"] == "kept-local"


def test_update_project_rewrites_a_managed_file_nobody_touched(tmp_path):
    """The other arm: hash still matches the manifest, so the template wins.

    Recording the on-disk hash simulates AIPass having written it before the template moved.
    """
    import hashlib

    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="mod")

    prep = target / ".agents" / "skills" / "prep" / "SKILL.md"
    prep.write_text("# superseded template\n", encoding="utf-8")
    manifest_path = target / ".aipass" / "scaffold_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][".agents/skills/prep/SKILL.md"] = hashlib.sha256(prep.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = update_project(target)

    assert str(prep.resolve()) in result["updated_files"]
    assert prep.read_text(encoding="utf-8") == sc.prep_skill_md()
    assert not prep.with_name("SKILL.md.aipass-new").exists()

    backups = list((target / ".aipass" / ".backup").glob("scaffold_*/.agents/skills/prep/SKILL.md"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "# superseded template\n"


def test_update_project_never_touches_the_registry_or_readme(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="skip")

    (target / "README.md").write_text("# My custom README\n", encoding="utf-8")

    result = update_project(target)

    skipped = result["skipped_files"]
    assert any("REGISTRY" in s for s in skipped)
    assert any("README.md" in s for s in skipped)
    assert not any(".gitignore" in s for s in skipped)

    assert (target / "README.md").read_text(encoding="utf-8") == "# My custom README\n"


@pytest.mark.parametrize("throwaway_home", [False, True], ids=["real_home", "throwaway_home"])
def test_update_project_creates_missing_managed_dirs(tmp_path, monkeypatch, throwaway_home):
    """update_project recreates .aipass/ and .claude/; settings.local.json only for a non-throwaway home.

    The home's throwaway answer is pinned: a checkout under /tmp (CI, seedgo's audit env) reads as one.
    Mutant: bootstrap's `aipass_home and not is_throwaway_path(...)` -> `aipass_home` -> red on throwaway_home.
    """
    monkeypatch.setattr(bootstrap, "is_throwaway_path", lambda home: throwaway_home)
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="recover")

    import shutil

    shutil.rmtree(target / ".aipass")
    shutil.rmtree(target / ".claude")

    result = update_project(target)

    assert result["aipass_home"] == _expected_aipass_home()
    assert (target / ".claude" / "settings.json").exists()
    local_settings = target.resolve() / ".claude" / "settings.local.json"
    assert (str(local_settings) in result["updated_files"]) is not throwaway_home
    assert local_settings.exists() is not throwaway_home
    # tier0_kernel, tier1_navmap, .aipass/.gitignore, hooks.json, settings.json, prep, /codex, /opencode,
    # plus settings.local.json for a real home
    assert len(result["updated_files"]) == (8 if throwaway_home else 9)
    assert str((target / "AGENTS.md").resolve()) in result["already_current"]


def test_update_project_skipped_files_count(tmp_path):
    """update_project skips the registry and README, the project's own."""
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="count")

    result = update_project(target)

    assert len(result["skipped_files"]) == 2


def _make_nested_project(tmp_path):
    """<host>/projects/<name> with registries at both levels (is_projects_child == True)."""
    host = tmp_path / "host"
    host.mkdir()
    (host / "HOST_REGISTRY.json").write_text("{}", encoding="utf-8")
    projects = host / "projects"
    projects.mkdir()
    target = projects / "myapp"
    target.mkdir()
    (target / "MYAPP_REGISTRY.json").write_text("{}", encoding="utf-8")
    return host, target


def test_update_project_retrofits_claude_md_excludes_into_existing_settings(tmp_path, monkeypatch):
    """update_project adds claudeMdExcludes to an existing settings.local.json that only has env.AIPASS_HOME."""
    host, target = _make_nested_project(tmp_path)
    monkeypatch.setattr(bootstrap, "is_throwaway_path", lambda home: home != str(host))
    monkeypatch.setattr(bootstrap, "_detect_aipass_home", lambda: str(host))

    claude_dir = target / ".claude"
    claude_dir.mkdir()
    local_settings_path = claude_dir / "settings.local.json"
    local_settings_path.write_text(json.dumps({"env": {"AIPASS_HOME": str(host)}}, indent=2) + "\n", encoding="utf-8")

    result = bootstrap.update_project(target)

    data = json.loads(local_settings_path.read_text(encoding="utf-8"))
    assert data["env"]["AIPASS_HOME"] == str(host)
    assert data["claudeMdExcludes"] == [
        (host / "CLAUDE.md").as_posix(),
        (host / ".claude" / "CLAUDE.md").as_posix(),
        (host / "AGENTS.md").as_posix(),
        (host / ".claude" / "AGENTS.md").as_posix(),
    ]
    assert str(local_settings_path) in result["updated_files"]
    entry = next(e for e in result["files"] if e["path"] == ".claude/settings.local.json")
    assert entry["reason"] == ("merge adds claudeMdExcludes CLAUDE.md, .claude/CLAUDE.md, AGENTS.md, .claude/AGENTS.md")


def _plan_reason_for(tmp_path, monkeypatch, existing: dict) -> str:
    host, target = _make_nested_project(tmp_path)
    monkeypatch.setattr(bootstrap, "is_throwaway_path", lambda home: home != str(host))
    monkeypatch.setattr(bootstrap, "_detect_aipass_home", lambda: str(host))
    claude_dir = target / ".claude"
    claude_dir.mkdir()
    text = json.dumps(existing, indent=2).replace("{host}", host.as_posix()) + "\n"
    (claude_dir / "settings.local.json").write_text(text, encoding="utf-8")
    result = bootstrap.update_project(target, apply=False)
    return next(e for e in result["files"] if e["path"] == ".claude/settings.local.json")["reason"]


def test_update_plan_names_only_the_agents_md_pair_when_env_already_holds_the_home(tmp_path, monkeypatch):
    """The fixed 'merge adds AIPASS_HOME' every project read while only the AGENTS.md pair was added."""
    existing = {
        "env": {"AIPASS_HOME": str(tmp_path / "host")},
        "claudeMdExcludes": ["{host}/CLAUDE.md", "{host}/.claude/CLAUDE.md"],
    }
    reason = _plan_reason_for(tmp_path, monkeypatch, existing)
    assert reason == "merge adds claudeMdExcludes AGENTS.md, .claude/AGENTS.md"


def test_update_plan_names_the_env_key_and_the_fence_when_both_grow(tmp_path, monkeypatch):
    reason = _plan_reason_for(
        tmp_path, monkeypatch, {"claudeMdExcludes": ["{host}/CLAUDE.md", "{host}/.claude/CLAUDE.md"]}
    )
    assert reason == "merge adds AIPASS_HOME; adds claudeMdExcludes AGENTS.md, .claude/AGENTS.md"


def test_update_plan_names_a_moved_home_as_changed_not_added(tmp_path, monkeypatch):
    fenced = ["{host}/CLAUDE.md", "{host}/.claude/CLAUDE.md", "{host}/AGENTS.md", "{host}/.claude/AGENTS.md"]
    reason = _plan_reason_for(
        tmp_path, monkeypatch, {"env": {"AIPASS_HOME": "an-older-home"}, "claudeMdExcludes": fenced}
    )
    assert reason == "merge changes AIPASS_HOME"


def test_update_project_claude_md_excludes_retrofit_is_idempotent(tmp_path, monkeypatch):
    """Running update_project a second time after the retrofit reports no further changes."""
    host, target = _make_nested_project(tmp_path)
    monkeypatch.setattr(bootstrap, "is_throwaway_path", lambda home: home != str(host))
    monkeypatch.setattr(bootstrap, "_detect_aipass_home", lambda: str(host))

    claude_dir = target / ".claude"
    claude_dir.mkdir()
    local_settings_path = claude_dir / "settings.local.json"
    local_settings_path.write_text(json.dumps({"env": {"AIPASS_HOME": str(host)}}, indent=2) + "\n", encoding="utf-8")

    result1 = bootstrap.update_project(target)
    before = local_settings_path.read_text(encoding="utf-8")
    result2 = bootstrap.update_project(target)
    after = local_settings_path.read_text(encoding="utf-8")

    assert str(local_settings_path) in result1["updated_files"]
    assert str(local_settings_path) in result2["already_current"]
    assert str(local_settings_path) not in result2["updated_files"]
    assert before == after


def test_update_project_preserves_custom_claude_md_excludes_entries(tmp_path, monkeypatch):
    """update_project unions in the official fence entries without dropping a user's hand-added ones."""
    host, target = _make_nested_project(tmp_path)
    monkeypatch.setattr(bootstrap, "is_throwaway_path", lambda home: home != str(host))
    monkeypatch.setattr(bootstrap, "_detect_aipass_home", lambda: str(host))

    claude_dir = target / ".claude"
    claude_dir.mkdir()
    local_settings_path = claude_dir / "settings.local.json"
    custom_entry = "/custom/extra/CLAUDE.md"
    local_settings_path.write_text(
        json.dumps(
            {"env": {"AIPASS_HOME": str(host)}, "claudeMdExcludes": [custom_entry]},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    bootstrap.update_project(target)

    data = json.loads(local_settings_path.read_text(encoding="utf-8"))
    assert data["claudeMdExcludes"] == [
        custom_entry,
        (host / "CLAUDE.md").as_posix(),
        (host / ".claude" / "CLAUDE.md").as_posix(),
        (host / "AGENTS.md").as_posix(),
        (host / ".claude" / "AGENTS.md").as_posix(),
    ]


def test_update_project_keeps_an_edited_agents_md_and_writes_the_template_beside_it(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="sync")
    template = (target / "AGENTS.md").read_text(encoding="utf-8")
    (target / "AGENTS.md").write_text("# My own AGENTS.md\n", encoding="utf-8")

    result = update_project(target)

    assert (target / "AGENTS.md").read_text(encoding="utf-8") == "# My own AGENTS.md\n"
    assert (target / "AGENTS.md.aipass-new").read_text(encoding="utf-8") == template
    entry = next(e for e in result["files"] if e["path"] == "AGENTS.md")
    assert entry["action"] == "kept-local"


def test_update_project_rewrites_an_unedited_agents_md_from_an_older_template(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="sync")
    template = (target / "AGENTS.md").read_text(encoding="utf-8")
    (target / "AGENTS.md").write_text("# The older template\n", encoding="utf-8")
    manifest = target / MANIFEST_REL
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["files"]["AGENTS.md"] = sc_sha256("# The older template\n")
    manifest.write_text(json.dumps(document), encoding="utf-8")

    result = update_project(target)

    assert (target / "AGENTS.md").read_text(encoding="utf-8") == template
    assert next(e for e in result["files"] if e["path"] == "AGENTS.md")["action"] == "update"


def test_update_project_never_overwrites_an_agents_md_whose_edit_a_seed_era_manifest_adopted(tmp_path):
    """Seed-era updates recorded the on-disk AGENTS.md hash: an edit reads as unmodified there."""
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="sync")
    (target / "AGENTS.md").write_text("# Edited under the seed rule\n", encoding="utf-8")
    manifest = target / MANIFEST_REL
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document.pop("agents_md_managed")
    document["files"]["AGENTS.md"] = sc_sha256("# Edited under the seed rule\n")
    manifest.write_text(json.dumps(document), encoding="utf-8")

    update_project(target)

    assert (target / "AGENTS.md").read_text(encoding="utf-8") == "# Edited under the seed rule\n"
    assert (target / "AGENTS.md.aipass-new").is_file()
    assert "AGENTS.md" not in json.loads(manifest.read_text(encoding="utf-8"))["files"]


def test_update_project_retires_a_claude_md_shadowing_agents_md_and_keeps_its_text(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="sync")
    (target / "CLAUDE.md").write_text("# My own CLAUDE.md\n", encoding="utf-8")
    (target / ".claude" / "CLAUDE.md").write_text("# Claimed\n", encoding="utf-8")
    (target / ".updateignore").write_text(".claude/CLAUDE.md\n", encoding="utf-8")

    planned = update_project(target, apply=False)

    assert (target / "CLAUDE.md").is_file()
    entry = next(e for e in planned["files"] if e["path"] == "CLAUDE.md")
    assert entry["action"] == "retire"
    assert "shadows AGENTS.md (differs)" in entry["reason"]
    assert next(e for e in planned["files"] if e["path"] == ".claude/CLAUDE.md")["action"] == "skipped"

    update_project(target)

    assert not (target / "CLAUDE.md").exists()
    assert (target / "CLAUDE.md(disabled)").read_text(encoding="utf-8") == "# My own CLAUDE.md\n"
    assert (target / ".claude" / "CLAUDE.md").read_text(encoding="utf-8") == "# Claimed\n"


def test_update_project_creates_missing_agents_md(tmp_path):
    """update creates AGENTS.md if it was deleted from the project."""
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="miss")

    agents_md = target / "AGENTS.md"
    agents_md.unlink()

    result = update_project(target)

    assert agents_md.exists()
    assert str(agents_md.resolve()) in result["updated_files"]
    content = agents_md.read_text(encoding="utf-8")
    assert "# MISS" in content
    assert not (target / "CLAUDE.md").exists()


def test_update_project_agents_md_already_current(tmp_path):
    """update reports AGENTS.md as already_current when unchanged."""
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="cur")

    result = update_project(target)

    assert any("AGENTS.md" in f for f in result["already_current"])
    assert not any("AGENTS.md" in f for f in result["updated_files"])


def test_update_project_removes_stale_global_prompt(tmp_path):
    """update removes retired .aipass/aipass_global_prompt.md."""
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="cruft")

    stale = target / ".aipass" / "aipass_global_prompt.md"
    stale.write_text("# old\n", encoding="utf-8")

    result = update_project(target)

    assert not stale.exists()
    assert str(stale) in result["removed_files"]


def test_update_project_cleanup_does_not_touch_user_files(tmp_path):
    """Cruft cleanup never removes user-owned files."""
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="safe")

    readme = target / "README.md"
    registry = target / "SAFE_REGISTRY.json"

    result = update_project(target)

    assert readme.exists()
    assert registry.exists()
    assert len(result["removed_files"]) == 0


def test_update_project_removed_files_in_result(tmp_path):
    """Mutant: removed_files reported empty after a retire -> red."""
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="rkey")
    stale = target / ".aipass" / "aipass_global_prompt.md"
    stale.write_text("# old\n", encoding="utf-8")

    result = update_project(target)

    assert result["removed_files"] == [str(stale)]


def test_update_project_cleanup_no_stale_is_noop(tmp_path):
    """When no stale files exist, removed_files is empty."""
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="clean")

    result = update_project(target)

    assert result["removed_files"] == []


def test_update_project_skips_files_the_owner_protected(tmp_path):
    """.updateignore outranks every other rule — no write, no backup, no sidecar.

    Covers all three spellings: a relative path, a bare filename at any depth, a directory.
    """
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="owned")

    (target / ".updateignore").write_text(
        "# mine now\n\n.agents/skills/prep/SKILL.md\ntier0_kernel.md\n.claude/\n",
        encoding="utf-8",
    )
    prep = target / ".agents" / "skills" / "prep" / "SKILL.md"
    prep.write_text("# my own prep\n", encoding="utf-8")

    result = update_project(target)

    assert str(prep.resolve()) in result["ignored_files"]
    assert str(prep.resolve()) not in result["kept_files"]
    assert prep.read_text(encoding="utf-8") == "# my own prep\n"
    assert not prep.with_name("SKILL.md.aipass-new").exists()
    assert not (target / ".aipass" / ".backup").exists()

    entry = next(e for e in result["files"] if e["path"] == ".agents/skills/prep/SKILL.md")
    assert entry["action"] == "skipped"
    assert entry["reason"] == ".updateignore"

    protected = {e["path"] for e in result["files"] if e["action"] == "skipped"}
    assert ".aipass/tier0_kernel.md" in protected
    assert ".claude/settings.json" in protected


def test_update_project_leaves_a_protected_file_out_of_the_manifest(tmp_path):
    """No recorded hash for an ignored file, so un-ignoring it behaves like backfill.

    A recorded on-disk hash would make the next update read the file as unmodified
    and overwrite the very thing the owner protected.
    """
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="unignore")

    prep = target / ".agents" / "skills" / "prep" / "SKILL.md"
    (target / ".updateignore").write_text(".agents/skills/prep/SKILL.md\n", encoding="utf-8")
    prep.write_text("# my own prep\n", encoding="utf-8")
    update_project(target)

    manifest = json.loads((target / ".aipass" / "scaffold_manifest.json").read_text(encoding="utf-8"))
    assert ".agents/skills/prep/SKILL.md" not in manifest["files"]

    # Un-ignore: the file is now unknown provenance, so it is kept, not clobbered.
    (target / ".updateignore").unlink()
    result = update_project(target)

    assert str(prep.resolve()) in result["kept_files"]
    assert prep.read_text(encoding="utf-8") == "# my own prep\n"


def _files_and_bytes(root: Path) -> dict:
    """Every file under *root* with its bytes; symlinked directories (the .venv link) are not entered."""
    return {
        Path(d, f).relative_to(root).as_posix(): Path(d, f).read_bytes()
        for d, _dirs, names in os.walk(root)
        for f in names
        if not Path(d, f).is_symlink()
    }


def test_update_refuses_when_the_ignore_file_is_there_but_unreadable(tmp_path):
    """A .updateignore that exists but cannot be read stops the update before any write.

    Read as no patterns, it would let the update overwrite the files the owner claimed.
    What reading a directory raises is the platform's choice, so the test reads it first.
    Mutant: read_ignore's unreadable branch -> `return []` -> red.
    """
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="claimed")
    ignore = target / ".updateignore"
    ignore.rename(target / "seeded_updateignore")
    ignore.mkdir()
    with pytest.raises(OSError) as asked:  # what this platform raises for the same read
        ignore.read_text(encoding="utf-8")
    platform_error = asked.value
    before = _files_and_bytes(target)

    with pytest.raises(UpdateIgnoreUnreadable, match=r"\.updateignore") as refused:
        update_project(target)

    assert type(refused.value.__cause__) is type(platform_error)
    assert _files_and_bytes(target) == before


def test_update_project_repoints_a_dangling_venv_link(tmp_path, monkeypatch):
    """apply=True repoints a .venv link whose home moved instead of raising FileExistsError."""
    host, target = _make_nested_project(tmp_path)
    (host / ".venv").mkdir()
    monkeypatch.setattr(bootstrap, "is_throwaway_path", lambda home: home != str(host))
    monkeypatch.setattr(bootstrap, "_detect_aipass_home", lambda: str(host))
    (target / ".venv").symlink_to(tmp_path / "old_home" / ".venv")

    bootstrap.update_project(target, apply=True)

    assert (target / ".venv").resolve() == (host / ".venv").resolve()


def _a_project_from_before_the_shared_skills(tmp_path, prep_text: str) -> Path:
    """A project init made when /prep was .claude/commands/prep.md: that file, no skill, no link."""
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="legacy")
    (target / ".claude" / "skills").unlink()
    skill = target / ".agents" / "skills" / "prep" / "SKILL.md"
    skill.unlink()
    legacy = target / ".claude" / "commands" / "prep.md"
    legacy.write_text(prep_text, encoding="utf-8")
    manifest_path = target / ".aipass" / "scaffold_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["files"][".agents/skills/prep/SKILL.md"]
    manifest["files"][".claude/commands/prep.md"] = sc_sha256(sc.prep_md())
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return target


class TestSharedSkillsUpdate:
    """init update moves an old project's /prep into the shared skill and links .claude/skills."""

    def test_an_unedited_legacy_prep_is_retired_for_the_skill_and_the_link_is_made(self, tmp_path):
        target = _a_project_from_before_the_shared_skills(tmp_path, sc.prep_md())

        result = update_project(target)

        legacy = target / ".claude" / "commands" / "prep.md"
        assert not legacy.exists()
        assert (target / ".claude" / "commands" / "prep(disabled).md").read_text(encoding="utf-8") == sc.prep_md()
        skill = target / ".agents" / "skills" / "prep" / "SKILL.md"
        assert skill.read_text(encoding="utf-8") == sc.prep_skill_md()
        assert (target / ".claude" / "skills").resolve() == (target / ".agents" / "skills").resolve()
        entry = next(e for e in result["files"] if e["path"] == ".claude/commands/prep.md")
        assert entry["action"] == "retire"
        assert entry["reason"].startswith("replaced by .agents/skills/prep/SKILL.md")
        assert str(legacy) in result["removed_files"]

    def test_an_edited_legacy_prep_is_kept_and_named(self, tmp_path):
        target = _a_project_from_before_the_shared_skills(tmp_path, "# my own prep\n")

        result = update_project(target)

        legacy = target / ".claude" / "commands" / "prep.md"
        assert legacy.read_text(encoding="utf-8") == "# my own prep\n"
        entry = next(e for e in result["files"] if e["path"] == ".claude/commands/prep.md")
        assert entry["action"] == "current"
        assert entry["writes"] is False
        assert "edited here, kept" in entry["reason"]

    def test_the_dry_run_plans_the_link_and_the_retire_and_writes_neither(self, tmp_path):
        target = _a_project_from_before_the_shared_skills(tmp_path, sc.prep_md())

        result = update_project(target, apply=False)

        actions = {e["path"]: e["action"] for e in result["files"]}
        assert actions[".claude/skills"] == "create"
        assert actions[".claude/commands/prep.md"] == "retire"
        assert result["pending"] is True
        assert not (target / ".claude" / "skills").exists()
        assert (target / ".claude" / "commands" / "prep.md").is_file()


_SWITCH = {".claude/commands/codex.md": sc.codex_command_md(), ".codex/skills/claude/SKILL.md": sc.claude_skill_md()}


class TestProviderSwitchPair:
    """init writes /codex and $claude into a project; the update adds them to an older one, edits kept."""

    def test_init_writes_both_switch_files_verbatim_and_hashes_them(self, tmp_path):
        target = tmp_path / "proj"
        target.mkdir()
        init_project(target, project_name="switch")

        manifest = read_manifest(target)["files"]
        for rel, body in _SWITCH.items():
            assert (target / rel).read_text(encoding="utf-8") == body
            assert manifest[rel] == sc_sha256(body)

    def test_update_adds_a_missing_switch_file_and_keeps_an_edited_one(self, tmp_path):
        target = tmp_path / "proj"
        target.mkdir()
        init_project(target, project_name="older")
        command = target / ".claude" / "commands" / "codex.md"
        command.unlink()
        skill = target / ".codex" / "skills" / "claude" / "SKILL.md"
        skill.write_text("# my own switch\n", encoding="utf-8")
        manifest_path = target / ".aipass" / "scaffold_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        del manifest["files"][".claude/commands/codex.md"]
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

        result = update_project(target)

        assert command.read_text(encoding="utf-8") == sc.codex_command_md()
        assert skill.read_text(encoding="utf-8") == "# my own switch\n"
        actions = {e["path"]: e["action"] for e in result["files"]}
        assert actions[".claude/commands/codex.md"] == "create"
        assert actions[".codex/skills/claude/SKILL.md"] == "kept-local"

    def test_an_older_project_is_planned_and_given_the_seven_opencode_files_verbatim(self, tmp_path):
        target = tmp_path / "proj"
        target.mkdir()
        init_project(target, project_name="older")
        opencode = {rel: body() for rel, body in bootstrap.SWITCH_PAIR if "opencode" in rel}
        manifest_path = target / ".aipass" / "scaffold_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for rel in opencode:
            (target / rel).rename(tmp_path / rel.replace("/", "_"))
            del manifest["files"][rel]
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

        plan = update_project(target, apply=False)
        planned = {e["path"]: e["action"] for e in plan["files"]}
        on_disk_before = [rel for rel in opencode if (target / rel).exists()]
        update_project(target)

        assert len(opencode) == 7
        assert {rel: planned[rel] for rel in opencode} == dict.fromkeys(opencode, "create")
        assert on_disk_before == []
        for rel, body in opencode.items():
            assert (target / rel).read_text(encoding="utf-8") == body
            assert read_manifest(target)["files"][rel] == sc_sha256(body)

    def test_a_hand_copy_matching_the_template_is_current_and_adopted(self, tmp_path):
        target = tmp_path / "proj"
        target.mkdir()
        init_project(target, project_name="copied")
        manifest_path = target / ".aipass" / "scaffold_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for rel in _SWITCH:
            del manifest["files"][rel]
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

        result = update_project(target)

        entries = {e["path"]: e for e in result["files"]}
        for rel, body in _SWITCH.items():
            assert entries[rel]["action"] == "current"
            assert entries[rel]["writes"] is False
            assert read_manifest(target)["files"][rel] == sc_sha256(body)


def test_update_project_appends_missing_gitignore_lines_under_a_dated_comment_and_keeps_owner_lines(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="merge")
    owner = "# mine\nzeta/\n!tools/keep/\nlogs/\n"
    (target / ".gitignore").write_text(owner, encoding="utf-8")

    planned = update_project(target, apply=False)

    entry = next(e for e in planned["files"] if e["path"] == ".gitignore")
    assert entry["action"] == "update"
    assert ".chroma/" in entry["lines"] and "logs/" not in entry["lines"]
    assert (target / ".gitignore").read_text(encoding="utf-8") == owner

    update_project(target)

    merged = (target / ".gitignore").read_text(encoding="utf-8")
    head, added = merged.split("\n# Added by aipass init update ", 1)
    assert head == owner
    assert added.splitlines()[1:] == entry["lines"]
    again = next(e for e in update_project(target)["files"] if e["path"] == ".gitignore")
    assert (again["action"], again["writes"]) == ("current", False)


def test_update_project_seeds_missing_ignore_files_once_and_never_rewrites_them(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="seeds")
    (target / ".updateignore").rename(target / "seeded_updateignore")
    (target / ".aipass" / ".gitignore").write_text("*\n", encoding="utf-8")

    result = update_project(target)

    assert (target / ".updateignore").read_text(encoding="utf-8") == sc.updateignore()
    assert (target / ".aipass" / ".gitignore").read_text(encoding="utf-8") == "*\n"
    entry = next(e for e in result["files"] if e["path"] == ".updateignore")
    assert entry["action"] == "create"


def test_update_project_retires_an_unedited_old_hook_script_the_manifest_knows_and_leaves_an_edited_one(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="hooks")
    hooks_dir = target / ".claude" / "hooks"
    hooks_dir.mkdir()
    (hooks_dir / "old.py").write_text("print('aipass')\n", encoding="utf-8")
    (hooks_dir / "edited.py").write_text("print('mine')\n", encoding="utf-8")
    manifest = target / MANIFEST_REL
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["files"][".claude/hooks/old.py"] = sc_sha256("print('aipass')\n")
    document["files"][".claude/hooks/edited.py"] = sc_sha256("print('aipass')\n")
    manifest.write_text(json.dumps(document), encoding="utf-8")

    update_project(target)

    assert not (hooks_dir / "old.py").exists()
    assert (hooks_dir / "old(disabled).py").read_text(encoding="utf-8") == "print('aipass')\n"
    assert (hooks_dir / "edited.py").read_text(encoding="utf-8") == "print('mine')\n"


def test_every_scaffold_switch_text_equals_its_repo_root_file_byte_for_byte():
    """Each scaffold text is a copy of the AIPass root file; an edit to either side ships stale to every init."""
    root = Path(_expected_aipass_home())
    missing = [rel for rel, _ in bootstrap.SWITCH_PAIR if not (root / rel).is_file()]
    if missing:
        pytest.skip(f"repo-root switch files absent in this clone: {', '.join(missing)}")
    drifted = [rel for rel, body in bootstrap.SWITCH_PAIR if (root / rel).read_bytes() != body().encode("utf-8")]
    assert drifted == [], f"scaffold text differs from the root file: {', '.join(drifted)}"
