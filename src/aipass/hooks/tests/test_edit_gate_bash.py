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


def _names(targets, *parts: str) -> bool:
    """True when some target ends in these components, in any OS's spelling.

    THE CONTRACT, ruled 2026-08-31: the target list stays OS-NATIVE. These are
    the Path objects edit_gate hands to _find_project_root, which globs the real
    filesystem for *_REGISTRY.json — a list canonicalised to POSIX spelling
    would be unwalkable on Windows, so the fence would go dark in exactly the
    place this whole train was fixing. 1.2.0 normalises separators on the way
    IN, before pathlib parses a token; it deliberately does not normalise on the
    way out.

    So a test may not assert on str(target). @devpulse's windows-setup run
    caught two that did — they expected "/other/Project/x.json" and got
    "\\other\\Project\\x.json". That spelling is pathlib's own __str__ on
    Windows, not anything 1.2.0 did: a rooted-but-driveless path is not
    absolute there, and joining it onto the cwd REPLACES the cwd, so the same
    two pins were red on Windows before 1.2.0 for the same reason.

    Comparing components says what the test actually means — this command
    surrendered that path — in a spelling neither OS owns.
    """
    return any(tuple(t.parts[-len(parts) :]) == parts for t, _ in targets)


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
        targets = write_targets(command, "/tmp")
        assert _names(targets, "other", "Project", "x.json"), f"heredoc body surrendered nothing: {targets}"

    def test_a_real_redirection_on_the_heredoc_opening_line_still_counts(self):
        """Only the BODY stops being syntax — the opening line is still shell."""
        from aipass.hooks.apps.modules.bash_writes import write_targets

        command = "cat <<'EOF' > /other/Project/out.txt\njust some text\nEOF"
        targets = write_targets(command, "/tmp")
        assert _names(targets, "other", "Project", "out.txt"), f"opening-line redirection lost: {targets}"

    def test_the_residual_gap_is_published_not_implied(self):
        """What the parser cannot see is data, so the reply, README and tests agree."""
        from aipass.hooks.apps.modules.bash_writes import NOT_CAUGHT

        assert NOT_CAUGHT
        joined = " ".join(NOT_CAUGHT)
        for named in ("symlink", "xargs", "chmod", "git"):
            assert named in joined


def _win(path) -> str:
    """Spell a path the way Windows spells it, on whatever OS is reading.

    This is the whole trick that makes the class below runnable anywhere. On
    Windows ``str(tmp_path)`` is already backslashed and this is a no-op. On
    Linux it turns a real absolute POSIX path into ``\\tmp\\...\\f.json`` — the
    exact spelling that killed the parser — and the gate must still resolve it
    back to the same real file under the same real fence. The claim under test
    is "separators are understood", and that claim is OS-independent even
    though drive letters are not.
    """
    return str(path).replace("/", "\\")


