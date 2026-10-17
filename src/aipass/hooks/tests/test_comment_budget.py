# =================== AIPass ====================
# Name: test_comment_budget.py
# Version: 1.0.0
# Description: Tests for the comment budget: counter, PostToolUse handler, comments verb
# Branch: hooks
# Created: 2026-10-16
# Modified: 2026-10-16
# =============================================

"""Tests for apps/handlers/lifecycle/comment_budget.py, apps/modules/comment_scan.py and apps/modules/comments.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(documentation) — that the three files' functions carry docstrings
# seedgo: no-test-needed(stdlib) — tokenize's own token stream and append_jsonl's rotation

import json

import pytest

from aipass.hooks.apps.handlers.lifecycle import comment_budget
from aipass.hooks.apps.modules import comment_scan, comments


def _code(count: int) -> str:
    return "".join(f"x{n} = {n}\n" for n in range(count))


def _hashes(count: int) -> str:
    return "".join(f"# note {n}\n" for n in range(count))


def _edit(path, old: str, new: str, tool: str = "Edit") -> dict:
    return {
        "tool_name": tool,
        "session_id": "seat-one",
        "tool_input": {"file_path": str(path), "old_string": old, "new_string": new},
    }


def _write(path) -> dict:
    return {"tool_name": "Write", "session_id": "seat-one", "tool_input": {"file_path": str(path)}}


def _answer(result: dict) -> dict:
    return json.loads(result["stdout"]) if result["stdout"] else {}


def _rows() -> list[dict]:
    return comment_budget.ledger_rows()


class TestPythonCounter:
    def test_the_aipass_header_is_neither_body_nor_comment(self):
        text = "# ==== AIPass ====\n# Name: x.py\n# =====\n\n" + _code(10)
        scan = comment_scan.scan(text, "python")
        assert (scan.body, scan.comments) == (10, 0)

    def test_a_header_lower_in_the_file_is_counted(self):
        scan = comment_scan.scan(_code(10) + "# ==== AIPass ====\n# Name: x.py\n", "python")
        assert (scan.body, scan.comments) == (12, 2)

    def test_a_one_line_docstring_is_free_and_a_three_line_one_costs_two(self):
        one = comment_scan.scan('def f():\n    """One line."""\n    return 1\n', "python")
        three = comment_scan.scan('def f():\n    """Line one.\n\n    Line three.\n    """\n    return 1\n', "python")
        assert one.comments == 0
        assert (three.comments, three.runs) == (2, [(4, 5)])

    def test_module_and_class_docstrings_count_past_their_first_line(self):
        text = '"""Module.\n\nMore.\n"""\n\n\nclass A:\n    """Cls.\n    more\n    """\n'
        assert comment_scan.scan(text, "python").comments == 4

    def test_a_string_that_is_a_value_is_not_a_docstring(self):
        assert comment_scan.scan('X = """a\nb\nc"""\n', "python").comments == 0

    def test_directive_lines_are_free(self):
        text = "#!/usr/bin/env python\n# -*- coding: utf-8 -*-\n# noqa: E501\n# type: ignore\n# pyright: basic\n"
        text += "# pragma: no cover\n# fmt: off\n# ruff: noqa\n# pylint: disable=x\n# a real comment\n"
        assert comment_scan.scan(text, "python").comments == 1

    def test_a_trailing_comment_after_code_is_not_counted(self):
        assert comment_scan.scan("x = 1  # why\n", "python").comments == 0

    def test_a_fragment_the_tokenizer_refuses_still_counts_hash_lines(self):
        fragment = '    # first\n    s = """open\n    # second\n'
        assert comment_scan.scan(fragment, "python").comments == 2


class TestCStyleCounter:
    def test_a_starless_line_inside_a_block_counts_and_a_star_line_outside_does_not(self):
        text = "/* opens\nplain words inside\n*/\nconst a = 1;\n* b;\n"
        scan = comment_scan.scan(text, "c")
        assert (scan.comments, scan.runs) == (3, [(1, 3)])

    def test_slash_lines_and_jsx_blocks_count_and_lint_directives_are_free(self):
        text = "// why\n{/* jsx */}\n// eslint-disable-next-line\n// @ts-expect-error\n/* eslint-disable */\nx();\n"
        assert comment_scan.scan(text, "c").comments == 2

    def test_shell_hash_lines_count_and_the_shebang_is_free(self):
        assert comment_scan.scan("#!/bin/bash\n# why\necho hi\n", "shell").comments == 1


