"""Tests for drone rm — contained safe-delete.

Red-team containment tests verify that paths outside allowed roots
are refused, including symlink escapes and traversal attempts.
Carve-out tests verify .git, .trinity, .aipass, .codex, .agents,
and sibling branches are protected even inside allowed roots.
Stale-mode tests (DPLAN-0338) sit at the bottom.
"""

import errno
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.drone.apps.handlers.rm_handler import (
    _detect_current_branch,
    _find_branch_root,
    check_carveouts,
    check_containment,
    format_age,
    format_stale_summary,
    get_allowed_roots,
    parse_age,
    parse_stale_args,
    safe_delete,
    stale_sweep,
)
from aipass.drone.apps.modules.rm import handle_command

#: The canonical POSIX temp root, SPELLED BY THE RUNNING PLATFORM rather than
#: written down. ``rm_handler.get_allowed_roots`` carves it out on POSIX only
#: (``Path("/tmp")`` behind a ``sys.platform != "win32"`` gate), so it genuinely
#: is the subject of the three tests below — but a rooted literal is
#: DRIVE-RELATIVE under ntpath, where ``Path("/tmp").resolve()`` is ``D:\tmp``,
#: so a written-down root claims something different on the other half of the
#: matrix. ``os.sep`` is "/" wherever these tests are allowed to run.
POSIX_TMP = Path(os.sep, "tmp")

#: Why the POSIX-only units skip. Spelled once: three tests share the reason.
_POSIX_CARVE_OUT_REASON = "POSIX-only carve-out: rm_handler adds /tmp on non-win32 platforms only"

#: A mode-0 folder only stops a caller the kernel holds to permissions: not on
#: Windows, not as root. ``or`` short-circuits, so geteuid is never read on nt.
_PERMISSIONS_DO_NOT_BIND = sys.platform == "win32" or os.geteuid() == 0
_PERMISSIONS_REASON = "needs POSIX permissions that bind the caller"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def project_dir(tmp_path):
    """Fake project root with a registry file and src/aipass layout."""
    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}")
    return tmp_path


@pytest.fixture()
def project_with_branches(project_dir):
    """Project root with branch dirs containing .trinity/ markers."""
    for branch in ("drone", "api", "flow"):
        d = project_dir / "src" / "aipass" / branch
        d.mkdir(parents=True)
        (d / ".trinity").mkdir()
        (d / "README.md").write_text(f"# {branch}")
    return project_dir


@pytest.fixture()
def _patch_roots(project_dir):
    """Patch get_allowed_roots to use deterministic test roots."""
    tmpdir = Path(tempfile.gettempdir()).resolve()
    roots = [project_dir.resolve()]
    seen = set(roots)
    if sys.platform != "win32":
        slash_tmp = Path("/tmp").resolve()
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


# ---------------------------------------------------------------------------
# get_allowed_roots
# ---------------------------------------------------------------------------


