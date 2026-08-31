# =================== AIPass ====================
# Name: adapters.py
# Description: audit-tests adapter discovery and contract enforcement
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
Adapter discovery and contract enforcement — the seam that keeps the core
language-neutral.

THE SHAPE GATE (design section 2.1). An execution pack must be invisible to
the audit's file-walk engine. `discover_checkers()` keeps a module only if it
defines `check_module` or `check_branch`; an adapter defines `run_gated` and
neither, so it is invisible with ZERO change to the audit engine. That matters
more than it looks: `.github/scripts/seedgo_audit.py` calls `audit_branch()`
directly and never consults a pack manifest, so a manifest flag would not
protect CI. The shape gate is the only gate CI has.

THE CONTRACT. An adapter exposes eight functions plus two constants. The core
refuses an adapter it does not speak rather than calling half of it — a
partially-honoured contract produces a measurement nobody can interpret, which
is the confidently-wrong-number shape this whole lane refuses to publish.

REGISTRATION IS CONDITIONAL ON ISOLATION. The payload runs inside a copy of a
foreign tree and must import nothing from aipass (Law M10). That is not a
regrettable exception — it is the property that makes the instrument
trustworthy, because an instrument that imports the tree it measures has that
tree's defects available to it. @devpulse granted the payload bypass in
boardroom post 6 CONDITIONAL on this check, so the pack fails registration the
moment any payload file imports aipass. The grant cannot widen silently and it
outlives everyone who agreed to it.
"""

import ast
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Dict, List, Optional, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.module_root import module_file

#: The adapter API version this core speaks.
SUPPORTED_ADAPTER_API = 1

#: The eight functions an adapter must expose (design section 3.1).
REQUIRED_FUNCTIONS: tuple = (
    "detect",
    "build_env",
    "assert_env_is_live",
    "run_gated",
    "fire_canary",
    "nominate",
    "teardown",
    "declared_groups",
)

#: Constants an adapter must expose.
REQUIRED_CONSTANTS: tuple = ("ADAPTER_API", "ECOSYSTEM")

#: Functions whose presence would make a module visible to the AUDIT engine.
#: An adapter defining either of these has broken the shape gate.
FORBIDDEN_FUNCTIONS: tuple = ("check_module", "check_branch")

#: Directory name holding the injected, stdlib-only payload.
PAYLOAD_DIR = "payload"

#: Where adapter packs live.
HANDLERS_ROOT = module_file(__file__).parents[1]

#: Pack directory suffix. Kept per Patrick's ruling 2026-08-29 19:23 —
#: "don't change the command path, it already works".
PACK_SUFFIX = "_standards"


class AdapterContractError(Exception):
    """An adapter that may not be registered, naming what it broke."""


# =============================================================================
# THE ISOLATION PROOF - Law M10, and the condition on the Q-B grant
# =============================================================================


def payload_imports_aipass(payload_dir: Path) -> List[str]:
    """Every payload file that imports aipass. Empty list means isolated.

    AST-based rather than a text grep, so a string mentioning `aipass` in a
    docstring is not a violation and `from aipass.prax import logger` cannot
    hide behind formatting. Static analysis nominating on a token is exactly
    the error class this campaign has already made twice.

    A file that will not parse is reported as a violation rather than skipped:
    an unparseable payload file is one the proof could not clear, and "could
    not check" must never read as "checked and clean".
    """
    offenders: List[str] = []
    if not payload_dir.is_dir():
        return offenders

    for path in sorted(payload_dir.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, OSError) as exc:
            logger.warning(f"[AUDIT-TESTS] payload file {path.name} will not parse, isolation unproven: {exc}")
            offenders.append(f"{path.name}: unparseable, so isolation is unproven ({exc})")
            continue

        offenders.extend(_aipass_imports_in(tree, path.name))

    return offenders


def _aipass_imports_in(tree: ast.AST, filename: str) -> List[str]:
    """Every aipass import in one parsed payload file."""
    found: List[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] == "aipass" for alias in node.names):
                found.append(f"{filename}:{node.lineno}: imports aipass")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "aipass":
                found.append(f"{filename}:{node.lineno}: from aipass import ...")

    return found


def execution_isolation(pack_dir: Path) -> dict:
    """The machine check the payload bypass is conditional on.

    Returns `{"isolated": bool, "checked": int, "offenders": [str]}`. The core
    refuses to register a pack whose payload is not isolated — the boundary is
    proved every run, never trusted once.
    """
    payload_dir = pack_dir / PAYLOAD_DIR
    offenders = payload_imports_aipass(payload_dir)
    checked = len(list(payload_dir.rglob("*.py"))) if payload_dir.is_dir() else 0

    return {"isolated": not offenders, "checked": checked, "offenders": offenders}


# =============================================================================
# CONTRACT ENFORCEMENT
# =============================================================================


def contract_problems(module: ModuleType) -> List[str]:
    """Every way this module fails the adapter contract, reported at once."""
    problems: List[str] = []

    for constant in REQUIRED_CONSTANTS:
        if not hasattr(module, constant):
            problems.append(f"missing constant {constant}")

    api = getattr(module, "ADAPTER_API", None)
    if api is not None and api != SUPPORTED_ADAPTER_API:
        problems.append(f"ADAPTER_API {api} - this core speaks {SUPPORTED_ADAPTER_API}")

    for name in REQUIRED_FUNCTIONS:
        attribute = getattr(module, name, None)
        if attribute is None:
            problems.append(f"missing function {name}()")
        elif not callable(attribute):
            problems.append(f"{name} is not callable")

    for name in FORBIDDEN_FUNCTIONS:
        if hasattr(module, name):
            problems.append(
                f"defines {name}() - that makes the pack visible to the audit's "
                f"file-walk engine, which is the shape gate this lane depends on"
            )

    return problems


# =============================================================================
# DISCOVERY
# =============================================================================


def _load_adapter_module(adapter_file: Path) -> Optional[ModuleType]:
    """Import an adapter.py by path. Returns None if it will not load."""
    spec = importlib.util.spec_from_file_location(f"audit_tests_adapter_{adapter_file.parent.name}", adapter_file)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def discover_adapters(handlers_root: Optional[Path] = None) -> Tuple[Dict[str, ModuleType], List[str]]:
    """Find and validate every execution adapter pack.

    Returns `(adapters_by_ecosystem, rejections)`. A rejected pack is NEVER
    silently dropped — every rejection carries the reason, because a pack that
    vanished without explanation is how a fleet quietly stops being measured.
    """
    root = handlers_root or HANDLERS_ROOT
    adapters: Dict[str, ModuleType] = {}
    rejections: List[str] = []

    for pack_dir in sorted(p for p in root.glob(f"tests_*{PACK_SUFFIX}") if p.is_dir()):
        adapter_file = pack_dir / "adapter.py"
        if not adapter_file.exists():
            rejections.append(f"{pack_dir.name}: no adapter.py")
            continue

        try:
            module = _load_adapter_module(adapter_file)
        except Exception as exc:
            logger.warning(f"[AUDIT-TESTS] adapter pack {pack_dir.name} failed to import: {exc}")
            rejections.append(f"{pack_dir.name}: adapter.py failed to import ({exc})")
            continue

        if module is None:
            rejections.append(f"{pack_dir.name}: adapter.py could not be loaded")
            continue

        problems = contract_problems(module)
        if problems:
            rejections.append(f"{pack_dir.name}: {'; '.join(problems)}")
            continue

        isolation = execution_isolation(pack_dir)
        if not isolation["isolated"]:
            rejections.append(
                f"{pack_dir.name}: payload is not isolated (Law M10) - {'; '.join(isolation['offenders'])}"
            )
            json_handler.log_operation(
                "adapter_registration_refused",
                {"pack": pack_dir.name, "reason": "payload_imports_aipass", "offenders": isolation["offenders"]},
            )
            continue

        ecosystem = getattr(module, "ECOSYSTEM")
        if ecosystem in adapters:
            rejections.append(f"{pack_dir.name}: ecosystem '{ecosystem}' already claimed")
            continue

        adapters[ecosystem] = module

    return adapters, rejections


def claim_target(adapters: Dict[str, ModuleType], target_path: Path) -> Tuple[Optional[ModuleType], Dict[str, dict]]:
    """Ask every adapter whether it claims this target.

    Returns `(winner_or_None, detections_by_ecosystem)`. Every detection is
    returned even when one adapter wins, so a refusal for "no adapter claims
    this target" can print what each adapter actually said rather than leaving
    the operator guessing.
    """
    detections: Dict[str, dict] = {}
    winner: Optional[ModuleType] = None

    for ecosystem, module in sorted(adapters.items()):
        try:
            detection = module.detect(target_path)
        except Exception as exc:
            logger.warning(f"[AUDIT-TESTS] adapter '{ecosystem}' detect() raised on {target_path}: {exc}")
            detection = {"applicable": False, "reason": f"detect() raised: {exc}", "unit_count": 0}
        detections[ecosystem] = detection

        if detection.get("applicable") and winner is None:
            winner = module

    return winner, detections
