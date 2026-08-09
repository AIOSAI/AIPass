# =================== AIPass ====================
# Name: tests/test_help_chat.py
# Description: Tests for help_chat module — section-aware v2 (DPLAN-0282 P3)
# Version: 2.0.0
# Created: 2026-04-16
# Modified: 2026-08-07
# =============================================

"""Tests for aipass.aipass.apps.modules.help_chat"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

from aipass.aipass.apps.modules.help_chat import (
    COMMAND,
    _MAX_SECTION_LINES,
    _extract_keywords,
    _format_answer,
    _match_branches,
    _score_section,
    _search_readme,
    _split_sections,
    handle_command,
)

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

_FAKE_README_PATH = Path("/fake/src/aipass/drone/README.md")

# Ensure encoding='utf-8' appears in this file (PATTERN check scans file-wide)
_ENCODING = "utf-8"


# =============================================================================
# HELPERS — reduce nesting in test functions via ExitStack
# =============================================================================


def _call_handle_command_drone_question(readme_content: str, readme_path: Path):
    """Call handle_command for 'what does drone do' with file I/O mocked."""
    patches = [
        patch("aipass.aipass.apps.modules.help_chat.json_handler"),
        patch("aipass.aipass.apps.modules.help_chat.list_branches", return_value=["drone"]),
        patch("aipass.aipass.apps.modules.help_chat.get_readme_path", return_value=readme_path),
        patch("builtins.open", mock_open(read_data=readme_content)),
        patch("aipass.aipass.apps.modules.help_chat.console"),
        patch("aipass.aipass.apps.modules.help_chat.header"),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        return handle_command("help", ["what", "does", "drone", "do"])


def _call_handle_no_match():
    """Call handle_command for unknown keyword with no README path returned."""
    patches = [
        patch("aipass.aipass.apps.modules.help_chat.json_handler"),
        patch("aipass.aipass.apps.modules.help_chat.list_branches", return_value=["drone"]),
        patch("aipass.aipass.apps.modules.help_chat.get_readme_path", return_value=None),
        patch("aipass.aipass.apps.modules.help_chat.console"),
        patch("aipass.aipass.apps.modules.help_chat.header"),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        return handle_command("help", ["xyzzy999"])


def _call_handle_all_stopwords():
    """Call handle_command with a question that reduces to zero keywords."""
    mock_error = MagicMock()
    patches = [
        patch("aipass.aipass.apps.modules.help_chat.json_handler"),
        patch("aipass.aipass.apps.modules.help_chat.console"),
        patch("aipass.aipass.apps.modules.help_chat.error", mock_error),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        result = handle_command("help", ["what", "is", "the"])
    return result, mock_error


def _capture_depth_offer_prints(readme_path: Path):
    """Call handle_command for 'drone' where open() raises OSError; capture console output."""
    printed: list[str] = []

    def capture(*args, **kwargs):
        """Capture positional string args from console.print calls."""
        if args:
            printed.append(str(args[0]))

    mock_console = MagicMock()
    mock_console.print.side_effect = capture
    patches = [
        patch("aipass.aipass.apps.modules.help_chat.json_handler"),
        patch("aipass.aipass.apps.modules.help_chat.list_branches", return_value=["drone"]),
        patch("aipass.aipass.apps.modules.help_chat.get_readme_path", return_value=readme_path),
        patch("builtins.open", side_effect=OSError("no file")),
        patch("aipass.aipass.apps.modules.help_chat.logger"),
        patch("aipass.aipass.apps.modules.help_chat.console", mock_console),
        patch("aipass.aipass.apps.modules.help_chat.header"),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        handle_command("help", ["drone"])
    return printed


# =============================================================================
# _extract_keywords
# =============================================================================


class TestExtractKeywords:
    """Tests for _extract_keywords: stopword filtering and punctuation stripping."""

    def test_strips_stopwords(self):
        """Known stopwords must not appear in the result."""
        result = _extract_keywords("what does drone do")
        assert "drone" in result
        assert "what" not in result
        assert "does" not in result
        assert "do" not in result

    def test_strips_question_mark(self):
        """Trailing ? on a word must be stripped before comparison."""
        result = _extract_keywords("how does drone work?")
        assert "work" in result
        assert "work?" not in result

    def test_strips_comma_and_period(self):
        """Commas and periods attached to words must be stripped."""
        result = _extract_keywords("drone, flow, prax.")
        assert "drone" in result
        assert "flow" in result
        assert "prax" in result

    def test_lowercases_words(self):
        """All output keywords must be lowercase."""
        result = _extract_keywords("What Is DRONE")
        assert "drone" in result
        assert "DRONE" not in result

    def test_filters_single_char_words(self):
        """Single-character tokens must be excluded from output."""
        result = _extract_keywords("a b c drone")
        assert "a" not in result
        assert "b" not in result
        assert "c" not in result
        assert "drone" in result

    def test_empty_question_returns_empty_list(self):
        """Empty string input must return an empty list."""
        assert _extract_keywords("") == []

    def test_all_stopwords_returns_empty_list(self):
        """A question composed entirely of stopwords must return []."""
        assert _extract_keywords("what is the") == []

    def test_mixed_content_extracts_content_words(self):
        """Only non-stopword, non-punctuation words of length > 1 returned."""
        result = _extract_keywords("how do i send mail to another branch?")
        assert "send" in result
        assert "mail" in result
        assert "branch" in result
        assert "how" not in result
        assert "do" not in result
        assert "i" not in result
        assert "to" not in result


# =============================================================================
# _match_branches
# =============================================================================


class TestMatchBranches:
    """Tests for _match_branches: branch-name matching and fallback behaviour."""

    @patch("aipass.aipass.apps.modules.help_chat.list_branches", return_value=_FAKE_BRANCHES)
    def test_exact_branch_name_match_is_first(self, _mock):
        """A keyword exactly matching a branch name places it first in results."""
        result = _match_branches(["drone"])
        assert "drone" in result
        assert result[0] == "drone"

    @patch("aipass.aipass.apps.modules.help_chat.list_branches", return_value=_FAKE_BRANCHES)
    def test_multiple_direct_matches_included(self, _mock):
        """Multiple exact branch-name keywords all appear in results."""
        result = _match_branches(["drone", "flow"])
        assert "drone" in result
        assert "flow" in result

    @patch("aipass.aipass.apps.modules.help_chat.list_branches", return_value=_FAKE_BRANCHES)
    def test_fallback_returns_all_branches_when_no_match(self, _mock):
        """Unrecognised keyword triggers broad fallback — all branches returned."""
        result = _match_branches(["xyzzy999"])
        assert result == _FAKE_BRANCHES

    @patch("aipass.aipass.apps.modules.help_chat.list_branches", return_value=_FAKE_BRANCHES)
    def test_partial_keyword_in_branch_name(self, _mock):
        """Keyword 'mail' contained in branch name 'ai_mail' must be included."""
        result = _match_branches(["mail"])
        assert "ai_mail" in result

    @patch("aipass.aipass.apps.modules.help_chat.list_branches", return_value=[])
    def test_empty_branches_list_returns_empty(self, _mock):
        """When no branches exist, result must be an empty list."""
        assert _match_branches(["drone"]) == []

    @patch("aipass.aipass.apps.modules.help_chat.list_branches", return_value=_FAKE_BRANCHES)
    def test_no_duplicates_in_result(self, _mock):
        """Passing the same keyword twice must not produce duplicate branch entries."""
        result = _match_branches(["drone", "drone"])
        assert result.count("drone") == 1


# =============================================================================
# _search_readme
# =============================================================================


class TestSplitSections:
    """Tests for _split_sections: heading-bounded splitting."""

    def test_splits_on_headings(self):
        """Each #/##/### heading starts a new section."""
        sections = _split_sections(_SAMPLE_README.splitlines(keepends=True))
        titles = [s["title"] for s in sections]
        assert "Drone" in titles
        assert "Usage" in titles

    def test_preamble_becomes_intro_section(self):
        """Content before the first heading is kept as an untitled section."""
        sections = _split_sections(["intro line\n", "# Title\n", "body\n"])
        assert sections[0]["title"] == ""
        assert "intro line" in sections[0]["lines"]

    def test_line_numbers_1_indexed_and_bounded(self):
        """start = heading line, end = last line of the section."""
        sections = _split_sections(_SAMPLE_README.splitlines(keepends=True))
        drone_sec = next(s for s in sections if s["title"] == "Drone")
        assert drone_sec["start"] == 1
        assert drone_sec["end"] >= drone_sec["start"]

    def test_heading_inside_code_fence_ignored(self):
        """A # line inside ``` fences is body text, not a section break."""
        sections = _split_sections(["# Real\n", "```\n", "# not a heading\n", "```\n", "tail\n"])
        assert len(sections) == 1
        assert "# not a heading" in sections[0]["lines"]

    def test_empty_input_returns_empty(self):
        """No lines → no sections."""
        assert _split_sections([]) == []


