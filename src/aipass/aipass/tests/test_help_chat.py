# =================== AIPass ====================
# Name: tests/test_help_chat.py
# Description: Tests for help_chat module — section-aware v2 (DPLAN-0282 P3)
# Version: 2.1.4
# Created: 2026-04-16
# Modified: 2026-09-28
# =============================================

"""Tests for apps/modules/help_chat.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that help_chat.py and the modules it imports parse and import

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.aipass.apps.modules.help_chat import COMMAND, handle_command

_HC = "aipass.aipass.apps.modules.help_chat"
_RM = "aipass.aipass.apps.handlers.readme_map"

# The product's body cap per section (help_chat._MAX_SECTION_LINES), read here as the number it is.
_BODY_CAP = 25


def _ask(
    tmp_path: Path,
    words: list[str],
    capsys: pytest.CaptureFixture[str],
    readme: str | None = None,
    branches: list[str] | None = None,
    readme_path: Path | None = None,
) -> tuple[str, str, dict]:
    """Run `aipass help <words>` over one README under tmp_path; return (stdout, stderr, logged data).

    Every branch in `branches` (default ["drone"]) resolves to the same README path, both in
    help_chat and in readme_map (which read_readme_lines reads through). `readme` None leaves no
    README path at all. The logged data is what handle_command hands json_handler.log_operation
    ({} when it logs nothing).
    """
    path = readme_path or tmp_path / "src" / "aipass" / "drone" / "README.md"
    if readme is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(readme, encoding="utf-8")
    resolved = path if readme is not None else None
    with ExitStack() as stack:
        jh = stack.enter_context(patch(f"{_HC}.json_handler", autospec=True))
        stack.enter_context(patch(f"{_HC}.list_branches", return_value=branches or ["drone"]))
        stack.enter_context(patch(f"{_HC}.get_readme_path", return_value=resolved))
        stack.enter_context(patch("aipass.aipass.apps.handlers.readme_map.get_readme_path", return_value=resolved))
        assert handle_command("help", words) is True
    out, err = capsys.readouterr()
    call = jh.log_operation.call_args
    return out, err, (call.kwargs["data"] if call else {})


# =============================================================================
# CONSTANTS / SHARED DATA
# =============================================================================

_FAKE_BRANCHES = ["drone", "seedgo", "prax", "cli", "flow", "ai_mail", "spawn"]

_SAMPLE_README = """\
# Drone

Drone is the task-runner for AIPass.

## Usage

Run tasks with drone dispatch.

