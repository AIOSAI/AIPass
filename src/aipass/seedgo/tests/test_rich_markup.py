"""Tests for the rich_markup standard — asserted against RENDERED output."""

# =================== META ====================
# Name: test_rich_markup.py
# Description: Unit tests for rich_markup_check and rich_markup_content
# Version: 1.1.0
# Created: 2026-08-11
# Modified: 2026-09-15
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


# ---------------------------------------------------------------------------
# 8. Following a literal to the print site that consumes it
#
# v1 read the PRINT SITE only, so drone's per-verb git help page scored 100
# while eating its own placeholders: the page is a literal RETURNED by
# get_help() and printed by print_help(), and the print site carried no
# literal at all to read. Measured 2026-09-15: v1 found 0 tokens in that file;
# the same file carries 29.
# ---------------------------------------------------------------------------


def _line_of(source: str, needle: str) -> int:
    """The 1-indexed line of the first source line containing *needle*."""
    for index, line in enumerate(source.splitlines(), start=1):
        if needle in line:
            return index
    raise AssertionError(f"{needle!r} is not in the fixture")


DRONE_SHAPED = '''"""S."""
console = None


def get_help():
    """Return the page, assembled here."""
    return "git log [count] [path]\\n"


def print_help():
    """Print the page, assembled elsewhere."""
    console.print(get_help())
'''

CONSTANT_SHAPED = '''"""S."""
console = None

HELP_TEXT = "compass add \\"c\\" \\"d\\" --rating R [opts]\\n"


def emit():
    """Print the page held in a module constant."""
    console.print(HELP_TEXT)
'''


def test_returned_literal_printed_by_a_caller_is_caught(tmp_path):
    """The drone shape: assembled in get_help(), printed in print_help()."""
    result = check_module(_write_source(tmp_path, DRONE_SHAPED))
    assert result["score"] == 0, f"a returned literal is still printed: {result}"
    rendered = _rendered_message(result)
    assert "[count]" in rendered
    assert "[path]" in rendered
    # Ground truth: this really is what reaches the terminal.
    assert _render("git log [count] [path]").rstrip() == "git log"


def test_returned_literal_names_both_the_token_line_and_the_print_line(tmp_path):
    """A followed token is two lines apart; naming one of them is not actionable."""
    result = check_module(_write_source(tmp_path, DRONE_SHAPED))
    token_line = _line_of(DRONE_SHAPED, "git log")
    print_line = _line_of(DRONE_SHAPED, "console.print(get_help())")
    assert f"[count] on line {token_line} (printed on line {print_line})" in _rendered_message(result)


def test_module_constant_printed_by_name_is_caught(tmp_path):
    """devpulse's compass page: a module-level literal, printed by name."""
    result = check_module(_write_source(tmp_path, CONSTANT_SHAPED))
    assert result["score"] == 0, f"a printed module constant is markup: {result}"
    assert "[opts]" in _rendered_message(result)
    assert "[opts]" not in _render('compass add "c" "d" --rating R [opts]')


def test_concatenated_return_is_read_through(tmp_path):
    """A help page is a run of adjacent literals with calls spliced in."""
    source = '"""S."""\nconsole = None\n\n\ndef page():\n    """Page."""\n    return "head\\n" + other() + "log [count]\\n"\n\n\ndef other():\n    """Other."""\n    return "x"\n\n\ndef emit():\n    """Emit."""\n    console.print(page())\n'
    result = check_module(_write_source(tmp_path, source))
    assert result["score"] == 0, f"concatenated literals are still literals: {result}"
    assert "[count]" in _rendered_message(result)


def test_a_followed_token_is_reported_once_however_often_it_is_printed(tmp_path):
    """Two call sites, one page: one token, not two."""
    source = (
        '"""S."""\nconsole = None\n\n\ndef page():\n    """Page."""\n    return "log [count]"\n\n\n'
        'def one():\n    """One."""\n    console.print(page())\n\n\ndef two():\n    """Two."""\n    console.print(page())\n'
    )
    result = check_module(_write_source(tmp_path, source))
    assert "1 literal placeholder(s)" in _rendered_message(result), _message(result)


def test_bypassing_the_print_line_silences_a_followed_token(tmp_path):
    """A followed token has two lines an author may reasonably silence."""
    path = _write_source(tmp_path, DRONE_SHAPED)
    print_line = _line_of(DRONE_SHAPED, "console.print(get_help())")
    rules = [{"standard": "rich_markup", "file": "sample.py", "lines": [print_line]}]
    assert check_module(path, bypass_rules=rules)["score"] == 100


# ---------------------------------------------------------------------------
# 9. markup=False -- right for one case, wrong for the rest
#
# "Escape the data; do not disarm the line" (src/aipass/cli/docs/rich_markup.md).
# markup=False is per-call and absolute: correct for a pre-formatted block that
# carries no styling, and on a styled line it does not merely fail to help --
# it prints the tags.
# ---------------------------------------------------------------------------


