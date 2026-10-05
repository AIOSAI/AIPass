# =================== AIPass ====================
# Name: test_git_gate.py
# Description: Regex coverage for git_gate handler (DPLAN-0163, migrated DPLAN-0184)
# Version: 2.2.0
# Created: 2026-05-03
# Modified: 2026-10-04
# =============================================

"""Tests for src/aipass/hooks/apps/handlers/security/git_gate.py through handle(), the hook engine's door."""

# 2.2.0: raw git and gh are refused for every seat, the admin seat included (git_gate 5.0.0, the owner's ruling
# of 2026-10-04). The 2.1.0 rows that let the admin seat read raw and run gh api are gone with the carve-out.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — the re module's matching engine under the gate's patterns

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.hooks.apps.handlers.security import git_gate

_ADMIN_RAIL = "aipass.ai_mail.apps.handlers.users.verified_caller.is_verified_admin_caller"


def _is_blocked(result: dict) -> bool:
    """Return True if the handler result represents a block decision."""
    if result.get("exit_code", 0) == 2:
        return True
    stdout = result.get("stdout", "")
    if not stdout:
        return False
    parsed = json.loads(stdout)
    return parsed.get("decision") == "block"


def _bash(cmd: str) -> dict:
    """Run a Bash command through the git gate's hook entry."""
    return git_gate.handle({"tool_name": "Bash", "tool_input": {"command": cmd}})


def _edit(path: Path, cwd: Path) -> dict:
    """Run an edit path through the git gate's hook entry."""
    return git_gate.handle({"tool_name": "Edit", "tool_input": {"file_path": str(path)}, "cwd": str(cwd)})


class TestGitWriteBlocking:
    """Core git write verbs must be blocked."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "git commit -m 'test'",
            "git push origin main",
            "git pull",
            "git merge main",
            "git rebase main",
            "git reset HEAD~1",
            "git checkout -b new-branch",
            "git switch -c new-branch",
            "git cherry-pick abc123",
            "git revert HEAD",
            "git rm file.txt",
            "git mv old.py new.py",
            "git restore --staged file.py",
            "git clean -fd",
            "git config user.name 'x'",
        ],
    )
    def test_blocks_write_verbs(self, cmd):
        """Each blocked git verb triggers the gate."""
        assert _is_blocked(_bash(cmd)), f"Should block: {cmd}"

    @pytest.mark.parametrize(
        "cmd",
        [
            "git stash drop",
            "git stash clear",
            "git stash pop",
            "git stash apply",
        ],
    )
    def test_blocks_stash_destructive(self, cmd):
        """Destructive stash subcommands are blocked."""
        assert _is_blocked(_bash(cmd)), f"Should block: {cmd}"

    @pytest.mark.parametrize(
        "cmd",
        [
            "git branch -D old",
            "git branch -d old",
            "git branch -m old new",
            "git branch -M old new",
            "git tag -d v1.0",
            "git tag --delete v1.0",
            "git remote add origin url",
            "git remote remove origin",
        ],
    )
    def test_blocks_branch_tag_remote_destructive(self, cmd):
        """Destructive branch, tag, and remote operations are blocked."""
        assert _is_blocked(_bash(cmd)), f"Should block: {cmd}"


class TestLongFormFlagBypass:
    """DPLAN-0163 Finding 1: long-form flags must not bypass detection."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "git --config core.hooksPath=/dev/null commit",
            "git --no-pager push",
            "git -c x=y commit",
            "git --git-dir=/x checkout",
            "git --work-tree=/tmp commit -m 'x'",
            "git -C /some/path commit",
            "git --bare push origin main",
        ],
    )
    def test_blocks_long_form_flag_bypass(self, cmd):
        """Long-form flags before the verb must not hide the write verb."""
        assert _is_blocked(_bash(cmd)), f"Should block: {cmd}"


class TestEscapedQuoteBypass:
    """Escaped quotes must not break quote-stripping."""

    @pytest.mark.parametrize(
        "cmd,should_block",
        [
            ('echo "git commit inside quotes"', False),
            ("echo 'git push inside single quotes'", False),
            ('drone @git pr "fix: git commit msg"', False),
            ('git commit -m "msg"', True),
        ],
    )
    def test_escaped_quote_stripping(self, cmd, should_block):
        """Quoted strings containing git verbs must not trigger false positives."""
        assert _is_blocked(_bash(cmd)) == should_block, f"{'Should block' if should_block else 'Should allow'}: {cmd}"


# (command, the drone twin the refusal must name; None = the verb has no twin and says so)
_READ_VERBS = [
    ("git status", "drone @git status"),
    ("git log --oneline", "drone @git log"),
    ("git diff", "drone @git diff"),
    ("git show HEAD", "drone @git show"),
    ("git ls-files", "drone @git tracked"),
    ("git ls-tree HEAD", None),
    ("git rev-parse --show-toplevel", None),
    ("git blame README.md", "drone @git blame"),
    ("git grep TODO", None),
    ("git archive HEAD", "drone @git export"),
    ("git for-each-ref", None),
    ("git -C sub/x log", "drone @git log"),
]


def _reason(result: dict) -> str:
    """The refusal text a blocked result carries."""
    return json.loads(result["stdout"])["reason"]


