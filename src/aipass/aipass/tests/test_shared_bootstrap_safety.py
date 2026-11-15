# =================== AIPass ====================
# Name: test_shared_bootstrap_safety.py
# Description: Guard test — shared/ and init's pure files log through prax and load no other branch
# Version: 2.0.0
# Created: 2026-06-10
# Modified: 2026-11-15
# =============================================

"""Tests for shared/project_home.py, shared/json_ops.py, apps/handlers/init/bootstrap.py and scaffold_manifest.py."""

# prax ships in the same wheel as these files, so it is importable wherever they are; @spawn imports
# shared/ into its own process, so any other branch loaded here would ride into spawn too.

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(covered_elsewhere) — the modules' own return values; see tests/test_project_home.py,
# sentry: no-test-needed(covered_elsewhere) — tests/test_bootstrap.py and tests/test_adopt.py

import subprocess
import sys

MODULES = (
    "aipass.aipass.shared.json_ops",
    "aipass.aipass.shared.project_home",
    "aipass.aipass.shared.registry_discovery",
    "aipass.aipass.shared.scaffold_content",
    "aipass.aipass.apps.handlers.init.bootstrap",
    "aipass.aipass.apps.handlers.init.scaffold_manifest",
)
LOGGING = (
    "aipass.aipass.shared.json_ops",
    "aipass.aipass.shared.project_home",
    "aipass.aipass.apps.handlers.init.bootstrap",
    "aipass.aipass.apps.handlers.init.scaffold_manifest",
)

SCRIPT = """\
import importlib
import sys

mods = {{m: importlib.import_module(m) for m in {modules!r}}}
import aipass.prax

bad = sorted(
    n for n in sys.modules
    if n.startswith("aipass.") and not n.startswith(("aipass.aipass", "aipass.prax"))
)
if bad:
    print("FAIL other branches loaded: " + ", ".join(bad))
    sys.exit(1)
stdlib = [m for m in {logging!r} if mods[m].logger is not aipass.prax.logger]
if stdlib:
    print("FAIL not on prax's logger: " + ", ".join(stdlib))
    sys.exit(1)
print("OK")
""".format(modules=MODULES, logging=LOGGING)


class TestSharedBootstrapSafety:
    def test_the_four_logging_files_use_prax_and_no_other_branch_loads(self):
        result = subprocess.run(
            [sys.executable, "-c", SCRIPT],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
        assert result.stdout.strip() == "OK"