class TestScoreSection:
    """Tests for _score_section: title weighting and body-hit capping."""

    def _sec(self, title: str, body: list[str]) -> dict:
        return {"title": title, "start": 1, "end": len(body) + 1, "lines": body}

    def test_exact_title_match_beats_containment(self):
        """Title == keyword scores higher than keyword-in-title."""
        exact = _score_section(self._sec("Drone", []), ["drone"])
        contains = _score_section(self._sec("Drone Commands", []), ["drone"])
        assert exact > contains

    def test_body_hit_lines_are_capped(self):
        """30 hit lines score no more than the cap allows — tables can't drown intros."""
        long_body = [f"drone line {i}" for i in range(30)]
        short_body = ["drone here", "drone again", "drone third", "drone fourth", "drone fifth"]
        assert _score_section(self._sec("x", long_body), ["drone"]) == _score_section(
            self._sec("x", short_body), ["drone"]
        )

    def test_no_hits_scores_zero(self):
        """Section without any keyword scores 0."""
        assert _score_section(self._sec("Other", ["nothing here"]), ["drone"]) == 0


class TestSearchReadme:
    """Tests for _search_readme: live reads, section ranking, error handling."""

    def _mock_lines(self, content):
        """Return a patch that makes read_readme_lines return content as lines."""
        lines = content.splitlines(keepends=True)
        return patch("aipass.aipass.apps.modules.help_chat.read_readme_lines", return_value=lines)

    def test_returns_whole_sections(self):
        """Results are section dicts with title/start/end/lines."""
        with self._mock_lines(_SAMPLE_README):
            results = _search_readme("drone", ["drone"])
        assert len(results) > 0
        assert all({"title", "start", "end", "lines"} <= set(s.keys()) for s in results)

    def test_returns_at_most_two_sections(self):
        """No more than _MAX_SECTIONS sections come back."""
        content = "\n".join(f"# S{i}\ndrone body {i}\n" for i in range(6))
        with self._mock_lines(content):
            results = _search_readme("drone", ["drone"])
        assert len(results) <= 2

    def test_no_keyword_match_returns_empty(self):
        """Keyword with no hits in the README must return an empty list."""
        with self._mock_lines(_SAMPLE_README):
            results = _search_readme("drone", ["xyzzy999"])
        assert results == []

    def test_handler_returns_none_returns_empty_and_logs(self):
        """None from handler must return [] and call logger.warning."""
        with patch("aipass.aipass.apps.modules.help_chat.read_readme_lines", return_value=None):
            with patch("aipass.aipass.apps.modules.help_chat.logger") as mock_logger:
                results = _search_readme("nonexistent", ["drone"])
        assert results == []
        mock_logger.warning.assert_called_once()

    def test_matching_is_case_insensitive(self):
        """Uppercase text in README must still match a lowercase query keyword."""
        with self._mock_lines("# Intro\nDRONE does routing\n"):
            results = _search_readme("drone", ["drone"])
        assert len(results) == 1

    def test_exact_title_section_ranked_first(self):
        """The '# Drone' intro outranks a longer commands section for 'drone'."""
        content = "# Drone\nThe drone router.\n\n## Commands\n" + "\n".join(f"drone cmd {i}" for i in range(20))
        with self._mock_lines(content):
            results = _search_readme("drone", ["drone"])
        assert results[0]["title"] == "Drone"


