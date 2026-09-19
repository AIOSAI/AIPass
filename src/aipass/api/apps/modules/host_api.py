# =================== AIPass ====================
# Name: host_api.py
# Description: Host API Module — server lifecycle and token administration
# Version: 1.2.0
# Created: 2026-08-14
# Modified: 2026-09-14
# =============================================

"""
Host API Module

Orchestration and CLI for the Stage 0 host API (FPLAN-0411) — the server the
BAUD phone face talks to. This module routes; the handlers under
apps/handlers/host/ implement.

Per FPLAN-0411's D0 line, this branch owns the pipe and never the meaning: the
server carries transport, auth and protocol, and every future read or verb is a
pass-through to the branch that owns the data or the machinery.

The loopback gate has been open since 2026-08-14, the owner's ruling on the Phase 5
security review: the server binds one address this machine holds, never a
wildcard. What the help says about it is read from LOOPBACK_ONLY, not written here.

Commands (via drone @api):
    host-api serve [--host H] [--port P]        Run the server
    host-api issue-token <label> [--scope S] [--out FILE]
    host-api list-tokens                        Show tokens (never the values)
    host-api revoke-token <id>                  Revoke, effective next request
    host-api config                             Show the effective config
    host-api set-config [--host H] [--port P] [--face-dir DIR|default] [--baud-bin PATH|default]

config and set-config live in host_config_cli.py, serve/status/stop/autostart in
host_serve.py; this module offers them every call and owns the tokens.
"""

import os
import sys

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from datetime import datetime
from pathlib import Path
from typing import List, Optional

from aipass.cli.apps.modules import console, header, success, error, warning
from aipass.api.apps.handlers.json import json_handler
from aipass.prax import logger  # noqa: F401
from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.modules import host_config_cli
from aipass.api.apps.modules import host_serve
from aipass.api.apps.handlers.host import tokens as host_tokens

HELP_FLAGS = ("--help", "-h", "help")


# =============================================
# MODULE INTROSPECTION
# =============================================


def print_introspection() -> None:
    """Show module introspection — connected handlers and capabilities."""
    console.print()
    header("Host API Module Introspection")
    console.print()

    console.print("[cyan]Purpose:[/cyan] Stage 0 host API for the BAUD phone face")
    console.print()

    console.print("[cyan]Connected Handlers:[/cyan]")
    console.print("  - api.apps.handlers.host.config")
    console.print("  - api.apps.handlers.host.tokens")
    console.print("  - api.apps.handlers.host.server")
    console.print()

    console.print("[cyan]Available Workflows:[/cyan]")
    console.print("  - serve()          - Validate the bind, then run the server")
    console.print("  - issue_token()    - Mint a bearer token for a device")
    console.print("  - revoke_token()   - Revoke server-side, next request")
    console.print()

    available = host_server.is_available()
    status = "[green]installed[/green]" if available else "[red]missing[/red]"
    console.print(f"[cyan]Server Libraries:[/cyan] {status}")

    config = host_config.load_config()
    console.print(f"[cyan]Bind:[/cyan] {config['host']}:{config['port']}")

    if host_config.LOOPBACK_ONLY:
        gate = "[yellow]loopback only (Phase 5 review pending)[/yellow]"
    else:
        gate = "[green]open[/green]"
    console.print(f"[cyan]Bind Gate:[/cyan] {gate}")

    console.print(f"[cyan]Tokens:[/cyan] {len(host_tokens.list_tokens())} issued")
    console.print()