class TestGetAllowedRoots:
    def test_includes_temp_dir(self):
        roots = get_allowed_roots()
        tmpdir = Path(tempfile.gettempdir()).resolve()
        assert tmpdir in roots

    @pytest.mark.skipif(sys.platform == "win32", reason=_POSIX_CARVE_OUT_REASON)
    def test_includes_slash_tmp(self, tmp_path, monkeypatch):
        """The POSIX carve-out puts the canonical tmp root in roots by itself.

        $TMPDIR IS MOVED OFF THE CARVE-OUT FIRST, and that is the whole test.
        Measured with the carve-out deleted from ``get_allowed_roots`` and this
        machine's default $TMPDIR (which IS /tmp): the unit stayed GREEN, because
        the system-temp candidate was quietly supplying the root the carve-out
        was being credited for. Pointed somewhere else, only the carve-out can
        put /tmp in the list.
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

    @pytest.mark.skipif(sys.platform == "win32", reason=_POSIX_CARVE_OUT_REASON)
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


# ---------------------------------------------------------------------------
# check_containment
# ---------------------------------------------------------------------------


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
        # A SIBLING of the root, not a rooted literal. /etc/passwd stood in for
        # "somewhere outside the fence" and was never the subject here; written
        # down it is also drive-relative under ntpath, so the line meant a
        # different thing on the other half of the matrix.
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


# ---------------------------------------------------------------------------
# ALLOW: valid deletions
# ---------------------------------------------------------------------------


class TestAllowDeletion:
    @pytest.mark.usefixtures("_patch_roots")
    def test_delete_dir_in_tmp(self):
        target = Path(tempfile.mkdtemp())
        try:
            (target / "file.txt").write_text("data")
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
        (target / "data.txt").write_text("hello")
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
        target.write_text("binary")
        results = safe_delete([str(target)])
        assert results[0][1] is True
        assert not target.exists()

    @pytest.mark.usefixtures("_patch_roots")
    def test_delete_subdir_in_project(self, project_dir):
        target = project_dir / "sub" / "scratch"
        target.mkdir(parents=True)
        (target / "temp.txt").write_text("scratch")
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
        (target / "f.txt").write_text("x")
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
        (target / "out.js").write_text("x")
        results = safe_delete([str(target)])
        assert results[0][1] is True

    @pytest.mark.usefixtures("_patch_roots")
    def test_project_dist_dir_allowed(self, project_dir):
        """Regression guard: dist/ is not a carve-out."""
        target = project_dir / "dist"
        target.mkdir()
        (target / "bundle.js").write_text("x")
        results = safe_delete([str(target)])
        assert results[0][1] is True

    @pytest.mark.skipif(sys.platform == "win32", reason=_POSIX_CARVE_OUT_REASON)
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


# ---------------------------------------------------------------------------
# REFUSE: red-team containment
# ---------------------------------------------------------------------------


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
    def test_refuse_symlink_escape_from_tmp(self):
        """Symlink under /tmp pointing to /home/user should be refused."""
        target_outside = Path.home()
        link_dir = Path(tempfile.mkdtemp())
        link = link_dir / "escape_link"
        try:
            link.symlink_to(target_outside)
            results = safe_delete([str(link)])
            assert results[0][1] is False
        finally:
            if link.exists() or link.is_symlink():
                link.unlink()
            if link_dir.exists():
                shutil.rmtree(link_dir)

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
    def test_refuse_home_patrick(self):
        results = safe_delete(["/home/patrick"])
        assert results[0][1] is False

    @pytest.mark.usefixtures("_patch_roots")
    def test_refuse_var_tmp(self):
        """/var/tmp is NOT in the default allowed set (Codex excludes it)."""
        results = safe_delete(["/var/tmp"])
        assert results[0][1] is False


# ---------------------------------------------------------------------------
# Carve-outs: .git, .trinity, .aipass, .codex, .agents, siblings
# ---------------------------------------------------------------------------


class TestCarveouts:
    def test_refuse_dot_git_dir(self, project_dir):
        """<repo>/.git directory must be refused."""
        git_dir = project_dir / ".git"
        git_dir.mkdir()
        resolved = git_dir.resolve()
        blocked, reason = check_carveouts(resolved, project_dir.resolve())
        assert blocked is True
        assert ".git" in reason

    def test_refuse_inside_dot_git(self, project_dir):
        """Files inside .git/ must be refused."""
        git_dir = project_dir / ".git" / "objects"
        git_dir.mkdir(parents=True)
        resolved = git_dir.resolve()
        blocked, reason = check_carveouts(resolved, project_dir.resolve())
        assert blocked is True
        assert ".git" in reason

    def test_refuse_dot_trinity(self, project_dir):
        trinity = project_dir / ".trinity"
        trinity.mkdir()
        resolved = trinity.resolve()
        blocked, reason = check_carveouts(resolved, project_dir.resolve())
        assert blocked is True
        assert ".trinity" in reason

    def test_refuse_inside_dot_trinity(self, project_dir):
        passport = project_dir / ".trinity" / "passport.json"
        passport.parent.mkdir(parents=True)
        passport.write_text("{}")
        resolved = passport.resolve()
        blocked, reason = check_carveouts(resolved, project_dir.resolve())
        assert blocked is True
        assert ".trinity" in reason

    def test_refuse_dot_aipass(self, project_dir):
        aipass_dir = project_dir / ".aipass"
        aipass_dir.mkdir()
        resolved = aipass_dir.resolve()
        blocked, reason = check_carveouts(resolved, project_dir.resolve())
        assert blocked is True
        assert ".aipass" in reason

    def test_refuse_dot_codex(self, project_dir):
        codex = project_dir / ".codex"
        codex.mkdir()
        resolved = codex.resolve()
        blocked, reason = check_carveouts(resolved, project_dir.resolve())
        assert blocked is True
        assert ".codex" in reason

    def test_refuse_dot_agents(self, project_dir):
        agents = project_dir / ".agents"
        agents.mkdir()
        resolved = agents.resolve()
        blocked, reason = check_carveouts(resolved, project_dir.resolve())
        assert blocked is True
        assert ".agents" in reason

    def test_allow_normal_project_dir(self, project_dir):
        """build/ is not a carve-out."""
        build = project_dir / "build"
        build.mkdir()
        resolved = build.resolve()
        blocked, _reason = check_carveouts(resolved, project_dir.resolve())
        assert blocked is False

    def test_refuse_sibling_branch(self, project_with_branches, monkeypatch):
        """From drone CWD, deleting src/aipass/api must be refused."""
        drone_dir = project_with_branches / "src" / "aipass" / "drone"
        monkeypatch.chdir(drone_dir)
        target = project_with_branches / "src" / "aipass" / "api"
        resolved = target.resolve()
        blocked, reason = check_carveouts(resolved, project_with_branches.resolve())
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
        blocked, _reason = check_carveouts(resolved, project_with_branches.resolve())
        assert blocked is False

    def test_refuse_all_branches_when_outside(self, project_with_branches, monkeypatch):
        """When CWD isn't inside any branch, ALL src/aipass/<branch> are refused."""
        monkeypatch.chdir(project_with_branches)
        for branch in ("drone", "api", "flow"):
            target = project_with_branches / "src" / "aipass" / branch
            resolved = target.resolve()
            blocked, _reason = check_carveouts(resolved, project_with_branches.resolve())
            assert blocked is True, f"Expected {branch} to be blocked"

    def test_git_file_worktree_pointer(self, project_dir):
        """A .git FILE (worktree pointer) should protect the resolved gitdir."""
        real_git = project_dir / "real_git_dir"
        real_git.mkdir()
        git_file = project_dir / ".git"
        git_file.write_text(f"gitdir: {real_git}")
        resolved = git_file.resolve()
        blocked, reason = check_carveouts(resolved, project_dir.resolve())
        assert blocked is True
        assert ".git" in reason


