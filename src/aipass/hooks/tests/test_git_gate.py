# =================== AIPass ====================
# Name: test_git_gate.py
# Version: 2.0.0
# Description: Tests for git_gate security handler
# Branch: hooks
# Created: 2026-05-21
# Modified: 2026-06-05
# =============================================

"""Tests for handlers/security/git_gate.py."""

import json

CWD = "/home/patrick/Projects/AIPass/src/aipass/api"


def _bash(cmd: str) -> dict:
    from aipass.hooks.apps.handlers.security.git_gate import handle

    return handle({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": CWD})


def _assert_allowed(result: dict) -> None:
    assert result["exit_code"] == 0
    assert result["stdout"] == ""


def _assert_blocked(result: dict) -> None:
    assert result["exit_code"] == 2
    parsed = json.loads(result["stdout"])
    assert parsed["decision"] == "block"


class TestGitGateReadAllowed:
    """Read-only git verbs are allowed raw."""

    def test_git_status(self):
        _assert_allowed(_bash("git status"))

    def test_git_log(self):
        _assert_allowed(_bash("git log --oneline -10"))

    def test_git_diff(self):
        _assert_allowed(_bash("git diff HEAD~1"))

    def test_git_show(self):
        _assert_allowed(_bash("git show HEAD:README.md"))

    def test_git_ls_files(self):
        _assert_allowed(_bash("git ls-files"))

    def test_git_ls_tree(self):
        _assert_allowed(_bash("git ls-tree HEAD"))

    def test_git_cat_file(self):
        _assert_allowed(_bash("git cat-file -p HEAD"))

    def test_git_rev_parse(self):
        _assert_allowed(_bash("git rev-parse HEAD"))

    def test_git_rev_list(self):
        _assert_allowed(_bash("git rev-list --count HEAD"))

    def test_git_blame(self):
        _assert_allowed(_bash("git blame README.md"))

    def test_git_describe(self):
        _assert_allowed(_bash("git describe --tags"))

    def test_git_for_each_ref(self):
        _assert_allowed(_bash("git for-each-ref refs/heads"))

    def test_git_show_ref(self):
        _assert_allowed(_bash("git show-ref --heads"))

    def test_git_symbolic_ref(self):
        _assert_allowed(_bash("git symbolic-ref HEAD"))

    def test_git_shortlog(self):
        _assert_allowed(_bash("git shortlog -sn"))

    def test_git_grep(self):
        _assert_allowed(_bash("git grep TODO"))

    def test_git_archive(self):
        _assert_allowed(_bash("git archive HEAD"))

    def test_git_count_objects(self):
        _assert_allowed(_bash("git count-objects -v"))

    def test_git_var(self):
        _assert_allowed(_bash("git var GIT_EDITOR"))

    def test_git_help(self):
        _assert_allowed(_bash("git help status"))

    def test_git_version(self):
        _assert_allowed(_bash("git version"))


class TestGitGateGlobalOptions:
    """Read verbs with global options before the subcommand."""

    def test_git_C_path_ls_files(self):
        _assert_allowed(_bash("git -C /some/path ls-files"))

    def test_git_C_path_push_blocked(self):
        _assert_blocked(_bash("git -C /some/path push"))

    def test_git_no_pager_log(self):
        _assert_allowed(_bash("git --no-pager log"))

    def test_git_c_config_status(self):
        _assert_allowed(_bash("git -c core.pager=less status"))

    def test_git_git_dir_log(self):
        _assert_allowed(_bash("git --git-dir=/foo/.git log"))

    def test_git_work_tree_status(self):
        _assert_allowed(_bash("git --work-tree /foo status"))

    def test_git_multiple_opts_ls_files(self):
        _assert_allowed(_bash("git -C /foo -c key=val --no-pager ls-files"))

    def test_git_multiple_opts_push_blocked(self):
        _assert_blocked(_bash("git -C /foo -c key=val --no-pager push"))


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

    def test_bare_git(self):
        _assert_blocked(_bash("git "))


class TestGitGateChaining:
    """Compound commands with mixed git verbs."""

    def test_chained_read_then_write_blocked(self):
        _assert_blocked(_bash("git ls-files && git push"))

    def test_chained_reads_allowed(self):
        _assert_allowed(_bash("git ls-files && git log"))

    def test_piped_read_write_blocked(self):
        _assert_blocked(_bash("git ls-files | git push"))

    def test_semicolon_read_write_blocked(self):
        _assert_blocked(_bash("git status; git commit -m 'msg'"))

    def test_or_read_write_blocked(self):
        _assert_blocked(_bash("git status || git push"))

    def test_read_with_non_git_allowed(self):
        _assert_allowed(_bash("git ls-files && echo done"))


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

    def test_a_path_git_read_verb_is_allowed_like_the_bare_form(self):
        _assert_allowed(_bash("/usr/bin/git status"))
        _assert_allowed(_bash("./git log --oneline"))

    def test_a_path_that_only_names_git_is_not_an_invocation(self):
        _assert_allowed(_bash("ls /usr/bin/git"))
        _assert_allowed(_bash("rm -rf /path/to/git"))
        _assert_allowed(_bash("cat /srv/proj/.git/config"))
        _assert_allowed(_bash("bash /opt/tools/git_helper.sh"))

    def test_path_spelled_gh_is_ruled_the_same_way(self):
        """Same lookbehind, same file, same hole — `gh` was never read either."""
        _assert_blocked(_bash("/usr/bin/gh pr create"))
        _assert_allowed(_bash("/usr/bin/gh api repos/x"))
        _assert_allowed(_bash("ls /usr/bin/gh"))


class TestGitGateGhCommands:
    """gh command handling (unchanged behavior)."""

    def test_block_raw_gh(self):
        _assert_blocked(_bash("gh pr list"))

    def test_allow_gh_api(self):
        _assert_allowed(_bash("gh api repos/owner/repo/pulls"))


class TestGitGateEditProtection:
    """Protected file edit handling."""

    def test_block_edit_settings(self):
        from aipass.hooks.apps.handlers.security.git_gate import handle

        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/home/patrick/.claude/settings.json"},
                "cwd": CWD,
            }
        )
        _assert_blocked(result)

    def test_allow_edit_settings_from_devpulse(self):
        from aipass.hooks.apps.handlers.security.git_gate import handle

        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/home/patrick/.claude/settings.json"},
                "cwd": "/home/patrick/Projects/AIPass/src/aipass/devpulse",
            }
        )
        _assert_allowed(result)

    def test_block_edit_hooks_dir(self):
        from aipass.hooks.apps.handlers.security.git_gate import handle

        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/home/patrick/Projects/AIPass/.claude/hooks/some_hook.py"},
                "cwd": CWD,
            }
        )
        _assert_blocked(result)


