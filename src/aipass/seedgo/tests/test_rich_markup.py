"""Tests for the rich_markup standard — asserted against RENDERED output."""

# =================== META ====================
# Name: test_rich_markup.py
# Description: Unit tests for rich_markup_check and rich_markup_content
# Version: 1.0.0
# Created: 2026-08-11
# Modified: 2026-08-11
# =============================================

import io
from pathlib import Path
from typing import List, Tuple

import pytest
from rich.console import Console
from rich.errors import MarkupError

from aipass.seedgo.apps.handlers.aipass_standards.rich_markup_check import check_module
from aipass.seedgo.apps.handlers.aipass_standards.rich_markup_content import get_rich_markup_standards

# ---------------------------------------------------------------------------
# Rendering harness
#
# THE ACCEPTANCE CRITERION OF THIS STANDARD: every assertion below is made
# against bytes read back out of a real Console's buffer. The repo conftest
# installs a MagicMock console elsewhere; nothing here touches it, and nothing
# here asserts on call arguments. A MagicMock records the arguments -- which
# are CORRECT, that is the entire defect -- and renders nothing, so it agrees
# by construction. A real Console whose output is never read is the same
# stand-in wearing a better name. Only reading the rendered bytes can catch
# a loss that only happens at render time.
# ---------------------------------------------------------------------------


def _render(markup: str) -> str:
    """Render *markup* through a real Console and read the output back out."""
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=False, width=300)
    console.print(markup)
    return buffer.getvalue().rstrip("\n")


# ---------------------------------------------------------------------------
# Module-under-test builders
# ---------------------------------------------------------------------------

_HEADER = ['"""Sample module."""', "", "console = None", "", "def emit():", '    """Emit output."""']
_FIRST_PRINT_LINE = len(_HEADER) + 1


def _write_source(tmp_path: Path, source: str, name: str = "sample.py") -> str:
    """Write a source file and return its path as a string."""
    target = tmp_path / name
    target.write_text(source, encoding="utf-8")
    return str(target)


def _write_module(tmp_path: Path, printed: List[str], name: str = "sample.py") -> str:
    """Write a module that console.print()s each string in *printed*.

    ``repr()`` round-trips the value: the source Python parses back to exactly
    the string handed to :func:`_render`, so the checker and the renderer are
    judging the same bytes.
    """
    lines = list(_HEADER) + [f"    console.print({text!r})" for text in printed]
    return _write_source(tmp_path, "\n".join(lines) + "\n", name)


def _message(result: dict) -> str:
    """The single check message from a checker result."""
    return result["checks"][0]["message"]


def _rendered_message(result: dict) -> str:
    """The check message as the audit displays it -- through Rich.

    audit_display.py interpolates every check message into
    ``console.print(f"[dim]• {message}[/dim]")``. A message naming ``[args...]``
    unescaped would have that token eaten on its way to the reader, so the
    checker would commit the very defect it reports. Read it back rendered.
    """
    return _render(f"[dim]• {_message(result)}[/dim]")


# ---------------------------------------------------------------------------
# 1. The defect: tokens Rich silently eats
# ---------------------------------------------------------------------------

EATEN_CASES: List[Tuple[str, str]] = [
    ("a [args...] b", "[args...]"),
    ("[branch] row", "[branch]"),
    ("drone @hooks <command> [args...]", "[args...]"),
    ("monitor run [branches]", "[branches]"),
    ("usage: cmd [options]", "[options]"),
    ("mail from [@daemon]", "[@daemon]"),
    ("see [link] below", "[link]"),
]


@pytest.mark.parametrize("text,token", EATEN_CASES)
def test_eaten_token_really_vanishes_from_rendered_output(text, token):
    """The premise: Rich deletes these tokens, silently, at render time."""
    rendered = _render(text)
    assert token not in rendered, f"expected Rich to eat {token!r}, but rendered: {rendered!r}"


@pytest.mark.parametrize("text,token", EATEN_CASES)
def test_eaten_token_is_flagged(tmp_path, text, token):
    """Every token proven eaten above must be caught by the checker."""
    result = check_module(_write_module(tmp_path, [text]))
    assert result["score"] == 0, f"{text!r} should be flagged: {result}"
    assert result["passed"] is False
    assert token in _rendered_message(result)


