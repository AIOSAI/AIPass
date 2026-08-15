# =================== AIPass ====================
# Name: host_api.py
# Description: Host API Module — server lifecycle and token administration
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-08-14
# =============================================

"""
Host API Module

Orchestration and CLI for the Stage 0 host API (FPLAN-0411) — the server the
BAUD phone face talks to. This module routes; the handlers under
apps/handlers/host/ implement.

Per FPLAN-0411's D0 line, this branch owns the pipe and never the meaning: the
server carries transport, auth and protocol, and every future read or verb is a
pass-through to the branch that owns the data or the machinery.

PHASE 1 ONLY. Serving is loopback-gated until the security review (Phase 5) —
this would be the first network-listening service in AIPass.

Commands (via drone @api):
    host-api serve [--host H] [--port P]        Run the server
    host-api issue-token <label> [--scope S] --out FILE
    host-api list-tokens                        Show tokens (never the values)
    host-api revoke-token <id>                  Revoke, effective next request
    host-api config                             Show the effective config
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
from typing import List, Optional

from aipass.cli.apps.modules import console, header, success, error, warning
from aipass.api.apps.handlers.json import json_handler
from aipass.prax import logger  # noqa: F401
from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host import server as host_server
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
    console.print("  [cyan]host-api serve[/cyan]                 [dim]Run the server (loopback only in Phase 1)[/dim]")
    console.print("  [cyan]host-api issue-token <label>[/cyan]   [dim]Mint a bearer token for a device[/dim]")
    console.print("  [cyan]host-api list-tokens[/cyan]           [dim]List tokens — values are never shown[/dim]")
    console.print("  [cyan]host-api revoke-token <id>[/cyan]     [dim]Revoke, effective on the next request[/dim]")
    console.print("  [cyan]host-api config[/cyan]                [dim]Show the effective server config[/dim]")
    console.print("  [cyan]host-api set-config[/cyan]            [dim]Set the bind address (validated first)[/dim]")
    console.print()
    console.print("[yellow]OPTIONS:[/yellow]")
    console.print("  [cyan]--host <ip>[/cyan]      [dim]Bind address override (literal IP, never a hostname)[/dim]")
    console.print("  [cyan]--port <n>[/cyan]       [dim]Port override[/dim]")
    console.print("  [cyan]--scope <s>[/cyan]      [dim]Token scope: read or operate (default: read)[/dim]")
    console.print("  [cyan]--out <file>[/cyan]     [dim]Write the raw token to a 0600 file[/dim]")
    console.print()
    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [dim]# Enroll a phone, then start the server[/dim]")
    console.print("  [cyan]drone @api host-api issue-token pixel-8 --scope read --out ~/pixel.token[/cyan]")
    console.print("  [cyan]drone @api host-api serve[/cyan]")
    console.print()
    console.print("  [dim]# Lost phone — revoke it, no restart needed[/dim]")
    console.print("  [cyan]drone @api host-api list-tokens[/cyan]")
    console.print("  [cyan]drone @api host-api revoke-token a1b2c3d4e5f6[/cyan]")
    console.print()
    console.print("  [dim]# Check what the server would bind[/dim]")
    console.print("  [cyan]drone @api host-api config[/cyan]")
    console.print()
    console.print("[yellow]SECURITY:[/yellow]")
    console.print("  [dim]Raw token values are never printed — use --out (0600 file).[/dim]")
    console.print("  [dim]Bind refuses wildcards, hostnames, and addresses this machine lacks.[/dim]")
    console.print("  [dim]Phase 1 is loopback-only, pending the security review gate.[/dim]")
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

    if subcommand == "serve":
        _cmd_serve(rest)
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
    if subcommand == "config":
        _cmd_config()
        return True
    if subcommand == "set-config":
        _cmd_set_config(rest)
        return True

    error(
        f"Unknown host-api subcommand: {subcommand}",
        suggestion="Run 'drone @api host-api --help' for available subcommands",
    )
    return True


# =============================================
# CLI COMMAND IMPLEMENTATIONS
# =============================================


def _cmd_serve(args: List[str]) -> None:
    """Run the server after the bind gate clears."""
    header("Host API Server")
    console.print()

    if not host_server.is_available():
        error(
            "Server libraries not installed",
            suggestion=host_server.INSTALL_HINT,
        )
        return

    host = _flag_value(args, "--host")
    port_raw = _flag_value(args, "--port")

    port = None
    if port_raw is not None:
        try:
            port = int(port_raw)
        except ValueError:
            logger.warning("[host_api] non-numeric port rejected: %s", port_raw)
            error(f"Port must be a number, got: {port_raw}")
            return

    try:
        host_server.serve(host=host, port=port)
    except host_config.BindRefused as e:
        # The whole point of D1: refuse, explain, and do not start.
        logger.error("[host_api] bind refused, server not started: %s", e)
        error("Bind refused — server not started", suggestion=str(e))
        json_handler.log_operation("host_api_bind_refused", {"reason": str(e)})
    except RuntimeError as e:
        logger.error("[host_api] server could not start: %s", e)
        error(str(e))


def _cmd_issue_token(args: List[str]) -> None:
    """Mint a token for a device, writing the raw value to a 0600 file."""
    header("Issue Host API Token")
    console.print()

    positional = [arg for arg in args if not arg.startswith("-")]
    flag_values = {_flag_value(args, "--scope"), _flag_value(args, "--out")}
    label_candidates = [value for value in positional if value not in flag_values]

    if not label_candidates:
        error(
            "Token label required",
            suggestion="drone @api host-api issue-token <label> --out FILE",
        )
        return

    label = label_candidates[0]
    scope = _flag_value(args, "--scope") or "read"
    out_path = _flag_value(args, "--out")

    if not out_path:
        # S49 precedent: no raw secret to stdout. A token pasted into scrollback
        # is a token in the shell history file.
        error(
            "--out FILE is required",
            suggestion="The raw token is never printed. Write it to a file: --out ~/device.token",
        )
        return

    try:
        record, raw = host_tokens.issue_token(label, scope)
    except host_tokens.TokenError as e:
        logger.warning("[host_api] token issuance refused: %s", e)
        error(str(e))
        return

    try:
        target = os.path.expanduser(out_path)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, raw.encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as e:
        # The token is already in the store. Say so — a caller who thinks the
        # write failed cleanly would issue a second one and leave a live orphan.
        logger.error("[host_api] token %s issued but its file write failed: %s", record["id"], e)
        error(
            f"Token was issued but could not be written to {out_path}: {e}",
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
        console.print("[dim]Issue one: drone @api host-api issue-token <label> --out FILE[/dim]")
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
        warning(f"No active token with id: {token_id}")
    console.print()


def _cmd_config() -> None:
    """Show the effective server configuration."""
    header("Host API Config")
    console.print()

    config = host_config.load_config()
    console.print(f"  [cyan]host:[/cyan] {config['host']}")
    console.print(f"  [cyan]port:[/cyan] {config['port']}")
    console.print()

    try:
        host_config.validate_bind(config["host"], int(config["port"]))
        success("Bind address would be accepted")
    except host_config.BindRefused as e:
        logger.info("[host_api] config preview: bind would be refused (%s)", e)
        warning("Bind address would be REFUSED")
        console.print(f"  [dim]{e}[/dim]")
    console.print()


def _cmd_set_config(args: List[str]) -> None:
    """
    Write the server config.

    The bind address is a security control, so it gets a real command rather
    than leaving the operator to hand-edit JSON in the secrets store. The value
    is validated BEFORE it is stored — a config that would be refused at startup
    is refused at write time, where the person who typed it is still watching.
    """
    header("Set Host API Config")
    console.print()

    host = _flag_value(args, "--host")
    port_raw = _flag_value(args, "--port")

    if host is None and port_raw is None:
        error(
            "Nothing to set",
            suggestion="drone @api host-api set-config --host 127.0.0.1 --port 8787",
        )
        return

    config = host_config.load_config()
    if host is not None:
        config["host"] = host
    if port_raw is not None:
        try:
            config["port"] = int(port_raw)
        except ValueError:
            logger.warning("[host_api] non-numeric port rejected at set-config: %s", port_raw)
            error(f"Port must be a number, got: {port_raw}")
            return

    try:
        host_config.validate_bind(config["host"], int(config["port"]))
    except host_config.BindRefused as e:
        logger.warning("[host_api] set-config refused: %s", e)
        error("Refusing to store a bind that would not start", suggestion=str(e))
        return

    path = host_config.save_config(config)
    json_handler.log_operation("host_api_config_saved", {"host": config["host"], "port": config["port"]})

    success(f"Config saved: {config['host']}:{config['port']}")
    console.print(f"  [dim]{path}[/dim]")
    console.print()


# =============================================
# PRIVATE HELPERS
# =============================================


def _flag_value(args: List[str], flag: str) -> Optional[str]:
    """
    Read the value following *flag*.

    Args:
        args: Argument list.
        flag: Flag name, e.g. "--host".

    Returns:
        The value, or None if the flag is absent or has no value after it.
    """
    if flag not in args:
        return None

    index = args.index(flag)
    if index + 1 >= len(args):
        return None

    value = args[index + 1]
    if value.startswith("-"):
        return None

    return value


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
