# =================== AIPass ====================
# Name: grounding_content.py
# Version: 1.4.1
# Description: Shared content loaders for grounding prompt injections (DPLAN-0276), each rendered under its cap
# Branch: hooks
# Layer: apps/modules
# Created: 2026-08-01
# Modified: 2026-10-17
# =============================================

"""Loads raw grounding content — kernel, navmap, branch, identity — with no cadence gating."""

import json
import os
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console

# A mid-task continuation never gets the greeting that runs the startup protocol;
# without this the agent resumes with stale memory of its own state.
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


#: Under the 10,000 chars the harness persists behind a preview, past which the model never reads it.
BRANCH_CHAR_BUDGET = 9000

INTEGRATION_CHAR_BUDGET = 2000


def print_introspection() -> None:
    """Print module structure for drone routing."""
    CONSOLE.print("[bold cyan]grounding_content[/bold cyan] — Kernel/navmap/branch/identity loaders (DPLAN-0276)")


def _truncate_block(text: str, limit: int, source: Path | str) -> str:
    """Cut a rendered block to *limit* chars, ending with a marker that names *source*.

    A block that simply stops reads as corrupted; the marker turns the cut into a pointer.
    """
    if len(text) <= limit:
        return text

    marker = f"\n[… cut at {limit} chars by @hooks — the rest of this block is in {source}]"
    keep = limit - len(marker)
    if keep <= 0:
        return text[:limit]

    window = text[:keep]
    boundary = window.rfind("\n")
    if boundary > keep // 2:
        window = window[:boundary]
    logger.warning(
        "[HOOKS] grounding_content: %s renders %d chars, over the %d budget — cut, marker names the file",
        source,
        len(text),
        limit,
    )
    return window.rstrip() + marker


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


def _is_user_state_dir(candidate: Path) -> bool:
    """True when *candidate* is the per-user ~/.aipass (trust registry, commons.db), not a stamped tree.

    samefile, not spelling: Windows can reach the same directory through an 8.3 name.
    """
    try:
        return candidate.samefile(Path.home() / ".aipass")
    except OSError:
        return False


def _find_project_dir() -> Path | None:
    """Walk up from CWD to the nearest .aipass/ directory — the mark of a stamped tree.

    The per-user ~/.aipass is skipped: every tree under home walks through it and would "promise" a kernel.
    """
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / ".aipass"
        if candidate.is_dir() and not _is_user_state_dir(candidate):
            return candidate
        if parent == parent.parent:
            break
    return None


def _tier_file(filename: str) -> Path | None:
    """The .aipass/<filename> this session reads: AIPASS_HOME's when inside it, else the nearest."""
    aipass_home = os.environ.get("AIPASS_HOME", "")
    cwd = str(Path.cwd())

    if aipass_home and cwd.startswith(aipass_home):
        prompt_file = Path(aipass_home) / ".aipass" / filename
    else:
        prompt_file = _find_project_file(filename)

    if not prompt_file or not prompt_file.exists():
        return None
    return prompt_file


def load_kernel(hook_data: dict) -> str:
    """Read tier0_kernel.md content."""
    prompt_file = _tier_file("tier0_kernel.md")
    return prompt_file.read_text(encoding="utf-8") if prompt_file else ""


def load_navmap(hook_data: dict) -> str:
    """Read tier1_navmap.md content."""
    prompt_file = _tier_file("tier1_navmap.md")
    return prompt_file.read_text(encoding="utf-8") if prompt_file else ""


def find_branch_root(cwd: str) -> Path | None:
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
    branch_root = find_branch_root(cwd)
    if not branch_root:
        return ""

    parts: list[str] = []

    prompt_file = branch_root / ".aipass" / "aipass_local_prompt.md"
    if prompt_file.exists():
        content = prompt_file.read_text(encoding="utf-8").strip()
        branch_name = branch_root.name.upper()
        block = f"# Branch Context: {branch_name}\n<!-- Source: {prompt_file} -->\n{content}"
        parts.append(_truncate_block(block, BRANCH_CHAR_BUDGET, prompt_file))

    integrations_dir = branch_root / "apps" / "integrations"
    if integrations_dir.is_dir():
        for prompt in sorted(integrations_dir.glob("*/private_prompt.md")):
            body = prompt.read_text(encoding="utf-8").strip()
            parts.append(_truncate_block(body, INTEGRATION_CHAR_BUDGET, prompt))

    return "\n".join(parts)


def _find_passport(cwd: str) -> Path | None:
    """Walk up from CWD looking for .trinity/passport.json."""
    search = Path(cwd).resolve()
    home = Path.home().resolve()  # both sides resolved, or a symlinked home never stops the walk
    while search != home and search.parent != search:
        passport = search / ".trinity" / "passport.json"
        if passport.exists():
            return passport
        search = search.parent
    return None


#: Injected every cadence beat: a passport that grows without bound taxes the whole session.
IDENTITY_CHAR_BUDGET = 4000

FACET_CHAR_BUDGET = 320


