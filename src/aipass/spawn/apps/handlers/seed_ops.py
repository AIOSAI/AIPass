# =================== AIPass ====================
# Name: seed_ops.py
# Description: Passport vaults — tracked identity, untracked live file (TDPLAN-0017)
# Version: 1.4.0
# Created: 2026-08-28
# Modified: 2026-11-20
# =============================================

"""Passport vaults: the identity that ships with the repo (TDPLAN-0017). Code names keep the older word seed.

The live passport is gitignored (tracking it is pull-hostile); the tracked vault is
generated from it by ``export-vault``, never hand-edited. Schema knowledge is
borrowed from ``passport_migration``, never re-declared. Both lanes refuse an
invalid document rather than write it.
Reference: docs/birth.md
"""

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path

from aipass.prax import logger

from aipass.spawn.apps.handlers.atomic_write import atomic_write_text
from aipass.spawn.apps.handlers.json_merge import backup_json
from aipass.spawn.apps.handlers.class_registry import resolve_template_class
from aipass.spawn.apps.handlers.json import json_handler
from aipass.spawn.apps.handlers.passport_migration import (
    BLOCK_ORDER,
    KEY_ORDER,
    SCHEMA_VERSION,
    PassportTarget,
    discover_passports,
)
from aipass.spawn.apps.handlers.placeholders import resolve_residency
from aipass.spawn.apps.handlers.registry import (
    _validate_path_containment,
    aipass_home,
    branches_as_list,
    entry_path,
    find_registry,
    load_registry,
)

__all__ = [
    "MACHINE_LOCAL_CITIZENSHIP",
    "OPTIONAL_KEYS",
    "LEGACY_FILE_NAME",
    "SEED_DIR_NAME",
    "VAULT_FILE_NAME",
    "VAULT_RELATIVE_PATH",
    "STAMP_KEY",
    "SeedError",
    "build_seed",
    "copy_seed_home",
    "home_seed_path",
    "canonical_text",
    "export_seed",
    "export_seeds",
    "find_seed",
    "load_seed",
    "mint_and_write",
    "mint_from_seed",
    "seed_fingerprint",
    "seed_path_for",
    "seed_stamp",
    "validate_passport",
    "validate_seed",
]


SEED_DIR_NAME = ".aipass"
VAULT_FILE_NAME = "passport.vault.json"
VAULT_RELATIVE_PATH = f"{SEED_DIR_NAME}/{VAULT_FILE_NAME}"
# The name 2.8.38 shipped: read when no vault is there, and retired by the next export.
LEGACY_FILE_NAME = "passport.seed.json"
HOME_VAULT_DIR = Path(".aipass") / "vault"

# Additive optional field: schema_version stays 2.0.0. A template mint gets no stamp.
STAMP_KEY = "seed"
STAMP_FIELDS = ("version", "sha256")

# Never shipped in a tracked seed; this tuple is also the privacy leak-guard's definition.
MACHINE_LOCAL_CITIZENSHIP = ("registered", "registry_id", "citizen_id", STAMP_KEY)

OPTIONAL_KEYS = {
    "citizenship": (STAMP_KEY,),
    "identity": ("class_extension",),
}

# The AIPass tree's export seeds core citizens only: a resident belongs to its own project's repo,
# and that project's own export (run at its registry) seeds it there.
SEED_RESIDENCY = "core"
TREE_REGISTRY_NAME = "AIPASS_REGISTRY.json"

# A passport declaring one of these is its project's own shape: no core schema is forced on it.
PROJECT_RESIDENCIES = ("resident", "external")

# Deliberately small, not a second schema engine. Unlisted fields must be strings.
_FIELD_TYPES = {
    ("document_metadata", "tags"): (list, "a list"),
    ("identity", "what_i_do"): (list, "a list"),
    ("identity", "what_i_dont_do"): (list, "a list"),
    ("identity", "traits"): (list, "a list"),
    ("identity", "principles"): (list, "a list"),
    ("citizenship", "registered"): (bool, "true/false"),
    ("citizenship", "communications"): (bool, "true/false"),
    ("citizenship", "memory"): (bool, "true/false"),
}
_DEFAULT_FIELD_TYPE = (str, "a string")

