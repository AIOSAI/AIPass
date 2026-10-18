# =================== AIPass ====================
# Name: test_edit_gate_bash.py
# Version: 1.7.0
# Description: Tests for the edit gate's scripted lane (passport refused since 1.1.0)
# Branch: hooks
# Created: 2026-08-30
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/security/edit_gate.py's scripted lane and apps/modules/bash_writes.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that edit_gate.py and bash_writes.py parse and import
# seedgo: no-test-needed(constant) — NO_WRITE_VERB's text, the marker testwrite_gate reads

import importlib
import json
import os
import shutil
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from unittest.mock import patch

import pytest

from aipass.hooks.apps.handlers.security import edit_gate
from aipass.hooks.apps.modules import bash_writes
from aipass.hooks.apps.modules.bash_writes import write_targets

# The cross-project fence holds on both lanes for every seat; only the admin seat passes, on a VERIFIED
# grant, and each granted test has a withheld twin. POSIX literals are test data; a path put into a
# command uses as_posix() (bash's form on every OS); backslashes are tested only through _win().

_RAIL = "aipass.ai_mail.apps.modules.door_verified_caller"
_BASH_WRITES = "aipass.hooks.apps.modules.bash_writes"


@pytest.fixture
def sibling_projects(tmp_path: Path) -> dict:
    """Two top-level projects side by side — the real Projects/ layout.

    Siblings, so the sideways crossing is pinned (the nested fixture covers only upward).
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


def _names(targets, *parts: str) -> bool:
    """True when some target ends in these components, in any OS's spelling.

    Targets stay OS-native (project_of globs the real filesystem), so never assert on str(target).
    """
    return any(tuple(t.parts[-len(parts) :]) == parts for t, _ in targets)


def _run(cwd: str, *, command: str | None = None, file_path: str | None = None, tool: str = "Bash") -> dict:
    tool_input = {"command": command} if command is not None else {"file_path": file_path}
    return edit_gate.handle({"tool_name": tool, "tool_input": tool_input, "cwd": cwd})


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
    """devpulse's Edit into a sibling project — the write the owner overruled."""

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
        """A machine-wide grant is not a machine-wide licence: the rail answers for the CALLER."""
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

    def test_the_stamp_does_not_outlive_the_check(self, sibling_projects: dict, grant_granted, monkeypatch):
        """A hook process is short-lived, but it is not the only thing in it.

        monkeypatch.delenv, not os.environ.pop: a raw pop outlives the test and is not restored on failure.
        """
        monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
        _run(sibling_projects["admin_seat"], file_path=sibling_projects["foreign_file"], tool="Edit")
        assert "AIPASS_CALLER_CWD" not in os.environ

    def test_an_existing_caller_stamp_is_never_overwritten(self, sibling_projects: dict, monkeypatch, tmp_path: Path):
        """A drone-invoked caller keeps the identity drone gave it."""
        elsewhere = str(tmp_path / "elsewhere")
        monkeypatch.setenv("AIPASS_CALLER_CWD", elsewhere)
        seen: dict[str, str] = {}

        def spy() -> bool:
            seen["cwd"] = os.environ.get("AIPASS_CALLER_CWD", "<unset>")
            return True

        with patch(f"{_RAIL}.is_verified_admin_caller", side_effect=spy):
            _run(sibling_projects["admin_seat"], file_path=sibling_projects["foreign_file"], tool="Edit")

        assert seen["cwd"] == elsewhere

    def test_a_raising_rail_fails_closed(self, sibling_projects: dict):
        with patch(f"{_RAIL}.is_verified_admin_caller", side_effect=RuntimeError("registry unreadable")):
            result = _run(sibling_projects["admin_seat"], file_path=sibling_projects["foreign_file"], tool="Edit")
        assert _blocked(result)

    def test_an_unimportable_rail_fails_closed(self, sibling_projects: dict, grant_granted):
        """Only the rail is missing; the fence itself is a call-time import too.

        The grant is given, so only the dark rail can refuse; a None sys.modules entry did not isolate it.
        """
        real = edit_gate._import_module

        def _no_rail(name: str):
            if name.endswith("admin_seat") or name.startswith("aipass.ai_mail"):
                raise ImportError("no ai_mail")
            return real(name)

        with patch.object(edit_gate, "_import_module", side_effect=_no_rail):
            result = _run(sibling_projects["admin_seat"], file_path=sibling_projects["foreign_file"], tool="Edit")
        assert _blocked(result)

    def test_the_admin_check_is_not_run_for_a_write_that_stays_home(self, sibling_projects: dict):
        """Verification touches the disk; a local write must not pay for it."""
        local = str(Path(sibling_projects["admin_seat"]) / "notes.md")
        with patch(f"{_RAIL}.is_verified_admin_caller", return_value=True) as rail:
            assert _run(sibling_projects["admin_seat"], file_path=local, tool="Edit")["exit_code"] == 0
        rail.assert_not_called()


class TestAdminExemptionStaysNarrow:
    """The owner exempted the OUTWARD reach. Nothing else moved."""

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

        An operand can name a project root, whose parent holds no registry.
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

    # Own files only, on this lane too: the project boundary alone would let hooks sed another branch.

    def test_sed_into_another_branch(self, registered_projects: dict):
        target = (Path(registered_projects["memory"]) / "apps" / "x.py").as_posix()
        result = _run(registered_projects["hooks"], command=f"sed -i s/a/b/ {target}")
        assert _blocked(result)
        assert "Cross-branch write blocked (sed -i): 'hooks' cannot write to 'memory'" in _reason(result)

    def test_redirection_into_a_project_level_file(self, registered_projects: dict):
        target = (registered_projects["aipass"] / "notes.md").as_posix()
        result = _run(registered_projects["hooks"], command=f"echo x > {target}")
        assert _blocked(result)
        assert "Project-level write blocked" in _reason(result)

    def test_tee_into_the_managers_branch_from_an_ordinary_agent(self, registered_projects: dict):
        target = (Path(registered_projects["vera_seat"]) / "brand.md").as_posix()
        assert _blocked(_run(registered_projects["writer"], command=f"echo x | tee {target}"))

    def test_cp_down_into_a_nested_project(self, registered_projects: dict, grant_withheld):
        target = (Path(registered_projects["baud_seat"]) / "app.py").as_posix()
        result = _run(registered_projects["hooks"], command=f"cp ./app.py {target}")
        assert _blocked(result)
        assert "Cross-project" in _reason(result)


