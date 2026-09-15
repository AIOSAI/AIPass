# =================== AIPass ====================
# Name: module_eviction_content.py
# Description: Module Eviction Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-15
# Modified: 2026-09-15
# =============================================

"""
Module Eviction Standards Content Handler

Provides formatted module_eviction standards content.
Module orchestrates, handler implements.
"""


def get_module_eviction_standards() -> str:
    """Return formatted module_eviction standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  A test may evict a cached module to force a fresh import. It may",
        "  not walk away leaving the import cache holding a different object",
        "  from the one it found. Same ruling as [dim]host_state[/dim], one layer",
        "  in: [bold]touching is allowed; leaving it changed is the defect[/bold].",
        "",
        "[bold cyan]WHY IT EXISTS:[/bold cyan]",
        "  A memory helper evicted [dim]rollover[/dim] with a bare",
        "  [red]sys.modules.pop[/red] and a bare [red]delattr(parent, ...)[/red],",
        "  then re-imported it against a MagicMock cli. Teardown put the cli",
        "  back and not the module. The next in-process [dim]memory.main()[/dim]",
        "  on that xdist worker routed [dim]rollover <bogus>[/dim] through the",
        "  mock [dim]error()[/dim] and exited 0 where the contract says 2. Which",
        "  worker inherited it was loadscope ordering: CI on PR #769 flickered",
        "  red on some platforms and Pythons only.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Every function in a test file - tests, fixtures, and helpers at",
        "  module, class or nested level - read on its own scope.",
        "",
        "  [yellow]Two species:[/yellow]",
        "  - [red]SYS_MODULES_EVICTION[/red] — [dim]sys.modules.pop(K)[/dim] or",
        "    [dim]del sys.modules[K][/dim]",
        "  - [red]PACKAGE_ATTRIBUTE_EVICTION[/red] — [dim]delattr(M, 'attr')[/dim]",
        "    where M is provably a module: bound from import_module,",
        "    __import__, sys.modules[...] or sys.modules.get, or by an import",
        "",
        "[bold cyan]WHAT IS NEVER FLAGGED:[/bold cyan]",
        "  - [green]monkeypatch recorded it first[/green] — setitem/delitem on",
        "    sys.modules with the same key, or setattr/delattr with the same",
        "    object and attribute, EARLIER in the same function",
        "  - [green]patch.dict(sys.modules)[/green] as a with around the eviction",
        "    or a decorator on the function — for sys.modules evictions only;",
        "    it never restores a package attribute",
        "  - [green]an explicit restore[/green] after the eviction or in a",
        "    finally: sys.modules[K] = ..., sys.modules.update(...),",
        "    setattr(M, 'attr', ...), M.attr = ...",
        "  - [green]a fixture with any statement after its last yield[/green]",
        "  - [green]an autouse fixture in the same file records the key[/green] —",
        "    setitem/delitem on sys.modules in an autouse=True fixture, both",
        "    sides resolving to the same literal name (a string, a module-level",
        "    constant, or a for over a literal collection); cache evictions only",
        "  - [green]monkeypatch.delitem / monkeypatch.delattr[/green] — the cure",
        "",
        "[bold cyan]A RE-IMPORT IS NOT A RESTORE:[/bold cyan]",
        "  [dim]importlib.import_module(K)[/dim] after the eviction mints a new",
        "  module object and caches that. It is the pollution, not the cure.",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  Record, then evict. monkeypatch puts back whatever stood there -",
        "  the real module, or nothing:",
        "    [dim]monkeypatch.delitem(sys.modules, NAME, raising=False)[/dim]",
        "    [dim]monkeypatch.delattr(parent, 'leaf', raising=False)[/dim]",
        "  or, when the eviction must be a bare del:",
        "    [dim]monkeypatch.setitem(sys.modules, NAME, None)[/dim]",
        "    [dim]del sys.modules[NAME][/dim]",
        "",
        "[bold cyan]WHAT IT CANNOT SEE — ALL TOWARD FEWER FLAGS:[/bold cyan]",
        "  It does not follow calls, and it does not read conftest.py, so a",
        "  restore in a helper, a requested fixture or an autouse conftest",
        "  fixture is invisible - a site flagged here may already be undone",
        "  there. delattr on a name that is not provably a module is not read.",
        "  Code in a string (a child-process harness) is not read. Module-level",
        "  statements outside any function are not read.",
        "  [bold]It nominates. A human decides.[/bold]",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold]",
        "  Walks [dim]tests/[/dim] then [dim]test/[/dim]; whole tree if neither.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Functions not flagged / every function read - tests, fixtures and",
        "  helpers - one row per function however many lines it evicts.",
        "  [yellow]ADVISORY[/yellow] — reports a number, never fails a board.",
        "  A project with no tests reports [dim]not_applicable[/dim].",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: pytest_quality standards pack (module_eviction)[/dim]",
        "  [dim]Checker: module_eviction_check.py[/dim]",
        "  [dim]Incident: PR #769, memory test_rollover.py _import_rollover[/dim]",
    ]

    return "\n".join(lines)