def print_help() -> None:
    """Print drone-compliant help output with Rich markup"""
    console.print()
    console.print("[bold cyan]HOST_API — Stage 0 host API for the BAUD phone face[/bold cyan]")
    console.print()
    console.print("[yellow]COMMANDS:[/yellow]  [dim](via drone @api)[/dim]")
    console.print("  [cyan]host-api serve[/cyan]                 [dim]Run the server on the configured bind[/dim]")
    console.print(
        "  [cyan]host-api status[/cyan]                [dim]Is a server running, who holds it, and where[/dim]"
    )
    console.print("  [cyan]host-api stop[/cyan]                  [dim]Stop it, through whoever owns it[/dim]")
    console.print("  [cyan]host-api autostart[/cyan]             [dim]Render the boot unit + the install steps[/dim]")
    console.print("  [cyan]host-api issue-token <label>[/cyan]   [dim]Mint a bearer token for a device[/dim]")
    console.print("  [cyan]host-api list-tokens[/cyan]           [dim]List tokens — values are never shown[/dim]")
    console.print("  [cyan]host-api revoke-token <id>[/cyan]     [dim]Revoke, effective on the next request[/dim]")
    console.print("  [cyan]host-api config[/cyan]                [dim]Show the effective server config[/dim]")
    console.print(
        "  [cyan]host-api set-config[/cyan]            [dim]Set bind, face dir or baud binary (validated first)[/dim]"
    )
    console.print()
    console.print("[yellow]OPTIONS:[/yellow]")
    console.print("  [cyan]--host <ip>[/cyan]      [dim]Bind address override (literal IP, never a hostname)[/dim]")
    console.print("  [cyan]--port <n>[/cyan]       [dim]Port override[/dim]")
    console.print("  [cyan]--face-dir <dir>[/cyan] [dim]set-config: the phone face's built bundle, absolute[/dim]")
    console.print("  [dim]                'default' clears it back to the checkout build; restart to serve[/dim]")
    console.print("  [cyan]--baud-bin <path>[/cyan] [dim]set-config: the binary the fleet lanes exec, absolute[/dim]")
    console.print("  [dim]                'default' clears it back to the automatic lookup; no restart[/dim]")
    console.print("  [cyan]--detach[/cyan]         [dim]serve: run in its own session, output to a log file[/dim]")
    console.print("  [dim]                a serve under drone dies on drone's exec timeout[/dim]")
    console.print("  [dim]                and a detached one dies with the machine — see autostart[/dim]")
    console.print("  [cyan]--scope <s>[/cyan]      [dim]Token scope: read or operate (default: read)[/dim]")
    console.print("  [cyan]--out <file>[/cyan]     [dim]Override where the 0600 receipt lands[/dim]")
    console.print("  [dim]                default: ~/.secrets/aipass/host_api/<label>.token[/dim]")
    console.print()
    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [dim]# Enroll a phone, then start the server[/dim]")
    console.print("  [cyan]drone @api host-api issue-token pixel-8 --scope read[/cyan]")
    console.print("  [cyan]drone @api host-api serve[/cyan]")
    console.print()
    console.print("  [dim]# Lost phone — revoke it, no restart needed[/dim]")
    console.print("  [cyan]drone @api host-api list-tokens[/cyan]")
    console.print("  [cyan]drone @api host-api revoke-token a1b2c3d4e5f6[/cyan]")
    console.print()
    console.print("  [dim]# Check what the server would bind, and which face it would serve[/dim]")
    console.print("  [cyan]drone @api host-api config[/cyan]")
    console.print()
    console.print("  [dim]# Serve an installed phone face instead of the checkout build[/dim]")
    console.print("  [cyan]drone @api host-api set-config --face-dir <dir>[/cyan]")
    console.print()
    console.print("  [dim]# Exec a headless baud-cli for the fleet lanes, from the next request[/dim]")
    console.print("  [cyan]drone @api host-api set-config --baud-bin <path>[/cyan]")
    console.print()
    console.print("  [dim]# A server that outlives the shell that started it[/dim]")
    console.print("  [cyan]drone @api host-api serve --detach[/cyan]")
    console.print("  [cyan]drone @api host-api status[/cyan]")
    console.print()
    console.print("[yellow]SECURITY:[/yellow]")
    console.print("  [dim]Raw token values are never printed — they land in a 0600 receipt file.[/dim]")
    console.print("  [dim]An existing receipt is never overwritten: its token is still live.[/dim]")
    console.print("  [dim]Bind refuses wildcards, hostnames, and addresses this machine lacks.[/dim]")
    # Read from the flag, never written down: the sentence that said loopback-only
    # outlived the gate by a month (found by @baud, 2026-09-13).
    if host_config.LOOPBACK_ONLY:
        console.print("  [dim]Loopback-only: every non-loopback bind is refused.[/dim]")
    else:
        console.print("  [dim]Non-loopback binds are open since the 2026-08-14 security review.[/dim]")
    console.print("  [dim]--detach validates the bind BEFORE spawning — a refusal never reaches a child.[/dim]")
    console.print()


