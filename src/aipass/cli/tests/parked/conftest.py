# =================== AIPass ====================
# Name: tests/parked/conftest.py
# Description: Collection barrier for the parked code under this directory
# Version: 1.0.0
# Created: 2026-08-19
# Modified: 2026-08-19
# =============================================

"""Collection barrier for the parked code under this directory.

`scaffold(disabled).py` drops the `test_` prefix, which is what actually
keeps `python_files = test_*.py` from matching it — the `(disabled)` suffix
alone is a habit, not enforcement (@memory proved a `test_`-prefixed file is
collected regardless of suffix, 2026-08-19). This conftest is the real
barrier: `collect_ignore_glob` answers zero for this directory no matter what
anything in it is named.

A conftest and not a `norecursedirs` line in this branch's pytest.ini on
purpose: CI runs the whole repo from its root, where the root config is the
one in force and this branch's ini is never read there. A conftest loads
from its own directory regardless of rootdir.

Pinned by `tests/test_parked_is_not_collected.py`, which runs real pytest
collection against this directory rather than trusting the convention.
"""

collect_ignore_glob = ["*"]
