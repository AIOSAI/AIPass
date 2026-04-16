# =================== AIPass ====================
# Name: class_registry.py
# Description: Citizen class registry — maps class names to template directories
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-10
# =============================================

"""Citizen class registry for spawn template system.

Maps citizen class names to their template directories. Each class
defines a different level of branch scaffold.

Classes:
    builder     — Full 3-layer architecture (apps/, modules/, handlers/)
    birthright  — Minimal citizenship (.trinity/, .aipass/, README.md only)
"""

from pathlib import Path

# Templates directory (relative to this file)
_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"

# Registry of citizen classes and their template directories
CITIZEN_CLASSES = {
    "builder": {
        "template_dir": "builder",
        "description": "Full 3-layer branch with apps/, modules/, handlers/",
        "default": True,
    },
    "birthright": {
        "template_dir": "birthright",
        "description": "Minimal citizenship — .trinity/, .aipass/, README.md",
        "default": False,
    },
}

# The default class when none is specified
DEFAULT_CLASS = "builder"


def get_template_dir(citizen_class: str = DEFAULT_CLASS) -> Path:
    """Return the absolute path to a citizen class template directory.

    Args:
        citizen_class: Name of the citizen class (e.g. "builder", "birthright").

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
    """Check if a citizen class name is valid."""
    return name in CITIZEN_CLASSES


def get_default_class() -> str:
    """Return the default citizen class name."""
    return DEFAULT_CLASS
