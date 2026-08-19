# =================== AIPass ====================
# Name: conftest.py
# Description: screen_lock skill test configuration — log redirect and path setup
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-08-14
# =============================================

"""
screen_lock skill test configuration.

Redirects Prax logger output to a temp dir so test runs never write to the
production log files, and puts the src root on sys.path so `aipass.*` resolves
without a full pip install.
"""

import os
import sys
import tempfile
from pathlib import Path

if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="screen_lock_test_logs_")

_src_root = Path(__file__).resolve().parents[5]
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))
