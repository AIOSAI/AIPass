# =================== AIPass ====================
# Name: help_chat.py
# Description: README-backed chatbot Q&A — section-aware answers (DPLAN-0282 P3)
# Version: 1.1.0
# Created: 2026-04-16
# Modified: 2026-08-07
# =============================================

"""
aipass help — chatbot-style Q&A over branch READMEs

User types `aipass help <question>`. We:
    1. Extract keywords from the question (stopword filter, no ML)
    2. Match keywords against branch names / README paths
    3. Live-read {branch}/README.md for matched branches
    4. Return the best-matching README sections — whole, heading-bounded,
       rendered as Markdown with a line-range citation
    5. Always offer depth: view full README or dispatch to @branch

Principle: nothing cached except branch-name → README-path map.
Every answer re-reads the real file. Stale info is the enemy.

No LLM — scripted keyword lookups only (token-cheap by default).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.readme_map import get_readme_path, list_branches, read_readme_lines
from aipass.cli.apps.modules import console, error, header
from aipass.prax import logger

# =============================================================================
# MODULE METADATA
# =============================================================================

COMMAND = "help"
_MODULE_NAME = "help_chat"
_VERSION = "1.1.0"
_DESCRIPTION = "README-backed chatbot Q&A over branch documentation"


# =============================================================================
# INTROSPECTION
# =============================================================================


def print_introspection() -> None:
    """Print module info for diagnostics."""
    console.print(f"[bold cyan]Module:[/bold cyan] {_MODULE_NAME}")
    console.print(f"[bold cyan]Command:[/bold cyan] {COMMAND}")
    console.print(f"[bold cyan]Description:[/bold cyan] {_DESCRIPTION}")
    console.print(f"[bold cyan]Version:[/bold cyan] {_VERSION}")


def print_help() -> None:
    """Print usage help for the help command."""
    console.print()
    console.print("[bold cyan]aipass help[/bold cyan] — README-backed Q&A")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [green]aipass help <question>[/green]  [dim]# Search branch READMEs[/dim]")
    console.print()
    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [green]aipass help what does drone do[/green]")
    console.print("  [green]aipass help how does ai_mail work[/green]")
    console.print()


# =============================================================================
# KEYWORD EXTRACTION
# =============================================================================

_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "what",
        "how",
        "why",
        "when",
        "where",
        "who",
        "does",
        "do",
        "can",
        "i",
        "to",
        "in",
        "of",
        "for",
        "and",
        "or",
        "not",
        "it",
        "my",
        "me",
        "you",
    }
)


def _extract_keywords(question: str) -> list[str]:
    """Extract meaningful keywords from question string (stopword filter).

    Strips punctuation, lowercases, filters stopwords and single-char words.
    No ML — pure string operations.
    """
    words = question.lower().split()
    keywords: list[str] = []
    for word in words:
        stripped = word.strip("?.,!")
        if stripped and stripped not in _STOPWORDS and len(stripped) > 1:
            keywords.append(stripped)
    return keywords


# =============================================================================
# BRANCH MATCHING
# =============================================================================


def _match_branches(keywords: list[str]) -> list[str]:
    """Return branches whose README likely covers the question.

    Strategy:
      1. If a keyword exactly matches a branch name → include that branch first
      2. Score remaining available branches by keyword overlap with branch name
      3. Fallback: return all branches if no match found (broad search)
    """
    available = list_branches()
    if not available:
        return []

    direct: list[str] = []
    for kw in keywords:
        if kw in available and kw not in direct:
            direct.append(kw)

    # Broad fallback — no direct matches
    if not direct:
        return available

    # Also include branches whose names contain keyword fragments
    # (e.g. keyword "mail" → matches "ai_mail")
    extended: list[str] = list(direct)
    for branch in available:
        if branch in extended:
            continue
        for kw in keywords:
            if kw in branch or branch in kw:
                extended.append(branch)
                break

    return extended if extended else available


# =============================================================================
# README SEARCH (LIVE-READ, SECTION-AWARE)
# =============================================================================

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")

_MAX_SECTIONS = 2  # best sections per branch — depth lives in `aipass read`
_MAX_SECTION_LINES = 25  # body cap per section, truncation hint points at read


def _split_sections(lines: Sequence[str]) -> list[dict]:
    """Split README lines into heading-bounded sections.

    A section is a #/##/### heading plus everything until the next heading;
    content before the first heading becomes an untitled intro section.
    Headings inside ``` fences are body text, not section breaks.
    Line numbers are 1-indexed; start = heading line, end = last body line.
    """
    sections: list[dict] = []
    current: dict = {"title": "", "start": 1, "end": 0, "lines": []}
    in_fence = False

    def _keep(sec: dict) -> bool:
        return bool(sec["title"]) or any(ln.strip() for ln in sec["lines"])

    for idx, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        match = None if in_fence else _HEADING_RE.match(line)
        if match:
            current["end"] = idx - 1
            if _keep(current):
                sections.append(current)
            current = {"title": match.group(2).strip(), "start": idx, "end": idx, "lines": []}
        else:
            current["lines"].append(line)

    current["end"] = len(lines)
    if _keep(current):
        sections.append(current)
    return sections


def _score_section(section: dict, keywords: list[str]) -> int:
    """Score a section: title hits 3x, distinct body keywords 2x, hit-lines capped.

    The hit-line cap stops long command tables (branch name on every line)
    from drowning out the short overview section that actually answers
    "what is X". Ties resolve to document order — intros come first.
    """
    title_lower = section["title"].lower()
    # Exact title match ("# Drone" vs keyword 'drone') outranks mere containment
    score = sum(6 if kw == title_lower else 3 for kw in keywords if kw in title_lower)

    body_kws: set[str] = set()
    hit_lines = 0
    for line in section["lines"]:
        line_lower = line.lower()
        matched = [kw for kw in keywords if kw in line_lower]
        if matched:
            hit_lines += 1
            body_kws.update(matched)

    return score + 2 * len(body_kws) + min(hit_lines, 5)


def _search_readme(branch: str, keywords: list[str]) -> list[dict]:
    """Live-read branch README via handler. Return best-scoring whole sections.

    Reads every call — never cached. Returns up to _MAX_SECTIONS sections,
    highest score first, document order as tie-break.
    """
    lines = read_readme_lines(branch)
    if lines is None:
        logger.warning("[help_chat] Could not read README for branch %s", branch)
        return []

    scored = [(sec, _score_section(sec, keywords)) for sec in _split_sections(lines)]
    hits = [(sec, score) for sec, score in scored if score > 0]
    hits.sort(key=lambda t: (-t[1], t[0]["start"]))
    return [sec for sec, _ in hits[:_MAX_SECTIONS]]


# =============================================================================
# ANSWER FORMATTING
# =============================================================================


def _format_answer(branch: str, readme_path: Path, sections: list[dict]) -> str:
    """Format whole sections into a Markdown answer with line-range citations.

    Citation format: (src/aipass/{branch}/README.md:{start}-{end})
    Bodies longer than _MAX_SECTION_LINES are truncated with a hint
    pointing at `aipass read {branch}`.
    """
    # Build relative citation prefix — always use forward slashes
    # readme_path is absolute; we extract from src/aipass/ onwards
    parts = readme_path.parts
    try:
        src_idx = parts.index("src")
        rel_path = "/".join(parts[src_idx:])
    except ValueError as exc:
        logger.warning("[help_chat] Could not resolve relative path for %s: %s", readme_path, exc)
        rel_path = f"src/aipass/{branch}/README.md"

    blocks: list[str] = []
    for sec in sections:
        body = list(sec["lines"])
        while body and not body[0].strip():
            body.pop(0)
        while body and not body[-1].strip():
            body.pop()

        truncated = False
        if len(body) > _MAX_SECTION_LINES:
            body = body[:_MAX_SECTION_LINES]
            truncated = True

        title = sec["title"] or "(intro)"
        citation = f"({rel_path}:{sec['start']}-{sec['end']})"
        block_lines = [f"**{branch} — {title}**  `{citation}`", ""]
        block_lines.extend(body)
        if truncated:
            block_lines.extend(["", f"*…section truncated — `aipass read {branch}` for the full document*"])
        blocks.append("\n".join(block_lines))

    return "\n\n".join(blocks)


# =============================================================================
# COMMAND HANDLER
# =============================================================================


def handle_command(command: str, args: list[str]) -> bool:
    """Route `aipass help [question]` — returns True if handled."""
    if command != COMMAND:
        return False

    # Log invocation via json_handler for audit trail
    json_handler.ensure_module_jsons(_MODULE_NAME)

    if not args:
        print_help()
        return True

    if args[0] in ("--help", "-h", "help"):
        print_help()
        return True

    if args[0] == "--info":
        print_introspection()
        return True

    question = " ".join(args)
    keywords = _extract_keywords(question)

    if not keywords:
        error("Could not extract keywords from question. Try rephrasing.")
        return True

    branches = _match_branches(keywords)

    console.print()
    header(f"AIPass Help — {question!r}")
    console.print()

    from rich.markdown import Markdown

    found_any = False
    for branch in branches[:3]:  # limit to 3 branches per search
        readme_path = get_readme_path(branch)
        if not readme_path:
            continue
        sections = _search_readme(branch, keywords)
        if sections:
            found_any = True
            answer = _format_answer(branch, readme_path, sections)
            console.print(Markdown(answer))
            console.print()

    if not found_any:
        console.print("[dim]No relevant information found.[/dim]")
        console.print("[dim]Try: aipass help <broader question>[/dim]")
        console.print()

    # Always offer depth — non-negotiable per design
    console.print("Want to go deeper?")
    console.print("  [cyan]→[/cyan] Full README:    [dim]aipass read <branch>[/dim]")
    console.print('  [cyan]→[/cyan] Ask the branch: [dim]drone @ai_mail dispatch @<branch> "Question" "..."[/dim]')
    console.print()

    json_handler.log_operation(
        "help_query",
        data={"question": question, "keywords": keywords, "branches_searched": branches[:3]},
        module_name=_MODULE_NAME,
    )

    return True
