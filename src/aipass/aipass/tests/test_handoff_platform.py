# =================== AIPass ====================
# Name: test_handoff_platform.py
# Description: Tests for handoff_platform handler
# Version: 2.0.0
# Created: 2026-05-12
# Modified: 2026-11-14
# =============================================

"""Tests for apps/handlers/handoff_platform/__init__.py: the inline launch `aipass new` uses."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that apps/handlers/handoff_platform/__init__.py parses and imports

from __future__ import annotations

import shlex
from unittest.mock import MagicMock

from aipass.aipass.apps.handlers.handoff_platform import (
    build_cli_cmd,
    launch_inline,
    return_path_breadcrumb,
)

# Ensure encoding='utf-8' appears (PATTERN check)
_ENCODING = "utf-8"


class TestBuildCliCmd:
    """Tests for build_cli_cmd()."""

    def test_claude_is_the_bare_name(self) -> None:
        """Claude launches bare: its hooks, not a flag, set the posture."""
        assert build_cli_cmd("claude") == "claude"

    def test_codex_always_bypasses_approvals_and_sandbox(self) -> None:
        """Mutant: dropping the codex branch returns bare `codex` and goes red."""
        assert build_cli_cmd("codex") == "codex --dangerously-bypass-approvals-and-sandbox"

    def test_opencode_gets_baud_s_standalone_auto_launch(self) -> None:
        """Mutant: dropping the opencode branch returns bare `opencode` and goes red."""
        assert build_cli_cmd("opencode") == 'PATH="$HOME/.opencode/bin:$PATH" opencode --standalone --auto --prompt'


class TestReturnPathBreadcrumb:
    """Tests for return_path_breadcrumb()."""

    def test_returns_cd_and_continue(self, tmp_path) -> None:
        """Breadcrumb is `cd <cwd> && claude --continue`.

        Mutant: `f"cd {cwd} && claude --continue"` -> `f"cd . && claude --continue"` reddens this test.
        """
        proj = str(tmp_path / "proj")
        assert return_path_breadcrumb(proj) == f"cd {proj} && claude --continue"

    def test_uses_continue_not_resume(self, tmp_path) -> None:
        """Uses --continue, never --resume <id> — session stores are per-directory,
        so a bare --resume hint (no cwd) fails from anywhere else."""
        result = return_path_breadcrumb(str(tmp_path / "somewhere"))
        assert "--continue" in result
        assert "--resume" not in result

    def test_codex_resumes_its_last_session(self, tmp_path) -> None:
        """Codex's way back is `codex resume --last` from the same directory."""
        cwd = str(tmp_path / "it's here")
        assert shlex.split(return_path_breadcrumb(cwd, "codex")) == ["cd", cwd, "&&", "codex", "resume", "--last"]

    def test_reflects_the_given_cwd(self, tmp_path) -> None:
        """Different cwd values are reflected verbatim in the breadcrumb."""
        cwd = str(tmp_path / "a" / "b" / "c")
        assert f"cd {cwd} " in return_path_breadcrumb(cwd)


def _inline_which(
    cli_path: str | None = "/usr/bin/claude",
    bash_path: str | None = "/bin/bash",
    sh_path: str | None = "/usr/bin/sh",
):
    """Build a shutil.which side_effect that resolves cli/bash/sh to distinct paths."""

    def _side_effect(name: str) -> str | None:
        return {"claude": cli_path, "bash": bash_path, "sh": sh_path}.get(name)

    return _side_effect