def test_preformatted_block_printed_verbatim_is_clean(tmp_path):
    """The one case markup=False is for: no styling, placeholders literal."""
    source = '"""S."""\nconsole = None\n\n\ndef page():\n    """Page."""\n    return "git log [count] [path]\\n"\n\n\ndef emit():\n    """Emit."""\n    console.print(page(), markup=False)\n'
    result = check_module(_write_source(tmp_path, source))
    assert result["score"] == 100, f"an unstyled verbatim block is the cure: {result}"
    # Ground truth: the placeholders really do reach the terminal.
    buffer = io.StringIO()
    Console(file=buffer, force_terminal=False, width=200).print("git log [count] [path]", markup=False)
    assert "[count] [path]" in buffer.getvalue()


def test_styled_line_with_markup_false_is_flagged(tmp_path):
    """Disarming a styled line prints the tags the author meant as styling."""
    source = '"""S."""\nconsole = None\n\n\ndef emit():\n    """Emit."""\n    console.print("[green]ok[/green] done", markup=False)\n'
    result = check_module(_write_source(tmp_path, source))
    assert result["score"] == 0, f"markup=False on a styled line prints its tags: {result}"
    assert "[green]" in _rendered_message(result)
    # Ground truth: the tag really does reach the terminal as text.
    buffer = io.StringIO()
    Console(file=buffer, force_terminal=False, width=200).print("[green]ok[/green] done", markup=False)
    assert "[green]ok[/green] done" in buffer.getvalue()


def test_followed_literal_is_read_for_the_disarmed_family_too(tmp_path):
    """A styled page returned from elsewhere is disarmed just as thoroughly."""
    source = '"""S."""\nconsole = None\n\n\ndef page():\n    """Page."""\n    return "[bold]Usage:[/bold]\\n"\n\n\ndef emit():\n    """Emit."""\n    console.print(page(), markup=False)\n'
    result = check_module(_write_source(tmp_path, source))
    assert result["score"] == 0, f"following applies to both families: {result}"
    assert "[bold]" in _rendered_message(result)


def test_markup_false_message_names_escape_not_the_switch(tmp_path):
    """The cure offered is per-value escape, never a wider disarm."""
    source = '"""S."""\nconsole = None\n\n\ndef emit():\n    """Emit."""\n    console.print("[green]ok[/green]", markup=False)\n'
    rendered = _rendered_message(check_module(_write_source(tmp_path, source)))
    assert "markup=False disarms the whole line" in rendered
    assert "escape the value instead" in rendered


def test_pass_through_body_with_markup_false_stays_clean(tmp_path):
    """@ai_mail routes message bodies this way: a runtime value, nothing to read.

    This is the case the guard exists for. A rule that flagged it would mark a
    branch non-compliant for applying the only fix available to it.
    """
    source = '"""S."""\nconsole = None\n\n\ndef emit(body):\n    """Emit."""\n    console.print(body, markup=False)\n'
    assert check_module(_write_source(tmp_path, source))["score"] == 100


# ---------------------------------------------------------------------------
# 10. Escaping: per value, and what a hand-escape is worth
# ---------------------------------------------------------------------------


def test_per_value_escape_is_clean(tmp_path):
    """escape() composes: a styled label beside a literal placeholder, both right."""
    source = (
        '"""S."""\nfrom rich.markup import escape\n\nconsole = None\n\n\n'
        'def emit(value):\n    """Emit."""\n    console.print(f"[green]ok[/green] {escape(value)}")\n'
    )
    assert check_module(_write_source(tmp_path, source))["score"] == 100
    # Ground truth: the styling survives and the value's brackets do too.
    from rich.markup import escape as rich_escape

    assert _render(f"[green]ok[/green] {rich_escape('[count]')}") == "ok [count]"


def test_eaten_message_prescribes_escape_not_a_hand_written_backslash(tmp_path):
    """A hand-escape is not the spelling this standard asks for any more.

    It works while the parser is on, so it is not flagged; it is simply no
    longer what the checker tells an author to type. escape() is per-value,
    composes, and is the only spelling available to a runtime value.
    """
    rendered = _rendered_message(check_module(_write_module(tmp_path, ["a [args...] b"])))
    assert "escape the value with rich.markup.escape()" in rendered
    assert "escape as" not in rendered


def test_hand_escape_still_works_so_it_is_not_flagged(tmp_path):
    """The stated limit: a scored, gating standard does not fail working code.

    A styled literal help page that must also show a literal placeholder has
    no other spelling -- escape() applied to the whole page would eat the
    styling with it. The demotion is in the guidance, not in the score.
    """
    source = '"""S."""\nconsole = None\n\n\ndef emit():\n    """Emit."""\n    console.print("[bold]usage:[/bold] cmd \\\\[args...]")\n'
    assert check_module(_write_source(tmp_path, source))["score"] == 100
    assert _render("[bold]usage:[/bold] cmd \\[args...]") == "usage: cmd [args...]"


