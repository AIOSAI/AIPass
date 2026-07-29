# =================== AIPass ====================
# Name: class_registry.py
# Description: Citizen class registry — maps class names to template directories
# Version: 1.1.0
# Created: 2026-03-07
# Modified: 2026-07-27
# =============================================

"""Citizen class registry for spawn template system.

Maps citizen class names to their template directories. Each class
defines a different level of branch scaffold.

Classes:
    aipass_framework — Full 3-layer architecture (apps/, modules/, handlers/)
    project_agent — Project-root resident agent

"manager" is a third value that shows up in real passports' identity.citizen_class
(devpulse, every project_agent instance) but is NOT a template-selectable class here —
it's an identity/behavioral label that ai_mail's wake-block keys on (managers are
emailed, never dispatched). It resolves to two different template shapes depending on
who's wearing it, so it lives in IDENTITY_CITIZEN_CLASSES + resolve_template_class()
below rather than CITIZEN_CLASSES. See resolve_template_class() for the resolution rule.
"""

from pathlib import Path

# Templates directory (relative to this file)
_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"

# Registry of template-selectable citizen classes and their template directories.
# This is the creation-time class list (spawn create <class> <path>) — "manager" is
# deliberately absent, see module docstring.
CITIZEN_CLASSES = {
    "aipass_framework": {
        "template_dir": "aipass_framework",
        "description": "Full 3-layer branch with apps/, modules/, handlers/",
        "default": True,
    },
    "project_agent": {
        "template_dir": "project_agent",
        "description": "Project-root resident agent (manager class, collision-safe)",
        "default": False,
    },
}

# Valid identity.citizen_class values on a live passport — superset of CITIZEN_CLASSES.
# Used by resolve_template_class() to recognize "manager" as
# a real, known identity without making it template-selectable at creation time
# (validate_class()/get_available_classes() stay scoped to CITIZEN_CLASSES on purpose —
# they gate `spawn create <class>` and `update <class> --all`, both template-selection
# operations "manager" was never meant to answer).
IDENTITY_CITIZEN_CLASSES = frozenset(CITIZEN_CLASSES) | {"manager"}

# The default class when none is specified
DEFAULT_CLASS = "aipass_framework"


def get_template_dir(citizen_class: str = DEFAULT_CLASS) -> Path:
    """Return the absolute path to a citizen class template directory.

    Args:
        citizen_class: Name of the citizen class (e.g. "aipass_framework").

    Returns:
        Path to the template directory.

    Raises:
        ValueError: If the citizen class is not registered.
    """
    if citizen_class not in CITIZEN_CLASSES:
        available = ", ".join(sorted(CITIZEN_CLASSES.keys()))
        raise ValueError(f"Unknown citizen class '{citizen_class}'. Available: {available}")

    subdir = CITIZEN_CLASSES[citizen_class]["template_dir"]
    return _TEMPLATES_DIR / subdir


def get_available_classes() -> list[str]:
    """Return list of registered citizen class names."""
    return sorted(CITIZEN_CLASSES.keys())


def validate_class(name: str) -> bool:
    """Check if a citizen class name is template-selectable (spawn create / update --all)."""
    return name in CITIZEN_CLASSES


def get_default_class() -> str:
    """Return the default citizen class name."""
    return DEFAULT_CLASS


def resolve_template_class(identity: dict) -> str:
    """Resolve a passport's identity block to the template class it should update against.

    "manager" (identity.citizen_class) is worn by two structurally different branch
    kinds: devpulse (role="orchestration_hub", aipass_framework-shaped) and every
    project_agent instance (role="project_agent", project_agent-shaped). identity.role
    is the tiebreaker — it's a free-text CLI convention, not code-enforced, but it's the
    only signal a passport carries that distinguishes the two, and it holds for all live
    "manager" passports today. role == "project_agent" resolves to the project_agent
    template; any other role (including devpulse's "orchestration_hub") resolves to
    aipass_framework, the core-manager shape.

    Every other citizen_class must be a real, registered template class — no fallback.

    Raises:
        ValueError: citizen_class isn't "manager" and isn't a registered template class.
    """
    citizen_class = identity.get("citizen_class")
    if citizen_class == "manager":
        return "project_agent" if identity.get("role") == "project_agent" else "aipass_framework"
    if citizen_class in CITIZEN_CLASSES:
        return citizen_class
    available = ", ".join(sorted(IDENTITY_CITIZEN_CLASSES))
    raise ValueError(f"Unknown citizen_class '{citizen_class}'. Registered classes: {available}")
