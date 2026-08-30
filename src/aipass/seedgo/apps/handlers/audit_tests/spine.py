# =================== AIPass ====================
# Name: spine.py
# Description: audit-tests core spine - the universal group list
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
CORE_SPINE — the groups every ecosystem publishes.

The group list is a COMPOSITION, never a constant (design section 4.2):

    group_list = CORE_SPINE + [f"{ecosystem}.{name}" for name in adapter.declared_groups()]

Revision 1 of the design made `group_list` equality with a single core
constant. That shape could not grow: adding an ecosystem meant editing the
core, which is the exact future rebuild Patrick's ruling 3 forbade. The
invariant that actually matters is not equality — it is that NOTHING
VANISHES, which `laws.py` enforces against the previous artifact.

A spine group an adapter cannot measure stays in the list and reports
`not_applicable` with a reason. It never disappears, and it is never 0
(Law S1: not-run is `not_applicable`, never zero).

REV 4 CONTRACTS, written while the groups are still unbuilt, because the
requirement has to land before the capability or it never lands at all:

  * `kill_cause` binds `oracle_execution` and the adapter's mutation groups.
    No mutant record may exist without a kill-cause split. See KILL_CAUSE_CONTRACT.
  * `scoped_survival` measures module-granularity ORACLE SURVIVAL and is never
    to be read as pseudo-testedness. See SURVIVAL_NAMING_CONTRACT.
"""

from typing import Dict, List

from aipass.seedgo.apps.handlers.json import json_handler

# =============================================================================
# THE SPINE
# =============================================================================

#: Universal across every ecosystem. Order is the published order.
CORE_SPINE: tuple = (
    "hygiene",
    "oracle_execution",
    "order_dependence",
    "ai_advisory",
)

#: The only group carrying a score on day one.
#:
#: SCORED and GATING are different words and stay different: `hygiene` carries
#: a number, and the artifact blocks nothing at launch. Promotion into this
#: tuple requires BOTH (1) the group's blind counters existing and published,
#: and (2) a measured fleet-wide distribution of those counters in hand at
#: ruling time. Disclosure is a confession, not a certificate — a bar phrased
#: as "until gate_coverage proves the gate sees what it claims" is either
#: unreachable or met by an empty confession (design section 4.5, rev 4).
SCORED_GROUPS: tuple = ("hygiene",)

#: Tier per spine group. The AI tier may only nominate (Law S6).
SPINE_TIERS: Dict[str, str] = {
    "hygiene": "exec",
    "oracle_execution": "exec",
    "order_dependence": "exec",
    "ai_advisory": "ai",
}

#: Why each spine group is universal — published in the artifact so a reader
#: never has to ask why a group they cannot use is present.
SPINE_RATIONALE: Dict[str, str] = {
    "hygiene": "'a test may write only inside the declared sandbox' is a claim in every language",
    "oracle_execution": "the PROJECTION-ORACLE family; mutation exists in every ecosystem",
    "order_dependence": "a property of a suite, not of a language",
    "ai_advisory": "the L2 tier - nominate only, never scored",
}

# =============================================================================
# REV 4 CONTRACTS - binding on groups that do not exist yet
# =============================================================================

#: Groups bound by the kill_cause contract. Every one of them is currently
#: `not_applicable: "not built"`; the contract exists so that the day any of
#: them runs, it cannot ship without the split.
KILL_CAUSE_BOUND: tuple = (
    "oracle_execution",
    "scoped_survival",
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

#: Contract text keyed by the group it binds, for stamping into the artifact.
GROUP_CONTRACTS: Dict[str, str] = {
    "oracle_execution": KILL_CAUSE_CONTRACT,
    "scoped_survival": KILL_CAUSE_CONTRACT + " " + SURVIVAL_NAMING_CONTRACT,
    "targeted_mutation": KILL_CAUSE_CONTRACT,
}


# =============================================================================
# COMPOSITION
# =============================================================================


def compose_group_list(ecosystem: str, declared: List[str]) -> List[str]:
    """Build the published group list: spine first, adapter groups namespaced.

    Namespacing is what lets a second ecosystem exist without the core knowing
    about it. `pytest.static_ruff_pt` is a Python linter's rule family; a Rust
    adapter would never have to enumerate it, and a Rust species has somewhere
    to go.

    Raises ValueError if an adapter declares a name that collides with the
    spine, because a shadowed spine group would vanish from the list without a
    ruling — the one thing S3/S4 exists to prevent.
    """
    collisions = sorted(set(declared) & set(CORE_SPINE))
    if collisions:
        # A rejected adapter is operationally interesting: it means a pack tried
        # to shadow a spine group, which would have made that group vanish from
        # the published list without a ruling.
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
    """The rev-4 contract text bound to a group, or "" if it has none.

    Accepts both the bare adapter name (`scoped_survival`) and the namespaced
    published name (`pytest.scoped_survival`), because callers legitimately
    hold either.
    """
    if group in GROUP_CONTRACTS:
        return GROUP_CONTRACTS[group]
    bare = group.split(".", 1)[-1]
    return GROUP_CONTRACTS.get(bare, "")


def spine_document(group: str) -> dict:
    """The default `not_applicable` document for an unimplemented spine group.

    Law S1: not-run is `not_applicable`, never 0. The reason is mandatory —
    a `not_applicable` without one is indistinguishable from a silent skip.

    The AI tier carries `kind: nominate_only` unconditionally (Law S6). A
    refused artifact is built entirely from these documents, so if the spine
    did not stamp it here, every refusal would itself be an unlawful artifact —
    found by the refused-artifact test on its first run.
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
