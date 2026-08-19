"""Tests for drone rm — contained safe-delete.

Red-team containment tests verify that paths outside allowed roots
are refused, including symlink escapes and traversal attempts.
Carve-out tests verify .git, .trinity, .aipass, .codex, .agents,
and sibling branches are protected even inside allowed roots.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.drone.apps.handlers.rm_handler import (
    _detect_current_branch,
    _find_branch_root,
    check_carveouts,
    check_containment,
    get_allowed_roots,
    safe_delete,
)


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

    def test_includes_slash_tmp(self):
        roots = get_allowed_roots()
        if sys.platform != "win32":
            assert Path("/tmp").resolve() in roots

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
        if sys.platform != "win32":
            fake_tmpdir = "/tmp/claude-9999"
            os.makedirs(fake_tmpdir, exist_ok=True)
            try:
                monkeypatch.setenv("TMPDIR", fake_tmpdir)
                tempfile.tempdir = None
                roots = get_allowed_roots()
                resolved_roots = {r for r in roots}
                assert Path("/tmp").resolve() in resolved_roots
                assert Path(fake_tmpdir).resolve() in resolved_roots
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
        outside = Path("/etc/passwd").resolve()
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

    @pytest.mark.usefixtures("_patch_roots")
    def test_slash_tmp_literal_allowed(self):
        """Literal POSIX tmp path must succeed even if $TMPDIR differs."""
        if sys.platform != "win32":
            target = Path("/tmp") / f"rm_test_{os.getpid()}"
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

    def test_print_introspection(self):
        from aipass.drone.apps.modules.rm import print_introspection

        print_introspection()

    def test_print_help(self):
        from aipass.drone.apps.modules.rm import print_help

        print_help()
