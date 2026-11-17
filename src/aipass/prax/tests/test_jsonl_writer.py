# =================== AIPass ====================
# Name: test_jsonl_writer.py
# Description: Tests for PRAX JSONL writer with rotation, and the trail logger on it
# Version: 1.4.0
# Created: 2026-07-10
# Modified: 2026-11-17
# =============================================

"""Tests for apps/handlers/logging/jsonl_writer.py and apps/handlers/logging/trail.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(error_handling) — _rotate raising when backup_count=0 cannot remove it, covered by that row
# sentry: no-test-needed(error_handling) — _over_limit raising when the stat fails, covered by that row
# sentry: no-test-needed(constant) — rotation above the JSONL_MAX_BYTES default; only the size under it is tested

import contextlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from aipass.prax.apps.handlers.logging import jsonl_writer
from aipass.prax.apps.handlers.logging import trail as trail_mod
from aipass.prax.apps.handlers.logging.jsonl_writer import append_jsonl
from aipass.prax import trail

SRC_DIR = Path(__file__).resolve().parents[3]

_WRITER_PACKAGES = {
    "aipass",
    "aipass.prax",
    "aipass.prax.apps",
    "aipass.prax.apps.handlers",
    "aipass.prax.apps.handlers.logging",
    "aipass.prax.apps.handlers.logging.jsonl_writer",
}

_IMPORT_PROBE = """
import importlib, json, sys
sys.path.insert(0, sys.argv[1])
for name in sys.argv[2:]:
    importlib.import_module(name)
print(json.dumps(sorted(n for n in sys.modules if n == "aipass" or n.startswith("aipass."))))
"""

_WRITER_PROBE = """
import sys
sys.path.insert(0, sys.argv[1])
from aipass.prax.apps.handlers.logging.jsonl_writer import append_jsonl
target, proc, count = sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
for n in range(count):
    append_jsonl(target, {"p": proc, "n": n}, max_bytes=256, backup_count=1000)
"""


def _aipass_modules_after_importing(*names: str) -> set:
    """aipass modules a fresh isolated interpreter holds after importing *names*."""
    result = subprocess.run(
        [sys.executable, "-I", "-c", _IMPORT_PROBE, str(SRC_DIR), *names],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ},
        timeout=60,
    )
    assert result.returncode == 0, f"probe failed: {result.stderr}"
    return set(json.loads(result.stdout.strip().splitlines()[-1]))


def _records(path: Path) -> list:
    """Every JSON line in *path*, in file order."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class TestAppendJsonl:
    """Core append behavior."""

    def test_creates_file_and_appends(self, tmp_path):
        """Verify a new file is created and data appended as JSON line."""
        target = tmp_path / "test.jsonl"

        append_jsonl(target, {"key": "value"})

        assert target.exists()
        lines = target.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0]) == {"key": "value"}

    def test_appends_multiple_lines(self, tmp_path):
        """Verify successive appends produce multiple JSON lines."""
        target = tmp_path / "test.jsonl"

        append_jsonl(target, {"n": 1})
        append_jsonl(target, {"n": 2})
        append_jsonl(target, {"n": 3})

        lines = target.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3
        assert json.loads(lines[2])["n"] == 3

    def test_creates_parent_directories(self, tmp_path):
        """Verify missing parent directories are auto-created."""
        target = tmp_path / "deep" / "nested" / "dir" / "test.jsonl"

        append_jsonl(target, {"created": True})

        assert target.exists()
        assert json.loads(target.read_text(encoding="utf-8").strip())["created"] is True

    def test_handles_non_serializable_with_default_str(self, tmp_path):
        """Verify non-serializable types fall back to str()."""
        target = tmp_path / "test.jsonl"
        test_path = tmp_path / "some" / "path"

        append_jsonl(target, {"path": test_path})

        line = json.loads(target.read_text(encoding="utf-8").strip())
        assert line["path"] == str(test_path)