# ---------------------------------------------------------------------------
# Template skeletons are not citizens — outermost .trinity wins
#
# @spawn ships a full branch skeleton under templates/, .trinity/ and all, so
# shape-based branch detection reads it as a citizen. The innermost-wins walk
# named that skeleton in refusals ("sibling branch aipass_framework/") and —
# worse — locked @spawn out of its own templates, because the skeleton's name
# never matches the branch you are standing in. The same mimicry sent the
# commit gate running pytest inside the template (fixed there in e934099f with
# outermost-citizen-wins); this is that rule, applied to the delete guard.
# ---------------------------------------------------------------------------


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

    def test_find_branch_root_returns_the_outermost_citizen(self, project_with_template):
        """Two .trinity ancestors: the citizen wins, not the skeleton."""
        stray = project_with_template / "src" / "aipass" / "spawn" / "templates" / "aipass_framework" / ".pytest_cache"
        root = _find_branch_root(stray.resolve(), project_with_template.resolve())
        assert root is not None
        assert root.name == "spawn"

    def test_refusal_names_the_citizen_not_the_skeleton(self, project_with_template, monkeypatch):
        """@devpulse's report: the refusal named a thing that is not a citizen."""
        monkeypatch.chdir(project_with_template / "src" / "aipass" / "drone")
        stray = project_with_template / "src" / "aipass" / "spawn" / "templates" / "aipass_framework" / ".pytest_cache"
        blocked, reason = check_carveouts(stray.resolve(), project_with_template.resolve())
        assert blocked is True
        assert "spawn" in reason
        assert "aipass_framework" not in reason

    def test_a_citizen_can_clean_inside_its_own_templates(self, project_with_template, monkeypatch):
        """Innermost-wins locked @spawn out of its own tree — nobody reported this."""
        spawn = project_with_template / "src" / "aipass" / "spawn"
        monkeypatch.chdir(spawn)
        stray = spawn / "templates" / "aipass_framework" / ".pytest_cache"
        blocked, reason = check_carveouts(stray.resolve(), project_with_template.resolve())
        assert blocked is False, f"spawn refused inside its own tree: {reason}"

    def test_standing_in_a_template_is_standing_in_the_citizen(self, project_with_template, monkeypatch):
        """CWD detection uses the same walk — it has to agree with the guard."""
        skeleton = project_with_template / "src" / "aipass" / "spawn" / "templates" / "aipass_framework"
        monkeypatch.chdir(skeleton)
        assert _detect_current_branch(project_with_template.resolve()) == "spawn"

    def test_ordinary_branch_path_is_unchanged(self, project_with_template):
        """The fix must not over-reach: a normal branch still maps to itself."""
        target = project_with_template / "src" / "aipass" / "drone" / "build"
        root = _find_branch_root(target.resolve(), project_with_template.resolve())
        assert root is not None
        assert root.name == "drone"

    def test_sibling_protection_still_holds_for_real_citizens(self, project_with_template, monkeypatch):
        """Outermost-wins must not accidentally unprotect anything."""
        monkeypatch.chdir(project_with_template / "src" / "aipass" / "drone")
        target = project_with_template / "src" / "aipass" / "spawn"
        blocked, reason = check_carveouts(target.resolve(), project_with_template.resolve())
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
    def test_git_file_worktree_pointer_still_protected(self, project_dir):
        """Pinned separately so the walk change cannot quietly weaken it."""
        real_git = project_dir / "real_git_dir"
        real_git.mkdir()
        git_file = project_dir / ".git"
        git_file.write_text(f"gitdir: {real_git}")
        resolved = git_file.resolve()
        blocked, reason = check_carveouts(resolved, project_dir.resolve())
        assert blocked is True
        assert ".git" in reason


