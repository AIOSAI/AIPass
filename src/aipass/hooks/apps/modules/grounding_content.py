# =================== AIPass ====================
# Name: grounding_content.py
# Version: 1.0.0
# Description: Shared content loaders for grounding prompt injections (DPLAN-0276)
# Branch: hooks
# Layer: apps/modules
# Created: 2026-08-01
# Modified: 2026-08-01
# =============================================

"""Loads raw grounding content — kernel, navmap, branch, identity — with no cadence gating.

Shared by apps/handlers/prompt/{tier0_kernel,navmap,branch_loader,identity}.py
(their own cadence-gated UserPromptSubmit handlers) and
apps/handlers/lifecycle/post_compact_regrounding.py (the PostToolUse backstop,
which fires unconditionally once per compact regardless of cadence).
"""

import json
import os
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.prax.apps.modules.logger import system_logger as logger  # noqa: F401

CONSOLE = err_console


def print_introspection() -> None:
    """Print module structure for drone routing."""
    CONSOLE.print("[bold cyan]grounding_content[/bold cyan] — Kernel/navmap/branch/identity loaders (DPLAN-0276)")


def _find_project_file(filename: str) -> Path | None:
    """Walk up from CWD to find the nearest .aipass/<filename>."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / ".aipass" / filename
        if candidate.is_file():
            return candidate
        if parent == parent.parent:
            break
    return None


def load_kernel(hook_data: dict) -> str:
    """Read tier0_kernel.md content."""
    aipass_home = os.environ.get("AIPASS_HOME", "")
    cwd = str(Path.cwd())

    if aipass_home and cwd.startswith(aipass_home):
        prompt_file = Path(aipass_home) / ".aipass" / "tier0_kernel.md"
    else:
        prompt_file = _find_project_file("tier0_kernel.md")

    if not prompt_file or not prompt_file.exists():
        return ""

    return prompt_file.read_text(encoding="utf-8")


def load_navmap(hook_data: dict) -> str:
    """Read tier1_navmap.md content."""
    aipass_home = os.environ.get("AIPASS_HOME", "")
    cwd = str(Path.cwd())

    if aipass_home and cwd.startswith(aipass_home):
        prompt_file = Path(aipass_home) / ".aipass" / "tier1_navmap.md"
    else:
        prompt_file = _find_project_file("tier1_navmap.md")

    if not prompt_file or not prompt_file.exists():
        return ""

    return prompt_file.read_text(encoding="utf-8")


def _find_branch_root(cwd: str) -> Path | None:
    """Walk up from CWD looking for .trinity/ or apps/ — stop at repo root."""
    search = Path(cwd).resolve()
    while search.parent != search:
        if (search / ".trinity").is_dir() or (search / "apps").is_dir():
            return search
        if (search / "pyproject.toml").exists() or (search / ".git").is_dir():
            return None
        search = search.parent
    return None


def load_branch(hook_data: dict) -> str:
    """Read branch prompt + private integration prompts."""
    cwd = hook_data.get("cwd", "") or str(Path.cwd())
    branch_root = _find_branch_root(cwd)
    if not branch_root:
        return ""

    parts: list[str] = []

    prompt_file = branch_root / ".aipass" / "aipass_local_prompt.md"
    if prompt_file.exists():
        content = prompt_file.read_text(encoding="utf-8").strip()
        branch_name = branch_root.name.upper()
        parts.append(f"# Branch Context: {branch_name}\n<!-- Source: {prompt_file} -->\n{content}")

    integrations_dir = branch_root / "apps" / "integrations"
    if integrations_dir.is_dir():
        for prompt in sorted(integrations_dir.glob("*/private_prompt.md")):
            parts.append(prompt.read_text(encoding="utf-8").strip())

    return "\n".join(parts)


def _find_passport(cwd: str) -> Path | None:
    """Walk up from CWD looking for .trinity/passport.json."""
    search = Path(cwd).resolve()
    home = Path.home()
    while search != home and search.parent != search:
        passport = search / ".trinity" / "passport.json"
        if passport.exists():
            return passport
        search = search.parent
    return None


def _format_identity(data: dict) -> str:
    lines: list[str] = []

    branch = data.get("branch_info", {})
    identity = data.get("identity", {})
    name = branch.get("branch_name") or identity.get("name", "UNKNOWN")
    lines.append(f"# {name} Identity")
    lines.append(f"Path: {branch.get('path', 'unknown')}")
    lines.append(f"Email: {branch.get('email', 'unknown')}")

    if identity.get("role"):
        lines.append(f"Role: {identity['role']}")

    traits = identity.get("traits") or data.get("traits")
    if traits:
        if isinstance(traits, list):
            lines.append("Traits: " + " | ".join(traits))
        else:
            lines.append(f"Traits: {traits}")

    if identity.get("purpose"):
        lines.append(f"Purpose: {identity['purpose']}")

    what_i_do = identity.get("what_i_do", [])
    if what_i_do:
        lines.append("Do: " + " | ".join(what_i_do[:4]))

    what_i_dont_do = identity.get("what_i_dont_do", [])
    if what_i_dont_do:
        lines.append("Don't: " + " | ".join(what_i_dont_do[:3]))

    principles = data.get("principles", [])
    if principles:
        lines.append("Principles: " + " * ".join(principles))

    return "\n".join(lines)


def load_identity(hook_data: dict) -> str:
    """Read + format passport.json identity."""
    cwd = hook_data.get("cwd", "") or str(Path.cwd())
    passport = _find_passport(cwd)
    if not passport:
        return ""

    data = json.loads(passport.read_text(encoding="utf-8"))
    output = _format_identity(data)
    return f"\n{output}" if output else ""