class TestScriptedLaneDoesNotOverreach:
    """A gate that refuses correct commands teaches agents to route around it."""

    def _run_plain(self, sibling_projects: dict, command: str) -> dict:
        return _run(sibling_projects["plain_seat"], command=command)

    def test_reading_a_foreign_file_is_allowed(self, sibling_projects: dict):
        assert self._run_plain(sibling_projects, f"cat {sibling_projects['foreign_file']}")["exit_code"] == 0

    def test_reading_foreign_and_writing_home_is_allowed(self, sibling_projects: dict):
        command = f"cat {sibling_projects['foreign_file']} > ./local_copy.json"
        assert self._run_plain(sibling_projects, command)["exit_code"] == 0

    def test_a_program_that_only_reads_may_name_a_foreign_file(self, sibling_projects: dict):
        """Default-deny: only a read-only program may name it as an operand.

        sed without -i can still write (w) or run (e), so it is not read as a filter.
        """
        foreign = Path(sibling_projects["foreign_file"]).as_posix()  # bash eats an unquoted backslash (PR #774)
        assert self._run_plain(sibling_projects, f"sed s/a/b/ {foreign}")["exit_code"] == 2
        assert self._run_plain(sibling_projects, f"grep a {foreign}")["exit_code"] == 0
        assert self._run_plain(sibling_projects, f"cat {foreign}")["exit_code"] == 0

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

    def test_a_parser_failure_refuses_the_call(self, sibling_projects: dict, monkeypatch):
        """A fence that cannot read a command does not let it through."""
        monkeypatch.setitem(sys.modules, _BASH_WRITES, None)
        with pytest.raises(ImportError) as raised:
            importlib.import_module(_BASH_WRITES)
        result = self._run_plain(sibling_projects, f"sed -i s/a/b/ {sibling_projects['foreign_file']}")
        assert result["exit_code"] == 2
        assert str(raised.value) in json.loads(result["stdout"])["reason"]

    def test_a_seat_outside_any_project_is_not_fenced(self, tmp_path: Path):
        """A fence that cannot locate a boundary must not invent one."""
        loose = tmp_path / "loose"
        loose.mkdir()
        target = (tmp_path / "whatever.txt").as_posix()
        assert _run(str(loose), command=f"sed -i s/a/b/ {target}")["exit_code"] == 0

    def test_an_interpreter_reading_another_branch_is_allowed(self, registered_projects: dict):
        """Inside one project the branch fence convicts on write grammar only.

        An interpreter's held paths cannot be told from reads; the residual is published in docs/edit_gate.md.
        """
        target = (Path(registered_projects["memory"]) / "apps" / "x.py").as_posix()
        for command in (f"python3 -c \"print(open('{target}').read())\"", f"grep def {target}", f"cat {target}"):
            assert _run(registered_projects["hooks"], command=command)["exit_code"] == 0, command
        # awk is not a read-only program (print > file, system()), so it may not name it.
        assert _run(registered_projects["hooks"], command=f"awk '/def /' {target}")["exit_code"] == 2

    def test_seedgo_and_the_manager_no_longer_write_across_branches_from_a_shell(self, registered_projects: dict):
        """A name (seedgo) and a manager row (vera) decide nothing in the shell lane either."""
        memory = (Path(registered_projects["memory"]) / "apps" / "x.py").as_posix()
        writer = (Path(registered_projects["writer"]) / "draft.md").as_posix()
        assert _run(registered_projects["seedgo"], command=f"sed -i s/a/b/ {memory}")["exit_code"] == 2
        assert _run(registered_projects["vera_seat"], command=f"sed -i s/a/b/ {writer}")["exit_code"] == 2

    def test_a_projects_manager_writes_its_unrowed_files_from_a_shell(self, registered_projects: dict):
        root = (registered_projects["vera"] / "README.md").as_posix()
        app = (registered_projects["baud"] / "app" / "src" / "x.tsx").as_posix()
        assert _run(registered_projects["vera_seat"], command=f"sed -i s/a/b/ {root}")["exit_code"] == 0
        assert _run(registered_projects["baud_seat"], command=f"echo x > {app}")["exit_code"] == 0
        assert _run(registered_projects["writer"], command=f"sed -i s/a/b/ {root}")["exit_code"] == 2

    def test_an_aipass_update_dry_run_is_a_read_and_the_update_is_a_write(self, registered_projects: dict):
        root = registered_projects["vera"].as_posix()
        assert _run(registered_projects["writer"], command=f"aipass init update {root} --dry-run")["exit_code"] == 0
        assert _run(registered_projects["writer"], command=f"aipass init update --dry-run {root}")["exit_code"] == 0
        assert _run(registered_projects["writer"], command=f"aipass init update {root}")["exit_code"] == 2
        assert _run(registered_projects["writer"], command=f"aipass init run {root} --dry-run")["exit_code"] == 2

    def test_a_shells_syntax_check_is_a_read_and_running_the_script_is_not(self, registered_projects: dict):
        script = (registered_projects["aipass"] / "setup.sh").as_posix()
        Path(script).write_text("echo hi\n", encoding="utf-8")
        assert _run(registered_projects["hooks"], command=f"bash -n {script}")["exit_code"] == 0
        for command in (f"bash {script}", f"bash {script} -n"):
            assert _run(registered_projects["hooks"], command=command)["exit_code"] == 2, command

    def test_writing_your_own_branch_stays_allowed(self, registered_projects: dict):
        own = (Path(registered_projects["hooks"]) / "docs" / "x.md").as_posix()
        for command in (f"echo x > {own}", f"sed -i s/a/b/ {own}", "mkdir -p ./docs.local/probe"):
            assert _run(registered_projects["hooks"], command=command)["exit_code"] == 0, command