# ---------------------------------------------------------------------------
# A folder that CONTAINS a citizen — the fence above the branches
#
# The sibling fence walks UP from the target, so `drone rm ..` from a branch
# (src/aipass) and `drone rm ../..` (src) found no .trinity above them and
# passed every guard: rmtree would have taken the fleet. Measured 2026-09-11
# with the guards alone, no delete (DPLAN-0338 follow-up). The cure walks DOWN
# and stops at the first foreign citizen, which the refusal names.
# ---------------------------------------------------------------------------


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
        (record,) = _ledger(tmp_path)
        assert record["outcome"] == "refused"
        assert "contains citizen api/" in record["reason"]

    def test_a_caller_outside_every_branch_is_refused_too(self, project_with_branches, monkeypatch):
        monkeypatch.chdir(project_with_branches)
        ((_path, ok, message),) = safe_delete(["src"])
        assert ok is False
        assert "contains citizen api/" in message

    @pytest.fixture()
    def only_my_own_tree(self, project_dir, monkeypatch):
        """Stand in spawn, whose parent holds spawn and its skeleton and nobody
        else — the one shape the contains-fence must let through."""
        spawn = project_dir / "src" / "aipass" / "spawn"
        (spawn / ".trinity").mkdir(parents=True)
        (spawn / "templates" / "aipass_framework" / ".trinity").mkdir(parents=True)
        monkeypatch.chdir(spawn)
        return spawn.parent

    @pytest.mark.deletable_cwd
    def test_a_folder_holding_only_the_callers_own_tree_is_allowed(self, only_my_own_tree):
        """The caller's tree is pruned whole — its template skeleton included,
        which is spawn's by outermost-wins and must not read as a stranger.

        Marked: standing in your own tree while deleting its parent IS deleting
        the directory you stand in, and Windows refuses that (run 34686193857,
        WinError 32 — see WINDOWS_CWD_REASON in conftest). The recipe is what
        that host lacks, not the verdict; the two cases below make the verdict
        on every OS.
        """
        ((_path, ok, message),) = safe_delete([".."])
        assert ok is True, message
        assert not only_my_own_tree.exists()

    def test_the_fence_itself_allows_the_callers_own_tree_on_every_os(self, only_my_own_tree, project_dir):
        """The same verdict, asked of the guard instead of proved by a delete,
        so the claim above is not the skipped host's only cover."""
        blocked, reason = check_carveouts(only_my_own_tree.resolve(), project_dir.resolve())
        assert blocked is False, reason

    def test_a_host_that_refuses_to_delete_a_live_cwd_is_not_a_refusal_of_ours(
        self, only_my_own_tree, tmp_path, monkeypatch
    ):
        """The Windows half of the case above, manufactured here rather than
        asked of this host.

        The rule is injected at the seam: rmtree refuses to remove a directory
        the process stands in, which is all WinError 32 is. What that shows is
        whose refusal it is — every drone guard passed, the message is the
        host's own and carries the way out of it, the ledger says failed, and
        the tree is still standing. It models the refusal only; a real rmtree
        empties what it can reach before raising.
        """
        real_rmtree = shutil.rmtree

        def windows_rmtree(path, *args, **kwargs):
            here = Path.cwd()
            target = Path(path)
            if here == target or target in here.parents:
                raise PermissionError(
                    errno.EACCES,
                    "[WinError 32] The process cannot access the file because it is being used by another process",
                    str(target),
                )
            real_rmtree(path, *args, **kwargs)

        monkeypatch.setattr(shutil, "rmtree", windows_rmtree)

        ((_path, ok, message),) = safe_delete([".."])

        assert ok is False
        assert "WinError 32" in message
        assert "Protected:" not in message, "no guard of ours refused this one"
        assert f"run drone rm from outside {only_my_own_tree.resolve()}" in message
        (record,) = _ledger(tmp_path)
        assert record["outcome"] == "failed"
        assert "standing in" in record["reason"], "the durable half must carry the way out too"
        assert only_my_own_tree.exists()

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


