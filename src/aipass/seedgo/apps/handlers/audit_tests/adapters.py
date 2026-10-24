# =================== AIPass ====================
# Name: adapters.py
# Description: audit-tests adapter discovery and contract enforcement
# Version: 1.0.3
# Created: 2026-08-29
# Modified: 2026-10-24
# =============================================

"""
Adapter discovery and contract enforcement — the seam that keeps the core
language-neutral.

Shape gate: an adapter defines neither `check_module` nor `check_branch`, so the
audit engine (and CI, which calls `audit_branch()` directly) never sees it.
A pack registers only while its payload imports nothing from aipass (Law M10).
"""

import ast
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Dict, List, Optional, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.module_root import module_file

SUPPORTED_ADAPTER_API = 1

REQUIRED_FUNCTIONS: tuple = (
    "detect",
    "build_env",
    "assert_env_is_live",
    "run_gated",
    "nominate",
    "declared_groups",
)

REQUIRED_CONSTANTS: tuple = ("ADAPTER_API", "ECOSYSTEM")

#: Either of these makes a module visible to the audit engine: the shape gate.
FORBIDDEN_FUNCTIONS: tuple = ("check_module", "check_branch")

PAYLOAD_DIR = "payload"

HANDLERS_ROOT = module_file(__file__).parents[1]

#: Pack directory suffix; the command path depends on it.
PACK_SUFFIX = "_standards"


class AdapterContractError(Exception):
    """An adapter that may not be registered, naming what it broke."""


def payload_imports_aipass(payload_dir: Path) -> List[str]:
    """Every payload file that imports aipass. Empty list means isolated.

    An unparseable file counts as an offender: "could not check" is not "clean".
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
        elif isinstance(node, ast.Call) and _dynamic_import_name(node).split(".")[0] == "aipass":
            found.append(f"{filename}:{node.lineno}: imports aipass dynamically")

    return found


def _dynamic_import_name(node: ast.AST) -> str:
    """The literal module name of an `importlib.import_module(...)` / `__import__(...)` call, else ""."""
    if not isinstance(node, ast.Call) or not node.args:
        return ""
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
    first = node.args[0]
    if name in ("import_module", "__import__") and isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return ""


def execution_isolation(pack_dir: Path) -> dict:
    """The machine check the payload bypass is conditional on."""
    payload_dir = pack_dir / PAYLOAD_DIR
    offenders = payload_imports_aipass(payload_dir)
    checked = len(list(payload_dir.rglob("*.py"))) if payload_dir.is_dir() else 0

    return {"isolated": not offenders, "checked": checked, "offenders": offenders}


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

    Every rejected pack carries its reason; a silently dropped pack goes unmeasured.
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

    All detections return, even with a winner, so a refusal can show each answer.
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
