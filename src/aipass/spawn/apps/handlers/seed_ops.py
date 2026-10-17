# =================== AIPass ====================
# Name: seed_ops.py
# Description: Passport seeds — tracked identity, untracked live file (TDPLAN-0017)
# Version: 1.0.0
# Created: 2026-08-28
# Modified: 2026-10-17
# =============================================

"""Passport seeds: the identity that ships with the repo (TDPLAN-0017).

The live passport is gitignored (tracking it is pull-hostile); the tracked seed is
generated from it by ``export-seeds``, never hand-edited. Schema knowledge is
borrowed from ``passport_migration``, never re-declared. Both lanes refuse an
invalid document rather than write it.
Reference: docs/birth.md
"""

import copy
import hashlib
import json
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.spawn.apps.handlers.atomic_write import atomic_write_text
from aipass.spawn.apps.handlers.class_registry import resolve_template_class
from aipass.spawn.apps.handlers.json import json_handler
from aipass.spawn.apps.handlers.passport_migration import (
    BLOCK_ORDER,
    EXPECTED_FLEET,
    KEY_ORDER,
    SCHEMA_VERSION,
    discover_passports,
    repo_root,
)

__all__ = [
    "MACHINE_LOCAL_CITIZENSHIP",
    "OPTIONAL_KEYS",
    "SEED_DIR_NAME",
    "SEED_FILE_NAME",
    "SEED_RELATIVE_PATH",
    "STAMP_KEY",
    "SeedError",
    "build_seed",
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
SEED_FILE_NAME = "passport.seed.json"
SEED_RELATIVE_PATH = f"{SEED_DIR_NAME}/{SEED_FILE_NAME}"

# Additive optional field: schema_version stays 2.0.0. A template mint gets no stamp.
STAMP_KEY = "seed"
STAMP_FIELDS = ("version", "sha256")

# Never shipped in a tracked seed; this tuple is also the privacy leak-guard's definition.
MACHINE_LOCAL_CITIZENSHIP = ("registered", "registry_id", "citizen_id", STAMP_KEY)

OPTIONAL_KEYS = {
    "citizenship": (STAMP_KEY,),
    "identity": ("class_extension",),
}

# Residents belong to their own project's repo, so only core citizens get seeds.
SEED_RESIDENCY = "core"

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
    """Return the seed path for a branch directory — ``<branch>/.aipass/...``.

    Inside the branch, never looked up by name, so no citizen can get another's identity.
    """
    return Path(branch_dir) / SEED_DIR_NAME / SEED_FILE_NAME


def find_seed(branch_dir) -> Path | None:
    """Return the branch's seed file, or None when it carries none."""
    candidate = seed_path_for(branch_dir)
    return candidate if candidate.is_file() else None


def _validate_block(block: dict, section: str, *, kind: str) -> list[str]:
    """Return every problem with one block. Empty list means valid."""
    problems: list[str] = []
    order = _key_order(section)
    optional = set(OPTIONAL_KEYS.get(section, ()))

    forbidden = set(MACHINE_LOCAL_CITIZENSHIP) if (kind == "seed" and section == "citizenship") else set()
    required = [key for key in order if key not in optional and key not in forbidden]

    for key in forbidden & set(block):
        problems.append(
            f"{section}.{key} is machine-local and must never appear in a seed (it is minted fresh per install)"
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


def validate_seed(document) -> list[str]:
    """Problems with a seed document — machine-local fields are FORBIDDEN."""
    return _validate_document(document, kind="seed")


def validate_passport(document) -> list[str]:
    """Problems with a live passport document — machine-local fields REQUIRED."""
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
        raise SeedError(f"seed at {path} could not be read: {exc}") from exc

    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SeedError(f"seed at {path} is not valid JSON: {exc}") from exc

    problems = validate_seed(document)
    if problems:
        raise SeedError(
            f"seed at {path} is not a valid {SCHEMA_VERSION} passport seed:\n  - " + "\n  - ".join(problems)
        )
    return document


def mint_from_seed(seed: dict, seed_file, *, branch_name: str, registry_id: str, citizen_id: str) -> dict:
    """Render a live passport from a seed. Pure apart from hashing the seed file.

    Raises SeedError when the seed names another branch or the render does not validate.
    """
    declared = (seed.get("branch_info") or {}).get("branch_name", "")
    if declared != branch_name:
        raise SeedError(
            f"seed at {seed_file} belongs to branch {declared!r}, not {branch_name!r} — "
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
        logger.error("[export-seeds] %s: %s", target.path, exc)
        return record

    problems = validate_passport(document)
    if problems:
        # A bad seed shipped to every clone is worse than a missing one.
        record["error"] = f"live passport is not a valid {SCHEMA_VERSION} passport: " + "; ".join(problems)
        logger.error("[export-seeds] %s skipped: %s", record["branch"], record["error"])
        return record

    try:
        seed = build_seed(document)
    except SeedError as exc:
        record["error"] = str(exc)
        logger.error("[export-seeds] %s skipped: %s", record["branch"], exc)
        return record

    seed_problems = validate_seed(seed)
    if seed_problems:
        record["error"] = "built seed did not validate: " + "; ".join(seed_problems)
        logger.error("[export-seeds] %s skipped: %s", record["branch"], record["error"])
        return record

    wanted = canonical_text(seed)
    current = None
    if seed_file.exists():
        try:
            current = seed_file.read_text(encoding="utf-8")
        except OSError as exc:
            # Refuse: a blind overwrite would lose whatever the unreadable seed holds.
            record["error"] = f"existing seed unreadable: {exc}"
            logger.error("[export-seeds] %s skipped: %s", record["branch"], exc)
            return record

    if current == wanted:
        record["action"] = "current"
        return record

    record["action"] = "updated" if current is not None else "created"
    record["changed"] = True
    if not confirm:
        return record

    try:
        seed_file.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(seed_file, wanted)
    except OSError as exc:
        record["error"] = f"write failed: {exc}"
        record["changed"] = False
        record["action"] = "skipped"
        logger.error("[export-seeds] %s write failed: %s", record["branch"], exc)
        return record

    record["written"] = True
    logger.info("[export-seeds] %s seed %s (%s)", record["branch"], record["action"], seed_file)
    return record


def export_seeds(root=None, *, only: str | None = None, confirm: bool = False) -> dict:
    """Export every core citizen's seed and return a measured receipt.

    Shares discovery with the 2.0 migration so the fleet commands agree on the fleet.
    """
    base = Path(root) if root is not None else repo_root()

    discovered = discover_passports(base)
    core = [t for t in discovered if t.residency == SEED_RESIDENCY]
    skipped_resident = len(discovered) - len(core)

    wanted = (only or "").lstrip("@").strip().lower()
    targets = [t for t in core if t.branch_dir.name.lower() == wanted] if wanted else core

    records = [export_seed(target, confirm=confirm) for target in targets]
    errors = [{"branch": r["branch"], "error": r["error"]} for r in records if r["error"]]

    # An alarm, never a gate: the discovered set is the truth.
    baseline = {
        "expected_core": EXPECTED_FLEET["core"],
        "discovered_core": len(core),
        "filtered": bool(wanted),
        "matches": len(core) == EXPECTED_FLEET["core"],
    }

    receipt = {
        "root": str(base),
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
        "baseline": baseline,
    }

    # Dry runs are logged by the CLI layer instead.
    if confirm and receipt["written"]:
        json_handler.log_operation(
            "passport_seeds_exported",
            data={"written": receipt["written"], "scanned": receipt["scanned"], "root": receipt["root"]},
        )

    return receipt
