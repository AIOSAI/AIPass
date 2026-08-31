# =================== AIPass ====================
# Name: passport_migration.py
# Description: Passport 2.0 fleet migration — structure transform, backup, measured receipt
# Version: 1.0.0
# Created: 2026-08-28
# Modified: 2026-08-28
# =============================================

"""One-shot fleet migration of every live passport to schema 2.0 (DPLAN-0319).

``spawn update`` cannot do this and never will: its heal allowlist
(``update_ops._PASSPORT_HEAL_ALLOWLIST``) admits exactly
``branch_info.email``, ``branch_info.git_branch`` and ``identity.traits``.
``citizenship`` and ``document_metadata`` are create-only, and update_ops
deliberately refuses to reorder an existing passport's keys — a healthy
passport must come out byte-for-byte unchanged there. Every single thing this
migration does is on the other side of that fence, so it lives in its own
command with its own backup and its own dry-run default.

What this is NOT: a rewrite of anybody's identity. ``role``, ``purpose``,
``what_i_do``, ``what_i_dont_do``, the TEXT inside ``traits``, ``principles``
and devpulse's ``class_extension`` are carried across verbatim. This module
moves fields, renames dead values, and fixes shapes — it never authors content.

Three rules keep the migration honest:

* **Never silently drop.** Exactly three keys are dropped, by name, because
  R8 retired them (``citizenship.owner``, top-level ``family``,
  ``document_metadata.note``). Anything else the migration does not recognise
  is PRESERVED — appended at the end of its own block — and REPORTED in the
  receipt, so an unknown field shows up as a question rather than as a
  silent deletion.
* **Never guess.** A passport carrying a forbidden class, an unresolvable
  class, or a ``principles`` conflict raises and is SKIPPED with the reason on
  the record. A registry_path that is neither missing nor a recognised legacy
  form is left alone and reported.
* **Idempotent by construction.** ``document_metadata.last_updated`` is
  stamped only when something ELSE actually changed. Without that rule a
  second run would rewrite all 22 files the moment the date rolls over, which
  is exactly the "measured no-op" the plan asks for, lost.

The backup suffix is ``.pre_v2_backup`` — trinity-legal, unlike ``.bak``. It is
written only when a real change is about to land, and NEVER over an existing
one: the first backup is the true pre-migration original, and a second run
overwriting it with an already-migrated copy would destroy the only way back.
That is also why ``backup_passport`` is public — ``sync_registry_ops``' legacy
class rewrite is a second fleet-write path and calls it before its own write.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.spawn.apps.handlers.atomic_write import atomic_write_text
from aipass.spawn.apps.handlers.class_registry import (
    CITIZEN_CLASSES,
    LEGACY_CLASSES,
    refuse_forbidden_class,
)
from aipass.spawn.apps.handlers.json import json_handler

__all__ = [
    "BACKUP_SUFFIX",
    "BLOCK_ORDER",
    "CANONICAL_REGISTRY_PATH",
    "EXPECTED_FLEET",
    "KEY_ORDER",
    "PassportMigrationError",
    "PassportTarget",
    "SCHEMA_VERSION",
    "TARGET_GIT_BRANCH",
    "backup_passport",
    "discover_passports",
    "migrate_document",
    "migrate_fleet",
    "migrate_passport_file",
    "repo_root",
]


# =============================================================================
# CONTRACT — the 2.0 shape, straight off the gold reference
# (devpulse dropbox passport_v2_draft.devpulse.json)
# =============================================================================

SCHEMA_VERSION = "2.0.0"
TARGET_GIT_BRANCH = "dev"
CANONICAL_REGISTRY_PATH = ".aipass/registry.json"
BACKUP_SUFFIX = ".pre_v2_backup"

# Block order IS contract (R1) — citizenship moves above identity.
BLOCK_ORDER = ("document_metadata", "branch_info", "citizenship", "identity")

# Key order inside each block IS contract too. ``class_extension`` sits in the
# identity order because devpulse already carries one (DPLAN-0288 prose); it is
# NOT in the template and is never created here, only kept in its right place.
KEY_ORDER = {
    "document_metadata": (
        "document_type",
        "document_name",
        "version",
        "schema_version",
        "created",
        "last_updated",
        "managed_by",
        "tags",
    ),
    "branch_info": (
        "branch_name",
        "alias",
        "path",
        "module",
        "email",
        "created",
        "git_branch",
    ),
    "citizenship": (
        "registered",
        "residency",
        "registry_id",
        "citizen_id",
        "registry_path",
        "communications",
        "memory",
    ),
    "identity": (
        "citizen_class",
        "class_extension",
        "role",
        "purpose",
        "what_i_do",
        "what_i_dont_do",
        "traits",
        "principles",
    ),
}

# R8 drops. Nothing else is ever removed — see module docstring.
DROPPED_KEYS = {
    "citizenship": ("owner",),
    "document_metadata": ("note",),
}
DROPPED_TOP_LEVEL = ("family",)

# Identity content this migration must never author or edit. Asserted by
# tests/test_passport_migration.py — a structure migration that quietly
# reworded somebody's purpose would be the worst possible bug here.
IDENTITY_CONTENT_KEYS = (
    "class_extension",
    "role",
    "purpose",
    "what_i_do",
    "what_i_dont_do",
    "traits",
    "principles",
)

# Where the fleet lives, and what it measured at build time (2026-08-28).
# A drift from this baseline is REPORTED, never silently accepted and never
# used to skip work — the discovered set is the truth, this is the alarm.
CORE_GLOB = "src/aipass/*/.trinity/passport.json"
RESIDENT_GLOB = "projects/*/src/*/*/.trinity/passport.json"
EXPECTED_FLEET = {"core": 18, "resident": 4, "total": 22}


class PassportMigrationError(Exception):
    """A passport that cannot be migrated without guessing. Caller skips it."""


@dataclass(frozen=True)
class PassportTarget:
    """One discovered passport and the facts derived from WHERE it lives."""

    path: Path
    branch_dir: Path
    project_root: Path
    residency: str

    @property
    def relative_path(self) -> str:
        """The branch's path relative to the project root that owns it."""
        return self.branch_dir.relative_to(self.project_root).as_posix()