class TestRotation:
    """Size-based rotation behavior."""

    def test_rotates_when_exceeding_max_bytes(self, tmp_path):
        """Verify file is rotated to .1 when it exceeds max_bytes."""
        target = tmp_path / "test.jsonl"

        target.write_text("x" * 500 + "\n", encoding="utf-8")

        append_jsonl(target, {"after": "rotation"}, max_bytes=400)

        backup = tmp_path / "test.jsonl.1"
        assert backup.exists()
        assert "x" * 500 in backup.read_text(encoding="utf-8")

        content = target.read_text(encoding="utf-8").strip()
        assert json.loads(content)["after"] == "rotation"

    def test_a_rotation_another_writer_won_is_not_repeated(self, monkeypatch, tmp_path):
        """Two writers saw the file over the limit; the one that waited on the lock must not rotate again."""
        target = tmp_path / "shared.jsonl"
        target.write_text("x" * 500 + "\n", encoding="utf-8")

        @contextlib.contextmanager
        def lock_won_by_another(path):
            os.replace(path, tmp_path / "shared.jsonl.1")
            path.write_text('{"theirs": 1}\n', encoding="utf-8")
            yield

        monkeypatch.setattr(jsonl_writer, "rotation_lock", lock_won_by_another)
        append_jsonl(target, {"mine": 1}, max_bytes=400)

        assert "x" * 500 in (tmp_path / "shared.jsonl.1").read_text(encoding="utf-8")
        assert [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()] == [
            {"theirs": 1},
            {"mine": 1},
        ]

    def test_no_rotation_under_limit(self, tmp_path):
        """Verify no rotation occurs when file is under max_bytes."""
        target = tmp_path / "test.jsonl"

        append_jsonl(target, {"small": True}, max_bytes=10000)

        backup = tmp_path / "test.jsonl.1"
        assert not backup.exists()

    def test_backup_overwritten_on_second_rotation(self, tmp_path):
        """Verify second rotation overwrites the previous .1 backup."""
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
        target = tmp_path / "test.jsonl"

        target.write_text("x" * 500 + "\n", encoding="utf-8")

        append_jsonl(target, {"fresh": True}, max_bytes=100, backup_count=0)

        backup = tmp_path / "test.jsonl.1"
        assert not backup.exists()
        assert json.loads(target.read_text(encoding="utf-8").strip())["fresh"] is True


class TestRotationUnderOneLock:
    """The size check, rotation and append share one cross-process lock; backup_count is honoured."""

    def test_a_failed_rotation_rename_raises_and_appends_nothing(self, tmp_path):
        """Shipped defect: a failed rename was logged and the append went on into the oversized file."""
        target = tmp_path / "test.jsonl"
        target.write_text("x" * 500 + "\n", encoding="utf-8")
        # The real route to a failed rename: a directory sits where the .1 backup goes.
        (tmp_path / "test.jsonl.1").mkdir()

        with pytest.raises(IsADirectoryError):
            append_jsonl(target, {"lost": True}, max_bytes=400)

        assert target.read_text(encoding="utf-8") == "x" * 500 + "\n"

    def test_backup_count_three_keeps_three_backups_and_never_a_fourth(self, tmp_path):
        """Shipped defect: any backup_count >= 1 kept exactly one .1."""
        target = tmp_path / "test.jsonl"

        for n in range(6):
            append_jsonl(target, {"n": n}, max_bytes=1, backup_count=3)

        kept = [_records(tmp_path / f"test.jsonl.{i}") for i in (3, 2, 1)] + [_records(target)]
        assert kept == [[{"n": 2}], [{"n": 3}], [{"n": 4}], [{"n": 5}]]
        assert not (tmp_path / "test.jsonl.4").exists()

    def test_concurrent_processes_lose_and_misplace_no_line(self, tmp_path):
        """Real processes racing rotation: every line lands once, each process's lines in order."""
        target = tmp_path / "shared.jsonl"
        procs, count = 4, 60
        writers = [
            subprocess.Popen(
                [sys.executable, "-I", "-c", _WRITER_PROBE, str(SRC_DIR), str(target), str(p), str(count)],
                env={**os.environ},
                stderr=subprocess.PIPE,
            )
            for p in range(procs)
        ]
        for writer in writers:
            _, err = writer.communicate(timeout=30)
            assert writer.returncode == 0, err.decode("utf-8")

        backups = sorted(tmp_path.glob("shared.jsonl.[0-9]*"), key=lambda b: int(b.suffix[1:]), reverse=True)
        lines = [record for path in [*backups, target] for record in _records(path)]
        for p in range(procs):
            assert [r["n"] for r in lines if r["p"] == p] == list(range(count))
        assert len(backups) > 1


