# =================== AIPass ====================
# Name: support_test_monitoring_handlers.py
# Description: Shared helpers for test_monitoring_handlers.py and its split siblings
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Helpers shared by the monitoring handler test files (no test_ prefix: never collected)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — BranchDetector, covered by tests/test_monitoring_handlers.py

from pathlib import Path, PurePosixPath
from unittest.mock import patch

from aipass.prax.apps.handlers.monitoring import branch_detector

# POSIX strings fed through a mocked Path, never a disk; no home directory in the root.
_HOME = PurePosixPath("/", "ws")
_WS = _HOME / "Projects" / "AIPass"
_ECO = _WS / "src" / "aipass"


def _import_branch_detector():
    """The branch_detector module, bound at the top of this file."""
    return branch_detector


def _make_detector_with_branches(mod, branches: dict | None = None):
    """Create a BranchDetector with controlled state (no filesystem access)."""
    with patch.object(mod.BranchDetector, "_load_registry"):
        detector = mod.BranchDetector()
    if branches is None:
        branches = {
            str(_ECO / "prax"): "PRAX",
            str(_ECO / "seedgo"): "SEEDGO",
            str(_ECO / "flow"): "FLOW",
            str(_ECO / "cli"): "CLI",
            str(_ECO / "ai_mail"): "AI_MAIL",
        }
    for path_str, name in branches.items():
        detector.branch_map[path_str] = name
        detector.known_branches.add(name)
    return detector


def _write_registry(root: Path, payload: str) -> None:
    """Write AIPASS_REGISTRY.json under the repo root the loader is pointed at."""
    (root / "AIPASS_REGISTRY.json").write_text(payload, encoding="utf-8")
