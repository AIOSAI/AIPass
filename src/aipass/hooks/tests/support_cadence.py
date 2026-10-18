# =================== AIPass ====================
# Name: support_cadence.py
# Description: Helpers shared by test_cadence.py and test_cadence_regroup.py: module path, cache reset, state writer
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Helpers for the cadence tests (no test_ prefix: never collected).

conftest's _restore_cadence_globals puts back the caches _reset_module_globals writes.
"""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import json
import os
import time

from aipass.hooks.apps.modules import cadence


def _kept_redirect() -> dict[str, str]:
    """The json redirect a clear=True wipe must hand back, or the loggers write the live <branch>_json."""
    return {"AIPASS_TEST_LOG_DIR": os.environ["AIPASS_TEST_LOG_DIR"]}


MODULE = "aipass.hooks.apps.modules.cadence"


def _reset_module_globals():
    """Reset module-level caches between tests (also = simulate a new process)."""
    cadence._turn = None
    cadence._config = None
    cadence._turn_degraded = None


def _write_state(tmp_path, turn, token=-1, session="test-session", aged=True):
    """Write a cadence state file. aged=True backdates mtime past the debounce
    window so it reads as a PREVIOUS turn; aged=False = sibling in same turn."""
    state_file = tmp_path / f"aipass-cadence-{session}.json"
    state_file.write_text(json.dumps({"turn": turn, "token": token}), encoding="utf-8")
    if aged:
        old = time.time() - 10
        os.utime(state_file, (old, old))
    return state_file