def test_hand_escape_is_not_credited_once_the_parser_is_off(tmp_path):
    """markup=False strands a hand-escape: the backslash itself reaches the terminal."""
    source = '"""S."""\nconsole = None\n\n\ndef emit():\n    """Emit."""\n    console.print("cmd \\\\[args...]", markup=False)\n'
    result = check_module(_write_source(tmp_path, source))
    assert result["score"] == 0, f"a stranded escape is a real loss: {result}"
    assert "\\[args...]" in _rendered_message(result)
    # Ground truth: the backslash really is printed.
    buffer = io.StringIO()
    Console(file=buffer, force_terminal=False, width=200).print("cmd \\[args...]", markup=False)
    assert "cmd \\[args...]" in buffer.getvalue()


# ---------------------------------------------------------------------------
# 11. What this rule deliberately does not claim
#
# Every pin below asserts SILENCE. Each one is a stated limit in
# rich_markup_check's module docstring and in rich_markup.md; a limit with no
# pin is a limit that quietly widens on the next edit.
# ---------------------------------------------------------------------------


def test_limit_the_file_boundary_is_not_crossed(tmp_path):
    """A literal assembled in another module is invisible, by choice."""
    _write_source(tmp_path, '"""H."""\n\n\ndef get_help():\n    """Page."""\n    return "log [count]"\n', "helper.py")
    printer = '"""S."""\nfrom helper import get_help\n\nconsole = None\n\n\ndef emit():\n    """Emit."""\n    console.print(get_help())\n'
    assert check_module(_write_source(tmp_path, printer))["score"] == 100


def test_limit_hops_do_not_chain(tmp_path):
    """One hop. A followed function's own local call is not entered."""
    source = (
        '"""S."""\nconsole = None\n\n\ndef page():\n    """Page."""\n    return inner()\n\n\n'
        'def inner():\n    """Inner."""\n    return "log [count]"\n\n\ndef emit():\n    """Emit."""\n    console.print(page())\n'
    )
    assert check_module(_write_source(tmp_path, source))["score"] == 100


def test_limit_a_local_variable_is_not_followed(tmp_path):
    """Flow inside a function is not read -- which literal arrives is a guess."""
    source = '"""S."""\nconsole = None\n\n\ndef emit():\n    """Emit."""\n    body = "log [count]"\n    console.print(body)\n'
    assert check_module(_write_source(tmp_path, source))["score"] == 100


def test_limit_an_accumulated_list_is_not_followed(tmp_path):
    """join(), append() and % need flow analysis this rule refuses to fake."""
    source = (
        '"""S."""\nconsole = None\n\nLINES = ["log [count]"]\n\n\n'
        'def emit():\n    """Emit."""\n    console.print("\\n".join(LINES))\n    console.print("log %s [count]" % "x")\n'
    )
    assert check_module(_write_source(tmp_path, source))["score"] == 100


def test_limit_a_name_bound_twice_is_not_followed(tmp_path):
    """Rebound, so the value at the print site is not provable."""
    source = (
        '"""S."""\nimport os\n\nconsole = None\n\nBANNER = "log [count]"\n\n\n'
        'def emit():\n    """Emit."""\n    global BANNER\n    BANNER = os.environ.get("B", "")\n    console.print(BANNER)\n'
    )
    assert check_module(_write_source(tmp_path, source))["score"] == 100


def test_limit_a_non_constant_markup_argument_is_not_read(tmp_path):
    """Whether the parser runs is unknown, so neither family claims the call."""
    source = (
        '"""S."""\nconsole = None\n\n\ndef emit(flag):\n    """Emit."""\n'
        '    console.print("log [count]", markup=flag)\n    console.print("[green]ok[/green]", markup=flag)\n'
    )
    assert check_module(_write_source(tmp_path, source))["score"] == 100


def test_limit_a_rich_renderable_wrapper_is_not_opened(tmp_path):
    """Panel(...) and friends are constructor arguments, not print arguments."""
    source = (
        '"""S."""\nfrom rich.panel import Panel\n\nconsole = None\n\n\n'
        'def emit():\n    """Emit."""\n    console.print(Panel("log [count]"))\n'
    )
    assert check_module(_write_source(tmp_path, source))["score"] == 100


def test_limit_markup_false_cannot_read_intent(tmp_path):
    """The known false positive, pinned so it is a decision and not a surprise.

    A pre-formatted block that QUOTES a real style tag is reported, because
    nothing in the source distinguishes documentation about [dim] from a line
    the author meant to style. It nominates. A human decides.
    """
    source = '"""S."""\nconsole = None\n\n\ndef emit():\n    """Emit."""\n    console.print("write [dim] to dim a run", markup=False)\n'
    assert check_module(_write_source(tmp_path, source))["score"] == 0
