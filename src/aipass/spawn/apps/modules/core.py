# =================== AIPass ====================
# Name: core.py
# Description: Main orchestrator for agent spawning
# Version: 1.3.0
# Created: 2026-03-05
# Modified: 2026-09-28
# =============================================

"""
Spawn Module — Create new AIPass agents from templates.

Orchestrates the full agent creation workflow:
1. Validate target path
2. Copy template to target
3. Rename placeholder paths
4. Replace all {{PLACEHOLDER}} patterns
5. Regenerate .template_registry.json
6. Register in AIPASS_REGISTRY.json
7. Validate no unreplaced placeholders remain
"""

from pathlib import Path
from typing import List

from aipass.prax import logger

try:
    from aipass.cli.apps.modules.display import console
# An optional dependency's fallback has to be at least as wide as the failures its import can produce.
# A peer's handler package does real filesystem work at import time (its access guard), so a broken
# peer can raise OSError — FileNotFoundError from a dead cwd — not only ImportError.
# Catching ImportError alone means 'the peer is unavailable' is handled and 'the peer is broken'
# is fatal, which is backwards.
# Raised by @prax 2026-08-31 from their own watcher, measured against spawn the same hour.
except (ImportError, OSError) as e:
    logger.warning("Failed to import aipass.cli.apps.modules.display, falling back to rich.console: %s", e)
    from rich.console import Console

    console = Console()

# apps/spawn.py imports these two from here, so they are re-exported by name.
from aipass.spawn.apps.handlers.metadata import (
    get_branch_name as get_branch_name,
    normalize_branch_name as normalize_branch_name,
)
from aipass.spawn.apps.handlers.seed_ops import find_seed
from aipass.spawn.apps.handlers.adoption_ops import adopt_existing, birth_from_seed, error_result
from aipass.spawn.apps.handlers.class_registry import (
    get_template_dir as _get_template_dir,
    validate_class as validate_class,
    get_default_class as get_default_class,
    get_available_classes as get_available_classes,
    refuse_forbidden_class as refuse_forbidden_class,
    refuse_retired_or_forbidden as refuse_retired_or_forbidden,
    class_for_citizen_number as class_for_citizen_number,
)
from aipass.spawn.apps.handlers.json import json_handler
from aipass.spawn.apps.handlers.mint_ops import mint_citizen

# Default template location (relative to spawn package root). One template for
# every citizen — the class no longer picks a scaffold (DPLAN-0319 R3).
DEFAULT_TEMPLATE = Path(__file__).parents[2] / "templates" / "citizen"

_META_TAB_KEYS = {"TODOS_META", "KEY_LEARNINGS_META", "SESSIONS_META", "OBSERVATIONS_META"}