# =============================================
# CROSS-BRANCH API
# =============================================


def issue_token(label: str, scope: str = "read"):
    """Mint a bearer token. Returns (record, raw_value); the raw is never stored."""
    return host_tokens.issue_token(label, scope)


def revoke_token(token_id: str) -> bool:
    """Revoke a token by id. Effective on the next request, no restart."""
    return host_tokens.revoke_token(token_id)


def serve(host: Optional[str] = None, port: Optional[int] = None) -> None:
    """Validate the configured bind address, then run the server."""
    host_server.serve(host=host, port=port)


# The door for other branches' in-process calls (@aipass's installer), so none
# reaches into handlers/host/config.py. Same functions, same refusals.
FaceDirRefused = host_config.FaceDirRefused
BaudBinRefused = host_config.BaudBinRefused


def load_config() -> dict:
    """The effective host config: defaults merged under the stored values."""
    return host_config.load_config()


def face_dir() -> Optional[Path]:
    """The configured phone-face directory, or None: the checkout build serves."""
    return host_config.face_dir()


def set_face_dir(path: Optional[Path]) -> Optional[Path]:
    """Validate and store the face dir, or clear it with None. Raises FaceDirRefused."""
    return host_config.set_face_dir(path)


def baud_bin() -> Optional[Path]:
    """The configured baud binary, or None: the automatic lookup answers."""
    return host_config.baud_bin()


def set_baud_bin(path: Optional[Path]) -> Optional[Path]:
    """Validate and store the baud binary, or clear it with None. Raises BaudBinRefused."""
    return host_config.set_baud_bin(path)


# =============================================
# COMMAND HANDLING (drone @api host-api ...)
# =============================================


def handle_command(command: str, args: List[str]) -> bool:
    """Handle host API commands routed via drone.

    Args:
        command: Command name — this module owns "host-api".
        args: Command arguments, e.g. ["serve", "--host", "127.0.0.1"].

    Returns:
        True if command was handled, False to pass through.
    """
    # Both spellings answer. `drone @api` bare lists MODULE names, so it
    # advertises "host_api" while the command is "host-api" — @baud read the
    # self-map, typed what it said, and reported themselves blocked over one
    # character. A surface that publishes a spelling which does not work is the
    # surface's bug. Spelled literally so a checker can see the match too.
    mine = command in ("host-api", "host_api")

    # NO-ARGS GATE (seedgo standard)
    if not args:
        if mine:
            print_introspection()
            return True
        return False

    if not mine:
        return False

    # HELP GATE — a help flag ANYWHERE means "explain", never "run". Checking
    # only args[0] is what let `cleanup 30 --help` run a real cleanup (S58) and
    # `get-key <provider> --help` disclose key material (S59). Never again, and
    # never only at the router: this module's __main__ reaches here directly.
    # Flags spelled literally so a static checker can see the intercept too.
    if any(arg in ("--help", "-h", "help") for arg in args):
        print_help()
        return True

    subcommand = args[0]
    rest = args[1:]

    # Offered to host_serve FIRST — it owns serve/status/stop and declines
    # everything else, so an unknown subcommand still reaches the error below
    # rather than disappearing into a silent True.
    if host_serve.handle_command(command, args):
        return True
    if host_config_cli.handle_command(command, args):
        return True

    if subcommand == "issue-token":
        _cmd_issue_token(rest)
        return True
    if subcommand == "list-tokens":
        _cmd_list_tokens()
        return True
    if subcommand == "revoke-token":
        _cmd_revoke_token(rest)
        return True

    error(
        f"Unknown host-api subcommand: {subcommand}",
        suggestion="Run 'drone @api host-api --help' for available subcommands",
    )
    return True