class TestShellWritesToMemoryAreRefused:
    """A memory file is written where its caps are measured (the Edit/Write lane), never from a shell."""

    @pytest.mark.parametrize(
        "command",
        [
            "echo '{}' > .trinity/local.json",
            "echo x >> .trinity/observations.json",
            "echo x | tee .trinity/local.json",
            "sed -i s/a/b/ .trinity/local.json",
            "cp docs/draft.json .trinity/local.json",
            "python3 -c \"open('.trinity/local.json', 'w').write('{}')\"",
            "python3 - <<'PY'\nfrom pathlib import Path\nPath('.trinity/observations.json').write_text('{}')\nPY",
            "cd .trinity && echo x > local.json",
        ],
        ids=["redirect", "append", "tee", "sed-i", "cp", "python-c", "python-heredoc", "cd-then-redirect"],
    )
    def test_every_shape_the_reader_sees_is_refused(self, sibling_projects: dict, command: str):
        result = _run(sibling_projects["plain_seat"], command=command)
        assert _blocked(result), command
        assert "Edit or Write tool" in _reason(result)

    def test_the_refusal_names_the_file_the_verb_and_where_memory_is_written(self, sibling_projects: dict):
        reason = _reason(_run(sibling_projects["plain_seat"], command="sed -i s/a/b/ .trinity/local.json"))
        assert "local.json via sed -i" in reason
        assert "drone @memory" in reason

    def test_the_admin_seat_is_refused_too(self, sibling_projects: dict, grant_granted):
        """The admin exemption reaches other projects. It says nothing about how memory is written."""
        assert _blocked(_run(sibling_projects["admin_seat"], command="echo x > .trinity/local.json"))

    def test_a_seat_outside_any_project_is_refused_too(self, tmp_path: Path):
        """The project fence needs a boundary to draw; this rule needs only the file."""
        loose = tmp_path / "loose"
        loose.mkdir()
        assert _blocked(_run(str(loose), command="echo x > .trinity/local.json"))

    def test_an_interpreter_that_only_reads_is_refused_and_told_how_to_read(self, sibling_projects: dict):
        """The published over-refusal: the interpreter rule cannot tell a read from a write."""
        command = "python3 -c \"import json; print(json.load(open('.trinity/local.json')))\""
        result = _run(sibling_projects["plain_seat"], command=command)
        assert _blocked(result)
        assert "Read tool, cat or jq" in _reason(result)

    def test_the_cure_drops_the_fleet_clauses_where_there_is_no_fleet(self, sibling_projects: dict):
        """This gate ships to projects `aipass init` creates, and they have no @memory.

        A cure naming an absent service is one agents route around instead of reporting.
        """
        from unittest.mock import patch

        target = "aipass.hooks.apps.handlers.security.edit_gate._memory_service_reachable"
        with patch(target, return_value=False):
            reason = _reason(_run(sibling_projects["plain_seat"], command="sed -i s/a/b/ .trinity/local.json"))

        assert "local.json via sed -i" in reason
        assert "Edit or Write tool" in reason
        assert "drone @memory" not in reason
        assert "@memory's caps are measured" not in reason


class TestShellMemoryRuleDoesNotOverreach:
    """Reads, drone verbs and every other file stay open. A rule that refuses correct commands gets routed around."""

    @pytest.mark.parametrize(
        "command",
        [
            "cat .trinity/local.json | jq .",
            "jq . .trinity/local.json > docs/trinity_copy.json",
            "wc -c .trinity/local.json .trinity/observations.json",
            "drone @memory lint",
            "echo x > docs/local.json",
            "echo x > observations.json",
            "echo x > docs/passport.json",
        ],
        ids=["cat-jq", "jq-elsewhere", "wc", "drone-memory", "local-json-elsewhere", "bare-name", "passport-elsewhere"],
    )
    def test_reads_verbs_and_other_files_are_allowed(self, sibling_projects: dict, command: str):
        assert _run(sibling_projects["plain_seat"], command=command)["exit_code"] == 0, command

    def test_a_shell_write_to_a_passport_is_refused_like_the_other_two(self, sibling_projects: dict):
        """passport.json is capped like the other two .trinity files, so a shell write to it is refused."""
        result = _run(sibling_projects["plain_seat"], command="echo x > .trinity/passport.json")
        assert _blocked(result)
        assert "passport.json" in _reason(result)


class TestTheVerbIsReadTheSameOnEveryHost:
    """One program, four spellings — the reading the gates share.

    ``CP.EXE`` is cp on a Windows host, not an unknown program that names no target.
    """

    def test_verb_name_reads_path_extension_and_case(self):
        assert bash_writes.verb_name("rm") == "rm"
        assert bash_writes.verb_name("RM.EXE") == "rm"
        assert bash_writes.verb_name("/usr/bin/git") == "git"
        assert bash_writes.verb_name("C:\\Program Files\\Git\\bin\\git.exe") == "git"
        assert bash_writes.verb_name("git.cmd") == "git"

    def test_a_non_executable_extension_is_part_of_the_name(self):
        """A file NAMED for a program is not that program — `git.py` stays quiet."""
        assert bash_writes.verb_name("git.py") == "git.py"
        assert bash_writes.verb_name("some/path/rm.txt") == "rm.txt"
        assert bash_writes.verb_name(".bashrc") == ".bashrc"

    def test_a_renamed_write_verb_still_names_its_target(self, tmp_path: Path):
        mine = str(tmp_path / "Mine")
        assert _names(write_targets("CP.EXE a.json /work/Other/b.json", mine), "Other", "b.json")
        assert _names(write_targets("TOUCH /work/Other/new.json", mine), "Other", "new.json")