@dataclass
class MigrationResult:
    """The outcome of migrating one document (pure, no filesystem)."""

    document: dict
    changed: bool
    changes: list[tuple[str, object, object]] = field(default_factory=list)
    unknown_fields: list[str] = field(default_factory=list)


# =============================================================================
# DISCOVERY
# =============================================================================


def repo_root() -> Path:
    """Return the AIPass repo root, derived from this file's own location.

    handlers/ -> apps/ -> spawn/ -> aipass/ -> src/ -> repo root.
    """
    return Path(__file__).resolve().parents[5]


def _is_hidden_path(passport: Path, base: Path) -> bool:
    """True when any directory between ``base`` and ``.trinity`` starts with a dot.

    A citizen directory never begins with a dot, so this is a rule rather than a
    blocklist of names — ``.archive``, ``.backup``, ``.git`` and whatever the
    next retirement convention is are all refused by the same sentence, and no
    real citizen is ever caught by it. ``.trinity`` itself is excluded because it
    is part of the shape being matched, not part of the location.
    """
    try:
        relative = passport.relative_to(base)
    except ValueError:
        # Not under the scanned root at all. Both globs are anchored at base, so
        # this is unreachable today — but a refusal nobody can see is how a
        # future caller passing an unanchored path gets silently migrated.
        logger.warning(f"[spawn] Passport outside the scanned root, refused: {passport}")
        return True
    # Drop the trailing ".trinity/passport.json" the globs both end with.
    return any(part.startswith(".") for part in relative.parts[:-2])


def discover_passports(root: Path | str | None = None) -> list[PassportTarget]:
    """Glob every live fleet passport under ``root``.

    Two shapes, and the shape decides residency (R5) — a core citizen lives
    under ``src/aipass/``, a resident under ``projects/<project>/``. Residency
    is read off the location rather than off the passport, because the passport
    is precisely the thing being corrected.

    Backups (``.backup/``), archives and the template under
    ``spawn/templates/`` are refused BY RULE — ``_is_hidden_path`` drops any
    candidate with a dotted directory component between the root and
    ``.trinity``. That used to be true only by luck of layout: pathlib's ``*``
    matches dotted names, so ``src/aipass/.archive/.trinity/passport.json`` was
    a match waiting for such a directory to exist (measured 2026-08-31).
    Vera-Studio holds five such passports today under ``src/.archive/``, which
    is what the rule exists for: retiring a citizen is a REGISTRY act, and a
    passport walk cannot tell a retired citizen from a live one.

    Args:
        root: Repo root to scan. Defaults to the live repo root.

    Returns:
        Targets sorted by path — core first, residents after.
    """
    base = Path(root) if root is not None else repo_root()

    targets: list[PassportTarget] = []
    for match in sorted(base.glob(CORE_GLOB)):
        if _is_hidden_path(match, base):
            continue
        targets.append(
            PassportTarget(
                path=match,
                branch_dir=match.parent.parent,
                project_root=base,
                residency="core",
            )
        )
    for match in sorted(base.glob(RESIDENT_GLOB)):
        if _is_hidden_path(match, base):
            continue
        # projects/<project>/src/<pkg>/<branch>/.trinity/passport.json
        project_root = match.parents[4]
        targets.append(
            PassportTarget(
                path=match,
                branch_dir=match.parent.parent,
                project_root=project_root,
                residency="resident",
            )
        )
    return targets


