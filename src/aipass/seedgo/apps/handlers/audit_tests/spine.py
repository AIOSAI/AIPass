# =================== AIPass ====================
# Name: spine.py
# Description: audit-tests core spine - the universal group list
# Version: 1.1.0
# Created: 2026-08-29
# Modified: 2026-10-17
# =============================================

"""
CORE_SPINE — the groups every ecosystem publishes.

The group list is CORE_SPINE plus namespaced adapter groups, never a constant;
the invariant is that nothing vanishes, which `laws.py` enforces.
"""

from typing import Dict, List

from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.tests_pytest_standards import envdiff

#: Universal across every ecosystem. Order is the published order.
CORE_SPINE: tuple = (
    "hygiene",
    "oracle_execution",
    "order_dependence",
    "ai_advisory",
)

#: Scored is not gating: promotion needs published blind counters AND a measured fleet distribution of them.
SCORED_GROUPS: tuple = ("hygiene",)

#: Tier per spine group. The AI tier may only nominate (Law S6).
SPINE_TIERS: Dict[str, str] = {
    "hygiene": "exec",
    "oracle_execution": "exec",
    "order_dependence": "exec",
    "ai_advisory": "ai",
}

#: Why each spine group is universal, published in the artifact.
SPINE_RATIONALE: Dict[str, str] = {
    "hygiene": "'a test may write only inside the declared sandbox' is a claim in every language",
    "oracle_execution": "the PROJECTION-ORACLE family; mutation exists in every ecosystem",
    "order_dependence": "a property of a suite, not of a language",
    "ai_advisory": "the L2 tier - nominate only, never scored",
}

#: Every group that EXECUTES A MUTANT, and nothing else; `width_coupling` runs none, so it is absent.
KILL_CAUSE_BOUND: tuple = (
    "oracle_execution",
    "pseudo_tested",
    "scoped_survival",
    "statement_deletion",
    "targeted_mutation",
)

KILL_CAUSE_CONTRACT = (
    "No mutant record may exist without a kill_cause field splitting the kill by "
    "exception class (AssertionError vs everything else). not_applicable while "
    "unbuilt; on the first release that executes a mutant, an unsplit kill record "
    "is a REFUSAL. Evidence: Schuler & Zeller ICST 2011 Table III (a suite with "
    "every assertion deleted still detects >50% of the mutants the original "
    "detects; ~45% of kills are implicit runtime exceptions) and Zhang & Mesbah "
    "FSE 2015 (28-73% assertion-caused across five subjects). The amplification "
    "that matters here: gutting replaces bodies with `return None`, so Python "
    "callers raise TypeError/AttributeError on contact and a suite can post a "
    "near-perfect gutting kill rate with no assertion firing at all. Unsplit, "
    "the gutting probe would be the most flattering number in the lane."
)

SURVIVAL_NAMING_CONTRACT = (
    "scoped_survival measures module-granularity ORACLE SURVIVAL - a property of "
    "the TEST - and is never to be read, named or reported as pseudo-testedness, "
    "which is a property of a FUNCTION (Niedermayr et al. ICSE-CSED 2016; "
    "Vera-Perez et al. EMSE 2018). Module gutting cannot report the latter: a "
    "test covering five functions of which one has a real oracle dies when all "
    "five are gutted, so it reads strong while the other four pseudo-tested "
    "functions stay invisible. That is a systematic false negative, not noise. "
    "The per-function probe lands as a NEW group under S3/S4's no-vanishing "
    "rule, never as a redefinition of this one."
)

PSEUDO_TESTED_SCOPE_CONTRACT = (
    "pseudo_tested is the per-function probe contract 2 promised as a NEW group, "
    "and it reports GUTTING SURVIVORS, which is a SUPERSET of pseudo-tested "
    "functions. Descartes (Vera-Perez et al. EMSE 2018) calls a method "
    "pseudo-tested only when it is COVERED and the mutant survives; this probe "
    "measures no coverage, so a function no test ever executes also survives and "
    "is ordinary dead-to-the-suite code rather than this group's news. Measured on "
    "the banked canary fixture: 3 survivors, of which 1 was covered and genuinely "
    "pseudo-tested and 2 were never executed at all. Until a coverage pass feeds "
    "this group, every survivor list is published with that split unknown, and the "
    "group may not be read as a pseudo-tested RATE."
)

