# =================== AIPass ====================
# Name: tests/parked/conftest.py
# Version: 1.0.0
# Description: Collection barrier for parked tests under this directory
# Branch: hooks
# Layer: tests
# Created: 2026-09-07
# Modified: 2026-09-07
# =============================================

"""Collection barrier for the parked tests under this directory.

`test_presence(disabled).py` covers presence.py, which was retired on 2026-09-07
(FPLAN-0495 item 4) and now sits beside it as `apps/modules/presence(disabled).py`.
Both are kept for revival until a session cycle proves nothing was connected —
kept, not run.

The `(disabled)` suffix does not stop pytest: `test_presence(disabled).py` still
matches the default `test_*.py` glob, and the first full-suite run after the park
died at collection on `ImportError: cannot import name 'presence'`. The suffix
stops a dotted-path import; only this file stops collection.

A conftest and not a `norecursedirs` line, for the reason @memory's identical
barrier gives: CI runs the whole repo from its root, where the ROOT pyproject is
the config in force and a branch-level ini is never read. A conftest is loaded
from its own directory whatever the rootdir — the one property that holds on the
lane that broke.
"""

collect_ignore_glob = ["*"]