# =============================================================================
# BACKUP — also called by sync_registry_ops before ITS passport write
# =============================================================================


def backup_passport(path: Path | str) -> bool:
    """Copy a passport to ``<name>.pre_v2_backup``, once and only once.

    An existing backup is NEVER overwritten. The first copy is the true
    pre-migration original; a later run (or a later writer, e.g.
    ``sync-registry --fix``) overwriting it with an already-modified copy would
    quietly destroy the only way back.

    Args:
        path: Path to the live passport.json.

    Returns:
        True if a backup was written now, False if one already existed or the
        source does not exist.

    Raises:
        OSError: The copy could not be staged or swapped in — callers must not
            proceed to write the passport they failed to back up.
    """
    source = Path(path)
    if not source.exists():
        return False

    backup = source.with_name(source.name + BACKUP_SUFFIX)
    if backup.exists():
        return False

    atomic_write_text(backup, source.read_text(encoding="utf-8"))
    logger.info("[migrate-passports] Backed up %s -> %s", source, backup.name)
    return True


# =============================================================================
# TRANSFORM — pure, no filesystem
# =============================================================================


def _canonical(document: dict) -> str:
    """Serialise order-sensitively, so key ORDER counts as a difference."""
    return json.dumps(document, indent=2, ensure_ascii=False)


def _lower_document_name(value: str) -> str:
    """Lowercase only the branch part of ``<branch>.PASSPORT``.

    ``AIPASS_SITE.PASSPORT`` -> ``aipass_site.PASSPORT``. The suffix is left
    exactly as found — this fixes casing on the name, it does not rename the
    document.
    """
    head, sep, tail = value.partition(".")
    return f"{head.lower()}{sep}{tail}"


def _migrate_citizen_class(current: object) -> str:
    """Resolve a passport's citizen_class to a live 2.0 class name.

    ``LEGACY_CLASSES`` is the single old->new table — the same one
    ``refuse_legacy_class`` quotes at the entry points. The entry points refuse
    the old names; THIS is the one sanctioned place that translates them, which
    is the whole reason the migration exists.

    Raises:
        PassportMigrationError: forbidden ("admin"), or a class that is neither
            live nor a known retired name. Both are "ask a human", not "guess".
    """
    value = current if isinstance(current, str) else ""
    refusal = refuse_forbidden_class(value)
    if refusal:
        raise PassportMigrationError(refusal)

    if value in CITIZEN_CLASSES:
        return value

    replacement = LEGACY_CLASSES.get(value.strip().lower())
    if replacement:
        return replacement

    available = ", ".join(sorted(CITIZEN_CLASSES))
    raise PassportMigrationError(
        f"identity.citizen_class {value!r} is neither a live class ({available}) "
        f"nor a known retired name — spawn will not guess a class for it."
    )


def _migrate_registry_path(current: object) -> tuple[str, bool]:
    """Return (value, reconciled) for citizenship.registry_path.

    Missing/blank backfills to the canonical path. A bare legacy
    ``*_REGISTRY.json`` filename (commons' outlier) reconciles to it. Any OTHER
    non-canonical value is left alone and reported — a project pointing
    somewhere deliberate is not drift, and overwriting it would be a guess.
    """
    value = current if isinstance(current, str) else ""
    if not value.strip():
        return CANONICAL_REGISTRY_PATH, True
    if value == CANONICAL_REGISTRY_PATH:
        return value, False
    if value.endswith("_REGISTRY.json") and "/" not in value and "\\" not in value:
        return CANONICAL_REGISTRY_PATH, True
    return value, False


