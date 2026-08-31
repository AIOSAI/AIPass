# =================== AIPass ====================
# Name: test_edit_gate_bash.py
# Version: 1.0.0
# Description: Tests for the admin exemption and the scripted (Bash) cross-project lane
# Branch: hooks
# Created: 2026-08-30
# Modified: 2026-08-30
# =============================================

"""Tests for edit_gate's scripted lane and the devpulse admin exemption.

Patrick's ruling, 2026-08-30 (devpulse compass 322): the cross-project write
fence stays for every agent and devpulse is the sole exemption — "It is only you
who can reach outwards. Nobody else."

Two halves, one boundary:

1. The admin seat passes, but only on a VERIFIED grant. Every test that grants
   the exemption also has a twin that withholds the grant from the same seat, so
   nothing here can pass on a directory name.
2. Every other seat is blocked on BOTH lanes. The tool lane was already fenced;
   the shell lane (sed -i, redirection, tee, cp, a python heredoc) was open to
   all 18 citizens until this file.
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

_RAIL = "aipass.ai_mail.apps.handlers.users.verified_caller"


@pytest.fixture
def sibling_projects(tmp_path: Path) -> dict:
    """Two top-level projects side by side — the real Projects/ layout.

    The pre-existing project fixture nests one project inside the other, which
    exercises the upward direction only. Tonight's blocked case was SIDEWAYS:
    AIPass and Vera-Studio are siblings, neither contains the other.

        Projects/
          AIPass/        AIPASS_REGISTRY.json
            src/aipass/devpulse/     the admin seat
            src/aipass/hooks/        an ordinary seat
          Vera-Studio/   VERA-STUDIO_REGISTRY.json
            .daemon/schedule.json    the file @devpulse was refused
    """
    projects = tmp_path / "Projects"

    aipass = projects / "AIPass"
    (aipass / "src" / "aipass" / "devpulse").mkdir(parents=True)
    (aipass / "src" / "aipass" / "hooks").mkdir(parents=True)
    (aipass / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")

    vera = projects / "Vera-Studio"
    (vera / ".daemon").mkdir(parents=True)
    (vera / "VERA-STUDIO_REGISTRY.json").write_text("{}", encoding="utf-8")
    schedule = vera / ".daemon" / "schedule.json"
    schedule.write_text('{"jobs": []}', encoding="utf-8")

    return {
        "aipass": aipass,
        "admin_seat": str(aipass / "src" / "aipass" / "devpulse"),
        "plain_seat": str(aipass / "src" / "aipass" / "hooks"),
        "vera": vera,
        "foreign_file": str(schedule),
    }


def _run(cwd: str, *, command: str | None = None, file_path: str | None = None, tool: str = "Bash") -> dict:
    from aipass.hooks.apps.handlers.security.edit_gate import handle

    tool_input = {"command": command} if command is not None else {"file_path": file_path}
    return handle({"tool_name": tool, "tool_input": tool_input, "cwd": cwd})


def _blocked(result: dict) -> bool:
    return result["exit_code"] == 2 and json.loads(result["stdout"]).get("decision") == "block"


def _reason(result: dict) -> str:
    return json.loads(result["stdout"])["reason"]


@pytest.fixture
def grant_granted():
    with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True) as m:
        yield m


@pytest.fixture
def grant_withheld():
    with patch(f"{_RAIL}.is_verified_admin_caller", return_value=False) as m:
        yield m


class TestAdminExemptionToolLane:
    """devpulse's Edit into a sibling project — the write Patrick overruled."""

    @pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit", "NotebookEdit"])
    def test_verified_admin_passes(self, sibling_projects: dict, grant_granted, tool: str):
        result = _run(sibling_projects["admin_seat"], file_path=sibling_projects["foreign_file"], tool=tool)
        assert result["exit_code"] == 0

    @pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit", "NotebookEdit"])
    def test_admin_seat_without_the_grant_is_blocked(self, sibling_projects: dict, grant_withheld, tool: str):
        """The seat is not the credential. Same directory, no grant, refused."""
        result = _run(sibling_projects["admin_seat"], file_path=sibling_projects["foreign_file"], tool=tool)
        assert _blocked(result)
        assert "Vera-Studio" in _reason(result)

    def test_another_seat_is_blocked_even_with_a_valid_grant_on_the_machine(
        self, sibling_projects: dict, grant_withheld
    ):
        """A machine-wide grant is not a machine-wide licence.

        The rail answers for the CALLER, so a grant that verifies for devpulse
        says nothing about @hooks. Withholding here is the rail doing exactly
        that — the seat changed, so the answer changed.
        """
        result = _run(sibling_projects["plain_seat"], file_path=sibling_projects["foreign_file"], tool="Edit")
        assert _blocked(result)