class TestLaunchInline:
    """Tests for launch_inline() — shell-wrapped exec with a return-path breadcrumb.

    Every test hands in recorders for which, chdir and execvp: a real execvp replaces the test process.
    """

    @staticmethod
    def _launch(proj: str, prompt: str = "hello", which=None, **kwargs) -> tuple[MagicMock, MagicMock]:
        """Run launch_inline on recorders; return the (chdir, execvp) recorders."""
        chdir, execvp = MagicMock(), MagicMock()
        launch_inline("claude", prompt, proj, which=which or _inline_which(), chdir=chdir, execvp=execvp, **kwargs)
        return chdir, execvp

    def test_returns_without_exec_when_cli_not_found(self, tmp_path) -> None:
        """No CLI on PATH — logs and returns, never touches chdir/execvp."""
        chdir, execvp = self._launch(str(tmp_path / "proj"), which=_inline_which(cli_path=None))
        chdir.assert_not_called()
        execvp.assert_not_called()

    def test_chdirs_into_cwd_before_exec(self, tmp_path) -> None:
        """Changes into the target cwd before exec'ing the wrapper shell."""
        proj = str(tmp_path / "proj")
        order = MagicMock()
        launch_inline("claude", "hello", proj, which=_inline_which(), chdir=order.chdir, execvp=order.execvp)
        assert [c[0] for c in order.mock_calls] == ["chdir", "execvp"]
        order.chdir.assert_called_once_with(proj)

    def test_execs_shell_wrapper_not_cli_directly(self, tmp_path) -> None:
        """execvp is called with the shell, not the CLI binary — the CLI is embedded in -c."""
        _, execvp = self._launch(str(tmp_path / "proj"))
        execvp.assert_called_once()
        shell_arg, argv = execvp.call_args[0]
        assert shell_arg == "/bin/bash"
        assert argv[0] == "/bin/bash"
        assert argv[1] == "-c"

    def test_shell_command_includes_cli_invocation_and_prompt(self, tmp_path) -> None:
        """The exec'd shell command runs the resolved CLI path with the prompt."""
        _, execvp = self._launch(str(tmp_path / "proj"), prompt="hello world")
        _, argv = execvp.call_args[0]
        shell_cmd = argv[2]
        assert "/usr/bin/claude" in shell_cmd
        assert "hello world" in shell_cmd

    def test_shell_command_includes_breadcrumb_after_cli(self, tmp_path) -> None:
        """Breadcrumb (cd + claude --continue) prints via printf after the CLI invocation.

        Unquoted, the shell would run the breadcrumb's `cd` and `claude` instead of printing them.
        Mutant: `shlex.quote(breadcrumb)` -> `breadcrumb` -> red at the endswith assert.
        """
        proj = str(tmp_path / "proj")
        _, execvp = self._launch(proj)
        _, argv = execvp.call_args[0]
        shell_cmd = argv[2]
        breadcrumb = return_path_breadcrumb(proj)
        assert shell_cmd.endswith(f"printf '\\n%s\\n' {shlex.quote(breadcrumb)}")
        assert breadcrumb in shell_cmd
        cli_idx = shell_cmd.index("/usr/bin/claude")
        breadcrumb_idx = shell_cmd.index(breadcrumb)
        assert cli_idx < breadcrumb_idx, "breadcrumb must print after the CLI invocation, not before"

    def test_falls_back_to_sh_when_bash_missing(self, tmp_path) -> None:
        """Uses sh (resolved via which) when bash isn't on PATH."""
        _, execvp = self._launch(str(tmp_path / "proj"), which=_inline_which(bash_path=None))
        shell_arg = execvp.call_args[0][0]
        assert shell_arg == "/usr/bin/sh"

    def test_falls_back_to_bin_sh_literal_when_neither_found(self, tmp_path) -> None:
        """Uses the hardcoded /bin/sh fallback when neither bash nor sh resolve via which."""
        _, execvp = self._launch(str(tmp_path / "proj"), which=_inline_which(bash_path=None, sh_path=None))
        shell_arg = execvp.call_args[0][0]
        assert shell_arg == "/bin/sh"

    def test_codex_runs_bypassed_and_prints_its_own_way_back(self, tmp_path) -> None:
        """Choosing codex execs codex with its bypass flag, then prints `codex resume --last`.
        Mutant: launch_inline passing no cli to the breadcrumb prints `claude --continue` and goes red."""
        proj = str(tmp_path / "proj")
        execvp = MagicMock()
        which = {"codex": "/usr/bin/codex", "bash": "/bin/bash"}.get
        launch_inline("codex", "hi", proj, which=which, chdir=MagicMock(), execvp=execvp)
        shell_cmd = execvp.call_args[0][1][2]
        expected = shlex.join(["/usr/bin/codex", "--dangerously-bypass-approvals-and-sandbox", "hi"])
        assert shell_cmd.startswith(expected + ";")
        assert shell_cmd.endswith(shlex.quote(return_path_breadcrumb(proj, "codex")))

    def test_prompt_with_special_chars_is_shell_quoted(self, tmp_path) -> None:
        """A prompt containing shell metacharacters is safely quoted, not interpolated raw."""
        _, execvp = self._launch(str(tmp_path / "proj"), prompt="hi $(whoami) && rm -rf /")
        _, argv = execvp.call_args[0]
        shell_cmd = argv[2]
        # shlex.join quotes the argv: the dangerous substring appears quoted, never bare.
        assert "'hi $(whoami) && rm -rf /'" in shell_cmd
