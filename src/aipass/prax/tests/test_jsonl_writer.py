# =================== AIPass ====================
# Name: test_jsonl_writer.py
# Description: Tests for PRAX JSONL writer with rotation
# Version: 1.1.0
# Created: 2026-07-10
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/logging/jsonl_writer.py, exported via apps/modules/logger.py."""

# Tests for the JSONL writer — append_jsonl with size-based rotation.
#
# Tests verify: basic append, auto-rotation at size cap, backup creation,
# directory auto-creation, and the package-level export.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(error_handling) — _rotate_with_backup unlinking when the rename fails, covered by that row
# seedgo: no-test-needed(error_handling) — _unlink_safe's warning when the unlink fails, covered by that row
# seedgo: no-test-needed(error_handling) — _maybe_rotate skipping rotation when the stat fails, covered by that row
# seedgo: no-test-needed(json_structure) — append_jsonl's log_operation("jsonl_append") record, covered by that row
# seedgo: no-test-needed(constant) — rotation above the JSONL_MAX_BYTES default; only the size under it is tested

import json
import sys


def _get_append_jsonl():
    """Import append_jsonl after conftest mocks are active."""
    mod_name = "aipass.prax.apps.modules.logger"
    sys.modules.pop(mod_name, None)
    from aipass.prax.apps.modules.logger import append_jsonl

    return append_jsonl


class TestAppendJsonl:
    """Core append behavior."""

    def test_creates_file_and_appends(self, tmp_path):
        """Verify a new file is created and data appended as JSON line."""
        append_jsonl = _get_append_jsonl()
        target = tmp_path / "test.jsonl"

        append_jsonl(target, {"key": "value"})

        assert target.exists()
        lines = target.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0]) == {"key": "value"}

    def test_appends_multiple_lines(self, tmp_path):
        """Verify successive appends produce multiple JSON lines."""
        append_jsonl = _get_append_jsonl()
        target = tmp_path / "test.jsonl"

        append_jsonl(target, {"n": 1})
        append_jsonl(target, {"n": 2})
        append_jsonl(target, {"n": 3})

        lines = target.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3
        assert json.loads(lines[2])["n"] == 3

    def test_creates_parent_directories(self, tmp_path):
        """Verify missing parent directories are auto-created."""
        append_jsonl = _get_append_jsonl()
        target = tmp_path / "deep" / "nested" / "dir" / "test.jsonl"

        append_jsonl(target, {"created": True})

        assert target.exists()
        assert json.loads(target.read_text(encoding="utf-8").strip())["created"] is True

    def test_handles_non_serializable_with_default_str(self, tmp_path):
        """Verify non-serializable types fall back to str()."""
        append_jsonl = _get_append_jsonl()
        target = tmp_path / "test.jsonl"
        test_path = tmp_path / "some" / "path"

        append_jsonl(target, {"path": test_path})

        line = json.loads(target.read_text(encoding="utf-8").strip())
        assert line["path"] == str(test_path)


class TestRotation:
    """Size-based rotation behavior."""

    def test_rotates_when_exceeding_max_bytes(self, tmp_path):
        """Verify file is rotated to .1 when it exceeds max_bytes."""
        append_jsonl = _get_append_jsonl()
        target = tmp_path / "test.jsonl"

        target.write_text("x" * 500 + "\n", encoding="utf-8")

        append_jsonl(target, {"after": "rotation"}, max_bytes=400)

        backup = tmp_path / "test.jsonl.1"
        assert backup.exists()
        assert "x" * 500 in backup.read_text(encoding="utf-8")

        content = target.read_text(encoding="utf-8").strip()
        assert json.loads(content)["after"] == "rotation"

    def test_no_rotation_under_limit(self, tmp_path):
        """Verify no rotation occurs when file is under max_bytes."""
        append_jsonl = _get_append_jsonl()
        target = tmp_path / "test.jsonl"

        append_jsonl(target, {"small": True}, max_bytes=10000)

        backup = tmp_path / "test.jsonl.1"
        assert not backup.exists()

    def test_backup_overwritten_on_second_rotation(self, tmp_path):
        """Verify second rotation overwrites the previous .1 backup."""
        append_jsonl = _get_append_jsonl()
        target = tmp_path / "test.jsonl"
        backup = tmp_path / "test.jsonl.1"

        target.write_text("first_content\n", encoding="utf-8")
        append_jsonl(target, {"round": 1}, max_bytes=10)

        assert backup.exists()
        assert "first_content" in backup.read_text(encoding="utf-8")

        target.write_text("second_content_padded_long\n", encoding="utf-8")
        append_jsonl(target, {"round": 2}, max_bytes=10)

        assert "second_content" in backup.read_text(encoding="utf-8")
        assert "first_content" not in backup.read_text(encoding="utf-8")

    def test_zero_backup_count_deletes_instead(self, tmp_path):
        """Verify backup_count=0 deletes the oversized file instead of rotating."""
        append_jsonl = _get_append_jsonl()
        target = tmp_path / "test.jsonl"

        target.write_text("x" * 500 + "\n", encoding="utf-8")

        append_jsonl(target, {"fresh": True}, max_bytes=100, backup_count=0)

        backup = tmp_path / "test.jsonl.1"
        assert not backup.exists()
        assert json.loads(target.read_text(encoding="utf-8").strip())["fresh"] is True


class TestDefaultRotation:
    """Verify default rotation kicks in at the right size."""

    def test_no_rotation_under_default_cap(self, tmp_path):
        """Verify file stays intact under the 500KB default cap."""
        append_jsonl = _get_append_jsonl()
        target = tmp_path / "test.jsonl"

        target.write_text("x" * 400_000 + "\n", encoding="utf-8")
        append_jsonl(target, {"still": "ok"})

        assert not (tmp_path / "test.jsonl.1").exists()
