# =================== META ====================
# Name: test_mock_console_check.py
# Description: mock_console_check — test template v1 item 14, the product's console is the real one
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""Tests for apps/handlers/aipass_standards/mock_console_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — that ast.parse builds the tree it documents
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — applies_to_file's production/tests split; tests/test_applicability.py
# seedgo: no-test-needed(constant) — the prose of FIX; the shapes and line numbers are asserted

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import mock_console_check, skip_dirs
from aipass.seedgo.apps.modules import checklist

#: The fleet's gold test file for this item, resolved from this file's own
#: location so the test reads the real thing on any host.
MODEL = Path(__file__).resolve().parent / "test_readme_update.py"


def _write(tmp_path, body, name="test_thing.py"):
    """A test file on disk under a tests/ directory, which is what the rule scopes to."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    path = tests_dir / name
    path.write_text(body, encoding="utf-8")
    return path


def _found(source):
    """Just what each hit names, in line order."""
    return [what for _line, what, _fix in mock_console_check.scan(source)]


def _lines(source):
    """Just the line each hit sits on, in order."""
    return [line for line, _what, _fix in mock_console_check.scan(source)]


class TestTheFourInstallSites:
    """432 fleet hits arrive through four spellings, and the message is the same finding."""

    def test_a_patch_with_no_replacement_is_the_biggest_habit(self):
        """284 of the 432 sites. mock hands the product a MagicMock by default."""
        source = '@patch("aipass.spawn.apps.spawn.console")\ndef test_x(mock_console):\n    pass\n'

        assert _found(source) == [
            "a patch with no replacement (the default MagicMock) installed over the product's console"
        ]

    def test_an_f_string_target_is_read_from_its_last_literal_part(self):
        """@ai_mail spells the module as f"{MOD}.console" in 44 places."""
        source = '@patch(f"{MOD}.console")\ndef test_x(mock_console):\n    pass\n'

        assert len(_found(source)) == 1

    def test_patch_object_names_the_attribute_as_its_second_argument(self):
        source = 'cons = Console(file=buf)\nwith patch.object(display, "CONSOLE", cons):\n    pass\n'

        assert _lines(source) == [2]

    def test_the_three_argument_setattr_is_a_hit(self):
        assert _found('monkeypatch.setattr(mod, "console", MagicMock())\n') == [
            "a Mock installed over the product's console"
        ]

    def test_the_two_argument_setattr_is_a_hit(self):
        """monkeypatch's own form: the dotted target is the first argument."""
        assert len(_found('monkeypatch.setattr("aipass.x.mod.console", Mock())\n')) == 1

    def test_an_attribute_assignment_is_a_hit(self):
        assert _found("cli_mod.console = MagicMock()\n") == ["a Mock installed over the product's console"]

    def test_a_console_keyword_argument_is_handed_not_installed(self):
        """The message says so: the product never looked, it was given one."""
        assert _found("render_report(console=MagicMock())\n") == ["a Mock handed to the product as its console"]

    def test_the_line_number_is_the_install(self):
        source = 'import os\n\nmonkeypatch.setattr(\n    mod,\n    "console",\n    Mock(),\n)\n'

        assert _lines(source) == [3]

    def test_one_install_reported_once(self):
        """Two walks over one node would print the same row twice."""
        assert len(_found('patch.object(mod, "console", Mock())\n')) == 1


class TestWhatIsInstalled:
    """Three kinds of stand-in, each named in the message so the author knows which."""

    @pytest.mark.parametrize("factory", ["Mock", "MagicMock", "AsyncMock", "PropertyMock", "create_autospec"])
    def test_every_mock_factory_is_a_mock(self, factory):
        assert _found(f'setattr(mod, "console", {factory}())\n') == ["a Mock installed over the product's console"]

    def test_a_rich_console_on_a_buffer_is_named_as_one(self):
        """It renders for real, which is why it looks innocent."""
        assert _found('patch.object(mod, "CONSOLE", Console(file=buf))\n') == [
            "a Rich Console on a buffer installed over the product's console"
        ]

    def test_a_recording_console_is_named_as_one(self):
        assert _found('setattr(mod, "console", Console(record=True))\n') == [
            "a recording Rich Console installed over the product's console"
        ]

    def test_a_fake_class_with_a_print_method_is_the_third_shape(self):
        """seedgo's own _Recorder. The install site is what makes it unambiguous."""
        source = (
            "class _Recorder:\n"
            "    def print(self, text=''):\n"
            "        pass\n"
            "\n"
            'monkeypatch.setattr(module, "console", _Recorder(printed))\n'
        )

        assert _found(source) == ["a fake console class installed over the product's console"]

    def test_a_patch_given_a_real_replacement_is_judged_on_that_replacement(self):
        """new= is what arrives, so new= is what the rule reads."""
        assert _found('patch("aipass.x.console", new=build_real())\n') == []


