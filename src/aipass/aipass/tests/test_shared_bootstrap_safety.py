# =================== AIPass ====================
# Name: test_shared_bootstrap_safety.py
# Description: Guard test — shared/'s four modules must stay stdlib-only (pre-drone)
# Version: 1.1.0
# Created: 2026-06-10
# Modified: 2026-10-17
# =============================================

"""Tests that shared/project_home.py and its sibling shared/ modules import with no branch dependency."""

# bootstrap.py imports shared/ at `aipass init`, before drone/prax/trigger exist: no branch imports.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — project_home, registry_discovery and scaffold_content's
# seedgo: no-test-needed(covered_elsewhere) — own return values; see tests/test_project_home.py and tests/test_adopt.py

import subprocess
import sys

ALLOWED_PREFIXES = ("aipass.aipass.shared",)
ALLOWED_EXACT = {"aipass", "aipass.aipass"}

SCRIPT = """\
import sys

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
            encoding="utf-8",
            timeout=30,
        )
        assert result.returncode == 0, f"shared/ pulled in branch dependencies:\n{result.stdout}\n{result.stderr}"
