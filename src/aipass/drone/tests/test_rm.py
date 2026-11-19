# =================== AIPass ====================
# Name: test_rm.py
# Description: drone rm: containment, carve-outs, the sibling fence and the admin crossing
# Version: 1.5.0
# Created: 2026-06-02
# Modified: 2026-11-18
# =============================================

"""Tests for apps/modules/rm.py and the rm_handler containment it drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(covered_elsewhere) — the deletion record's contents, pinned in tests/test_deletion_log.py
# sentry: no-test-needed(covered_elsewhere) — the broker lane of a sandboxed delete, pinned in tests/test_broker.py
# sentry: no-test-needed(covered_elsewhere) — rm from a deleted working directory, pinned in tests/test_no_cwd_sweep.py
# sentry: no-test-needed(covered_elsewhere) — the move to .archive, --stale and the dot guard, pinned in tests/test_rm_archive.py, tests/test_rm_stale.py and tests/test_rm_dot.py

import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.drone.apps.handlers import rm_handler
from aipass.drone.apps.handlers.rm_handler import (
    DOT_FLAG,
    check_carveouts,
    check_containment,
    get_allowed_roots,
    safe_delete,
)

from .conftest import RAIL, rail_answers, rm_ledger

POSIX_TMP = Path(os.sep, "tmp")
# Written here, not read from the product: a carve-out dropped there must fail a test.
CARVEOUTS = (".agents", ".aipass", ".codex", ".git", ".trinity")

#: A mode-0 folder only stops a caller the kernel holds to permissions: not as root.
_PERMISSIONS_DO_NOT_BIND = os.geteuid() == 0
_PERMISSIONS_REASON = "needs file permissions that bind the caller"


@pytest.fixture()
def _patch_roots(project_dir):
    """Patch get_allowed_roots to use deterministic test roots."""
    tmpdir = Path(tempfile.gettempdir()).resolve()
    roots = [project_dir.resolve()]
    seen = set(roots)
    slash_tmp = POSIX_TMP.resolve()
    if slash_tmp not in seen:
        seen.add(slash_tmp)
        roots.append(slash_tmp)
    if tmpdir not in seen:
        seen.add(tmpdir)
        roots.append(tmpdir)
    with patch(
        "aipass.drone.apps.handlers.rm_handler.get_allowed_roots",
        return_value=roots,
    ):
        yield


class TestGetAllowedRoots:
    def test_includes_temp_dir(self):
        roots = get_allowed_roots()
        tmpdir = Path(tempfile.gettempdir()).resolve()
        assert tmpdir in roots

    def test_includes_slash_tmp(self, tmp_path, monkeypatch):
        """The /tmp carve-out puts the canonical tmp root in roots by itself.

        $TMPDIR is moved off /tmp first: left there, the system-temp root hides a deleted carve-out.
        """
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        tempfile.tempdir = None
        try:
            roots = get_allowed_roots()
            assert tmp_path.resolve() in roots
            assert POSIX_TMP.resolve() in roots
        finally:
            tempfile.tempdir = None

    def test_includes_project_root_when_in_project(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        roots = get_allowed_roots()
        assert project_dir.resolve() in roots

    def test_temp_dir_always_present_even_without_project(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        roots = get_allowed_roots()
        tmpdir = Path(tempfile.gettempdir()).resolve()
        assert tmpdir in roots

    def test_tmpdir_and_slash_tmp_both_present_when_different(self, monkeypatch):
        """When $TMPDIR != /tmp, both must appear in roots."""
        fake_tmpdir = POSIX_TMP / "claude-9999"
        fake_tmpdir.mkdir(exist_ok=True)
        try:
            monkeypatch.setenv("TMPDIR", str(fake_tmpdir))
            tempfile.tempdir = None
            roots = get_allowed_roots()
            resolved_roots = set(roots)
            assert POSIX_TMP.resolve() in resolved_roots
            assert fake_tmpdir.resolve() in resolved_roots
        finally:
            tempfile.tempdir = None

    def test_roots_are_deduplicated(self):
        roots = get_allowed_roots()
        assert len(roots) == len(set(roots))


class TestCheckContainment:
    def test_allows_child_of_root(self, tmp_path):
        root = tmp_path.resolve()
        child = (tmp_path / "sub" / "file.txt").resolve()
        allowed, reason = check_containment(child, [root])
        assert allowed is True
        assert reason == ""

    def test_refuses_root_itself(self, tmp_path):
        root = tmp_path.resolve()
        allowed, reason = check_containment(root, [root])
        assert allowed is False
        assert "root directory itself" in reason

    def test_refuses_outside_path(self, tmp_path):
        root = tmp_path.resolve()
        outside = (tmp_path.parent / f"{tmp_path.name}_outside" / "secret.txt").resolve()
        allowed, reason = check_containment(outside, [root])
        assert allowed is False
        assert "outside allowed roots" in reason

    def test_allows_second_root(self, tmp_path):
        root1 = (tmp_path / "a").resolve()
        root2 = (tmp_path / "b").resolve()
        child = (tmp_path / "b" / "file.txt").resolve()
        allowed, _ = check_containment(child, [root1, root2])
        assert allowed is True

    def test_refuses_empty_roots(self, tmp_path):
        child = (tmp_path / "file.txt").resolve()
        allowed, _reason = check_containment(child, [])
        assert allowed is False


class TestAllowDeletion:
    @pytest.mark.usefixtures("_patch_roots")
    def test_delete_dir_in_tmp(self):
        target = Path(tempfile.mkdtemp())
        try:
            (target / "file.txt").write_text("data", encoding="utf-8")
            results = safe_delete([str(target)])
            assert results[0][1] is True
            assert not target.exists()
        finally:
            if target.exists():
                shutil.rmtree(target)

    @pytest.mark.usefixtures("_patch_roots")
    def test_delete_nested_tmp_dir(self):
        """e.g. tempdir/claude-1000/<x>."""
        parent = Path(tempfile.mkdtemp())
        target = parent / "nested"
        target.mkdir()
        (target / "data.txt").write_text("hello", encoding="utf-8")
        try:
            results = safe_delete([str(target)])
            assert results[0][1] is True
            assert not target.exists()
        finally:
            if parent.exists():
                shutil.rmtree(parent)

    @pytest.mark.usefixtures("_patch_roots")
    def test_delete_file_in_project(self, project_dir):
        target = project_dir / "build" / "output.o"
        target.parent.mkdir(parents=True)
        target.write_text("binary", encoding="utf-8")
        results = safe_delete([str(target)])
        assert results[0][1] is True
        assert not target.exists()

    @pytest.mark.usefixtures("_patch_roots")
    def test_delete_subdir_in_project(self, project_dir):
        target = project_dir / "sub" / "scratch"
        target.mkdir(parents=True)
        (target / "temp.txt").write_text("scratch", encoding="utf-8")
        results = safe_delete([str(target)])
        assert results[0][1] is True
        assert not target.exists()

    @pytest.mark.usefixtures("_patch_roots")
    def test_delete_multiple_paths(self):
        t1 = Path(tempfile.mkdtemp())
        t2 = Path(tempfile.mkdtemp())
        try:
            results = safe_delete([str(t1), str(t2)])
            assert all(r[1] for r in results)
            assert not t1.exists()
            assert not t2.exists()
        finally:
            for t in [t1, t2]:
                if t.exists():
                    shutil.rmtree(t)

    @pytest.mark.usefixtures("_patch_roots")
    def test_pure_python_no_subprocess(self):
        """Verify shutil.rmtree is used, not subprocess rm."""
        target = Path(tempfile.mkdtemp())
        (target / "f.txt").write_text("x", encoding="utf-8")
        with patch("subprocess.run") as mock_run, patch("subprocess.Popen") as mock_popen:
            results = safe_delete([str(target)])
            assert results[0][1] is True
            mock_run.assert_not_called()
            mock_popen.assert_not_called()

    @pytest.mark.usefixtures("_patch_roots")
    def test_project_build_dir_allowed(self, project_dir):
        """Regression guard: ordinary project dirs are still deletable."""
        target = project_dir / "build"
        target.mkdir()
        (target / "out.js").write_text("x", encoding="utf-8")
        results = safe_delete([str(target)])
        assert results[0][1] is True

    @pytest.mark.usefixtures("_patch_roots")
    def test_project_dist_dir_allowed(self, project_dir):
        """Regression guard: dist/ is not a carve-out."""
        target = project_dir / "dist"
        target.mkdir()
        (target / "bundle.js").write_text("x", encoding="utf-8")
        results = safe_delete([str(target)])
        assert results[0][1] is True

    @pytest.mark.usefixtures("_patch_roots")
    def test_slash_tmp_literal_allowed(self):
        """Literal POSIX tmp path must succeed even if $TMPDIR differs."""
        target = POSIX_TMP / f"rm_test_{os.getpid()}"
        target.mkdir(exist_ok=True)
        try:
            results = safe_delete([str(target)])
            assert results[0][1] is True
            assert not target.exists()
        finally:
            if target.exists():
                shutil.rmtree(target)

    @pytest.mark.usefixtures("_patch_roots")
    def test_tmpdir_env_allowed(self):
        """$TMPDIR/<x> must succeed."""
        target = Path(tempfile.mkdtemp())
        try:
            results = safe_delete([str(target)])
            assert results[0][1] is True
            assert not target.exists()
        finally:
            if target.exists():
                shutil.rmtree(target)


class TestRefuseDeletion:
    @pytest.mark.usefixtures("_patch_roots")
    def test_refuse_home_dir(self):
        results = safe_delete([str(Path.home())])
        assert results[0][1] is False

    @pytest.mark.usefixtures("_patch_roots")
    def test_refuse_etc(self):
        results = safe_delete(["/etc"])
        assert results[0][1] is False

    @pytest.mark.usefixtures("_patch_roots")
    def test_refuse_root_filesystem(self):
        results = safe_delete(["/"])
        assert results[0][1] is False

    @pytest.mark.usefixtures("_patch_roots")
    def test_refuse_project_root_itself(self, project_dir):
        results = safe_delete([str(project_dir)])
        assert results[0][1] is False
        assert "root directory itself" in results[0][2]

    @pytest.mark.usefixtures("_patch_roots")
    def test_refuse_tmp_root_itself(self):
        tmpdir = tempfile.gettempdir()
        results = safe_delete([tmpdir])
        assert results[0][1] is False
        assert "root directory itself" in results[0][2]

    @pytest.mark.usefixtures("_patch_roots")
    def test_refuse_traversal_escape(self, project_dir, monkeypatch):
        """../../etc from inside project should resolve outside and be refused."""
        subdir = project_dir / "deep" / "nested"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)
        results = safe_delete(["../../../../../../etc"])
        assert results[0][1] is False

    @pytest.mark.usefixtures("_patch_roots")
    def test_refuse_absolute_outside_roots(self):
        results = safe_delete(["/usr/local/bin"])
        assert results[0][1] is False

    @pytest.mark.usefixtures("_patch_roots")
    def test_nonexistent_path_clean_error(self):
        nonexistent = os.path.join(tempfile.gettempdir(), "this_path_does_not_exist_abc123xyz")
        results = safe_delete([nonexistent])
        assert results[0][1] is False
        assert "does not exist" in results[0][2]

    @pytest.mark.usefixtures("_patch_roots")
    def test_mixed_valid_and_invalid(self, project_dir):
        """Valid paths succeed; invalid paths fail independently."""
        valid = project_dir / "ok_to_delete"
        valid.mkdir()
        results = safe_delete([str(valid), "/etc/shadow"])
        assert results[0][1] is True
        assert results[1][1] is False

    @pytest.mark.usefixtures("_patch_roots")
    def test_refuse_a_users_home_directory(self):
        results = safe_delete(["/home/someone"])
        assert results[0][1] is False

    @pytest.mark.usefixtures("_patch_roots")
    def test_refuse_var_tmp(self):
        """/var/tmp is NOT in the default allowed set (Codex excludes it)."""
        results = safe_delete(["/var/tmp"])
        assert results[0][1] is False


class TestCarveouts:
    def test_refuse_dot_git_dir(self, project_dir):
        """<repo>/.git directory must be refused."""
        git_dir = project_dir / ".git"
        git_dir.mkdir()
        resolved = git_dir.resolve()
        blocked, reason, _exemption = check_carveouts(resolved, project_dir.resolve())
        assert blocked is True
        assert ".git" in reason

    def test_refuse_inside_dot_git(self, project_dir):
        """Files inside .git/ must be refused."""
        git_dir = project_dir / ".git" / "objects"
        git_dir.mkdir(parents=True)
        resolved = git_dir.resolve()
        blocked, reason, _exemption = check_carveouts(resolved, project_dir.resolve())
        assert blocked is True
        assert ".git" in reason

    def test_refuse_dot_trinity(self, project_dir):
        trinity = project_dir / ".trinity"
        trinity.mkdir()
        resolved = trinity.resolve()
        blocked, reason, _exemption = check_carveouts(resolved, project_dir.resolve())
        assert blocked is True
        assert ".trinity" in reason

    def test_refuse_inside_dot_trinity(self, project_dir):
        passport = project_dir / ".trinity" / "passport.json"
        passport.parent.mkdir(parents=True)
        passport.write_text("{}", encoding="utf-8")
        resolved = passport.resolve()
        blocked, reason, _exemption = check_carveouts(resolved, project_dir.resolve())
        assert blocked is True
        assert ".trinity" in reason

    def test_refuse_dot_aipass(self, project_dir):
        aipass_dir = project_dir / ".aipass"
        aipass_dir.mkdir()
        resolved = aipass_dir.resolve()
        blocked, reason, _exemption = check_carveouts(resolved, project_dir.resolve())
        assert blocked is True
        assert ".aipass" in reason

    def test_refuse_dot_codex(self, project_dir):
        codex = project_dir / ".codex"
        codex.mkdir()
        resolved = codex.resolve()
        blocked, reason, _exemption = check_carveouts(resolved, project_dir.resolve())
        assert blocked is True
        assert ".codex" in reason

    def test_refuse_dot_agents(self, project_dir):
        agents = project_dir / ".agents"
        agents.mkdir()
        resolved = agents.resolve()
        blocked, reason, _exemption = check_carveouts(resolved, project_dir.resolve())
        assert blocked is True
        assert ".agents" in reason

    def test_allow_normal_project_dir(self, project_dir):
        """build/ is not a carve-out."""
        build = project_dir / "build"
        build.mkdir()
        resolved = build.resolve()
        blocked, _reason, _exemption = check_carveouts(resolved, project_dir.resolve())
        assert blocked is False

    def test_refuse_sibling_branch(self, project_with_branches, monkeypatch):
        """From drone CWD, deleting src/aipass/api must be refused."""
        drone_dir = project_with_branches / "src" / "aipass" / "drone"
        monkeypatch.chdir(drone_dir)
        target = project_with_branches / "src" / "aipass" / "api"
        resolved = target.resolve()
        blocked, reason, _exemption = check_carveouts(resolved, project_with_branches.resolve())
        assert blocked is True
        assert "sibling branch" in reason
        assert "api" in reason

    def test_allow_own_branch(self, project_with_branches, monkeypatch):
        """Deleting a subdir inside own branch must be allowed."""
        drone_dir = project_with_branches / "src" / "aipass" / "drone"
        monkeypatch.chdir(drone_dir)
        target = drone_dir / "build"
        target.mkdir()
        resolved = target.resolve()
        blocked, _reason, _exemption = check_carveouts(resolved, project_with_branches.resolve())
        assert blocked is False

    def test_refuse_all_branches_when_outside(self, project_with_branches, monkeypatch):
        """When CWD isn't inside any branch, ALL src/aipass/<branch> are refused."""
        monkeypatch.chdir(project_with_branches)
        for branch in ("drone", "api", "flow"):
            target = project_with_branches / "src" / "aipass" / branch
            resolved = target.resolve()
            blocked, _reason, _exemption = check_carveouts(resolved, project_with_branches.resolve())
            assert blocked is True, f"Expected {branch} to be blocked"

    def test_git_file_worktree_pointer(self, project_dir):
        """A .git FILE (worktree pointer) should protect the resolved gitdir."""
        real_git = project_dir / "real_git_dir"
        real_git.mkdir()
        git_file = project_dir / ".git"
        git_file.write_text(f"gitdir: {real_git}", encoding="utf-8")
        resolved = git_file.resolve()
        blocked, reason, _exemption = check_carveouts(resolved, project_dir.resolve())
        assert blocked is True
        assert ".git" in reason