# ---------------------------------------------------------------------------
# Carve-outs via safe_delete (integration)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Module orchestrator (rm.py)
# ---------------------------------------------------------------------------


class TestRmModule:
    def test_handle_command_help(self):
        from aipass.drone.apps.modules.rm import handle_command

        result = handle_command("--help")
        assert result is True

    def test_handle_command_introspection(self):
        from aipass.drone.apps.modules.rm import handle_command

        result = handle_command(None, None)
        assert result is True

    def test_print_introspection(self, capsys):
        """The self-map names the module and points at --help."""
        from aipass.drone.apps.modules.rm import print_introspection

        print_introspection()

        printed = capsys.readouterr().out
        assert "Contained Safe-Delete" in printed
        assert "--help" in printed

    def test_print_help(self, capsys):
        """--help states the usage line and the containment rule it enforces."""
        from aipass.drone.apps.modules.rm import print_help

        print_help()

        printed = capsys.readouterr().out
        assert "Usage: drone rm" in printed
        assert "Carve-outs" in printed

    def test_a_refusal_outside_every_root_is_a_failure_not_a_quiet_success(self, tmp_path):
        """A refusal is an error: handle_command reports False, the CLI exits 1.

        @seedgo's 2026-09-07 report was that ``drone rm`` on paths outside every
        allowed root printed the red refusal and exited 0 — a script reading
        ``$?`` would read a delete that never happened as done. Measured from
        every door reachable here (built-in lane, @drone routing, multi-path,
        sibling-branch refusal, projectless cwd) the exit was already 1, so this
        pins the mapping rather than fixing it: the boolean handle_command
        returns is the only thing standing between a refusal and exit 0.

        The root and the target are SIBLINGS under tmp_path, and the roots list
        is narrowed by hand. Two earlier drafts of this test passed the delete
        instead of the refusal: the shared ``_patch_roots`` fixture leaves /tmp
        allowed, and ``project_dir`` IS ``tmp_path``, so a target under either
        one sits inside a root. A containment test whose subject is inside the
        fence proves nothing about the fence.
        """
        from aipass.drone.apps.modules.rm import handle_command

        root = tmp_path / "the_only_allowed_root"
        root.mkdir()
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        target = elsewhere / "keepme.txt"
        target.write_text("must survive")

        with patch(
            "aipass.drone.apps.handlers.rm_handler.get_allowed_roots",
            return_value=[root.resolve()],
        ):
            assert handle_command(str(target)) is False

        assert target.exists(), "the refusal did not hold — the file was deleted"

    def test_the_cli_maps_a_refusal_to_a_non_zero_exit(self, monkeypatch):
        """The other half: False must not be flattened to 0 on the way out."""
        from aipass.drone.apps import drone as drone_cli

        monkeypatch.setattr(drone_cli, "_handle_rm", drone_cli._handle_rm)
        with patch("aipass.drone.apps.modules.rm.handle_command", return_value=False):
            assert drone_cli._handle_rm(["/some/refused/path"]) == 1
        with patch("aipass.drone.apps.modules.rm.handle_command", return_value=True):
            assert drone_cli._handle_rm(["/some/allowed/path"]) == 0


# ---------------------------------------------------------------------------
# Stale mode — drone rm --stale AGE [--dry-run] DIR [DIR...]  (DPLAN-0338)
#
# A narrower lane on the same verb: it unlinks only *.tmp regular files sitting
# directly inside a *_json folder and older than AGE, keeps the carve-outs, and
# crosses the sibling-branch fence on purpose. The fixture stands in @drone and
# sweeps @api's tree, so every sweep below crosses the fence — a lost crossing
# turns the whole block red, not one test.
# ---------------------------------------------------------------------------

_DAY = 86_400

#: The twelve keys a plain delete record has always carried.
_PLAIN_RECORD_KEYS = {
    "timestamp",
    "lane",
    "outcome",
    "caller",
    "cwd",
    "requested",
    "path",
    "reason",
    "kind",
    "size_bytes",
    "entry_count",
    "measured",
}