class TestBashWritesParser:
    """Unit-level reading of the parser, independent of the fence."""

    def test_unbalanced_quotes_fall_back_rather_than_going_quiet(self, tmp_path: Path):
        targets = write_targets("echo 'unterminated > x.json", str(tmp_path))
        assert any(str(t).endswith("x.json") for t, _ in targets)

    def test_a_variable_path_is_skipped_not_guessed(self, tmp_path: Path):
        assert write_targets("sed -i s/a/b/ $TARGET/schedule.json", str(tmp_path)) == []

    def test_descriptor_duplication_is_not_a_filename(self, tmp_path: Path):
        assert write_targets("some_command 2>&1", str(tmp_path)) == []

    def test_a_quoted_heredoc_body_is_data_not_shell(self, tmp_path: Path):
        """A redirection quoted inside a ``cat <<EOF`` body belongs to the prose, not to the shell."""
        command = "BODY=$(cat <<'EOF'\necho probe > /other/Project/x.tmp\nEOF\n)\ndrone @ai_mail reply id \"$BODY\""
        assert write_targets(command, str(tmp_path)) == []

    def test_stripping_heredoc_bodies_does_not_weaken_the_interpreter_rule(self, tmp_path: Path):
        """The python-heredoc catch was the point; it survives the fix."""
        command = "python3 <<'EOF'\nfrom pathlib import Path\nPath('/other/Project/x.json').write_text('{}')\nEOF"
        targets = write_targets(command, str(tmp_path))
        assert _names(targets, "other", "Project", "x.json"), f"heredoc body surrendered nothing: {targets}"

    def test_a_real_redirection_on_the_heredoc_opening_line_still_counts(self, tmp_path: Path):
        """Only the BODY stops being syntax — the opening line is still shell."""
        command = "cat <<'EOF' > /other/Project/out.txt\njust some text\nEOF"
        targets = write_targets(command, str(tmp_path))
        assert _names(targets, "other", "Project", "out.txt"), f"opening-line redirection lost: {targets}"

    def test_the_residual_gap_is_published_not_implied(self):
        """What the parser cannot see is data, so the reply, README and tests agree."""
        assert bash_writes.NOT_CAUGHT
        joined = " ".join(bash_writes.NOT_CAUGHT)
        for named in ("symlink", "xargs", "chmod", "git", "pipe", "no separator", "joined", "sponge"):
            assert named in joined

    def test_no_usable_cwd_raises_rather_than_reading_no_writes(self, tmp_path: Path, monkeypatch):
        """With no cwd to resolve against, the reader raises; [] would let a relative write through.

        Windows refuses to remove a process's cwd, so there the command is read as before.
        """
        gone = tmp_path / "gone"
        gone.mkdir()
        monkeypatch.chdir(gone)
        shutil.rmtree(gone, ignore_errors=True)  # the platform answers by whether the directory is still there
        if not gone.exists():
            with pytest.raises(OSError):
                bash_writes.write_targets_by_segment("echo hi > out.txt", "")
        else:
            assert write_targets("echo hi > out.txt", "") == [(gone / "out.txt", "redirection (>)")]

    @pytest.mark.parametrize(
        ("command", "named"),
        [
            ("sed -i 68,90p other/branch/file.py", ["other/branch/file.py"]),
            ("sed -ni 1p file.py", ["file.py"]),
            ("sed -i.bak 1d file.py", ["file.py"]),
            ("sed -Ei 's/a/b/' file.py", ["file.py"]),
            ("sed -e 1d -i file.py", ["file.py"]),
            ("sed -i 1d a.py b.py", ["a.py", "b.py"]),
            ("sed -i s/a/b/ file.py", ["file.py"]),
            ("sed -n 68,90p file.py", []),
        ],
        ids=["non-path-script", "ni-cluster", "i-suffix", "Ei-cluster", "e-script", "two-files", "script", "read"],
    )
    def test_sed_in_place_names_every_file_and_never_its_script(self, tmp_path: Path, command: str, named: list):
        """A non-path script must not drop the real target, and -ni is in place."""
        assert write_targets(command, str(tmp_path)) == [(tmp_path / name, "sed -i") for name in named]


