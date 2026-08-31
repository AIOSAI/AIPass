# ===================AIPASS====================
# META DATA HEADER
# Name: test_json_durability.py - JSON Handler Durability Tests
# Date: 2026-08-18
# Version: 1.0.0
# Category: prax/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-08-18): Initial creation — os.replace retry pins (Windows sharing violation)
#
# CODE STANDARDS:
#   - Pytest function style (no unittest classes)
#   - tmp_path + monkeypatch for file isolation — never the live prax_json/
# =============================================

"""
Durability tests for the prax JSON handler.

Two defects meet at the swap. The first is the torn write: opening a live
document with mode "w" truncates it before the new bytes land, so a concurrent
reader sees an empty or partial file — closed by staging to a temp file in the
target's own directory and swapping with os.replace.

The second is Windows-only and was closed on 2026-08-18: os.replace raises
PermissionError while ANY reader holds the target open (no FILE_SHARE_DELETE on
Python's open), and one stuck move starved a whole CI run — 45-minute cancels.
The fix is _replace_with_retry, a bounded retry that converges on the
microsecond-scale handles a reader actually holds and then raises honestly.

A standards audit found _replace_with_retry carried ZERO tests fleet-wide. These
pins close that gap: the helper is exercised directly (success after retry,
exhaustion raises, a non-sharing OSError propagates on the first attempt), the
write site is proven to route through it, and a 2-writer/2-reader race measures
zero unusable reads.

Linux never raises PermissionError from os.replace on an open file, so every
retry test here injects the failure — that injection is the only cross-platform
proof the retry path exists at all.
"""

import errno
import json
import os
import threading
import time
from pathlib import Path

import pytest

import aipass.prax.apps.handlers.json.json_handler as json_handler_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_data(module_name: str = "durability", filler: str = "x") -> dict:
    """Build a structurally valid 'data' document with a wide truncation window."""
    return {
        "module_name": module_name,
        "created": "2026-08-18",
        "last_updated": "2026-08-18",
        "filler": [filler * 64 for _ in range(400)],
    }


def _temp_files(directory: Path) -> list:
    """Return staged temp artifacts left behind in a directory."""
    return [path for path in directory.iterdir() if path.suffix == ".tmp"]


@pytest.fixture
def json_dir(tmp_path, monkeypatch):
    """Point the handler at a throwaway JSON directory for the duration of a test."""
    target = tmp_path / "prax_json"
    target.mkdir()
    monkeypatch.setattr(json_handler_mod, "PRAX_JSON_DIR", target)
    return target


# ---------------------------------------------------------------------------
# The retry helper's own contract
# ---------------------------------------------------------------------------


def test_replace_helper_exists():
    """The handler exposes the bounded replace helper."""
    assert hasattr(json_handler_mod, "_replace_with_retry"), (
        "_replace_with_retry missing — a Windows sharing violation still kills the write"
    )
    assert json_handler_mod._REPLACE_ATTEMPTS > 1, "a single attempt is not a retry"
    assert json_handler_mod._REPLACE_BACKOFF_SECONDS > 0, "a zero backoff spins instead of waiting"


def test_replace_helper_moves_the_staged_file(tmp_path):
    """The happy path is still a plain move — the retry costs nothing when nothing blocks."""
    source = tmp_path / "staged.tmp"
    source.write_text("new", encoding="utf-8")
    destination = tmp_path / "live.json"
    destination.write_text("old", encoding="utf-8")

    json_handler_mod._replace_with_retry(str(source), str(destination))

    assert destination.read_text(encoding="utf-8") == "new"
    assert not source.exists()


def test_replace_helper_retries_through_a_transient_sharing_violation(tmp_path, monkeypatch):
    """Two sharing violations then success — the move still lands."""
    calls = {"count": 0}
    real_replace = os.replace

    def flaky_replace(source, destination):
        calls["count"] += 1
        if calls["count"] <= 2:
            raise PermissionError(13, "sharing violation", str(destination))
        real_replace(source, destination)

    monkeypatch.setattr(json_handler_mod.os, "replace", flaky_replace)
    source = tmp_path / "staged.tmp"
    source.write_text("new", encoding="utf-8")
    destination = tmp_path / "live.json"
    destination.write_text("old", encoding="utf-8")

    json_handler_mod._replace_with_retry(str(source), str(destination))

    assert destination.read_text(encoding="utf-8") == "new"
    assert calls["count"] == 3, "retry path never engaged"


