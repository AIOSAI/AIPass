# =================== AIPass ====================
# Name: grounding_content.py
# Version: 1.3.1
# Description: Shared content loaders for grounding prompt injections (DPLAN-0276), each rendered under its cap
# Branch: hooks
# Layer: apps/modules
# Created: 2026-08-01
# Modified: 2026-09-16
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
from aipass.prax.apps.modules.logger import system_logger as logger

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


#: Ceiling for the rendered branch block — the branch prompt plus its header.
#: The owner ruled the layer contract on 2026-09-15 (DPLAN-0347): 9,000 chars, one
#: under the 10,000 the harness persists behind a 2,000-char preview. A prompt
#: that crosses that line is not read by the model at all; truncation here is
#: what keeps the first 9,000 chars of it live.
BRANCH_CHAR_BUDGET = 9000

#: Each apps/integrations/*/private_prompt.md, appended after the branch prompt.
#: Zero live fleet-wide today, uncapped and ungated until now: the first one
#: written is the one that would have pushed the block over the persist line.
INTEGRATION_CHAR_BUDGET = 2000


def print_introspection() -> None:
    """Print module structure for drone routing."""
    CONSOLE.print("[bold cyan]grounding_content[/bold cyan] — Kernel/navmap/branch/identity loaders (DPLAN-0276)")


def _truncate_block(text: str, limit: int, source: Path | str) -> str:
    """Cut a rendered block to *limit* chars, ending with a marker that names *source*.

    The marker is the point. A block that simply stops reads as a corrupted
    prompt and the agent has no way to find the rest; a marker naming the file
    turns a cut into a pointer — and gives whoever wrote past the cap the one
    line they need to see in the transcript.

    The cut lands on the last line boundary in the window when there is one past
    the halfway mark, so a truncated block never ends mid-sentence.

    Args:
        text: The rendered block.
        limit: Maximum characters for the result, marker included.
        source: The file the block was rendered from, named in the marker.

    Returns:
        The text unchanged when it fits, else the kept head plus the marker.
    """
    if len(text) <= limit:
        return text

    marker = f"\n[… cut at {limit} chars by @hooks — the rest of this block is in {source}]"
    keep = limit - len(marker)
    if keep <= 0:
        # A budget smaller than its own marker cannot say where the rest went;
        # a bare cut is the honest answer rather than a marker with no content.
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

    Compared by samefile, not by spelling: a Windows TEMP can reach the same
    directory through an 8.3 name (C:\\Users\\RUNNER~1) that no string compare matches.
    """
    try:
        return candidate.samefile(Path.home() / ".aipass")
    except OSError:
        return False


def _find_project_dir() -> Path | None:
    """Walk up from CWD to the nearest .aipass/ directory — the mark of a stamped tree.

    The per-user ~/.aipass is skipped. Any tree under home walks up through it,
    so counting it made every unstamped tree under home "promise" a kernel. The
    Windows CI runner measured that: its temp dir is under home, so tests that
    expected silence got the degraded banner (2026-09-16). Linux never saw it,
    because /tmp is not under home.
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
    """The .aipass/<filename> this session reads: AIPASS_HOME's when inside it, else the nearest.

    Args:
        filename: The tier file's name, e.g. "tier0_kernel.md".

    Returns:
        The path when it exists, else None.
    """
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
    home = Path.home()
    while search != home and search.parent != search:
        passport = search / ".trinity" / "passport.json"
        if passport.exists():
            return passport
        search = search.parent
    return None


#: Ceiling for the whole rendered identity block, in characters. Not a hard
#: platform limit — a budget. This block is injected on every cadence beat, so a
#: passport that grows without bound quietly taxes the whole session. Declared
#: 2026-09-08 and read by nothing until DPLAN-0347: a budget no code enforces is
#: documentation, and the largest passport in the fleet had already reached 5,461.
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
    """Why a tier file is missing, or None when nothing was expected here.

    An unstamped tree has no .aipass/ at all and was never promised a kernel;
    a stamped one that cannot produce the file has lost something it had.
    """
    if _find_project_dir() is None:
        return None
    return f"{label}: this tree is AIPass-stamped but .aipass/{filename} is missing or unreadable"


def _branch_failure(hook_data: dict) -> str | None:
    """Why the branch prompt is missing, or None when this seat is not a branch."""
    root = _find_branch_root(hook_data.get("cwd", "") or str(Path.cwd()))
    if root is None:
        return None
    return f"branch: {root.name} is a branch but .aipass/aipass_local_prompt.md is missing or unreadable"


def _branch_has_trinity(cwd: str) -> Path | None:
    """The nearest .trinity/ above *cwd*, stopping at home."""
    search = Path(cwd).resolve()
    home = Path.home()
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

    Two different empties, kept apart on purpose (DPLAN-0347, hooks row 1). A
    seat that is not a branch has no branch prompt to lose: that is the shape of
    the tree, not a defect, and measured on 2026-09-16 it is the common case —
    four of four stamped projects on this machine carry a kernel and a navmap
    and no .trinity/ or branch prompt at all. Warning on those every beat is the
    false-alarm class this branch is curing elsewhere, so they are silent.

    A seat that IS a branch and still gets no branch prompt has lost something it
    was promised, and doctrine is that it fails loud rather than quietly running
    on less. A loader that RAISES is always a failure — a reader that cannot
    parse its own input never gets to call the result "not applicable".

    Args:
        hook_data: The hook payload; only "cwd" is read.

    Returns:
        (sections, failures) — sections as (label, content) in SECTION_ORDER,
        failures as one already-worded line each, safe to inject verbatim.
    """
    loaders = {"branch": load_branch, "identity": load_identity, "kernel": load_kernel, "navmap": load_navmap}
    sections: list[tuple[str, str]] = []
    failures: list[str] = []
    for label in SECTION_ORDER:
        try:
            content = loaders[label](hook_data)
        except Exception as exc:  # noqa: BLE001 - any loader failure is a failure, whatever its type
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
    """The loud line for a session flying on partial grounding — what is missing and why.

    Substitutes nothing. A fallback that hands back a different answer than the
    one asked for is banned here, so this names the hole instead of filling it.

    Args:
        failures: Already-worded lines from grounding_report.
        loaded: Labels of the sections that did load.

    Returns:
        The banner, or "" when nothing was lost.
    """
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