def _migrate_traits(current: object) -> object:
    """2.0 says traits is a LIST; 20 of 22 live passports carry a STRING.

    JUDGMENT CALL, flagged in the build report: a non-empty string becomes a
    ONE-ELEMENT list holding that exact string. The content survives verbatim —
    only the container changes. Splitting the prose on commas would have been
    an edit to somebody's self-description, which this migration does not do.
    An empty string becomes ``[]`` (the template's own empty value). A list is
    already right and is returned untouched. Any other type is left exactly as
    found and reported, because inventing a conversion for it would be a guess.
    """
    if isinstance(current, list):
        return current
    if isinstance(current, str):
        return [current] if current.strip() else []
    return current


def _resolve_principles(document: dict, identity: dict) -> tuple[object, bool]:
    """Return (principles, moved) — R1 moves top-level principles into identity.

    Raises:
        PassportMigrationError: both copies exist and DISAGREE. Picking one
            would silently delete a version of somebody's principles.
    """
    has_top = "principles" in document
    has_identity = "principles" in identity

    if has_top and has_identity and document["principles"] != identity["principles"]:
        raise PassportMigrationError(
            "top-level `principles` and `identity.principles` both exist and differ — "
            "migrating would have to discard one of them. Reconcile them by hand, then re-run."
        )
    if has_top:
        return document["principles"], not has_identity
    if has_identity:
        return identity["principles"], False
    return None, False


def _order_block(block: dict, section: str) -> tuple[dict, list[str]]:
    """Emit one block in contract key order, dropping R8 keys.

    Unrecognised keys are APPENDED after the contract keys, in the order they
    were found, and returned for the receipt. Preserve-and-report, never drop.
    """
    order = KEY_ORDER[section]
    drops = DROPPED_KEYS.get(section, ())

    ordered = {key: block[key] for key in order if key in block}
    unknown: list[str] = []
    for key, value in block.items():
        if key in order or key in drops:
            continue
        ordered[key] = value
        unknown.append(f"{section}.{key}")
    return ordered, unknown


