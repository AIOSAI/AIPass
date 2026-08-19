# ===================AIPASS====================
# META DATA HEADER
# Name: tests/parked/conftest.py
# Date: 2026-08-18
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""Collection barrier for the parked code under this directory.

Four of the files in `unwired_handlers_20260813/` are the TESTS that covered
handlers which left the tree on 2026-08-13. They are kept for revival, not to
run: the code they exercise is parked beside them. Their `(disabled)` suffix
stops anything importing them by dotted path, but it does NOT stop pytest --
`test_storage(disabled).py` still matches the default `test_*.py` glob, and the
whole park got collected and failed 66 times the first time it landed here.

The barrier is a conftest and not a `norecursedirs` line in this branch's
pytest.ini on purpose: CI runs the whole repo from its root, where the ROOT
config is the one in force and this branch's ini is never read. A conftest is
loaded from its own directory whatever the rootdir, which is the only property
that makes this hold on the lane that broke.

Pinned by `tests/test_symbolic_parked.py::TestParkIsNeverCollected`, which runs
a real collection over this directory in a subprocess.
"""

collect_ignore_glob = ["*"]
