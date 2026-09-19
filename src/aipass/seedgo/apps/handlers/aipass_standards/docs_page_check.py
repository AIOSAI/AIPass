# =================== AIPass ====================
# Name: docs_page_check.py
# Description: Docs Page Standards Checker Handler — one shape for every docs/*.md page
# Version: 1.1.0
# Created: 2026-09-19
# Modified: 2026-09-19
# =============================================

"""
Docs Page Standards Checker Handler (DPLAN-0351)

A docs page is a guide a seat reads on arriving at a branch. The README is the
face; ``docs/`` is the depth; every page has the same shape so a reader, and
the owner sampling at random, meets one layout page to page.

SCORED — six checks over every ``<branch>/docs/*.md`` (one level, the reach of
readme_check's docs index):
1. Back-link and one H1 — a README back-link above the purpose paragraph, and
   exactly one ``# `` heading outside code fences with only blank lines, HTML
   comments and the back-link above it. One rule for how a page opens: the
   back-link is the one thing required in the slot this check already read.
2. Purpose paragraph — the first line under the H1 (back-link lines skipped)
   is prose: not a heading, list, table, quote, fence, rule or lone link.
3. Heading depth — nothing deeper than ``###``.
4. Links resolve — every relative link and image target exists, read from the
   page's own directory.
5. Size — the page is at most the context pack's ``caps["docs/*.md"]`` chars,
   read at call time. An unreadable cap fails the check and names the key.
6. Not a register — the page's name does not contain ``known_issues`` or
   ``tech_debt``. The owner retired the defect registers on 2026-09-19; their
   content lives in each branch's ``docs.local/``, open items on the pad or in
   a plan. A register coming back under ``docs/`` is red.

ADVISORY, NON-SCORED (check_branch_info) — nominations, never a number:
- story: "used to", "previously", <fixed|cured|corrected|retired> ... <date>
  (the arms that hand-sampled at 7/8 or better; history goes to the CHANGELOG)
- defect prose: an open defect told as a paragraph (the owner's pad holds it)
"""

import re
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple
from urllib.parse import unquote

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.context_standards import startup_budget_check as budget

# Audit scope: entry points only (apps/{name}.py) — one call per branch
AUDIT_SCOPE = "entry_point"

#: Page content decides the score, so a page edit must bust the audit cache.
BRANCH_INPUTS = ("docs/*.md",)

_STANDARD = "docs_page"
_DOCS_DIRNAME = "docs"

#: Name fragments of the retired defect registers (the owner, 2026-09-19).
REGISTER_NAME_PARTS: Tuple[str, ...] = ("known_issues", "tech_debt")
_RETIRED = "a defect register, retired 2026-09-19: its content lives in docs.local/, open items on the pad"

CHECK_NAMES: Tuple[str, ...] = (
    "Back-link and one H1",
    "Purpose paragraph",
    "Heading depth",
    "Links resolve",
    "Size",
    "Not a register",
)

_MAX_DEPTH = 3
_SAMPLE_LIMIT = 6

_HEADING_RE = re.compile(r"^(#{1,6})\s+\S")
_LINK_RE = re.compile(r"!?\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_LIST_RE = re.compile(r"^(?:[-*+]\s|\d+[.)]\s)")
_RULE_RE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})$")
_BACKLINK_SLACK = 40

_STORY_ARMS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("used to", re.compile(r"\bused to\b", re.IGNORECASE)),
    ("previously", re.compile(r"\bpreviously\b", re.IGNORECASE)),
    (
        "cured on a date",
        re.compile(
            r"\b(?:fixed|cured|corrected|retired)\b[^.\n]{0,60}\b20\d\d-\d\d-\d\d\b"
            r"|\b20\d\d-\d\d-\d\d\b[^.\n]{0,60}\b(?:fixed|cured|corrected|retired)\b",
            re.IGNORECASE,
        ),
    ),
)
_DEFECT_RE = re.compile(
    r"\b(?:known (?:bug|issue|defect|gap)|open defect|not yet (?:fixed|built|wired|implemented)"
    r"|still (?:broken|open|red)|currently (?:broken|fails|red)|workaround|tracked in [A-Z]PLAN"
    r"|is a bug|a bug:|defect:)",
    re.IGNORECASE,
)


