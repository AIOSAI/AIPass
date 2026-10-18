# =================== AIPass ====================
# Name: core.py
# Description: Main orchestrator for agent spawning
# Version: 1.4.2
# Created: 2026-03-05
# Modified: 2026-10-17
# =============================================

"""
Spawn Module — Create new AIPass agents from templates.
Reference: docs/birth.md
"""

from pathlib import Path
from typing import List

from aipass.prax import logger

try:
    from aipass.cli.apps.modules.display import console
# A peer's import-time access guard touches the filesystem, so a broken peer raises OSError
# (dead cwd), not only ImportError; catching ImportError alone makes "broken" fatal.
except (ImportError, OSError) as e:
    logger.warning("Failed to import aipass.cli.apps.modules.display, falling back to rich.console: %s", e)
    from rich.console import Console

    console = Console()

# apps/spawn.py imports these two from here, so they are re-exported by name.
from aipass.spawn.apps.handlers.metadata import (
    get_branch_name as get_branch_name,
    normalize_branch_name as normalize_branch_name,
)
from aipass.spawn.apps.handlers.adoption_ops import adopt_existing, birth_from_seed, error_result
from aipass.spawn.apps.handlers.class_registry import (
    get_template_dir as get_template_dir,
    validate_class as validate_class,
    get_default_class as get_default_class,
    get_available_classes as get_available_classes,
    refuse_forbidden_class as refuse_forbidden_class,
    refuse_retired_or_forbidden as refuse_retired_or_forbidden,
    class_for_citizen_number as class_for_citizen_number,
)
from aipass.spawn.apps.handlers.mint_ops import spawn_at

# One template for every citizen: the class no longer picks a scaffold.
DEFAULT_TEMPLATE = Path(__file__).parents[2] / "templates" / "citizen"

_META_TAB_KEYS = {"TODOS_META", "KEY_LEARNINGS_META", "SESSIONS_META", "OBSERVATIONS_META"}


def _load_meta_tabs(branch_dir: str | None = None):
    """Load memory meta-tab values from @memory's renderer.

    Returns empty dict when @memory is unavailable (standalone project).
    """
    try:
        from aipass.memory.apps.modules.door_tab_renderer import render_all_meta_tabs
    # Width, not politeness: see the module-level import above.
    except (ImportError, OSError) as e:
        logger.info("[spawn] @memory not available — meta-tab placeholders will be empty (%s)", e)
        return {}

    tabs = render_all_meta_tabs(branch_dir)
    missing = _META_TAB_KEYS - set(tabs or {})
    if missing:
        raise RuntimeError(f"render_all_meta_tabs() missing keys: {sorted(missing)}")
    return tabs


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]core Module[/bold cyan]")
    console.print("Agent creation orchestrator — full spawn workflow from template to registry")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/[/cyan]")
    console.print(
        "    [dim]- mint_ops.py (spawn_at, mint_citizen — the lane and the mint body, called by spawn_agent)[/dim]"
    )
    console.print(
        "    [dim]- metadata.py (get_branch_name, normalize_branch_name, detect_profile — branch identity)[/dim]"
    )
    console.print(
        "    [dim]- placeholders.py (build_replacements_dict, validate_no_placeholders — template substitution)[/dim]"
    )
    console.print(
        "    [dim]- file_ops.py (copy_template, rename_placeholder_paths,"
        " regenerate_template_registry, ensure_directory — filesystem ops)[/dim]"
    )
    console.print(
        "    [dim]- meta_ops.py"
        " (load_template_registry, generate_branch_meta, save_branch_meta — branch metadata)[/dim]"
    )
    console.print(
        "    [dim]- registry.py"
        " (find_registry, add_to_registry, get_next_citizen_number — AIPASS_REGISTRY management)[/dim]"
    )
    console.print(
        "    [dim]- class_registry.py (validate_class, get_default_class,"
        " get_available_classes, get_template_dir — citizen class lookup)[/dim]"
    )
    console.print(
        "    [dim]- seed_ops.py (find_seed, load_seed, mint_from_seed — mint a citizen from its tracked seed)[/dim]"
    )
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Route spawn commands to implementation."""
    if not args:
        print_introspection()
        return True

    if "--help" in args:
        print_introspection()
        return True

    if command == "create":
        if not args:
            logger.error("spawn create requires a target path")
            return False
        target_path = args[0]
        kwargs = {}
        i = 1
        while i < len(args):
            if args[i] == "--role" and i + 1 < len(args):
                kwargs["role"] = args[i + 1]
                i += 2
            elif args[i] == "--traits" and i + 1 < len(args):
                kwargs["traits"] = args[i + 1]
                i += 2
            elif args[i] == "--purpose" and i + 1 < len(args):
                kwargs["purpose"] = args[i + 1]
                i += 2
            elif args[i] == "--template" and i + 1 < len(args):
                template_val = args[i + 1]
                # Refuse a retired class by name, or it is read as a template directory path.
                refusal = refuse_retired_or_forbidden(template_val)
                if refusal:
                    logger.error(refusal)
                    return False
                if validate_class(template_val):
                    kwargs["citizen_class"] = template_val
                else:
                    kwargs["template_dir"] = template_val
                i += 2
            elif args[i] == "--registry" and i + 1 < len(args):
                kwargs["registry_path"] = args[i + 1]
                i += 2
            else:
                i += 1
        result = spawn_agent(target_path, **kwargs)
        return result["success"]
    else:
        logger.error(f"Unknown spawn command: {command}")
        return False


def spawn_agent(
    target_path,
    role="",
    traits: str | list[str] | tuple[str, ...] = "",
    purpose="",
    profile=None,
    template_dir=None,
    registry_path=None,
    citizen_class=None,
):
    """Create a new AIPass agent from template — the public door (aipass.spawn exports it).

    Arguments and the result dict are documented on handlers/mint_ops.py spawn_at.
    """
    return spawn_at(
        target_path,
        _load_meta_tabs,
        role=role,
        traits=traits,
        purpose=purpose,
        profile=profile,
        template_dir=template_dir,
        registry_path=registry_path,
        citizen_class=citizen_class,
    )


# Old private names re-exported from handlers/adoption_ops.py: tests and callers use them.
_birth_from_seed = birth_from_seed


_adopt_existing = adopt_existing
_error = error_result