class TestEveryLineIsACommand:
    """A newline separates commands: shlex reads it as blank space, gluing line two onto line one."""

    def test_a_write_on_line_two_is_seen(self, tmp_path: Path):
        targets = write_targets("true\ntouch made.json", str(tmp_path))
        assert _names(targets, tmp_path.name, "made.json"), targets

    def test_a_cd_on_its_own_line_moves_the_ground(self, tmp_path: Path):
        targets = write_targets(f"cd {(tmp_path / 'sub').as_posix()}\nsed -i s/a/b/ f.json", str(tmp_path))
        assert _names(targets, "sub", "f.json"), targets

    def test_a_continued_line_is_still_one_command(self, tmp_path: Path):
        """The newline split must not break a backslash continuation in two."""
        targets = write_targets("sed -i s/a/b/ \\\n  f.json", str(tmp_path))
        assert _names(targets, tmp_path.name, "f.json"), targets

    def test_a_comment_line_ends_at_its_newline(self, tmp_path: Path):
        targets = write_targets("# the next line writes\ntouch made.json", str(tmp_path))
        assert _names(targets, tmp_path.name, "made.json"), targets

    def test_a_trailing_comment_names_no_target(self, tmp_path: Path):
        targets = write_targets("cp a.json b.json # was c.json", str(tmp_path))
        assert _names(targets, tmp_path.name, "b.json")
        assert not _names(targets, tmp_path.name, "c.json"), targets

    def test_a_hash_inside_a_word_is_not_a_comment(self, tmp_path: Path):
        """shlex's own rule cut the line at ANY '#', so a URL fragment hid the write after it."""
        targets = write_targets("echo host/#frag && touch made.json", str(tmp_path))
        assert _names(targets, tmp_path.name, "made.json"), targets

    def test_a_quoted_hash_is_data(self, tmp_path: Path):
        """The '#' starts a word INSIDE the quotes - only quote tracking keeps it data.
        (MUTATION-CHECK: "'# header'" would pass with quote tracking off.)"""
        targets = write_targets("echo 'see # header' > made.json", str(tmp_path))
        assert _names(targets, tmp_path.name, "made.json"), targets

    def test_a_subshell_cd_ends_with_the_subshell(self, tmp_path: Path):
        command = f"(cd {(tmp_path / 'sub').as_posix()} && touch inner.json); touch outer.json"
        targets = write_targets(command, str(tmp_path))
        assert _names(targets, "sub", "inner.json"), targets
        assert _names(targets, tmp_path.name, "outer.json"), targets

    def test_the_fence_now_sees_a_foreign_write_on_line_two(self, sibling_projects: dict, grant_withheld):
        command = f"true\nsed -i s/a/b/ {Path(sibling_projects['foreign_file']).as_posix()}"
        assert _blocked(_run(sibling_projects["plain_seat"], command=command))

    def test_the_fence_now_follows_a_cd_on_line_one(self, sibling_projects: dict, grant_withheld):
        command = f"cd {sibling_projects['vera'].as_posix()}\nsed -i s/a/b/ .daemon/schedule.json"
        assert _blocked(_run(sibling_projects["plain_seat"], command=command))


class TestAnInterpreterHoldsOnlyItsOwnText:
    """An interpreter claims only its own segment's paths, resolved from where it stands."""

    def test_another_commands_path_is_not_claimed(self, tmp_path: Path):
        command = f"python3 - <<'EOF'\nprint(1)\nEOF\ncd {(tmp_path / 'sub').as_posix()} && cat data/x.json"
        targets = write_targets(command, str(tmp_path))
        assert not any("x.json" in t.parts for t, _ in targets), targets

    def test_each_heredoc_goes_to_the_interpreter_that_opened_it(self, tmp_path: Path):
        """Attribution AND ground: the second body resolves where the second python stands."""
        sub = (tmp_path / "sub").as_posix()
        command = f"python3 - <<'A'\nopen('one/x.json')\nA\ncd {sub} && python3 - <<'B'\nopen('two/y.json')\nB"
        targets = write_targets(command, str(tmp_path))
        assert _names(targets, tmp_path.name, "one", "x.json"), targets
        assert _names(targets, "sub", "two", "y.json"), targets
        assert not _names(targets, tmp_path.name, "two", "y.json"), targets
        assert not _names(targets, "sub", "one", "x.json"), targets

    def test_its_own_arguments_are_still_held(self, tmp_path: Path):
        targets = write_targets("cat notes.txt && python3 tool.py out/r.json", str(tmp_path))
        assert _names(targets, tmp_path.name, "out", "r.json"), targets

    def test_openers_and_bodies_that_disagree_keep_the_whole_command_read(self, tmp_path: Path):
        """A here-string looks like a heredoc to the body reader and not to the lexer.
        When the two cannot be paired, every interpreter keeps the old, broader read."""
        command = "python3 -c 'print(1)' && cat <<<EOF\nfar/z.json\nEOF"
        targets = write_targets(command, str(tmp_path))
        assert _names(targets, tmp_path.name, "far", "z.json"), targets


def _win(path) -> str:
    """Spell a path the way Windows spells it, on whatever OS is reading."""
    return str(path).replace("/", "\\")


class TestWindowsSpelledPathsAreStillFenced:
    """Backslash separators must not walk a foreign write past the fence.

    POSIX shlex reads a backslash as an escape, collapsing a foreign path into one local filename.
    """

    def _cmd(self, sibling_projects: dict, command: str) -> dict:
        return _run(sibling_projects["plain_seat"], command=command)

    def test_sed_in_place_with_backslash_separators(self, sibling_projects, grant_withheld):
        """sed -i into a sibling project, backslash-spelled: exit 2, not 0."""
        target = _win(sibling_projects["foreign_file"])

        result = self._cmd(sibling_projects, f"sed -i s/a/b/ {target}")

        assert _blocked(result), f"backslash-spelled sed -i was ALLOWED: {result}"
        assert "Vera-Studio" in _reason(result)

    def test_redirection_with_backslash_separators(self, sibling_projects, grant_withheld):
        target = _win(Path(sibling_projects["vera"]) / "notes.txt")

        assert _blocked(self._cmd(sibling_projects, f"echo x > {target}")), "backslash redirection allowed"

    def test_copy_destination_with_backslash_separators(self, sibling_projects, grant_withheld):
        target = _win(Path(sibling_projects["vera"]) / "copy.txt")

        assert _blocked(self._cmd(sibling_projects, f"cp local.txt {target}")), "backslash cp allowed"

    def test_interpreter_holding_a_backslash_path(self, sibling_projects, grant_withheld):
        """The interpreter scan must read "\\" as a separator, or a Windows path matches nothing."""
        target = _win(sibling_projects["foreign_file"])

        result = self._cmd(sibling_projects, f"python3 -c \"open('{target}', 'w')\"")

        assert _blocked(result), f"interpreter holding a backslash path was ALLOWED: {result}"

    def test_cd_chain_with_backslash_separators(self, sibling_projects, grant_withheld):
        """`cd` moves the ground for the next segment in either spelling."""
        vera = _win(sibling_projects["vera"])

        result = self._cmd(sibling_projects, f"cd {vera} && tee out.txt")

        assert _blocked(result), f"backslash cd-chain was ALLOWED: {result}"

    def test_directory_target_with_no_extension(self, sibling_projects, grant_withheld):
        """`mkdir C:\\Proj\\Vera\\newdir` — no dot anywhere to fall back on.

        Pins _looks_like_path's backslash clause: a dotted filename passes on the dot clause alone.
        """
        target = _win(Path(sibling_projects["vera"]) / "newdir")
        assert "." not in target, f"precondition lost — this path has a dot to fall back on: {target}"

        assert _blocked(self._cmd(sibling_projects, f"mkdir {target}")), "backslash mkdir allowed"

    def test_local_write_stays_allowed_in_both_spellings(self, sibling_projects, grant_withheld):
        """The fix must not convict the seat's own project of being foreign."""
        own = _win(Path(sibling_projects["plain_seat"]) / "mine.txt")

        result = self._cmd(sibling_projects, f"echo x > {own}")

        assert result["exit_code"] == 0, f"a write into the seat's own project was refused: {result}"


