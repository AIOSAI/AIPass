"""CI gate: run seedgo standards audit across all branches.

Three gates, one job (DPLAN-0347 phase 5, DPLAN-0350):

1. The STARTUP RATCHET holds every branch's README.md and branch prompt at the
   caps their owners publish. It runs FIRST because it is 36 file reads against
   two caps — under a second, where the audit below runs pyright over eighteen
   branches. An over-cap README is self-diagnosing: its red names the file, the
   size, the cap and the owner, and needs nothing the audit would have printed.
   When it is green (the ordinary case) everything after it runs exactly as it
   did before the ratchet existed.
2. The NAME RATCHET (DPLAN-0350) holds the owner's first name and a person's
   home path at the baseline taken when the sweep finished: a NEW line is red.
   ADVISORY while NAME_RATCHET_GATES is False - it prints its red and the job
   carries on. Flipping it is a decision, made here, in one line.
3. The STANDARDS AUDIT scores every branch against the aipass pack and holds
   the fleet at 100%, with the pack-count tripwire guarding the average itself.

They share the branch list built once below, deliberately: two walks of
src/aipass could drift, and a file gated on a branch the audit does not score
(or the reverse) is a hole nobody would see until it was used.
"""

import sys
from pathlib import Path

from aipass.seedgo.apps.handlers.audit.branch_audit import audit_branch
from aipass.seedgo.apps.handlers.bypass.bypass_handler import load_bypass_rules
from aipass.seedgo.apps.handlers.context_standards import name_ratchet, startup_ratchet

THRESHOLD = 100

# The name ratchet lands advisory (DPLAN-0350): its red prints, the job goes on.
# True makes a NEW name or home-path line fail this job. @devpulse's call, once
# the owner has ruled on the exempt set (settings.json, hook logs, suspend/).
NAME_RATCHET_GATES = False

