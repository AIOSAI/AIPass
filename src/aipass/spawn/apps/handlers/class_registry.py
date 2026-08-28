# =================== AIPass ====================
# Name: class_registry.py
# Description: Citizen class registry — the two citizen classes and the one template
# Version: 2.0.0
# Created: 2026-03-07
# Modified: 2026-08-27
# =============================================

"""Citizen class registry for spawn template system.

There is exactly ONE template on disk (``templates/citizen/``) and exactly two
citizen classes, and the two facts are DECOUPLED on purpose (DPLAN-0319, R3/R4):

    manager    — the first citizen of a project, the one who manages it
    specialist — every citizen minted after the first (DEFAULT_CLASS)

Both classes mint from the same template directory. The class is a *behavioral*
label carried in ``identity.citizen_class`` (ai_mail's wake-block keys on
"manager": managers are emailed, never dispatched); it is no longer a choice of
scaffold shape. That is why ``template_dir`` below is the same string for both
entries and why the directory is named for what it is (a citizen) rather than
for a class — a class-named template dir would be wrong by construction the
moment two classes share it.

The class is decided AT MINT from the citizen number, not typed by a caller —
see ``class_for_citizen_number``. An explicit caller-supplied class still wins.

"admin" is the permanent refusal: a devpulse-only registry privilege
(DPLAN-0288), not a class and not a template. The hospital never issues it,
only Patrick's ceremony does. See FORBIDDEN_CLASSES.

The retired names ("aipass_framework", "project_agent", "builder") REFUSE
LOUDLY and are never silently remapped — see ``refuse_legacy_class``. A silent
map would let a caller that still types the old name keep working while its
passport quietly says something else, which is the exact drift this rework
exists to end.
"""

from pathlib import Path

# Templates directory (relative to this file)
_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"

# The single template every citizen mints from, whatever their class.
TEMPLATE_DIR_NAME = "citizen"

# Registry of citizen classes. template_dir is identical for both entries —
# the class does not select a scaffold any more, see module docstring.
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

# Valid identity.citizen_class values on a live passport. This used to be a
# SUPERSET of CITIZEN_CLASSES because "manager" was an identity-only label with
# no template of its own. "manager" is a first-class registered class now, so
# the superset collapses to equality. The name is kept because it reads as the
# passport-side question ("is this a class a passport may claim?") and
# test_admin_fence.py:242 imports it.
IDENTITY_CITIZEN_CLASSES = frozenset(CITIZEN_CLASSES)

# The default class when none is specified
DEFAULT_CLASS = "specialist"

# Values spawn refuses to treat as a class or template — permanently, at every entry
# point (create, update, sync). Adding one here is a one-way door by design.
FORBIDDEN_CLASSES = frozenset({"admin"})

_FORBIDDEN_REASON = {
    "admin": (
        "'admin' is not a citizen class and never will be — it is a devpulse-only "
        "registry privilege (DPLAN-0288), granted once by Patrick's ceremony "
        "(drone @spawn grant-admin), never minted from a template."
    ),
}

# Retired class/template names → the class that replaced them (DPLAN-0319 R4).
# This map exists to WRITE A REFUSAL MESSAGE, never to translate a value:
# see refuse_legacy_class(). Callers still passing these are being fixed in
# parallel plans (@aipass's new_project passes "project_agent" today); until
# they land, a named refusal is the correct answer, not a quiet substitution.
LEGACY_CLASSES = {
    "aipass_framework": "specialist",
    "builder": "specialist",
    "project_agent": "manager",
}


def refuse_forbidden_class(name: str | None) -> str:
    """Return a named refusal for a permanently forbidden class value, else "".

    Case-insensitive. Truthy return means REFUSE and say this out loud — callers
    must never fall back to a default class when this fires.

    Args:
        name: Candidate citizen class / template value from a caller or passport.

    Returns:
        The refusal reason, or "" when the value is not forbidden.
    """
    key = (name or "").strip().lower()
    if key in FORBIDDEN_CLASSES:
        return _FORBIDDEN_REASON[key]
    return ""


