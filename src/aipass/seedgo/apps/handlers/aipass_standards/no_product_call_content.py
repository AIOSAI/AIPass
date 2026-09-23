# =================== AIPass ====================
# Name: no_product_call_content.py
# Description: No Product Call Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
No Product Call Standards Content Handler

Provides formatted No Product Call standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_no_product_call_standards() -> str:
    """Return formatted no_product_call standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (crack class A, review of @backup 2026-09-22):[/bold cyan]",
        "  A [green]def test_*[/green] must reach the product. A test no edit anywhere in",
        "  aipass/ can turn red is green for a reason that has nothing to do with",
        "  the code it is filed under.",
        "",
        "  The reviewers called these [red]LIBRARY[/red] tests, because what they usually",
        "  pin is a third party: pathspec matching a glob, StringIO returning what",
        "  was written to it, capsys capturing a print. All ten template checkers",
        "  pass them. Those measure SHAPE; this one measures whether the test is",
        "  pointed at anything.",
        "",
        "[bold cyan]IT IS A REACHABILITY RULE, NOT A CALL-SITE RULE:[/bold cyan]",
        "  Reachable means the test's body, its decorators, every same-file helper",
        "  it calls, and every fixture it requests. NAMING the product means any of:",
        "",
        "  [green]•[/green] a name bound by an [green]aipass.*[/green] import",
        "  [green]•[/green] a module-level constant whose value reaches one (fixed point) —",
        "    SIMPLE_MODULES = [snapshot, versioned] is how a parametrized test",
        "    reaches mod.handle_command with the import three screens up",
        "  [green]•[/green] a dotted string starting [green]aipass.[/green] — import_module and mock.patch",
        "    both take the product by name, not by binding",
        "  [green]•[/green] a multi-line string mentioning aipass — a probe source a subprocess",
        "    runs is product code, written down",
        "  [green]•[/green] a path computed from [green]__file__[/green] — it points into the repo tree",
        "",
        "[bold cyan]TWO ACQUITTALS THAT ARE NOT ABOUT THE PRODUCT AT ALL:[/bold cyan]",
        "  [green]The file's own apparatus.[/green] A call to a function defined in this file, or",
        "  a fixture defined in the branch conftest. A negative control feeding a",
        "  synthetic source to the file's own detector is a META-test, not a library",
        "  test — @backup has nine. The class is 'pointed at nothing', and a control",
        "  for the file's own apparatus IS pointed at something.",
        "",
        "  [green]A class that reaches.[/green] A unittest.TestCase method reaches the product",
        "  through self.conn, which setUp built and the body never mentions.",
        "",
        "[bold cyan]CHECK FIRST (measured 2026-09-22 over 559 fleet test files):[/bold cyan]",
        "  [green]23 files, 82 hits, 7.9s.[/green] Top three: prax 5 files, commons 3, memory 3.",
        "  Worst file: commons/test_commons.py at 29 — 29 methods running raw SQL",
        "  against a sqlite connection with no commons code on the path at all.",
        "",
        "  [green]Against the reviewers' ground truth:[/green] the nine reports name 12 LIBRARY",
        "  rows in @backup and this checker convicts all 12 and misses none. It",
        "  convicts two more there (test_ignore_pathspec.py 135, 142) which the",
        "  reviewers marked DUPLICATE — a second true reading of the same rows, not",
        "  a false one. Eight of the nine reviewed files pass clean.",
        "",
        "[bold cyan]FOUR CUTS, AND THE NUMBER MOVED BY 70x:[/bold cyan]",
        "  A call-site rule convicted 295 files and 5,807 hits, and nearly all of it",
        "  was false. Parametrize argvalues, a probe source handed to a subprocess, a",
        "  dotted module path in an f-string, and a setUp that builds the world are",
        "  four ways to reach the product with no call site a checker can see. Every",
        "  acquittal above is one of them, found by reading what an earlier cut",
        "  convicted — not by tuning to a number.",
        "",
        "[bold cyan]KNOWN LIMITS:[/bold cyan]",
        "  A test whose only product contact is a helper in a SIBLING test file is",
        "  acquitted only if the name also exists in this file or the conftest —",
        "  one pass reads one file plus its conftest.",
        "  The class acquittal is generous on purpose: one product name anywhere in",
        "  a TestCase body clears every method on it. @backup's",
        "  test_cli_routing.py:510, which the reviewers marked OUT-OF-PLACE for",
        "  'asserts only on a literal this file defines', is acquitted that way.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per file. Every convicted test is named with its line on ONE",
        "  check, because the checklist prints the first failed check and hides the",
        "  rest behind a count. conftest.py holds no tests and always scores 100.",
    ]

    json_handler.log_operation("content_served", {"standard": "no_product_call"})
    return "\n".join(lines)