# =============================================
# CLI COMMAND IMPLEMENTATIONS
# =============================================


def _cmd_issue_token(args: List[str]) -> None:
    """Mint a token for a device, writing the raw value to a 0600 file."""
    header("Issue Host API Token")
    console.print()

    positional = [arg for arg in args if not arg.startswith("-")]
    flag_values = {host_serve.flag_value(args, "--scope"), host_serve.flag_value(args, "--out")}
    label_candidates = [value for value in positional if value not in flag_values]

    if not label_candidates:
        error(
            "Token label required",
            suggestion="drone @api host-api issue-token <label> [--scope read|operate]",
        )
        return

    label = label_candidates[0]
    scope = host_serve.flag_value(args, "--scope") or "read"
    out_path = host_serve.flag_value(args, "--out")

    # --out IS OPTIONAL NOW, and S49 is untouched by that: the rule was never
    # "make the caller name a file", it was "never print the raw value". A
    # default that lands in the secrets directory honours it better than a
    # required flag whose own example pointed at the home root — which is how
    # three raw receipts came to be sitting in ~ (found 2026-08-19).
    try:
        target = Path(os.path.expanduser(out_path)) if out_path else host_tokens.receipt_path(label)
    except host_tokens.TokenError as e:
        logger.warning("[host_api] token receipt path refused: %s", e)
        error(str(e))
        return

    # BEFORE minting, not after: a token that exists in the store with no
    # readable receipt is a live credential nobody holds. Checked here so the
    # refusal costs nothing, and again by O_EXCL below so the check is not
    # merely check-then-act.
    if target.exists():
        error(
            f"A receipt already exists at {target}",
            suggestion=(
                "Refusing to overwrite it — the token it holds is still LIVE in the store, and truncating the "
                "file would leave a credential nobody can read and nobody thought to revoke. Move or delete "
                "that file, or revoke its token first: drone @api host-api list-tokens"
            ),
        )
        return

    try:
        host_tokens.prepare_receipt_dir(target)
    except OSError as e:
        logger.error("[host_api] could not prepare the receipt directory %s: %s", target.parent, e)
        error(f"Could not prepare {target.parent}: {e}")
        return

    try:
        record, raw = host_tokens.issue_token(label, scope)
    except host_tokens.TokenError as e:
        logger.warning("[host_api] token issuance refused: %s", e)
        error(str(e))
        return

    try:
        # O_EXCL, not O_TRUNC: the existence check above is a good sentence, this
        # is the guarantee. Between the two, another process could have created
        # the file — and silently truncating whatever it wrote is the data loss
        # the check exists to prevent.
        fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, raw.encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as e:
        # The token is already in the store. Say so — a caller who thinks the
        # write failed cleanly would issue a second one and leave a live orphan.
        logger.error("[host_api] token %s issued but its file write failed: %s", record["id"], e)
        # The handler logged the issuance; only this module knows the receipt never landed.
        json_handler.log_operation("host_api_token_receipt_unwritten", {"id": record["id"], "error": str(e)})
        error(
            f"Token was issued but could not be written to {target}: {e}",
            suggestion=f"Revoke it: drone @api host-api revoke-token {record['id']}",
        )
        return

    success(f"Token issued: {record['label']}")
    console.print(f"  [cyan]id:[/cyan]    {record['id']}")
    console.print(f"  [cyan]scope:[/cyan] {record['scope']}")
    console.print(f"  [cyan]file:[/cyan]  {target} [dim](0600)[/dim]")
    console.print()
    console.print("[dim]The raw value is not stored and cannot be shown again.[/dim]")
    console.print()