class TestBudgetBoundary:
    def test_exactly_ten_percent_is_not_over_and_one_line_more_is(self):
        at = comment_scan.scan(_code(90) + _hashes(10), "python")
        past = comment_scan.scan(_code(89) + _hashes(11), "python")
        assert (at.body, at.comments, at.over()) == (100, 10, 0)
        assert past.over() == 1

    def test_the_budget_floors_a_fractional_allowance(self):
        assert comment_scan.scan(_code(18) + _hashes(1), "python").over() == 0
        assert comment_scan.scan(_code(17) + _hashes(2), "python").over() == 1

    def test_runs_come_longest_first_and_three_at_most(self):
        text = _hashes(1) + "x = 1\n" + _hashes(3) + "x = 2\n" + _hashes(2) + "x = 3\n" + _hashes(4) + "x = 4\n"
        assert comment_scan.scan(text, "python").heaviest() == [(10, 13), (3, 5), (7, 8)]

    def test_an_unjudged_suffix_has_no_kind(self):
        assert comment_scan.kind_of("notes.md") is None
        assert comment_scan.kind_of("App.TSX") == "c"


class TestHandler:
    def test_an_edit_adding_comments_reports_the_count_added(self, tmp_path):
        path = tmp_path / "mod.py"
        path.write_text(_code(20), encoding="utf-8")
        _answer(comment_budget.handle(_edit(path, "x0 = 0\n", "x0 = 0\n")))
        path.write_text(_hashes(5) + _code(20), encoding="utf-8")
        answer = _answer(comment_budget.handle(_edit(path, "x0 = 0\n", _hashes(5) + "x0 = 0\n")))
        assert _rows()[-1]["added"] == 5
        assert "This edit added 5." in answer["hookSpecificOutput"]["additionalContext"]

    def test_a_multiedit_that_removes_comments_says_removed(self, tmp_path):
        path = tmp_path / "mod.py"
        path.write_text(_hashes(6) + _code(10), encoding="utf-8")
        data = _edit(path, "", "", tool="MultiEdit")
        data["tool_input"]["edits"] = [
            {"old_string": _hashes(3), "new_string": ""},
            {"old_string": "", "new_string": ""},
        ]
        context = _answer(comment_budget.handle(data))["hookSpecificOutput"]["additionalContext"]
        assert "This edit removed 3." in context

    def test_a_first_write_has_no_added_and_a_second_measures_from_the_ledger(self, tmp_path):
        path = tmp_path / "mod.py"
        path.write_text(_hashes(1) + _code(20), encoding="utf-8")
        comment_budget.handle(_write(path))
        path.write_text(_hashes(4) + _code(20), encoding="utf-8")
        comment_budget.handle(_write(path))
        assert [row["added"] for row in _rows()] == [None, 3]

    def test_over_budget_answers_live_numbers_under_700_characters(self, tmp_path):
        path = tmp_path / "PhoneApp.tsx"
        path.write_text("// c\n" * 30 + "x();\n" * 70, encoding="utf-8")
        answer = _answer(comment_budget.handle(_write(path)))
        context = answer["hookSpecificOutput"]["additionalContext"]
        assert context.startswith(
            "[COMMENTS] PhoneApp.tsx is over the comment budget: "
            "30 of 100 lines are comments (30%, budget 10%, 20 over)."
        )
        assert "Heaviest runs: L1-30 (30)." in context
        assert len(context) < 700

    def test_under_budget_answers_the_statusline_only(self, tmp_path):
        path = tmp_path / "mod.py"
        path.write_text(_hashes(1) + _code(24), encoding="utf-8")
        answer = _answer(comment_budget.handle(_write(path)))
        assert answer == {"systemMessage": "[comments] mod.py 4% ok"}

    def test_a_file_at_exactly_the_budget_answers_ok(self, tmp_path):
        path = tmp_path / "mod.py"
        path.write_text(_hashes(2) + _code(18), encoding="utf-8")
        assert _answer(comment_budget.handle(_write(path))) == {"systemMessage": "[comments] mod.py 10% ok"}

    def test_a_scratch_path_answers_the_skip_and_writes_no_row(self, tmp_path):
        path = tmp_path / "docs.local" / "draft.py"
        path.parent.mkdir()
        path.write_text(_hashes(9) + _code(1), encoding="utf-8")
        answer = _answer(comment_budget.handle(_write(path)))
        assert answer == {"systemMessage": "[comments] skipped: docs.local is scratch"}
        assert _rows() == []

    def test_an_unjudged_kind_is_silent_and_writes_no_row(self, tmp_path):
        path = tmp_path / "notes.md"
        path.write_text("# heading\n", encoding="utf-8")
        assert comment_budget.handle(_write(path)) == {"stdout": "", "exit_code": 0}
        assert _rows() == []

    def test_the_ledger_row_carries_the_judged_edit(self, tmp_path):
        path = tmp_path / "mod.py"
        path.write_text(_hashes(3) + _code(17), encoding="utf-8")
        comment_budget.handle(_edit(path, "a", "b"))
        row = _rows()[-1]
        assert set(row) == {"time", "seat", "tool", "file", "body", "comments", "share", "over", "added"}
        expected = {"seat": "seat-one", "tool": "Edit", "body": 20, "comments": 3, "share": 0.15, "over": 1, "added": 0}
        assert {key: row[key] for key in expected} == expected
        assert row["file"] == str(path)