# A template skeleton under templates/ carries its own .trinity/, so the outermost .trinity wins:
# innermost-wins named the skeleton in refusals and locked @spawn out of its own templates.


class TestTemplateSkeletonIsNotACitizen:
    @pytest.fixture()
    def project_with_template(self, project_dir):
        """A citizen (spawn) whose templates/ holds a full branch skeleton."""
        spawn = project_dir / "src" / "aipass" / "spawn"
        (spawn / ".trinity").mkdir(parents=True)
        skeleton = spawn / "templates" / "aipass_framework"
        (skeleton / ".trinity").mkdir(parents=True)
        (skeleton / ".pytest_cache").mkdir()
        drone = project_dir / "src" / "aipass" / "drone"
        (drone / ".trinity").mkdir(parents=True)
        return project_dir

    def test_safe_delete_refuses_a_skeleton_path_in_the_outer_citizens_name(self, project_with_template, monkeypatch):
        """Mutant killed: _find_branch_root keeping the innermost .trinity (refusal named the skeleton)."""
        monkeypatch.chdir(project_with_template / "src" / "aipass" / "drone")
        stray = project_with_template / "src" / "aipass" / "spawn" / "templates" / "aipass_framework" / ".pytest_cache"

        ((_path, ok, message),) = safe_delete([str(stray)])

        assert ok is False, message
        assert "sibling branch spawn/" in message
        assert "aipass_framework" not in message.splitlines()[0], "the verdict names the citizen; the path line follows"
        assert stray.is_dir()

    def test_refusal_names_the_citizen_not_the_skeleton(self, project_with_template, monkeypatch):
        """@devpulse's report: the refusal named a thing that is not a citizen."""
        monkeypatch.chdir(project_with_template / "src" / "aipass" / "drone")
        stray = project_with_template / "src" / "aipass" / "spawn" / "templates" / "aipass_framework" / ".pytest_cache"
        blocked, reason, _exemption = check_carveouts(stray.resolve(), project_with_template.resolve())
        assert blocked is True
        assert "spawn" in reason
        assert "aipass_framework" not in reason

    def test_a_citizen_can_clean_inside_its_own_templates(self, project_with_template, monkeypatch):
        """Innermost-wins locked @spawn out of its own tree — nobody reported this."""
        spawn = project_with_template / "src" / "aipass" / "spawn"
        monkeypatch.chdir(spawn)
        stray = spawn / "templates" / "aipass_framework" / ".pytest_cache"
        blocked, reason, _exemption = check_carveouts(stray.resolve(), project_with_template.resolve())
        assert blocked is False, f"spawn refused inside its own tree: {reason}"

    def test_standing_in_a_template_is_standing_in_the_citizen(self, project_with_template, monkeypatch):
        """CWD detection uses the same walk — it has to agree with the guard.

        Mutant killed: _find_branch_root keeping the innermost .trinity (the caller read as the skeleton)."""
        spawn = project_with_template / "src" / "aipass" / "spawn"
        monkeypatch.chdir(spawn / "templates" / "aipass_framework")
        outside_the_skeleton = spawn / "build"
        blocked, reason, _exemption = check_carveouts(outside_the_skeleton.resolve(), project_with_template.resolve())
        assert blocked is False, f"a caller standing in spawn's template was refused spawn's own tree: {reason}"

    def test_ordinary_branch_path_is_unchanged(self, project_with_template, monkeypatch):
        """The fix must not over-reach: a normal branch still maps to itself.

        Mutant killed: _find_branch_root answering None (a normal branch stopped mapping to itself)."""
        monkeypatch.chdir(project_with_template / "src" / "aipass" / "spawn")
        target = project_with_template / "src" / "aipass" / "drone" / "build"
        blocked, reason, _exemption = check_carveouts(target.resolve(), project_with_template.resolve())
        assert blocked is True
        assert "sibling branch drone/" in reason

    def test_sibling_protection_still_holds_for_real_citizens(self, project_with_template, monkeypatch):
        """Outermost-wins must not accidentally unprotect anything."""
        monkeypatch.chdir(project_with_template / "src" / "aipass" / "drone")
        target = project_with_template / "src" / "aipass" / "spawn"
        blocked, reason, _exemption = check_carveouts(target.resolve(), project_with_template.resolve())
        assert blocked is True
        assert "spawn" in reason

    def test_a_citizen_can_clear_its_own_templates_folder(self, project_with_template, monkeypatch):
        """The contains-fence must not read spawn's own skeleton as a stranger."""
        spawn = project_with_template / "src" / "aipass" / "spawn"
        monkeypatch.chdir(spawn)
        ((_path, ok, message),) = safe_delete(["templates"])
        assert ok is True, message
        assert not (spawn / "templates").exists()


