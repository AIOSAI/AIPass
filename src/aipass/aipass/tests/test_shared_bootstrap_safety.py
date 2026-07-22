# =================== AIPass ====================
# Name: test_shared_bootstrap_safety.py
# Description: Guard test — shared/ must stay stdlib-only (loads pre-drone)
# Version: 1.0.0
# Created: 2026-06-10
# Modified: 2026-06-10
# =============================================

"""Guard test: importing aipass.aipass.shared must NOT pull in branch dependencies.

The shared/ package is used by bootstrap.py during `aipass init` on fresh machines
where drone/prax/trigger don't exist yet. If shared/ ever imports a branch
dependency, init breaks. This test enforces the invariant via subprocess isolation.
"""

import subprocess
import sys

ALLOWED_PREFIXES = ("aipass.aipass.shared",)
ALLOWED_EXACT = {"aipass", "aipass.aipass"}

SCRIPT = """\
import sys

import aipass.aipass.shared.json_handler
import aipass.aipass.shared.json_ops
import aipass.aipass.shared.project_home
import aipass.aipass.shared.registry_discovery
import aipass.aipass.shared.scaffold_content

bad = []
for name in sorted(sys.modules):
    if not name.startswith("aipass"):
        continue
    if name in {allowed_exact}:
        continue
    if any(name.startswith(p) for p in {allowed_prefixes}):
        continue
    bad.append(name)

if bad:
    print("FAIL: branch dependencies loaded: " + ", ".join(bad))
    sys.exit(1)
print("OK")
""".format(
    allowed_exact=repr(ALLOWED_EXACT),
    allowed_prefixes=repr(ALLOWED_PREFIXES),
)


class TestSharedBootstrapSafety:
    def test_no_branch_deps_loaded(self):
        """Importing all shared modules must not pull in any branch code."""
        result = subprocess.run(
            [sys.executable, "-c", SCRIPT],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"shared/ pulled in branch dependencies:\n{result.stdout}\n{result.stderr}"