class TestAdminExemptionScriptedLane:
    """The same ruling, on the lane devpulse actually used under authorization."""

    def test_verified_admin_passes_sed(self, sibling_projects: dict, grant_granted):
        command = f"sed -i 's/false/true/' {sibling_projects['foreign_file']}"
        assert _run(sibling_projects["admin_seat"], command=command)["exit_code"] == 0

    def test_admin_seat_without_the_grant_is_blocked_on_sed(self, sibling_projects: dict, grant_withheld):
        command = f"sed -i 's/false/true/' {sibling_projects['foreign_file']}"
        assert _blocked(_run(sibling_projects["admin_seat"], command=command))


class TestAdminIdentityIsVerifiedNotClaimed:
    """The exemption consumes @ai_mail's rail; it never re-implements or guesses."""

    def test_the_session_cwd_is_stamped_for_the_rail(self, sibling_projects: dict):
        """A hook is not drone-invoked, so it must hand the rail the evidence it reads."""
        seen: dict[str, str] = {}

        def spy() -> bool:
            seen["cwd"] = os.environ.get("AIPASS_CALLER_CWD", "<unset>")
            return True

        with patch(f"{_RAIL}.is_verified_admin_caller", side_effect=spy):
            _run(sibling_projects["admin_seat"], file_path=sibling_projects["foreign_file"], tool="Edit")

        assert seen["cwd"] == sibling_projects["admin_seat"]

    def test_the_stamp_does_not_outlive_the_check(self, sibling_projects: dict, grant_granted):
        """A hook process is short-lived, but it is not the only thing in it."""
        os.environ.pop("AIPASS_CALLER_CWD", None)
        _run(sibling_projects["admin_seat"], file_path=sibling_projects["foreign_file"], tool="Edit")
        assert "AIPASS_CALLER_CWD" not in os.environ

    def test_an_existing_caller_stamp_is_never_overwritten(self, sibling_projects: dict, monkeypatch):
        """A drone-invoked caller keeps the identity drone gave it."""
        monkeypatch.setenv("AIPASS_CALLER_CWD", "/somewhere/else")
        seen: dict[str, str] = {}

        def spy() -> bool:
            seen["cwd"] = os.environ.get("AIPASS_CALLER_CWD", "<unset>")
            return True

        with patch(f"{_RAIL}.is_verified_admin_caller", side_effect=spy):
            _run(sibling_projects["admin_seat"], file_path=sibling_projects["foreign_file"], tool="Edit")

        assert seen["cwd"] == "/somewhere/else"

    def test_a_raising_rail_fails_closed(self, sibling_projects: dict):
        with patch(f"{_RAIL}.is_verified_admin_caller", side_effect=RuntimeError("registry unreadable")):
            result = _run(sibling_projects["admin_seat"], file_path=sibling_projects["foreign_file"], tool="Edit")
        assert _blocked(result)

    def test_an_unimportable_rail_fails_closed(self, sibling_projects: dict):
        from aipass.hooks.apps.handlers.security import edit_gate

        with patch.object(edit_gate.importlib, "import_module", side_effect=ImportError("no ai_mail")):
            result = _run(sibling_projects["admin_seat"], file_path=sibling_projects["foreign_file"], tool="Edit")
        assert _blocked(result)

    def test_the_admin_check_is_not_run_for_a_write_that_stays_home(self, sibling_projects: dict):
        """Verification touches the disk; a local write must not pay for it."""
        local = str(Path(sibling_projects["admin_seat"]) / "notes.md")
        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True) as rail:
            assert _run(sibling_projects["admin_seat"], file_path=local, tool="Edit")["exit_code"] == 0
        rail.assert_not_called()


class TestAdminExemptionStaysNarrow:
    """Patrick exempted the OUTWARD reach. Nothing else moved."""

    def test_inbox_writes_are_still_refused_for_the_admin_seat(self, sibling_projects: dict, grant_granted):
        inbox = str(Path(sibling_projects["admin_seat"]) / ".ai_mail.local" / "inbox.json")
        result = _run(sibling_projects["admin_seat"], file_path=inbox, tool="Write")
        assert _blocked(result)
        assert "inbox.json" in _reason(result)

    def test_the_exemption_does_not_reach_a_foreign_project_from_an_ordinary_seat(
        self, sibling_projects: dict, grant_withheld
    ):
        command = f"tee {sibling_projects['foreign_file']}"
        assert _blocked(_run(sibling_projects["plain_seat"], command=command))