# ---------------------------------------------------------------------------
# 2. False-positive families: brackets Rich leaves alone
# ---------------------------------------------------------------------------

SURVIVING_CASES: List[Tuple[str, str]] = [
    ("a [1,2,3] b", "a [1,2,3] b"),
    ("lines [42, 78]", "lines [42, 78]"),
    ("L[42]: msg", "L[42]: msg"),
    ("a [] b", "a [] b"),
    ("a [ spaced ] b", "a [ spaced ] b"),
    ("a \\[literal] b", "a [literal] b"),
    ("a [Branch] b", "a [Branch] b"),
]


@pytest.mark.parametrize("text,expected", SURVIVING_CASES)
def test_surviving_family_reaches_the_terminal_intact(text, expected):
    """The premise: nothing is lost, so there is nothing to report."""
    assert _render(text) == expected


@pytest.mark.parametrize("text,expected", SURVIVING_CASES)
def test_surviving_family_is_not_flagged(tmp_path, text, expected):
    """No token was lost, so the checker must stay silent."""
    result = check_module(_write_module(tmp_path, [text]))
    assert result["score"] == 100, f"{text!r} must not be flagged: {result}"


LEGITIMATE_MARKUP: List[Tuple[str, str]] = [
    ("a [dim]x[/dim] b", "a x b"),
    ("a [bold cyan]x[/] b", "a x b"),
    ("a [link=http://x]y[/link] b", "a y b"),
    ("a [on red]x[/] b", "a x b"),
    ("a [#ff0000]x[/] b", "a x b"),
]


@pytest.mark.parametrize("text,expected", LEGITIMATE_MARKUP)
def test_intentional_markup_keeps_its_content(text, expected):
    """The premise: a real style tag consumes itself, never the content."""
    assert _render(text) == expected


@pytest.mark.parametrize("text,expected", LEGITIMATE_MARKUP)
def test_intentional_markup_is_not_flagged(tmp_path, text, expected):
    """Deliberate styling is the feature, not the defect."""
    result = check_module(_write_module(tmp_path, [text]))
    assert result["score"] == 100, f"{text!r} must not be flagged: {result}"


def test_mismatched_closing_tag_fails_loudly_and_is_not_flagged(tmp_path):
    """[/usr/bin] raises MarkupError -- loud, already caught by tests."""
    with pytest.raises(MarkupError):
        _render("a [/usr/bin] b")
    result = check_module(_write_module(tmp_path, ["a [/usr/bin] b"]))
    assert result["score"] == 100, f"loud failures are out of scope: {result}"


# ---------------------------------------------------------------------------
# 3. Structural exclusions (AST, not regex)
# ---------------------------------------------------------------------------


def test_markup_false_is_not_flagged(tmp_path):
    """markup=False turns Rich's parser off -- nothing is eaten, nothing to fix.

    This is the correct treatment for pass-through content the author cannot
    edit (@ai_mail renders message bodies this way). Flagging it would mark a
    branch non-compliant for applying the only fix available to it.
    """
    source = '"""S."""\nconsole = None\n\n\ndef emit():\n    console.print("cmd [args...] here", markup=False)\n'
    result = check_module(_write_source(tmp_path, source))
    assert result["score"] == 100, f"markup=False must not be flagged: {result}"
    # Ground truth: Rich really does render the brackets verbatim here.
    buffer = io.StringIO()
    Console(file=buffer, force_terminal=False, width=200).print("cmd [args...] here", markup=False)
    assert "[args...]" in buffer.getvalue(), "markup=False should render brackets literally"


def test_markup_true_is_still_flagged(tmp_path):
    """The guard is keyed to False only -- markup=True still renders markup."""
    source = '"""S."""\nconsole = None\n\n\ndef emit():\n    console.print("cmd [args...] here", markup=True)\n'
    result = check_module(_write_source(tmp_path, source))
    assert result["score"] == 0, f"markup=True still eats the token: {result}"


def test_fstring_subscript_is_not_flagged(tmp_path):
    """An f-string subscript's brackets live outside every literal segment."""
    source = '"""S."""\nconsole = None\n\n\ndef emit(d):\n    console.print(f"count {d[\'k\']} rows")\n'
    result = check_module(_write_source(tmp_path, source))
    assert result["score"] == 100, f"f-string subscript must not be flagged: {result}"
    # And nothing is lost when the realized string is rendered
    assert _render("count 42 rows") == "count 42 rows"