class TestBothSpellingsAreRead:
    """Parser level: neither dialect may be chosen at the other's expense."""

    def test_posix_escaped_space_survives(self, tmp_path: Path):
        """shlex's escape reading is still produced — it is correct for POSIX."""
        segments = bash_writes.write_targets_by_segment(r"cp a\ b.txt dest.txt", str(tmp_path))
        readings = [tokens for tokens, _ in segments]

        assert ["cp", "a b.txt", "dest.txt"] in readings, f"escape reading lost: {readings}"

    def test_separator_reading_is_produced_too(self, tmp_path: Path):
        """The separator-keeping reading is produced alongside the escape reading."""
        segments = bash_writes.write_targets_by_segment(r"sed -i s/a/b/ C:\Proj\Vera\f.json", str(tmp_path))
        readings = [tokens for tokens, _ in segments]

        assert any(r"C:\Proj\Vera\f.json" in tokens for tokens in readings), (
            f"no reading kept the separators: {readings}"
        )

    def test_a_command_with_no_backslash_is_read_once(self, tmp_path: Path):
        """No cost where the dialects agree — and no duplicate refusal lines."""
        assert len(bash_writes.write_targets_by_segment("echo hi > out.txt", str(tmp_path))) == 1

    def test_a_target_named_twice_is_reported_once(self):
        """Both readings can find the SAME write; the caller is told once.

        The backslash is off the target, so both readings agree on `out.txt` and the duplicate is real.
        """
        command = r'python3 -c "print(\"hi\")" > out.txt'
        readings = bash_writes.write_targets_by_segment(command, str(Path.cwd()))
        assert len(readings) == 2, "precondition: both readings must run"

        hits = bash_writes.write_targets(command, str(Path.cwd()))

        assert len(hits) == len(set(hits)), f"the same write was reported twice: {hits}"

    def test_separators_alone_are_not_a_path(self):
        """Widening the run to accept "\\" made every escaped quote match.

        A refusal listing paths the command never named is one nobody believes.
        """
        hits = bash_writes.write_targets(r'python3 -c "print(\"hi\")"', str(Path.cwd()))

        assert all(any(c.isalnum() for c in t.name) for t, _ in hits), f"separator-only target: {hits}"

    def test_the_cross_os_root_limit_is_published(self):
        """A drive letter names nothing on Linux — said as data, not discovered."""
        assert any("operating system" in gap for gap in bash_writes.NOT_CAUGHT), (
            "the cross-OS root residual is not in NOT_CAUGHT"
        )


class TestTargetSpellingIsNotPartOfTheContract:
    """Tests compare target components, never str(target), which differs per OS."""

    def test_names_accepts_the_windows_rendering(self):
        """The Windows rendering, compared on any OS: the tests above are green on Linux either way."""
        as_windows = [(PureWindowsPath(r"\other\Project\x.json"), "python3 (interpreter)")]

        assert _names(as_windows, "other", "Project", "x.json")

    def test_names_does_not_match_a_shorter_tail(self):
        """A comparison loose enough to pass anywhere proves nothing."""
        targets = [(PurePosixPath("/somewhere/else/x.json"), "why")]

        assert not _names(targets, "other", "Project", "x.json")

    def test_the_target_list_stays_os_native(self):
        """The ruling, pinned: normalise on the way IN, never on the way out.

        project_of globs the real filesystem; a canonicalised list is unwalkable on the other OS.
        """
        from pathlib import Path as LocalPath

        targets = write_targets("echo x > sub/out.txt", str(LocalPath.cwd()))

        assert targets, "precondition: the command must name a target"
        assert all(isinstance(t, LocalPath) for t, _ in targets), (
            f"targets are not the local Path flavour the fence must walk: {targets}"
        )


def _read_as(monkeypatch, pure: type) -> None:
    """The platform oracle: bash_writes builds every path in *pure*'s flavour.

    expanduser is the only concrete method the reader calls, and a pure path has none.
    """

    class Flavour(pure):
        def expanduser(self):
            return self

    monkeypatch.setattr("aipass.hooks.apps.modules.bash_writes.Path", Flavour)