class TestGitWorktreePointerUnchanged:
    def test_safe_delete_refuses_a_git_worktree_pointer_and_leaves_it_on_disk(
        self, project_dir, _patch_roots, monkeypatch
    ):
        """Mutant killed: _safe_delete_direct skipping check_carveouts (the pointer was deleted)."""
        monkeypatch.chdir(project_dir)
        real_git = project_dir / "real_git_dir"
        real_git.mkdir()
        git_file = project_dir / ".git"
        git_file.write_text(f"gitdir: {real_git}", encoding="utf-8")

        ((_path, ok, message),) = safe_delete([str(git_file)])

        assert ok is False, message
        assert ".git" in message
        assert git_file.read_text(encoding="utf-8") == f"gitdir: {real_git}"


# A folder that CONTAINS a citizen: the sibling fence walks UP, so `drone rm ..` from a branch
# passes it. The contains-fence walks DOWN and stops at the first foreign citizen.


class TestContainedCitizens:
    @pytest.fixture()
    def at_drone(self, project_with_branches, monkeypatch):
        """Stand in @drone; @api and @flow are the neighbours."""
        monkeypatch.chdir(project_with_branches / "src" / "aipass" / "drone")
        return project_with_branches

    @pytest.mark.parametrize("spelling", ["..", os.path.join("..", "..")], ids=["up-one", "up-two"])
    def test_the_two_spellings_are_refused_from_a_branch(self, at_drone, spelling):
        ((_path, ok, message),) = safe_delete([spelling])
        assert ok is False
        assert "contains citizen api/" in message, "the walk is sorted, so the first foreign citizen is api"
        for branch in ("api", "drone", "flow"):
            assert (at_drone / "src" / "aipass" / branch / ".trinity").is_dir()

    def test_the_refusal_is_recorded(self, at_drone, tmp_path):
        safe_delete([".."])
        (record,) = rm_ledger(tmp_path)
        assert record["outcome"] == "refused"
        assert "contains citizen api/" in record["reason"]

    def test_a_caller_outside_every_branch_is_refused_too(self, project_with_branches, monkeypatch):
        monkeypatch.chdir(project_with_branches)
        ((_path, ok, message),) = safe_delete(["src"])
        assert ok is False
        assert "contains citizen api/" in message

    @pytest.fixture()
    def only_my_own_tree(self, project_dir, monkeypatch):
        """Stand in spawn, whose parent holds spawn and its skeleton and nobody else."""
        spawn = project_dir / "src" / "aipass" / "spawn"
        (spawn / ".trinity").mkdir(parents=True)
        (spawn / "templates" / "aipass_framework" / ".trinity").mkdir(parents=True)
        monkeypatch.chdir(spawn)
        return spawn.parent

    @pytest.mark.parametrize("spelling", [".", "templates/..", ".."], ids=["dot", "dotted", "parent"])
    def test_the_callers_own_branch_and_its_holders_are_refused(self, only_my_own_tree, spelling):
        """Mutant killed: check_carveouts without the own-branch fence (spawn and its .trinity deleted)."""
        ((_path, ok, message),) = safe_delete([spelling])
        assert ok is False, message
        assert "your own branch spawn/" in message
        assert (only_my_own_tree / "spawn" / ".trinity").is_dir()

    def test_a_temp_dir_target_is_unchanged(self, at_drone, tmp_path_factory):
        """Outside the project a .trinity is scaffolding, not a citizen."""
        scratch = tmp_path_factory.mktemp("scratch")
        (scratch / "sandbox_branch" / ".trinity").mkdir(parents=True)
        ((_path, ok, message),) = safe_delete([str(scratch)])
        assert ok is True, message
        assert not scratch.exists()

    def test_a_symlink_to_a_citizen_is_not_contained(self, at_drone):
        """rmtree unlinks the link and never touches what it points at."""
        api = at_drone / "src" / "aipass" / "api"
        junk = at_drone / "junk"
        junk.mkdir()
        (junk / "api_link").symlink_to(api, target_is_directory=True)
        ((_path, ok, message),) = safe_delete([str(junk)])
        assert ok is True, message
        assert (api / ".trinity").is_dir()

    @pytest.mark.skipif(_PERMISSIONS_DO_NOT_BIND, reason=_PERMISSIONS_REASON)
    def test_an_unreadable_folder_refuses_rather_than_skips(self, at_drone):
        junk = at_drone / "junk"
        locked = junk / "locked"
        locked.mkdir(parents=True)
        locked.chmod(0)
        try:
            ((_path, ok, message),) = safe_delete([str(junk)])
        finally:
            locked.chmod(0o700)
        assert ok is False
        assert "cannot verify" in message
        assert junk.exists()

    @pytest.mark.skipif(_PERMISSIONS_DO_NOT_BIND, reason=_PERMISSIONS_REASON)
    def test_the_walk_stops_at_the_first_foreign_citizen(self, at_drone):
        """A locked folder sorted AFTER api is never reached, so the refusal
        names api. A walk that went on would meet the lock and say so."""
        locked = at_drone / "src" / "aipass" / "zz_locked"
        locked.mkdir()
        locked.chmod(0)
        try:
            ((_path, _ok, message),) = safe_delete([".."])
        finally:
            locked.chmod(0o700)
        assert "contains citizen api/" in message