def _cmd_list_tokens() -> None:
    """List token records — never the values."""
    header("Host API Tokens")
    console.print()

    records = host_tokens.list_tokens()
    if not records:
        warning("No tokens issued")
        console.print()
        console.print("[dim]Issue one: drone @api host-api issue-token <label>[/dim]")
        return

    for record in records:
        state = "[red]revoked[/red]" if record["revoked"] else "[green]active[/green]"
        console.print(f"  [cyan]{record['id']}[/cyan]  {record['label']}  [dim]{record['scope']}[/dim]  {state}")
        console.print(f"                [dim]{_provenance(record)}[/dim]")
    console.print()


def _provenance(record: dict) -> str:
    """
    The one line that answers who minted a token, whether it is live, and when
    it died.

    Written because the store learning it three fields would have changed
    nothing on its own: an operate token appeared on this system and the honest
    answer to "who minted this" was that nobody had recorded it. Provenance
    nobody can read at the place they actually look is provenance that does not
    exist — so the listing carries it, not just the JSON.

    Args:
        record: A row from list_tokens().

    Returns:
        A single dim line for beneath the record.
    """
    parts = [f"minted by {record.get('minted_by') or host_tokens.UNKNOWN_MINTER}"]

    # 'never used' rather than a blank: a token minted an hour ago that has
    # never been presented is a different situation from a live one, and the
    # difference is the whole reason the field exists.
    parts.append(f"last used {_stamp(record.get('last_used'))}" if record.get("last_used") else "never used")

    if record.get("revoked_at"):
        parts.append(f"revoked {_stamp(record.get('revoked_at'))}")

    return " · ".join(parts)


def _stamp(value: object) -> str:
    """
    Render a stored ISO timestamp for a human, without inventing precision.

    Args:
        value: An ISO timestamp string, or anything else.

    Returns:
        'YYYY-MM-DD HH:MM', or the raw value if it will not parse — never an
        empty string, because a stamp that renders as nothing reads as absent.
    """
    text = str(value or "")
    try:
        return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M")
    except ValueError as e:
        # Shown raw rather than swallowed: the only way a stored stamp fails to
        # parse is a hand-edited store or a shape change nobody migrated, and
        # the operator reading this listing is exactly who should see it.
        logger.warning("[host_api] unreadable timestamp %r in the token store: %s", text, e)
        return text


def _cmd_revoke_token(args: List[str]) -> None:
    """Revoke a token by id."""
    header("Revoke Host API Token")
    console.print()

    if not args:
        error("Token id required", suggestion="drone @api host-api revoke-token <id>")
        return

    token_id = args[0]
    if host_tokens.revoke_token(token_id):
        success(f"Token {token_id} revoked")
        console.print("[dim]Effective on the next request — no restart needed.[/dim]")
    else:
        # A refusal, not a note: nothing was revoked, so an operator scripting
        # `revoke-token <id> && <next>` must not proceed believing the device
        # is off. error() names the id and carries the failure to the exit
        # seam, the same channel its sibling refusal above already uses.
        error(f"No active token with id: {token_id}")
    console.print()


# =============================================
# STANDALONE EXECUTION
# =============================================

if __name__ == "__main__":
    cli_args = sys.argv[1:]

    if len(cli_args) == 0:
        print_introspection()
        sys.exit(0)

    # Both dashed spellings, ANY position — the standalone path bypasses the
    # router, so it needs the same gate the router has (seedgo help_flag_safety).
    if any(arg in HELP_FLAGS for arg in cli_args):
        print_help()
        sys.exit(0)

    if handle_command("host-api", cli_args):
        sys.exit(0)
    else:
        error("Unknown command", suggestion="Run 'drone @api host-api --help' for available commands")
        sys.exit(1)