# Pack-count tripwire (DPLAN-0323 phase 6). A standard must never leave the
# gate silently: retire a checker, or break its import, and the audit would
# quietly average one fewer standard, still print 100, and this job would stay
# green. The number moves ONLY by hand, in the same commit that adds or retires
# a standard. Today: 48 *_check.py in the aipass pack + the diagnostics checker.
#
# Counted = every standard the audit CONSULTED: the ones that scored plus the
# ones that reported not_applicable (measured nothing by design and stay out of
# the average - trinity on a clean checkout, where .trinity/ is machine-local
# and gitignored, so this job never sees 47 scored). A checker that crashes
# scores 0 and is still counted. Only a standard that VANISHES trips this - the
# first board with the tripwire caught exactly the not_applicable case, which
# is why the count reads results, not scores.
EXPECTED_STANDARDS = 80  # +4 on 2026-09-21: tests/ joined the audit corpus (owner 21:20), so router_assert,
#                          oversize_test_file, import_site and through_the_command became scored rows.
#                          A branch with no test files reports them not_applicable, so the count holds there too.
#                          +1 the same day: named_encoding, test template v1 item 21.
#                          +1 on 2026-09-22: literal_path, test template v1 item 22.
#                          +1 the same day: file_top, test template v1 items 5, 6 and 7.
#                          +1 the same day: mock_console, test template v1 item 14.
#                          +1 the same day: state_leak, test template v1 item 18.
#                          +1 the same day: conftest_fixtures, test template v1 item 20.
#                          +2 the same day: no_product_call and duplicate_test, the first two CRACK
#                          classes from the eyes-on review of backup's tests. Not template items -- the
#                          ten above passed all 107 tests that carry a finding. These measure what shape
#                          cannot see: whether a test reaches the product at all, and whether another
#                          test in the same file already asserts everything it asserts.
#                          +2 the same day: discarded_patch and weak_oracle, CRACK classes R and D
#                          (dispatch eb5602d0). R convicts a mock of the branch's OWN code that nothing
#                          ever observes; D convicts a test whose WHOLE oracle cannot fail. D is scored
#                          only on the forms that cannot be right -- the soft forms ride as a count.
#                          +2 the same day: flag_never_passed and uncalled_public_function, CRACK classes
#                          P and O (dispatch cb55cc37). Both are branch_level -- the first tests-only
#                          rules that compare a branch's apps/ against its whole tests/ tree. P convicts
#                          a --flag a parser reads that no test ever hands it; O convicts a public
#                          function of a test file's DECLARED SUBJECT that no test calls.
#                          +4 on 2026-09-23: constant_predicate, sleep_in_test, stdlib_patch and
#                          unused_conftest_fixture, CRACK classes C, N, Q and G (dispatch f66ac9d0).
#                          C convicts a bool-returning constant lambda handed to the product; N convicts
#                          any sleep in a test; Q convicts a patch whose target resolves to stdlib rather
#                          than aipass; G convicts a conftest fixture the branch never requests. C and Q
#                          score only what cannot be right -- inert None stubs and unresolvable local
#                          targets ride as counts. Measured: cli and seedgo both consult 69.
#                          +3 the same day: declared_pass_contradiction, self_set_assert and
#                          unconsumed_side_effect, CRACK classes H, E and F (dispatch 0035b7bb) --
#                          the last of the mechanical classes. H convicts a declared pass the file
#                          itself breaks; E convicts an assert that only reads back what the test
#                          wrote; F convicts a multi-answer side_effect no assertion counts. H and E
#                          score only what cannot be right -- prose declarations, dotted stdlib names
#                          and durability re-reads ride as counts. Measured: cli and seedgo consult 72.
#                          +1 the same day: accepted_and_never_used_parameter, CRACK class M (dispatch
#                          a752532e) -- the pack's first PRODUCTION-only crack rule, and the first that
#                          reads a branch's whole apps/ tree to decide who owns a signature. It convicts
#                          a parameter no path in the body reads, and acquits four shapes that say the
#                          signature belongs to somebody else: the branch never calls the function, the
#                          name is handed off as a value, the def is an except-ImportError shim, or the
#                          name is defined twice. Class L was CHECKED and NOT built -- unused_function
#                          already convicts its specimen. Measured: cli and seedgo consult 73.
#                          +2 on 2026-09-25: stale_header_date and declared_pass_symbol_resolves, pair
#                          one of the template compliance review (dispatch 303ca9e3). stale_header_date
#                          is the first checker to READ GIT: a Modified: date older than the file's last
#                          commit (an uncommitted file is judged as of today). It DECLINES on a shallow
#                          clone, so this job's fetch-depth: 0 is load-bearing for it.
#                          declared_pass_symbol_resolves convicts a declared-pass name that resolves
#                          nowhere in apps/ or the stdlib. Measured: cli and seedgo consult 75.
#                          +2 on 2026-09-25: retired_token_docstring and module_scope_side_effect, pair
#                          two of the template compliance review (dispatch 41554e9d). The first convicts
#                          the retired v4 test_quality keyword vocabulary (c1e0eeed^) used as bait in a
#                          test docstring; the second convicts a side effect a test_*.py runs at import
#                          (conftest.py exempt). Measured: cli and seedgo consult 77.
#                          +1 on 2026-09-25: subprocess_text_true, pair three (dispatch 2122a278) - a
#                          subprocess call in text mode with no encoding=, named_encoding's hazard one
#                          pipe over (named_encoding judges open/read_text/write_text only, so this is
#                          a new standard, not a widening). Measured: cli and seedgo consult 78.
#                          +1 on 2026-09-25: os_walk_onerror, product pack pair one (dispatch 8314efac) - an
#                          os.walk call with no onerror=, which swallows scandir errors. The first rule of the
#                          product pack; its sibling logged_fallback was measured and STOPPED for the owner.
#                          Measured: cli consults 79.
#                          +1 on 2026-09-25: logged_fallback, product pack pair one's second half (dispatch
#                          3144dd93, owner 12:17 'narrow it then land it') - an except returning a literal
#                          default the success path can also return; silent_catch's log acquittal closed.

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

# -----------------------------------------------------------------------------
# GATE 1 — THE STARTUP RATCHET (DPLAN-0347 phase 5)
# -----------------------------------------------------------------------------
# README.md and .aipass/aipass_local_prompt.md only: both are tracked in git, so
# this checkout measures what a local audit measures. .trinity/ and
# DASHBOARD.local.json are gitignored - CI never sees them, and a gate that
# measures nothing passes by accident forever. docs/ pages are measured by the
# advisory lane but not gated: the fleet holds pages that predate the 20,000-char
# rule. Stabilise, do not expand.
#
# No cap number lives here or in the ratchet module. Every cap is read from its
# owner on every run (seedgo's pack.json, @hooks' BRANCH_CHAR_BUDGET) and a cap
# that cannot be read is a RED naming the owner, never a remembered default.
# A file measuring exactly its cap passes; over is strictly greater.
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

# -----------------------------------------------------------------------------
# GATE 2 — THE NAME RATCHET (DPLAN-0350) - ADVISORY UNTIL NAME_RATCHET_GATES
# -----------------------------------------------------------------------------
# Every tracked file (git ls-files) for the owner's first name, and every .md
# and *_content.py for a person's home path, held at the baseline in
# context_standards/name_ratchet_baseline.json. The exemptions (the culture
# doc, changelogs, plans, the hook logs, settings.json, suspend/) live in the
# module and its docstring, never here. Every printed line is masked.
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

# -----------------------------------------------------------------------------
# GATE 3 — THE STANDARDS AUDIT
# -----------------------------------------------------------------------------
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