Drone supports multiple branches.
"""

# Ensure encoding='utf-8' appears in this file (PATTERN check scans file-wide)
_ENCODING = "utf-8"


# =============================================================================
# HELPERS — reduce nesting in test functions via ExitStack
# =============================================================================


def _call_handle_command_drone_question(readme_content: str, readme_path: Path):
    """Call handle_command for 'what does drone do' over a real README written at readme_path."""
    readme_path.parent.mkdir(parents=True, exist_ok=True)
    readme_path.write_text(readme_content, encoding="utf-8")
    patches = [
        patch("aipass.aipass.apps.modules.help_chat.json_handler", autospec=True),
        patch("aipass.aipass.apps.modules.help_chat.list_branches", return_value=["drone"]),
        patch("aipass.aipass.apps.modules.help_chat.get_readme_path", return_value=readme_path),
        patch("aipass.aipass.apps.handlers.readme_map.get_readme_path", return_value=readme_path),
        patch("aipass.aipass.apps.modules.help_chat.header"),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        return handle_command("help", ["what", "does", "drone", "do"])


def _call_handle_no_match():
    """Call handle_command for unknown keyword with no README path returned."""
    patches = [
        patch("aipass.aipass.apps.modules.help_chat.json_handler", autospec=True),
        patch("aipass.aipass.apps.modules.help_chat.list_branches", return_value=["drone"]),
        patch("aipass.aipass.apps.modules.help_chat.get_readme_path", return_value=None),
        patch("aipass.aipass.apps.modules.help_chat.header"),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        return handle_command("help", ["xyzzy999"])


def _call_handle_all_stopwords():
    """Call handle_command with a question that reduces to zero keywords."""
    with patch("aipass.aipass.apps.modules.help_chat.json_handler", autospec=True):
        return handle_command("help", ["what", "is", "the"])


def _capture_depth_offer_prints(readme_path: Path) -> None:
    """Call handle_command for 'drone' where readme_path is never written, so open() raises OSError."""
    patches = [
        patch("aipass.aipass.apps.modules.help_chat.json_handler", autospec=True),
        patch("aipass.aipass.apps.modules.help_chat.list_branches", return_value=["drone"]),
        patch("aipass.aipass.apps.modules.help_chat.get_readme_path", return_value=readme_path),
        patch("aipass.aipass.apps.handlers.readme_map.get_readme_path", return_value=readme_path),
        patch("aipass.aipass.apps.modules.help_chat.logger"),
        patch("aipass.aipass.apps.modules.help_chat.header"),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        handle_command("help", ["drone"])


# =============================================================================
# Keyword extraction (_extract_keywords), read through `aipass help`
# =============================================================================


class TestExtractKeywords:
    """Keyword extraction, read from the keywords `aipass help` logs for its question."""

    def test_strips_stopwords(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """Known stopwords must not appear in the result.

        Mutant: `stripped not in _STOPWORDS and` dropped from the filter -> red.
        """
        _out, _err, data = _ask(tmp_path, ["what", "does", "drone", "do"], capsys)
        assert data["keywords"] == ["drone"]

    def test_strips_question_mark(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """Trailing ? on a word must be stripped before comparison."""
        _out, _err, data = _ask(tmp_path, ["how", "does", "drone", "work?"], capsys)
        assert data["keywords"] == ["drone", "work"]

    def test_strips_comma_and_period(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """Commas and periods attached to words must be stripped."""
        _out, _err, data = _ask(tmp_path, ["drone,", "flow,", "prax."], capsys)
        assert data["keywords"] == ["drone", "flow", "prax"]

    def test_lowercases_words(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """All output keywords must be lowercase."""
        _out, _err, data = _ask(tmp_path, ["What", "Is", "DRONE"], capsys)
        assert data["keywords"] == ["drone"]

    def test_filters_single_char_words(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """Single-character tokens must be excluded from output."""
        _out, _err, data = _ask(tmp_path, ["a", "b", "c", "drone"], capsys)
        assert data["keywords"] == ["drone"]

    def test_empty_question_returns_empty_list(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """A question of bare punctuation extracts nothing: error printed, nothing logged."""
        _out, err, data = _ask(tmp_path, ["?", "!"], capsys)
        assert "Could not extract keywords from question" in err
        assert data == {}

    def test_all_stopwords_returns_empty_list(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """A question composed entirely of stopwords extracts nothing: error printed, nothing logged."""
        _out, err, data = _ask(tmp_path, ["what", "is", "the"], capsys)
        assert "Could not extract keywords from question" in err
        assert data == {}

    def test_mixed_content_extracts_content_words(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """Only non-stopword, non-punctuation words of length > 1 returned."""
        words = ["how", "do", "i", "send", "mail", "to", "another", "branch?"]
        _out, _err, data = _ask(tmp_path, words, capsys)
        assert data["keywords"] == ["send", "mail", "another", "branch"]


# =============================================================================
# Branch matching (_match_branches), read through `aipass help`
# =============================================================================


class TestMatchBranches:
    """Branch matching, read from the branches `aipass help` logs as searched (first three)."""

    def test_exact_branch_name_match_is_first(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """A keyword exactly matching a branch name places it first in results.

        Mutant: `if kw in available and kw not in direct:` -> `if False:` (no direct match) -> red.
        """
        _out, _err, data = _ask(tmp_path, ["spawn"], capsys, branches=_FAKE_BRANCHES)
        assert data["branches_searched"] == ["spawn"]

    def test_multiple_direct_matches_included(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """Multiple exact branch-name keywords all appear in results."""
        _out, _err, data = _ask(tmp_path, ["drone", "flow"], capsys, branches=_FAKE_BRANCHES)
        assert data["branches_searched"] == ["drone", "flow"]

    def test_fallback_returns_all_branches_when_no_match(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """Unrecognised keyword falls back to every branch; the first three are searched and logged.

        Every branch resolves to one README holding the word, so a searched branch prints its
        section: what is searched is read off the screen, what is logged off the log call.
        Mutants: the search loop over `branches` uncapped -> red at the fourth branch printed;
        the log of `branches` uncapped -> red at the logged list.
        """
        readme = "# Topic\nxyzzy999 here\n"
        out, _err, data = _ask(tmp_path, ["xyzzy999"], capsys, readme=readme, branches=_FAKE_BRANCHES)
        searched = [b for b in _FAKE_BRANCHES if f"{b} — Topic" in out]
        assert searched == _FAKE_BRANCHES[:3]
        assert data["branches_searched"] == _FAKE_BRANCHES[:3]

    def test_partial_keyword_in_branch_name(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """Keyword 'mail' contained in branch name 'ai_mail' is searched after the direct match."""
        _out, _err, data = _ask(tmp_path, ["drone", "mail"], capsys, branches=_FAKE_BRANCHES)
        assert data["branches_searched"] == ["drone", "ai_mail"]

    def test_empty_branches_list_returns_empty(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """When no branches exist, nothing is searched and nothing is found."""
        with patch(f"{_HC}.list_branches", return_value=[]):
            with patch(f"{_HC}.json_handler", autospec=True) as jh:
                assert handle_command("help", ["drone"]) is True
        assert jh.log_operation.call_args.kwargs["data"]["branches_searched"] == []
        assert "No relevant information found." in capsys.readouterr().out

    def test_no_duplicates_in_result(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """Passing the same keyword twice must not produce duplicate branch entries."""
        _out, _err, data = _ask(tmp_path, ["drone", "drone"], capsys, branches=_FAKE_BRANCHES)
        assert data["branches_searched"] == ["drone"]


# =============================================================================
# Section splitting and ranking (_split_sections, _score_section, _search_readme),
# read through `aipass help`
# =============================================================================


class TestSplitSections:
    """Heading-bounded splitting, read from the sections `aipass help drone` prints."""

    def test_splits_on_headings(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """Each #/##/### heading starts a new section, each printed with its own title.

        Mutant: `_HEADING_RE.match(line)` -> `None` (no heading ever splits) -> red.
        """
        out, _err, _data = _ask(tmp_path, ["drone", "usage"], capsys, readme=_SAMPLE_README)
        assert "drone — Drone  (src/aipass/drone/README.md:1-4)" in out
        assert "drone — Usage  (src/aipass/drone/README.md:5-9)" in out

    def test_preamble_becomes_intro_section(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """Content before the first heading is kept as an untitled section."""
        out, _err, _data = _ask(tmp_path, ["drone"], capsys, readme="intro drone line\n# Title\nbody\n")
        assert "drone — (intro)  (src/aipass/drone/README.md:1-1)" in out
        assert "intro drone line" in out

    def test_line_numbers_1_indexed_and_bounded(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """start = heading line, end = last line of the section."""
        out, _err, _data = _ask(tmp_path, ["drone"], capsys, readme="# Other\nx\n# Drone\nThe drone router.\n")
        assert "drone — Drone  (src/aipass/drone/README.md:3-4)" in out

    def test_heading_inside_code_fence_ignored(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """A # line inside ``` fences is body text, not a section break."""
        readme = "# Real\n```\n# not a heading drone\n```\ntail\n"
        out, _err, _data = _ask(tmp_path, ["drone"], capsys, readme=readme)
        assert "drone — Real  (src/aipass/drone/README.md:1-5)" in out
        assert "# not a heading drone" in out
        assert out.count("drone — ") == 1

    def test_empty_input_returns_empty(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """An empty README has no sections: nothing found."""
        out, _err, _data = _ask(tmp_path, ["drone"], capsys, readme="")
        assert "No relevant information found." in out


class TestScoreSection:
    """Section scoring, read from the order `aipass help drone` prints sections in."""

    def test_exact_title_match_beats_containment(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """Title == keyword outranks keyword-in-title, even when it comes later in the file.

        Mutant: `6 if kw == title_lower else 3` -> `3` (no exact-title bonus) -> red.
        """
        out, _err, _data = _ask(tmp_path, ["drone"], capsys, readme="# Drone Commands\n# Drone\n")
        assert out.index("README.md:2-2") < out.index("README.md:1-1")

    def test_body_hit_lines_are_capped(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """30 hit lines score the same as 5 — tables can't drown the earlier intro.

        Equal scores tie to document order, so each section comes first when it comes first in
        the README: a long section scored higher loses the first order, lower loses the second.
        Mutants: `min(hit_lines, 5)` -> `hit_lines` (no cap) -> red at the first order;
        the long section scored lower -> red at the second.
        """
        short = "# Short\n" + "".join(f"drone s{i}\n" for i in range(5))
        long = "# Long\n" + "".join(f"drone l{i}\n" for i in range(30))
        out, _err, _data = _ask(tmp_path, ["drone"], capsys, readme=short + long)
        assert out.index("drone — Short") < out.index("drone — Long")
        out, _err, _data = _ask(tmp_path, ["drone"], capsys, readme=long + short)
        assert out.index("drone — Long") < out.index("drone — Short")

    def test_no_hits_scores_zero(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """A section without any keyword is never printed."""
        out, _err, _data = _ask(tmp_path, ["drone"], capsys, readme="# Other\nnothing here\n")
        assert "Other" not in out
        assert "No relevant information found." in out


class TestSearchReadme:
    """Live README reads and section ranking, through `aipass help` over a README on disk."""

    def test_returns_whole_sections(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """The matched section is printed whole: title, citation and every body line."""
        out, _err, _data = _ask(tmp_path, ["drone"], capsys, readme=_SAMPLE_README)
        assert "drone — Usage  (src/aipass/drone/README.md:5-9)" in out
        assert "Run tasks with drone dispatch." in out
        assert "Drone supports multiple branches." in out

    def test_returns_at_most_two_sections(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """No more than two sections are printed per branch.

        Mutant: `hits[:_MAX_SECTIONS]` -> `hits` -> red.
        """
        readme = "".join(f"# S{i}\ndrone body {i}\n" for i in range(6))
        out, _err, _data = _ask(tmp_path, ["drone"], capsys, readme=readme)
        assert out.count("drone — S") == 2

    def test_no_keyword_match_returns_empty(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """Keyword with no hits in the README prints no section."""
        out, _err, _data = _ask(tmp_path, ["drone", "xyzzy999"], capsys, readme="# Intro\nnothing\n")
        assert "Intro" not in out
        assert "No relevant information found." in out

    def test_handler_returns_none_returns_empty_and_logs(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """An unreadable README prints no section and logs a warning naming the branch."""
        readme_path = tmp_path / "src" / "aipass" / "drone" / "README.md"  # never written
        with ExitStack() as stack:
            stack.enter_context(patch(f"{_HC}.json_handler", autospec=True))
            stack.enter_context(patch(f"{_HC}.list_branches", return_value=["drone"]))
            stack.enter_context(patch(f"{_HC}.get_readme_path", return_value=readme_path))
            stack.enter_context(patch(f"{_RM}.get_readme_path", return_value=readme_path))
            mock_logger = stack.enter_context(patch(f"{_HC}.logger"))
            assert handle_command("help", ["drone"]) is True
        mock_logger.warning.assert_called_once_with("[help_chat] Could not read README for branch %s", "drone")
        assert "No relevant information found." in capsys.readouterr().out

    def test_matching_is_case_insensitive(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """Uppercase text in README must still match a lowercase query keyword.

        Mutant: `line_lower = line.lower()` -> `line_lower = line` -> red.
        """
        out, _err, _data = _ask(tmp_path, ["routing"], capsys, readme="# Intro\nDRONE does ROUTING\n")
        assert "DRONE does ROUTING" in out

    def test_exact_title_section_ranked_first(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """The '# Drone' intro outranks a longer commands section for 'drone'."""
        readme = "# Drone\nThe drone router.\n\n## Commands\n" + "\n".join(f"drone cmd {i}" for i in range(20))
        out, _err, _data = _ask(tmp_path, ["drone"], capsys, readme=readme)
        assert out.index("drone — Drone") < out.index("drone — Commands")


# =============================================================================
# Answer rendering (_format_answer), read through `aipass help`
# =============================================================================


class TestFormatAnswer:
    """Answer rendering — citations, titles, truncation — as `aipass help` prints it."""

    def test_citation_range_format_present(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """Citation must follow the (src/aipass/{branch}/README.md:{start}-{end}) format.

        Mutant: `f"({rel_path}:{sec['start']}-{sec['end']})"` -> `f"({rel_path})"` -> red.
        """
        readme = "# A\nx\n# Drone\ntask-runner\nmore\n\n\nend\n"
        out, _err, _data = _ask(tmp_path, ["drone"], capsys, readme=readme)
        assert "(src/aipass/drone/README.md:3-8)" in out

    def test_branch_and_title_in_output(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """Output must include the branch name and section title."""
        out, _err, _data = _ask(tmp_path, ["drone"], capsys, readme="# Overview\ndrone line\n")
        assert "drone — Overview" in out

    def test_multiple_sections_all_cited(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """Every section must carry its own line-range citation."""
        path = tmp_path / "src" / "aipass" / "flow" / "README.md"
        readme = "# One\nflow a\n\n\n# Two\nflow b\n\n\n\n"
        out, _err, _data = _ask(tmp_path, ["flow"], capsys, readme=readme, branches=["flow"], readme_path=path)
        assert "(src/aipass/flow/README.md:1-4)" in out
        assert "(src/aipass/flow/README.md:5-9)" in out

    def test_fallback_citation_when_src_not_in_path(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """When path lacks 'src', fallback citation must still include branch and range."""
        path = tmp_path / "unusual" / "path" / "drone" / "README.md"
        with patch(f"{_HC}.logger"):
            out, _err, _data = _ask(tmp_path, ["drone"], capsys, readme="# X\ndrone content\n", readme_path=path)
        assert "(src/aipass/drone/README.md:1-2)" in out

    def test_long_section_truncated_with_read_hint(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """Bodies beyond the 25-line cap are cut and point at aipass read.

        Mutant: `if len(body) > _MAX_SECTION_LINES:` -> `if False:` (never truncated) -> red.
        """
        readme = "# Drone\n" + "".join(f"row{i:02d}\n" for i in range(_BODY_CAP + 10))
        out, _err, _data = _ask(tmp_path, ["drone"], capsys, readme=readme)
        assert f"row{_BODY_CAP - 1:02d}" in out
        assert f"row{_BODY_CAP:02d}" not in out
        assert "aipass read drone for the full document" in out

    def test_untitled_section_labeled_intro(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """A preamble section with no heading renders with an (intro) label."""
        out, _err, _data = _ask(tmp_path, ["drone"], capsys, readme="drone preamble text\n")
        assert "drone — (intro)" in out


# =============================================================================
# handle_command
# =============================================================================


class TestHandleCommand:
    """Integration-level tests for handle_command routing and output."""

    def test_returns_false_for_unknown_command(self):
        """Any command other than 'help' must return False immediately."""
        assert handle_command("other", []) is False

    def test_returns_false_for_doctor_command(self):
        """The 'doctor' command must not be handled by this module."""
        assert handle_command("doctor", ["something"]) is False

    def test_command_constant_is_help(self):
        """COMMAND module constant must equal the string 'help'."""
        assert COMMAND == "help"

    def test_no_args_returns_true_and_shows_help(self):
        """handle_command('help', []) must return True and print usage help."""
        with patch("aipass.aipass.apps.modules.help_chat.print_help") as mock_help:
            with patch("aipass.aipass.apps.modules.help_chat.json_handler", autospec=True):
                result = handle_command("help", [])
        assert result is True
        mock_help.assert_called_once()

    def test_info_flag_calls_introspection(self):
        """--info flag triggers print_introspection."""
        with patch("aipass.aipass.apps.modules.help_chat.print_introspection") as mock_intro:
            with patch("aipass.aipass.apps.modules.help_chat.json_handler", autospec=True):
                result = handle_command("help", ["--info"])
        assert result is True
        mock_intro.assert_called_once()

    def test_valid_drone_question_returns_true(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """Mutant: found answer not printed -> red.

        Mutant: readme_map's `return fh.readlines()` -> `return []` (README on disk never read) -> red.
        """
        readme_content = "# Drone\nDrone dispatches tasks to branches.\n"
        readme_path = tmp_path / "src" / "aipass" / "drone" / "README.md"
        result = _call_handle_command_drone_question(readme_content, readme_path)
        assert result is True
        out, _err = capsys.readouterr()
        assert "Drone dispatches tasks to branches." in out

    def test_no_readme_match_still_returns_true(self, capsys: pytest.CaptureFixture[str]):
        """Mutant: no-match notice not printed -> red."""
        assert _call_handle_no_match() is True
        out, _err = capsys.readouterr()
        assert "No relevant information found." in out

    def test_all_stopwords_returns_true_and_calls_error(self, capsys: pytest.CaptureFixture[str]):
        """Mutant: error() for empty keywords dropped -> red."""
        result = _call_handle_all_stopwords()
        assert result is True
        _out, err = capsys.readouterr()
        assert "Could not extract keywords from question" in err

    def test_depth_offer_always_printed(self, tmp_path, capsys: pytest.CaptureFixture[str]):
        """Depth offer lines must appear even when the README cannot be opened.

        Mutant: depth-offer 'aipass read' line dropped -> red.
        """
        readme_path = tmp_path / "src" / "aipass" / "drone" / "README.md"
        _capture_depth_offer_prints(readme_path)
        out, _err = capsys.readouterr()
        assert "aipass read" in out