class TestScriptedLaneCatches:
    """The write-verbs a shell aims at a foreign project root."""

    def _cmd_blocked(self, sibling_projects: dict, command: str) -> dict:
        return _run(sibling_projects["plain_seat"], command=command)

    def test_sed_in_place(self, sibling_projects: dict, grant_withheld):
        assert _blocked(self._cmd_blocked(sibling_projects, f"sed -i s/a/b/ {sibling_projects['foreign_file']}"))

    def test_truncating_redirection(self, sibling_projects: dict, grant_withheld):
        assert _blocked(self._cmd_blocked(sibling_projects, f"echo '{{}}' > {sibling_projects['foreign_file']}"))

    def test_appending_redirection(self, sibling_projects: dict, grant_withheld):
        assert _blocked(self._cmd_blocked(sibling_projects, f"echo x >> {sibling_projects['foreign_file']}"))

    def test_tee(self, sibling_projects: dict, grant_withheld):
        assert _blocked(self._cmd_blocked(sibling_projects, f"echo x | tee {sibling_projects['foreign_file']}"))

    def test_cp_destination(self, sibling_projects: dict, grant_withheld):
        assert _blocked(self._cmd_blocked(sibling_projects, f"cp ./local.json {sibling_projects['foreign_file']}"))

    def test_mv_destination(self, sibling_projects: dict, grant_withheld):
        assert _blocked(self._cmd_blocked(sibling_projects, f"mv ./local.json {sibling_projects['foreign_file']}"))

    def test_dd_of(self, sibling_projects: dict, grant_withheld):
        assert _blocked(self._cmd_blocked(sibling_projects, f"dd if=/dev/zero of={sibling_projects['foreign_file']}"))

    def test_mkdir_into_a_foreign_project(self, sibling_projects: dict, grant_withheld):
        target = str(Path(sibling_projects["vera"]) / "newdir")
        assert _blocked(self._cmd_blocked(sibling_projects, f"mkdir -p {target}"))

    def test_writing_to_the_foreign_project_root_itself(self, sibling_projects: dict, grant_withheld):
        """The boundary walk starts AT the target, not at its parent.

        A bash operand can name a directory, and a project root's parent holds
        no registry — so starting one level up reads a write INTO Vera-Studio
        as a write into the tree that merely contains it, and allows it.
        """
        command = f"cp ./local.json {sibling_projects['vera']}"
        assert _blocked(self._cmd_blocked(sibling_projects, command))

    def test_python_one_liner(self, sibling_projects: dict, grant_withheld):
        command = f"python3 -c \"import pathlib; pathlib.Path('{sibling_projects['foreign_file']}').write_text('x')\""
        assert _blocked(self._cmd_blocked(sibling_projects, command))

    def test_python_heredoc(self, sibling_projects: dict, grant_withheld):
        """The exact shape @devpulse named: a heredoc, whose body the lexer mangles."""
        command = (
            "python3 <<'EOF'\n"
            "from pathlib import Path\n"
            f"Path('{sibling_projects['foreign_file']}').write_text('{{}}')\n"
            "EOF"
        )
        assert _blocked(self._cmd_blocked(sibling_projects, command))

    def test_cd_then_relative_write(self, sibling_projects: dict, grant_withheld):
        """cd moves the ground the next segment stands on."""
        command = f"cd {sibling_projects['vera']} && sed -i s/a/b/ .daemon/schedule.json"
        assert _blocked(self._cmd_blocked(sibling_projects, command))

    def test_the_refusal_names_the_verb_that_earned_it(self, sibling_projects: dict, grant_withheld):
        result = self._cmd_blocked(sibling_projects, f"sed -i s/a/b/ {sibling_projects['foreign_file']}")
        assert "sed -i" in _reason(result)
        assert "drone @devpulse feedback send" in _reason(result)