# A symlink is guarded and reported where the LINK lives, never by its resolved target.


class TestASymlinkIsJudgedWhereItLives:
    @pytest.fixture()
    def aipass_dir(self, project_with_branches):
        return (project_with_branches / "src" / "aipass").resolve()

    def test_a_link_in_a_sibling_branch_is_refused_though_it_points_home(self, aipass_dir, monkeypatch):
        monkeypatch.chdir(aipass_dir / "api")
        link = aipass_dir / "flow" / "home_link"
        link.symlink_to(aipass_dir / "api", target_is_directory=True)
        ((_path, ok, message),) = safe_delete([str(link)])
        assert ok is False
        assert "sibling branch flow/" in message
        assert link.is_symlink()

    def test_a_link_in_my_branch_moves_as_the_link_and_is_reported_with_its_target(
        self, aipass_dir, monkeypatch, tmp_path
    ):
        monkeypatch.chdir(aipass_dir / "drone")
        link = aipass_dir / "drone" / "api_link"
        link.symlink_to(aipass_dir / "api", target_is_directory=True)
        ((_path, ok, message),) = safe_delete([str(link)])
        moved = aipass_dir / "drone" / ".archive" / "api_link"
        assert message.splitlines() == [
            "Moved to .archive:",
            str(link),
            f"-> {moved}",
            f"(the link only; it points at {aipass_dir / 'api'})",
        ]
        assert ok is True
        assert not link.is_symlink()
        assert moved.is_symlink()
        assert (aipass_dir / "api" / ".trinity").is_dir()
        (record,) = rm_ledger(tmp_path)
        assert (record["path"], record.get("target")) == (str(link), str(aipass_dir / "api"))

    def test_a_link_inside_a_carveout_is_refused_wherever_it_points(self, aipass_dir, monkeypatch):
        monkeypatch.chdir(aipass_dir / "drone")
        build = aipass_dir / "drone" / "build"
        build.mkdir()
        link = aipass_dir / "drone" / ".trinity" / "build_link"
        link.symlink_to(build, target_is_directory=True)
        ((_path, ok, message),) = safe_delete([str(link)])
        assert ok is False
        assert ".trinity" in message
        assert link.is_symlink()

    def test_a_link_to_the_whole_fleet_is_only_a_link(self, aipass_dir, monkeypatch):
        """rm unlinks; the contains-a-citizen walk must not follow the link into the fleet."""
        monkeypatch.chdir(aipass_dir / "drone")
        scratch = aipass_dir.parent.parent / "scratch"
        scratch.mkdir()
        link = scratch / "fleet_link"
        link.symlink_to(aipass_dir, target_is_directory=True)
        ((_path, ok, message),) = safe_delete([str(link)])
        assert ok is True, message
        assert not link.is_symlink()
        assert (aipass_dir / "api" / ".trinity").is_dir()

    def test_a_link_to_a_citizen_is_not_itself_a_citizen(self, aipass_dir, monkeypatch):
        """The branch-root walk must not read the link's own name as a branch."""
        monkeypatch.chdir(aipass_dir / "drone")
        scratch = aipass_dir.parent.parent / "scratch"
        scratch.mkdir()
        link = scratch / "api_link"
        link.symlink_to(aipass_dir / "api", target_is_directory=True)
        ((_path, ok, message),) = safe_delete([str(link)])
        assert ok is True, message
        assert (aipass_dir / "api" / ".trinity").is_dir()

    def test_a_link_out_of_the_roots_is_unlinked_and_its_target_survives(
        self, project_dir, tmp_path_factory, monkeypatch
    ):
        outside = tmp_path_factory.mktemp("outside")
        (outside / "keep.txt").write_text("keep", encoding="utf-8")
        link = project_dir.resolve() / "out_link"
        link.symlink_to(outside, target_is_directory=True)
        monkeypatch.setattr(rm_handler, "get_allowed_roots", lambda: [project_dir.resolve()])
        ((_path, ok, message),) = safe_delete([str(link)])
        assert ok is True, message
        assert not link.is_symlink()
        assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep"

    def test_a_path_through_a_link_is_still_judged_at_its_target(self, project_dir, tmp_path_factory, monkeypatch):
        """Guard: only the final name is left unfollowed. A path under a link resolves."""
        outside = tmp_path_factory.mktemp("outside")
        (outside / "keep.txt").write_text("keep", encoding="utf-8")
        link = project_dir.resolve() / "out_link"
        link.symlink_to(outside, target_is_directory=True)
        monkeypatch.setattr(rm_handler, "get_allowed_roots", lambda: [project_dir.resolve()])
        ((_path, ok, message),) = safe_delete([str(link / "keep.txt")])
        assert ok is False
        assert "outside allowed roots" in message
        assert (outside / "keep.txt").exists()