def _aged(path: Path, age_seconds: float, body: str = "x") -> Path:
    """Write *path* and backdate its mtime by *age_seconds*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    then = time.time() - age_seconds
    os.utime(path, (then, then))
    return path


def _ledger(tmp_path: Path) -> list[dict]:
    """Every record the autouse deletion-log fixture captured in this test."""
    store = tmp_path / "deletions.jsonl"
    if not store.exists():
        return []
    return [json.loads(line) for line in store.read_text(encoding="utf-8").splitlines()]


def _sweep(*tokens: str):
    return stale_sweep(parse_stale_args(list(tokens)))


@pytest.fixture()
def stale_tree(project_with_branches, monkeypatch):
    """@drone stands at home; @api's tree holds one stale temp and one of each skip."""
    monkeypatch.chdir(project_with_branches / "src" / "aipass" / "drone")
    api = project_with_branches / "src" / "aipass" / "api"
    return {
        "api": api,
        "stale": _aged(api / "api_json" / "tmpab12cd.tmp", 11 * _DAY, "abc"),
        "young": _aged(api / "api_json" / ".4242_7.tmp", 9 * _DAY),
        "not_tmp": _aged(api / "api_json" / "api_log.json", 11 * _DAY),
        "not_json_folder": _aged(api / "scratch" / "old.tmp", 11 * _DAY),
    }


class TestStaleAge:
    @pytest.mark.parametrize(("text", "seconds"), [("10d", 864_000), ("36h", 129_600), ("90m", 5_400)])
    def test_the_three_forms(self, text, seconds):
        assert parse_age(text) == seconds

    @pytest.mark.parametrize("text", ["10", "10s", "2w", "d", "-5d", "10D", "1.5d", "10d ", "", "0d", "٣d"])
    def test_anything_else_is_refused_naming_the_three_forms(self, text):
        """Includes zero (a write in flight is younger than any real age) and a
        non-ASCII digit, which ``\\d`` would have matched and ``int()`` read."""
        with pytest.raises(ValueError) as caught:
            parse_age(text)
        message = str(caught.value)
        assert "10d" in message
        assert "36h" in message
        assert "90m" in message

    @pytest.mark.parametrize(
        ("seconds", "shown"), [(11 * _DAY + 3 * 3600 + 120, "11d3h"), (5_400, "1h30m"), (59, "0m")]
    )
    def test_format_age(self, seconds, shown):
        assert format_age(seconds) == shown


class TestStaleArgs:
    def test_flags_ride_in_any_slot(self):
        request = parse_stale_args(["a", "--dry-run", "--stale", "36h", "b"])
        assert (request.age, request.age_seconds, request.dry_run, request.dirs) == ("36h", 129_600, True, ("a", "b"))

    def test_the_equals_spelling_is_read(self):
        request = parse_stale_args(["--stale=90m", "a"])
        assert (request.age, request.dry_run, request.dirs) == ("90m", False, ("a",))

    @pytest.mark.parametrize(
        "tokens",
        [
            ["--stale"],
            ["--stale", "10d"],
            ["--stale", "10d", "--dryrun", "a"],
            ["--stale", "10d", "--stale", "5d", "a"],
            ["--staleness", "a"],
            ["--stale", "--dry-run", "a"],
        ],
        ids=["no-age", "no-dir", "typo-dry-run", "twice", "unknown-spelling", "flag-in-age-slot"],
    )
    def test_malformed_requests_are_refused(self, tokens):
        with pytest.raises(ValueError):
            parse_stale_args(tokens)


