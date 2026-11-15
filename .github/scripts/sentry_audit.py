"""CI gate: the startup ratchet, the name ratchet (advisory) and the standards audit over every branch.

One branch list feeds all three, so no file is gated on a branch the audit does not score.
"""

import sys
from pathlib import Path

from aipass.sentry.apps.modules.door_audit import audit_branch, load_bypass_rules, name_ratchet, startup_ratchet

THRESHOLD = 100

# Advisory: True makes a new name or home-path line fail the job.
NAME_RATCHET_GATES = False

# Standards consulted (scored + not_applicable): 83 aipass checkers + diagnostics. Moves by hand only, so a
# checker that vanishes (retired, or its import broken) turns this job red instead of averaging one fewer.
EXPECTED_STANDARDS = 84

src = Path("src/aipass")
pack = src / "sentry/apps/handlers/aipass_standards"

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

# Gated: tracked README.md and branch prompts only; every cap is read from its owner, never kept here.
ratchet = startup_ratchet.run(branches)
for line in ratchet["report"]:
    print(line)
if not ratchet["passed"]:
    print(f"\nSTARTUP RATCHET FAILED: {len(ratchet['failures'])} gated file(s) over cap or unmeasurable")
    for line in ratchet["failure_lines"]:
        print(line)
    print("\n  Shrink the file, or move the cap at its OWNER - never here. The gate reads the owner's number.")
    sys.exit(1)
print()

names = name_ratchet.run(Path("."))
for line in names["report"]:
    print(line)
if not names["passed"]:
    verdict = "FAILED" if NAME_RATCHET_GATES else "RED (advisory - not gating yet)"
    print(f"\nNAME RATCHET {verdict}: {len(names['over'])} file/rule pair(s) above baseline")
    for line in names["failure_lines"]:
        print(line)
    print("\n  Take the name or the home path out of the line. The baseline only ever goes down.")
    if NAME_RATCHET_GATES:
        sys.exit(1)
print()

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