def refuse_legacy_class(name: str | None) -> str:
    """Return a named refusal for a RETIRED class/template value, else "".

    The one message every entry point uses, so a caller stuck on an old name
    gets the same sentence from create, update, sync and regenerate-registry.
    Case-insensitive. Truthy return means REFUSE — never map the old value to
    the new one behind the caller's back.

    Args:
        name: Candidate citizen class / template value from a caller or passport.

    Returns:
        The refusal reason, or "" when the value is not a retired name.
    """
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
    """Return the first applicable refusal for a class value, else "".

    Convenience for the entry points that must check both doors. Forbidden is
    checked first: "admin" is a privilege refusal and outranks a rename notice.

    Args:
        name: Candidate citizen class / template value.

    Returns:
        The refusal reason, or "" when the value is neither forbidden nor retired.
    """
    return refuse_forbidden_class(name) or refuse_legacy_class(name)


def class_for_citizen_number(citizen_number: int) -> str:
    """Return the class a citizen is born with, from its number (DPLAN-0319 R3).

    The first citizen of a project manages it; everyone after is a specialist.
    The signal already exists at mint time (``get_next_citizen_number``), so the
    class is derived rather than typed — one less thing a caller can get wrong.

    Args:
        citizen_number: 1-based citizen number from the project registry.

    Returns:
        "manager" for citizen #1, DEFAULT_CLASS ("specialist") otherwise.
    """
    return "manager" if citizen_number == 1 else DEFAULT_CLASS


def get_template_dir(citizen_class: str = DEFAULT_CLASS) -> Path:
    """Return the absolute path to the template directory for a citizen class.

    Both registered classes resolve to the same directory — the argument is
    validated, not used to pick a scaffold.

    Args:
        citizen_class: Name of the citizen class ("manager" or "specialist").

    Returns:
        Path to the template directory.

    Raises:
        ValueError: If the citizen class is forbidden, retired, or not registered.
    """
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

    Both classes map to one directory today, so iterating classes to do
    per-template work (regenerate-registry --all) would do the same work twice
    and report it as two templates. Callers that mean "every template" ask here.
    """
    seen: dict[str, Path] = {}
    for spec in CITIZEN_CLASSES.values():
        subdir = spec["template_dir"]
        seen.setdefault(subdir, _TEMPLATES_DIR / subdir)
    return [seen[key] for key in sorted(seen)]


def get_available_classes() -> list[str]:
    """Return list of registered citizen class names."""
    return sorted(CITIZEN_CLASSES.keys())


def validate_class(name: str) -> bool:
    """Check if a citizen class name is registered (spawn create / update --all).

    A pure predicate — it answers "is this one of the two class names", nothing
    more. Retired and forbidden names answer False here; the entry points that
    need to SAY WHY call refuse_retired_or_forbidden() alongside it.
    """
    return name in CITIZEN_CLASSES


def get_default_class() -> str:
    """Return the default citizen class name."""
    return DEFAULT_CLASS


def resolve_template_class(identity: dict) -> str:
    """Resolve a passport's identity block to the template class it updates against.

    Both classes mint and update from the same template, so this is now a
    validation step rather than a fork: a passport's ``identity.citizen_class``
    must be one of the two registered classes and is returned unchanged.

    The ``role == "project_agent"`` tiebreaker that used to live here died with
    the template fork — there is no second template shape left to choose, so
    reading free text to pick one would be inventing a distinction.

    No fallback. A passport claiming a FORBIDDEN class ("admin") is refused by
    name — privilege is never self-declared, and spawn will not hand it a
    template either. A passport still carrying a RETIRED class is refused by
    name too, so it shows up as "migrate this passport", not as a silent update
    against a class it no longer claims.

    Raises:
        ValueError: citizen_class is forbidden, retired, or not a registered class.
    """
    citizen_class = identity.get("citizen_class")
    refusal = refuse_retired_or_forbidden(citizen_class)
    if refusal:
        raise ValueError(refusal)
    if citizen_class in CITIZEN_CLASSES:
        return citizen_class
    available = ", ".join(sorted(IDENTITY_CITIZEN_CLASSES))
    raise ValueError(f"Unknown citizen_class '{citizen_class}'. Registered classes: {available}")
