# =================== AIPass ====================
# Name: test_json_log_dir_seam.py
# Description: AIPASS_TEST_LOG_DIR adoption pins for daemon's json_handler
# Version: 1.0.0
# Created: 2026-08-30
# Modified: 2026-08-30
# =============================================

"""
The fleet AIPASS_TEST_LOG_DIR contract, adopted in daemon's own json_handler.

@prax ruled the contract (mail 01fb09c6) after measuring that the env-var
branch ALONE is not enough: daemon's own conftest sets AIPASS_TEST_LOG_DIR at
module scope, but something imports json_handler before conftest runs, so a
value captured at import time loses the race and resolves to the live tree.
A seam that depends on winning an import race is not a seam.

Every pin here was red before the fix and names which part of the contract it
holds, so a mutation that reverts one detail dies by name rather than by count.
"""

import os
import sys

import pytest

from aipass.daemon.apps.handlers.json import json_handler as jh


class TestTheRedirectResolvesAtCallTime:
    """The defect @prax found the hard way: import-time capture loses."""

    def test_an_env_set_after_import_still_redirects(self, tmp_path, monkeypatch):
        # The whole point. json_handler is ALREADY imported by the time this
        # runs, exactly as it is already imported when conftest sets the var.
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))

        path = jh.get_json_path("some_module", "log")

        assert tmp_path in path.parents, f"resolved to {path}, not under {tmp_path}"

    def test_the_layout_matches_the_fleet_contract(self, tmp_path, monkeypatch):
        # <root>/<branch>/<branch>_json/ — @trigger's form, so a shared root
        # holding several branches' redirects never collides.
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))

        path = jh.get_json_path("some_module", "log")

        assert path == tmp_path / "daemon" / "daemon_json" / "some_module_log.json"

    def test_a_second_call_follows_a_changed_env(self, tmp_path, monkeypatch):
        # Resolution is per-call, not cached on first use: a memoised resolver
        # would pass the first pin above and still be import-time in disguise.
        first = tmp_path / "first"
        second = tmp_path / "second"

        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(first))
        before = jh.get_json_path("some_module", "log")
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(second))
        after = jh.get_json_path("some_module", "log")

        assert first in before.parents
        assert second in after.parents


class TestAnEmptyValueIsAbsenceNotARedirect:
    """@prax's detail 1 — Path('') / 'x' is RELATIVE and scatters state."""

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_a_blank_env_falls_back_to_the_real_directory(self, blank, monkeypatch):
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", blank)

        path = jh.get_json_path("some_module", "log")

        assert path.is_absolute()
        assert path.parent == jh._IMPORT_TIME_JSON_DIR

    def test_an_unset_env_falls_back_to_the_real_directory(self, monkeypatch):
        monkeypatch.delenv("AIPASS_TEST_LOG_DIR", raising=False)

        path = jh.get_json_path("some_module", "log")

        assert path.parent == jh._IMPORT_TIME_JSON_DIR


class TestAnExplicitPatchBeatsTheEnv:
    """@prax's detail 2 — ~20 existing daemon tests redirect by setattr."""

    def test_a_patched_module_attribute_wins_over_the_env(self, tmp_path, monkeypatch):
        patched = tmp_path / "patched"
        env_dir = tmp_path / "env"
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(env_dir))
        monkeypatch.setattr(jh, "JSON_DIR", patched)

        path = jh.get_json_path("some_module", "log")

        assert path == patched / "some_module_log.json"

    def test_a_patch_given_as_a_string_is_honoured(self, tmp_path, monkeypatch):
        # test_contracts.py and test_error_resilience.py both patch with str(),
        # not Path() — the resolver coerces rather than returning a str and
        # exploding at the first `/`.
        patched = tmp_path / "patched"
        monkeypatch.setattr(jh, "JSON_DIR", str(patched))

        path = jh.get_json_path("some_module", "log")

        assert path == patched / "some_module_log.json"


class TestTheUseSitesResolveTooNotJustTheResolver:
    """@prax's detail 3 — the mutation that survived every other test they had.

    Reverting a path builder to read the import-time constant is invisible to a
    resolver-only pin, so each writing entry point is held here directly.
    """

    def test_ensure_json_exists_creates_under_the_redirect(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))

        assert jh.ensure_json_exists("probe_module", "log") is True

        assert (tmp_path / "daemon" / "daemon_json" / "probe_module_log.json").exists()

    def test_save_json_writes_under_the_redirect(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))

        assert jh.save_json("probe_module", "log", [{"operation": "x"}]) is True

        target = tmp_path / "daemon" / "daemon_json" / "probe_module_log.json"
        assert target.exists()

    def test_load_json_reads_under_the_redirect(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
        jh.save_json("probe_module", "log", [{"operation": "written"}])

        assert jh.load_json("probe_module", "log") == [{"operation": "written"}]

    def test_log_operation_writes_under_the_redirect(self, tmp_path, monkeypatch):
        # The residual @prax named for daemon by name: rotation_log.json and
        # friends are module-name-derived, so they are OURS, not prax's.
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))

        assert jh.log_operation("probe_op", {"k": "v"}, module_name="rotation") is True

        assert (tmp_path / "daemon" / "daemon_json" / "rotation_log.json").exists()


