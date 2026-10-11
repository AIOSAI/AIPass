# =================== AIPass ====================
# Name: clear_text_secret_logging_content.py
# Description: Clear Text Secret Logging Standards Content Handler
# Version: 1.0.0
# Created: 2026-10-10
# Modified: 2026-10-10
# =============================================

"""
Clear Text Secret Logging Standards Content Handler

Provides formatted Clear Text Secret Logging standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_clear_text_secret_logging_standards() -> str:
    """Return formatted clear_text_secret_logging standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]WHERE IT CAME FROM (PR #774 round seven, CodeQL HIGH):[/bold cyan]",
        "  py/clear-text-logging-sensitive-data on prax logger.py:135, SystemLogger.warning - the",
        "  fleet's one log sink. CodeQL names the sink; the leak is the CALLER that hands it a",
        "  value named, or built from a name, that says secret. This rule convicts the caller line.",
        "",
        "[bold cyan]THE SHAPE:[/bold cyan]",
        "  A prax logger call ([green]logger.debug/info/warning/error/critical/exception[/green], or an",
        "  alias imported from aipass.prax) whose message - a positional argument, an f-string",
        "  piece, a % operand, a .format() argument or a + operand - is:",
        "  [red]1. named as a secret[/red]: a Name, Attribute or Call whose identifier holds, as a whole",
        "     segment, secret(s), token(s), password(s), passwd, api_key, apikey, credential(s),",
        "     bearer, auth_header, access_key or private_key;",
        "  [red]2. built in this file from a secret-named source[/red]. It STARTS only from a module-level",
        "     binding ([yellow]SECRETS_BASE = ...[/yellow]) or an attribute read",
        "     ([yellow]secrets_store.SECRETS_BASE[/yellow], [yellow]self.api_key[/yellow]) - never a parameter,",
        "     loop or with target, local, or secret-named call.",
        "     From there it FOLLOWS assignments, same-file returns and parameters, and attributes",
        "     ([yellow]target.parent[/yellow]). Why: a parameter or loop var called token is a shell word or a",
        "     counter as often as a credential; arm 1 judges its name wherever it is logged. A",
        "     module binding or attribute is where a file names its secret store - CodeQL's source too.",
        "",
        "[bold cyan]NOT A ROW:[/bold cyan]",
        "  An identifier of a secret: a segment beside the word says what it is - token_id,",
        "  token_count, token_store, secret_path, secret_name, n_tokens, TOKEN_SLUG.",
        "  A redaction: a call named redact/mask/scrub, len(), a slice showing at most 4 characters",
        "  ([green][-4:][/green]). [yellow]token[:10][/yellow] still shows the secret and stays a row.",
        "  The word in a string constant; print() and other receivers; flow through another file.",
        "",
        "[bold cyan]WHY NAMES RULE:[/bold cyan]",
        "  A scanner and a stranger both read the name. A name that says secret on a log line is a",
        "  leak in the reader's eyes even when the value is benign - so the cure for a false hit is",
        "  [green]the rename[/green], and the rename is a cure, not a dodge.",
        "",
        "[bold cyan]FLEET (2026-10-10, 1,301 product files in apps/ and lib/):[/bold cyan]",
        "  [red]16 rows in 8 files[/red], 4 branches: api 7 (arm 2), drone 1, hooks 7, skills lib 1 (arm 1)",
        "  (skills/lib is outside the audit corpus, so api, drone and hooks score under 100).",
        "  The CodeQL flows are among api's: host/tokens.py :324 :370 :438 and auth/secrets.py",
        "  :62 :187 :216, every one built from SECRETS_BASE.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per file: 0 on any row, else 100. Every row on ONE check.",
        "",
        "[bold cyan]THE CURE:[/bold cyan]",
        "  [green]A real secret: log the field's name, its len() or its last four characters, or[/green]",
        "  [green]redact()/mask() it, or leave it out of the line. No secret: rename it.[/green]",
    ]

    json_handler.log_operation("content_served", {"standard": "clear_text_secret_logging"})
    return "\n".join(lines)
