"""CI gate: run seedgo standards audit across all branches."""

import sys
from pathlib import Path

from aipass.seedgo.apps.handlers.audit.branch_audit import audit_branch
from aipass.seedgo.apps.handlers.bypass.bypass_handler import load_bypass_rules

THRESHOLD = 100

# Pack-count tripwire (DPLAN-0323 phase 6). A standard must never leave the
# gate silently: retire a checker, or break its import, and the audit would
# quietly average one fewer standard, still print 100, and this job would stay
# green. The number moves ONLY by hand, in the same commit that adds or retires
# a standard. Today: 46 *_check.py in the aipass pack + the diagnostics checker.
#
# Counted = every standard the audit CONSULTED: the ones that scored plus the
# ones that reported not_applicable (measured nothing by design and stay out of
# the average - trinity on a clean checkout, where .trinity/ is machine-local
# and gitignored, so this job never sees 47 scored). A checker that crashes
# scores 0 and is still counted. Only a standard that VANISHES trips this - the
# first board with the tripwire caught exactly the not_applicable case, which
# is why the count reads results, not scores.
EXPECTED_STANDARDS = 47

src = Path("src/aipass")
pack = src / "seedgo/apps/handlers/aipass_standards"

branches = []
for d in sorted(src.iterdir()):
    if d.is_dir() and (d / "apps").is_dir():
        entry = d / "apps" / f"{d.name}.py"
        branches.append(
            {
                "name": d.name,
                "path": str(d),
                "entry_file": str(entry) if entry.exists() else "",
            }
        )

failed = []
for branch in branches:
    bypass_rules = load_bypass_rules(branch["path"])
    result = audit_branch(branch, bypass_rules, pack_path=pack)
    scored = sorted(result.get("scores", {}))
    stood_down = sorted(
        name for name, r in result.get("results", {}).items() if isinstance(r, dict) and r.get("not_applicable") is True
    )
    consulted = sorted(set(scored) | set(stood_down))
    if len(consulted) != EXPECTED_STANDARDS:
        print(
            f"\nTRIPWIRE: {branch['name']} consulted {len(consulted)} standards "
            f"({len(scored)} scored, {len(stood_down)} not applicable), expected "
            f"{EXPECTED_STANDARDS} - a standard left the gate silently "
            f"(or one was added without moving EXPECTED_STANDARDS)"
        )
        print("  scored: " + ", ".join(scored))
        print("  not applicable: " + (", ".join(stood_down) or "-"))
        sys.exit(1)
    avg = result.get("average", 0)
    detail = f"{len(scored)} scored"
    if stood_down:
        detail += f", not applicable: {', '.join(stood_down)}"
    print(f"  {branch['name']:>12}: {avg:.0f}%  ({detail})")
    if avg < THRESHOLD:
        failed.append((branch["name"], avg, result))

if failed:
    print(f"\nFAILED: {len(failed)} branch(es) below {THRESHOLD}%")
    for name, score, result in failed:
        print(f"  {name}: {score:.0f}%")
        # Name the failing standards + the specific checks that did not pass,
        # so CI logs say WHY (not just the percentage). Critical for diagnosing
        # working-tree-vs-clean-checkout divergence.
        scores = result.get("scores", {})
        results = result.get("results", {})
        for std, sc in scores.items():
            if sc < 100:
                checks = results.get(std, {}).get("checks", [])
                msgs = [c.get("message", "") for c in checks if not c.get("passed", True)]
                detail = " | ".join(m for m in msgs if m)[:400]
                print(f"      └ {std}: {sc:.0f}%  {detail}")
    sys.exit(1)
else:
    print(f"\nAll {len(branches)} branches pass (>={THRESHOLD}%)")
