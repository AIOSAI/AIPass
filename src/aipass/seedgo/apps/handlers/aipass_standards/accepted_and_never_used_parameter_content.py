# =================== AIPass ====================
# Name: accepted_and_never_used_parameter_content.py
# Description: Accepted And Never Used Parameter Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-23
# Modified: 2026-09-23
# =============================================

"""
Accepted And Never Used Parameter Standards Content Handler

Provides formatted Accepted And Never Used Parameter standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_accepted_and_never_used_parameter_standards() -> str:
    """Return formatted accepted_and_never_used_parameter content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (crack class M, review of @backup 2026-09-22):[/bold cyan]",
        "  A product function accepts a parameter and no path in its body ever",
        "  reads it. The caller computes a value, hands it over, and it goes",
        "  nowhere.",
        "",
        "[bold cyan]THE SPECIMEN, backup/apps/handlers/cleanup/mirror.py:92:[/bold cyan]",
        "  [red]def cleanup_deleted_files(backup_path, source_dir, should_ignore, result, ...):[/red]",
        "  [red]      should_ignore: Callable(Path) -> bool for ignore check.[/red]",
        "",
        "  should_ignore is documented, accepted, and never called. At the other",
        "  end, copy/snapshot.py:93 builds a lambda to pass in. [red]Those are not two",
        "  defects, they are one[/red]: the caller builds a predicate, the callee drops",
        "  it, and the mirror cleanup ignores nothing. The verdict lands on the",
        "  ACCEPTING side, which is where the cure lives.",
        "",
        "[bold cyan]WHAT IT IS NOT:[/bold cyan]",
        "  Not tidiness. A dropped parameter is a promise in the signature that",
        "  the body does not keep, so every caller reasons about behaviour that",
        "  never happens. The docstring above is the proof — it describes a",
        "  contract the function never honours.",
        "",
        "[bold cyan]HOW YOU TELL A PROTOCOL — four shapes, all saying[/bold cyan]",
        "[bold cyan]'somebody else owns this signature':[/bold cyan]",
        "  [green]THE BRANCH NEVER CALLS IT.[/green] pytest_runtest_logfinish(nodeid, location)",
        "  is dictated by pytest's hookspec; handle_stop(hook_data) is dispatched",
        "  by the bridge under its name. Nothing in the branch calls either, so",
        "  nothing in the branch may narrow them. Whether such a function should",
        "  exist at all is unused_function's verdict, not this one's.",
        "",
        "  [green]THE NAME IS HANDED OFF AS A VALUE.[/green] A bare mention — not a call, not",
        "  its own def line, [yellow]and not an import[/yellow] — means the function was passed to",
        "  something that will call it: signal.signal(SIGINT, handler), a dispatch",
        "  table. The consumer fixed the arity.",
        "",
        "  [green]IT IS A FALLBACK FOR AN IMPORT THAT FAILED.[/green] A def inside an",
        "  except ImportError handler stands in for the real module and must match",
        "  it. @trigger's registry_should_dispatch(fingerprint) returns True",
        "  without reading fingerprint because that is what a no-op shim does.",
        "",
        "  [green]THE NAME IS DEFINED MORE THAN ONCE IN THE BRANCH.[/green] Two defs of one name",
        "  are a shared shape with two implementations; one may legitimately",
        "  ignore what the other needs.",
        "",
        "[bold cyan]ORDINARY EXEMPTIONS:[/bold cyan]",
        "  self and cls · *args and **kwargs (never named, so never judged) ·",
        "  dunders · a decorated function (the decorator may read the signature) ·",
        "  a stub body (pass, ..., raise NotImplementedError) · any parameter whose",
        "  name starts with _, which is Python's own way of writing 'accepted and",
        "  deliberately ignored'.",
        "",
        "[bold cyan]THE CORPUS IS CODE, NOT PROSE:[/bold cyan]",
        "  Strings and comments are blanked before the branch is counted. This very",
        "  checker's docstring names pytest_runtest_logfinish, and that one sentence",
        "  made the branch look like it called pytest's hook — [red]convicting both of its",
        "  parameters[/red] until the corpus was stripped.",
        "",
        "[bold cyan]FLEET STANDING ON ARRIVAL (2026-09-23, 1,203 product files, 18 branches):[/bold cyan]",
        "  [yellow]38 files, 49 hits, 10.4s. 2,841 parameters acquitted by a shape above.[/yellow]",
        "  The review's first cut said 83 files and 157 hits; the gap is protocol",
        "  shapes, not tuning.",
        "",
        "[bold cyan]WHY IT CANNOT BE SATISFIED BY ACCIDENT:[/bold cyan]",
        "  Reading the parameter once anywhere in the body clears it, and that",
        "  reading is the whole point. There is no threshold and nothing to tune.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per file. Every hit names the line, the function and the",
        "  parameter, on ONE check.",
        "",
        "[bold cyan]THE CURE:[/bold cyan]",
        "  [green]read the parameter, forward it, or drop it from the signature.[/green]",
    ]

    json_handler.log_operation("content_served", {"standard": "accepted_and_never_used_parameter"})
    return "\n".join(lines)