class TestCarveoutIntegration:
    @pytest.mark.usefixtures("_patch_roots")
    def test_safe_delete_refuses_dot_git(self, project_dir):
        git_dir = project_dir / ".git"
        git_dir.mkdir()
        results = safe_delete([str(git_dir)])
        assert results[0][1] is False
        assert ".git" in results[0][2]
        assert git_dir.exists()

    @pytest.mark.usefixtures("_patch_roots")
    def test_safe_delete_refuses_trinity(self, project_dir):
        trinity = project_dir / ".trinity"
        trinity.mkdir()
        results = safe_delete([str(trinity)])
        assert results[0][1] is False
        assert trinity.exists()

    @pytest.mark.usefixtures("_patch_roots")
    def test_safe_delete_refuses_dot_aipass(self, project_dir):
        aipass_dir = project_dir / ".aipass"
        aipass_dir.mkdir()
        results = safe_delete([str(aipass_dir)])
        assert results[0][1] is False
        assert aipass_dir.exists()

    @pytest.mark.usefixtures("_patch_roots")
    def test_safe_delete_allows_build_dir(self, project_dir):
        """Regression guard: build/ and dist/ still allowed."""
        build = project_dir / "build"
        build.mkdir()
        results = safe_delete([str(build)])
        assert results[0][1] is True
        assert not build.exists()