class TestStaleSweep:
    def test_the_stale_tmp_in_a_json_folder_is_deleted(self, stale_tree):
        report = _sweep("--stale", "10d", str(stale_tree["api"]))
        assert not stale_tree["stale"].exists()
        assert (report.deleted, report.refusals) == (1, [])

    @pytest.mark.parametrize("survivor", ["young", "not_tmp", "not_json_folder"])
    def test_the_three_skip_rules(self, stale_tree, survivor):
        """Younger than AGE, not named .tmp, not inside a _json folder: untouched."""
        _sweep("--stale", "10d", str(stale_tree["api"]))
        assert stale_tree[survivor].exists()

    def test_the_parent_folder_is_the_one_that_counts(self, stale_tree):
        """A _json GRANDPARENT is not enough — the rule reads the parent's name."""
        deeper = _aged(stale_tree["api"] / "api_json" / "sub" / "old.tmp", 11 * _DAY)
        _sweep("--stale", "10d", str(stale_tree["api"]))
        assert deeper.exists()

    @pytest.mark.skipif(os.utime not in os.supports_follow_symlinks, reason="needs lutimes to age the link itself")
    def test_a_symlink_named_tmp_is_skipped(self, stale_tree):
        """The LINK is aged too, so only the regular-file rule can spare it."""
        target = _aged(stale_tree["api"] / "elsewhere" / "real.tmp", 11 * _DAY)
        link = stale_tree["api"] / "api_json" / "link.tmp"
        link.symlink_to(target)
        then = time.time() - 11 * _DAY
        os.utime(link, (then, then), follow_symlinks=False)

        report = _sweep("--stale", "10d", str(stale_tree["api"]))

        assert link.is_symlink()
        assert target.exists()
        assert report.matched == 1

    def test_a_directory_named_tmp_is_skipped(self, stale_tree):
        folder = stale_tree["api"] / "api_json" / "held.tmp"
        folder.mkdir()
        then = time.time() - 11 * _DAY
        os.utime(folder, (then, then))
        _sweep("--stale", "10d", str(stale_tree["api"]))
        assert folder.is_dir()

    def test_the_walk_never_enters_a_carve_out(self, stale_tree):
        hidden = _aged(stale_tree["api"] / ".trinity" / "trinity_json" / "old.tmp", 11 * _DAY)
        _sweep("--stale", "10d", str(stale_tree["api"]))
        assert hidden.exists()

    def test_a_carve_out_dir_is_refused_and_recorded(self, stale_tree, tmp_path):
        trinity = stale_tree["api"] / ".trinity"
        hidden = _aged(trinity / "trinity_json" / "old.tmp", 11 * _DAY)

        report = _sweep("--stale", "10d", str(trinity))

        assert hidden.exists()
        assert len(report.refusals) == 1
        assert "Protected directory" in report.refusals[0]
        (record,) = _ledger(tmp_path)
        assert (record["outcome"], record["mode"], record["age"]) == ("refused", "stale", "10d")

    def test_a_dir_outside_the_project_is_refused(self, stale_tree, tmp_path_factory):
        """Outside the project but inside the system temp dir: the plain lane's
        temp roots are not swept here."""
        outside = tmp_path_factory.mktemp("outside")
        litter = _aged(outside / "x_json" / "old.tmp", 11 * _DAY)

        report = _sweep("--stale", "10d", str(outside))

        assert litter.exists()
        assert "outside allowed roots" in report.refusals[0]

    def test_a_missing_dir_is_a_refusal(self, stale_tree, tmp_path):
        report = _sweep("--stale", "10d", str(stale_tree["api"] / "nope"))
        assert "does not exist" in report.refusals[0]
        assert _ledger(tmp_path)[0]["outcome"] == "not_found"

    @pytest.mark.parametrize("dry_run", [False, True])
    @pytest.mark.parametrize("nested_first", [False, True])
    def test_overlapping_dirs_walk_each_folder_once(self, stale_tree, nested_first, dry_run):
        """A real run hides a double walk — the first pass already unlinked what
        the second would list — so the folder count and the dry run carry it."""
        dirs = [str(stale_tree["api"]), str(stale_tree["api"] / "api_json")]
        if nested_first:
            dirs.reverse()
        report = _sweep("--stale", "10d", *(["--dry-run"] if dry_run else []), *dirs)
        assert (report.folders_scanned, report.matched, report.refusals) == (3, 1, [])


class TestStaleCrossesTheSiblingFence:
    def test_stale_mode_deletes_inside_a_sibling_branch(self, stale_tree):
        assert handle_command("--stale", ["10d", str(stale_tree["api"])]) is True
        assert not stale_tree["stale"].exists()

    def test_the_plain_verb_still_refuses_the_same_file(self, stale_tree, tmp_path):
        assert handle_command(str(stale_tree["stale"])) is False
        assert stale_tree["stale"].exists()
        assert "sibling branch api" in _ledger(tmp_path)[0]["reason"]


