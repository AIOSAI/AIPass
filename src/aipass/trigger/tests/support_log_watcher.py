# =================== AIPass ====================
# Name: support_log_watcher.py
# Description: Shared synthetic log paths for test_log_watcher.py and test_log_watcher_state.py
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Constants for the tests of apps/handlers/log_watcher.py (no test_ prefix: never collected).

Moved out of test_log_watcher.py when it was split along the unit under test
(fleet green, oversize_test_file): the parsing file and the state file both
hand the watcher a branch log path built from the same synthetic root.
"""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

from pathlib import Path, PurePosixPath

# Synthetic path root. detect_branch_from_path, _should_process and
# classify_log_path parse a path STRING and never touch disk, so this is an
# input under test, not a location — but a literal /home/user or /tmp prefix
# reads as an assumption about the machine, so the root is built instead.
# The POSIX shape IS part of the contract: these functions split on aipass/
# and logs/ segments, so the separator must stay "/" on every platform.
_SYNTHETIC_HOME = PurePosixPath("/synthetic/home")

_BRANCH_LOG_PATH = str(Path(_SYNTHETIC_HOME) / "src" / "aipass" / "flow" / "logs" / "flow.log")
