# =================== AIPass ====================
# Name: passport_migration.py
# Description: Passport 2.0 fleet migration — structure transform, backup, measured receipt
# Version: 1.0.0
# Created: 2026-08-28
# Modified: 2026-10-17
# =============================================

"""One-shot fleet migration of every live passport to schema 2.0 (DPLAN-0319).

Moves fields, renames dead values, fixes shapes; never authors identity content. Never silently
drops (only the R8 keys go; unknowns are kept and reported), never guesses (refuse and skip), and
stamps last_updated only when something else changed, so a re-run is a measured no-op.
Reference: docs/registry_and_repair.md
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


SCHEMA_VERSION = "2.0.0"
TARGET_GIT_BRANCH = "dev"
CANONICAL_REGISTRY_PATH = ".aipass/registry.json"
BACKUP_SUFFIX = ".pre_v2_backup"

BLOCK_ORDER = ("document_metadata", "branch_info", "citizenship", "identity")

# ``class_extension`` is never created here, only kept in its place where a passport carries one.
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

# Nothing else is ever removed.
DROPPED_KEYS = {
    "citizenship": ("owner",),
    "document_metadata": ("note",),
}
DROPPED_TOP_LEVEL = ("family",)

# Must never be authored or edited here; tests/test_passport_migration.py asserts it.
IDENTITY_CONTENT_KEYS = (
    "class_extension",
    "role",
    "purpose",
    "what_i_do",
    "what_i_dont_do",
    "traits",
    "principles",
)

# The baseline is an alarm, never a gate: drift is reported, the discovered set is the truth.
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


def repo_root() -> Path:
    """Return the AIPass repo root, derived from this file's own location."""
    return Path(__file__).resolve().parents[5]


def _is_hidden_path(passport: Path, base: Path) -> bool:
    """True when any directory between ``base`` and ``.trinity`` starts with a dot.

    A rule, not a blocklist: no citizen directory begins with a dot, so every archive convention is refused.
    """
    try:
        relative = passport.relative_to(base)
    except ValueError:
        # Unreachable today (both globs are anchored); logged so an unanchored caller is seen.
        logger.warning(f"[spawn] Passport outside the scanned root, refused: {passport}")
        return True
    # Drop the trailing ".trinity/passport.json" the globs both end with.
    return any(part.startswith(".") for part in relative.parts[:-2])


def discover_passports(root: Path | str | None = None) -> list[PassportTarget]:
    """Glob every live fleet passport under ``root``.

    Residency is read off the location, not the passport being corrected. Dotted directories are
    refused by rule: retiring a citizen is a registry act a passport walk cannot see.
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


def backup_passport(path: Path | str) -> bool:
    """Copy a passport to ``<name>.pre_v2_backup``, once and only once.

    Never overwrites: the first copy is the only way back. False if one existed or no source.
    Raises OSError on a failed copy; callers must not then write the passport.
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


def _canonical(document: dict) -> str:
    """Serialise order-sensitively, so key ORDER counts as a difference."""
    return json.dumps(document, indent=2, ensure_ascii=False)


def _lower_document_name(value: str) -> str:
    """Lowercase only the branch part of ``<branch>.PASSPORT``; the suffix is left as found."""
    head, sep, tail = value.partition(".")
    return f"{head.lower()}{sep}{tail}"


def _migrate_citizen_class(current: object) -> str:
    """Resolve a passport's citizen_class to a live 2.0 class name.

    The one sanctioned place that translates retired names (entry points refuse them).
    Raises PassportMigrationError for a forbidden or unknown class.
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

    Blank or a bare legacy ``*_REGISTRY.json`` reconciles; any other value may be deliberate and stays.
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

    A string becomes a one-element list verbatim (splitting on commas would edit the prose); "" -> [].
    """
    if isinstance(current, list):
        return current
    if isinstance(current, str):
        return [current] if current.strip() else []
    return current


def _resolve_principles(document: dict, identity: dict) -> tuple[object, bool]:
    """Return (principles, moved) — R1 moves top-level principles into identity.

    Raises PassportMigrationError when both copies exist and disagree.
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

    Unrecognised keys are appended after the contract keys and returned for the receipt."""
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

    Raises PassportMigrationError when the document cannot be migrated without a guess.
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

    branch_name = info.get("branch_name")
    if not isinstance(branch_name, str) or not branch_name.strip():
        raise PassportMigrationError("branch_info.branch_name is missing or empty")
    branch_name = record("branch_info.branch_name", branch_name, branch_name.lower())

    # Derived from where the passport sits, never trusted from it: stale and absolute paths both fall.
    record("branch_info.path", info.get("path"), relative_path)
    info["path"] = relative_path

    # Residents own their package namespace; only a core module is derivable from its name.
    if residency == "core":
        info["module"] = record("branch_info.module", info.get("module"), f"aipass.{branch_name}")

    info["git_branch"] = record("branch_info.git_branch", info.get("git_branch"), TARGET_GIT_BRANCH)
    info["branch_name"] = branch_name

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

    citizenship["residency"] = record("citizenship.residency", citizenship.get("residency"), residency)

    registry_path, reconciled = _migrate_registry_path(citizenship.get("registry_path"))
    if reconciled:
        record("citizenship.registry_path", citizenship.get("registry_path"), registry_path)
        citizenship["registry_path"] = registry_path

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

    for section, keys in DROPPED_KEYS.items():
        for key in keys:
            if key in blocks[section]:
                changes.append((f"{section}.{key}", blocks[section][key], "(dropped)"))
    for key in DROPPED_TOP_LEVEL:
        if key in document:
            changes.append((key, "(present)", "(dropped)"))

    # BLOCK_ORDER drives the assembly, so an order pin bites when it moves.
    unknown: list[str] = []
    migrated: dict = {}
    for section in BLOCK_ORDER:
        migrated[section], block_unknown = _order_block(blocks[section], section)
        unknown.extend(block_unknown)

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


def migrate_passport_file(
    target: PassportTarget,
    *,
    confirm: bool = False,
    run_date: str | None = None,
) -> dict:
    """Migrate one passport on disk. Writes nothing unless ``confirm``.

    Without confirm: no backup, no write, no mtime change. ``error`` is set when the file is skipped.
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

    Without confirm nothing is written at all.
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

    # A dry run is logged by the CLI layer instead.
    if confirm and receipt["changed"]:
        json_handler.log_operation(
            "passports_migrated",
            data={"changed": receipt["changed"], "scanned": receipt["scanned"], "root": receipt["root"]},
        )

    return receipt
