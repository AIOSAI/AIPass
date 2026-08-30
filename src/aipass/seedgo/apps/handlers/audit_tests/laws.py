# =================== AIPass ====================
# Name: laws.py
# Description: audit-tests artifact gatekeeper - S1-S9 + T-BUDGET
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
The artifact gatekeeper. Every law is mechanical or it is decoration.

An artifact that fails any law is REFUSED, not published with a warning. The
lane's whole argument is that a confident wrong number is worse than a missing
one, so the validator's default on doubt is refuse.

The laws (design section 4.3):

    S1   not-run is `not_applicable` with a reason, NEVER 0
    S2   every group carries its tier
    S3   no group present in the previous artifact may be absent from this one
         without a `retired_groups` entry naming a ruling
    S4   `group_list` is the published order; `groups` matches it exactly
    S5   a cache-served artifact is stamped, and names what it cannot see
    S6   any `tier == "ai"` group must be `nominate_only`
    S7   (a) an unscored group may not carry a score
         (b) no nomination may carry a delete-family verdict
    S8   any group carrying a score must carry `gate_coverage`
    S9   no mutant record without a `kill_cause` split           (rev 4)
    T-BUDGET  every execution group carries budget + elapsed; exhausted is
              `refused`, never `measured`, never scored

S3/S4 is a NO-VANISHING PROPERTY, not an equality. Revision 1 made it equality
with a core constant, which caught a vanishing group but also blocked every
legitimate addition — the one true rebuild trigger the design review found.
A group may be added freely, may become `not_applicable` freely, and may only
vanish by a recorded ruling.
"""

from typing import Dict, List, Optional

from aipass.seedgo.apps.handlers.audit_tests import spine
from aipass.seedgo.apps.handlers.json import json_handler

# =============================================================================
# VOCABULARY
# =============================================================================

#: Closed verdict vocabulary for nominations (Law S7b). A nomination says a
#: test is suspect; it never says a test is worthless. TAXONOMY section 7 Q1
#: asked where the KEEP/IMPROVE/USELESS verdict lives, and the answer this
#: design gives is that USELESS is not a verdict any tier may emit.
ALLOWED_VERDICTS: frozenset = frozenset({"suspect", "nominated", "improve", "fix"})

#: Verdicts that may never appear anywhere in the document.
DELETE_FAMILY: frozenset = frozenset({"useless", "delete", "remove", "worthless", "dead"})

#: Statuses a group document may carry.
VALID_STATUSES: frozenset = frozenset({"measured", "not_applicable", "refused"})

#: One-line statements stamped into every artifact, so a reader never has to
#: hold the design open beside it.
LAW_STATEMENTS: Dict[str, str] = {
    "L0": "a test proves something when there EXISTS a change to production code that makes it fail",
    "M1": "static NOMINATES, execution CONVICTS",
    "M2": "a measurement that agrees with you everywhere is not evidence",
    "M10": "run suites against a copy - the instrument must not import the tree it measures",
    "M11": "deletion-safety is a row-level probe, not a group",
    "S1": "not-run is not_applicable with a reason, never 0",
    "S2": "every group declares its tier",
    "S3": "no group vanishes without a retired_groups ruling",
    "S4": "group_list is the published order and groups matches it exactly",
    "S5": "a cache-served artifact is stamped and names what it cannot see",
    "S6": "an AI-tier group may only nominate",
    "S7": "an unscored group carries no score; no nomination carries a delete-family verdict",
    "S8": "a scored group must declare what its instrument cannot see",
    "S9": "no mutant record without a kill_cause split",
    "T10": "a run that cannot catch its own planted canary refuses to publish",
    "T-BUDGET": "an execution group that exhausts its budget is refused, never measured",
}


class LawViolation(Exception):
    """An artifact that may not be published, naming the law it broke."""

    def __init__(self, law: str, detail: str) -> None:
        self.law = law
        self.detail = detail
        super().__init__(f"[{law}] {detail}")


# =============================================================================
# INDIVIDUAL LAWS
# =============================================================================


def check_s1_s2(groups: Dict[str, dict]) -> List[str]:
    """S1 + S2 — status, reason and tier discipline.

    The heart of S1: a group that did not run reports `not_applicable` WITH A
    REASON. A `not_applicable` with no reason is indistinguishable from a
    silent skip, and a 0 for a group that never ran is the exact lie this lane
    was built to stop telling.
    """
    problems: List[str] = []

    for name, document in groups.items():
        status = document.get("status")
        if status not in VALID_STATUSES:
            problems.append(f"S1: group '{name}' has status {status!r}, expected one of {sorted(VALID_STATUSES)}")
            continue

        if status in ("not_applicable", "refused") and not document.get("reason"):
            problems.append(f"S1: group '{name}' is {status} without a reason")

        if status != "measured" and document.get("score") == 0:
            problems.append(f"S1: group '{name}' is {status} but carries score 0 - not-run is not_applicable, never 0")

        if not document.get("tier"):
            problems.append(f"S2: group '{name}' declares no tier")

    return problems


def check_s3_s4(
    group_list: List[str],
    groups: Dict[str, dict],
    previous_group_list: Optional[List[str]],
    retired_groups: List[dict],
) -> List[str]:
    """S3 + S4 — the no-vanishing property, and list/document agreement.

    `previous_group_list is None` means first run for this (target, adapter)
    pair: the diff cannot run, and the caller stamps `group_baseline` to say
    so. A check that silently did not run is exactly what section 10 exists to
    prevent, so its absence is recorded rather than assumed harmless.
    """
    problems: List[str] = []

    if list(groups.keys()) != list(group_list):
        problems.append(
            f"S4: groups keys {list(groups.keys())} do not match group_list {list(group_list)} in content or order"
        )

    if previous_group_list is None:
        return problems

    retired_names = {entry.get("group") for entry in retired_groups}
    for name in previous_group_list:
        if name in group_list:
            continue
        if name not in retired_names:
            problems.append(
                f"S3: group '{name}' was published previously and is absent now, "
                f"with no retired_groups entry naming a ruling"
            )

    for entry in retired_groups:
        if not entry.get("ruling"):
            problems.append(f"S3: retired_groups entry for '{entry.get('group')}' names no ruling")

    return problems


def check_s6_s7(groups: Dict[str, dict]) -> List[str]:
    """S6 + S7 — AI advisory-only, and the two verdict-shape rules."""
    problems: List[str] = []

    for name, document in groups.items():
        if document.get("tier") == "ai" and document.get("kind") != "nominate_only":
            problems.append(f"S6: AI-tier group '{name}' is not nominate_only")

        if not spine.is_scored(name) and document.get("score") is not None:
            problems.append(f"S7a: group '{name}' is not in SCORED_GROUPS but carries a score")

        for nomination in document.get("nominations", []):
            verdict = str(nomination.get("verdict", "")).lower()
            if verdict in DELETE_FAMILY:
                problems.append(
                    f"S7b: group '{name}' emits delete-family verdict {verdict!r} - "
                    f"the vocabulary is closed to {sorted(ALLOWED_VERDICTS)}"
                )
            elif verdict and verdict not in ALLOWED_VERDICTS:
                problems.append(f"S7b: group '{name}' emits unknown verdict {verdict!r}")

    return problems


def check_s8(groups: Dict[str, dict]) -> List[str]:
    """S8 — a score without a declared blind spot is a refusal.

    A hard 100/0 gate that cannot state what it is blind to is precisely the
    species this lane exists to catch. `blind` must be non-empty: every real
    instrument is blind to something, and an empty list is a claim of
    omniscience nobody has earned.
    """
    problems: List[str] = []

    for name, document in groups.items():
        if document.get("score") is None:
            continue

        coverage = document.get("gate_coverage")
        if not coverage:
            problems.append(f"S8: scored group '{name}' carries no gate_coverage block")
            continue

        if not coverage.get("mechanism"):
            problems.append(f"S8: gate_coverage for '{name}' names no mechanism")
        if not coverage.get("blind"):
            problems.append(
                f"S8: gate_coverage for '{name}' declares nothing blind - every instrument is blind to something"
            )

    return problems


def check_s9(groups: Dict[str, dict]) -> List[str]:
    """S9 — no mutant record without a kill_cause split (rev 4 contract).

    Binding on `oracle_execution` and the adapter's mutation groups. While
    they report `not_applicable: "not built"` there is nothing to check, which
    is the point: the requirement is written before the capability so it
    cannot be skipped under delivery pressure later.
    """
    problems: List[str] = []

    for name, document in groups.items():
        for record in document.get("mutants", []):
            if "kill_cause" not in record:
                problems.append(
                    f"S9: group '{name}' publishes a mutant record with no kill_cause - "
                    f"an unsplit kill record is a refusal, not a warning"
                )
                break

    return problems


def check_budget(groups: Dict[str, dict]) -> List[str]:
    """T-BUDGET — execution groups carry a budget, and exhaustion refuses.

    An exhausted group may never be `measured` and may never carry a score: a
    partial suite that reports a number is forgery by omission.
    """
    problems: List[str] = []

    for name, document in groups.items():
        if document.get("tier") != "exec":
            continue
        if document.get("status") == "not_applicable":
            continue

        if document.get("budget_seconds") is None:
            problems.append(f"T-BUDGET: execution group '{name}' carries no budget_seconds")
        if document.get("elapsed_seconds") is None:
            problems.append(f"T-BUDGET: execution group '{name}' carries no elapsed_seconds")

        if document.get("budget_exhausted"):
            if document.get("status") != "refused":
                problems.append(
                    f"T-BUDGET: group '{name}' exhausted its budget but is {document.get('status')!r}, not 'refused'"
                )
            if document.get("score") is not None:
                problems.append(f"T-BUDGET: group '{name}' exhausted its budget and still carries a score")

    return problems


def check_s5(cache: dict) -> List[str]:
    """S5 — a cache-served artifact is stamped and names what it cannot see."""
    problems: List[str] = []

    if cache.get("served_from_cache") and not cache.get("stamp"):
        problems.append("S5: artifact is cache-served but carries no stamp")
    if cache.get("not_fingerprinted") is None:
        problems.append("S5: cache block declares no not_fingerprinted list")

    return problems


# =============================================================================
# THE GATE
# =============================================================================


def validate(document: dict, previous_group_list: Optional[List[str]] = None) -> List[str]:
    """Run every law against an assembled artifact. Returns problems found.

    An empty list means publishable. This function never raises on a law
    violation — the caller decides between refusing and reporting — but it
    also never returns a partial verdict: every law runs on every call, so a
    reader sees all the reasons at once rather than one per attempt.
    """
    groups = document.get("groups", {})
    group_list = document.get("group_list", [])
    retired = document.get("retired_groups", [])

    problems: List[str] = []
    problems.extend(check_s1_s2(groups))
    problems.extend(check_s3_s4(group_list, groups, previous_group_list, retired))
    problems.extend(check_s6_s7(groups))
    problems.extend(check_s8(groups))
    problems.extend(check_s9(groups))
    problems.extend(check_budget(groups))
    problems.extend(check_s5(document.get("cache", {})))

    if "group_baseline" not in document:
        problems.append("S3: artifact carries no group_baseline - a check that did not run must say so")

    return problems


def enforce(document: dict, previous_group_list: Optional[List[str]] = None) -> None:
    """Validate and raise LawViolation on the first problem found.

    Used where publication is the next statement and a partial artifact must
    not reach disk.
    """
    problems = validate(document, previous_group_list)
    if problems:
        law = problems[0].split(":", 1)[0]
        # An artifact refused for a law violation is an operational event, not
        # a detail: it is the record that the lane declined to publish a number
        # rather than publishing a wrong one.
        json_handler.log_operation(
            "artifact_refused",
            {
                "law": law,
                "problem_count": len(problems),
                "problems": problems,
                "target": document.get("target", {}).get("name"),
            },
        )
        raise LawViolation(law, "; ".join(problems))
