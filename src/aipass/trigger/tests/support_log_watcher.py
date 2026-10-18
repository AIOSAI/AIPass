# =================== AIPass ====================
# Name: support_log_watcher.py
# Description: Shared synthetic log paths for test_log_watcher.py and test_log_watcher_state.py
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Constants for the tests of apps/handlers/log_watcher.py (no test_ prefix: never collected)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

from pathlib import Path, PurePosixPath

# Never touched on disk; POSIX on purpose: the parsers split on "/" segments.
_SYNTHETIC_HOME = PurePosixPath("/synthetic/home")

_BRANCH_LOG_PATH = str(Path(_SYNTHETIC_HOME) / "src" / "aipass" / "flow" / "logs" / "flow.log")
