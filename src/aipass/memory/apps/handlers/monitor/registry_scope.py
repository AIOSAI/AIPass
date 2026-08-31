# =================== AIPass ====================
# Name: registry_scope.py
# Description: The one definition of "the fleet" — core, passport-declared residents, declared-root externals
# Version: 4.1.0
# Created: 2026-08-27
# Modified: 2026-08-30
# =============================================

"""Fleet Scope

Which branches @memory's lanes are responsible for, defined once.

Before this module the answer differed per lane.  The trinity push resolved
its own scope from a named constant and reached all 22 branches; every other
lane — rollover, lint, health — walked ``detector._read_registry()`` and
reached 19, because it only knew the core registry plus whatever external
registry a caller's cwd happened to have persisted into
``known_registries.json``.  ``baud`` was in that file by accident of where
somebody once stood; ``earmark``, ``finch`` and ``aipass_site`` were not, and
so three citizens' memory files could overflow with no rollover ever running
on them.  A gap that depends on a caller's working directory is not a policy.

DECLARED IN A PASSPORT, ANCHORED IN A REGISTRY (2.0.0, DPLAN-0319)
------------------------------------------------------------------
Passport 2.0 gives every citizen ``citizenship.residency`` — ``core`` or
``resident``.  Classification reads that field.  The named 4-tuple that used
to hold the answer is GONE as of 2026-08-28: it survived one wave as a drift
anchor only because @ai_mail's mirror pinned against it, and it went the
moment that mirror did.  There is no list of residents anywhere now — there
is a rule, and the passports answer it.  Discovery still globs, but it globs REGISTRIES, never passports,
and the distinction is load-bearing rather than stylistic: a passport walk
under ``projects/`` on this machine returns EIGHT passports for FOUR
residents, because ``baud`` carries two more under ``.backup/versioned/`` and
``.backup/snapshots/``, each a real passport declaring ``residency:
resident``.  A backup copy of a declaration is still a declaration.  Reading
a passport only at a path some registry declared is what makes the count
right.

THE TRUST MODEL decides who wins when the two disagree.  A passport is
agent-writable; a registry is not.  So:

* A passport can never ADD scope.  Nothing walks passports, so a declared
  resident that no discovered registry lists is unreachable by construction —
  refused by never being looked at, not by being filtered out later.
* A passport can never REMOVE a core citizen.  A core branch declaring
  nothing stays in the fleet and the disagreement is logged.  If an absent
  field could drop a citizen, an agent could stop its own memories being
  rolled over by deleting one line of its own file.
* Inside ``projects/``, both keys are required: the project registry lists the
  branch active AND the passport declares ``resident``.  Every other outcome is
  refused and NAMED — missing passport, unreadable passport, absent field,
  ``core`` claimed from inside ``projects/``, or a value nobody defined.

WHAT REPLACED THE NAMED LIST'S FRICTION, stated plainly because it is weaker
in one specific way.  The old constant meant adding a resident required an
edit here.  Now a directory under ``projects/`` carrying a registry and a
passport that declares ``resident`` joins the fleet on its own.  The friction
did not vanish, it moved: the declaration is a deliberate write to a tracked
passport.  It is genuinely less friction than a review of this file, and that
trade is the ruling, not an oversight.

THE STALE-CITIZEN RULE, which the named list used to carry alone.
``marketstand`` is parked but its registry still marks its branch ``active``,
so a status field can never be trusted by itself.  It is excluded three deep,
and each layer alone suffices: it lives under ``projects/.archive/`` and every
dot-prefixed path component is refused; its registry sits below the one-level
discovery depth; and its passport declares no residency at all.  Removing any
one layer must not quietly open the door, which is why the tests assert them
one at a time.

Discovery of registries OUTSIDE the repo (an external project whose agent
calls in from its own tree) is a separate mechanism and is untouched by this
module — see ``detector._find_caller_registries``.
"""

