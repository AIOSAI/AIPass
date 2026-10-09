# =================== AIPass ====================
# Name: support_doctor.py
# Description: Helpers shared by test_doctor.py and test_doctor_home.py (no test_ prefix: never collected)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Helpers shared by the doctor test files: the scratch-home edge."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import os
from unittest.mock import patch


def _home_at(home):
    """Point Path.home() at a scratch dir through its edge, the environment (USERPROFILE on Windows)."""
    return patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)})
