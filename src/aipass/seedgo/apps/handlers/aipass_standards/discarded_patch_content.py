# =================== AIPass ====================
# Name: discarded_patch_content.py
# Description: Discarded Patch Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
Discarded Patch Standards Content Handler

Provides formatted Discarded Patch standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_discarded_patch_standards() -> str:
    """Return formatted discarded_patch standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (crack class R, review of @backup 2026-09-22):[/bold cyan]",
        "  A test replaces a function in [red]its own branch[/red] with a mock, hands the mock",
        "  nothing, binds it to nothing, and asserts nothing about it. The",
        "  replacement is pure silence. The product's call to that function is then",
        "  unpinned, and the call can be deleted with the suite green.",
        "",
        "[bold cyan]THE SHAPE IN ONE FILE:[/bold cyan]",
        "  @backup's test_ceiling_guard.py wraps every check_ceiling call in",
        "  [red]patch('aipass.backup...audit.trail.log_operation')[/red] and discards the mock.",
        "  The reviewer's finding: [red]delete _log_breach (ceiling.py:168-179) entirely",
        "  and all 21 tests pass.[/red] The ops-log entry is the only forensic trace of a",
        "  runaway refusal, and nothing pins it.",
        "",
        "[bold cyan]WHAT STAYS LEGAL — each acquittal is a measured cut:[/bold cyan]",
        "",
        "  [green]ANOTHER BRANCH, A GATEWAY, THE CLOCK, THE NETWORK[/green]",
        "     That is an edge, and sealing an edge is what a test is for. Only a",
        "     target inside the test file's OWN branch is judged. The branch comes",
        "     from the file's path; the target from an aipass.<branch>. string or a",
        "     name imported from that package.",
        "",
        "  [green]A REPLACEMENT HANDED OVER[/green]",
        "     patch(target, tmp_path) redirects a path constant at a test-owned",
        "     directory. return_value=, side_effect=, new=, new_callable=, wraps=,",
        "     spec= and autospec= all drive or shape what the product gets. That is",
        "     a seam doing work, not a mock thrown away. This one acquittal took",
        "     the count from [green]1,025 to 692[/green].",
        "",
        "  [green]AN as BINDING THAT IS REFERENCED[/green]",
        "     And a @patch parameter that is referenced. Asserting on the mock is",
        "     the whole cure. The reference may sit AFTER the with block closes —",
        "     reading only the block's own statements convicted [red]51 files and 331",
        "     hits[/red] that are perfectly sound.",
        "",
        "  [green]A NAMED OR RECORDING monkeypatch.setattr[/green]",
        "     monkeypatch.setattr has no bare-mock form — the replacement is a",
        "     required argument — so 1,838 own-branch calls all pass the test above.",
        "     [red]222 of them hand over something ANONYMOUS[/red]: Mock() with no arguments,",
        "     or lambda *a, **k: None. Nothing binds it, it records nothing, and the",
        "     silenced call is as unpinned as a discarded patch. A NAMED replacement",
        "     is acquitted; a RECORDER lambda is acquitted by its body.",
        "",
        "  [green]A PATCH IN A FIXTURE OR A HELPER[/green]",
        "     The branch conftest's seam is the sanctioned place to silence",
        "     infrastructure; a patch in a test body that duplicates it is the",
        "     defect. Only def test_* bodies are judged.",
        "",
        "[bold cyan]CHECK FIRST (measured 2026-09-22 over 561 fleet test files):[/bold cyan]",
        "  [green]73 files, 529 hits, 6.4s[/green]. Top three: seedgo 12 files, commons 10, api 7 —",
        "  my own branch is worst, and it stays worst until it is cured.",
        "  Worst single file: ai_mail/test_dispatch_monitor.py at 65.",
        "  By spelling: patch / patch.object 47 files, 309 hits · monkeypatch.setattr",
        "  26 files, 220 hits.",
        "",
        "  FIVE CUTS, 6,401 → 309, and the LAST was the biggest correction:",
        "    any unused binding          250 files / 6,401 hits",
        "    own-branch targets only     203 / 3,547",
        "    nothing handed over         111 / 1,025",
        "    ...second POSITIONAL too     97 / 692",
        "    test bodies + @patch form   110 / 786",
        "    assertions after the with    47 / 309",
        "",
        "[bold cyan]WHAT IT DECLINES, AND WHY:[/bold cyan]",
        "  [red]test_handlers_filesystem.py 68, 83[/red] — the reviewer is right that the",
        "  defect is real, but it is not this one. filter_paths NEVER REACHES the",
        "  patched function: a [yellow]dead[/yellow] patch, not a discarded one. That needs the",
        "  product's call graph; one file's AST cannot see it. Both also carry",
        "  return_value=, so the mock is answering, not silent.",
        "",
        "  [red]test_share.py 100, 112, 122[/red] — each is a monkeypatch recorder followed by",
        "  assert ran == []. The reviewer marked them SOUND. A recorder that is",
        "  asserted is the cure, not the defect.",
        "",
        "[bold cyan]WHY IT CANNOT BE SATISFIED BY ACCIDENT:[/bold cyan]",
        "  If you never name the mock and never ask it anything, the only effect",
        "  your patch has on the test's verdict is to make one of the product's",
        "  calls unobservable. There is no threshold and nothing to tune.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per file. Every hit names the line, the patched target and the",
        "  cure, on ONE check. A file outside any branch scores 100 — it has no own",
        "  code to discard a patch of.",
        "",
        "[bold cyan]THE CURE:[/bold cyan]",
        "  [green]assert on the mock, or drop the patch and let the call stand.[/green]",
    ]

    json_handler.log_operation("content_served", {"standard": "discarded_patch"})
    return "\n".join(lines)
