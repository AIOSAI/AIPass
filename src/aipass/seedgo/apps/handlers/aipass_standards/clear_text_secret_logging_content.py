# =================== AIPass ====================
# Name: clear_text_secret_logging_content.py
# Description: Clear Text Secret Logging Standards Content Handler
# Version: 1.1.0
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
        "     bearer, auth_header, access_key, private_key, trusted or confidential (untrusted is not);",
        "  [red]2. built in this file from a secret-named source[/red]. It STARTS only from a module-level",
        "     binding ([yellow]SECRETS_BASE = ...[/yellow]), an attribute read",
        "     ([yellow]secrets_store.SECRETS_BASE[/yellow], [yellow]self.api_key[/yellow]) - a token word seeds",
        "     neither - or the RESULT of a call named by CodeQL's source words: secret(s), trusted,",
        "     confidential ([yellow]secret = _get_secret(bot_id)[/yellow]), unless the name also holds hash,",
        "     md5, sha, random, encode, encrypt, public, user, login, logging, clear or redact, or a setter",
        "     verb (set/write/save/put/delete/remove/drop/rotate/revoke: it returns a status). Never a",
        "     parameter, loop or with target, or local.",
        "     From there it FOLLOWS assignments, comprehensions over a built value, the wrappers",
        "     sorted/list/tuple/set/dict/str/repr/join/format/f-strings, same-file returns and parameters,",
        "     attributes ([yellow]target.parent[/yellow]) and [red]the same-file hop[/red]: a built argument to a",
        "     function defined here taints that call's result when the parameter reaches its return",
        "     ([yellow]strays = non_secret_keys(secret)[/yellow]). Per call: a clean argument stays clean. A",
        "     non_/not_ prefix acquits nothing. Why so narrow: a parameter or loop var called token is a",
        "     shell word as often as a credential (and token_hex, issue_token return no secret); arm 1",
        "     judges its name wherever it is logged.",
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
        "  Round nine (1.1.0): CodeQL's next row was @skills telegram config.py load_bot_config,",
        "  strays from _get_secret through non_secret_keys - the call seed and the hop convict it.",
        "  Fleet after: 0 rows (the line was already cured); the narrowings each dropped a false row.",
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