class TestTheTargetMayBeAnyRouteToTheConsole:
    """All three end with the product holding a Mock, so all three are one finding."""

    def test_a_product_function_that_returns_a_console_is_a_hit(self):
        """@drone patches git_module._get_console; the product then gets a Mock."""
        assert len(_found('patch(f"{_M}.git_module._get_console")\n')) == 1

    def test_richs_own_class_is_a_hit(self):
        """@prax patches rich.console.Console, so every console the product builds is a Mock."""
        assert len(_found('with patch("rich.console.Console") as mock_rich:\n    pass\n')) == 1

    def test_an_err_console_is_a_console(self):
        assert len(_found('patch("aipass.cli.apps.modules.display.err_console")\n')) == 1


class TestANameIsResolvedOneHop:
    """@prax binds the console, @devpulse returns it from a helper. Both install a name."""

    def test_a_name_bound_to_a_stand_in_is_judged_where_it_is_installed(self):
        source = 'real_console = Console(file=buffer)\nsetattr(module, "console", real_console)\n'

        assert mock_console_check.scan(source) == [
            (2, "a Rich Console on a buffer installed over the product's console", mock_console_check.FIX)
        ]

    def test_the_binding_line_alone_is_not_a_hit(self):
        """Building one touches nothing. It is the install that hands it to the product."""
        assert _found("real_console = Console(file=buffer)\n") == []

    def test_a_same_file_helper_that_returns_one_is_followed(self):
        """@devpulse's _real_console() returns (console, buffer) and eight tests install it."""
        source = (
            "def _real_console():\n"
            "    buffer = io.StringIO()\n"
            "    return Console(file=buffer, width=200), buffer\n"
            "\n"
            "def test_x():\n"
            "    console, buffer = _real_console()\n"
            '    setattr(module, "console", console)\n'
        )

        assert _found(source) == ["a Rich Console on a buffer installed over the product's console"]

    def test_a_name_reassigned_to_anything_else_is_dropped(self):
        """Which value reaches the install is a question one pass cannot answer."""
        source = 'c = MagicMock()\nc = build_real()\nsetattr(mod, "console", c)\n'

        assert _found(source) == []


class TestWhatIsNeverConvicted:
    """Each carve-out carries its fleet count; none of them is a guess."""

    def test_capsys_is_the_fix_not_the_offence(self):
        """79 of the 580 fleet test files already read the channel."""
        source = 'def test_x(capsys):\n    run()\n    assert "ok" in capsys.readouterr().out\n'

        assert _found(source) == []

    def test_putting_the_real_console_back_is_not_a_hit(self):
        """setattr(module, "console", original) is the opposite of the habit. 5 fleet sites."""
        source = (
            'original = getattr(module, "console")\n'
            'setattr(module, "console", Console(file=buf))\n'
            "try:\n"
            "    call(module)\n"
            "finally:\n"
            '    setattr(module, "console", original)\n'
        )

        assert _lines(source) == [2]

    def test_a_mock_for_something_that_is_not_a_console_is_not_a_hit(self):
        assert _found('patch("aipass.x.wake_branch")\nsetattr(mod, "logger", MagicMock())\n') == []

    def test_a_helper_whose_name_merely_ends_in_the_word_is_not_a_console(self):
        """@prax mocks _print_event_to_console. Console-named means ONE qualifier at most."""
        assert _found('patch.object(mod, "_print_event_to_console", side_effect=ValueError("x"))\n') == []

    def test_a_console_the_test_prints_to_itself_is_not_convicted(self):
        """The subject is what RICH does to a string. No product console is in the picture."""
        source = (
            "buffer = io.StringIO()\n"
            "console = Console(file=buffer, width=200)\n"
            'console.print("cmd [args...] here", markup=False)\n'
            'assert "args" in buffer.getvalue()\n'
        )

        assert _found(source) == []

    def test_a_syntax_error_yields_nothing(self):
        """ruff already convicts it, and an invented line number is the wrong address."""
        assert mock_console_check.scan("def broken(:\n") == []