def migrate_document(
    document: dict,
    *,
    residency: str,
    relative_path: str,
    run_date: str,
) -> MigrationResult:
    """Transform one passport document to schema 2.0. Pure — no filesystem.

    Args:
        document: The parsed passport, left unmodified.
        residency: "core" or "resident", decided by WHERE the file lives.
        relative_path: The branch dir relative to its owning project root —
            ground truth for branch_info.path, measured off disk rather than
            trusted from the passport.
        run_date: YYYY-MM-DD stamped into last_updated, and ONLY when something
            else changed (see module docstring on idempotency).

    Returns:
        MigrationResult with the new document, whether it changed, the per-field
        change log, and any unrecognised fields that were preserved.

    Raises:
        PassportMigrationError: the document cannot be migrated without a guess.
    """
    changes: list[tuple[str, object, object]] = []

    def record(dotted: str, before: object, after: object) -> object:
        """Log a field change when the value actually moves, and return ``after``."""
        if before != after:
            changes.append((dotted, before, after))
        return after

    meta = dict(document.get("document_metadata") or {})
    info = dict(document.get("branch_info") or {})
    citizenship = dict(document.get("citizenship") or {})
    identity = dict(document.get("identity") or {})

    # --- branch_info -------------------------------------------------------
    branch_name = info.get("branch_name")
    if not isinstance(branch_name, str) or not branch_name.strip():
        raise PassportMigrationError("branch_info.branch_name is missing or empty")
    branch_name = record("branch_info.branch_name", branch_name, branch_name.lower())

    # path is DERIVED from where the passport actually sits, relative to the
    # project root that owns it. That one rule covers three defects at once:
    # skills' stale src/skills, and the four residents' hardcoded absolute
    # /home/... paths (public-repo house rule; R1 says {{PATH}} renders
    # relative). Four hardcoded strings would have fixed today's four files
    # and nothing else.
    record("branch_info.path", info.get("path"), relative_path)
    info["path"] = relative_path

    # A core citizen's import module is derivable from its name; residents own
    # their own package namespace and are left alone. Fixes commons -> and
    # skills -> the aipass.* prefix without a per-branch table.
    if residency == "core":
        info["module"] = record("branch_info.module", info.get("module"), f"aipass.{branch_name}")

    info["git_branch"] = record("branch_info.git_branch", info.get("git_branch"), TARGET_GIT_BRANCH)
    info["branch_name"] = branch_name

    # --- document_metadata -------------------------------------------------
    meta["version"] = record("document_metadata.version", meta.get("version"), SCHEMA_VERSION)
    meta["schema_version"] = record("document_metadata.schema_version", meta.get("schema_version"), SCHEMA_VERSION)

    managed_by = meta.get("managed_by")
    if isinstance(managed_by, str):
        meta["managed_by"] = record("document_metadata.managed_by", managed_by, managed_by.lower())

    document_name = meta.get("document_name")
    if isinstance(document_name, str):
        meta["document_name"] = record(
            "document_metadata.document_name", document_name, _lower_document_name(document_name)
        )

    # --- citizenship -------------------------------------------------------
    citizenship["residency"] = record("citizenship.residency", citizenship.get("residency"), residency)

    registry_path, reconciled = _migrate_registry_path(citizenship.get("registry_path"))
    if reconciled:
        record("citizenship.registry_path", citizenship.get("registry_path"), registry_path)
        citizenship["registry_path"] = registry_path

    # --- identity ----------------------------------------------------------
    identity["citizen_class"] = record(
        "identity.citizen_class",
        identity.get("citizen_class"),
        _migrate_citizen_class(identity.get("citizen_class")),
    )

    traits = _migrate_traits(identity.get("traits"))
    if "traits" in identity:
        record("identity.traits", identity["traits"], traits)
        identity["traits"] = traits

    principles, moved = _resolve_principles(document, identity)
    if principles is not None:
        identity["principles"] = principles
        if moved:
            changes.append(("principles -> identity.principles", "top-level", "identity"))

    blocks = {
        "document_metadata": meta,
        "branch_info": info,
        "citizenship": citizenship,
        "identity": identity,
    }

    # --- drops -------------------------------------------------------------
    for section, keys in DROPPED_KEYS.items():
        for key in keys:
            if key in blocks[section]:
                changes.append((f"{section}.{key}", blocks[section][key], "(dropped)"))
    for key in DROPPED_TOP_LEVEL:
        if key in document:
            changes.append((key, "(present)", "(dropped)"))

    # --- assemble in contract order ---------------------------------------
    # BLOCK_ORDER drives the assembly, it does not merely describe it: one
    # constant to read, and an order pin that actually bites when it moves.
    unknown: list[str] = []
    migrated: dict = {}
    for section in BLOCK_ORDER:
        migrated[section], block_unknown = _order_block(blocks[section], section)
        unknown.extend(block_unknown)

    # Unrecognised TOP-LEVEL blocks ride along after identity, reported.
    handled_top = set(BLOCK_ORDER) | set(DROPPED_TOP_LEVEL) | {"principles"}
    for key, value in document.items():
        if key in handled_top:
            continue
        migrated[key] = value
        unknown.append(key)

    changed = _canonical(migrated) != _canonical(document)
    if changed and migrated["document_metadata"].get("last_updated") != run_date:
        changes.append(("document_metadata.last_updated", migrated["document_metadata"].get("last_updated"), run_date))
        migrated["document_metadata"]["last_updated"] = run_date

    if changed and "block order" not in {name for name, _, _ in changes}:
        if tuple(document.keys()) != tuple(migrated.keys()):
            changes.append(("block order", " > ".join(document.keys()), " > ".join(migrated.keys())))

    return MigrationResult(document=migrated, changed=changed, changes=changes, unknown_fields=unknown)


# =============================================================================
# FILE + FLEET
# =============================================================================