import json
from pathlib import Path
from typing import Any

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler

CORE_REGISTRY = "AIPASS_REGISTRY.json"

# Discovery: exactly one level under this directory, dot-prefixed components
# refused. Named so other branches can mirror the rule without importing it.
RESIDENT_PROJECTS_DIR = "projects"
RESIDENT_REGISTRY_GLOB = "*/*_REGISTRY.json"
PASSPORT_RELATIVE = Path(".trinity") / "passport.json"

# The two values passport 2.0 defines for citizenship.residency.
RESIDENCY_CORE = "core"
RESIDENCY_RESIDENT = "resident"

# The third TIER, which is deliberately not a third passport value. FPLAN-0460
# phase 2 retired the schema migration as a precondition: external membership is
# PRESENCE (a passport exists), not DECLARATION (a passport says a word). None of
# the six live external citizens carries a residency field, so gating on one
# would have shipped a feature nobody could reach. The label is ours to apply,
# not theirs to claim.
RESIDENCY_EXTERNAL = "external"

# The machine-scope anchor: AIPass home declares which repo roots participate.
# Beside AIPASS_REGISTRY.json because it is the same species of file -- machine
# managed, blessed by Patrick, the anchor of trust for a whole tier.
DECLARED_ROOTS = "AIPASS_ROOTS.json"
EXTERNAL_REGISTRY_GLOB = "*_REGISTRY.json"


