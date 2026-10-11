# =================== AIPass ====================
# Name: constant_predicate_content.py
# Description: Constant Predicate Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
Constant Predicate Standards Content Handler

Provides formatted Constant Predicate standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_constant_predicate_standards() -> str:
    """Return formatted constant_predicate standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (crack class C, review of @backup 2026-09-22):[/bold cyan]",
        "  A lambda whose body is a constant, handed to product code as an argument.",
        "  It cannot discriminate a product that honours the callable from one that",
        "  ignores it entirely.",
        "",
        "[bold cyan]THE SHAPE, from test_ignore_pathspec.py:491:[/bold cyan]",
        "  [red]mirror_tree(src, dst, should_ignore=lambda p: False)[/red]",
        "",
        "  mirror.py:95 never calls should_ignore. The lambda answers False for every",
        "  path, and a product that dropped the parameter passes the same test.",
        "",
        "[bold cyan]THE SPLIT IS THE JUDGEMENT, and the numbers make the case:[/bold cyan]",
        "",
        "  [red]SCORED[/red]    the body is a bool. lambda p: False is a PREDICATE, and a",
        "            predicate that returns the same answer for every input cannot",
        "            discriminate. No test using it can tell a product that consults",
        "            it from one that does not. [red]163 hits.[/red]",
        "",
        "  [green]REPORTED[/green]  the body is anything else. 309 hits, and [green]236 return None[/green] —",
        "            lambda *a: None as an on_progress or a logger. That is an inert",
        "            CALLBACK, not a predicate, and a no-op stub for a callback that",
        "            is not under test is a legitimate thing to write. The other 73",
        "            return a value the product then uses — 0, 'HEADER',",
        "            '/usr/bin/python3' — a stand-in answering a question, not a",
        "            predicate refusing to.",
        "",
        "  163 + 309 = 472, the review's own first cut to the hit. Same population;",
        "  this rule scores the third of it that cannot be right.",
        "",
        "[bold cyan]NOT RESTRICTED TO TEST BODIES:[/bold cyan]",
        "  The one place it reads wider than the brief. A constant predicate handed to",
        "  the product from a fixture or a module-level helper is the same defect",
        "  reaching the same product call. Every hit is still inside a tests/ file.",
        "",
        "[bold cyan]CHECK FIRST (2026-09-22, 565 fleet test files):[/bold cyan]",
        "  SCORED [green]38 files, 163 hits[/green] · REPORTED 309.",
        "  Evidence lands: test_ignore_pathspec.py:491, test_snapshot_fidelity.py",
        "  89, 107, 124, 149.",
        "",
        "[bold cyan]WHY IT CANNOT BE SATISFIED BY ACCIDENT:[/bold cyan]",
        "  A bool-constant lambda returns the same answer for every argument it is",
        "  ever given. Delete the product's call to it and nothing about the test",
        "  changes.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per file. Every hit names the line and the constant, on ONE check.",
        "  Inert callback stubs are counted in the passing message, never charged.",
        "",
        "[bold cyan]THE CURE:[/bold cyan]",
        "  [green]return an answer that depends on the argument, or assert the product",
        "  called it.[/green]",
    ]

    json_handler.log_operation("content_served", {"standard": "constant_predicate"})
    return "\n".join(lines)