_STAMP_FIELD = {("citizenship", STAMP_KEY)}
_REQUIRED_NON_EMPTY = {
    ("document_metadata", "document_name"),
    ("document_metadata", "schema_version"),
    ("branch_info", "branch_name"),
    ("branch_info", "path"),
    ("citizenship", "residency"),
    ("identity", "citizen_class"),
}


class SeedError(Exception):
    """A seed that cannot be trusted. Callers refuse rather than write."""


def _key_order(section: str) -> tuple:
    """Canonical key order for a block, with the stamp appended to citizenship.

    Appended because that is where ``passport_migration._order_block`` puts an unknown key.
    """
    if section == "citizenship":
        return KEY_ORDER["citizenship"] + (STAMP_KEY,)
    return KEY_ORDER[section]


def seed_path_for(branch_dir) -> Path:
    """Return the passport vault path for a branch directory — ``<branch>/.aipass/passport.vault.json``.

    Inside the branch, never looked up by name, so no citizen can get another's identity.
    """
    return Path(branch_dir) / SEED_DIR_NAME / VAULT_FILE_NAME


def legacy_seed_path_for(branch_dir) -> Path:
    """The pre-vault name, ``<branch>/.aipass/passport.seed.json``: read when no vault is there."""
    return Path(branch_dir) / SEED_DIR_NAME / LEGACY_FILE_NAME


def home_seed_path(project_root, branch_dir) -> Path:
    """A project seat's durable vault copy: under the AIPass home (in @backup's scope), never in the product's git.

    Raises RuntimeError when no AIPass home is found."""
    seat = Path(branch_dir).name.lower()
    return aipass_home() / HOME_VAULT_DIR / Path(project_root).name / f"{seat}.{VAULT_FILE_NAME}"