def _truncate_at_sentence(text: str, limit: int) -> str:
    """Cut *text* to <= *limit* chars, preferring the last sentence boundary."""
    if len(text) <= limit:
        return text

    window = text[:limit]
    cut = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    if cut > 0:
        return window[: cut + 1]
    # The ellipsis comes out of the budget, or the result renders one char over *limit*.
    return text[: limit - 1].rstrip() + "…"


def _personality_lines(personality: object) -> list[str]:
    """One 'Facet: text' line per personality facet, in the passport's order. Only a dict renders."""
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

    # Facets keep the author's order: they are written as a progression, and sorting rewrites it.
    lines.extend(_personality_lines(identity.get("personality")))

    what_i_do = identity.get("what_i_do", [])
    if what_i_do:
        lines.append("Do: " + " | ".join(what_i_do[:4]))

    what_i_dont_do = identity.get("what_i_dont_do", [])
    if what_i_dont_do:
        lines.append("Don't: " + " | ".join(what_i_dont_do[:3]))

    anti_traits = identity.get("anti_traits")
    if isinstance(anti_traits, list) and anti_traits:
        lines.append("Never: " + " | ".join(str(a) for a in anti_traits))

    # Passport 2.0 keeps principles inside identity, 1.0 at the top level: read both.
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
    if not output:
        return ""
    return "\n" + _truncate_block(output, IDENTITY_CHAR_BUDGET, passport)


#: The grounding sections, in the order a session must not lose them. Branch
#: first: it carries the seat's own rules and no other injection repeats it.
SECTION_ORDER = ("branch", "identity", "kernel", "navmap")

DEGRADED_HEADING = "[GROUNDING DEGRADED — this session is running on PARTIAL grounding]"


def _unhomed(text: str) -> str:
    """The same text with the home directory spelled ~, for anything the agent will read."""
    return text.replace(str(Path.home()), "~")


def _tier_failure(label: str, filename: str) -> str | None:
    """Why a tier file is missing, or None when nothing was expected here."""
    if _find_project_dir() is None:
        return None
    return f"{label}: this tree is AIPass-stamped but .aipass/{filename} is missing or unreadable"


def _branch_failure(hook_data: dict) -> str | None:
    """Why the branch prompt is missing, or None when this seat is not a branch."""
    root = find_branch_root(hook_data.get("cwd", "") or str(Path.cwd()))
    if root is None:
        return None
    return f"branch: {root.name} is a branch but .aipass/aipass_local_prompt.md is missing or unreadable"


def _branch_has_trinity(cwd: str) -> Path | None:
    """The nearest .trinity/ above *cwd*, stopping at home."""
    search = Path(cwd).resolve()
    home = Path.home().resolve()  # both sides resolved, or a symlinked home never stops the walk
    while search != home and search.parent != search:
        candidate = search / ".trinity"
        if candidate.is_dir():
            return candidate
        search = search.parent
    return None


def _identity_failure(hook_data: dict) -> str | None:
    """Why the identity block is missing, or None when this seat has no .trinity/ at all."""
    cwd = hook_data.get("cwd", "") or str(Path.cwd())
    if _branch_has_trinity(cwd) is None:
        return None
    if _find_passport(cwd) is None:
        return "identity: a .trinity/ is present but holds no passport.json"
    return "identity: passport.json was read but rendered no identity block"


_FAILURE_OF = {
    "branch": _branch_failure,
    "identity": _identity_failure,
    "kernel": lambda hook_data: _tier_failure("kernel", "tier0_kernel.md"),
    "navmap": lambda hook_data: _tier_failure("navmap", "tier1_navmap.md"),
}


def grounding_report(hook_data: dict) -> tuple[list[tuple[str, str]], list[str]]:
    """Every grounding section that loaded, and one line per section that was expected and did not.

    A section the tree never had is silent; one it was promised fails loud; a loader that raises always fails.
    """
    loaders = {"branch": load_branch, "identity": load_identity, "kernel": load_kernel, "navmap": load_navmap}
    sections: list[tuple[str, str]] = []
    failures: list[str] = []
    for label in SECTION_ORDER:
        try:
            content = loaders[label](hook_data)
        except Exception as exc:  # any loader failure is a failure, whatever its type
            failures.append(_unhomed(f"{label}: loading it raised {type(exc).__name__}: {exc}"))
            continue
        if content and content.strip():
            sections.append((label, content.strip("\n")))
            continue
        reason = _FAILURE_OF[label](hook_data)
        if reason:
            failures.append(_unhomed(reason))
    return sections, failures


def degraded_banner(failures: list[str], loaded: list[str]) -> str:
    """The loud line for a session flying on partial grounding — what is missing and why. Substitutes nothing."""
    if not failures:
        return ""
    return "\n".join(
        [
            DEGRADED_HEADING,
            f"Carried: {', '.join(loaded) if loaded else 'nothing'}. Missing, and why:",
            *(f" - {failure}" for failure in failures),
            "Nothing was substituted for the missing part. Treat any rule that lives there as UNREAD: "
            "fetch it (`drone @<self> --help`, the branch README, .trinity/) before acting on memory of "
            "it, and say in your reply that you ran degraded.",
        ]
    )