class TestTheRendererConsoleIsCountedNotConvicted:
    """8 consoles in 4 files. capsys cannot capture an output the product never wrote."""

    def test_the_count_rides_in_the_passing_message(self, tmp_path):
        source = 'buffer = io.StringIO()\nConsole(file=buffer).print("x")\nassert buffer.getvalue()\n'
        path = _write(tmp_path, source)

        result = mock_console_check.check_module(str(path))

        assert result["score"] == 100
        assert "1 renderer console is counted" in result["checks"][0]["message"]

    def test_several_are_counted_in_the_plural(self, tmp_path):
        source = "Console(file=a).print('x')\nConsole(file=b).print('y')\n"
        path = _write(tmp_path, source)

        assert "2 renderer consoles are counted" in mock_console_check.check_module(str(path))["checks"][0]["message"]

    def test_a_file_with_none_says_only_that_the_console_is_real(self, tmp_path):
        path = _write(tmp_path, 'def test_x(capsys):\n    assert "ok" in capsys.readouterr().out\n')

        message = mock_console_check.check_module(str(path))["checks"][0]["message"]

        assert message == "The console the product prints to is the real one"
        assert "counted" not in message


class TestTheMessageAnAuthorReads:
    """Every hit on one check, because _format_failure shows the first and hides the rest."""

    def test_all_hits_share_one_check(self, tmp_path):
        source = 'setattr(mod, "console", Mock())\nother.console = MagicMock()\nrun(console=Mock())\n'
        path = _write(tmp_path, source)

        result = mock_console_check.check_module(str(path))

        assert len(result["checks"]) == 1
        assert result["checks"][0]["message"].count("test_thing.py:") == 3

    def test_the_message_names_the_file_the_line_and_the_fix(self, tmp_path):
        path = _write(tmp_path, 'setattr(mod, "console", Mock())\n')

        message = mock_console_check.check_module(str(path))["checks"][0]["message"]

        assert message == (
            "test_thing.py:1 a Mock installed over the product's console - read the channel with capsys.readouterr()"
        )

    def test_a_missing_file_scores_zero_and_says_which(self, tmp_path):
        result = mock_console_check.check_module(str(tmp_path / "tests" / "gone.py"))

        assert result["score"] == 0
        assert "File not found" in result["checks"][0]["message"]


class TestTheModelFileHoldsTheLine:
    """tests/test_readme_update.py is the fleet's gold test file for this item."""

    def test_the_model_file_passes(self):
        assert mock_console_check.check_module(str(MODEL))["score"] == 100

    def test_the_model_file_with_a_mock_console_handed_to_a_product_call_is_convicted(self, tmp_path):
        """Not a hand-written sample: the real file, plus the one line item 14 names."""
        source = MODEL.read_text(encoding="utf-8")
        mutated = source + "\n\ndef test_a_mock_console():\n    readme_update.render(console=MagicMock())\n"
        path = _write(tmp_path, mutated, name="test_readme_update.py")

        result = mock_console_check.check_module(str(path))

        assert result["score"] == 0
        assert "a Mock handed to the product as its console" in result["checks"][0]["message"]

    def test_the_model_file_with_a_buffered_console_installed_is_convicted(self, tmp_path):
        """A Rich Console on a StringIO renders for real and still leaves the channel empty."""
        source = MODEL.read_text(encoding="utf-8")
        mutated = source + (
            "\n\ndef test_a_buffered_console(monkeypatch):\n"
            "    buf = StringIO()\n"
            '    monkeypatch.setattr(readme_update, "console", Console(file=buf))\n'
            "    readme_update.render()\n"
            '    assert "x" in buf.getvalue()\n'
        )
        path = _write(tmp_path, mutated, name="test_readme_update.py")

        result = mock_console_check.check_module(str(path))

        assert result["score"] == 0
        assert "a Rich Console on a buffer installed over the product's console" in result["checks"][0]["message"]


class TestThroughTheChecklistCommand:
    """The door an agent actually meets the rule through: the PostToolUse lane."""

    @pytest.fixture(autouse=True)
    def _not_a_scratchpad(self, monkeypatch):
        """tmp_path lives under a temp root, and checklist skips those by design."""
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    def test_the_command_convicts_a_mock_console(self, tmp_path, capsys):
        path = _write(tmp_path, 'def test_x(monkeypatch):\n    monkeypatch.setattr(mod, "console", MagicMock())\n')

        checklist.handle_command("checklist", [str(path)])

        out = capsys.readouterr().out
        assert "[FAIL] — mock_console" in out
        assert "capsys" in out

    def test_the_command_stays_quiet_on_a_clean_file(self, tmp_path, capsys):
        """The standard still prints — as a tick. The absence to assert is the conviction."""
        path = _write(tmp_path, 'def test_x(capsys):\n    assert "ok" in capsys.readouterr().out\n')

        checklist.handle_command("checklist", [str(path)])

        out = capsys.readouterr().out
        assert "✓ mock_console" in out
        assert "[FAIL] — mock_console" not in out