def test_fstring_literal_segment_is_still_checked(tmp_path):
    """The literal half of an f-string is markup like any other."""
    source = '"""S."""\nconsole = None\n\n\ndef emit(name):\n    console.print(f"[branch] {name}")\n'
    result = check_module(_write_source(tmp_path, source))
    assert result["score"] == 0, f"f-string literals must still be checked: {result}"
    assert "[branch]" in _rendered_message(result)


def test_format_template_tag_is_not_flagged(tmp_path):
    """A {} placeholder inside a tag is filled in before Rich ever sees it.

    ``[bold {color}]`` is deliberately the shape used here: Rich's own regex
    DOES match it (it starts with a-z), so only the ``{`` guard keeps it out
    of the report. ``[{color}]`` would prove nothing -- RE_TAGS never matches
    a tag opening on ``{``.
    """
    source = '"""S."""\nconsole = None\n\n\ndef emit(c):\n    console.print("[bold {color}]x[/]".format(color=c))\n'
    result = check_module(_write_source(tmp_path, source))
    assert result["score"] == 100, f"format templates must not be flagged: {result}"
    # The realized string is real markup and loses nothing
    assert _render("[bold red]x[/]") == "x"


def test_format_template_literal_is_still_checked(tmp_path):
    """A .format() template is still a literal -- its real tags are checked."""
    source = '"""S."""\nconsole = None\n\n\ndef emit(name):\n    console.print("[branch] {}".format(name))\n'
    result = check_module(_write_source(tmp_path, source))
    assert result["score"] == 0, f".format() templates must still be checked: {result}"
    assert "[branch]" in _rendered_message(result)


def test_style_keyword_argument_is_not_markup(tmp_path):
    """style= carries a style name, not markup -- keywords are not scanned."""
    source = '"""S."""\nconsole = None\n\n\ndef emit():\n    console.print("plain text", style="bold")\n'
    result = check_module(_write_source(tmp_path, source))
    assert result["score"] == 100, f"style= must not be scanned: {result}"


def test_stdlib_print_is_not_flagged(tmp_path):
    """Bare print() is stdlib: it renders no markup, so nothing is lost."""
    source = '"""S."""\n\n\ndef emit():\n    print("usage: cmd [args...]")\n'
    result = check_module(_write_source(tmp_path, source))
    assert result["score"] == 100, f"stdlib print renders brackets verbatim: {result}"


def test_rich_print_import_is_flagged(tmp_path):
    """from rich import print shadows the builtin with a markup renderer."""
    source = '"""S."""\nfrom rich import print\n\n\ndef emit():\n    print("usage: cmd [args...]")\n'
    result = check_module(_write_source(tmp_path, source))
    assert result["score"] == 0, f"rich's print does render markup: {result}"
    assert "[args...]" in _rendered_message(result)


def test_multiline_literal_reports_the_tag_line(tmp_path):
    """A tag inside a triple-quoted literal is reported where it sits."""
    source = '"""S."""\nconsole = None\n\n\ndef emit():\n    console.print("""first\nsecond [options] here""")\n'
    result = check_module(_write_source(tmp_path, source))
    assert "[options] on line 7" in _rendered_message(result)


# ---------------------------------------------------------------------------
# 4. The violation message
# ---------------------------------------------------------------------------


def test_message_names_every_token_and_its_line(tmp_path):
    """A bare count cannot be acted on -- name the token and the line."""
    path = _write_module(tmp_path, ["a [args...] b", "clean line", "[branch] row"])
    rendered = _rendered_message(check_module(path))
    assert f"[args...] on line {_FIRST_PRINT_LINE}" in rendered
    assert f"[branch] on line {_FIRST_PRINT_LINE + 2}" in rendered
    assert "2 literal placeholder(s)" in rendered


def test_message_survives_its_own_rendering(tmp_path):
    """The tokens are escaped, so the audit's console.print cannot eat them."""
    result = check_module(_write_module(tmp_path, ["a [args...] b"]))
    raw = _message(result)
    assert "\\[args...]" in raw, f"tokens must be Rich-escaped in the raw message: {raw}"
    assert "[args...]" in _rendered_message(result)


