# =================== AIPass ====================
# Name: docs_page_content.py
# Description: Docs Page Standards Content — the one shape of a docs/*.md page
# Version: 1.1.0
# Created: 2026-09-19
# Modified: 2026-09-19
# =============================================

"""
Docs Page Standards Content

Provides Rich-formatted reference text for the docs_page standard (DPLAN-0351).
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_docs_page_standards() -> str:
    """Return Rich-formatted docs page standards text"""
    json_handler.log_operation("standard_content_queried", {"standard": "docs_page"})
    return """[bold white]DOCS PAGE STANDARD[/bold white]

[yellow]WHO READS A PAGE:[/yellow]
  A seat arriving at the branch, or a stranger. After one page they must be
  able to find the verb, understand the reason behind the design, and know
  what is not verified. The README is the face; [dim]docs/[/dim] is the depth,
  one page per module or handler group. Every page has the same shape, so a
  reader - and the owner sampling at random - meets one layout throughout.

[yellow]THE SHAPE:[/yellow]

  [dim][<- Back to the README](../README.md)[/dim]     a bare back-link, top
  [dim]# <Title>[/dim]                                one H1
  [dim]<one purpose paragraph, present tense>[/dim]   what the page is for
  [dim]## <topic> ... ### <detail>[/dim]              free topic sections, depth <= 3
  [dim]## Why it is this way[/dim]                    optional, fixed name
  [dim]## What is not verified[/dim]                  optional, fixed name
  [dim]## Related[/dim]                               optional, fixed name

  Commands by reference - [bold cyan]drone @<branch> --help[/bold cyan] is the
  source of truth; a page that re-types it rots. No history (the CHANGELOG has
  it), no cured entries, no defect paragraphs (the owner's pad holds them).
  [dim]docs/README.md[/dim] is the index shape: back-link, title, one line,
  then one line per page.

[yellow]SCORED - 6 checks over every docs/*.md (one level):[/yellow]

  [bold cyan]1 Back-link and one H1[/bold cyan]  a README back-link above the purpose paragraph
                        (on top, or straight under the H1); exactly one [dim]# [/dim]
                        heading outside code fences; only blanks, HTML comments
                        and the back-link above it. The move stamp's link,
                        below the purpose, is not the slot
  [bold cyan]2 Purpose paragraph[/bold cyan]  the first line under the H1 (back-link lines
                        skipped) is prose - not a heading, list, table, quote,
                        fence, rule or lone link
  [bold cyan]3 Heading depth[/bold cyan]      nothing deeper than [dim]###[/dim]
  [bold cyan]4 Links resolve[/bold cyan]      every relative link and image exists, read from
                        the page's own directory (as GitHub renders it)
  [bold cyan]5 Size[/bold cyan]               at most the context pack's [dim]caps["docs/*.md"][/dim]
                        chars, read at call time. At the cap passes. A cap
                        that cannot be read fails the check and names the key
  [bold cyan]6 Not a register[/bold cyan]     the page's name does not contain [dim]known_issues[/dim] or
                        [dim]tech_debt[/dim] (hyphen and space spellings too)

  6 checks, ~17 points each. Pass threshold 75%; CI holds every branch at 100.
  No docs/ pages is a skip, not a red.

[yellow]THE DEFECT REGISTERS - retired 2026-09-19:[/yellow]

  The owner retired every docs/known_issues.md and docs/tech_debt.md. Their
  content lives in each branch's [dim]docs.local/[/dim], untracked; an open item goes
  on the owner's pad or into a plan. A register coming back under docs/ is
  red by check 6.

[yellow]ADVISORY - nominations, never a number:[/yellow]

  [bold cyan]story[/bold cyan]         "used to", "previously", fixed/cured/corrected/retired
                 next to a date - the arms that hand-sampled at 7/8 or better.
                 A dated WHY is a reason and stays; a dated WHAT CHANGED is history.
  [bold cyan]defect prose[/bold cyan]  an open defect told as a paragraph ("known gap",
                 "still open", "tracked in APLAN-..."). A line that links to the
                 register is a pointer and is not nominated.

[yellow]NOT THE CORPUS:[/yellow]

  [dim]docs/**/[/dim] below one level, and [dim]docs.local/[/dim]. Research and dated one-offs
  are not docs at all - they live in [dim]docs.local/[/dim], untracked.

[yellow]BYPASS:[/yellow]

  Per page, by path: [dim]{"file": "docs/<page>.md", "standard": "docs_page"}[/dim]
  in the branch's [dim].seedgo/bypass.json[/dim]. On the entry point it bypasses
  the whole standard."""
