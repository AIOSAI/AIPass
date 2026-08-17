# =================== AIPass ====================
# Name: test_activity_report.py
# Description: Tests for the activity_report CLI module
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

"""Tests for the activity_report CLI module (apps/modules/activity_report.py)."""

import re
from unittest.mock import patch

MODULE = "aipass.daemon.apps.modules.activity_report"


# =============================================
# handle_command -- routing basics
# =============================================


@patch(f"{MODULE}.json_handler")
@patch(f"{MODULE}.console")
@patch(f"{MODULE}.error")
@patch(f"{MODULE}.logger")
class TestHandleCommandRouting:
    """Tests for handle_command routing and unknown commands."""

    def test_unknown_command_returns_false(self, _log, _err, _con, _jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        assert handle_command("not_a_real_command", []) is False

    def test_activity_no_args_calls_generate(self, _log, _err, mock_con, mock_jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.generate_activity_report", return_value="report") as mock_gen:
            result = handle_command("activity", [])

        assert result is True
        mock_gen.assert_called_once_with(since_hours=24.0, verbosity="normal")
        mock_con.print.assert_called_with("report")

    def test_activity_help_shows_help(self, _log, _err, mock_con, _jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.generate_activity_report") as mock_gen:
            result = handle_command("activity", ["--help"])

        assert result is True
        mock_gen.assert_not_called()
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert any("ACTIVITY" in c for c in calls)

    def test_activity_hours_48(self, _log, _err, _con, mock_jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.generate_activity_report", return_value="report") as mock_gen:
            result = handle_command("activity", ["--hours", "48"])

        assert result is True
        mock_gen.assert_called_once_with(since_hours=48.0, verbosity="normal")


# =============================================
# handle_command -- activity-report
# =============================================


@patch(f"{MODULE}.json_handler")
@patch(f"{MODULE}.console")
@patch(f"{MODULE}.error")
@patch(f"{MODULE}.logger")
class TestActivityReportCommand:
    """Tests for 'activity-report' command."""

    def test_activity_report_no_args(self, _log, _err, _con, _jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.generate_activity_report", return_value="detailed") as mock_gen:
            result = handle_command("activity-report", [])

        assert result is True
        mock_gen.assert_called_once_with(since_hours=24.0, verbosity="detailed")

    def test_activity_report_help(self, _log, _err, mock_con, _jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.generate_activity_report") as mock_gen:
            result = handle_command("activity-report", ["--help"])

        assert result is True
        mock_gen.assert_not_called()
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert any("ACTIVITY-REPORT" in c for c in calls)

    def test_activity_report_json(self, _log, _err, mock_con, _jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.get_json_report", return_value={"branches": []}) as mock_json:
            result = handle_command("activity-report", ["--json"])

        assert result is True
        mock_json.assert_called_once_with(24.0)

    def test_activity_report_json_short_flag(self, _log, _err, mock_con, _jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.get_json_report", return_value={}) as mock_json:
            result = handle_command("activity-report", ["-j"])

        assert result is True
        mock_json.assert_called_once()


# =============================================
# handle_command -- activity_report alias
# =============================================


@patch(f"{MODULE}.json_handler")
@patch(f"{MODULE}.console")
@patch(f"{MODULE}.error")
@patch(f"{MODULE}.logger")
class TestActivityReportAlias:
    """Tests for 'activity_report' underscore alias."""

    def test_activity_report_alias_works(self, _log, _err, _con, mock_jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.generate_activity_report", return_value="r") as mock_gen:
            result = handle_command("activity_report", [])

        assert result is True
        mock_gen.assert_called_once()

    def test_activity_report_alias_help(self, _log, _err, mock_con, _jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        result = handle_command("activity_report", ["--help"])
        assert result is True
        # Shows introspection (module info)
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert any("activity_report Module" in c for c in calls)


# =============================================
# handle_command -- branch-health
# =============================================


@patch(f"{MODULE}.json_handler")
@patch(f"{MODULE}.console")
@patch(f"{MODULE}.error")
@patch(f"{MODULE}.logger")
class TestBranchHealthCommand:
    """Tests for 'branch-health' command."""

    def test_branch_health_no_args(self, _log, _err, _con, mock_jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.generate_activity_report", return_value="all") as mock_gen:
            result = handle_command("branch-health", [])

        assert result is True
        mock_gen.assert_called_once_with(since_hours=24, verbosity="normal")

    def test_branch_health_help(self, _log, _err, mock_con, _jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        result = handle_command("branch-health", ["--help"])
        assert result is True
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert any("BRANCH-HEALTH" in c for c in calls)

    def test_branch_health_with_branch(self, _log, _err, mock_con, _jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.generate_branch_report", return_value="DRONE report") as mock_br:
            result = handle_command("branch-health", ["DRONE"])

        assert result is True
        mock_br.assert_called_once_with("DRONE", since_hours=24.0)

    def test_branch_health_with_branch_and_hours(self, _log, _err, mock_con, _jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.generate_branch_report", return_value="report") as mock_br:
            result = handle_command("branch-health", ["DRONE", "--hours", "48"])

        assert result is True
        mock_br.assert_called_once_with("DRONE", since_hours=48.0)

    def test_branch_health_only_flags_shows_error(self, _log, mock_err, mock_con, _jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        result = handle_command("branch-health", ["--hours", "48"])
        assert result is True
        mock_err.assert_called()


# =============================================
# _parse_hours_arg
# =============================================


@patch(f"{MODULE}.logger")
class TestParseHoursArg:
    """Tests for _parse_hours_arg helper."""

    def test_hours_flag(self, _log):
        from aipass.daemon.apps.modules.activity_report import _parse_hours_arg

        assert _parse_hours_arg(["--hours", "48"]) == 48.0

    def test_short_flag(self, _log):
        from aipass.daemon.apps.modules.activity_report import _parse_hours_arg

        assert _parse_hours_arg(["-t", "12"]) == 12.0

    def test_no_flag_returns_default(self, _log):
        from aipass.daemon.apps.modules.activity_report import _parse_hours_arg

        assert _parse_hours_arg([]) == 24.0

    def test_invalid_value_returns_default(self, mock_log):
        from aipass.daemon.apps.modules.activity_report import _parse_hours_arg

        result = _parse_hours_arg(["--hours", "abc"])
        assert result == 24.0
        mock_log.warning.assert_called()


# =============================================
# _extract_branch_name
# =============================================


class TestExtractBranchName:
    """Tests for _extract_branch_name helper."""

    def test_branch_with_flags(self):
        from aipass.daemon.apps.modules.activity_report import _extract_branch_name

        assert _extract_branch_name(["DRONE", "--hours", "48"]) == "DRONE"

    def test_only_flags_returns_none(self):
        from aipass.daemon.apps.modules.activity_report import _extract_branch_name

        assert _extract_branch_name(["--hours", "48"]) is None


# =============================================
# _render_entry_health -- @memory's wrapped health API
# =============================================

HEALTH_TARGET = "aipass.memory.apps.modules.health.get_branch_health"

# SGR escape sequences (colour AND attributes such as bold). Rich's
# ReprHighlighter injects these around brackets and numbers whenever it
# believes it is writing to a terminal.
ANSI_SGR = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Drop escape codes so assertions read the visible characters only."""
    return ANSI_SGR.sub("", text)


def _clean_payload(**overrides):
    """Build a get_branch_health payload: healthy unless overridden."""
    payload = {
        "success": True,
        "branch": "DAEMON",
        "entry_count": {
            "local": {"should_rollover": False, "current_lines": 221, "reason": ""},
            "observations": {"should_rollover": False, "current_lines": 145, "reason": ""},
        },
        "entry_size": {"violations": [], "total_violations": 0},
    }
    payload.update(overrides)
    return payload


def _render(branch="DAEMON"):
    """Resolve the renderer by name so this file imports before the fix lands."""
    from aipass.daemon.apps.modules import activity_report

    fn = getattr(activity_report, "_render_entry_health")
    return fn(branch)


class TestRenderEntryHealthSeverity:
    """The severity mapping @memory pinned in words — rollover is never a fault."""

    def test_rollover_pending_is_informational_never_warning(self):
        payload = _clean_payload(
            entry_count={
                "local": {"should_rollover": True, "current_lines": 240, "reason": "over 220-line trigger"},
                "observations": {"should_rollover": False, "current_lines": 145, "reason": ""},
            }
        )
        with patch(HEALTH_TARGET, return_value=payload):
            out = _render()

        assert "pending" in out.lower()
        assert "WARNING" not in out

    def test_cap_violation_is_warning_and_names_the_entry(self):
        payload = _clean_payload(
            entry_size={
                "violations": [
                    {
                        "branch": "DAEMON",
                        "file": "local.json",
                        "container": "key_learnings",
                        "key": "pair_behaviour_guards",
                        "length": 212,
                        "cap": 200,
                        "over_by": 12,
                        "entry_type": "value",
                    }
                ],
                "total_violations": 1,
            }
        )
        with patch(HEALTH_TARGET, return_value=payload):
            out = _render()

        assert "WARNING" in out
        assert "key_learnings" in out
        assert "212" in out and "200" in out

    def test_clean_branch_has_no_warning(self):
        with patch(HEALTH_TARGET, return_value=_clean_payload()):
            out = _render()

        assert "WARNING" not in out
        assert "221" in out


class TestRenderEntryHealthDegradation:
    """Failure modes surface in the output — never a crash, never a silent blank."""

    def test_unknown_branch_surfaces_the_error(self):
        payload = {"success": False, "error": "Unknown branch: NOPE"}
        with patch(HEALTH_TARGET, return_value=payload):
            out = _render("NOPE")

        assert "Unknown branch: NOPE" in out

    def test_missing_memory_file_is_skipped_not_crashed(self):
        payload = _clean_payload(
            entry_count={
                "local": {"should_rollover": False, "current_lines": 221, "reason": ""},
                "observations": None,
            }
        )
        with patch(HEALTH_TARGET, return_value=payload):
            out = _render()

        assert "observations" in out
        assert "221" in out

    def test_memory_branch_unavailable_is_visible(self):
        import sys

        with patch.dict(sys.modules, {"aipass.memory.apps.modules.health": None}):
            out = _render()

        assert "unavailable" in out.lower()


@patch(f"{MODULE}.json_handler")
@patch(f"{MODULE}.console")
@patch(f"{MODULE}.error")
@patch(f"{MODULE}.logger")
class TestBranchHealthWiring:
    """branch-health must actually call @memory's API — the todo's whole point."""

    def test_branch_health_prints_entry_health(self, _log, _err, mock_con, _jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.generate_branch_report", return_value="base report"):
            with patch(f"{MODULE}._render_entry_health", return_value="ENTRY HEALTH BLOCK") as mock_render:
                result = handle_command("branch-health", ["DAEMON"])

        assert result is True
        mock_render.assert_called_once_with("DAEMON")
        printed = [str(c) for c in mock_con.print.call_args_list]
        assert any("ENTRY HEALTH BLOCK" in c for c in printed)

    def test_base_branch_report_still_printed(self, _log, _err, mock_con, _jh):
        """Behaviour preservation: the existing report is not displaced by the new block."""
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.generate_branch_report", return_value="base report") as mock_gen:
            with patch(f"{MODULE}._render_entry_health", return_value="block"):
                handle_command("branch-health", ["DAEMON", "--hours", "48"])

        mock_gen.assert_called_once_with("DAEMON", since_hours=48.0)
        printed = [str(c) for c in mock_con.print.call_args_list]
        assert any("base report" in c for c in printed)

    def test_no_args_summary_does_not_call_memory(self, _log, _err, _con, _jh):
        """Bare branch-health is the all-branches summary — no per-branch API call."""
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.generate_activity_report", return_value="summary"):
            with patch(f"{MODULE}._render_entry_health") as mock_render:
                handle_command("branch-health", [])

        mock_render.assert_not_called()


class TestMarkersSurviveRichMarkup:
    """The live-output gap: console.print() eats lowercase bracket tags as styles.

    Asserting on the returned string cannot see this — the marker is present in
    the string and absent on screen. These render through Rich the way the CLI
    does, so a lowercase marker regression fails here instead of silently
    blanking the report.
    """

    def _rendered(self, payload, force_terminal=True):
        """Render through Rich the way the shared cli console does, ANSI stripped.

        force_terminal=True pins the HOSTILE case deliberately. Rich decides
        whether to emit escape codes from is_terminal, and FORCE_COLOR in the
        environment makes even a StringIO count as a terminal — so ReprHighlighter
        wraps every bracket and every number in bold. Left to the environment this
        test passes or fails depending on which shell ran it: it was green in the
        morning and red the same evening on byte-identical code.

        no_color is deliberately NOT used here. It strips colour and leaves
        attributes, so bold survives it and a plain substring assert still fails.
        Stripping the escape codes outright is what answers the question this test
        actually asks: is the marker TEXT on screen. A marker eaten by markup
        parsing is absent from the stripped text too, so the guard still bites.

        color_system is pinned too: force_terminal alone is not enough, because
        TERM=dumb makes Rich resolve no colour system and emit plain text anyway.
        Naming it keeps the hostile case hostile in every shell.
        """
        import io

        from rich.console import Console

        buf = io.StringIO()
        console = Console(file=buf, width=120, force_terminal=force_terminal, color_system="truecolor")
        with patch(HEALTH_TARGET, return_value=payload):
            console.print(_render())
        return _strip_ansi(buf.getvalue())

    def test_pending_marker_survives(self):
        payload = _clean_payload(
            entry_count={
                "local": {"should_rollover": True, "current_lines": 240, "reason": "15/15 key_learnings"},
                "observations": None,
            }
        )
        out = self._rendered(payload)

        assert "[PENDING]" in out
        assert "[SKIP]" in out
        assert "15/15 key_learnings" in out

    def test_ok_marker_survives(self):
        out = self._rendered(_clean_payload())

        assert "[OK]" in out

    def test_warning_marker_survives(self):
        payload = _clean_payload(
            entry_size={
                "violations": [
                    {
                        "branch": "DAEMON",
                        "file": "local.json",
                        "container": "key_learnings",
                        "key": "k",
                        "length": 212,
                        "cap": 200,
                        "over_by": 12,
                        "entry_type": "value",
                    }
                ],
                "total_violations": 1,
            }
        )
        out = self._rendered(payload)

        assert "[!]" in out
        assert "WARNING" in out

    def test_markers_survive_piped_output(self):
        """The non-terminal path — pipes and files get no escape codes at all."""
        out = self._rendered(_clean_payload(), force_terminal=False)

        assert "[OK]" in out
        assert "221" in out

    def test_highlighted_path_is_genuinely_exercised(self):
        """Proof the hostile case is real, not a test that passes trivially.

        If Rich ever stopped emitting attributes for a forced terminal, every
        assertion above would still pass while no longer testing anything. This
        fails instead, so the guard cannot quietly go inert.

        Both settings are named explicitly. Relying on the ambient shell is what
        caused the original defect — and cost a second one: an earlier draft of
        this very test passed under FORCE_COLOR and failed under TERM=dumb.
        """
        import io

        from rich.console import Console

        buf = io.StringIO()
        console = Console(file=buf, width=120, force_terminal=True, color_system="truecolor")
        with patch(HEALTH_TARGET, return_value=_clean_payload()):
            console.print(_render())
        raw = buf.getvalue()

        assert "\x1b[" in raw, "expected Rich to emit escape codes for a forced terminal"
        assert "[OK]" not in raw, "expected the highlighter to break up the marker in raw output"
        assert "[OK]" in _strip_ansi(raw)


class TestSharedConsoleContract:
    """Pin the cli console behaviour the uppercase-marker convention rests on.

    The convention exists because the shared console parses markup, which eats a
    lowercase bracket tag as a style name. This asserts that hazard behaviourally
    against the REAL console rather than trusting a private attribute, so a cli
    change that removes or reverses it surfaces here instead of silently blanking
    daemon's report.
    """

    def test_shared_console_still_eats_lowercase_tags(self):
        from aipass.cli.apps.modules import console

        with console.capture() as captured:
            console.print("[ok] alpha [OK] beta")
        out = _strip_ansi(captured.get())

        assert "[ok]" not in out, "cli console stopped parsing markup — revisit the marker convention"
        assert "[OK]" in out
        assert "alpha" in out and "beta" in out
