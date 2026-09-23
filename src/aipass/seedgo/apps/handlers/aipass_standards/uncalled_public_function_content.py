# =================== AIPass ====================
# Name: uncalled_public_function_content.py
# Description: Uncalled Public Function Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
Uncalled Public Function Standards Content Handler

Provides formatted Uncalled Public Function standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_uncalled_public_function_standards() -> str:
    """Return formatted uncalled_public_function standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (crack class O, review of @backup 2026-09-22):[/bold cyan]",
        "  A public function of a test file's DECLARED SUBJECT module — the path in",
        "  its one-line docstring, test template v1 item 6 — that no test in the",
        "  branch ever calls. The file claims to test that module; one of its public",
        "  functions is not tested by anything.",
        "",
        "[bold cyan]THE CRISP PART IS WHAT COUNTS AS CALLED:[/bold cyan]",
        "",
        "  [green]CALLED[/green]      Named in a Call, or an attribute access that is then",
        "              called. share_mod.run_share(file_arg) is a call.",
        "",
        "  [red]O1 REPLACED[/red] Named ONLY as a patch / monkeypatch.setattr target —",
        "              replaced and never run. @backup's apps/backup.py:125",
        "              discover_modules is it exactly: four sites in",
        "              test_cli_routing.py replace it with return_value=[fake_module]",
        "              and nothing anywhere runs the real importlib discovery.",
        "",
        "  [green]REACHED[/green]     Through the product — the false conviction to avoid.",
        "              A name-level call graph over the branch's whole apps/, seeded",
        "              with every function name the tests DO call and closed to a",
        "              fixed point. In the closure → acquit. That guard acquits",
        "              [green]18 of the 20 candidates[/green], including route_command and every",
        "              print_introspection, which main() reaches for real.",
        "",
        "  A name-level graph collapses two modules that both define run, so it",
        "  over-acquits rather than under-acquits. For a SCORED rule that is the",
        "  right direction, and the number it acquits rides in the passing message.",
        "",
        "[bold cyan]CHECK FIRST (measured 2026-09-22 over the fleet):[/bold cyan]",
        "  [green]2 files, 2 hits, 9.7s[/green]. @backup both:",
        "    apps/backup.py:125 discover_modules — O1",
        "    apps/handlers/report/result.py:50 new_result — O2, defined once and",
        "      referenced nowhere in apps/ or tests/",
        "",
        "  [red]ONLY 69 OF THE FLEET'S 561 TEST FILES DECLARE A SUBJECT PATH AT ALL.[/red]",
        "  That is the headline and it caps the rule: O cannot judge a file that",
        "  never says what it tests. file_top's item 6 sub-rule convicts the other",
        "  492, and every file it cures hands this rule a new subject to read.",
        "",
        "[bold cyan]READ THE DOCSTRING PROPERLY — findall, not search:[/bold cyan]",
        "  'Tests for apps/modules/share.py and apps/handlers/drive/share.py'",
        "  declares TWO subjects. Taking only the first mis-attributes the second",
        "  module's functions to nobody.",
        "",
        "[bold cyan]WHERE IT DISAGREES WITH THE REVIEW, WITH THE LINE NUMBER:[/bold cyan]",
        "  run_share is offered as 'replaced at test_share.py 100, 112, 122 and never",
        "  runs anywhere in the suite'. [red]It runs.[/red] test_caller_path.py:86 calls",
        "  share_mod.run_share(file_arg) for real, with Drive mocked beneath it. The",
        "  brief's own wording is 'no test anywhere in the branch's tests/ calls', so",
        "  this rule ACQUITS it and is right to.",
        "",
        "  generate_diff_content is offered conditionally, 'if generator.py is within",
        "  the subject of a backup test file'. It is not — test_versioned_engine.py",
        "  declares copy/versioned.py and modules/restore.py. The rule does not see",
        "  it, which is correct and is also a hole: [yellow]a module nothing declares as a",
        "  subject is invisible to O no matter how untested it is.[/yellow]",
        "",
        "  restore.py's bare-basename fallback is a coverage gap inside a function,",
        "  not a function. O does not see it and should not.",
        "",
        "[bold cyan]WHY IT CANNOT BE SATISFIED BY ACCIDENT:[/bold cyan]",
        "  The file says in its own docstring that it tests this module. If a public",
        "  function of that module is never called, never reachable from anything",
        "  called, and named only where it is being replaced, then nothing in the",
        "  suite has ever run it.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per BRANCH — the rule compares declared subjects against the whole",
        "  tests/ tree. Every hit names the function, its line and its shape, on ONE",
        "  check. Functions the product still reaches are counted, never charged.",
        "",
        "[bold cyan]THE CURE:[/bold cyan]",
        "  [green]call it in a test, or retire it.[/green]",
    ]

    json_handler.log_operation("content_served", {"standard": "uncalled_public_function"})
    return "\n".join(lines)
