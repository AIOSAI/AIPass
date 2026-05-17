# =================== AIPass ====================
# Name: help_chat.py
# Description: README-backed chatbot Q&A — Phase 2 of DPLAN-0136
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-04-16
# =============================================

"""
aipass help — chatbot-style Q&A over branch READMEs

User types `aipass help <question>`. We:
    1. Extract keywords from the question (stopword filter, no ML)
    2. Match keywords against branch names / README paths
    3. Live-read {branch}/README.md for matched branches
    4. Return concise answer sourced from matching lines with citations
    5. Always offer depth: view full README or dispatch to @branch

Principle: nothing cached except branch-name → README-path map.
Every answer re-reads the real file. Stale info is the enemy.

No LLM in v1 — scripted keyword lookups only.
"""

from __future__ import annotations

from pathlib import Path

from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.readme_map import get_readme_path, list_branches
from aipass.cli.apps.modules import console, error, header
from aipass.prax import logger

# =============================================================================
# MODULE METADATA
# =============================================================================

COMMAND = "help"
_MODULE_NAME = "help_chat"
_VERSION = "1.0.0"
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
# README SEARCH (LIVE-READ)
# =============================================================================


def _search_readme(readme_path: Path, keywords: list[str]) -> list[tuple[int, str]]:
    """Live-read readme_path. Return (line_num, line_text) for matching lines.

    Reads every call — never cached. Scores lines by number of keyword hits.
    Returns up to 5 best matches.
    """
    try:
        with open(readme_path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        logger.warning("[help_chat] Could not read README %s: %s", readme_path, exc)
        return []

    scored: list[tuple[int, int, str]] = []  # (score, line_num, line_text)
    for idx, line in enumerate(lines, start=1):
        line_lower = line.lower()
        score = sum(1 for kw in keywords if kw in line_lower)
        if score > 0:
            scored.append((score, idx, line.rstrip()))

    # Sort by score descending, then by line number for tie-breaking
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [(ln, text) for _, ln, text in scored[:5]]


# =============================================================================
# ANSWER FORMATTING
# =============================================================================


def _format_answer(branch: str, readme_path: Path, matches: list[tuple[int, str]]) -> str:
    """Format matched lines into a readable answer with citations.

    Citation format: (src/aipass/{branch}/README.md:{line_num})
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

    lines_out: list[str] = [f"[{branch}]"]
    for line_num, line_text in matches:
        citation = f"({rel_path}:{line_num})"
        lines_out.append(f"  {line_text.strip()}  {citation}")

    return "\n".join(lines_out)


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
        print_introspection()
        return True

    if args[0] in ("--help", "-h", "help"):
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

    found_any = False
    for branch in branches[:3]:  # limit to 3 branches per search
        readme_path = get_readme_path(branch)
        if not readme_path:
            continue
        matches = _search_readme(readme_path, keywords)
        if matches:
            found_any = True
            answer = _format_answer(branch, readme_path, matches)
            console.print(answer)
            console.print()

    if not found_any:
        console.print("[dim]No relevant information found.[/dim]")
        console.print("[dim]Try: aipass help <broader question>[/dim]")
        console.print()

    # Always offer depth — non-negotiable per design
    console.print("Want to go deeper?")
    console.print("  [cyan]→[/cyan] View branch README:  [dim]aipass read <branch>[/dim]")
    console.print("  [cyan]→[/cyan] Connect with branch: [dim]aipass dispatch @<branch> <question>[/dim]")
    console.print()

    json_handler.log_operation(
        "help_query",
        data={"question": question, "keywords": keywords, "branches_searched": branches[:3]},
        module_name=_MODULE_NAME,
    )

    return True
