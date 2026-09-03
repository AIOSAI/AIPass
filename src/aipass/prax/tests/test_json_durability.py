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

The pins this file was born with — the bounded os.replace retry, the write site
routing through it, the exhausted retry leaving the original intact, the
concurrent-writers race — are pinned once for the whole fleet in seedgo's
tests/test_json_handler_contract.py (DPLAN-0323 phase 7, 2026-09-02), prax
included. What remains here is prax-specific: the AIPASS_TEST_LOG_DIR seam.
"""

import os
import subprocess
import sys
from pathlib import Path

import aipass.prax.apps.handlers.json.json_handler as json_handler_mod


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

    def test_the_import_time_anchor_is_env_independent(self, tmp_path):
        """The precondition @drone wrote down when they adopted this contract.

        _current_json_dir() detects an explicit override by comparing against two
        fixed points. A reference that is itself derived from the thing being
        detected cannot detect it (@daemon's sentence) — so if the anchor is
        seeded from AIPASS_TEST_LOG_DIR, then in any run where the variable was
        already exported at import time PRAX_JSON_DIR *is* a redirect, and the
        moment anything points the variable somewhere else that stale redirect
        reads as a deliberate patch and wins forever.

        Measured in a SUBPROCESS on purpose. In-process this is invisible: prax's
        own suite is green from the branch directory only because something
        imports this module before tests/conftest.py exports the variable — the
        anchor lands on the real tree by import-order luck, not by design. From
        the repo root another branch's conftest exports it first and the same
        assertion goes red. A pin that can only bite in one of the two universes
        is not a pin; running the import with the variable set makes the property
        observable in both.
        """
        code = (
            "from aipass.prax.apps.handlers.json import json_handler as m\n"
            "print(m._IMPORT_TIME_JSON_DIR)\n"
            "print(m.PRAX_JSON_DIR)\n"
            "print(m._resolve_prax_json_dir(None, m._PRAX_ROOT))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            env={**os.environ, "AIPASS_TEST_LOG_DIR": str(tmp_path)},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        anchor, live, real = result.stdout.strip().splitlines()[-3:]

        assert anchor == real, f"the anchor is env-derived: {anchor} — it must always be the real tree"
        assert live == real, (
            f"PRAX_JSON_DIR was seeded with a redirect: {live} — a later change of "
            "AIPASS_TEST_LOG_DIR makes this stale value look like an explicit patch"
        )

    def test_a_redirect_set_before_import_still_follows_a_later_change(self, tmp_path):
        """The defect end to end, in the ordering the repo-root suite creates.

        Export the variable, import, then point it somewhere else and ask where a
        write would land. It must follow the CURRENT value. Before the anchor was
        made env-independent this returned the first redirect for the rest of the
        process — the two reds @devpulse reproduced on the CI train.
        """
        first, second = tmp_path / "first", tmp_path / "second"
        code = (
            "import os\n"
            "from aipass.prax.apps.handlers.json import json_handler as m\n"
            f"os.environ['AIPASS_TEST_LOG_DIR'] = {str(second)!r}\n"
            "print(m.get_json_path('probe', 'config'))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            env={**os.environ, "AIPASS_TEST_LOG_DIR": str(first)},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        built = Path(result.stdout.strip().splitlines()[-1])

        assert built == second / "prax" / "prax_json" / "probe_config.json", (
            f"resolution stuck on the import-time redirect: {built}"
        )
