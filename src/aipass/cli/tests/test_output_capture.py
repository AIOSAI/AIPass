"""Tests for the test suite's own output capture — the layer that made it lie.

WHY THIS FILE EXISTS. On 2026-08-16 four tests in test_templates.py were green
at 09:00 and red at 22:00 on byte-identical code. Only the shell had changed:
it exported FORCE_COLOR=3, which makes Rich treat even a StringIO as a colour
terminal, so `created: 5` rendered as `created: \\x1b[1m5\\x1b[0m` and the plain
substring assert failed while a human would read the output as correct.

A display test means to assert what is VISIBLE. These tests pin that the
capture helper answers that question and no other, so the next person cannot
quietly reintroduce a raw-bytes assert and hand the suite back to the shell.
"""

import os
import subprocess
import sys

from .conftest import make_capture_console, strip_ansi


class TestStripAnsi:
    """strip_ansi removes escape sequences and nothing else."""

    def test_removes_colour_codes(self):
        assert strip_ansi("\x1b[31mred\x1b[0m") == "red"

    def test_removes_attribute_codes(self):
        """no_color=True strips COLOUR but leaves bold/dim — the actual trap."""
        assert strip_ansi("created: \x1b[1m5\x1b[0m") == "created: 5"

    def test_removes_compound_codes(self):
        assert strip_ansi("\x1b[1;2m2.\x1b[0m\x1b[2m5s\x1b[0m") == "2.5s"

    def test_leaves_plain_text_untouched(self):
        plain = "  operation_start()      Standard operation header"
        assert strip_ansi(plain) == plain

    def test_does_not_eat_square_brackets(self):
        """Rich markup is consumed at render time; literal brackets must survive."""
        assert strip_ansi("a [literal] bracket") == "a [literal] bracket"

    def test_preserves_box_drawing_and_unicode(self):
        assert strip_ansi("─" * 4 + " ⚙️ ") == "─" * 4 + " ⚙️ "


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
                env=env,
                cwd=repo_root,
            )
            assert result.returncode == 0, result.stderr
            renders.append(result.stdout.strip())

        assert len(set(renders)) == 1, f"env changed the output: {set(renders)}"
        assert "created: 5" in renders[0]
        assert "Completed in 2.5s" in renders[0]
        assert "\\x1b" not in renders[0]