class Page(NamedTuple):
    """One docs page, read once. ``fenced[i]`` is True inside a code fence."""

    path: Path
    text: str
    lines: List[str]
    fenced: List[bool]


# =============================================================================
# THE CORPUS
# =============================================================================


def is_register(page_path: Path) -> bool:
    """True for a retired defect register by name, however spelt: known_issues, Known-Issues, tech debt."""
    name = re.sub(r"[-\s]", "_", page_path.name.lower())
    return any(part in name for part in REGISTER_NAME_PARTS)


def _fence_mask(lines: List[str]) -> List[bool]:
    mask: List[bool] = []
    inside = False
    for line in lines:
        if line.lstrip().startswith(("```", "~~~")):
            inside = not inside
            mask.append(True)
            continue
        mask.append(inside)
    return mask


def read_page(page_path: Path) -> Tuple[Optional[Page], str]:
    """``(page, "")`` or ``(None, reason)`` when the file cannot be read as utf-8."""
    try:
        text = page_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.info("[docs_page] cannot read %s: %s", page_path, exc)
        return None, f"cannot be read ({type(exc).__name__})"
    lines = text.split("\n")
    return Page(page_path, text, lines, _fence_mask(lines)), ""


def docs_pages(branch_root: Path, bypass_rules: list | None = None) -> List[Path]:
    """The scored corpus: ``docs/*.md``, one level, minus bypassed pages."""
    docs_dir = branch_root / _DOCS_DIRNAME
    if not docs_dir.is_dir():
        return []
    return [
        page
        for page in sorted(docs_dir.glob("*.md"))
        if page.is_file() and not is_bypassed(str(page), _STANDARD, None, bypass_rules)
    ]


# =============================================================================
# THE FIVE RULES — each returns "" for a pass, or why the page fails
# =============================================================================


def _links(line: str) -> List[str]:
    return [found.group(2) for found in _LINK_RE.finditer(_INLINE_CODE_RE.sub("", line))]


def _resolves_to_readme(target: str, page: Page) -> bool:
    bare = unquote(target.split("#")[0].split("?")[0])
    if not bare or _SCHEME_RE.match(bare):
        return False
    return (page.path.parent / bare).resolve() == (page.path.parent.parent / "README.md").resolve()


def is_backlink_line(line: str, page: Page) -> bool:
    """A line that is a link back to the branch README and little else."""
    targets = _links(line)
    if not targets or not all(_resolves_to_readme(target, page) for target in targets):
        return False
    return len(_LINK_RE.sub("", line).strip()) <= _BACKLINK_SLACK