class TestTheGitBashDriveSpelling:
    """Git Bash's /c/... names drive C on Windows, not C:\\c\\... on the seat's drive."""

    SEAT = r"C:\Work\AIPass\src\aipass\hooks"
    VERA_FILE = PureWindowsPath(r"C:\Work\Vera-Studio\f.json")

    @pytest.mark.parametrize(
        "command",
        [
            "sed -i s/a/b/ /c/Work/Vera-Studio/f.json",
            "cd /c/Work/Vera-Studio && sed -i s/a/b/ f.json",
            "cd /c/Work/Vera-Studio\nsed -i s/a/b/ f.json",
            "sed -i s/a/b/ C:/Work/Vera-Studio/f.json",
        ],
    )
    def test_a_drive_path_names_the_drive_on_windows(self, monkeypatch, command):
        _read_as(monkeypatch, PureWindowsPath)

        assert [t for t, _ in write_targets(command, self.SEAT)] == [self.VERA_FILE]

    def test_the_bare_drive_is_its_root(self, monkeypatch):
        """/c alone is C:/, never the drive-relative C:, which pathlib joins as the seat itself."""
        _read_as(monkeypatch, PureWindowsPath)

        assert [t for t, _ in write_targets("cd /c && touch x.json", self.SEAT)] == [PureWindowsPath(r"C:\x.json")]

    def test_a_longer_first_component_is_not_a_drive(self, monkeypatch):
        """/cache is a directory on the seat's drive, not drive C with 'ache' under it."""
        _read_as(monkeypatch, PureWindowsPath)

        targets = [t for t, _ in write_targets("sed -i s/a/b/ /cache/f.json", self.SEAT)]
        assert targets == [PureWindowsPath(r"C:\cache\f.json")], targets

    def test_the_respelled_ci_pin_lands_on_the_existing_test(self, monkeypatch):
        """test_a_subshell_cd_resolves_its_own_edit, read the way windows-setup reads it.

        On Linux as_posix() changes nothing; this shows C:/... reaches the real file on Windows.
        """
        _read_as(monkeypatch, PureWindowsPath)
        command = "(cd C:/Work/AIPass && sed -i s/a/b/ src/aipass/hooks/te" + "sts/test_existing.py)"

        targets = [t for t, _ in write_targets(command, self.SEAT)]
        assert targets == [PureWindowsPath(self.SEAT) / "tests" / "test_existing.py"], targets

    def test_on_posix_a_one_letter_directory_is_only_a_directory(self, monkeypatch, tmp_path: Path):
        """The drive reading is Windows-only. On Linux /c is a real directory named c."""
        _read_as(monkeypatch, PurePosixPath)

        targets = [t for t, _ in write_targets("sed -i s/a/b/ /c/Work/f.json", tmp_path.as_posix())]
        assert targets == [PurePosixPath("/c/Work/f.json")], targets


class TestTheBranchAndMemoryLanesAreDefaultDeny:
    """An unlisted program naming another branch or a .trinity file is refused, not passed."""

    def test_an_unlisted_program_naming_another_branch_is_refused(self, registered_projects: dict):
        target = (Path(registered_projects["memory"]) / "apps" / "x.py").as_posix()
        assert _blocked(_run(registered_projects["hooks"], command=f"unknownwriter --in-place {target}"))
        assert _run(registered_projects["hooks"], command=f"grep def {target}")["exit_code"] == 0

    def test_an_unlisted_program_naming_a_memory_file_is_refused(self, registered_projects: dict):
        seat = Path(registered_projects["hooks"])
        memory = (seat / ".trinity" / "local.json").as_posix()
        assert _blocked(_run(str(seat), command=f"unknownwriter {memory}"))
        assert _run(str(seat), command=f"jq . {memory}")["exit_code"] == 0

    @pytest.mark.parametrize("cd", ["cd", "pushd"])
    def test_a_cd_into_another_branch_is_a_read_not_a_write(self, registered_projects: dict, grant_withheld, cd):
        """`cd <AIPass>/src/aipass && ...`: cd's directory is not a write.
        Only the cd is cured: pytest naming another branch's directory stays that branch's."""
        seat = Path(registered_projects["hooks"])
        other = Path(registered_projects["memory"]).as_posix()
        for command in (f"{cd} {seat.parent.as_posix()} && pytest hooks/tests -q", f"{cd} {other} && popd"):
            result = _run(registered_projects["hooks"], command=command)
            assert result["exit_code"] == 0, result["stdout"]

    def test_a_cd_does_not_carry_a_delete_past_the_fence(self, registered_projects: dict, grant_withheld):
        other = Path(registered_projects["memory"]).as_posix()
        assert _blocked(_run(registered_projects["hooks"], command=f"cd {other} && rm apps/x.py"))

    @pytest.mark.parametrize("flags", ["-p no:cacheprovider", "-k cd_into", "-k slow/net"])
    def test_a_flag_value_is_not_a_branch_write(self, registered_projects: dict, grant_withheld, flags):
        """A word that does not exist, whose first existing ancestor is src/aipass, names no file.

        `-k slow/net` pins the first-existing-ancestor walk: its parent src/aipass/slow looks like a branch.
        """
        aipass = Path(registered_projects["hooks"]).parent.as_posix()
        result = _run(registered_projects["hooks"], command=f"cd {aipass} && pytest hooks/tests {flags}")
        assert result["exit_code"] == 0, result["stdout"]

    def test_a_new_file_in_another_branch_is_still_a_write(self, registered_projects: dict, grant_withheld):
        aipass = Path(registered_projects["hooks"]).parent
        other = (aipass / "flow" / "new.py").as_posix()
        assert _blocked(_run(registered_projects["hooks"], command=f"cd {aipass.as_posix()} && cp x {other}"))
        assert _blocked(_run(registered_projects["hooks"], command=f"unknownwriter {other}"))

    def test_an_existing_file_in_another_branch_is_still_refused(self, registered_projects: dict, grant_withheld):
        existing = Path(registered_projects["memory"]) / "existing.py"
        existing.write_text("x = 1\n", encoding="utf-8")
        assert _blocked(_run(registered_projects["hooks"], command=f"rm {existing.as_posix()}"))

    def test_a_project_whose_directory_cannot_be_listed_is_refused_not_read_as_none(
        self, registered_projects: dict, grant_withheld, tmp_path: Path
    ):
        """An unlistable directory (0o300) must not read as no project: glob answers [] for it.
        Where the platform still lists it (Windows, root) the crossing rule refuses instead."""
        locked = tmp_path / "Projects" / "Locked"
        locked.mkdir(parents=True)
        (locked / "LOCKED_REGISTRY.json").write_text('{"branches": []}', encoding="utf-8")
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        locked.chmod(0o300)
        try:
            command = f"cp x {(locked / 'new.py').as_posix()}"
            assert _blocked(_run(registered_projects["hooks"], command=command))
            assert (
                _run(registered_projects["hooks"], command=f"cp x {(scratch / 'new.py').as_posix()}")["exit_code"] == 0
            ), "control: a listable directory in no project stays nobody's"
        finally:
            locked.chmod(0o700)

    def test_drone_and_own_branch_work_still_pass(self, registered_projects: dict):
        seat = registered_projects["hooks"]
        for command in ("drone @seedgo checklist apps", "mkdir -p .archive && mv old.py .archive/", "pytest tests -q"):
            assert _run(seat, command=command)["exit_code"] == 0, command