def test_replace_retry_is_bounded_and_raises(tmp_path, monkeypatch):
    """A replace that never unblocks raises instead of retrying forever."""
    calls = {"count": 0}

    def blocked_replace(source, destination):
        calls["count"] += 1
        raise PermissionError(13, "sharing violation", str(destination))

    monkeypatch.setattr(json_handler_mod.os, "replace", blocked_replace)
    monkeypatch.setattr(json_handler_mod, "_REPLACE_BACKOFF_SECONDS", 0)

    with pytest.raises(PermissionError):
        json_handler_mod._replace_with_retry(str(tmp_path / "staged.tmp"), str(tmp_path / "live.json"))

    assert calls["count"] == json_handler_mod._REPLACE_ATTEMPTS, "bound not honoured"


def test_retry_waits_between_attempts(tmp_path, monkeypatch):
    """
    The backoff is used, not just declared.

    Deleting the sleep leaves a busy spin that passes every other pin here: it
    still retries, still bounds, still raises. But 40 immediate attempts finish
    inside a microsecond and never outlast the reader handle the retry exists to
    wait out. The retry stops being a fix and becomes decoration, and nothing
    else in this file would say so — it survived a mutation run on 2026-08-18.
    Counting the sleeps pins the wait without asserting on wall-clock time,
    which would be flaky on a loaded runner.
    """
    sleeps = []
    monkeypatch.setattr(json_handler_mod.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(
        json_handler_mod.os,
        "replace",
        lambda source, destination: (_ for _ in ()).throw(PermissionError(13, "sharing violation", str(destination))),
    )

    with pytest.raises(PermissionError):
        json_handler_mod._replace_with_retry(str(tmp_path / "staged.tmp"), str(tmp_path / "live.json"))

    # One wait between each pair of attempts — never after the last, which raises.
    assert sleeps == [json_handler_mod._REPLACE_BACKOFF_SECONDS] * (json_handler_mod._REPLACE_ATTEMPTS - 1)


def test_non_permission_error_propagates_immediately(tmp_path, monkeypatch):
    """
    Only a sharing violation is worth waiting out.

    A cross-device rename or a full disk will not fix itself in 200ms, and
    retrying it 40 times buys nothing but a slower failure.
    """
    calls = {"count": 0}

    def broken_replace(source, destination):
        calls["count"] += 1
        raise OSError(errno.EXDEV, "invalid cross-device link")

    monkeypatch.setattr(json_handler_mod.os, "replace", broken_replace)
    monkeypatch.setattr(json_handler_mod, "_REPLACE_BACKOFF_SECONDS", 0)

    with pytest.raises(OSError) as caught:
        json_handler_mod._replace_with_retry(str(tmp_path / "staged.tmp"), str(tmp_path / "live.json"))

    assert caught.value.errno == errno.EXDEV
    assert calls["count"] == 1, "a non-sharing failure was retried"


# ---------------------------------------------------------------------------
# The write site routes through the helper
# ---------------------------------------------------------------------------


def test_atomic_write_routes_through_the_replace_helper(json_dir, monkeypatch):
    """A bare os.replace re-introduces the whole Windows hang, and it reads as harmless."""
    calls = []
    real_replace = os.replace

    def spy(source, destination):
        calls.append((source, destination))
        real_replace(source, destination)

    monkeypatch.setattr(json_handler_mod, "_replace_with_retry", spy)

    json_handler_mod._atomic_write(json_dir / "routed.json", json.dumps({"ok": True}))

    assert len(calls) == 1, "the write did not go through _replace_with_retry"


def test_exhausted_retry_leaves_the_original_intact_and_cleans_the_temp(json_dir, monkeypatch):
    """A move that never unblocks must not damage the live document or litter."""
    target = Path(json_handler_mod.get_json_path("durability", "data"))
    original = _valid_data(filler="original")
    assert json_handler_mod.save_json("durability", "data", original) is True

    def blocked_replace(source, destination):
        raise PermissionError(13, "sharing violation", str(destination))

    monkeypatch.setattr(json_handler_mod.os, "replace", blocked_replace)
    monkeypatch.setattr(json_handler_mod, "_REPLACE_BACKOFF_SECONDS", 0)

    # save_json owns the refusal here — it logs and answers False rather than
    # raising. The live document surviving intact is what this test is about.
    assert json_handler_mod.save_json("durability", "data", _valid_data(filler="doomed")) is False

    survivor = json.loads(target.read_text(encoding="utf-8"))
    assert survivor["filler"] == original["filler"], "the live document was damaged"
    assert _temp_files(json_dir) == []


def test_save_survives_a_transient_sharing_violation(json_dir, monkeypatch):
    """End to end: the branch's own save path rides out a Windows sharing violation."""
    calls = {"count": 0}
    real_replace = os.replace

    def flaky_replace(source, destination):
        calls["count"] += 1
        if calls["count"] <= 2:
            raise PermissionError(13, "sharing violation", str(destination))
        real_replace(source, destination)

    monkeypatch.setattr(json_handler_mod.os, "replace", flaky_replace)

    assert json_handler_mod.save_json("durability", "data", _valid_data(filler="retry")) is True

    target = json_handler_mod.get_json_path("durability", "data")
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written["filler"] == _valid_data(filler="retry")["filler"], "payload lost across the retry"

    assert calls["count"] == 3, "retry path never engaged"


# ---------------------------------------------------------------------------
# Concurrency probe — the defect itself
# ---------------------------------------------------------------------------


def test_concurrent_writers_never_expose_a_torn_document(json_dir):
    """
    Two writers and two readers on one document produce zero unusable reads.

    Measured against a truncating write this same way on the sibling commons
    handler: 1,297 reads, 553 empty and 485 unparseable — 80.03% unusable.
    """
    module_name = "durability"
    target = Path(json_handler_mod.get_json_path(module_name, "data"))
    json_handler_mod.save_json(module_name, "data", _valid_data(filler="a"))

    stop = threading.Event()
    counts = {"ok": 0, "empty": 0, "unparseable": 0}
    lock = threading.Lock()
    iterations = 150

    failures = []

    def writer(filler):
        # stop.set() must fire even if a write raises — a dead writer that
        # never releases the readers hangs the whole suite, not just this
        # test (Windows CI sat 1h45m exactly this way on 2026-08-18).
        try:
            for _ in range(iterations):
                assert json_handler_mod.save_json(module_name, "data", _valid_data(filler=filler)) is True
        except Exception as error:  # noqa: BLE001 - re-raised via failures below
            with lock:
                failures.append(error)
        finally:
            stop.set()

    def reader():
        local = {"ok": 0, "empty": 0, "unparseable": 0}
        while not stop.is_set():
            # Yield between polls — Windows share-mode semantics, not tuning.
            # A zero-delay spin-reader holds the target open at near-100% duty
            # cycle, and Python opens files without FILE_SHARE_DELETE, so on
            # Windows an os.replace onto a handle a reader holds fails with
            # WinError 5. Two spinning readers can then collide with every one
            # of the writer's bounded retry attempts and starve a correct retry
            # into exhaustion (first full Windows CI run, 2026-08-18). 1ms
            # models a real reader — no fleet workload spin-reads a config file
            # — and weakens no content check below. At the top of the pass so
            # the `continue` paths yield too: a refused open means a replace is
            # in flight, exactly when re-spinning hurts most.
            time.sleep(0.001)
            try:
                raw = target.read_text(encoding="utf-8")
            except OSError:
                # PermissionError lands here too: on Windows a concurrent
                # os.replace refuses the open. A refused open is share-mode
                # semantics — not a torn document, and not a read at all.
                continue
            if raw.strip() == "":
                local["empty"] += 1
                continue
            try:
                json.loads(raw)
                local["ok"] += 1
            except json.JSONDecodeError:
                local["unparseable"] += 1
        with lock:
            for key, value in local.items():
                counts[key] += value

    threads = [
        threading.Thread(target=writer, args=("a",)),
        threading.Thread(target=writer, args=("b",)),
        threading.Thread(target=reader),
        threading.Thread(target=reader),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    stuck = [thread.name for thread in threads if thread.is_alive()]
    assert not stuck, f"threads never finished: {stuck}"

    assert not failures, f"a writer died mid-race: {failures[0]!r}"
    assert counts["ok"] > 0, "probe never observed a readable document"
    assert counts["empty"] == 0, f"{counts['empty']} readers saw an empty document"
    assert counts["unparseable"] == 0, f"{counts['unparseable']} readers saw a partial document"


# =============================================================================
# AIPASS_TEST_LOG_DIR — the fleet seam (2026-08-30, @devpulse dispatch)
# =============================================================================
#
# prax redirected its log FILES under pytest for a long time
# (config/load.py::get_system_logs_dir) and never gave PRAX_JSON_DIR the same
# branch, so one logger.info() under pytest wrote 4 redirected files and 24 real
# ones into src/aipass/prax/prax_json/. Every branch's suite paid it: @drone
# measured 3449 of their hygiene records as prax's json_handler, @memory 1552,
# @daemon 1096, @backup 778.
#
# The contract is AIPASS_TEST_LOG_DIR in @trigger's form
# (trigger/apps/handlers/json/json_handler.py:35) — deliberately NOT a sixth
# spelling invented here.


class TestTestLogDirSeam:
    """PRAX_JSON_DIR honours AIPASS_TEST_LOG_DIR, like the log files already do.

    Tested through the pure resolver rather than by reloading the module: this
    branch's conftest pulls prax modules out of sys.modules, so importlib.reload
    is not available here, and a resolver that can be called with its inputs is
    a better seam than one that can only be observed as an import side effect.
    """

    def test_env_var_redirects_out_of_the_real_tree(self, tmp_path):
        """The whole point: a suite that sets the var keeps its writes out of prax."""
        resolved = json_handler_mod._resolve_prax_json_dir(str(tmp_path), Path("/real/prax"))
        assert resolved == tmp_path / "prax" / "prax_json"
        assert Path("/real/prax") not in resolved.parents

    def test_absent_env_var_uses_the_real_tree(self):
        """Production must be untouched — absence of the var means the real dir."""
        assert json_handler_mod._resolve_prax_json_dir(None, Path("/real/prax")) == Path("/real/prax/prax_json")

    def test_empty_env_var_is_absence_not_the_filesystem_root(self):
        """AIPASS_TEST_LOG_DIR='' must not resolve to /prax/prax_json."""
        assert json_handler_mod._resolve_prax_json_dir("", Path("/real/prax")) == Path("/real/prax/prax_json")

    def test_writes_land_in_the_redirect_not_the_real_tree(self, monkeypatch, tmp_path):
        """Call-time resolution: the seam works even though this module was
        imported before the conftest set the variable. Import-time resolution
        alone left the live constant pointing at the real tree — measured."""
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
        resolved = json_handler_mod._current_json_dir()
        assert resolved == tmp_path / "prax" / "prax_json"
        assert "Projects" not in resolved.parts, resolved

    def test_an_explicit_override_still_wins_over_the_env(self, monkeypatch, tmp_path):
        """~20 tests redirect by patching the attribute; that must keep working."""
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "env"))
        monkeypatch.setattr(json_handler_mod, "PRAX_JSON_DIR", tmp_path / "patched")
        assert json_handler_mod._current_json_dir() == tmp_path / "patched"

    def test_the_path_builder_resolves_at_call_time(self, monkeypatch, tmp_path):
        """The load-bearing pin. A mutation reverting _json_path() to read the
        import-time constant survived every other test in this class — the seam
        is only real if the USE SITES resolve, not just the resolver."""
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
        built = json_handler_mod.get_json_path("probe", "config")
        assert built == tmp_path / "prax" / "prax_json" / "probe_config.json"
        assert "Projects" not in built.parts, built

    def test_a_stale_write_back_of_the_real_dir_is_not_an_override(self, monkeypatch, tmp_path):
        """@daemon's reload defect, reproduced against prax's own resolver.

        A test that calls importlib.reload while a monkeypatch is live has its
        teardown write the PRE-reload Path back onto the POST-reload module. With
        the identity check prax originally shipped — and with @daemon's value
        comparison too, in this ordering — that stale real-directory value reads
        as an explicit override and the redirect silently dies for the rest of the
        session. Every one of the 18 branches uses importlib.reload somewhere.
        """
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
        real = json_handler_mod._resolve_prax_json_dir(None, json_handler_mod._PRAX_ROOT)
        monkeypatch.setattr(json_handler_mod, "PRAX_JSON_DIR", real)

        resolved = json_handler_mod._current_json_dir()
        assert resolved == tmp_path / "prax" / "prax_json", (
            "a stale write-back of the real directory was read as a deliberate override"
        )

    def test_a_write_back_equal_to_the_redirect_is_not_an_override(self, monkeypatch, tmp_path):
        """@daemon's own ordering: the write-back equals the post-reload default."""
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
        monkeypatch.setattr(json_handler_mod, "PRAX_JSON_DIR", tmp_path / "prax" / "prax_json")
        assert json_handler_mod._current_json_dir() == tmp_path / "prax" / "prax_json"

    def test_no_env_and_no_override_is_the_real_tree(self, monkeypatch):
        """Production is untouched when nobody asks for a redirect."""
        monkeypatch.delenv("AIPASS_TEST_LOG_DIR", raising=False)
        resolved = json_handler_mod._current_json_dir()
        assert resolved.name == "prax_json" and resolved.parent.name == "prax"
