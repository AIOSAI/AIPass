# =================== AIPass ====================
# Name: test_output_capture.py
# Description: strip_ansi and the capture console, fed display.py's real rendering
# Version: 1.1.0
# Created: 2026-08-16
# Modified: 2026-09-27
# =============================================

"""Tests for tests/conftest.py strip_ansi and make_capture_console, fed apps/modules/display.py output."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — which style display.py picks per function; tests/test_display.py pins the visible text
# seedgo: no-test-needed(generated) — the exact escape bytes around display.success output; Rich emits them

import os
import subprocess
import sys
from io import StringIO

from rich.console import Console

from aipass.cli.apps.modules import display

from .conftest import make_capture_console, strip_ansi


# WHY THIS FILE EXISTS. On 2026-08-16 four tests in test_templates.py were green
# at 09:00 and red at 22:00 on byte-identical code. Only the shell had changed:
# it exported FORCE_COLOR=3, which makes Rich treat even a StringIO as a colour
# terminal, so `created: 5` rendered as `created: \x1b[1m5\x1b[0m` and the plain
# substring assert failed while a human would read the output as correct.
#
# A display test means to assert what is VISIBLE. These tests pin that the
# capture helper answers that question and no other, so the next person cannot
# quietly reintroduce a raw-bytes assert and hand the suite back to the shell.
#
# strip_ansi is fed what the product really renders — display.py's functions
# printing through a colour-forced console — not hand-written escapes, so a Rich
# upgrade that changes the bytes it emits reaches these tests.


def _render(monkeypatch, fn, *args, colour=True, no_color=False, **kwargs) -> str:
    """Run a display.py function against one console and return its raw bytes.

    colour=True forces a truecolor terminal, the FORCE_COLOR=3 shell that bit
    us; no_color=True keeps the terminal but drops colour, leaving bold/dim.
    Both product consoles are swapped, since error() writes to err_console.
    """
    buf = StringIO()
    console = Console(
        file=buf,
        force_terminal=colour,
        color_system="truecolor" if colour else None,
        no_color=no_color,
        width=200,
    )
    monkeypatch.setattr(display, "CONSOLE", console)
    monkeypatch.setattr(display, "err_console", console)
    try:
        fn(*args, **kwargs)
    finally:
        display.reset_command_state()
    return buf.getvalue()


class TestStripAnsi:
    """strip_ansi removes escape sequences and nothing else."""

    def test_removes_colour_codes(self, monkeypatch):
        """Mutant: pattern matches only [0-2;]* params, so 32 (green) survives — killed."""
        raw = _render(monkeypatch, display.success, "Branch created")

        assert "\x1b[32m" in raw, f"no colour was emitted, nothing to strip: {raw!r}"
        assert strip_ansi(raw) == "✅ Branch created\n"

    def test_removes_attribute_codes(self, monkeypatch):
        """no_color=True strips COLOUR but leaves bold/dim — the actual trap.

        Mutant: pattern matches only colour and reset (0, 3x, 9x) params — killed.
        """
        raw = _render(monkeypatch, display.section, "Summary", no_color=True)

        assert "\x1b[1m" in raw, f"no bold was emitted, nothing to strip: {raw!r}"
        assert strip_ansi(raw) == "\nSummary\n" + "─" * 50 + "\n"

    def test_removes_compound_codes(self, monkeypatch):
        """Mutant: pattern params [0-9]* without the semicolon — killed."""
        raw = _render(monkeypatch, display.error, "Branch not found")

        assert "\x1b[1;31m" in raw, f"no compound code was emitted: {raw!r}"
        assert strip_ansi(raw) == "❌ Branch not found\n"

    def test_leaves_plain_text_untouched(self, monkeypatch):
        """Mutant: collapse runs of spaces after stripping — killed."""
        raw = _render(monkeypatch, display.success, "Branch created", colour=False, items=5)

        assert raw == "✅ Branch created\n   items: 5\n"
        assert strip_ansi(raw) == raw

    def test_does_not_eat_square_brackets(self, monkeypatch):
        """Rich markup is consumed at render time; literal brackets must survive.

        Mutant: strip [tag]-shaped runs after the escapes, a naive markup strip — killed.
        """
        raw = _render(monkeypatch, display.success, display.escape("a [literal] bracket"))

        assert "\x1b[" in raw, f"no escapes were emitted around the brackets: {raw!r}"
        assert strip_ansi(raw) == "✅ a [literal] bracket\n"

    def test_preserves_box_drawing_and_unicode(self, monkeypatch):
        """Mutant: encode the result to ascii, dropping what it cannot hold — killed."""
        rule = _render(monkeypatch, display.section, "Summary")
        emoji = _render(monkeypatch, display.success, "done")

        assert "\x1b[" in rule and "\x1b[" in emoji, f"nothing to strip: {rule!r} {emoji!r}"
        assert strip_ansi(rule).endswith("─" * 50 + "\n")
        assert strip_ansi(emoji) == "✅ done\n"


class TestCaptureConsoleIsEnvironmentProof:
    """The capture console must render identically under any colour env."""

    def test_output_has_no_escapes_in_this_shell(self):
        console, get_output = make_capture_console()
        console.print("[bold]Summary:[/bold]")
        console.print("  created: 5")
        assert "\x1b" not in get_output()

    def test_rendering_is_identical_across_hostile_environments(self):
        """The regression itself: same code, four shells, one answer.

        Spawns real subprocesses because Rich resolves the colour system once,
        from the environment, at Console construction — an in-process
        monkeypatch of os.environ would not reproduce what bit us.
        """
        script = (
            "from tests.conftest import make_capture_console\n"
            "console, get_output = make_capture_console(highlight=False)\n"
            "console.print('[bold]Summary:[/bold]')\n"
            "console.print('  created: 5')\n"
            "console.print('  [dim]Completed in 2.5s[/dim]')\n"
            "print(repr(get_output()))\n"
        )
        environments = [
            {"FORCE_COLOR": "3"},
            {"TERM": "dumb"},
            {"NO_COLOR": "1"},
            {"TERM": "xterm-256color"},
        ]
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        renders = []
        for overrides in environments:
            env = {key: value for key, value in os.environ.items() if key not in ("FORCE_COLOR", "NO_COLOR", "TERM")}
            env.update(overrides)
            result = subprocess.run(
                [sys.executable, "-B", "-c", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
                cwd=repo_root,
            )
            assert result.returncode == 0, result.stderr
            renders.append(result.stdout.strip())

        assert len(set(renders)) == 1, f"env changed the output: {set(renders)}"
        assert "created: 5" in renders[0]
        assert "Completed in 2.5s" in renders[0]
        assert "\\x1b" not in renders[0]
