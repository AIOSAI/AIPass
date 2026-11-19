# =================== AIPass ====================
# Name: support_bootstrap.py
# Description: Helpers shared by test_bootstrap.py and test_bootstrap_update.py (no test_ prefix: never collected)
# Version: 1.0.1
# Created: 2026-10-08
# Modified: 2026-11-17
# =============================================

"""Helpers shared by the bootstrap test files: the AIPASS_HOME the detector must find."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that the module parses and imports

from pathlib import Path

import aipass


def _expected_aipass_home() -> str:
    """The AIPASS_HOME the detector must find in a source checkout, derived independently of it.

    project_home._detect_aipass_home asks drone's resolver, which names the repo root here (AIPASS_HOME,
    or the venv's parent holding AIPASS_REGISTRY.json). This reads the repo root off the package itself,
    so the pin is a second derivation and not a restatement of the code under test.
    """
    return str(Path(aipass.__file__).resolve().parent.parent.parent)
