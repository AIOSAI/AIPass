# =================== AIPass ====================
# Name: exception_text_in_response_content.py
# Description: Exception Text In Response Standards Content Handler
# Version: 1.0.0
# Created: 2026-10-10
# Modified: 2026-10-10
# =============================================

"""
Exception Text In Response Standards Content Handler

Provides formatted Exception Text In Response standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_exception_text_in_response_standards() -> str:
    """Return formatted exception_text_in_response standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  An exception's text is written for the operator: paths, module names, argv, state.",
        "  A web server that copies it into a response body hands all of that to whoever sent",
        "  the request. CodeQL py/stack-trace-exposure, PR #774 round seven (head 38166f35).",
        "",
        "[bold cyan]WHAT IT READS (product code that builds responses):[/bold cyan]",
        "  In scope: a module that imports [green]fastapi[/green] or [green]starlette[/green], or defines a route",
        '  (a decorator x.get/post/put/delete/patch/head/options/route/api_route/websocket("/...")).',
        "  Any other file is NOT APPLICABLE (declined, out of the average).",
        "",
        "  Inside an except clause, the TEXT is: the bound name (except X as e), any attribute or",
        "  subscript of it (e.detail, e.args[0]), any call taking it (str(e), repr(e), a helper),",
        "  an f-string, % or + carrying it, a local assigned from those earlier in the clause, and",
        "  traceback.format_exc() / format_exception() / format_exception_only() / format_tb().",
        "",
        "  The RESPONSE is: HTTPException(detail=...) or its second positional; JSONResponse /",
        "  PlainTextResponse / HTMLResponse / Response content; a helper named deny, refuse,",
        "  error_response or respond (leading underscores ignored) taking the text anywhere; or a",
        "  return of the text, or of a dict, list or tuple holding it. The row is the sink's line.",
        "",
        "[bold cyan]NOT A ROW:[/bold cyan]",
        "  Text that goes only to a logger call. type(e).__name__ / isinstance(e, ...): a class",
        "  name is the fixed typed message. raise Other(str(e)) from e: not a response; the clause",
        "  that turns it into one is judged. A local re-assigned to a fixed value before use.",
        "",
        "[bold cyan]WHAT IT CANNOT SEE:[/bold cyan]",
        "  CodeQL's own three rows (@api server.py 848, 974, 995) are the routes' return",
        "  expressions; the text arrives from @skills' doors through api's ReadCache.get(key,",
        "  producer). A cross-file, cross-branch flow through a callable is past a file-local rule.",
        "",
        "[bold cyan]THE WIDENING, HELD (2026-10-10, devpulse steer bb431525):[/bold cyan]",
        "  Any returned/published value as a sink, past web modules, over apps/ lib/ shared/:",
        "  494 rows (471 without the same-file helper hop); it does convict the six skills lines",
        "  CodeQL's flows came from. But 'served to a client' is not in the returning file:",
        "  @skills' doors are served because @api imports them, @drone's git messages because api",
        "  relays their --json through a subprocess, and the same return elsewhere goes to a CLI.",
        "  No decorator, registry or door shape marks it, so the rule keeps the web-module scope.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per file: 0 on any row, else 100. Every row on ONE check.",
        "",
        "[bold cyan]THE CURE:[/bold cyan]",
        "  [green]Log the detail with exc_info, return a fixed typed message[/green] and, if traceability",
        "  is wanted, a correlation id that also appears in the log line.",
    ]

    json_handler.log_operation("content_served", {"standard": "exception_text_in_response"})
    return "\n".join(lines)