def test_capped_message_announces_how_many_it_hid(tmp_path):
    """A capped list must say so -- a silent truncation hides work."""
    texts = [f"row [tag{n}] end" for n in range(7)]
    rendered = _rendered_message(check_module(_write_module(tmp_path, texts)))
    assert "7 literal placeholder(s)" in rendered
    assert "and 2 more" in rendered
    assert "[tag0]" in rendered
    assert "[tag4]" in rendered
    assert "[tag6]" not in rendered


# ---------------------------------------------------------------------------
# 5. Bypass
# ---------------------------------------------------------------------------


def test_per_line_bypass_suppresses_only_that_line(tmp_path):
    """Line-scoped bypass removes one violation, not the file."""
    path = _write_module(tmp_path, ["a [args...] b", "[branch] row"])
    rules = [{"standard": "rich_markup", "file": "sample.py", "lines": [_FIRST_PRINT_LINE]}]
    rendered = _rendered_message(check_module(path, bypass_rules=rules))
    assert "1 literal placeholder(s)" in rendered
    assert "[args...]" not in rendered
    assert f"[branch] on line {_FIRST_PRINT_LINE + 1}" in rendered


def test_per_line_bypass_of_every_violation_passes(tmp_path):
    """Bypass every offending line and the file is clean."""
    path = _write_module(tmp_path, ["a [args...] b", "[branch] row"])
    rules = [
        {
            "standard": "rich_markup",
            "file": "sample.py",
            "lines": [_FIRST_PRINT_LINE, _FIRST_PRINT_LINE + 1],
        }
    ]
    result = check_module(path, bypass_rules=rules)
    assert result["score"] == 100, f"all lines bypassed: {result}"


def test_file_level_bypass_returns_100(tmp_path):
    """A file-wide rule short-circuits before the file is even read."""
    path = _write_module(tmp_path, ["a [args...] b", "[branch] row"])
    result = check_module(path, bypass_rules=[{"standard": "rich_markup", "file": "sample.py"}])
    assert result["score"] == 100
    assert result["passed"] is True
    assert result["checks"][0]["name"] == "Bypassed"


def test_bypass_for_another_standard_does_not_apply(tmp_path):
    """A debug_print rule must not silence rich_markup."""
    path = _write_module(tmp_path, ["a [args...] b"])
    result = check_module(path, bypass_rules=[{"standard": "debug_print", "file": "sample.py"}])
    assert result["score"] == 0, f"another standard's bypass must not apply: {result}"


# ---------------------------------------------------------------------------
# 6. Result shape and edge cases
# ---------------------------------------------------------------------------


def test_clean_file_passes(tmp_path):
    """A file with correct markup scores 100."""
    result = check_module(_write_module(tmp_path, ["all [green]good[/green] here", "L[42]: msg"]))
    assert result["score"] == 100
    assert result["standard"] == "RICH_MARKUP"


def test_missing_file_scores_zero(tmp_path):
    """A path that does not exist is reported, not silently passed."""
    result = check_module(str(tmp_path / "nope.py"))
    assert result["score"] == 0
    assert result["passed"] is False


def test_unparseable_file_is_skipped_not_failed(tmp_path):
    """Broken Python is the diagnostics lane's finding, not this one."""
    result = check_module(_write_source(tmp_path, "def broken(:\n", "broken.py"))
    assert result["score"] == 100
    assert "Not parseable" in _message(result)


# ---------------------------------------------------------------------------
# 7. Content handler
# ---------------------------------------------------------------------------


def test_content_renders_without_losing_its_own_examples():
    """The standard's own text must survive the defect it documents."""
    rendered = _render(get_rich_markup_standards())
    for token in ("[args...]", "[branch]", "[branches]", "[1,2,3]", "[42, 78]", "[@daemon]"):
        assert token in rendered, f"content lost {token} at render time"


def test_content_states_the_rendered_output_criterion():
    """The acceptance criterion is part of the standard, not a nicety."""
    rendered = _render(get_rich_markup_standards())
    assert "RENDERED OUTPUT" in rendered
    assert "MagicMock" in rendered
    assert "buffer.getvalue()" in rendered