class TestStaleDryRun:
    def test_dry_run_lists_every_candidate_and_deletes_nothing(self, stale_tree, capsys, tmp_path):
        assert handle_command("--stale", ["10d", "--dry-run", str(stale_tree["api"])]) is True

        out = capsys.readouterr().out
        assert stale_tree["stale"].exists()
        candidate_lines = [line for line in out.splitlines() if "would delete" in line]
        assert len(candidate_lines) == 1
        assert str(stale_tree["stale"].resolve()) in candidate_lines[0]
        assert "11d0h" in candidate_lines[0]
        assert "3 B" in candidate_lines[0]
        assert "files deleted 0" in out.splitlines()[-1]
        assert _ledger(tmp_path) == [], "a dry run deletes nothing, so it records nothing"

    def test_a_dry_run_refusal_prints_and_fails_but_is_not_recorded(self, stale_tree, tmp_path):
        """No delete was attempted, so the ledger has nothing to say about it."""
        assert handle_command("--stale", ["10d", "--dry-run", str(stale_tree["api"] / "nope")]) is False
        assert _ledger(tmp_path) == []


class TestStaleRecord:
    def test_a_stale_delete_is_recorded_with_mode_and_age(self, stale_tree, tmp_path):
        _sweep("--stale", "10d", str(stale_tree["api"]))

        (record,) = _ledger(tmp_path)
        assert record["path"] == str(stale_tree["stale"].resolve())
        assert (record["lane"], record["outcome"], record["mode"], record["age"]) == ("rm", "deleted", "stale", "10d")
        assert record["requested"] == str(stale_tree["api"])
        assert record["size_bytes"] == 3

    def test_a_plain_delete_keeps_its_twelve_keys(self, project_dir, monkeypatch, tmp_path):
        """Without --stale the record is byte-for-byte what it was: no mode key."""
        monkeypatch.chdir(project_dir)
        target = project_dir / "build.log"
        target.write_text("x", encoding="utf-8")
        safe_delete([str(target)])
        (record,) = _ledger(tmp_path)
        assert set(record) == _PLAIN_RECORD_KEYS


class TestStaleSummary:
    def test_the_summary_line_counts(self, stale_tree, capsys):
        """api, api_json and scratch are walked; .trinity is not."""
        _aged(stale_tree["api"] / "api_json" / "tmpzz99.tmp", 30 * _DAY, "defg")

        assert handle_command("--stale", ["10d", str(stale_tree["api"])]) is True

        assert capsys.readouterr().out.splitlines()[-1] == (
            "rm --stale 10d (swept): folders scanned 3, files matched 2 (7 bytes), "
            "files deleted 2, bytes freed 7, refusals 0"
        )

    def test_the_summary_is_rendered_from_the_report(self, stale_tree):
        request = parse_stale_args(["--stale", "10d", "--dry-run", str(stale_tree["api"])])
        assert format_stale_summary(request, stale_sweep(request)) == (
            "rm --stale 10d (dry run): folders scanned 3, files matched 1 (3 bytes), "
            "files deleted 0, bytes freed 0, refusals 0"
        )

    def test_nothing_matched_is_a_success(self, stale_tree, capsys):
        assert handle_command("--stale", ["10d", str(stale_tree["api"] / "scratch")]) is True
        assert "files matched 0" in capsys.readouterr().out

    def test_a_refusal_fails_the_run(self, stale_tree):
        assert handle_command("--stale", ["10d", str(stale_tree["api"] / "nope")]) is False

    @pytest.mark.skipif(_PERMISSIONS_DO_NOT_BIND, reason=_PERMISSIONS_REASON)
    def test_an_unreadable_folder_is_a_refusal_not_a_silence(self, stale_tree):
        locked = stale_tree["api"] / "locked_json"
        locked.mkdir()
        locked.chmod(0)
        try:
            report = _sweep("--stale", "10d", str(stale_tree["api"]))
        finally:
            locked.chmod(0o700)
        assert any("Cannot scan" in message for message in report.refusals)


class TestStaleNeverFallsIntoThePlainLane:
    def test_a_stale_flag_after_the_dir_still_selects_stale_mode(self, stale_tree, monkeypatch):
        """Standing in @api, the plain lane would remove api_json whole."""
        monkeypatch.chdir(stale_tree["api"])
        assert handle_command("api_json", ["--stale", "10d"]) is True
        assert not stale_tree["stale"].exists()
        assert stale_tree["young"].exists()

    @pytest.mark.parametrize(
        "tokens",
        [["--stale=", "api_json"], ["--staleness", "api_json"], ["--stale", "10d", "--dryrun", "api_json"]],
        ids=["empty-age", "unknown-spelling", "typo-dry-run"],
    )
    def test_a_malformed_stale_request_deletes_nothing(self, stale_tree, monkeypatch, tokens):
        monkeypatch.chdir(stale_tree["api"])
        assert handle_command(tokens[0], tokens[1:]) is False
        assert stale_tree["stale"].exists()
        assert stale_tree["young"].exists()