class TestReadVerbsAreRefusedForEverySeat:
    """Raw git reads are refused for every seat, the admin seat included (the owner, 2026-10-04; git_gate 5.0.0).

    DPLAN-0356 first let the verified admin seat read raw and refused the rest; the owner withdrew that carve-out:
    if drone cannot do it, it cannot be done. The @ai_mail admin rail is patched both ways to pin that it is no
    longer a grant for git — the refusal is the same answer whichever way it leans.
    """

    @pytest.mark.parametrize("admin", [True, False], ids=["admin-seat", "other-seat"])
    @pytest.mark.parametrize(("cmd", "twin"), _READ_VERBS, ids=[c for c, _ in _READ_VERBS])
    def test_raw_read_is_refused(self, cmd, twin, admin):
        """Every read verb is refused on every seat, and the refusal points at the door: its drone twin, or none."""
        with patch(_ADMIN_RAIL, return_value=admin):
            result = _bash(cmd)
        assert _is_blocked(result), f"Raw read must be refused (admin={admin}): {cmd}"
        reason = _reason(result)
        assert "every seat" in reason, f"The refusal must say the rule is for every seat: {cmd}"
        if twin is None:
            assert "has no drone twin" in reason, f"A twinless verb must say so: {cmd}"
        else:
            assert twin in reason, f"The refusal must name the drone twin {twin!r}: {cmd}"


class TestNonAllowlistedGitBlocked:
    """Git verbs outside the read allowlist stay blocked — conservative."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "git fetch",
            "git branch",
            "git tag",
            "git remote -v",
        ],
    )
    def test_blocks_non_allowlisted(self, cmd):
        """Reads not on the allowlist (fetch/branch/tag/remote) still block."""
        assert _is_blocked(_bash(cmd)), f"Should block (use drone): {cmd}"

    @pytest.mark.parametrize(
        "cmd",
        [
            "git log && git push",
            "git status; git commit -m x",
            "git diff | git apply",
        ],
    )
    def test_blocks_chained_read_then_write(self, cmd):
        """A read chained with a write blocks the whole command."""
        assert _is_blocked(_bash(cmd)), f"Chained read+write should block: {cmd}"


class TestDroneNotBlocked:
    """Drone commands must never be blocked."""

    @pytest.mark.parametrize(
        "cmd",
        [
            'drone @git pr "description"',
            'drone @git system-pr "fix"',
            "drone @git smart-sync",
            "drone @git sync",
            "drone @git status",
            "drone @git merge 42",
        ],
    )
    def test_allows_drone(self, cmd):
        """Drone-wrapped git ops are not raw git — must pass."""
        assert not _is_blocked(_bash(cmd)), f"Should allow: {cmd}"


class TestGhBlocking:
    """Raw gh is refused whole: writes, and gh api reads too, for every seat (the owner, 2026-10-04)."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "gh pr create --title x",
            "gh pr merge 42",
            "gh pr close 42",
            "gh issue create",
            "gh issue close 5",
            "gh release create v1",
            "gh repo create x",
        ],
    )
    def test_blocks_gh_writes(self, cmd):
        """State-changing gh subcommands are blocked."""
        assert _is_blocked(_bash(cmd)), f"Should block: {cmd}"

    @pytest.mark.parametrize("admin", [True, False], ids=["admin-seat", "other-seat"])
    @pytest.mark.parametrize("cmd", ["gh api repos/x/pulls", "gh pr list", "gh run view 12"])
    def test_refuses_gh_reads_on_every_seat(self, cmd, admin):
        """gh reads were the last raw door left open (gh api GET); they are refused too, the admin seat included."""
        with patch(_ADMIN_RAIL, return_value=admin):
            result = _bash(cmd)
        assert _is_blocked(result), f"Raw gh read must be refused (admin={admin}): {cmd}"
        assert "every seat" in _reason(result), f"The refusal must say the rule is for every seat: {cmd}"


class TestEditBlocking:
    """Protected file paths must be blocked by edit patterns."""

    @pytest.mark.parametrize(
        "path",
        [
            "home/.claude/settings.json",
            "home/.claude/settings.local.json",
            "home/.claude/hooks/git_gate.py",
            "home/.claude/hooks/pre_edit_gate.py",
            "repo/.git/hooks/pre-commit",
        ],
    )
    def test_blocks_protected_paths(self, path, tmp_path):
        """Enforcement-layer files are protected from edits."""
        assert _is_blocked(_edit(tmp_path / path, tmp_path / "project")), f"Should block edit: {path}"

    @pytest.mark.parametrize(
        "path",
        [
            "home/project/src/main.py",
            "home/.claude/CLAUDE.md",
            "home/project/.git/config",
            "home/project/src/aipass/devpulse/apps/handler.py",
        ],
    )
    def test_allows_normal_paths(self, path, tmp_path):
        """Normal project files are not blocked."""
        assert not _is_blocked(_edit(tmp_path / path, tmp_path / "project")), f"Should allow edit: {path}"

    def test_a_devpulse_named_directory_is_not_a_grant(self, tmp_path):
        """A directory name decides nothing (DPLAN-0356 item 5): off the verified grant, devpulse/ is refused."""
        with patch(_ADMIN_RAIL, return_value=False):
            result = _edit(
                tmp_path / "home" / ".claude" / "hooks" / "test.py",
                tmp_path / "home" / "src" / "aipass" / "devpulse" / "something",
            )
        assert _is_blocked(result), "a devpulse path without the grant must not edit a protected file"

    def test_the_verified_admin_seat_edits_a_protected_path(self, tmp_path):
        """The verified admin grant is the one identity that passes."""
        with patch(_ADMIN_RAIL, return_value=True):
            result = _edit(tmp_path / "home" / ".claude" / "hooks" / "test.py", tmp_path / "project")
        assert not _is_blocked(result), "the verified admin seat should edit a protected path"


class TestNonGitAllowed:
    """Normal commands without git/gh pass through."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "echo hello world",
            "ls -la",
            "cat file.txt",
            "grep -r pattern .",
        ],
    )
    def test_allows_normal_commands(self, cmd):
        """Commands without git/gh are allowed."""
        assert not _is_blocked(_bash(cmd)), f"Should allow: {cmd}"