class TestStandalone:
    """The writer is importable where prax's logger cannot be: stdlib plus its own packages only."""

    def test_importing_the_writer_loads_no_other_aipass_module(self):
        """Shipped defect: the writer imported rotation_lock from setup.py, pulling 14 prax modules."""
        assert _aipass_modules_after_importing("aipass.prax.apps.handlers.logging.jsonl_writer") == _WRITER_PACKAGES

    def test_importing_trail_loads_only_the_writer_beside_it(self):
        assert _aipass_modules_after_importing("aipass.prax.apps.handlers.logging.trail") == _WRITER_PACKAGES | {
            "aipass.prax.apps.handlers.logging.trail"
        }


class TestTrail:
    """trail(path): a JSONL logger for code that cannot log through prax; every failure raises."""

    @pytest.mark.parametrize("level", ["debug", "info", "warning", "error"])
    def test_each_level_appends_one_line_with_ts_level_msg_and_fields(self, tmp_path, level):
        target = tmp_path / "logs" / "trail.jsonl"

        getattr(trail(target), level)("job ran", job="sweep", n=2)

        [record] = _records(target)
        assert datetime.fromisoformat(record.pop("ts"))
        assert record == {"level": level.upper(), "msg": "job ran", "job": "sweep", "n": 2}

    @pytest.mark.parametrize("name", ["trail.log", "trail.jsonl.bak", "trail"])
    def test_a_path_without_the_jsonl_suffix_is_refused_and_nothing_is_written(self, tmp_path, name):
        with pytest.raises(ValueError, match="jsonl"):
            trail(tmp_path / "logs" / name)

        assert not (tmp_path / "logs").exists()

    def test_a_path_outside_a_logs_directory_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="logs"):
            trail(tmp_path / "log" / "trail.jsonl")

    @pytest.mark.parametrize("key", ["ts", "level", "msg"])
    def test_a_field_named_like_a_reserved_key_raises_and_writes_nothing(self, tmp_path, key):
        target = tmp_path / "logs" / "trail.jsonl"

        with pytest.raises(ValueError, match=key):
            trail(target).info("job ran", **{key: "spoof"})

        assert not target.exists()

    def test_a_failed_write_raises(self, tmp_path):
        """No drop counter, no bool: the caller hears the failure."""
        # The real route to a failed write: a file sits where the parent directory must go.
        (tmp_path / "blocked").write_text("", encoding="utf-8")
        log = trail(tmp_path / "blocked" / "logs" / "trail.jsonl")

        with pytest.raises(OSError):
            log.error("job failed")


class TestPraxTrail:
    """Prax's own diagnostics: prax/logs/<module>.jsonl, the test redirect read per line."""

    def test_a_diagnostic_lands_under_the_redirect_read_at_write_time(self, monkeypatch, tmp_path):
        diag = trail_mod.PraxTrail("probe")
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))

        diag.warning("probe failed", path="/x")

        [record] = _records(tmp_path / "prax" / "logs" / "probe.jsonl")
        assert (record["level"], record["msg"], record["path"]) == ("WARNING", "probe failed", "/x")

    def test_without_the_redirect_it_is_prax_logs(self, monkeypatch):
        monkeypatch.delenv("AIPASS_TEST_LOG_DIR")

        assert trail_mod.PraxTrail("probe").path == trail_mod.PRAX_LOGS / "probe.jsonl"
        assert trail_mod.PRAX_LOGS.parent.name == "prax" and trail_mod.PRAX_LOGS.name == "logs"


class TestDefaultRotation:
    """Verify default rotation kicks in at the right size."""

    def test_no_rotation_under_default_cap(self, tmp_path):
        """Verify file stays intact under the 500KB default cap."""
        target = tmp_path / "test.jsonl"

        target.write_text("x" * 400_000 + "\n", encoding="utf-8")
        append_jsonl(target, {"still": "ok"})

        assert not (tmp_path / "test.jsonl.1").exists()
