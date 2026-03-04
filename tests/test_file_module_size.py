"""
Tests for the file-module-size seedgo plugin.

Covers:
  - Files under 400 lines pass
  - Files over 400 lines fail with WARNING severity
  - Blank lines, comments, and docstrings are excluded from count
  - Configurable max_lines threshold
  - Fix hints suggest logical split points
  - Handles syntax errors and empty files gracefully
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from seedgo.plugins.file_module_size import PLUGIN_NAME, check


class TestFileModuleSizePass:
    """Files under the size limit should pass."""

    def test_small_file_passes(self, tmp_path: Path):
        """File with 10 code lines passes."""
        test_file = tmp_path / "test.py"
        test_file.write_text(
            textwrap.dedent("""\
            def add(a, b):
                return a + b

            def subtract(a, b):
                return a - b
            """)
        )

        result = check(str(test_file))
        assert result.plugin == PLUGIN_NAME
        assert result.passed is True

    def test_exactly_400_lines_passes(self, tmp_path: Path):
        """File with exactly 400 code lines passes."""
        test_file = tmp_path / "test.py"
        # Generate exactly 400 lines of code
        lines = ["def func():", "    pass", ""]
        code = "\n".join(lines * 200)  # 200 functions * 2 code lines = 400
        test_file.write_text(code)

        result = check(str(test_file))
        assert result.passed is True
        assert result.metadata["code_lines"] == 400

    def test_blank_lines_not_counted(self, tmp_path: Path):
        """Blank lines are excluded from code line count."""
        test_file = tmp_path / "test.py"
        test_file.write_text(
            textwrap.dedent("""\
            def add(a, b):
                return a + b


            def subtract(a, b):
                return a - b


            """)
        )

        result = check(str(test_file))
        # Should count 4 code lines (2 per function), not 8
        assert result.metadata["code_lines"] == 4

    def test_comments_not_counted(self, tmp_path: Path):
        """Comment lines are excluded from code line count."""
        test_file = tmp_path / "test.py"
        test_file.write_text(
            textwrap.dedent("""\
            # This is a comment
            # Another comment
            def add(a, b):
                # Inline comment
                return a + b
            # More comments
            # Even more
            """)
        )

        result = check(str(test_file))
        # Should count 2 code lines (def and return), not 7
        assert result.metadata["code_lines"] == 2

    def test_docstrings_not_counted(self, tmp_path: Path):
        """Docstrings are excluded from code line count."""
        test_file = tmp_path / "test.py"
        test_file.write_text(
            textwrap.dedent('''\
            """
            Module docstring.
            This spans multiple lines.
            """

            def add(a, b):
                """
                Function docstring.
                Also multiple lines.
                """
                return a + b

            class Calculator:
                """Class docstring."""

                def multiply(self, a, b):
                    """Method docstring."""
                    return a * b
            ''')
        )

        result = check(str(test_file))
        # Should count only actual code lines, not docstrings
        # Code lines: def add, return, class Calculator, def multiply, return = 5
        assert result.metadata["code_lines"] == 5

    def test_empty_file_passes(self, tmp_path: Path):
        """Empty file passes."""
        test_file = tmp_path / "test.py"
        test_file.write_text("")

        result = check(str(test_file))
        assert result.passed is True


class TestFileModuleSizeFail:
    """Files over the size limit should fail."""

    def test_file_over_400_lines_fails(self, tmp_path: Path):
        """File with 401 code lines fails."""
        test_file = tmp_path / "test.py"
        # Generate 401 lines of code
        lines = []
        for i in range(401):
            lines.append(f"x{i} = {i}")
        test_file.write_text("\n".join(lines))

        result = check(str(test_file))
        assert result.passed is False
        assert result.metadata["code_lines"] == 401

        violation = result.checks[0]
        assert violation.name == "file-size"
        assert violation.severity.value == "warning"  # WARNING, not ERROR
        assert "401" in violation.message
        assert "400" in violation.message

    def test_large_file_with_comments_and_blanks(self, tmp_path: Path):
        """File with 500 total lines but 401 code lines fails."""
        test_file = tmp_path / "test.py"
        lines = []
        for i in range(401):
            lines.append(f"x{i} = {i}")
            if i % 10 == 0:
                lines.append("")  # Add blank lines
                lines.append(f"# Comment {i}")  # Add comments
        test_file.write_text("\n".join(lines))

        result = check(str(test_file))
        assert result.passed is False
        # Should count 401 code lines, not the total with blanks and comments
        assert result.metadata["code_lines"] == 401

    def test_overage_reported(self, tmp_path: Path):
        """Violation message includes overage amount."""
        test_file = tmp_path / "test.py"
        # Generate 450 lines of code (50 over limit)
        lines = [f"x{i} = {i}" for i in range(450)]
        test_file.write_text("\n".join(lines))

        result = check(str(test_file))
        violation = result.checks[0]
        assert "50 lines" in violation.message or "50" in violation.message


class TestFileModuleSizeCustomLimit:
    """Custom max_lines config should be respected."""

    def test_custom_limit_200(self, tmp_path: Path):
        """File with 150 lines passes with custom limit of 200."""
        test_file = tmp_path / "test.py"
        lines = [f"x{i} = {i}" for i in range(150)]
        test_file.write_text("\n".join(lines))

        result = check(str(test_file), config={"max_lines": 200})
        assert result.passed is True
        assert result.metadata["code_lines"] == 150
        assert result.metadata["max_lines"] == 200

    def test_custom_limit_exceeded(self, tmp_path: Path):
        """File with 250 lines fails with custom limit of 200."""
        test_file = tmp_path / "test.py"
        lines = [f"x{i} = {i}" for i in range(250)]
        test_file.write_text("\n".join(lines))

        result = check(str(test_file), config={"max_lines": 200})
        assert result.passed is False
        assert result.metadata["code_lines"] == 250
        assert result.metadata["max_lines"] == 200


class TestFileModuleSizeFixHints:
    """Fix hints should provide actionable suggestions."""

    def test_fix_hint_for_multiple_classes(self, tmp_path: Path):
        """Large file with multiple classes suggests splitting classes."""
        test_file = tmp_path / "test.py"
        code = []
        for i in range(5):
            code.append(f"class Class{i}:")
            for j in range(85):  # 85 lines per class = 425 total
                code.append(f"    def method{j}(self): return {j}")
        test_file.write_text("\n".join(code))

        result = check(str(test_file))
        assert result.passed is False
        violation = result.checks[0]
        assert "split" in violation.fix_hint.lower() or "class" in violation.fix_hint.lower()

    def test_fix_hint_for_many_functions(self, tmp_path: Path):
        """Large file with many functions suggests grouping."""
        test_file = tmp_path / "test.py"
        code = []
        for i in range(401):
            code.append(f"def func{i}(): return {i}")
        test_file.write_text("\n".join(code))

        result = check(str(test_file))
        assert result.passed is False
        violation = result.checks[0]
        # Should suggest grouping functions
        assert "function" in violation.fix_hint.lower() or "group" in violation.fix_hint.lower()

    def test_fix_hint_generic(self, tmp_path: Path):
        """Fix hint provides generic suggestion when no specific pattern found."""
        test_file = tmp_path / "test.py"
        # Just a lot of assignments (no classes or functions)
        code = [f"x{i} = {i}" for i in range(401)]
        test_file.write_text("\n".join(code))

        result = check(str(test_file))
        violation = result.checks[0]
        # Should have some helpful suggestion
        assert len(violation.fix_hint) > 0
        assert "module" in violation.fix_hint.lower() or "break" in violation.fix_hint.lower()


class TestFileModuleSizeEdgeCases:
    """Edge cases and error handling."""

    def test_file_with_syntax_error(self, tmp_path: Path):
        """File with syntax error falls back to simple line counting."""
        test_file = tmp_path / "test.py"
        # Syntax error but with many lines
        lines = ["def broken(:"] * 401
        test_file.write_text("\n".join(lines))

        result = check(str(test_file))
        # Should still count lines even with syntax error
        assert result.passed is False

    def test_file_read_error(self, tmp_path: Path):
        """Non-existent file is skipped gracefully."""
        result = check(str(tmp_path / "nonexistent.py"))
        assert result.passed is True
        assert result.metadata.get("skipped") is True
        assert result.metadata.get("reason") == "file_read_error"

    def test_metadata_includes_counts(self, tmp_path: Path):
        """Metadata includes total_lines, code_lines, and max_lines."""
        test_file = tmp_path / "test.py"
        test_file.write_text(
            textwrap.dedent("""\
            # Comment

            def add(a, b):
                return a + b

            """)
        )

        result = check(str(test_file))
        assert "total_lines" in result.metadata
        assert "code_lines" in result.metadata
        assert "max_lines" in result.metadata
        assert result.metadata["total_lines"] == 5
        assert result.metadata["code_lines"] == 2
        assert result.metadata["max_lines"] == 400