def _load_meta_tabs():
    """Load memory meta-tab values from @memory's renderer.

    Returns empty dict when @memory is unavailable (standalone project).
    """
    try:
        from aipass.memory.apps.handlers.tracking.tab_renderer import render_all_meta_tabs
    # Width, not politeness: see the module-level import above.
    except (ImportError, OSError) as e:
        logger.info("[spawn] @memory not available — meta-tab placeholders will be empty (%s)", e)
        return {}

    tabs = render_all_meta_tabs()
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
    console.print("    [dim]- mint_ops.py (mint_citizen — the mint body, step by step, called by spawn_agent)[/dim]")
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
    """
    Route spawn commands to implementation.

    Args:
        command: The command string (e.g. "create")
        args: List of arguments for the command

    Returns:
        True if command succeeded, False otherwise
    """
    # No args → introspection
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
                # A retired class name reaching here would otherwise be read as a
                # DIRECTORY path and fail with "Template not found: aipass_framework",
                # naming the wrong problem. Refuse by name instead (DPLAN-0319).
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
    """
    Create a new AIPass agent from template.

    Args:
        target_path: Where to create the agent (must not exist)
        role: Agent's role description
        traits: Agent's personality traits. A bare string becomes a one-element
            list; a list/tuple is stored as given. identity.traits is a LIST in
            the 2.0 schema (DPLAN-0319 R7), and the annotation says so — the
            list branch below has always been reachable from the Python API, it
            was just invisible to a type checker reading the ``""`` default.
        purpose: Agent's purpose (brief description)
        profile: AIPass profile override (default: auto-detect)
        template_dir: Custom template directory (default: the citizen template)
        registry_path: Path to AIPASS_REGISTRY.json (default: auto-discover)
        citizen_class: Explicit citizen class ("manager" or "specialist").
            Default None means DECIDE AT MINT from the citizen number — the
            project's first citizen is its manager, everyone after is a
            specialist (DPLAN-0319 R3). An explicit value still wins; a retired
            name ("aipass_framework", "project_agent", "builder") is refused by
            name, never quietly translated.

    Returns:
        Dict with creation results:
            - success: bool
            - branch_name: str (uppercase)
            - path: str
            - files_copied: int
            - registry_updated: bool
            - validation_issues: list
            - error: str (only if success=False)
    """
    # Forbidden and RETIRED values refuse before any filesystem work — "admin" is
    # a devpulse-only registry privilege, never a class and never a template
    # directory (DPLAN-0288); "aipass_framework"/"project_agent"/"builder" are
    # renamed classes that spawn refuses to translate silently (DPLAN-0319 R4).
    # Both doors are checked, including the API — @aipass's new_project still
    # passes citizen_class="project_agent" today, and a loud refusal is the
    # correct answer until its parallel fix lands.
    for candidate in (citizen_class, Path(template_dir).name if template_dir else ""):
        refusal = refuse_retired_or_forbidden(candidate)
        if refusal:
            json_handler.log_operation("mint_refused", data={"class": candidate, "reason": refusal})
            return _error(refusal)

    target = Path(target_path).resolve()
    if template_dir:
        template = Path(template_dir)
    else:
        # Both classes share one template dir, so this lookup is class-independent
        # — the real class decision happens at mint, once citizen_number is known.
        template = _get_template_dir(citizen_class or get_default_class())

    # Guard: block creating agent inside another agent's directory
    for parent in target.parents:
        if (parent / ".trinity" / "passport.json").is_file():
            return _error(
                f"BLOCKED: Cannot create agent inside existing agent '{parent.name}' "
                f"(found .trinity/passport.json at {parent})"
            )
        if parent == parent.parent:
            break

    # Validate
    if target.exists():
        # If target has a passport, adopt it (register without re-creating)
        passport_path = target / ".trinity" / "passport.json"
        if passport_path.exists():
            return _adopt_existing(target, purpose, profile, registry_path)

        # A directory with no live passport but WITH a tracked seed is the
        # fresh-clone shape (TDPLAN-0017): the branch's code came down with the
        # repo, its passport did not — .trinity/ is gitignored. That citizen is
        # not "already existing", it is waiting to be born, and its identity is
        # sitting right there in .aipass/passport.seed.json.
        #
        # This is also the ONLY door a seed can ever be found at. A seed lives
        # inside the branch directory it describes, so a mint into a target that
        # does not exist yet has no seed to prefer — the template path below is
        # correct there by construction, not by omission.
        seed_file = find_seed(target)
        if seed_file:
            return _birth_from_seed(target, seed_file, purpose, profile, registry_path)

        return _error(f"Target already exists: {target}")
    if not template.exists():
        return _error(f"Template not found: {template}")

    # The mint itself lives in handlers/mint_ops.py (DPLAN-0354 leg 4); the
    # meta-tab importer stays here and is handed in.
    return mint_citizen(
        target,
        template,
        _load_meta_tabs,
        role=role,
        traits=traits,
        purpose=purpose,
        profile=profile,
        registry_path=registry_path,
        citizen_class=citizen_class,
    )


# The target-exists lane (adopt / birth-from-seed / the shared error dict) lives
# in handlers/adoption_ops.py — split out when this module crossed the 600-line
# standard. Re-exported under the old private names so the module seam the tests
# and callers know stays put.
_birth_from_seed = birth_from_seed


_adopt_existing = adopt_existing
_error = error_result
