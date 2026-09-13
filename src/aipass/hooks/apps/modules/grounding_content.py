# =================== AIPass ====================
# Name: grounding_content.py
# Version: 1.1.0
# Description: Shared content loaders for grounding prompt injections (DPLAN-0276)
# Branch: hooks
# Layer: apps/modules
# Created: 2026-08-01
# Modified: 2026-08-07
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

# The ACTIVE half of grounding. The passive half (kernel/navmap/branch/identity)
# re-injects itself on fresh context and after a compact; re-reading .trinity and
# refreshing the dashboard only ever happened because a greeting triggered the
# startup protocol. A mid-task continuation never gets a greeting, so without this
# the agent resumes with re-injected prompts but stale memory of its own state.
STARTUP_REGROUND_INSTRUCTION = (
    "ACTIVE RE-GROUNDING — do this BEFORE resuming the task, silently, no narration:\n"
    " 1. Read your memory: .trinity/passport.json, .trinity/local.json, .trinity/observations.json\n"
    " 2. Refresh and read your dashboard: drone @prax dashboard refresh @<self>, "
    "then read DASHBOARD.local.json\n"
    "    Outside an AIPass fleet project that refresh answers that your branch is not in the registry "
    "(the project has its own). Read DASHBOARD.local.json anyway and trust its own last_updated over its "
    "contents: a dashboard nothing refreshes reports zero new mail while the inbox has three.\n"
    "The context below is re-injected automatically; this half normally only runs off a greeting, and a "
    "mid-task continuation never gets one. If what you read contradicts what you believe about your own "
    "state, SAY SO in your reply before acting on it.\n"
)


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


#: Ceiling for the whole rendered identity block, in characters. Not a hard
#: platform limit — a budget. This block is injected on EVERY turn, so a
#: passport that grows without bound quietly taxes every prompt in the session.
IDENTITY_CHAR_BUDGET = 4000

#: What a facet may spend before it is cut at a sentence boundary. Sized so the
#: richest passport in the fleet (Vera's six facets) fits under the budget with
#: the rest of the block intact.
FACET_CHAR_BUDGET = 320


def _truncate_at_sentence(text: str, limit: int) -> str:
    """Cut *text* to <= *limit* chars, preferring the last sentence boundary.

    Dropping a whole facet would lose a claim the passport makes about the
    citizen; cutting one mid-word makes it read as corrupted. Cutting at the
    last full sentence keeps every facet present and every kept word true.

    Args:
        text: The facet body.
        limit: Maximum characters to keep.

    Returns:
        The text unchanged when it already fits, else the longest prefix ending
        at a sentence boundary, else a hard cut with an ellipsis.
    """
    if len(text) <= limit:
        return text

    window = text[:limit]
    cut = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    if cut > 0:
        return window[: cut + 1]
    # No sentence boundary in the window — hard cut. The ellipsis has to come
    # out of the budget, not be added on top of it, or a facet with no full stop
    # in range renders one char OVER the limit it was cut to.
    return text[: limit - 1].rstrip() + "…"


def _personality_lines(personality: object) -> list[str]:
    """One 'Facet: text' line per personality facet, in the passport's order.

    Only a dict renders. A string, a list or None yields nothing, so a passport
    that does not carry the key — every AIPass passport today — renders exactly
    as it did before this function existed.

    Args:
        personality: The raw identity.personality value, whatever shape it has.

    Returns:
        Rendered lines, empty when there is nothing to render.
    """
    if not isinstance(personality, dict) or not personality:
        return []

    lines: list[str] = []
    for facet, text in personality.items():
        if not text:
            continue
        label = str(facet).replace("_", " ").capitalize()
        lines.append(f"{label}: {_truncate_at_sentence(str(text), FACET_CHAR_BUDGET)}")
    return lines


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

    # Personality reads AFTER purpose and BEFORE the Do/Don't pair, so the
    # facets sit with who-I-am rather than with what-I-handle. Insertion order
    # is the passport author's order and is kept: the facets are written as a
    # progression (core, then voice, then how I decide, then how I hold up),
    # and sorting them would silently rewrite that argument.
    lines.extend(_personality_lines(identity.get("personality")))

    what_i_do = identity.get("what_i_do", [])
    if what_i_do:
        lines.append("Do: " + " | ".join(what_i_do[:4]))

    what_i_dont_do = identity.get("what_i_dont_do", [])
    if what_i_dont_do:
        lines.append("Don't: " + " | ".join(what_i_dont_do[:3]))

    # Anti-traits follow the Don't line because they are the same kind of
    # statement one level up: Don't names tasks that belong to someone else,
    # Never names ways of BEING that the citizen rejects. Old Vera's own
    # recorded insight was that the anti-traits, not the traits, were what
    # kept her out of generic-assistant drift — so they are worth the line.
    anti_traits = identity.get("anti_traits")
    if isinstance(anti_traits, list) and anti_traits:
        lines.append("Never: " + " | ".join(str(a) for a in anti_traits))

    # Passport 1.0 keeps principles at the top level, 2.0 moves them inside
    # identity (DPLAN-0319). Read the new home first, fall back to the old one —
    # same dual-location shape as the traits read above. Without the fallback the
    # line vanishes silently on whichever layout is not being read.
    principles = identity.get("principles") or data.get("principles") or []
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