class TestEdgeCases:
    @pytest.mark.usefixtures("_patch_roots")
    def test_relative_path_resolved_from_cwd(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        target = project_dir / "relative_target"
        target.mkdir()
        results = safe_delete(["relative_target"])
        assert results[0][1] is True
        assert not target.exists()

    @pytest.mark.usefixtures("_patch_roots")
    def test_single_file_deletion(self):
        fd, path = tempfile.mkstemp()
        os.close(fd)
        results = safe_delete([path])
        assert results[0][1] is True
        assert not Path(path).exists()

    @pytest.mark.usefixtures("_patch_roots")
    def test_empty_paths_list(self):
        results = safe_delete([])
        assert results == []


class TestTheVerifiedAdminCrossesTheSiblingFence:
    def test_the_admin_moves_a_sibling_file_into_that_branchs_archive_and_the_record_says_so(
        self, at_drone_beside_api, monkeypatch, tmp_path
    ):
        rail_answers(monkeypatch, True)
        target = at_drone_beside_api / "README.md"

        ((_, ok, message),) = safe_delete([str(target)])

        assert ok is True, message
        assert not target.exists()
        assert (at_drone_beside_api / ".archive" / "README.md").read_text(encoding="utf-8") == "# api"
        (record,) = rm_ledger(tmp_path)
        assert (record["outcome"], record["exemption"]) == ("moved", "admin")

    def test_a_caller_the_rail_says_is_not_admin_is_still_refused(self, at_drone_beside_api, monkeypatch, tmp_path):
        rail_answers(monkeypatch, False)
        target = at_drone_beside_api / "README.md"

        ((_, ok, message),) = safe_delete([str(target)])

        assert ok is False
        assert "sibling branch api/" in message
        assert target.exists()
        (record,) = rm_ledger(tmp_path)
        assert "exemption" not in record

    def test_a_raising_rail_fails_closed(self, at_drone_beside_api, monkeypatch):
        rail_answers(monkeypatch, RuntimeError("passport unreadable"))
        target = at_drone_beside_api / "README.md"

        ((_, ok, message),) = safe_delete([str(target)])

        assert ok is False
        assert "sibling branch api/" in message
        assert target.exists()

    def test_an_unimportable_rail_fails_closed(self, at_drone_beside_api, monkeypatch):
        # Both: the door's import_module reads sys.modules; `from package import name` reads the package attribute.
        monkeypatch.setitem(sys.modules, RAIL.__name__, None)
        monkeypatch.delattr(sys.modules[RAIL.__name__.rpartition(".")[0]], RAIL.__name__.rpartition(".")[2])
        target = at_drone_beside_api / "README.md"

        ((_, ok, _),) = safe_delete([str(target)])

        assert ok is False
        assert target.exists()

    @pytest.mark.parametrize(
        ("relative", "refusal"),
        [
            ((".trinity",), "inside .trinity/"),
            ((".archive", "old.md"), "inside .archive/"),
            ((), "sibling branch api/"),
        ],
    )
    def test_the_admin_is_still_refused_a_carveout_an_archive_and_the_branch_itself(
        self, at_drone_beside_api, monkeypatch, relative, refusal
    ):
        rail_answers(monkeypatch, True)
        (at_drone_beside_api / ".archive").mkdir()
        (at_drone_beside_api / ".archive" / "old.md").write_text("old", encoding="utf-8")
        target = at_drone_beside_api.joinpath(*relative)

        ((_, ok, message),) = safe_delete([str(target)])

        assert ok is False
        assert refusal in message
        assert target.exists()

    def test_the_admin_is_still_refused_a_folder_that_holds_citizens(self, at_drone_beside_api, monkeypatch):
        rail_answers(monkeypatch, True)
        fleet = at_drone_beside_api.parent

        ((_, ok, message),) = safe_delete([str(fleet)])

        assert ok is False
        assert "contains citizen" in message
        assert (at_drone_beside_api / ".trinity").is_dir()


@pytest.fixture()
def other_project(at_drone_beside_api, project_dir, tmp_path_factory, monkeypatch):
    """A second project under the owner's home, outside every allowed root; it holds a citizen."""
    home = tmp_path_factory.mktemp("home").resolve()
    monkeypatch.setenv("HOME", str(home))
    other = home / "Projects" / "Other"
    citizen = other / "src" / "vera"
    (citizen / ".trinity").mkdir(parents=True)
    (other / "OTHER_REGISTRY.json").write_text("{}", encoding="utf-8")
    for relative in ("logs/run.log", "src/vera/notes.md", ".ai_mail.local/x.json", ".archive/old.md"):
        (other / relative).parent.mkdir(parents=True, exist_ok=True)
        (other / relative).write_text(relative, encoding="utf-8")
    for carveout in CARVEOUTS:
        # Below the root: a .trinity at the root would make the project itself a citizen.
        (other / "work" / carveout).mkdir(parents=True)
        (other / "work" / carveout / "kept").write_text("kept", encoding="utf-8")
    with patch.object(rm_handler, "get_allowed_roots", return_value=[project_dir.resolve()]):
        yield other


class TestTheVerifiedAdminIsNotRefusedByLocation:
    def test_the_admin_moves_a_file_in_another_project_into_the_archive_beside_it(
        self, other_project, monkeypatch, tmp_path
    ):
        rail_answers(monkeypatch, True)
        target = other_project / "logs"

        ((_, ok, message),) = safe_delete([str(target)])

        assert ok is True, message
        assert not target.exists()
        assert (other_project / "logs" / ".archive").exists() is False
        assert (other_project / ".archive" / "logs" / "run.log").read_text(encoding="utf-8") == "logs/run.log"
        (record,) = rm_ledger(tmp_path)
        assert (record["outcome"], record["exemption"]) == ("moved", "elsewhere")

    def test_the_admin_crosses_into_a_citizen_there_and_both_exemptions_are_recorded(
        self, other_project, monkeypatch, tmp_path
    ):
        rail_answers(monkeypatch, True)

        ((_, ok, message),) = safe_delete([str(other_project / "src" / "vera" / "notes.md")])

        assert ok is True, message
        assert (other_project / "src" / "vera" / ".archive" / "notes.md").is_file()
        assert rm_ledger(tmp_path)[0]["exemption"] == "elsewhere+admin"

    def test_a_citizen_is_still_refused_there_by_location(self, other_project, monkeypatch, tmp_path):
        rail_answers(monkeypatch, False)
        target = other_project / "logs"

        ((_, ok, message),) = safe_delete([str(target)])

        assert ok is False
        assert "outside allowed roots" in message
        assert target.is_dir()
        assert "exemption" not in rm_ledger(tmp_path)[0]

    @pytest.mark.parametrize(
        ("relative", "refusal"),
        [
            *((("work", name, "kept"), f"inside {name}/") for name in CARVEOUTS),
            ((".archive", "old.md"), "inside .archive/"),
            (("src", "vera"), "sibling branch vera/"),
            (("src",), "contains citizen vera/"),
            ((), "root directory itself"),
            ((".ai_mail.local",), "dot name"),
        ],
    )
    def test_every_other_rule_still_holds_for_the_admin_outside_the_tree(
        self, other_project, monkeypatch, relative, refusal
    ):
        rail_answers(monkeypatch, True)
        target = other_project.joinpath(*relative)

        ((_, ok, message),) = safe_delete([str(target)])

        assert ok is False
        assert refusal in message
        assert target.exists()

    def test_the_admin_moves_a_dot_name_there_with_dot(self, other_project, monkeypatch, tmp_path):
        rail_answers(monkeypatch, True)

        ((_, ok, message),) = safe_delete([DOT_FLAG, str(other_project / ".ai_mail.local")])

        assert ok is True, message
        assert (other_project / ".archive" / ".ai_mail.local" / "x.json").is_file()
        assert rm_ledger(tmp_path)[0]["exemption"] == "elsewhere+dot"

    @pytest.mark.parametrize("where", ["provider", "loose", "outside_home"])
    def test_the_admin_is_refused_provider_folders_a_path_in_no_project_and_beyond_the_home(
        self, other_project, monkeypatch, tmp_path_factory, where
    ):
        rail_answers(monkeypatch, True)
        home = Path.home()
        spots = {
            "provider": (home / ".claude" / "settings.json", "provider settings"),
            "loose": (home / "loose" / "file.txt", "in no project"),
            "outside_home": (tmp_path_factory.mktemp("beyond") / "file.txt", "outside the owner's home"),
        }
        target, refusal = spots[where]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("stays", encoding="utf-8")

        ((_, ok, message),) = safe_delete([str(target)])

        assert ok is False
        assert refusal in message
        assert target.read_text(encoding="utf-8") == "stays"