def copy_seed_home(project_root, branch_dir) -> str:
    """Copy the seat's vault to its home copy; OSError or RuntimeError (no home) when it cannot."""
    dest = home_seed_path(project_root, branch_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(dest, seed_path_for(branch_dir).read_text(encoding="utf-8"))
    logger.info("[spawn] passport vault of %s copied to %s", branch_dir, dest)
    return f"copied to {dest}"


def find_seed(branch_dir) -> Path | None:
    """Return the branch's passport vault, else its pre-vault seed file, else None."""
    for candidate in (seed_path_for(branch_dir), legacy_seed_path_for(branch_dir)):
        if candidate.is_file():
            return candidate
    return None


def _validate_block(block: dict, section: str, *, kind: str) -> list[str]:
    """Return every problem with one block. Empty list means valid."""
    problems: list[str] = []
    order = _key_order(section)
    optional = set(OPTIONAL_KEYS.get(section, ()))

    forbidden = set(MACHINE_LOCAL_CITIZENSHIP) if (kind == "seed" and section == "citizenship") else set()
    required = [key for key in order if key not in optional and key not in forbidden]

    for key in forbidden & set(block):
        problems.append(
            f"{section}.{key} is machine-local and must never appear in a vault (it is minted fresh per install)"
        )
    for key in required:
        if key not in block:
            problems.append(f"{section}.{key} is missing")
    for key in block:
        if key not in order:
            problems.append(f"{section}.{key} is not a field of the {SCHEMA_VERSION} schema")

    present = [key for key in block if key in order]
    if present != [key for key in order if key in block]:
        problems.append(f"{section} keys are out of canonical order: {' > '.join(present)}")

    problems.extend(_validate_types(block, section))
    return problems


def _validate_types(block: dict, section: str) -> list[str]:
    """Type and emptiness rules for the fields whose shape is load-bearing."""
    problems: list[str] = []
    for key, value in block.items():
        field = (section, key)
        if field in _STAMP_FIELD:
            problems.extend(_validate_stamp(value))
        else:
            expected, label = _FIELD_TYPES.get(field, _DEFAULT_FIELD_TYPE)
            if not isinstance(value, expected):
                problems.append(f"{section}.{key} must be {label}, found {type(value).__name__}")

        if field in _REQUIRED_NON_EMPTY and isinstance(value, str) and not value.strip():
            problems.append(f"{section}.{key} is empty")
    return problems


def _validate_stamp(stamp) -> list[str]:
    """The stamp is a closed two-field record — a half-stamp is worse than none."""
    if not isinstance(stamp, dict):
        return [f"citizenship.{STAMP_KEY} must be an object, found {type(stamp).__name__}"]
    problems = [f"citizenship.{STAMP_KEY}.{key} is missing" for key in STAMP_FIELDS if key not in stamp]
    problems += [f"citizenship.{STAMP_KEY}.{key} is not a stamp field" for key in stamp if key not in STAMP_FIELDS]
    problems += [
        f"citizenship.{STAMP_KEY}.{key} must be a string"
        for key in STAMP_FIELDS
        if key in stamp and not isinstance(stamp[key], str)
    ]
    return problems


def _validate_document(document, *, kind: str) -> list[str]:
    """Return every problem with a passport-shaped document. Empty means valid. Never raises."""
    if not isinstance(document, dict):
        return [f"document root is not a JSON object (found {type(document).__name__})"]

    problems: list[str] = []
    for section in BLOCK_ORDER:
        if section not in document:
            problems.append(f"{section} block is missing")
    for key in document:
        if key not in BLOCK_ORDER:
            problems.append(f"top-level '{key}' is not a block of the {SCHEMA_VERSION} schema")

    present = [key for key in document if key in BLOCK_ORDER]
    if present != [key for key in BLOCK_ORDER if key in document]:
        problems.append(f"blocks are out of canonical order: {' > '.join(present)}")

    for section in BLOCK_ORDER:
        block = document.get(section)
        if block is None:
            continue
        if not isinstance(block, dict):
            problems.append(f"{section} is not a JSON object (found {type(block).__name__})")
            continue
        problems.extend(_validate_block(block, section, kind=kind))

    declared = (document.get("document_metadata") or {}).get("schema_version")
    if isinstance(declared, str) and declared and declared != SCHEMA_VERSION:
        problems.append(f"document_metadata.schema_version is {declared!r}, expected {SCHEMA_VERSION!r}")

    identity = document.get("identity")
    if isinstance(identity, dict) and "citizen_class" in identity:
        try:
            resolve_template_class(identity)
        except ValueError as exc:
            # Collected, not raised, so one bad field cannot hide the next.
            logger.warning("[seeds] citizen_class refused: %s", exc)
            problems.append(f"identity.citizen_class: {exc}")

    return problems


def _declares_project(document) -> bool:
    """True when the document says it is a resident or external citizen; anything else is held to 2.0."""
    citizenship = document.get("citizenship") if isinstance(document, dict) else None
    return isinstance(citizenship, dict) and citizenship.get("residency") in PROJECT_RESIDENCIES


def _validate_project_document(document, *, kind: str) -> list[str]:
    """A project passport is kept as its user wrote it; only what restore keys on and privacy are checked."""
    problems: list[str] = []
    for section, key in (("branch_info", "branch_name"), ("identity", "citizen_class")):
        block = document.get(section)
        value = block.get(key) if isinstance(block, dict) else None
        if not isinstance(value, str) or not value.strip():
            problems.append(f"{section}.{key} is missing or empty (restore reads it)")
    if kind == "seed":
        leaked = set(MACHINE_LOCAL_CITIZENSHIP) & set(document.get("citizenship") or {})
        problems += [
            f"citizenship.{key} is machine-local and must never appear in a vault (it is minted fresh per install)"
            for key in sorted(leaked)
        ]
    return problems


def validate_seed(document) -> list[str]:
    """Problems with a seed document — machine-local fields are FORBIDDEN."""
    if _declares_project(document):
        return _validate_project_document(document, kind="seed")
    return _validate_document(document, kind="seed")


def validate_passport(document) -> list[str]:
    """Problems with a live passport document — a core one's machine-local fields REQUIRED."""
    if _declares_project(document):
        return _validate_project_document(document, kind="passport")
    return _validate_document(document, kind="passport")


def _ordered_block(block: dict, section: str, drop: tuple = ()) -> dict:
    """Emit a block in canonical key order, dropping ``drop``.

    Unknown keys are appended, never removed: validation refuses them, the transform does not.
    """
    order = _key_order(section)
    ordered = {key: block[key] for key in order if key in block and key not in drop}
    for key, value in block.items():
        if key in order or key in drop:
            continue
        ordered[key] = value
    return ordered


def build_seed(passport: dict) -> dict:
    """Transform a live passport into its seed. Pure — no filesystem."""
    if not isinstance(passport, dict):
        raise SeedError(f"passport root is not a JSON object (found {type(passport).__name__})")

    seed: dict = {}
    for section in BLOCK_ORDER:
        if section not in passport:
            continue
        block = passport[section]
        if not isinstance(block, dict):
            seed[section] = block
            continue
        drop = MACHINE_LOCAL_CITIZENSHIP if section == "citizenship" else ()
        seed[section] = _ordered_block(block, section, drop=drop)

    for key, value in passport.items():
        if key not in BLOCK_ORDER:
            seed[key] = value
    return seed


def canonical_text(document: dict) -> str:
    """Serialise a seed or passport the one way either is ever written.

    Same form as ``passport_migration`` writes, so the files stay byte-comparable.
    """
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def seed_fingerprint(path) -> str:
    """SHA-256 of the seed FILE's bytes, hex (not a re-serialised copy, which could match a different file)."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def seed_stamp(seed: dict, path) -> dict:
    """Build the ``citizenship.seed`` stamp for a mint from ``path``."""
    version = (seed.get("document_metadata") or {}).get("version", "")
    return {"version": version, "sha256": seed_fingerprint(path)}


def load_seed(path) -> dict:
    """Read and validate a seed file; SeedError names every problem."""
    path = Path(path)
    try:
        raw = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SeedError(f"passport vault at {path} could not be read: {exc}") from exc

    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SeedError(f"passport vault at {path} is not valid JSON: {exc}") from exc

    problems = validate_seed(document)
    if problems:
        raise SeedError(
            f"passport vault at {path} is not a valid {SCHEMA_VERSION} passport vault:\n  - " + "\n  - ".join(problems)
        )
    return document


def mint_from_seed(seed: dict, seed_file, *, branch_name: str, registry_id: str, citizen_id: str) -> dict:
    """Render a live passport from a seed. Pure apart from hashing the seed file.

    Raises SeedError when the seed names another branch or the render does not validate.
    """
    declared = (seed.get("branch_info") or {}).get("branch_name", "")
    if declared != branch_name:
        raise SeedError(
            f"passport vault at {seed_file} belongs to branch {declared!r}, not {branch_name!r} — "
            f"spawn will not mint one citizen's identity into another."
        )

    passport = copy.deepcopy(seed)
    citizenship = dict(passport.get("citizenship") or {})
    citizenship["registered"] = True
    citizenship["registry_id"] = registry_id
    citizenship["citizen_id"] = citizen_id
    citizenship[STAMP_KEY] = seed_stamp(seed, seed_file)
    passport["citizenship"] = _ordered_block(citizenship, "citizenship")

    problems = validate_passport(passport)
    if problems:
        raise SeedError(
            f"passport rendered from {seed_file} is not a valid {SCHEMA_VERSION} passport, "
            f"nothing written:\n  - " + "\n  - ".join(problems)
        )
    return passport


def mint_and_write(seed_file, passport_path, *, branch_name: str, registry_id: str, citizen_id: str) -> dict:
    """Load a seed, mint the live passport, and write it atomically.

    Never the shared JSON writer: it escapes non-ASCII and breaks byte-comparability.
    SeedError means nothing was written; OSError means the write failed.
    """
    seed = load_seed(seed_file)
    passport = mint_from_seed(
        seed,
        seed_file,
        branch_name=branch_name,
        registry_id=registry_id,
        citizen_id=citizen_id,
    )
    passport_path = Path(passport_path)
    passport_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(passport_path, canonical_text(passport))
    return passport


def export_seed(target, *, confirm: bool = False) -> dict:
    """Export one branch's seed. Writes nothing unless ``confirm``."""
    seed_file = seed_path_for(target.branch_dir)
    record: dict = {
        "branch": target.branch_dir.name.lower(),
        "passport": str(target.path),
        "seed": str(seed_file),
        "residency": target.residency,
        "action": "skipped",
        "changed": False,
        "written": False,
        "error": None,
    }

    try:
        document = json.loads(target.path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        record["error"] = f"unreadable passport: {exc}"
        logger.error("[export-vault] %s: %s", target.path, exc)
        return record

    # A core branch is held to 2.0 by where it lives, whatever residency its passport declares.
    core = target.residency == SEED_RESIDENCY
    problems = _validate_document(document, kind="passport") if core else validate_passport(document)
    if problems:
        # A bad seed shipped to every clone is worse than a missing one.
        if core or not _declares_project(document):
            cure = "run `drone @spawn migrate-passports --confirm`, then re-run export-vault"
            record["error"] = f"live passport is not a valid {SCHEMA_VERSION} passport: "
        else:
            cure = "fix the named field in the passport, then re-run export-vault"
            record["error"] = "live passport cannot be restored from a passport vault: "
        record["error"] += "; ".join(problems) + f" - {cure}"
        logger.error("[export-vault] %s skipped: %s", record["branch"], record["error"])
        return record

    try:
        seed = build_seed(document)
    except SeedError as exc:
        record["error"] = str(exc)
        logger.error("[export-vault] %s skipped: %s", record["branch"], exc)
        return record

    seed_problems = _validate_document(seed, kind="seed") if core else validate_seed(seed)
    if seed_problems:
        record["error"] = "built passport vault did not validate: " + "; ".join(seed_problems)
        logger.error("[export-vault] %s skipped: %s", record["branch"], record["error"])
        return record

    wanted = canonical_text(seed)
    current = None
    if seed_file.exists():
        try:
            current = seed_file.read_text(encoding="utf-8")
        except OSError as exc:
            # Refuse: a blind overwrite would lose whatever the unreadable seed holds.
            record["error"] = f"existing passport vault unreadable: {exc}"
            logger.error("[export-vault] %s skipped: %s", record["branch"], exc)
            return record

    legacy = legacy_seed_path_for(target.branch_dir)
    if current == wanted and not legacy.is_file():
        record["action"] = "current"
        return record

    record["action"] = "updated" if current is not None or legacy.is_file() else "created"
    record["changed"] = True
    if not confirm:
        return record

    recovery = target.branch_dir / ".spawn" / ".recovery"
    try:
        seed_file.parent.mkdir(parents=True, exist_ok=True)
        if current is not None:
            # A refresh replaces a vault: the old one is kept where update keeps its backups.
            backup_json(seed_file, backup_dir=recovery)
        atomic_write_text(seed_file, wanted)
        if legacy.is_file():
            # Moved, never deleted: the vault now holds the identity, the old name keeps its bytes in recovery.
            recovery.mkdir(parents=True, exist_ok=True)
            legacy.replace(recovery / f"{LEGACY_FILE_NAME}.retired-{datetime.now():%Y%m%d-%H%M%S}")
            record["retired"] = str(legacy)
    except OSError as exc:
        record["error"] = f"write failed: {exc}"
        record["changed"] = False
        record["action"] = "skipped"
        logger.error("[export-vault] %s write failed: %s", record["branch"], exc)
        return record

    record["written"] = True
    logger.info("[export-vault] %s seed %s (%s)", record["branch"], record["action"], seed_file)
    if target.residency != SEED_RESIDENCY:
        _refresh_home_copy(target, record)
    return record


def _refresh_home_copy(target, record: dict) -> None:
    """Rewrite a project seat's home copy when it has one, so a restore never reads a stale identity."""
    try:
        home_copy = home_seed_path(target.project_root, target.branch_dir)
        if home_copy.is_file():
            copy_seed_home(target.project_root, target.branch_dir)
            record["home_copy"] = str(home_copy)
    except (OSError, RuntimeError) as exc:
        record["error"] = f"passport vault written, home copy not refreshed: {exc}"
        logger.error("[export-vault] %s: %s", record["branch"], record["error"])


def _project_targets(registry_path: Path) -> list[PassportTarget]:
    """Every citizen one project's registry lists with a passport inside that project."""
    targets: list[PassportTarget] = []
    for row in branches_as_list(load_registry(registry_path).get("branches", [])):
        name = row.get("name", "?")
        if not _validate_path_containment(row.get("path", ""), registry_path):
            logger.warning("[export-vault] %s: path %r is outside %s, skipped", name, row.get("path"), registry_path)
            continue
        branch_dir = registry_path.parent / entry_path(row)
        passport = branch_dir / ".trinity" / "passport.json"
        if not passport.is_file():
            logger.warning("[export-vault] %s at %s has no passport, not exported", name, branch_dir)
            continue
        targets.append(PassportTarget(passport, branch_dir, registry_path.parent, resolve_residency(branch_dir)))
    return targets


def export_seeds(root=None, *, only: str | None = None, confirm: bool = False) -> dict:
    """Export the seeds of the project at ``root`` (default: the cwd) and return a measured receipt.

    The nearest registry decides the scope. The AIPass tree's own registry exports core citizens
    only, through the 2.0 migration's discovery so the fleet commands agree on the fleet. Any other
    registry is a project: every citizen it lists is exported, whatever its residency.
    """
    start = Path(root) if root is not None else Path.cwd()
    registry_path = find_registry(start_path=start)
    if registry_path is None:
        logger.error("[export-vault] no *_REGISTRY.json at or above %s", start)
        raise FileNotFoundError(f"no *_REGISTRY.json at or above {start}: run export-vault inside a project")
    registry_path = Path(registry_path)
    base = registry_path.parent

    if registry_path.name == TREE_REGISTRY_NAME:
        scope = "core"
        discovered = discover_passports(base)
        core = [t for t in discovered if t.residency == SEED_RESIDENCY]
        skipped_resident = len(discovered) - len(core)
    else:
        scope = "project"
        core = _project_targets(registry_path)
        skipped_resident = 0

    wanted = (only or "").lstrip("@").strip().lower()
    targets = [t for t in core if t.branch_dir.name.lower() == wanted] if wanted else core

    records = [export_seed(target, confirm=confirm) for target in targets]
    errors = [{"branch": r["branch"], "error": r["error"]} for r in records if r["error"]]

    receipt = {
        "root": str(base),
        "scope": scope,
        "confirm": confirm,
        "only": wanted or None,
        "scanned": len(records),
        "created": sum(1 for r in records if r["action"] == "created"),
        "updated": sum(1 for r in records if r["action"] == "updated"),
        "current": sum(1 for r in records if r["action"] == "current"),
        "changed": sum(1 for r in records if r["changed"]),
        "written": sum(1 for r in records if r["written"]),
        "skipped_resident": skipped_resident,
        "errors": errors,
        "seeds": records,
    }

    # Dry runs are logged by the CLI layer instead.
    if confirm and receipt["written"]:
        json_handler.log_operation(
            "passport_seeds_exported",
            data={"written": receipt["written"], "scanned": receipt["scanned"], "root": receipt["root"]},
        )

    return receipt
