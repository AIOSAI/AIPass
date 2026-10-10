# =================== AIPass ====================
# Name: test_git_gate.py
# Version: 5.2.1
# Description: Tests for git_gate: raw git and gh refused for every seat; protected config writes the admin seat's
# Branch: hooks
# Created: 2026-05-21
# Modified: 2026-10-10
# =============================================

"""Tests for apps/handlers/security/git_gate.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that git_gate.py parses and imports, ruff and collection cover it
# seedgo: no-test-needed(documentation) — handle()'s docstring, the documentation standard covers it
# seedgo: no-test-needed(constant) — RAW_GIT_REFUSED's and GH_REDIRECT's full wording; block tests pin key phrases
# seedgo: no-test-needed(stdlib) — re.compile's matching engine, the stdlib's own

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.hooks.apps.handlers.security.git_gate import handle

# Derived, never spelled: the fixtures below are only meaningful as paths INSIDE
# this checkout, and a hardcoded home path makes the suite a property of one
# machine. parents[4] is the repo root — tests -> hooks -> aipass -> src -> root.
_REPO = Path(__file__).resolve().parents[4]


def _word(path) -> str:
    """A path as a command string spells it on every host: bash eats an unquoted backslash (CI red PR #774)."""
    return Path(path).as_posix()


CWD = str(_REPO / "src" / "aipass" / "api")
DEVPULSE_CWD = str(_REPO / "src" / "aipass" / "devpulse")
PROJECT_HOOK = str(_REPO / ".claude" / "hooks" / "some_hook.py")


def _provider_settings() -> str:
    """The provider's settings path, read at call time, never at import."""
    return str(Path.home() / ".claude" / "settings.json")


@pytest.fixture(autouse=True)
def admin_grant():
    """The classifier's tests run from the verified admin seat: since 5.0.0 the grant opens no git or gh lane.

    Patched at @ai_mail's rail, so no test reads this machine's real grant.
    TestRawGitIsRefusedForEverySeat patches it per call for the other seats.
    """
    with patch("aipass.ai_mail.apps.modules.door_verified_caller.is_verified_admin_caller", return_value=True):
        yield


def _bash(cmd: str) -> dict:
    return handle({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": DEVPULSE_CWD})


def _assert_allowed(result: dict) -> None:
    assert result["exit_code"] == 0
    assert result["stdout"] == ""


def _assert_blocked(result: dict) -> None:
    assert result["exit_code"] == 2
    parsed = json.loads(result["stdout"])
    assert parsed["decision"] == "block"


def _reason(result: dict) -> str:
    _assert_blocked(result)
    return json.loads(result["stdout"])["reason"]


class TestGitReadsAreRefusedFromTheAdminSeat:
    """The owner, 2026-10-04: every raw git read is refused, the admin seat (the autouse grant) included.

    Until 5.0.0 this class was TestGitGateReadAllowed: each verb below ran raw from the admin seat.
    """

    @pytest.mark.parametrize(
        "command",
        [
            "git status",
            "git log --oneline -10",
            "git diff HEAD~1",
            "git show HEAD:README.md",
            "git ls-files",
            "git ls-tree HEAD",
            "git cat-file -p HEAD",
            "git check-ignore -v docs.local/notes.md",
            "git check-ignore -q --no-index some/path",
            "git rev-parse HEAD",
            "git rev-list --count HEAD",
            "git blame README.md",
            "git describe --tags",
            "git for-each-ref refs/heads",
            "git show-ref --heads",
            "git symbolic-ref HEAD",
            "git shortlog -sn",
            "git grep TODO",
            "git archive HEAD",
            "git count-objects -v",
            "git var GIT_EDITOR",
            "git help status",
            "git version",
        ],
    )
    def test_every_read_verb_is_refused(self, command):
        assert "every seat, the admin seat included" in _reason(_bash(command))


class TestGitGateGlobalOptions:
    """Global options before the subcommand do not hide the verb the refusal names."""

    @pytest.mark.parametrize(
        ("command", "twin"),
        [
            ("git --no-pager log", "drone @git log"),
            ("git -c core.pager=less status", "drone @git status"),
            ("git --git-dir=/foo/.git log", "drone @git log"),
            ("git --work-tree /foo status", "drone @git status"),
            ("git -C /some/path push", "drone @git pr"),
        ],
    )
    def test_the_twin_is_read_past_the_options(self, command, twin):
        assert twin in _reason(_bash(command))

    @pytest.mark.parametrize("command", ["git -C /some/path cat-file -p x", "git -C /foo -c k=v --no-pager cat-file"])
    def test_a_verb_with_no_twin_past_the_options_is_named(self, command):
        reason = _reason(_bash(command))
        assert "git cat-file has no drone twin" in reason

    def test_git_multiple_opts_push_blocked(self):
        _assert_blocked(_bash("git -C /foo -c key=val --no-pager push"))

    @pytest.mark.parametrize(
        "command",
        [
            "git --config core.hooksPath=/dev/null commit",
            "git --no-pager push",
            "git -c x=y commit",
            "git --git-dir=/x checkout",
            "git --work-tree=/tmp commit -m 'x'",
            "git --bare push origin main",
        ],
    )
    def test_a_write_verb_past_long_form_options_is_blocked(self, command):
        """Absorbed from devpulse's test_git_gate (DPLAN-0163 finding 1): an option before the verb hides no write."""
        _assert_blocked(_bash(command))


class TestGitGateWriteBlocked:
    """Write/ambiguous git verbs are blocked."""

    def test_git_push(self):
        _assert_blocked(_bash("git push"))

    def test_git_commit(self):
        _assert_blocked(_bash("git commit -m 'msg'"))

    def test_git_checkout(self):
        _assert_blocked(_bash("git checkout main"))

    def test_git_switch(self):
        _assert_blocked(_bash("git switch main"))

    def test_git_merge(self):
        _assert_blocked(_bash("git merge feature"))

    def test_git_rebase(self):
        _assert_blocked(_bash("git rebase main"))

    def test_git_reset(self):
        _assert_blocked(_bash("git reset --hard HEAD"))

    def test_git_clone(self):
        _assert_blocked(_bash("git clone https://example.com/repo"))

    def test_git_pull(self):
        _assert_blocked(_bash("git pull"))

    def test_git_fetch(self):
        _assert_blocked(_bash("git fetch origin"))

    def test_git_clean(self):
        _assert_blocked(_bash("git clean -fd"))

    def test_git_stash(self):
        _assert_blocked(_bash("git stash"))

    def test_git_cherry_pick(self):
        _assert_blocked(_bash("git cherry-pick abc123"))

    def test_git_revert(self):
        _assert_blocked(_bash("git revert HEAD"))

    def test_git_rm(self):
        _assert_blocked(_bash("git rm file.py"))

    def test_git_mv(self):
        _assert_blocked(_bash("git mv old.py new.py"))

    def test_git_init(self):
        _assert_blocked(_bash("git init"))

    def test_git_restore(self):
        _assert_blocked(_bash("git restore file.py"))

    def test_git_add(self):
        _assert_blocked(_bash("git add ."))

    def test_git_tag(self):
        _assert_blocked(_bash("git tag v1.0"))

    def test_git_branch(self):
        _assert_blocked(_bash("git branch -D main"))

    def test_git_worktree(self):
        _assert_blocked(_bash("git worktree add ../tmp"))

    def test_git_gc(self):
        _assert_blocked(_bash("git gc"))

    def test_git_prune(self):
        _assert_blocked(_bash("git prune"))

    def test_git_am(self):
        _assert_blocked(_bash("git am patch.mbox"))

    def test_git_apply(self):
        _assert_blocked(_bash("git apply patch.diff"))

    def test_git_config(self):
        _assert_blocked(_bash("git config user.name 'x'"))

    @pytest.mark.parametrize("command", ["git stash drop", "git stash clear", "git stash pop", "git stash apply"])
    def test_each_stash_subcommand_is_blocked(self, command):
        """Absorbed from devpulse's test_git_gate (DPLAN-0404): the stash verbs that drop or rewrite work."""
        _assert_blocked(_bash(command))

    @pytest.mark.parametrize(
        "command",
        [
            "git branch -d old",
            "git branch -m old new",
            "git branch -M old new",
            "git tag -d v1.0",
            "git tag --delete v1.0",
            "git remote add origin url",
            "git remote remove origin",
            "git remote -v",
        ],
    )
    def test_branch_tag_and_remote_operations_are_blocked(self, command):
        """Absorbed from devpulse's test_git_gate (DPLAN-0404): renames, deletes, remote edits, the remote read."""
        _assert_blocked(_bash(command))

    def test_bare_git_prints_usage_and_is_allowed(self):
        """A bare `git` with no argument touches nothing; the shell reads `git ` and `git` alike."""
        _assert_allowed(_bash("git "))


class TestGitGateChaining:
    """Compound commands with mixed git verbs."""

    def test_chained_read_then_write_blocked(self):
        _assert_blocked(_bash("git ls-files && git push"))

    def test_chained_reads_blocked(self):
        _assert_blocked(_bash("git ls-files && git log"))

    def test_piped_read_write_blocked(self):
        _assert_blocked(_bash("git ls-files | git push"))

    def test_semicolon_read_write_blocked(self):
        _assert_blocked(_bash("git status; git commit -m 'msg'"))

    def test_or_read_write_blocked(self):
        _assert_blocked(_bash("git status || git push"))

    def test_read_with_non_git_blocked(self):
        _assert_blocked(_bash("git ls-files && echo done"))


class TestGitGateWordBoundary:
    """Word-boundary and quote handling."""

    def test_gitfoo_not_matched(self):
        _assert_allowed(_bash("gitfoo status"))

    def test_git_in_quoted_string(self):
        _assert_allowed(_bash('echo "git push"'))

    def test_git_in_single_quoted_string(self):
        _assert_allowed(_bash("echo 'git push'"))

    def test_drone_git_allowed(self):
        """KEPT and STRENGTHENED 2026-09-07, not merged (DPLAN-0323 contested band).

        The row arrived on the merge walk because it could not fail: the verb
        was ``status``, which is allowlisted, so removing the ``@`` lookbehind
        at git_gate.py:21 left the result allowed either way. That is a coverage
        GAP wearing the name of a passing test, and deleting it would have left
        the gap while removing the reminder.

        The write verb is what pins the lookbehind: a drone-routed push is the
        sanctioned route and must stay allowed, while the raw form is refused.
        Measured both, 2026-09-07.
        """
        _assert_allowed(_bash("drone @git status"))
        _assert_allowed(_bash("drone @git push"))
        _assert_blocked(_bash("git push"))

    def test_a_path_spelled_git_is_still_git(self):
        """REPLACES test_path_git_not_matched, which pinned the hole as the rule.

        The old unit asserted ``/usr/bin/git push`` was ALLOWED. It passed for
        its whole life because RAW_GIT_RE's lookbehind excludes a leading slash,
        and it made the one mechanical layer holding git writes behind drone a
        full path away from being bypassed. A green test naming the defect is
        worse than no test: it answers the question before anyone asks it.
        Reported 2026-09-11 by an external reader, via @devpulse (static).
        """
        _assert_blocked(_bash("/usr/bin/git push"))

    def test_dotgit_not_matched(self):
        _assert_allowed(_bash("cat .git/config"))

    def test_a_drone_argument_quoting_a_write_verb_stays_allowed(self):
        """Absorbed from devpulse's test_git_gate: a commit message naming `git commit` is an argument, not a call."""
        _assert_allowed(_bash('drone @git pr "fix: git commit msg"'))


class TestPathSpelledExecutable:
    """A git/gh spelled as a path, read only at a command position.

    The four re cases from the report are pinned verbatim (@devpulse
    2026-09-12, from an external reader of a public drone post): the first was
    the hole, the other three were the pattern's working behaviour and must
    stay working. Everything below the blocks is the other half of the rule —
    a path that merely NAMES the binary is not an invocation of it, or the cure
    would refuse `ls /usr/bin/git` and be routed around within the day.
    """

    def test_absolute_path_git_write_is_blocked(self):
        _assert_blocked(_bash("/usr/bin/git commit -m x"))

    def test_bare_git_write_is_still_blocked(self):
        _assert_blocked(_bash("git commit -m x"))

    def test_env_wrapped_git_is_still_blocked(self):
        _assert_blocked(_bash("env git commit"))

    def test_command_wrapped_git_is_still_blocked(self):
        _assert_blocked(_bash("command git commit"))

    def test_relative_and_home_paths_are_blocked_too(self):
        """Wider than reported: the lookbehind excludes `.` as well as `/`."""
        _assert_blocked(_bash("./git commit"))
        _assert_blocked(_bash("~/bin/git commit"))
        _assert_blocked(_bash("/usr/local/bin/git push"))

    def test_assignments_and_flags_before_the_path_do_not_hide_it(self):
        _assert_blocked(_bash("VAR=1 env -i /usr/bin/git commit"))

    def test_a_path_git_in_a_later_clause_is_blocked(self):
        _assert_blocked(_bash("cd /tmp && /usr/bin/git reset --hard"))

    def test_a_bare_path_git_with_no_verb_is_blocked(self):
        """No verb is not a read verb, and a path is nobody's usage print."""
        _assert_blocked(_bash("/usr/bin/git"))

    def test_the_word_git_alone_stays_allowed(self):
        """What the `/` requirement in _path_exec_tail is actually for.

        RAW_GIT_RE matches `git\\s`, so a bare `git` with no arguments was never
        in scope — it prints usage and touches nothing. Dropping the separator
        test from _path_exec_tail would make the new rule read that usage print
        as an unverbed invocation and refuse it. Found by mutation: the mutant
        that removed the check survived every other unit in this class.
        """
        _assert_allowed(_bash("git"))
        _assert_allowed(_bash("echo done; git"))

    def test_a_path_git_read_verb_is_refused_like_the_bare_form(self):
        assert "drone @git status" in _reason(_bash("/usr/bin/git status"))
        assert "drone @git log" in _reason(_bash("./git log --oneline"))

    def test_a_path_that_only_names_git_is_not_an_invocation(self):
        _assert_allowed(_bash("ls /usr/bin/git"))
        _assert_allowed(_bash("rm -rf /path/to/git"))
        _assert_allowed(_bash("cat /srv/proj/.git/config"))
        _assert_allowed(_bash("bash /opt/tools/git_helper.sh"))

    def test_path_spelled_gh_is_ruled_the_same_way(self):
        """Same lookbehind, same file, same hole — `gh` was never read either."""
        _assert_blocked(_bash("/usr/bin/gh pr create"))
        _assert_blocked(_bash("/usr/bin/gh api repos/x"))
        _assert_allowed(_bash("ls /usr/bin/gh"))


class TestGitGateGhCommands:
    """gh on the admin seat (the autouse grant): since 5.0.0 every gh call is refused there too."""

    def test_block_raw_gh(self):
        _assert_blocked(_bash("gh pr list"))

    def test_gh_api_get_is_refused(self):
        _assert_blocked(_bash("gh api repos/owner/repo/pulls"))

    def test_the_admin_seat_keeps_no_gh_api_method(self):
        _assert_blocked(_bash("gh api -X DELETE repos/o/r/git/refs/heads/x"))
        _assert_blocked(_bash("gh api graphql -f query=x"))


class TestGhApiIsRefusedOffTheAdminSeatToo:
    """DPLAN-0356 item 4 made `gh api` GET-only off the admin seat; the owner's 2026-10-04 ruling refuses it
    whole. Measured from canary before item 4: `gh api -X DELETE repos/o/r`, `gh api -X PUT .../contents/f`
    (a commit) and `gh api repos/o/r/merges` (a merge) were all allowed."""

    def _run(self, command: str, tmp_path: Path) -> dict:
        with patch(_RAIL, return_value=False):
            return handle({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": _seat(tmp_path, "canary")})

    @pytest.mark.parametrize(
        "command",
        [
            "gh api repos/o/r/actions/runs",
            "gh api -X GET repos/o/r/pulls",
            "gh api --method=get repos/o/r/issues",
            "gh api repos/o/r/actions/runs --paginate -q .total_count",
            "gh api -H 'Accept: application/vnd.github+json' repos/o/r",
        ],
    )
    def test_a_get_with_no_body_is_refused(self, command, tmp_path):
        assert "gh api GET too" in _reason(self._run(command, tmp_path))

    @pytest.mark.parametrize(
        "command",
        [
            "gh api -X DELETE repos/o/r",
            "gh api -X PUT repos/o/r/contents/f",
            "gh api --method POST repos/o/r/merges",
            "gh api --method=PATCH repos/o/r",
            "gh api -XPOST repos/o/r/merges",
            'gh api -X "DELETE" repos/o/r',
            "gh api repos/o/r/merges -f base=main -f head=dev",
            "gh api repos/o/r/merges -F base=main",
            "gh api repos/o/r/merges --field base=main",
            "gh api repos/o/r/merges --raw-field base=main",
            "gh api repos/o/r/merges --input body.json",
            "gh api -fbase=main repos/o/r/merges",
            "gh api graphql -f query='mutation { x }'",
            "gh api graphql",
            "ls && /usr/bin/gh api -X DELETE repos/o/r",
        ],
    )
    def test_a_write_or_graphql_is_refused_and_names_the_twins(self, command, tmp_path):
        assert "drone @git run list" in _reason(self._run(command, tmp_path))

    def test_every_other_gh_subcommand_stays_refused(self, tmp_path):
        for command in ("gh pr merge 5", "gh repo delete o/r", "gh release create v1", "gh auth token"):
            _assert_blocked(self._run(command, tmp_path))


def _edit(path: str, cwd: str, grant: bool, tool: str = "Edit") -> dict:
    with patch(_RAIL, return_value=grant):
        return handle({"tool_name": tool, "tool_input": {"file_path": path}, "cwd": cwd})


class TestGitGateEditProtection:
    """Protected file edit handling: the verified admin seat alone, never a name (DPLAN-0356 item 5)."""

    def test_block_edit_settings(self):
        _assert_blocked(_edit(_provider_settings(), CWD, grant=False))

    def test_allow_edit_settings_from_the_verified_admin_seat(self):
        _assert_allowed(_edit(_provider_settings(), DEVPULSE_CWD, grant=True))

    def test_a_seat_named_devpulse_or_seedgo_without_the_grant_is_refused(self):
        """TRUSTED_HOOK_EDITORS let these two names through until 2026-09-30, grant or none."""
        for name in ("devpulse", "seedgo"):
            _assert_blocked(_edit(_provider_settings(), str(_REPO / "src" / "aipass" / name), grant=False))

    def test_block_edit_hooks_dir(self):
        _assert_blocked(_edit(PROJECT_HOOK, CWD, grant=False))

    def test_windows_spellings_of_a_protected_path_are_blocked_on_every_host(self):
        """The Windows CI runner measured the gate ALLOWING these (2026-09-16).

        The tests above build their paths from the host, so Linux never saw a
        backslash. These are spelled out so every host exercises the Windows form,
        and in mixed case, which Windows and default macOS filesystems open as the same file.
        """
        for path in (
            r"D:\work\.claude\settings.json",
            r"D:\work\.claude\settings.local.json",
            r"D:\a\repo\.claude\hooks\some_hook.py",
            r"D:\a\repo\.git\hooks\pre-commit",
            r"D:\work\.Claude\Settings.JSON",
            "D:/work/.CLAUDE/hooks/x.py",
        ):
            result = _edit(path, CWD, grant=False)
            assert result["exit_code"] == 2, f"allowed: {path}"

    def test_an_ordinary_file_beside_a_protected_one_stays_allowed(self, tmp_path):
        """Absorbed from devpulse's test_git_gate: .claude/ and .git/ are not protected whole, only their switches."""
        for path in (
            tmp_path / "home" / ".claude" / "CLAUDE.md",
            tmp_path / "home" / "project" / ".git" / "config",
            tmp_path / "home" / "project" / "src" / "aipass" / "devpulse" / "apps" / "handler.py",
        ):
            _assert_allowed(_edit(str(path), CWD, grant=False))

    def test_a_windows_path_that_only_resembles_one_stays_allowed(self):
        for path in (r"D:\work\.claude\settings.json.bak", r"D:\a\repo\.claude\agents\helper.md"):
            _assert_allowed(handle({"tool_name": "Write", "tool_input": {"file_path": path}, "cwd": CWD}))


class TestGitGateMisc:
    """Miscellaneous edge cases."""

    def test_allow_normal_bash(self):
        _assert_allowed(_bash("ls -la"))

    def test_empty_hook_data(self):
        result = handle({})
        assert result["exit_code"] == 0

    def test_block_message_never_offers_a_raw_seat(self):
        reason = _reason(_bash("git push"))
        assert "run raw" not in reason
        assert "Read-only verbs" not in reason

    def test_git_block_explains_why(self):
        assert "if drone cannot do it, it cannot be done" in _reason(_bash("git push"))

    def test_git_block_names_the_twin_and_the_list(self):
        reason = _reason(_bash("git commit -m 'msg'"))
        assert "drone @git commit" in reason
        assert "drone @git --help" in reason

    def test_no_refusal_teaches_switching_a_gate_off(self):
        """DPLAN-0356 item 1: the refusals said "set git_gate.enabled to false in .aipass/hooks.json"."""
        for result in (_bash("git push"), _bash("gh pr list"), _edit(_provider_settings(), CWD, grant=False)):
            reason = json.loads(result["stdout"])["reason"]
            assert "enabled" not in reason
            assert "disable" not in reason.lower()

    def test_gh_block_separate_message(self):
        reason = _reason(_bash("gh pr list"))
        assert "Drone owns gh" in reason
        assert "gh api GET too" in reason
        assert "drone @git issue" in reason

    def test_a_crash_refuses_the_call_it_was_checking(self):
        """DPLAN-0356 item 2: `except: allow` became a refusal for Bash and the edit tools."""
        with patch("aipass.hooks.apps.handlers.security.git_gate._check_bash", side_effect=NameError("x")):
            result = _bash("ls")
        _assert_blocked(result)
        assert "git_gate could not check this call" in json.loads(result["stdout"])["reason"]
        with patch("aipass.hooks.apps.handlers.security.git_gate._check_edit", side_effect=NameError("x")):
            _assert_blocked(handle({"tool_name": "Write", "tool_input": {"file_path": "a"}, "cwd": CWD}))
            _assert_allowed(handle({"tool_name": "Read", "tool_input": {"file_path": "a"}, "cwd": CWD}))


class TestMailBodyIsAnArgumentNotACommand:
    """A heredoc body is data; an interpreter's own text is code.

    @ai_mail was refused twice on 2026-09-15 for a reply whose BODY quoted a
    write-shaped line, and shipped through a file instead; every dispatch brief
    since carried a line telling recipients not to quote one. Quoted spans were
    already blanked here, so the surviving shape was the heredoc — a body that
    carries no quotes to blank.

    The same reading closes the opposite hole in the same move: an interpreter's
    inline script had its whole program blanked as a quoted argument, so a write
    verb inside it was read as no invocation at all.
    """

    #: Assembled rather than written out. The pieces keep the fixture honest —
    #: every test below is the SAME text in a different position, so a failure
    #: names the position and never the wording.
    WRITE_LINE = "gi" + "t push"

    def test_a_heredoc_mail_body_quoting_a_write_line_is_allowed(self):
        body = f"The gate refused my reply because it quoted {self.WRITE_LINE} in prose."
        _assert_allowed(_bash(f"drone @ai_mail reply abc123 <<EOF\n{body}\nEOF"))

    def test_a_heredoc_handed_to_an_interpreter_is_still_blocked(self):
        """The cure must not become a bypass: bash really does run its heredoc."""
        _assert_blocked(_bash(f"bash <<'EOF'\n{self.WRITE_LINE}\nEOF"))

    def test_an_interpreters_inline_script_is_blocked(self):
        """The hole the same reading closes. Quoted, and still a program."""
        _assert_blocked(_bash(f'bash -c "{self.WRITE_LINE}"'))

    def test_a_non_shell_program_that_names_git_is_read_as_its_quotes_were(self):
        """awk and perl are not shell: their quoted programs stay blanked, as before 1.1.0.

        Measured on a real turn 2026-09-16: the first code_text appended every
        interpreter's program, and a read-only awk filter naming a diff header was refused.
        """
        _assert_allowed(_bash("drone @git diff | awk '/^diff --git a\\/x/{p=1} p'"))
        _assert_allowed(_bash(f"perl -e \"print('{self.WRITE_LINE}')\""))
        _assert_allowed(_bash(f"perl <<'EOF'\nprint('{self.WRITE_LINE}')\nEOF"))

    def test_a_quoted_argument_that_merely_names_it_stays_allowed(self):
        """Unchanged behaviour, pinned so the widening above cannot reach it."""
        _assert_allowed(_bash(f'drone @ai_mail reply abc123 "I quoted {self.WRITE_LINE} and was refused"'))

    def test_an_unquoted_invocation_inside_another_commands_arguments_is_blocked(self):
        """Also unchanged: the reading did not narrow to command position.

        find -exec is in bash_writes' published residual for write TARGETS, so
        nothing here may start depending on it being seen as a command.
        """
        _assert_blocked(_bash(f"find . -exec {self.WRITE_LINE} \\;"))

    def test_a_reader_failure_refuses_the_command(self):
        """A gate that cannot parse must not become permissive on what it cannot read."""
        from unittest.mock import patch

        with patch("aipass.hooks.apps.modules.shell_reader.invocations", side_effect=RuntimeError("boom")):
            _assert_blocked(_bash(f"drone @ai_mail reply abc123 <<EOF\n{self.WRITE_LINE}\nEOF"))


class TestOneProgramSpelledManyWays:
    """A rename is not a bypass — the owner's go, 2026-09-19 (devpulse DPLAN-0352).

    Measured on this gate BEFORE the cure: of the write rows below, only the
    bare lowercase one was refused. Windows runs every one of them as git, so
    the single mechanical layer holding git writes behind drone was one spelling
    away from being off — reported 09-16, carried as todo 51 until the go.
    """

    #: Assembled, like WRITE_LINE above and for the same reason: a literal write
    #: invocation in this file refuses the next agent who edits it from a shell.
    WRITE = "commi" + "t -m x"

    WRITES = ("git", "git.exe", "GIT", "Git", "git.EXE", "git.cmd", "/usr/bin/git.exe", "~/bin/git.exe")
    READS = ("git", "git.exe", "GIT", "/usr/bin/git.exe")

    def test_every_spelling_of_a_write_is_blocked(self):
        for spelled in self.WRITES:
            _assert_blocked(_bash(f"{spelled} {self.WRITE}"))

    def test_every_spelling_of_a_read_is_refused_and_names_the_twin(self):
        """Since 5.0.0 a read is refused on the admin seat too, and the twin is named whatever the spelling."""
        for spelled in self.READS:
            assert "drone @git status" in _reason(_bash(f"{spelled} status"))

    def test_gh_is_read_the_same_way(self):
        _assert_blocked(_bash("gh.exe pr create"))
        _assert_blocked(_bash("GH pr create"))
        _assert_blocked(_bash("gh.exe api repos/owner/repo/pulls"))
        _assert_blocked(_bash("GH api repos/owner/repo/pulls"))

    def test_a_dotted_tail_that_is_not_executable_is_not_the_program(self):
        """The regex finds a candidate; verb_name is what makes it a verdict.

        A file NAMED for git is not git. Keeping that quiet is why the list of
        executable extensions lives once in bash_writes instead of being spelled
        into a regex in each gate, where the two copies would drift apart.
        """
        _assert_allowed(_bash("cat some/path/git.py"))
        _assert_allowed(_bash("ls /usr/bin/git"))
        _assert_allowed(_bash(f"node git.js {self.WRITE}"))

    def test_the_reader_being_away_leaves_the_old_narrow_reading(self):
        """Fail-safe direction: the bare spelling still refuses, and the log says so."""
        from unittest.mock import patch

        with patch("aipass.hooks.apps.modules.bash_writes.verb_name", side_effect=RuntimeError("boom")):
            _assert_blocked(_bash(f"git {self.WRITE}"))


_RAIL = "aipass.ai_mail.apps.modules.door_verified_caller.is_verified_admin_caller"


def _seat(root: Path, name: str) -> str:
    """A branch directory carrying a passport that names *name*."""
    seat = root / name
    (seat / ".trinity").mkdir(parents=True, exist_ok=True)
    (seat / ".trinity" / "passport.json").write_text(
        json.dumps({"branch_info": {"branch_name": name}}), encoding="utf-8"
    )
    return str(seat)


class TestRawGitIsRefusedForEverySeat:
    """DPLAN-0356, the owner 2026-09-30 refused raw git reads off @devpulse; 2026-10-04 refused them on it too.

    The grant (@ai_mail's rail, patched here at that edge) no longer opens this lane;
    the passport only names the caller in the refusal.
    """

    def _run(self, command: str, cwd: str, grant: bool) -> dict:
        with patch(_RAIL, return_value=grant):
            return handle({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd})

    def test_git_log_from_canary_is_refused_and_names_the_drone_twins(self, tmp_path):
        reason = _reason(self._run("git log --oneline -5", _seat(tmp_path, "canary"), grant=False))

        assert "@canary" in reason
        assert "drone @git log [count] [path ...]" in reason
        assert "RAW GIT READS AND THEIR TWINS" in reason

    def test_git_log_from_the_verified_admin_seat_is_refused(self, tmp_path):
        reason = _reason(self._run("git log --oneline -5", _seat(tmp_path, "devpulse"), grant=True))
        assert "@devpulse" in reason

    def test_a_seat_named_devpulse_without_the_grant_is_refused(self, tmp_path):
        _assert_blocked(self._run("git status", _seat(tmp_path, "devpulse"), grant=False))

    def test_a_caller_with_no_passport_is_refused_and_told_so(self, tmp_path):
        result = self._run("git status", str(tmp_path), grant=False)

        _assert_blocked(result)
        assert "could not be named" in json.loads(result["stdout"])["reason"]

    def test_quoted_text_naming_git_is_not_an_invocation(self, tmp_path):
        _assert_allowed(self._run('drone @ai_mail email @x "S" "run git log"', _seat(tmp_path, "canary"), grant=False))

    def test_a_write_from_the_admin_seat_is_still_refused(self, tmp_path):
        _assert_blocked(self._run("git " + "push", _seat(tmp_path, "devpulse"), grant=True))


class TestTheFilesThatSwitchTheGatesAreTheAdminSeats:
    """DPLAN-0356 item 1: any branch could write its own .aipass/hooks.json (and so run with no gates),
    and ~/.aipass/trusted_projects.json was named by no gate at all. Both lanes, admin seat only."""

    def _protected(self) -> list[str]:
        return [
            str(_REPO / ".aipass" / "hooks.json"),
            str(_REPO / "src" / "aipass" / "canary" / ".aipass" / "hooks.json"),
            str(Path.home() / ".aipass" / "trusted_projects.json"),
            str(_REPO / ".claude" / "settings.local.json"),
            str(_REPO / "src" / "aipass" / "hooks" / ".live-current"),
            str(_REPO / "src" / "aipass" / "hooks" / ".live-20260930T000000Z" / "handlers" / "x.py"),
        ]

    def test_the_tool_lane_refuses_each_off_the_admin_seat(self, tmp_path):
        canary = _seat(tmp_path, "canary")
        for path in self._protected():
            result = _edit(path, canary, grant=False, tool="Write")
            _assert_blocked(result)
            assert "Only the admin seat" in json.loads(result["stdout"])["reason"], path

    def test_the_bash_lane_refuses_each_off_the_admin_seat(self, tmp_path):
        canary = _seat(tmp_path, "canary")
        for path in self._protected():
            for command in (f"echo x > {path}", f"sed -i s/a/b/ {path}", f"cp other.json {path}"):
                with patch(_RAIL, return_value=False):
                    result = handle({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": canary})
                _assert_blocked(result)

    def test_the_verified_admin_seat_writes_them(self):
        for path in self._protected():
            _assert_allowed(_edit(path, DEVPULSE_CWD, grant=True, tool="Write"))

    def test_an_external_projects_own_config_is_trusts_business_not_this_gates(self, tmp_path):
        _assert_allowed(_edit(str(tmp_path / ".aipass" / "hooks.json"), str(tmp_path), grant=False, tool="Write"))

    def test_reading_them_is_not_a_write(self, tmp_path):
        for path in self._protected()[:3]:
            with patch(_RAIL, return_value=False):
                result = handle({"tool_name": "Bash", "tool_input": {"command": f"cat {path}"}, "cwd": str(tmp_path)})
            _assert_allowed(result)

    def test_a_reader_that_cannot_name_the_changed_paths_refuses(self, tmp_path):
        with (
            patch("aipass.hooks.apps.modules.shell_reader.mutated_paths", side_effect=ValueError("unparseable")),
            patch(_RAIL, return_value=False),
        ):
            result = handle({"tool_name": "Bash", "tool_input": {"command": "x notes.txt"}, "cwd": str(tmp_path)})
        _assert_blocked(result)
        assert "could not check" in json.loads(result["stdout"])["reason"]


def _canary_bash(command: str, cwd: str) -> dict:
    with patch(_RAIL, return_value=False):
        return handle({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd})


@pytest.fixture
def trust_home(tmp_path, monkeypatch):
    """A home of its own holding a trust registry, so a hard link to it is made in tmp, never on this machine."""
    home = tmp_path / "home"
    (home / ".aipass").mkdir(parents=True)
    (home / ".aipass" / "trusted_projects.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home / ".aipass" / "trusted_projects.json"


class TestAProtectedFileIsProtectedUnderEveryName:
    """DPLAN-0356 phase 3, R1 (red team, CRITICAL): the files were matched by NAME.

    A hard link in a seat's own directory is a second name for the trust
    registry; before 2.0.0 of protected_paths a write through it was allowed.
    """

    def test_a_write_through_a_hard_link_is_refused_on_both_lanes(self, tmp_path, trust_home):
        seat = Path(_seat(tmp_path, "canary"))
        os.link(trust_home, seat / "mine.json")

        _assert_blocked(_canary_bash("echo x > mine.json", str(seat)))
        _assert_blocked(_edit(str(seat / "mine.json"), str(seat), grant=False, tool="Write"))

    def test_an_ordinary_file_with_two_names_is_not_protected(self, tmp_path, trust_home):
        seat = Path(_seat(tmp_path, "canary"))
        (seat / "a.json").write_text("{}", encoding="utf-8")
        os.link(seat / "a.json", seat / "b.json")

        _assert_allowed(_canary_bash("echo x > b.json", str(seat)))

    def test_making_a_hard_link_to_one_is_refused_in_shell_and_interpreter_forms(self, tmp_path, trust_home):
        seat = _seat(tmp_path, "canary")
        for command in (
            f"ln {_word(trust_home)} mine.json",
            f"python3 -c \"import os; os.link('{_word(trust_home)}', 'mine.json')\"",
        ):
            _assert_blocked(_canary_bash(command, seat))

    def test_the_admin_seat_still_links_it(self, tmp_path, trust_home):
        with patch(_RAIL, return_value=True):
            result = handle(
                {"tool_name": "Bash", "tool_input": {"command": f"ln {trust_home} x.json"}, "cwd": DEVPULSE_CWD}
            )
        _assert_allowed(result)


class TestTheProtectedLaneRefusesDeletesAndMovesOnItsOwn:
    """DPLAN-0356 phase 3, R2 (red team, CRITICAL): the protected lane watched write verbs only.

    A delete or a move away depended on rm_gate knowing the verb. git_gate now
    refuses each by itself — these run git_gate alone, no rm_gate behind it.
    """

    def test_a_delete_a_move_away_and_a_move_over_are_each_refused(self, tmp_path, trust_home):
        seat = _seat(tmp_path, "canary")
        for command in (
            f"unlink {_word(trust_home)}",
            f"shred -u {_word(trust_home)}",
            f"mv {_word(trust_home)} {_word(tmp_path / 'elsewhere.json')}",
            f"mv new.json {_word(trust_home)}",
            f"python3 -c \"import os; os.remove('{_word(trust_home)}')\"",
        ):
            result = _canary_bash(command, seat)
            _assert_blocked(result)
            assert "is protected" in json.loads(result["stdout"])["reason"], command

    def test_moving_the_directory_that_holds_one_is_refused(self, tmp_path, trust_home):
        command = f"mv {_word(trust_home.parent)} {_word(tmp_path / 'y')}"
        _assert_blocked(_canary_bash(command, _seat(tmp_path, "canary")))

    def test_moving_an_ordinary_file_is_allowed(self, tmp_path, trust_home):
        _assert_allowed(_canary_bash("mv old.json new.json", _seat(tmp_path, "canary")))


class TestGitFromInsideAProgramIsRawGit:
    """DPLAN-0356 phase 3, R5 (red team, HIGH): git and gh launched from an interpreter subprocess."""

    def test_each_launch_spelling_is_refused_off_the_admin_seat(self, tmp_path):
        seat = _seat(tmp_path, "canary")
        for command in (
            "python3 -c \"import subprocess; subprocess.run(['git', 'push'])\"",
            "python3 -c \"import os; os.system('gh pr create')\"",
            "node -e \"require('child_process').execSync('git push')\"",
            'perl -e \'system("git", "push")\'',
        ):
            result = _canary_bash(command, seat)
            _assert_blocked(result)
            assert "inside an interpreter" in json.loads(result["stdout"])["reason"], command

    def test_a_program_that_only_prints_the_word_is_allowed(self, tmp_path):
        _assert_allowed(_canary_bash("python3 -c \"print('git push')\"", _seat(tmp_path, "canary")))


class TestGitHubWritesWithoutGh:
    """DPLAN-0356 phase 3, R6 (red team, MEDIUM): the gh credential and HTTP writes to api.github.com."""

    def test_reading_the_credential_is_refused_off_the_admin_seat(self, tmp_path):
        seat = _seat(tmp_path, "canary")
        for command in (
            "gh auth token",
            "gh auth status --show-token",
            "secret-tool lookup service gh:github.com",
            "python3 -c \"import keyring; print(keyring.get_password('gh:github.com', ''))\"",
        ):
            result = _canary_bash(command, seat)
            _assert_blocked(result)
            assert "GitHub credential" in json.loads(result["stdout"])["reason"], command

    def test_a_non_get_or_a_body_to_the_api_is_refused(self, tmp_path):
        seat = _seat(tmp_path, "canary")
        for command in (
            "curl -X POST https://api.github.com/repos/o/r/issues",
            "curl -d '{}' https://api.github.com/repos/o/r/issues",
            "http PATCH api.github.com/repos/o/r title=x",
        ):
            result = _canary_bash(command, seat)
            _assert_blocked(result)
            assert "GitHub API" in json.loads(result["stdout"])["reason"], command

    def test_a_get_to_the_api_and_a_post_elsewhere_are_allowed(self, tmp_path):
        seat = _seat(tmp_path, "canary")
        _assert_allowed(_canary_bash("curl https://api.github.com/repos/o/r", seat))
        _assert_allowed(_canary_bash("curl -X POST https://example.com/hook -d x", seat))


class TestProtectedPathsAreDefaultDeny:
    """DPLAN-0356 phase 4, P2 (final review, CRITICAL): a write verb nobody listed passed every fence.

    Off the admin seat a protected path may be an operand only of a read-only program.
    Since protected_paths 2.1.0 the set holds AIPASS_HOME's .git/ and every sealed registry.
    """

    def _members(self) -> list[str]:
        return [
            _word(Path.home() / ".aipass" / "trusted_projects.json"),
            _word(_REPO / ".git" / "config"),
            _word(_REPO / ".git" / "refs" / "heads" / "main"),
            _word(_REPO / "AIPASS_REGISTRY.json"),
        ]

    def test_a_program_nobody_listed_is_refused_naming_one(self, tmp_path):
        seat = _seat(tmp_path, "canary")
        for path in self._members():
            for command in (f"vim {path}", f"unknownwriter --in-place {path}", f"tool --out={path}"):
                result = _canary_bash(command, seat)
                _assert_blocked(result)
                assert "is protected" in json.loads(result["stdout"])["reason"], command

    def test_a_read_only_program_may_name_one(self, tmp_path):
        seat = _seat(tmp_path, "canary")
        for path in self._members():
            for command in (f"cat {path}", f"grep x {path}", f"sha256sum {path}", f"sudo cat {path}"):
                _assert_allowed(_canary_bash(command, seat))
        _assert_allowed(_canary_bash("drone @git status", seat))

    def test_a_protected_path_not_yet_written_is_still_refused(self, tmp_path):
        """devpulse 73358617 judges a word by what exists, for the branch lanes. Not here: a new .git hook or
        registry does not exist until it is written, and its first existing ancestor is no branch."""
        seat = _seat(tmp_path, "canary")
        for path in (_REPO / ".git" / "hooks" / "pre-push-new", _REPO / "NEW_REGISTRY.json"):
            assert not path.exists()
            _assert_blocked(_canary_bash(f"unknownwriter {path.as_posix()}", seat))

    def test_a_redirect_into_one_is_refused_even_from_a_read_only_program(self, tmp_path):
        target = self._members()[3]
        _assert_blocked(_canary_bash(f"cat notes.txt > {target}", _seat(tmp_path, "canary")))

    def test_the_admin_seat_is_not_default_denied(self):
        with patch(_RAIL, return_value=True):
            result = handle(
                {"tool_name": "Bash", "tool_input": {"command": f"vim {self._members()[3]}"}, "cwd": DEVPULSE_CWD}
            )
        _assert_allowed(result)


class TestRawGitAndGhAreRefusedForEverySeat:
    """The owner, 2026-10-04: any git command is blocked; if drone cannot do it, it cannot be done.

    The admin carve-out for raw reads (DPLAN-0356, 09-30) is withdrawn. Each lane is
    called from the VERIFIED admin seat (the rail patched True) and must refuse.
    """

    def _admin(self, command: str) -> dict:
        with patch(_RAIL, return_value=True):
            return handle({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": DEVPULSE_CWD})

    def _reason(self, command: str) -> str:
        result = self._admin(command)
        _assert_blocked(result)
        return json.loads(result["stdout"])["reason"]

    @pytest.mark.parametrize(
        ("command", "twin"),
        (
            ("git status", "drone @git status"),
            ("git log -n 5 -- notes.txt", "drone @git log"),
            ("git diff --staged", "drone @git diff"),
            ("git show abc123", "drone @git show"),
            ("git blame -L 1,4 notes.txt", "drone @git blame"),
        ),
    )
    def test_a_raw_git_read_from_the_admin_seat_is_refused_and_names_its_twin(self, command, twin):
        assert twin in self._reason(command)

    @pytest.mark.parametrize(
        ("command", "twin"),
        (
            ("git ls-files apps", "drone @git tracked <path ...>"),
            ("git check-ignore -v docs.local/x.md", "drone @git tracked <path ...>"),
            ("git diff --stat -- apps", "drone @git diff [--staged] [--stat] <path ...>"),
            ("git rev-list --count a...b", "drone @git status --all (ahead/behind line)"),
            ("git merge-base HEAD origin/main", "drone @git status --all (ahead/behind line)"),
            ("git log origin/dev..HEAD", "drone @git log [n] <a>..<b>"),
            ("git archive HEAD", "drone @git export <ref> <dir>"),
        ),
    )
    def test_the_twins_drone_built_on_10_04_are_named(self, command, twin):
        """devpulse 662be795: drone's new read twins; until then each of these said 'cannot be done'."""
        assert twin in self._reason(command)

    @pytest.mark.parametrize("command", ("git cat-file -p HEAD", "git rev-parse HEAD", "git describe --tags"))
    def test_a_read_with_no_twin_says_it_cannot_be_done(self, command):
        reason = self._reason(command)
        assert "cannot be done" in reason and "@devpulse" in reason

    def test_raw_gh_api_get_from_the_admin_seat_is_refused(self):
        assert "drone @git" in self._reason("gh api repos/o/r/actions/runs")

    @pytest.mark.parametrize(
        "command",
        (
            "python3 -c \"import subprocess; subprocess.run(['git', 'status'])\"",
            "gh auth token",
            "curl -X POST https://api.github.com/repos/o/r/issues -d x",
        ),
    )
    def test_the_program_lane_refuses_the_admin_seat(self, command):
        self._reason(command)

    @pytest.mark.parametrize("command", ("drone @git status", "drone @git log 5 notes.txt", "drone @git diff"))
    def test_the_drone_twins_still_run(self, command):
        _assert_allowed(self._admin(command))