class TestCommentsVerb:
    def test_the_trend_ends_with_first_and_latest_share(self, tmp_path, capsys):
        path = tmp_path / "mod.py"
        for hashes in (4, 2):
            path.write_text(_hashes(hashes) + _code(16), encoding="utf-8")
            comment_budget.handle(_write(path))
        assert comments.handle_command("comments", ["--file", str(path)])
        out, _ = capsys.readouterr()
        assert out.strip().splitlines()[-1] == "first 20% → latest 11%"

    def test_over_lists_only_files_whose_latest_row_is_over(self, tmp_path, capsys):
        cured, heavy = tmp_path / "cured.py", tmp_path / "heavy.py"
        for path, hashes in ((cured, 9), (heavy, 9), (cured, 0)):
            path.write_text(_hashes(hashes) + _code(10), encoding="utf-8")
            comment_budget.handle(_write(path))
        comments.handle_command("comments", ["--over"])
        out, _ = capsys.readouterr()
        assert "heavy.py" in out
        assert "cured.py" not in out

    def test_a_tree_scan_sorts_worst_first_and_totals(self, tmp_path, capsys):
        (tmp_path / "light.py").write_text(_code(10), encoding="utf-8")
        (tmp_path / "heavy.ts").write_text("// c\n" * 5 + "x();\n" * 5, encoding="utf-8")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "dep.js").write_text("// c\n", encoding="utf-8")
        comments.handle_command("comments", [str(tmp_path)])
        lines = capsys.readouterr()[0].strip().splitlines()
        assert lines[0].endswith("heavy.ts")
        assert lines[1].endswith("light.py")
        assert lines[-1] == "files 2, over budget 1, share 25% (5 of 20 lines)"

    def test_a_relative_path_resolves_from_the_caller_not_the_branch(self, tmp_path, monkeypatch, capsys):
        (tmp_path / "mine.py").write_text(_hashes(1) + _code(9), encoding="utf-8")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))
        assert comments.handle_command("comments", ["mine.py"])
        assert "1 of 10 lines are comments (10%), 0 over" in capsys.readouterr()[0]

    def test_an_unknown_form_exits_one_on_stderr(self, capsys):
        with pytest.raises(SystemExit) as stop:
            comments.handle_command("comments", ["--bogus"])
        assert stop.value.code == 1
        assert "Unknown form: --bogus" in capsys.readouterr()[1]
