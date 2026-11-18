# =================== AIPass ====================
# META DATA HEADER
# Name: test_json_durability.py - JSON Handler Durability Tests
# Description: Durability tests for the json service, as prax reaches it (the AIPASS_TEST_LOG_DIR seam)
# Version: 2.2.0
# Created: 2026-08-18
# Modified: 2026-11-17
# Category: prax/tests
#
# CHANGELOG (Max 5 entries):
#   - v2.2.0 (2026-11-17): log_operation's per-module lock: the hundred, the killed and the frozen holder
#   - v2.0.0 (2026-09-03): Re-pointed at the fleet json service (DPLAN-0325);
#     the PRAX_JSON_DIR two-fixed-point tests retired with the constant
#   - v1.0.0 (2026-08-18): Initial creation — os.replace retry pins (Windows sharing violation)
#
# CODE STANDARDS:
#   - Pytest function style (no unittest classes)
#   - tmp_path + monkeypatch for file isolation — never the live prax_json/
# =============================================

"""Tests for apps/handlers/json/json_service.py and the apps/handlers/json/json_handler.py shim."""

# Measured in a SUBPROCESS: in-process, export-before-or-after-import is invisible.

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(through_the_command) — load_json and save_json, covered by tests/test_json_handler.py
# sentry: no-test-needed(through_the_command) — log_operation's entry and cap, covered by tests/test_json_handler.py
# sentry: no-test-needed(through_the_command) — read_json and write_json, covered by tests/test_json_handler.py
# sentry: no-test-needed(through_the_command) — for_module, covered by tests/test_json_handler.py

import fcntl
import json
import multiprocessing
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from aipass.prax.apps.handlers.json import json_service as service


def _probe(code: str, env_value: str) -> str:
    """Run code in a fresh interpreter with AIPASS_TEST_LOG_DIR exported."""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "AIPASS_TEST_LOG_DIR": env_value},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().splitlines()[-1]


# The contract is AIPASS_TEST_LOG_DIR in @trigger's form, deliberately not a new spelling.


class TestTestLogDirSeam:
    """The redirect is a function of the environment at the moment of the call."""

    def test_a_redirect_set_before_import_still_follows_a_later_change(self, tmp_path):
        """A redirect exported before import still follows a later change: the CURRENT value wins."""
        first, second = tmp_path / "first", tmp_path / "second"
        code = (
            "import os\n"
            "from aipass.prax import json_handler\n"
            "from aipass.prax.apps.handlers.json import json_handler as shim\n"
            f"os.environ['AIPASS_TEST_LOG_DIR'] = {str(second)!r}\n"
            "print(shim.get_json_path('probe', 'config'))\n"
        )

        built = Path(_probe(code, str(first)))

        assert built == second / "prax" / "prax_json" / "probe_config.json", (
            f"resolution stuck on the import-time redirect: {built}"
        )

    def test_a_redirect_arriving_after_import_takes_effect(self, tmp_path):
        """Nothing exported at import, set afterwards: a directory read at import would hit the real tree."""
        code = (
            "import os\n"
            "from aipass.prax.apps.handlers.json import json_handler as shim\n"
            f"os.environ['AIPASS_TEST_LOG_DIR'] = {str(tmp_path)!r}\n"
            "print(shim.get_json_path('probe', 'config'))\n"
        )

        built = Path(_probe(code, ""))

        assert built == tmp_path / "prax" / "prax_json" / "probe_config.json"

    def test_the_write_lands_in_the_redirect_and_the_real_tree_is_untouched(self, tmp_path):
        """The seam is only worth having if the FILE moves, not just the path."""
        code = (
            "from aipass.prax.apps.handlers.json import json_handler as shim\n"
            "shim.ensure_module_jsons('seam_probe')\n"
            "print(shim.get_json_path('seam_probe', 'config'))\n"
        )

        written = Path(_probe(code, str(tmp_path)))

        assert written.exists()
        assert written == tmp_path / "prax" / "prax_json" / "seam_probe_config.json"
        real_tree = Path(__file__).resolve().parents[1] / "prax_json"
        assert not (real_tree / "seam_probe_config.json").exists(), (
            "the probe wrote into the live prax_json/ despite the redirect"
        )

    def test_an_empty_variable_is_absence_not_the_filesystem_root(self, tmp_path):
        """AIPASS_TEST_LOG_DIR='' is "unset", never a redirect to the root of the disk."""
        code = (
            "from aipass.prax.apps.handlers.json import json_handler as shim\n"
            "print(shim.get_json_path('probe', 'config'))\n"
        )

        built = Path(_probe(code, ""))

        assert built.parent.parent.name == "prax"
        assert built.parent.name == "prax_json"
        assert built.parts[:2] != (os.sep, "prax")