def _is_comment(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("<!--") and stripped.endswith("-->")


def _h1_lines(page: Page) -> List[int]:
    return [
        i
        for i, line in enumerate(page.lines)
        if not page.fenced[i] and (match := _HEADING_RE.match(line)) and len(match.group(1)) == 1
    ]


def _above_purpose(page: Page) -> List[str]:
    """The lines above the purpose paragraph: before the H1, and back-link lines under it."""
    h1s = _h1_lines(page)
    if not h1s:
        return []
    head = page.lines[: h1s[0]]
    for i in range(h1s[0] + 1, len(page.lines)):
        if page.lines[i].strip() and not is_backlink_line(page.lines[i], page):
            break
        head.append(page.lines[i])
    return head


def has_backlink(page: Page) -> bool:
    """A README back-link sits above the purpose paragraph."""
    return any(is_backlink_line(line, page) for line in _above_purpose(page))


def opening(page: Page) -> str:
    """Rule 1: exactly one H1 with nothing but blanks, comments and a back-link above it, and the back-link there."""
    h1s = _h1_lines(page)
    if len(h1s) != 1:
        return "no H1" if not h1s else f"{len(h1s)} H1 headings"
    for i in range(h1s[0]):
        line = page.lines[i]
        if page.fenced[i] or not (not line.strip() or _is_comment(line) or is_backlink_line(line, page)):
            return f"line {i + 1} comes before the H1"
    if not has_backlink(page):
        return "no README back-link above the purpose paragraph"
    return ""


def purpose_paragraph(page: Page) -> str:
    """Rule 2: the first line under the H1 is a prose paragraph."""
    h1s = _h1_lines(page)
    if not h1s:
        return "no H1 to sit under"
    for i in range(h1s[0] + 1, len(page.lines)):
        line = page.lines[i]
        stripped = line.strip()
        if not page.fenced[i] and (not stripped or _is_comment(line) or is_backlink_line(line, page)):
            continue
        if page.fenced[i]:
            return f"line {i + 1} under the H1 is a code fence"
        if _HEADING_RE.match(stripped) or stripped.startswith(("|", ">", "<")) or _LIST_RE.match(stripped):
            return f"line {i + 1} under the H1 is not prose"
        if _RULE_RE.match(stripped) or not _LINK_RE.sub("", stripped).strip(" .:-—"):
            return f"line {i + 1} under the H1 is not prose"
        return ""
    return "nothing under the H1"


def heading_depth(page: Page) -> str:
    """Rule 3: no heading deeper than ``###``."""
    for i, line in enumerate(page.lines):
        match = _HEADING_RE.match(line)
        if match and not page.fenced[i] and len(match.group(1)) > _MAX_DEPTH:
            return f"line {i + 1} is a depth-{len(match.group(1))} heading"
    return ""


def dead_links(page: Page) -> List[str]:
    """Rule 4's evidence: relative link targets that do not exist from the page's directory."""
    dead: List[str] = []
    for i, line in enumerate(page.lines):
        if page.fenced[i]:
            continue
        for target in _links(line):
            bare = unquote(target.split("#")[0].split("?")[0])
            if not bare or _SCHEME_RE.match(bare):
                continue
            if not (page.path.parent / bare).exists():
                dead.append(target)
    return dead


def links_resolve(page: Page) -> str:
    """Rule 4: every relative link resolves."""
    dead = dead_links(page)
    return f"dead link(s) {_sample(dead)}" if dead else ""


def size_within(page: Page, cap: Optional[int]) -> str:
    """Rule 5: at most ``cap`` chars. At the cap passes."""
    if cap is not None and len(page.text) > cap:
        return f"{len(page.text):,} chars, over by {len(page.text) - cap:,}"
    return ""


def not_a_register(page: Page) -> str:
    """Rule 6: the page is not a retired defect register."""
    return _RETIRED if is_register(page.path) else ""


# =============================================================================
# THE SCORE
# =============================================================================


def _safe(text: str) -> str:
    """Page text made safe for a Rich console: brackets would read as style tags."""
    return text.replace("[", "(").replace("]", ")")


def _sample(names: List[str]) -> str:
    head = ", ".join(_safe(name) for name in names[:_SAMPLE_LIMIT])
    extra = len(names) - _SAMPLE_LIMIT
    return f"{head} and {extra} more" if extra > 0 else head


def _check(name: str, failures: List[str], measured: int) -> Dict:
    if not failures:
        return {"name": name, "passed": True, "message": f"All {measured} docs page(s) pass"}
    return {"name": name, "passed": False, "message": f"{len(failures)} of {measured} page(s): {_sample(failures)}"}


def check_pages(pages: List[Path], cap: Optional[int], cap_error: str) -> List[Dict]:
    """The six checks over ``pages``. An unreadable page fails all six."""
    failures: Dict[str, List[str]] = {name: [] for name in CHECK_NAMES}
    for path in pages:
        page, reason = read_page(path)
        label = f"docs/{path.name}"
        if page is None:
            for name in CHECK_NAMES:
                failures[name].append(f"{label} {reason}")
            continue
        verdicts = (opening(page), purpose_paragraph(page), heading_depth(page), links_resolve(page))
        for name, verdict in zip(CHECK_NAMES, verdicts + (size_within(page, cap), not_a_register(page))):
            if verdict:
                failures[name].append(f"{label} ({verdict})")
    checks = [_check(name, failures[name], len(pages)) for name in CHECK_NAMES]
    if cap is None:
        size = CHECK_NAMES.index("Size")
        checks[size] = {"name": "Size", "passed": False, "message": cap_error or "docs page cap unreadable"}
    return checks


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Score every docs/*.md page of the branch whose entry point is ``module_path``.

    Args:
        module_path: The branch entry point, ``<branch>/apps/<branch>.py``.
        bypass_rules: Rules from .seedgo/bypass.json. A rule on the entry point
            bypasses the standard; a rule on one page takes that page out.

    Returns:
        ``{"passed", "checks", "score", "standard"}`` — six checks.
    """
    if is_bypassed(module_path, _STANDARD, bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "DOCS_PAGE",
        }
    branch_root = Path(module_path).parent.parent
    pages = docs_pages(branch_root, bypass_rules)
    if not pages:
        checks = [{"name": name, "passed": True, "message": "No docs/*.md pages (skipped)"} for name in CHECK_NAMES]
    else:
        cap, cap_error = budget.docs_page_cap()
        checks = check_pages(pages, cap, cap_error)
    score = int(sum(1 for check in checks if check["passed"]) / len(checks) * 100)
    json_handler.log_operation(
        "check_completed", {"file": str(module_path), "score": score, "standard": _STANDARD, "pages": len(pages)}
    )
    return {"passed": score >= 75, "checks": checks, "score": score, "standard": "DOCS_PAGE"}


def external_inputs() -> List[Path]:
    """The context pack's pack.json: the size cap is read from it, so a cap change re-scores."""
    return [budget.pack_manifest_path()]


# =============================================================================
# ADVISORY — check_branch_info, rendered at any score, never a number
# =============================================================================


def _prose(page: Page) -> List[Tuple[int, str]]:
    """``(line number, text)`` for prose lines: outside fences and tables, link text stripped."""
    return [
        (i + 1, _LINK_RE.sub("", line))
        for i, line in enumerate(page.lines)
        if not page.fenced[i] and line.strip() and not line.lstrip().startswith("|")
    ]


def story_lines(page: Page) -> List[int]:
    """Lines telling history: the high-precision story arms."""
    return [number for number, text in _prose(page) if any(arm.search(text) for _, arm in _STORY_ARMS)]


def _points_at_registry(line: str) -> bool:
    """A line linking to a known_issues / tech_debt page is a pointer to the register, not a defect told here."""
    return any(is_register(Path(unquote(target.split("#")[0]))) for target in _links(line))


def defect_lines(page: Page) -> List[int]:
    """Lines telling an open defect as prose, outside link text and pointers to the register."""
    return [
        number
        for number, text in _prose(page)
        if _DEFECT_RE.search(text) and not _points_at_registry(page.lines[number - 1])
    ]


def _nominations(pages: List[Page]) -> Tuple[List[str], List[str]]:
    story = [f"docs/{page.path.name}:{n}" for page in pages for n in story_lines(page)]
    defects = [f"docs/{page.path.name}:{n}" for page in pages for n in defect_lines(page)]
    return story, defects


def check_branch_info(branch_path: str) -> List[str]:
    """Non-scored nominations: story lines and defect prose. The back-link scores under rule 1.

    Args:
        branch_path: Branch root to inspect.

    Returns:
        Advisory lines, each marked ``(advisory)``. Empty when the branch has
        no docs pages.
    """
    branch_root = Path(branch_path)
    pages = [page for page, _ in (read_page(path) for path in docs_pages(branch_root)) if page is not None]
    if not pages:
        return []
    story, defects = _nominations(pages)
    lines = []
    if story:
        lines.append(f"docs_page story (advisory): {len(story)} line(s) tell history — {_sample(story)}")
    if defects:
        lines.append(f"docs_page defect prose (advisory): {len(defects)} line(s) — {_sample(defects)}")
    if lines:
        json_handler.log_operation(
            "docs_page_advisory_lines", {"branch": branch_root.name, "count": len(lines), "standard": _STANDARD}
        )
    return lines