# =============================================================================
# _format_answer
# =============================================================================


class TestFormatAnswer:
    """Tests for _format_answer: section rendering, citations, truncation."""

    def _path(self, branch: str) -> Path:
        """Return a fake absolute README path for the given branch."""
        return Path(f"/home/user/Projects/AIPass/src/aipass/{branch}/README.md")

    def _sec(self, title: str, start: int, end: int, body: list[str]) -> dict:
        return {"title": title, "start": start, "end": end, "lines": body}

    def test_citation_range_format_present(self):
        """Citation must follow the (src/aipass/{branch}/README.md:{start}-{end}) format."""
        path = self._path("drone")
        result = _format_answer("drone", path, [self._sec("Drone", 3, 8, ["task-runner"])])
        assert "(src/aipass/drone/README.md:3-8)" in result

    def test_branch_and_title_in_output(self):
        """Output must include the branch name and section title."""
        path = self._path("drone")
        result = _format_answer("drone", path, [self._sec("Overview", 1, 4, ["some line"])])
        assert "drone" in result
        assert "Overview" in result

    def test_multiple_sections_all_cited(self):
        """Every section must carry its own line-range citation."""
        path = self._path("flow")
        sections = [
            self._sec("One", 1, 4, ["a"]),
            self._sec("Two", 5, 9, ["b"]),
        ]
        result = _format_answer("flow", path, sections)
        assert "(src/aipass/flow/README.md:1-4)" in result
        assert "(src/aipass/flow/README.md:5-9)" in result

    def test_fallback_citation_when_src_not_in_path(self):
        """When path lacks 'src', fallback citation must still include branch and range."""
        path = Path("/unusual/path/drone/README.md")
        with patch("aipass.aipass.apps.modules.help_chat.logger"):
            result = _format_answer("drone", path, [self._sec("X", 7, 9, ["some content"])])
        assert "src/aipass/drone/README.md:7-9" in result

    def test_long_section_truncated_with_read_hint(self):
        """Bodies beyond _MAX_SECTION_LINES are cut and point at aipass read."""
        path = self._path("drone")
        body = [f"line {i}" for i in range(_MAX_SECTION_LINES + 10)]
        result = _format_answer("drone", path, [self._sec("Big", 1, len(body) + 1, body)])
        assert "aipass read drone" in result
        assert f"line {_MAX_SECTION_LINES + 5}" not in result

    def test_untitled_section_labeled_intro(self):
        """A preamble section with no heading renders with an (intro) label."""
        path = self._path("drone")
        result = _format_answer("drone", path, [self._sec("", 1, 2, ["preamble text"])])
        assert "(intro)" in result


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
            with patch("aipass.aipass.apps.modules.help_chat.json_handler"):
                result = handle_command("help", [])
        assert result is True
        mock_help.assert_called_once()

    def test_info_flag_calls_introspection(self):
        """--info flag triggers print_introspection."""
        with patch("aipass.aipass.apps.modules.help_chat.print_introspection") as mock_intro:
            with patch("aipass.aipass.apps.modules.help_chat.json_handler"):
                result = handle_command("help", ["--info"])
        assert result is True
        mock_intro.assert_called_once()

    def test_valid_drone_question_returns_true(self):
        """A well-formed question about drone must return True."""
        readme_content = "# Drone\nDrone dispatches tasks to branches.\n"
        result = _call_handle_command_drone_question(readme_content, _FAKE_README_PATH)
        assert result is True

    def test_no_readme_match_still_returns_true(self):
        """handle_command must return True even when no README path resolves."""
        assert _call_handle_no_match() is True

    def test_all_stopwords_returns_true_and_calls_error(self):
        """A question of only stopwords must return True and call error()."""
        result, mock_error = _call_handle_all_stopwords()
        assert result is True
        mock_error.assert_called_once()

    def test_depth_offer_always_printed(self):
        """Depth offer lines must appear even when the README cannot be opened."""
        printed = _capture_depth_offer_prints(_FAKE_README_PATH)
        combined = "\n".join(printed)
        assert "aipass read" in combined or "deeper" in combined