class TestGitGateMisc:
    """Miscellaneous edge cases."""

    def test_allow_normal_bash(self):
        _assert_allowed(_bash("ls -la"))

    def test_empty_hook_data(self):
        from aipass.hooks.apps.handlers.security.git_gate import handle

        result = handle({})
        assert result["exit_code"] == 0

    def test_block_message_mentions_read_verbs(self):
        result = _bash("git push")
        parsed = json.loads(result["stdout"])
        assert "Read-only verbs" in parsed["reason"]

    def test_git_block_explains_why(self):
        result = _bash("git push")
        parsed = json.loads(result["stdout"])
        assert "enforces git via drone" in parsed["reason"]

    def test_git_block_lists_drone_commands(self):
        result = _bash("git commit -m 'msg'")
        parsed = json.loads(result["stdout"])
        assert "drone @git commit" in parsed["reason"]
        assert "drone @git smart-sync" in parsed["reason"]
        assert "drone @git --help" in parsed["reason"]

    def test_git_block_shows_disable_path(self):
        result = _bash("git push")
        parsed = json.loads(result["stdout"])
        assert "git_gate.enabled" in parsed["reason"]
        assert "hooks.json" in parsed["reason"]

    def test_gh_block_separate_message(self):
        result = _bash("gh pr list")
        parsed = json.loads(result["stdout"])
        assert "enforces gh via drone" in parsed["reason"]
        assert "gh api" in parsed["reason"]
        assert "drone @git issue" in parsed["reason"]

    def test_edit_block_shows_disable_path(self):
        from aipass.hooks.apps.handlers.security.git_gate import handle

        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/home/patrick/.claude/settings.json"},
                "cwd": CWD,
            }
        )
        parsed = json.loads(result["stdout"])
        assert "git_gate.enabled" in parsed["reason"]