class TestNothingReachesTheLiveTree:
    """The outcome the contract exists for, asserted as behaviour not as path.

    Recorded rather than blocked: @backup's lesson from the credentials watch —
    a hook that raises can drop a library into a worse path than the write.
    """

    def test_a_full_log_cycle_touches_no_file_in_the_real_daemon_json(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
        live = str(jh._IMPORT_TIME_JSON_DIR)
        touched: list = []

        def watch(event, args):
            if event not in ("open", "os.mkdir", "os.rename", "os.remove"):
                return
            try:
                if event == "open":
                    mode = str(args[1] or "")
                    if "w" not in mode and "a" not in mode and "x" not in mode:
                        return
                target = os.path.abspath(str(args[0]))
            except Exception:
                return
            if target.startswith(live):
                touched.append((event, target))

        sys.addaudithook(watch)

        jh.ensure_module_jsons("probe_module")
        jh.log_operation("probe_op", {"k": "v"}, module_name="probe_module")
        jh.increment_counter("probe_module", "probe_counter")

        assert touched == [], f"writes reached the live tree: {touched[:5]}"


class TestSaveJsonCreatesItsOwnDirectory:
    """Found BY the redirect, not by review — so it gets its own name.

    save_json was the only writer that never mkdir'd. It passed for years
    because the live daemon_json/ is committed and therefore always there;
    point the handler anywhere else and _atomic_write_json's tempfile raises
    FileNotFoundError before a byte is written.
    """

    def test_save_json_creates_a_missing_directory_rather_than_raising(self, tmp_path, monkeypatch):
        missing = tmp_path / "never" / "existed"
        monkeypatch.setattr(jh, "JSON_DIR", missing)
        assert not missing.exists()

        assert jh.save_json("probe_module", "log", [{"operation": "x"}]) is True

        assert (missing / "probe_module_log.json").exists()


class TestTheRedirectSurvivesAModuleReload:
    """@prax's recipe compares JSON_DIR by IDENTITY. That breaks here.

    test_contracts.py calls importlib.reload(json_handler) while its autouse
    monkeypatch is active. Teardown then writes the PRE-reload Path object back
    onto the POST-reload module, so JSON_DIR ends up EQUAL to the default and
    not IDENTICAL to it. Under an identity check every later call reads
    "explicitly patched" and the redirect silently stops working for the rest
    of the session -- 9 of these pins went red in the full suite while passing
    alone. Comparing by value is what makes it survive.
    """

    def test_a_reload_does_not_disable_the_env_redirect(self, tmp_path, monkeypatch):
        import importlib

        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
        # Reproduce the exact sequence: patch, reload underneath the patch,
        # then restore the object captured before the reload.
        before = jh.JSON_DIR
        jh.JSON_DIR = tmp_path / "transient"
        try:
            importlib.reload(jh)
        finally:
            jh.JSON_DIR = before

        assert jh.JSON_DIR == jh._IMPORT_TIME_JSON_DIR
        assert jh.JSON_DIR is not jh._IMPORT_TIME_JSON_DIR, "the reload signature this pin exists for did not reproduce"
        assert jh.get_json_path("some_module", "log") == (tmp_path / "daemon" / "daemon_json" / "some_module_log.json")

    def test_the_reverse_ordering_prax_reported_also_survives(self, tmp_path, monkeypatch):
        """@prax's follow-up (mail 80088f4a): import FIRST, env set AFTERWARDS.

        Their correction is right about prax and wrong about daemon, and the
        difference is structural rather than lucky. prax's import-time constant
        is ITSELF env-derived, so it takes a different VALUE across a reload
        that straddles the env being set - which is why comparing against it
        goes stale whichever operator you use. Daemon's _IMPORT_TIME_JSON_DIR
        is never env-derived: it is the real directory and nothing else, so it
        recomputes to the same value every reload and is already a fixed point.
        Pinned so a later refactor cannot quietly make it env-derived.
        """
        import importlib

        monkeypatch.delenv("AIPASS_TEST_LOG_DIR", raising=False)
        importlib.reload(jh)
        before = jh.JSON_DIR
        jh.JSON_DIR = tmp_path / "transient"
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "redirect"))
        try:
            importlib.reload(jh)
        finally:
            jh.JSON_DIR = before

        assert jh._IMPORT_TIME_JSON_DIR == before, (
            "the import-time default became env-derived - the prax failure now applies here"
        )
        assert jh.get_json_path("m", "log") == (tmp_path / "redirect" / "daemon" / "daemon_json" / "m_log.json")
