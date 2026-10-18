# =================== AIPass ====================
# Name: laws.py
# Description: audit-tests artifact gatekeeper - S1-S9 + T-BUDGET
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-10-17
# =============================================

"""
The artifact gatekeeper. Every law is mechanical or it is decoration.

A failing artifact is refused, never published with a warning. LAW_STATEMENTS
carries each law's one line. S3 is a no-vanishing property, not equality: groups
may be added or go `not_applicable` freely, and vanish only by a recorded ruling.
"""

from typing import Dict, List, Optional

from aipass.seedgo.apps.handlers.audit_tests import spine
from aipass.seedgo.apps.handlers.json import json_handler

#: Closed verdict vocabulary for nominations (Law S7b): no tier may call a test useless.
ALLOWED_VERDICTS: frozenset = frozenset({"suspect", "nominated", "improve", "fix"})

DELETE_FAMILY: frozenset = frozenset({"useless", "delete", "remove", "worthless", "dead"})

VALID_STATUSES: frozenset = frozenset({"measured", "not_applicable", "refused"})

#: `measured`: every subtracted path was observed; `partly declared`: one rests on a declaration.
CARRIER_ATTRIBUTION: frozenset = frozenset({"measured", "partly declared"})

LAW_STATEMENTS: Dict[str, str] = {
    "L0": "a test proves something when there EXISTS a change to production code that makes it fail",
    "M1": "static NOMINATES, execution CONVICTS",
    "M2": "a measurement that agrees with you everywhere is not evidence",
    "M10": (
        "run suites against a copy - the instrument must not import the tree it measures, and any "
        "path subtracted from the proof because the audit itself wrote it is published with its evidence"
    ),
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


def check_s1_s2(groups: Dict[str, dict]) -> List[str]:
    """S1 + S2 — status, reason and tier discipline."""
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

    `previous_group_list is None` is a first run; the caller stamps `group_baseline`.
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
    """S8 — a score without a declared blind spot is a refusal."""
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
    """S9 — no mutant record without a kill_cause split."""
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
    """T-BUDGET — execution groups carry a budget, and exhaustion refuses."""
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


def check_m10(proof: Optional[dict]) -> List[str]:
    """M10 — a carrier subtraction is auditable, or the artifact is refused.

    An absent block (a refusal) is nothing to check; `total` is cross-checked, never trusted.
    """
    if not proof:
        return []

    problems: List[str] = []

    if "diff_before_carrier_subtraction" not in proof:
        problems.append("M10: m10_proof publishes a diff with no diff_before_carrier_subtraction to check it against")

    attribution = proof.get("attribution")
    if attribution not in CARRIER_ATTRIBUTION:
        problems.append(
            f"M10: m10_proof carries attribution {attribution!r}, expected one of {sorted(CARRIER_ATTRIBUTION)}"
        )

    carrier = proof.get("carrier_writes")
    if not isinstance(carrier, dict):
        problems.append("M10: m10_proof carries no carrier_writes block naming what the audit's own machinery wrote")
        return problems

    problems.extend(_carrier_block_problems(carrier, attribution))
    return problems


def _carrier_block_problems(carrier: dict, attribution: object) -> List[str]:
    """Every shape problem in one `carrier_writes` block, all at once."""
    problems: List[str] = []
    observed, declared = carrier.get("observed"), carrier.get("declared")

    if not carrier.get("note"):
        problems.append("M10: carrier_writes states no note - a subtraction with no sentence for it is an exemption")
    if carrier.get("swallowed_errors") is None:
        problems.append("M10: carrier_writes declares no swallowed_errors count - a swallowed error shortens the list")

    for field, rows, required in (
        ("observed", observed, ("path", "evidence", "event")),
        ("declared", declared, ("path", "surface", "owner", "why")),
    ):
        if not isinstance(rows, list):
            problems.append(f"M10: carrier_writes declares no {field} list")
            continue
        for row in rows:
            if not isinstance(row, dict) or not all(row.get(key) for key in required):
                problems.append(f"M10: a {field} carrier write does not name {', '.join(required)}")
                break

    if isinstance(observed, list) and isinstance(declared, list):
        if carrier.get("total") != len(observed) + len(declared):
            problems.append(
                f"M10: carrier_writes totals {carrier.get('total')!r} against "
                f"{len(observed)} observed and {len(declared)} declared"
            )
        if declared and attribution != "partly declared":
            problems.append(
                "M10: carrier_writes used a declared entry but attribution says 'measured' - "
                "a declaration is not a measurement"
            )

    return problems


def check_s5(cache: dict) -> List[str]:
    """S5 — a cache-served artifact is stamped and names what it cannot see."""
    problems: List[str] = []

    if cache.get("served_from_cache") and not cache.get("stamp"):
        problems.append("S5: artifact is cache-served but carries no stamp")
    if cache.get("not_fingerprinted") is None:
        problems.append("S5: cache block declares no not_fingerprinted list")

    return problems


def validate(document: dict, previous_group_list: Optional[List[str]] = None) -> List[str]:
    """Run every law against an assembled artifact. Returns problems found; empty is publishable."""
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
    problems.extend(check_m10(document.get("m10_proof")))

    if "group_baseline" not in document:
        problems.append("S3: artifact carries no group_baseline - a check that did not run must say so")

    return problems


def enforce(document: dict, previous_group_list: Optional[List[str]] = None) -> None:
    """Validate and raise LawViolation on the first problem found."""
    problems = validate(document, previous_group_list)
    if problems:
        law = problems[0].split(":", 1)[0]
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
