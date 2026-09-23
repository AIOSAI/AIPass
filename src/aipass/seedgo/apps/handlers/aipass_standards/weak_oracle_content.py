# =================== AIPass ====================
# Name: weak_oracle_content.py
# Description: Weak Oracle Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
Weak Oracle Standards Content Handler

Provides formatted Weak Oracle standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_weak_oracle_standards() -> str:
    """Return formatted weak_oracle standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (crack class D, review of @backup 2026-09-22):[/bold cyan]",
        "  A test whose ENTIRE oracle cannot exclude the failure its name claims to",
        "  exclude. The largest verdict class the reviewers found: [red]51 WEAK rows out",
        "  of 285 tests.[/red]",
        "",
        "[bold cyan]SCORED ONLY WHEN IT IS THE WHOLE ORACLE:[/bold cyan]",
        "  A test that asserts the effect AND also checks isinstance is a good test",
        "  with a redundant line; charging it would be charging the thoroughness.",
        "  Every form below is judged against the test's complete set of assertions",
        "  — assert statements plus mock.assert_* calls.",
        "",
        "[bold cyan]THE SIX SCORED FORMS — each a thing a test cannot fail:[/bold cyan]",
        "",
        "  [red]D1[/red]  assert <constant>            assert True cannot fail.",
        "  [red]D2[/red]  assert <name>, alone         a bare local's truthiness.",
        "  [red]D3[/red]  is not None, alone           every object is not None.",
        "  [red]D4[/red]  isinstance(...), alone       the type, never the value.",
        "  [red]D5[/red]  assert_called / assert_called_once with NO arguments —",
        "      proves the call happened, pins nothing it was given.",
        "  [red]D6[/red]  assert f(...) is None where f is annotated -> None —",
        "      a tautology. The function CANNOT return anything else.",
        "",
        "  [green]NOT D2: assert is_ignored(p, spec).[/green] A predicate CALL's truthiness IS the",
        "  claim — it asks the product a specific question and asserts its answer.",
        "  Scoring it cost [red]1,356 false hits[/red] in the first cut and failed the model",
        "  file. isinstance is the one exception, because it answers about the TYPE.",
        "",
        "[bold cyan]REPORTED WITH A COUNT, NEVER SCORED:[/bold cyan]",
        "  is None alone (not a -> None function) · len and count compares ·",
        "  >= <= > < bounds · in and not in (substring of output, key of a dict) ·",
        "  == {} on a loader. Each of these can legitimately be the right oracle",
        "  and a rule cannot tell which, so the number rides in the PASSING message",
        "  and nobody is charged for it.",
        "",
        "[bold cyan]A SOFT COMPANION DOES NOT ACQUIT; only a STRONG one does.[/bold cyan]",
        "  This is the one place the rule bites harder than it reads, so it is",
        "  named. assert breach is not None plus two 'text' in output checks is",
        "  scored D3: nothing in it pins a value the product computed.",
        "  test_ceiling_guard.py 153 and 162 are exactly that shape, and the review",
        "  asked for it directly with test_module_isolation.py:48, whose companion",
        "  is a not in sys.modules.",
        "",
        "[bold cyan]A pytest.raises ANYWHERE IN THE TEST ACQUITS IT OUTRIGHT:[/bold cyan]",
        "  'It raised the right exception' is a real oracle, and it is often the",
        "  only one a refusal test needs.",
        "",
        "[bold cyan]NOT CHARGED TWICE:[/bold cyan]",
        "  router_assert already owns assert handle_command(...) is True. That form",
        "  is a Compare against a constant, which this rule reads as strong, so the",
        "  two never meet.",
        "",
        "[bold cyan]CHECK FIRST (measured 2026-09-22 over 561 fleet test files):[/bold cyan]",
        "  SCORED: [green]177 files, 468 hits, 8.3s[/green]. Top three: memory 20 files,",
        "  trigger 18, ai_mail 17.",
        "  By form — D5 162, D3 143, D2 113, D4 48, D6 2, [green]D1 0[/green].",
        "  There is not one assert True in the fleet.",
        "",
        "  REPORTED, not scored: 430 files, 4,667 soft oracles.",
        "  in / not in 3,346 · plain is None 632 · len/count 428 · == {} 132 ·",
        "  bound compares 129.",
        "",
        "[bold cyan]THE E-vs-D JUDGEMENT CALL:[/bold cyan]",
        "  An assertion on a value the TEST ITSELF set up (class E's shape) does not",
        "  count as a real oracle either — but this checker does not detect it,",
        "  because that is class E's whole job and building half of E inside D would",
        "  put one finding in two places under two names. D reads a self-set assert",
        "  as strong and leaves it to E. [yellow]If E never ships, that is a known hole.[/yellow]",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per file. Every hit names the test, its line and the form, on ONE",
        "  check. A test with a scored form AND a strong assertion is not charged.",
        "",
        "[bold cyan]THE CURE:[/bold cyan]",
        "  [green]assert the effect the test's name claims.[/green]",
    ]

    json_handler.log_operation("content_served", {"standard": "weak_oracle"})
    return "\n".join(lines)