class TestAWordTheGateCannotProbe:
    """A long printf format string probed as a path must not crash the gate (ENAMETOOLONG)."""

    @pytest.mark.parametrize(
        "name",
        [
            pytest.param(
                "x" * 300 + ".txt",
                marks=pytest.mark.skipif(
                    sys.platform == "win32", reason="the probe's errno for an over-long name is measured on POSIX only"
                ),
                id="name-over-NAME_MAX",
            ),
            pytest.param("x" * 40000, id="path-over-PATH_MAX"),
        ],
    )
    def test_a_target_the_probe_cannot_read_is_refused_in_one_line(self, registered_projects: dict, name: str):
        """Mutant: the OSError swallowed into an allow (exit 0)."""
        result = _run(registered_projects["hooks"], command=f"echo hi > {name}")
        assert _blocked(result)
        reason = _reason(result)
        assert "ENAMETOOLONG" in reason and "could not check" not in reason
        assert "\n" not in reason and name not in reason

    @pytest.mark.parametrize("program", ["printf", "echo"])
    def test_a_format_string_is_data_and_its_redirect_is_the_write(
        self, registered_projects: dict, grant_withheld, program: str
    ):
        """Mutant: the format string read as a path (refused as unprobeable)."""
        seat = registered_projects["hooks"]
        fmt = "row %s: " + "x" * 480
        result = _run(seat, command=f"for b in a b c; do {program} '{fmt}' $b 1 2 > head_$b.txt; done")
        assert result["exit_code"] == 0, result["stdout"]
        other = (Path(registered_projects["memory"]) / "head.txt").as_posix()
        refused = _run(seat, command=f"{program} '{fmt}' a > {other}")
        assert _blocked(refused) and "ENAMETOOLONG" not in _reason(refused)


class TestASedPrintScriptIsARead:
    """`sed -n 68,90p .claude/provider_manifest.json` is a read, not a write."""

    def _manifest(self, registered_projects: dict) -> str:
        manifest = registered_projects["aipass"] / ".claude" / "provider_manifest.json"
        manifest.parent.mkdir()
        manifest.write_text("{}\n", encoding="utf-8")
        return manifest.as_posix()

    def test_the_refused_read_is_allowed(self, registered_projects: dict, grant_withheld):
        """Mutant: sed read off the read-only table again (refused as a project-level write)."""
        self._manifest(registered_projects)
        aipass = registered_projects["aipass"].as_posix()
        command = f"cd {aipass}; sed -n 68,90p .claude/provider_manifest.json"
        result = _run(registered_projects["hooks"], command=command)
        assert result["exit_code"] == 0, result["stdout"]

    @pytest.mark.parametrize("script", ["-n 1,5p", "-n '1,5p;$p'", "-n -e 1p -e '$p'", "-nE 3q", "'2~3d'"])
    def test_a_print_script_may_name_another_branch(self, registered_projects: dict, grant_withheld, script: str):
        target = (Path(registered_projects["memory"]) / "apps" / "x.py").as_posix()
        result = _run(registered_projects["hooks"], command=f"sed {script} {target}")
        assert result["exit_code"] == 0, result["stdout"]

    @pytest.mark.parametrize(
        "command",
        [
            "sed -n '68,90w copy.txt' {manifest}",
            "sed -n 1e {manifest}",
            "sed -n '1r /dev/null' {manifest}",
            "sed -n -f edit.sed {manifest}",
            "sed -n s/a/b/p {manifest}",
            "sed -n -l 5 1p {manifest}",
        ],
        ids=["w-command", "e-command", "r-command", "script-file", "substitute", "unread-flag"],
    )
    def test_a_script_that_can_write_or_run_still_names_its_operands(
        self, registered_projects: dict, grant_withheld, command: str
    ):
        """Mutant: every sed without -i read as a read (all six allowed)."""
        manifest = self._manifest(registered_projects)
        result = _run(registered_projects["hooks"], command=command.format(manifest=manifest))
        assert _blocked(result)
        assert "sed (not a read-only program)" in _reason(result)

    @pytest.mark.parametrize("flags", ["-i -n", "-ni", "--in-place -n", "-n -i.bak"])
    def test_sed_in_place_on_the_same_path_stays_refused(self, registered_projects: dict, grant_withheld, flags: str):
        """Both lanes hold all four: every sed read as a read still refuses here, through bash_writes."""
        manifest = self._manifest(registered_projects)
        result = _run(registered_projects["hooks"], command=f"sed {flags} 68,90p {manifest}")
        assert _blocked(result)
        assert "provider_manifest.json" in _reason(result)

    def test_a_print_read_of_a_memory_file_is_allowed_and_its_writes_are_not(self, registered_projects: dict):
        """The memory lane reads a sed print script like cat and jq; its write forms stay refused."""
        seat = Path(registered_projects["hooks"])
        (seat / ".trinity").mkdir()
        (seat / ".trinity" / "local.json").write_text("{}\n", encoding="utf-8")
        read = _run(str(seat), command="sed -n 68,90p .trinity/local.json")
        assert read["exit_code"] == 0, read["stdout"]
        for command in ("sed -i -n 68,90p .trinity/local.json", "sed -n s/a/b/p .trinity/local.json"):
            assert "Memory files are not written from a shell" in _reason(_run(str(seat), command=command)), command