#: Limits are bound verbatim from `envdiff.WIDTH_AXIS_LIMITS`, never restated, so the two cannot drift.
WIDTH_COUPLING_CONTRACT = (
    "width_coupling publishes a DIVERGENCE COUNT: the number of nodeids whose pass/fail "
    "verdict changes between two runs of the same unmutated suite that differ only in "
    "COLUMNS. It executes no mutant, so kill_cause does not bind it and no mutant record "
    "may appear under it. The count is evidence of coupling where it is non-zero and it "
    "is NEVER evidence of width-independence where it is zero - a zero is what a "
    "two-point sample of one axis, measured once, looks like when it found nothing at "
    "those two points. Every reading of this group is bound by the axis's own published "
    "limits, which travel in the group document as `limits`: " + " ".join(envdiff.WIDTH_AXIS_LIMITS)
)

STATEMENT_DELETION_SCOPE_CONTRACT = (
    "A survivor here is one statement whose deletion no covering test noticed. It is not a claim "
    "about the function around it, and it is not a claim about any branch: this operator deletes "
    "simple statements only, so branch deletion is out of reach by construction. Arid statements "
    "(docstrings, pass, bare ellipsis, a trailing `return None`) are declared and excluded up front "
    "with the reason each cannot change behaviour, and their counts travel in the document."
)

GROUP_CONTRACTS: Dict[str, str] = {
    "oracle_execution": KILL_CAUSE_CONTRACT,
    "pseudo_tested": KILL_CAUSE_CONTRACT + " " + PSEUDO_TESTED_SCOPE_CONTRACT,
    "scoped_survival": KILL_CAUSE_CONTRACT + " " + SURVIVAL_NAMING_CONTRACT,
    "statement_deletion": KILL_CAUSE_CONTRACT + " " + STATEMENT_DELETION_SCOPE_CONTRACT,
    "targeted_mutation": KILL_CAUSE_CONTRACT,
    envdiff.GROUP: WIDTH_COUPLING_CONTRACT,
}


def compose_group_list(ecosystem: str, declared: List[str]) -> List[str]:
    """Build the published group list: spine first, adapter groups namespaced.

    A spine-name collision raises: a shadowed spine group would vanish without a ruling.
    """
    collisions = sorted(set(declared) & set(CORE_SPINE))
    if collisions:
        json_handler.log_operation(
            "adapter_declaration_rejected",
            {"ecosystem": ecosystem, "reason": "spine_collision", "groups": collisions},
        )
        raise ValueError(
            f"adapter '{ecosystem}' declares group name(s) colliding with the core spine: "
            f"{', '.join(collisions)} - the spine is reserved"
        )

    duplicates = sorted({name for name in declared if declared.count(name) > 1})
    if duplicates:
        raise ValueError(f"adapter '{ecosystem}' declares duplicate group name(s): {', '.join(duplicates)}")

    return list(CORE_SPINE) + [f"{ecosystem}.{name}" for name in declared]


def is_scored(group: str) -> bool:
    """True if this group carries a score. Everything else is advisory."""
    return group in SCORED_GROUPS


def contract_for(group: str) -> str:
    """The contract text bound to a bare or namespaced group name, or "" if it has none."""
    if group in GROUP_CONTRACTS:
        return GROUP_CONTRACTS[group]
    bare = group.split(".", 1)[-1]
    return GROUP_CONTRACTS.get(bare, "")


def spine_document(group: str) -> dict:
    """The default `not_applicable` document for an unimplemented spine group.

    The AI tier is stamped `nominate_only` here because refused artifacts are built from these (Law S6).
    """
    tier = SPINE_TIERS.get(group, "exec")
    document = {
        "tier": tier,
        "status": "not_applicable",
        "reason": "not built",
        "universal_because": SPINE_RATIONALE.get(group, ""),
        "score": None,
    }
    if tier == "ai":
        document["kind"] = "nominate_only"

    contract = contract_for(group)
    if contract:
        document["contract"] = contract
    return document