class TestWindowsSpelledPathsAreStillFenced:
    """Backslash separators must not walk a foreign write past the fence.

    THE DEFECT (@devpulse, windows-test.yml, 2026-08-31): every test in
    TestScriptedLaneCatches failed on Windows CI, all in the ALLOW direction —
    exit 0 on `sed -i` into a sibling project. Their reading was "path
    extraction or the fence comparison never matches that spelling". The
    measurement puts it one layer earlier than either: shlex runs in POSIX
    mode, where a backslash is an ESCAPE, so it ate every separator and
    `C:\\Users\\me\\Vera-Studio\\f.json` arrived as the single token
    `C:UsersmeVera-Studiof.json`. A drive-absolute foreign path became one
    relative filename, resolved under the caller's OWN project, and read as a
    local write. The extraction and the comparison were both working
    correctly on a path that had already been destroyed.

    Reproduced on Linux before the fix, no Windows box involved — which is the
    point: the parser never needed a Windows runner to be wrong, it needed a
    backslash. The class had never been green on Windows since the day it
    shipped, and NOT_CAUGHT did not name it. A category believed caught and
    silently uncaught on one OS is worse than a named blind spot.
    """

    def _cmd(self, sibling_projects: dict, command: str) -> dict:
        return _run(sibling_projects["plain_seat"], command=command)

    def test_sed_in_place_with_backslash_separators(self, sibling_projects, grant_withheld):
        """The exact shape of devpulse's log line: exit 0 where 2 belonged."""
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
        """The regex knew only "/" — so on a Windows path it matched NOTHING.

        Not a degraded reading: the interpreter mode, the broadest catch this
        parser has, returned an empty list for every Windows-spelled command.
        """
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

        Mutation found this one: with the backslash clause removed from
        _looks_like_path every other Windows case still passed, because a
        filename carries a dot and the dot clause caught it by luck of
        spelling. A directory target has no dot, so the separator is the only
        evidence that the token is a path at all.
        """
        target = _win(Path(sibling_projects["vera"]) / "newdir")
        assert "." not in target, f"precondition lost — this path has a dot to fall back on: {target}"

        assert _blocked(self._cmd(sibling_projects, f"mkdir {target}")), "backslash mkdir allowed"

    def test_local_write_stays_allowed_in_both_spellings(self, sibling_projects, grant_withheld):
        """The fix must not convict the seat's own project of being foreign.

        Reading a backslash as a separator only ever ADDS path components, so
        it cannot move a write upward out of its own project — this pins that
        reasoning rather than trusting it.
        """
        own = _win(Path(sibling_projects["plain_seat"]) / "mine.txt")

        result = self._cmd(sibling_projects, f"echo x > {own}")

        assert result["exit_code"] == 0, f"a write into the seat's own project was refused: {result}"


class TestBothSpellingsAreRead:
    """Parser level: neither dialect may be chosen at the other's expense."""

    def test_posix_escaped_space_survives(self):
        """shlex's escape reading is still produced — it is correct for POSIX.

        `cp a\\ b.txt dest` names ONE source file with a space in it. If the
        separator reading had replaced the escape reading rather than joining
        it, this filename would have become two tokens on every OS.
        """
        from aipass.hooks.apps.modules import bash_writes

        readings = bash_writes._readings(r"cp a\ b.txt /tmp/dest.txt")

        assert ["cp", "a b.txt", "/tmp/dest.txt"] in readings, f"escape reading lost: {readings}"

    def test_separator_reading_is_produced_too(self):
        """The reading that was missing entirely until 2026-08-31."""
        from aipass.hooks.apps.modules import bash_writes

        readings = bash_writes._readings(r"sed -i s/a/b/ C:\Proj\Vera\f.json")

        assert any(r"C:\Proj\Vera\f.json" in tokens for tokens in readings), (
            f"no reading kept the separators: {readings}"
        )

    def test_a_command_with_no_backslash_is_read_once(self):
        """No cost where the dialects agree — and no duplicate refusal lines."""
        from aipass.hooks.apps.modules import bash_writes

        assert len(bash_writes._readings("echo hi > out.txt")) == 1

    def test_a_target_named_twice_is_reported_once(self):
        """Both readings can find the SAME write; the caller is told once.

        The first cut of this test used a Windows-spelled target, where the two
        readings produce two DIFFERENT paths and there is nothing to dedupe —
        it passed with the dedupe removed. Mutation caught it. The command here
        carries a backslash (so both readings run) on something that is not the
        target, so both readings agree on `out.txt` and the duplicate is real.
        """
        from aipass.hooks.apps.modules import bash_writes

        command = r'python3 -c "print(\"hi\")" > out.txt'
        assert len(bash_writes._readings(command)) == 2, "precondition: both readings must run"

        hits = bash_writes.write_targets(command, str(Path.cwd()))

        assert len(hits) == len(set(hits)), f"the same write was reported twice: {hits}"

    def test_separators_alone_are_not_a_path(self):
        """Widening the run to accept "\\" made every escaped quote match.

        Harmless to the verdict — filesystem root holds no registry — but a
        refusal listing paths the command never named is one nobody believes.
        """
        from aipass.hooks.apps.modules import bash_writes

        hits = bash_writes.write_targets(r'python3 -c "print(\"hi\")"', str(Path.cwd()))

        assert all(any(c.isalnum() for c in t.name) for t, _ in hits), f"separator-only target: {hits}"

    def test_the_cross_os_root_limit_is_published(self):
        """A drive letter names nothing on Linux — said as data, not discovered."""
        from aipass.hooks.apps.modules import bash_writes

        assert any("operating system" in gap for gap in bash_writes.NOT_CAUGHT), (
            "the cross-OS root residual is not in NOT_CAUGHT"
        )


class TestTargetSpellingIsNotPartOfTheContract:
    """The two pins @devpulse's windows-setup run left red, pinned in-process.

    Both asserted on str(target) and expected the POSIX spelling. Neither could
    ever pass on Windows, and neither failure was about the parser — the target
    was correct, the test was reading it through __str__.
    """

    def test_names_accepts_the_windows_rendering(self):
        """The exact spelling from the CI log, compared on any OS.

        This is the half that matters: the tests above are green here either
        way, so without this one I would be shipping a fix to a Windows failure
        with no evidence it addresses the Windows failure.
        """
        from pathlib import PureWindowsPath

        as_windows = [(PureWindowsPath(r"\other\Project\x.json"), "python3 (interpreter)")]

        assert _names(as_windows, "other", "Project", "x.json")

    def test_names_does_not_match_a_shorter_tail(self):
        """A comparison loose enough to pass anywhere proves nothing."""
        from pathlib import PurePosixPath

        targets = [(PurePosixPath("/somewhere/else/x.json"), "why")]

        assert not _names(targets, "other", "Project", "x.json")

    def test_the_target_list_stays_os_native(self):
        """The ruling, pinned: normalise on the way IN, never on the way out.

        edit_gate hands these straight to _find_project_root, which globs the
        real filesystem for *_REGISTRY.json. A list canonicalised to one
        spelling would be unwalkable on the other OS — the fence would go dark
        in precisely the place this train was fixing.
        """
        from pathlib import Path as LocalPath

        from aipass.hooks.apps.modules.bash_writes import write_targets

        targets = write_targets("echo x > sub/out.txt", str(LocalPath.cwd()))

        assert targets, "precondition: the command must name a target"
        assert all(isinstance(t, LocalPath) for t, _ in targets), (
            f"targets are not the local Path flavour the fence must walk: {targets}"
        )
