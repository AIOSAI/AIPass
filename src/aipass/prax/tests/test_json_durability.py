# =================== AIPass ====================
# META DATA HEADER
# Name: test_json_durability.py - JSON Handler Durability Tests
# Description: Durability tests for the json service, as prax reaches it (the AIPASS_TEST_LOG_DIR seam)
# Version: 2.1.0
# Created: 2026-08-18
# Modified: 2026-10-17
# Category: prax/tests
#
# CHANGELOG (Max 5 entries):
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
# seedgo: no-test-needed(through_the_command) — load_json and save_json, covered by tests/test_json_handler.py
# seedgo: no-test-needed(through_the_command) — log_operation, covered by tests/test_json_handler.py
# seedgo: no-test-needed(through_the_command) — read_json and write_json, covered by tests/test_json_handler.py
# seedgo: no-test-needed(through_the_command) — for_module, covered by tests/test_json_handler.py
# seedgo: no-test-needed(json_handler) — replace_with_retry's bounded retry, pinned by seedgo's contract suite

import os
import subprocess
import sys
from pathlib import Path


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