# The repo root this FILE sits in, derived from the layout and nothing else.
# `src/` is the marker because it is the one directory the package layout
# guarantees; the last-resort value is the filesystem root, which is defined,
# never raises, and is absurd enough to fail loudly downstream instead of
# quietly resolving against somebody's home directory.
_SOURCE_ROOT = next(
    (parent.parent for parent in Path(__file__).resolve().parents if parent.name == "src"),
    Path(__file__).resolve().parents[-1],
)


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from *start* to the directory holding ``AIPASS_REGISTRY.json``.

    Falls back to the root implied by THIS FILE's location — never to the
    process working directory. Two defects lived in that one `Path.cwd()`:

    THE LOUD ONE, reported by @drone with an isolated repro. ``REPO_ROOT`` is
    resolved at MODULE level, and a clean checkout has no registry (it is
    gitignored and machine-local), so a bare CI runner took the fallback on
    every import — and a process whose working directory has been deleted
    raises ``FileNotFoundError`` from ``Path.cwd()`` while merely IMPORTING
    this module. It took down every import of drone on CI, router and
    ``drone rm`` included, because their handler imported the gateway at module
    level. They fixed their half and reported this line rather than patching
    another branch's tree.

    THE QUIET ONE, which would have outlived the crash: cwd is a GUESS. The
    directory a process happened to start in says nothing about where this
    source file lives, so on a registry-less tree every fleet lane would have
    resolved against whatever the caller's shell was pointing at — silently,
    and differently per caller. That is the species Patrick outlawed and the
    same objection @drone raised against ``_first_registry_in``: a fallback
    wearing a determinism costume.

    The source-derived answer is not a guess. On a registry-less checkout it
    IS the checkout, which is the true answer there. And the absence is said
    out loud, because a fallback nobody can see is how the next one survives.

    Args:
        start: Directory to walk up from. Defaults to this file's directory.

    Returns:
        The directory holding ``CORE_REGISTRY``, or ``_SOURCE_ROOT`` when no
        registry exists anywhere above *start*. Never reads the process cwd.
    """
    current = Path(start) if start is not None else Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / CORE_REGISTRY).exists():
            return parent
    logger.warning(
        f"[registry_scope] No {CORE_REGISTRY} above {current} — "
        f"resolving to the source tree at {_SOURCE_ROOT}, never the process directory"
    )
    return _SOURCE_ROOT


REPO_ROOT = find_repo_root()


def declared_residency(branch_path: Path) -> str | None:
    """What the passport at *branch_path* declares itself to be.

    The single reader for ``citizenship.residency``.  Every lane that needs to
    know whether a branch is core or resident should go through here rather
    than reach into the passport itself, so the field is only spelled once.

    An absent or unreadable passport declares NOTHING and does not raise.  A
    branch cannot be punished for a file the caller failed to hand it, and the
    caller — not this function — decides what silence means: for a core
    citizen it means "log it and keep them", for a resident candidate it means
    "refuse".  Returning ``None`` for both cases is what lets one reader serve
    two policies.

    Args:
        branch_path: The branch directory holding ``.trinity/passport.json``.

    Returns:
        The declared residency string, or ``None`` when nothing is declared.
    """
    passport = Path(branch_path) / PASSPORT_RELATIVE
    try:
        data = json.loads(passport.read_text(encoding="utf-8"))
    except FileNotFoundError:
        # DEBUG, not warning: an absent passport is an ordinary state here, not
        # a fault. It is the caller's policy that decides whether it matters —
        # a resident candidate without one is REFUSED at error level by
        # `_refuse`, and logging it twice would put a scary line under every
        # core citizen that predates passport 2.0. The event is still recorded
        # so a silent None can be traced back to a file that was never there.
        logger.debug(f"[registry_scope] No passport at {passport} — declares nothing")
        return None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.error(f"[registry_scope] Unreadable passport {passport}: {exc}")
        return None
    # SHAPE, not just parseability. Reported by @daemon 2026-08-30 (dispatch
    # 5031a591): valid JSON that is not an object made `.get` raise
    # AttributeError straight out of this function — and this function is not a
    # leaf. `fleet_branches` calls it once per core citizen and
    # `_accepted_residents` once per candidate, so one malformed file took out
    # every fleet lane at once, with a traceback naming this module instead of
    # the passport. The docstring above is the specification: unreadable
    # declares NOTHING and does not raise. A non-dict root is unreadable.
    if not isinstance(data, dict):
        logger.error(f"[registry_scope] Passport root is {type(data).__name__}, not an object: {passport}")
        return None
    citizenship = data.get("citizenship")
    if not isinstance(citizenship, dict):
        if citizenship is not None:
            logger.error(f"[registry_scope] Passport citizenship is {type(citizenship).__name__} in {passport}")
        return None
    residency = citizenship.get("residency")
    return residency if isinstance(residency, str) else None


def resident_registry_paths(repo_root: Path | None = None) -> list[Path]:
    """Candidate resident-project registries on this machine.

    DISCOVERY ONLY — this finds files, it does not decide who is in the fleet.
    Everything here is still a candidate until :func:`declared_residency`
    speaks for it.

    The glob is deliberately shallow and registry-led.  Exactly one level under
    ``projects/``, and any dot-prefixed component refused, because ``pathlib``
    (unlike a shell) happily matches hidden directories: without that filter
    ``projects/.archive/`` walks straight back in, and with it the disposal
    zone is unreachable by construction rather than by a later name check.

    A checkout with no ``projects/`` returns empty and does not raise — CI runs
    on exactly that tree.

    Args:
        repo_root: Repo root to resolve against; defaults to this checkout's.

    Returns:
        Absolute registry paths, sorted, one per candidate project.
    """
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    projects = root / RESIDENT_PROJECTS_DIR
    if not projects.is_dir():
        return []

    found = []
    for path in sorted(projects.glob(RESIDENT_REGISTRY_GLOB)):
        if any(part.startswith(".") for part in path.relative_to(projects).parts):
            continue
        found.append(path)
    return found


def read_registry_branches(registry_path: Path, name_from: str = "path") -> list[dict[str, Any]]:
    """Read one registry's ACTIVE branches with absolute paths.

    Args:
        registry_path: The registry JSON file.
        name_from: ``"path"`` to name each branch by its DIRECTORY (what the
            trinity checker compares ``managed_by`` against, and what the
            per-branch config lookups key on), or ``"registry"`` to keep the
            registry's own ``name`` field, whose casing disagrees for several
            citizens (``BACKUP`` vs ``backup``).

    Returns:
        ``[{"name", "path", "registry"}]`` — empty when the file is
        unreadable, which is logged as an error rather than raised: one
        broken registry must not take out a fleet-wide lane.
    """
    try:
        data = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.error(f"[registry_scope] Unreadable registry {registry_path}: {exc}")
        return []

    # Same shape defect as `declared_residency`, and worse here: a passport is
    # agent-written and expected to be wrong sometimes, while every lane trusts
    # the registry as the anchor a passport cannot forge. A registry that
    # crashes the reader takes the anchor down with it. Found by extending
    # @daemon's report rather than by their tests, which only reached the
    # passport.
    if not isinstance(data, dict):
        logger.error(f"[registry_scope] Registry root is {type(data).__name__}, not an object: {registry_path}")
        return []
    branches = data.get("branches", [])
    if not isinstance(branches, list):
        logger.error(f"[registry_scope] Registry 'branches' is {type(branches).__name__}, not a list: {registry_path}")
        return []

    found = []
    for branch in branches:
        # One bad row costs one row. A fleet where a single typo hides every
        # other citizen is not failing honestly — it is failing loudly in the
        # wrong place.
        if not isinstance(branch, dict):
            logger.error(f"[registry_scope] Registry row is {type(branch).__name__}, not an object: {registry_path}")
            continue
        if branch.get("status") != "active":
            continue
        raw = branch.get("path", "")
        if not isinstance(raw, str):
            logger.error(
                f"[registry_scope] Registry row '{branch.get('name')}' has a non-string path in {registry_path}"
            )
            continue
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = Path(registry_path).parent / raw
        name = path.name if name_from == "path" else branch.get("name", path.name)
        # Wrong TYPE is a wrong answer rather than a crash, so neither of these
        # is caught by the guards above — and both are still wrong. An int name
        # breaks any caller that formats it; a non-string address is unmailable
        # for @daemon and @ai_mail. The name has an honest fallback (the
        # directory); an address does not, so it becomes None and the caller
        # refuses on its own terms.
        if not isinstance(name, str):
            logger.error(f"[registry_scope] Registry row at {raw} has a non-string name in {registry_path}")
            name = path.name
        email = branch.get("email")
        if email is not None and not isinstance(email, str):
            logger.error(f"[registry_scope] Registry row '{name}' has a non-string email in {registry_path}")
            email = None
        # Pass-through, never derived. ``name`` may come from the DIRECTORY, so
        # deriving an address from it would hand an email-addressed caller a
        # plausible wrong answer instead of a missing one. Absent stays None and
        # the branch is kept: path-based lanes never read the address, and
        # dropping a citizen here would break them to protect a caller that has
        # not asked. Requested by @daemon, 2026-08-30, dispatch 16fbf1c0.
        found.append(
            {
                "name": name,
                "path": path,
                "registry": Path(registry_path).name,
                "email": email or None,
            }
        )
    return found


def overlaps_home(candidate: Path, home: Path) -> bool:
    """Does *candidate* sit inside AIPass home, contain it, or equal it?

    THE DOUBLE-COUNT GUARD, and it is not hypothetical. Declaring our own tree
    as an external root would return every core citizen and every resident a
    second time under a different tier; @baud would appear three times, because
    the backup copy the walk law already refuses is a third path to the same
    branch. A root that CONTAINS home is refused for the same reason from the
    other side -- declaring ``..`` would sweep this repo in as somebody's
    sibling.

    Public because the anchor's WRITE lane refuses the same thing at write time,
    against this exact function. Two enforcement points, one predicate.

    Both paths must already be resolved; this compares, it does not normalise.
    """
    return candidate == home or home in candidate.parents or candidate in home.parents


def declared_roots(repo_root: Path | None = None) -> list[Path]:
    """Repo roots this installation has DECLARED as participating, resolved.

    The anchor for the external tier.  Reading a file, not searching a disk:
    every root here was written down by someone, and a root nobody wrote down is
    not a root no matter how close it sits.

    The two anchors this replaces both failed in production, which is why it is
    a declaration rather than an accumulation.  ``ai_mail``'s contacts.json
    accretes by ``last_seen``, still carries dead April entries and does not
    contain @wren at all.  My own ``known_registries.json`` persisted a deleted
    /tmp scratchpad probe while never recording Vera-Studio's real registry.

    Relative paths resolve against *repo_root* so ``../wren`` survives a
    checkout move and keeps machine paths out of a public repo; absolute paths
    are accepted for roots that live nowhere near it.

    Every rejection is logged by name.  A missing file is NOT one of them: zero
    declared roots is the ordinary state of a fresh clone, and an installation
    that participates in nothing is not broken.

    Args:
        repo_root: AIPass home; defaults to this checkout's.

    Order is DECLARATION order, and that is load-bearing rather than
    incidental.  The fleet ruling breaks an N-root tie by declaration order, so
    a reader that sorted its result put alphabetical-by-resolved-path in front
    of the rule and the tie-breaker was never available at any door.  Both
    orders are deterministic; only the rows a human wrote carry intent, and
    directory names carry none.  Reported by @ai_mail (abe8141b), who found the
    order at their door could not be the order the ruling names and said so
    instead of guessing.

    Returns:
        Existing directories, resolved, deduplicated, in the order declared.
        First declaration wins a duplicate. Never this repo.
    """
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    anchor = root / DECLARED_ROOTS
    try:
        data = json.loads(anchor.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.debug(f"[registry_scope] No {DECLARED_ROOTS} at {root} — no external roots declared")
        return []
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.error(f"[registry_scope] Unreadable {DECLARED_ROOTS} at {anchor}: {exc}")
        return []

    if not isinstance(data, dict):
        logger.error(f"[registry_scope] {DECLARED_ROOTS} root is {type(data).__name__}, not an object: {anchor}")
        return []
    rows = data.get("roots", [])
    if not isinstance(rows, list):
        logger.error(f"[registry_scope] {DECLARED_ROOTS} 'roots' is {type(rows).__name__}, not a list: {anchor}")
        return []

    home = root.resolve()
    found: list[Path] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            logger.error(f"[registry_scope] {DECLARED_ROOTS} row is {type(row).__name__}, not an object: {anchor}")
            continue
        if row.get("status") != "active":
            logger.info(f"[registry_scope] Declared root {row.get('path')!r} is not active — skipped")
            continue
        raw = row.get("path")
        if not isinstance(raw, str) or not raw:
            logger.error(f"[registry_scope] Declared root has no usable path ({raw!r}) in {anchor}")
            continue

        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            candidate = candidate.resolve()
        except OSError as exc:
            logger.error(f"[registry_scope] Declared root {raw!r} cannot be resolved: {exc}")
            continue
        if not candidate.is_dir():
            logger.error(f"[registry_scope] Declared root {raw!r} is not a directory on this machine ({candidate})")
            continue
        # The double-count guard. Extracted as a public predicate so the WRITE
        # side refuses the same thing at the same place in the same words: a
        # rule enforced by two functions is a rule that agrees by coincidence.
        if overlaps_home(candidate, home):
            logger.error(
                f"[registry_scope] REFUSED declared root {raw!r} ({candidate}): it overlaps AIPass home "
                f"{home} — core and resident citizens would be counted twice"
            )
            continue

        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        found.append(candidate)

    # NOT sorted(): see the docstring. Declaration order is the tie-breaker the
    # fleet ruling names, and sorting here discarded it before any caller saw it.
    return found


def external_branches(repo_root: Path | None = None, name_from: str = "path") -> list[dict[str, Any]]:
    """Citizens living in declared roots outside this repo.

    Registry-led and shallow, exactly as the resident tier is: one glob for
    ``*_REGISTRY.json`` at the TOP LEVEL of a declared root, then that
    registry's own active branches.  Never a passport walk, at any depth, ever
    -- a walk of our own ``projects/`` returns eight passports for four
    residents because @baud carries copies under ``.backup/``, and the same walk
    across a whole machine would count every snapshot of every repo.

    MEMBERSHIP IS PRESENCE.  A branch is a citizen if ``.trinity/passport.json``
    exists; it does not have to say anything.  That is Patrick's ruling and the
    reason phase 2 shipped without a schema migration in front of it.

    The record carried a ``scheduler`` bool for three hours on 2026-08-30 and
    no longer does.  @daemon asked for it, then asked for it back: it reported
    one filename while they read ``.daemon/*.json``, so as a pre-filter it would
    have silently dropped jobs living in any other file -- reading as "no jobs"
    rather than as a bug.  Withdrawn on their word, by the branch that wanted it.

    Args:
        repo_root: AIPass home; defaults to this checkout's.
        name_from: See :func:`read_registry_branches`.

    Returns:
        ``[{"name", "path", "registry", "email", "residency"}]``.
    """
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in declared_roots(repo_root):
        registries = sorted(root.glob(EXTERNAL_REGISTRY_GLOB))
        if not registries:
            logger.error(
                f"[registry_scope] Declared root {root} carries no {EXTERNAL_REGISTRY_GLOB} at its top level — "
                "no citizens read from it, and a passport walk is never the fallback"
            )
            continue
        if len(registries) > 1:
            # Raised by @drone against their OWN code: their _first_registry_in
            # takes sorted(glob)[0], which they called a fallback wearing a
            # determinism costume, and recommended I not copy it. Merging would
            # be worse than picking — it invents a union nobody declared and
            # makes that repo's fleet a thing only this reader knows. So the
            # root contributes nothing and says why. One ambiguous root costs
            # one root; the others are untouched.
            logger.error(
                f"[registry_scope] REFUSED declared root {root}: it carries {len(registries)} registries "
                f"({', '.join(path.name for path in registries)}) — which one is the fleet is not ours to guess"
            )
            continue
        for registry_path in registries:
            for item in read_registry_branches(registry_path, name_from=name_from):
                if not (item["path"] / PASSPORT_RELATIVE).is_file():
                    _refuse(
                        item,
                        registry_path,
                        "no passport on disk — external membership is presence",
                        tier=RESIDENCY_EXTERNAL,
                    )
                    continue
                key = str(item["path"])
                if key in seen:
                    continue
                seen.add(key)
                item["residency"] = RESIDENCY_EXTERNAL
                found.append(item)
    return found


def _refuse(item: dict[str, Any], registry_path: Path, reason: str, tier: str = RESIDENCY_RESIDENT) -> None:
    """Log a refused candidate by tier, name, path and reason.

    Every rejection goes through here so none of them can be silent.  A
    candidate refused without a line in the log is indistinguishable from one
    that was never discovered, and those two need very different fixes.
    """
    logger.error(
        f"[registry_scope] REFUSED {tier} '{item['name']}' at {item['path']} "
        f"(listed active in {registry_path.name}): {reason}"
    )


def _accepted_residents(registry_path: Path, name_from: str) -> list[dict[str, Any]]:
    """The branches in one project registry whose passports declare them residents.

    Two keys, both required.  The registry says the branch is active — that is
    the anchor a passport cannot forge.  The passport says ``resident`` — that
    is the declaration a registry does not carry.  Anything else is refused
    and named.
    """
    accepted = []
    for item in read_registry_branches(registry_path, name_from=name_from):
        residency = declared_residency(item["path"])
        if residency == RESIDENCY_RESIDENT:
            accepted.append(item)
        elif residency is None:
            _refuse(item, registry_path, "passport declares no residency (missing, unreadable, or no field)")
        elif residency == RESIDENCY_CORE:
            _refuse(item, registry_path, f"passport declares '{RESIDENCY_CORE}' from inside {RESIDENT_PROJECTS_DIR}/")
        else:
            _refuse(item, registry_path, f"passport declares unknown residency '{residency}'")
    return accepted


def accepted_resident_paths(repo_root: Path | None = None) -> set[str]:
    """Resolved paths of every project branch whose passport declares it a resident.

    The classification, exposed once so no other lane re-implements it.
    ``detector`` reads registries in its own shape and cannot use
    :func:`fleet_branches` directly; without this it would have to repeat the
    two-key rule, and a policy with two implementations agrees only by
    coincidence — which is the exact defect this module was built to end.

    Refusals are logged by the classifier itself, so a caller filtering on this
    set stays silent and still leaves a named reason in the log.

    Args:
        repo_root: Repo root to resolve against; defaults to this checkout's.

    Returns:
        Absolute paths as strings, ready for membership tests.
    """
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    accepted = set()
    for registry_path in resident_registry_paths(root):
        for item in _accepted_residents(registry_path, name_from="path"):
            accepted.add(str(item["path"]))
    return accepted


def fleet_branches(repo_root: Path | None = None, name_from: str = "path") -> list[dict[str, Any]]:
    """Every branch @memory maintains: core citizens, residents, and externals.

    Deduplicated by resolved path, core registry first, residents in discovery
    order.

    The two halves are judged by DIFFERENT rules on purpose.  Core citizens
    come from the sealed registry and are included unconditionally; a core
    passport that declares nothing, or declares something else, is logged and
    the citizen is KEPT, because an agent-writable field must never be able to
    remove its own branch from maintenance.  Resident candidates need both the
    registry entry and the declaration, because there the passport is the only
    thing distinguishing a live project from a parked one.

    Args:
        repo_root: Repo root to resolve against; defaults to this checkout's.
        name_from: See :func:`read_registry_branches`.

    Returns:
        ``[{"name", "path", "registry", "email", "residency"}]``.
    """
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    branches = read_registry_branches(root / CORE_REGISTRY, name_from=name_from)
    core_count = len(branches)
    for item in branches:
        residency = declared_residency(item["path"])
        if residency != RESIDENCY_CORE:
            logger.warning(
                f"[registry_scope] Core citizen '{item['name']}' declares residency "
                f"{residency!r}, not '{RESIDENCY_CORE}' — kept, because the sealed registry is the anchor"
            )

    # The TIER is applied here, not read from the passport. A core citizen whose
    # passport disagrees is still core (the sealed registry is the anchor), and
    # an external citizen has no passport field at all -- so a record labelled
    # from the declaration would be blank for a whole tier. @daemon asked for
    # these labels by name so 'external' never silently reads as 'core'.
    for item in branches:
        item["residency"] = RESIDENCY_CORE

    seen = {str(item["path"]) for item in branches}
    for registry_path in resident_registry_paths(root):
        for item in _accepted_residents(registry_path, name_from):
            if str(item["path"]) not in seen:
                item["residency"] = RESIDENCY_RESIDENT
                branches.append(item)
                seen.add(str(item["path"]))
    resident_count = len(branches) - core_count

    for item in external_branches(root, name_from=name_from):
        if str(item["path"]) not in seen:
            branches.append(item)
            seen.add(str(item["path"]))

    # Logged because the SIZE of the fleet is the whole point of this module:
    # the residents were invisible to rollover, lint and health for months and
    # nothing said so. A run that quietly sees 19 branches instead of 22 is the
    # exact regression, and this line is where it shows up.
    json_handler.log_operation(
        "fleet_scope",
        {
            "total": len(branches),
            "core": core_count,
            "resident": resident_count,
            "external": len(branches) - core_count - resident_count,
        },
        module_name="registry_scope",
    )
    return branches