# Fork, not spawn: a spawned child re-imports the service through the handlers fence as a stranger.
_FORK = multiprocessing.get_context("fork")
_ERROR_MSG = "json_service: log_operation lock not acquired"


def _seat(tmp_path: Path) -> "service.JsonHandle":
    """A handle whose documents live under tmp_path, through the AIPASS_TEST_LOG_DIR seam."""
    return service.JsonHandle(tmp_path / "seat")


def _log_one(args: tuple) -> bool:
    """One seat's call, run in a pool worker process."""
    root, n = args
    return service.JsonHandle(Path(root)).log_operation(f"op{n}", module_name="hundred")


def _hold_lock(lock_path: str, ready, release) -> None:
    """Another agent taking the module's lock and keeping it until released or killed."""
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o666)
    fcntl.flock(fd, fcntl.LOCK_EX)
    ready.set()
    release.wait()


def _holder(handle, module: str):
    """(process, release): a live child holding module's lock."""
    handle.json_dir.mkdir(parents=True, exist_ok=True)
    ready, release = _FORK.Event(), _FORK.Event()
    child = _FORK.Process(target=_hold_lock, args=(str(handle.json_dir / f"{module}.lock"), ready, release))
    child.start()
    assert ready.wait(10), "the holder never took the lock"
    return child, release


def _doc(handle, module: str, json_type: str):
    """A module's document as it sits on disk."""
    return json.loads(handle.get_json_path(module, json_type).read_text(encoding="utf-8"))


def _trail_errors(tmp_path: Path) -> list:
    """ERROR lines on the json service's trail under the seam."""
    trail = tmp_path / "prax" / "logs" / "json_service.jsonl"
    if not trail.exists():
        return []
    lines = [json.loads(line) for line in trail.read_text(encoding="utf-8").splitlines()]
    return [line for line in lines if line["level"] == "ERROR"]


class TestWritersQueue:
    """Writers to one module's trail wait their turn; none is lost."""

    @pytest.mark.timeout(60)
    def test_a_hundred_processes_at_one_module_lose_no_entry_and_no_count(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
        handle = _seat(tmp_path)

        with _FORK.Pool(8) as pool:
            answers = pool.map(_log_one, [(str(handle.branch_root), n) for n in range(100)])

        assert answers == [True] * 100
        log = _doc(handle, "hundred", "log")
        assert sorted(entry["operation"] for entry in log) == sorted(f"op{n}" for n in range(100))
        assert _doc(handle, "hundred", "data")["operations_total"] == 100


class TestADeadHolder:
    """The kernel frees a killed holder's lock: the next writer goes straight through."""

    @pytest.mark.timeout(30)
    def test_a_holder_killed_mid_lock_blocks_no_one_and_logs_no_error(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
        handle = _seat(tmp_path)
        child, _ = _holder(handle, "dead")
        child.kill()
        child.join(10)
        assert child.exitcode == -signal.SIGKILL

        started = time.monotonic()
        answered = handle.log_operation("after the kill", module_name="dead")
        elapsed = time.monotonic() - started

        assert answered is True
        assert elapsed < service.LOCK_DEADLINE_SECONDS / 2
        assert [entry["operation"] for entry in _doc(handle, "dead", "log")] == ["after the kill"]
        assert _trail_errors(tmp_path) == []
        assert (handle.json_dir / "dead.lock").exists()


class TestAFrozenHolder:
    """A live holder past the deadline: one False, one ERROR with the reason, no write without the lock."""

    @pytest.mark.timeout(30)
    def test_a_frozen_holder_ends_in_one_false_and_one_error_and_spares_other_modules(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
        monkeypatch.setattr(service, "LOCK_DEADLINE_SECONDS", 0.5)
        handle = _seat(tmp_path)
        child, release = _holder(handle, "frozen")
        try:
            started = time.monotonic()
            answered = handle.log_operation("while frozen", module_name="frozen")
            waited = time.monotonic() - started

            other_started = time.monotonic()
            other = handle.log_operation("elsewhere", module_name="other")
            other_waited = time.monotonic() - other_started
        finally:
            release.set()
            child.join(10)

        assert answered is False
        assert 0.5 <= waited < 2.0
        assert other is True and other_waited < 0.5
        errors = _trail_errors(tmp_path)
        assert [(e["msg"], e["module"]) for e in errors] == [(_ERROR_MSG, "frozen")]
        assert "within 0.5 seconds" in errors[0]["error"]

        assert handle.log_operation("after the thaw", module_name="frozen") is True
        assert [entry["operation"] for entry in _doc(handle, "frozen", "log")] == ["after the thaw"]
