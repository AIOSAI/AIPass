# =================== AIPass ====================
# Name: class_registry.py
# Description: Citizen class registry — the two citizen classes and the one template
# Version: 2.0.0
# Created: 2026-03-07
# Modified: 2026-10-17
# =============================================

"""Citizen class registry for spawn template system.

One template, two classes: the class is a behavioral label (ai_mail emails a manager, never dispatches it)."""

from pathlib import Path

_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"

TEMPLATE_DIR_NAME = "citizen"

CITIZEN_CLASSES = {
    "manager": {
        "template_dir": TEMPLATE_DIR_NAME,
        "description": "A project's first citizen — manages the project",
        "default": False,
    },
    "specialist": {
        "template_dir": TEMPLATE_DIR_NAME,
        "description": "Domain specialist — every citizen after the first",
        "default": True,
    },
}

# Equal to CITIZEN_CLASSES; kept as the passport-side name, and test_admin_fence.py imports it.
IDENTITY_CITIZEN_CLASSES = frozenset(CITIZEN_CLASSES)

DEFAULT_CLASS = "specialist"

# Refused at every entry point (create, update, sync); adding one is a one-way door by design.
FORBIDDEN_CLASSES = frozenset({"admin"})

_FORBIDDEN_REASON = {
    "admin": (
        "'admin' is not a citizen class and never will be — it is a devpulse-only "
        "registry privilege (DPLAN-0288), granted once by the owner's ceremony "
        "(drone @spawn grant-admin), never minted from a template."
    ),
}

# Retired names: this map writes a refusal message, never translates a value.
LEGACY_CLASSES = {
    "aipass_framework": "specialist",
    "builder": "specialist",
    "project_agent": "manager",
}


def refuse_forbidden_class(name: str | None) -> str:
    """Return a named refusal for a permanently forbidden class value, else "".

    A truthy return means refuse: callers must never fall back to a default class."""
    key = (name or "").strip().lower()
    if key in FORBIDDEN_CLASSES:
        return _FORBIDDEN_REASON[key]
    return ""


def refuse_legacy_class(name: str | None) -> str:
    """Return a named refusal for a RETIRED class/template value, else "".

    A truthy return means refuse: a silent remap would let the passport disagree with the typed value."""
    key = (name or "").strip().lower()
    replacement = LEGACY_CLASSES.get(key)
    if not replacement:
        return ""
    return (
        f"'{key}' is a retired citizen class (DPLAN-0319). The classes are "
        f"'manager' (a project's first agent) and 'specialist' (everyone else); "
        f"'{key}' now means '{replacement}'. Pass '{replacement}' explicitly, or pass "
        f"no class at all and let spawn decide at mint from the citizen number. "
        f"Spawn will not translate the old name for you — the passport it wrote "
        f"would then disagree with the value you typed."
    )


def refuse_retired_or_forbidden(name: str | None) -> str:
    """Return the first applicable refusal for a class value, else ""."""
    return refuse_forbidden_class(name) or refuse_legacy_class(name)


def class_for_citizen_number(citizen_number: int) -> str:
    """Return the class a citizen is born with, from its number (DPLAN-0319 R3)."""
    return "manager" if citizen_number == 1 else DEFAULT_CLASS


def get_template_dir(citizen_class: str = DEFAULT_CLASS) -> Path:
    """Return the absolute path to the template directory for a citizen class.

    The argument is validated, not used to pick a scaffold: every class shares one directory."""
    refusal = refuse_retired_or_forbidden(citizen_class)
    if refusal:
        raise ValueError(refusal)

    if citizen_class not in CITIZEN_CLASSES:
        available = ", ".join(sorted(CITIZEN_CLASSES.keys()))
        raise ValueError(f"Unknown citizen class '{citizen_class}'. Available: {available}")

    subdir = CITIZEN_CLASSES[citizen_class]["template_dir"]
    return _TEMPLATES_DIR / subdir


def get_template_dirs() -> list[Path]:
    """Return every distinct template directory, deduplicated.

    Callers meaning "every template" ask here; iterating classes would do one template twice."""
    seen: dict[str, Path] = {}
    for spec in CITIZEN_CLASSES.values():
        subdir = spec["template_dir"]
        seen.setdefault(subdir, _TEMPLATES_DIR / subdir)
    return [seen[key] for key in sorted(seen)]


def get_available_classes() -> list[str]:
    """Return list of registered citizen class names."""
    return sorted(CITIZEN_CLASSES.keys())


def validate_class(name: str) -> bool:
    """Check if a citizen class name is registered (spawn create / update --all)."""
    return name in CITIZEN_CLASSES


def get_default_class() -> str:
    """Return the default citizen class name."""
    return DEFAULT_CLASS


def resolve_template_class(identity: dict) -> str:
    """Resolve a passport's identity block to the template class it updates against.

    No fallback: forbidden, retired or unknown classes raise ValueError by name."""
    citizen_class = identity.get("citizen_class")
    refusal = refuse_retired_or_forbidden(citizen_class)
    if refusal:
        raise ValueError(refusal)
    if citizen_class in CITIZEN_CLASSES:
        return citizen_class
    available = ", ".join(sorted(IDENTITY_CITIZEN_CLASSES))
    raise ValueError(f"Unknown citizen_class '{citizen_class}'. Registered classes: {available}")
