# ===================AIPASS====================
# META DATA HEADER
# Name: test_json_durability.py - JSON Handler Durability Tests
# Date: 2026-08-18
# Version: 2.0.0
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

"""Durability tests for the json service, as prax reaches it.

The pins this file was born with — the bounded os.replace retry, the write site
routing through it, the exhausted retry leaving the original intact, the
concurrent-writers race — are pinned once for the whole fleet in seedgo's
tests/test_json_handler_contract.py (DPLAN-0323 phase 7, 2026-09-02), prax
included. What remains here is the AIPASS_TEST_LOG_DIR seam, measured in a
SUBPROCESS: in-process the seam is invisible, because whether the redirect was
exported before or after the module was imported is exactly the property under
test.

The PRAX_JSON_DIR override tests that used to live here are in tests/.archive/.
They pinned the two-fixed-point rule that told an explicit monkeypatch of the
module constant apart from a stale reload write-back — a rule that existed only
because the directory was captured at import. The service has no constant and
captures nothing, so there is no override to tell apart. The env var is the one
redirect.
"""

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
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().splitlines()[-1]


# =============================================================================
# AIPASS_TEST_LOG_DIR — the fleet seam (2026-08-30, @devpulse dispatch)
# =============================================================================
#
# prax redirected its log FILES under pytest for a long time
# (config/load.py::get_system_logs_dir) and never gave the json directory the
# same branch, so one logger.info() under pytest wrote 4 redirected files and 24
# real ones into src/aipass/prax/prax_json/. Every branch's suite paid it: @drone
# measured 3449 of their hygiene records as prax's json_handler, @memory 1552,
# @daemon 1096, @backup 778.
#
# The contract is AIPASS_TEST_LOG_DIR in @trigger's form — deliberately NOT a
# sixth spelling invented here.


class TestTestLogDirSeam:
    """The redirect is a function of the environment at the moment of the call."""

    def test_a_redirect_set_before_import_still_follows_a_later_change(self, tmp_path):
        """The defect end to end, in the ordering the repo-root suite creates.

        Export the variable, import, then point it somewhere else and ask where a
        write would land. It must follow the CURRENT value. Before the directory
        stopped being captured this returned the first redirect for the rest of
        the process — the two reds @devpulse reproduced on the CI train.
        """
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
        """The other ordering: nothing exported at import, the variable set
        afterwards. A directory read once at import would answer the real tree
        here and quietly write into src/aipass/prax/prax_json/."""
        code = (
            "import os\n"
            "from aipass.prax.apps.handlers.json import json_handler as shim\n"
            f"os.environ['AIPASS_TEST_LOG_DIR'] = {str(tmp_path)!r}\n"
            "print(shim.get_json_path('probe', 'config'))\n"
        )

        built = Path(_probe(code, ""))

        assert built == tmp_path / "prax" / "prax_json" / "probe_config.json"

    def test_the_write_lands_in_the_redirect_and_the_real_tree_is_untouched(self, tmp_path):
        """The seam is only worth having if the FILE moves, not just the path.

        Asserted on disk, in a process that had the variable exported from the
        start — the arrangement every branch's conftest creates.
        """
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
        """AIPASS_TEST_LOG_DIR='' must not resolve to /prax/prax_json — an empty
        value is how a shell exports "unset", and treating it as a redirect
        aims every branch's writes at the root of the disk."""
        code = (
            "from aipass.prax.apps.handlers.json import json_handler as shim\n"
            "print(shim.get_json_path('probe', 'config'))\n"
        )

        built = Path(_probe(code, ""))

        assert built.parent.parent.name == "prax"
        assert built.parent.name == "prax_json"
        assert built.parts[:2] != (os.sep, "prax")