class TestScriptedLaneDoesNotOverreach:
    """A gate that refuses correct commands teaches agents to route around it."""

    def _run_plain(self, sibling_projects: dict, command: str) -> dict:
        return _run(sibling_projects["plain_seat"], command=command)

    def test_reading_a_foreign_file_is_allowed(self, sibling_projects: dict):
        assert self._run_plain(sibling_projects, f"cat {sibling_projects['foreign_file']}")["exit_code"] == 0

    def test_reading_foreign_and_writing_home_is_allowed(self, sibling_projects: dict):
        command = f"cat {sibling_projects['foreign_file']} > ./local_copy.json"
        assert self._run_plain(sibling_projects, command)["exit_code"] == 0

    def test_sed_without_in_place_is_a_filter_not_a_write(self, sibling_projects: dict):
        assert self._run_plain(sibling_projects, f"sed s/a/b/ {sibling_projects['foreign_file']}")["exit_code"] == 0

    def test_listing_a_foreign_project_is_allowed(self, sibling_projects: dict):
        assert self._run_plain(sibling_projects, f"ls -la {sibling_projects['vera']}")["exit_code"] == 0

    def test_writing_inside_your_own_project_is_allowed(self, sibling_projects: dict):
        assert self._run_plain(sibling_projects, "sed -i s/a/b/ ./README.md")["exit_code"] == 0

    def test_drone_and_git_name_no_write_verb_this_parser_reads(self, sibling_projects: dict):
        """Their fences stay theirs — and this one is not a second opinion on them."""
        for command in (
            f"drone rm {sibling_projects['foreign_file']}",
            f"git add {sibling_projects['foreign_file']}",
            f"gh api repos/x --input {sibling_projects['foreign_file']}",
        ):
            assert self._run_plain(sibling_projects, command)["exit_code"] == 0, command

    def test_a_redirection_is_still_caught_when_the_tool_carries_its_own_fence(self, sibling_projects: dict):
        """The shell performs that write, not the tool being run."""
        command = f"drone @hooks status > {sibling_projects['foreign_file']}"
        assert _blocked(self._run_plain(sibling_projects, command))

    def test_an_empty_command_is_allowed(self, sibling_projects: dict):
        assert self._run_plain(sibling_projects, "")["exit_code"] == 0

    def test_a_parser_failure_allows_and_says_so(self, sibling_projects: dict):
        from aipass.hooks.apps.handlers.security import edit_gate

        with patch.object(edit_gate.importlib, "import_module", side_effect=RuntimeError("boom")):
            result = self._run_plain(sibling_projects, f"sed -i s/a/b/ {sibling_projects['foreign_file']}")
        assert result["exit_code"] == 0

    def test_a_seat_outside_any_project_is_not_fenced(self, tmp_path: Path):
        """A fence that cannot locate a boundary must not invent one."""
        loose = tmp_path / "loose"
        loose.mkdir()
        assert _run(str(loose), command="sed -i s/a/b/ /tmp/whatever.txt")["exit_code"] == 0


class TestBashWritesParser:
    """Unit-level reading of the parser, independent of the fence."""

    def test_unbalanced_quotes_fall_back_rather_than_going_quiet(self):
        from aipass.hooks.apps.modules.bash_writes import write_targets

        targets = write_targets("echo 'unterminated > /tmp/x.json", "/tmp")
        assert any(str(t).endswith("x.json") for t, _ in targets)

    def test_a_variable_path_is_skipped_not_guessed(self):
        from aipass.hooks.apps.modules.bash_writes import write_targets

        assert write_targets("sed -i s/a/b/ $TARGET/schedule.json", "/tmp") == []

    def test_descriptor_duplication_is_not_a_filename(self):
        from aipass.hooks.apps.modules.bash_writes import write_targets

        assert write_targets("some_command 2>&1", "/tmp") == []

    def test_a_quoted_heredoc_body_is_data_not_shell(self):
        """Found live: this gate blocked the reply describing its own proof.

        A mail body assembled with ``cat <<EOF`` that QUOTES a shell command had
        its quoted text read as real syntax. cat cannot write anywhere; the
        redirection inside the body belongs to the prose, not to the shell.
        """
        from aipass.hooks.apps.modules.bash_writes import write_targets

        command = "BODY=$(cat <<'EOF'\necho probe > /other/Project/x.tmp\nEOF\n)\ndrone @ai_mail reply id \"$BODY\""
        assert write_targets(command, "/tmp") == []

    def test_stripping_heredoc_bodies_does_not_weaken_the_interpreter_rule(self):
        """The python-heredoc catch was the point; it survives the fix."""
        from aipass.hooks.apps.modules.bash_writes import write_targets

        command = "python3 <<'EOF'\nfrom pathlib import Path\nPath('/other/Project/x.json').write_text('{}')\nEOF"
        targets = [str(t) for t, _ in write_targets(command, "/tmp")]
        assert "/other/Project/x.json" in targets

    def test_a_real_redirection_on_the_heredoc_opening_line_still_counts(self):
        """Only the BODY stops being syntax — the opening line is still shell."""
        from aipass.hooks.apps.modules.bash_writes import write_targets

        command = "cat <<'EOF' > /other/Project/out.txt\njust some text\nEOF"
        targets = [str(t) for t, _ in write_targets(command, "/tmp")]
        assert "/other/Project/out.txt" in targets

    def test_the_residual_gap_is_published_not_implied(self):
        """What the parser cannot see is data, so the reply, README and tests agree."""
        from aipass.hooks.apps.modules.bash_writes import NOT_CAUGHT

        assert NOT_CAUGHT
        joined = " ".join(NOT_CAUGHT)
        for named in ("symlink", "xargs", "chmod", "git"):
            assert named in joined
