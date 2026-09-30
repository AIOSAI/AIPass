# =================== AIPass ====================
# Name: test_git_gate.py
# Description: Regex coverage for git_gate handler (DPLAN-0163, migrated DPLAN-0184)
# Version: 2.0.0
# Created: 2026-05-03
# Modified: 2026-09-27
# =============================================

"""Tests for src/aipass/hooks/apps/handlers/security/git_gate.py through handle(), the hook engine's door."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — the re module's matching engine under the gate's patterns

import json
from pathlib import Path

import pytest

from aipass.hooks.apps.handlers.security import git_gate


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


class TestReadVerbsAllowed:
    """Read-only git verbs in the allowlist run raw (S193, DPLAN-0195)."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "git status",
            "git log --oneline",
            "git diff",
            "git show HEAD",
            "git ls-files",
            "git ls-tree HEAD",
            "git rev-parse --show-toplevel",
            "git blame README.md",
            "git grep TODO",
            "git archive HEAD",
            "git for-each-ref",
            "git -C sub/x log",
        ],
    )
    def test_allows_read_verbs(self, cmd):
        """Allowlisted read verbs are not blocked — raw is fine."""
        assert not _is_blocked(_bash(cmd)), f"Read verb should be allowed: {cmd}"


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
    """gh write subcommands blocked, gh api allowed."""

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

    @pytest.mark.parametrize(
        "cmd",
        [
            "gh api repos/x/pulls",
        ],
    )
    def test_allows_gh_api(self, cmd):
        """gh api is allowed for read access."""
        assert not _is_blocked(_bash(cmd)), f"Should allow: {cmd}"


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

    def test_trusted_editors_bypass(self, tmp_path):
        """Trusted branches (devpulse, seedgo) can edit protected paths."""
        result = _edit(
            tmp_path / "home" / ".claude" / "hooks" / "test.py",
            tmp_path / "home" / "src" / "aipass" / "devpulse" / "something",
        )
        assert not _is_blocked(result), "devpulse should be trusted editor"


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