def migrate_passport_file(
    target: PassportTarget,
    *,
    confirm: bool = False,
    run_date: str | None = None,
) -> dict:
    """Migrate one passport on disk. Writes nothing unless ``confirm``.

    Args:
        target: A discovered passport.
        confirm: False (default) plans only — no backup, no write, no mtime
            change. True backs the file up and writes it atomically.
        run_date: YYYY-MM-DD for last_updated. Defaults to today.

    Returns:
        A per-file record: branch, path, residency, changed, changes, unknown
        fields, whether a backup was written, and an error string if skipped.
    """
    stamp = run_date or datetime.now().strftime("%Y-%m-%d")
    record: dict = {
        "branch": target.branch_dir.name.lower(),
        "path": str(target.path),
        "residency": target.residency,
        "changed": False,
        "changes": [],
        "unknown_fields": [],
        "backup_written": False,
        "error": None,
    }

    try:
        raw = target.path.read_text(encoding="utf-8")
        document = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        record["error"] = f"unreadable passport: {exc}"
        logger.error("[migrate-passports] %s: %s", target.path, exc)
        return record

    if not isinstance(document, dict):
        record["error"] = "passport root is not a JSON object"
        return record

    try:
        result = migrate_document(
            document,
            residency=target.residency,
            relative_path=target.relative_path,
            run_date=stamp,
        )
    except PassportMigrationError as exc:
        record["error"] = str(exc)
        logger.error("[migrate-passports] %s skipped: %s", record["branch"], exc)
        return record

    record["changed"] = result.changed
    record["changes"] = result.changes
    record["unknown_fields"] = result.unknown_fields

    if not result.changed or not confirm:
        return record

    try:
        record["backup_written"] = backup_passport(target.path)
        atomic_write_text(target.path, _canonical(result.document) + "\n")
    except OSError as exc:
        record["error"] = f"write failed: {exc}"
        record["changed"] = False
        logger.error("[migrate-passports] %s write failed: %s", record["branch"], exc)
        return record

    logger.info("[migrate-passports] Migrated %s (%d change(s))", record["branch"], len(result.changes))
    return record


def migrate_fleet(
    root: Path | str | None = None,
    *,
    only: str | None = None,
    confirm: bool = False,
    run_date: str | None = None,
) -> dict:
    """Migrate every discovered passport and return a measured receipt.

    Args:
        root: Repo root to scan. Defaults to the live repo root.
        only: Restrict to one branch (``@`` and case are ignored).
        confirm: False (default) is a dry run — nothing is written at all.
        run_date: YYYY-MM-DD for last_updated. Defaults to today.

    Returns:
        Receipt dict: root, confirm, counts, per-field change tally, the
        per-file records, preserved-unknown fields, errors, and a
        ``baseline`` block comparing the discovered set to the measured fleet.
    """
    base = Path(root) if root is not None else repo_root()
    stamp = run_date or datetime.now().strftime("%Y-%m-%d")

    targets = discover_passports(base)
    discovered_total = len(targets)
    discovered_core = sum(1 for t in targets if t.residency == "core")

    wanted = (only or "").lstrip("@").strip().lower()
    if wanted:
        targets = [t for t in targets if t.branch_dir.name.lower() == wanted]

    records = [migrate_passport_file(t, confirm=confirm, run_date=stamp) for t in targets]

    field_counts: dict[str, int] = {}
    unknown_fields: dict[str, list[str]] = {}
    for rec in records:
        for name, _before, _after in rec["changes"]:
            field_counts[name] = field_counts.get(name, 0) + 1
        for name in rec["unknown_fields"]:
            unknown_fields.setdefault(name, []).append(rec["branch"])

    errors = [{"branch": r["branch"], "path": r["path"], "error": r["error"]} for r in records if r["error"]]

    # The baseline is an ALARM, not a gate: a filtered or re-rooted run is
    # expected to differ, and a real drift on the live root must be SAID rather
    # than swallowed. Never used to skip work — the discovered set is the truth.
    baseline = {
        "expected": dict(EXPECTED_FLEET),
        "discovered_total": discovered_total,
        "discovered_core": discovered_core,
        "discovered_resident": discovered_total - discovered_core,
        "filtered": bool(wanted),
        "matches": discovered_total == EXPECTED_FLEET["total"] and discovered_core == EXPECTED_FLEET["core"],
    }

    receipt = {
        "root": str(base),
        "confirm": confirm,
        "run_date": stamp,
        "only": wanted or None,
        "scanned": len(records),
        "changed": sum(1 for r in records if r["changed"]),
        "unchanged": sum(1 for r in records if not r["changed"] and not r["error"]),
        "backups_written": sum(1 for r in records if r["backup_written"]),
        "field_counts": dict(sorted(field_counts.items())),
        "unknown_fields": unknown_fields,
        "errors": errors,
        "files": records,
        "baseline": baseline,
    }

    # The WRITE is the event worth a durable record — a dry run leaves the
    # filesystem untouched and is logged by the CLI layer instead.
    if confirm and receipt["changed"]:
        json_handler.log_operation(
            "passports_migrated",
            data={"changed": receipt["changed"], "scanned": receipt["scanned"], "root": receipt["root"]},
        )

    return receipt
