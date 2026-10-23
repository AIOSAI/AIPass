# =================== AIPass ====================
# Name: host_api.py
# Description: Host API Module — server lifecycle and token administration
# Version: 1.5.1
# Created: 2026-08-14
# Modified: 2026-10-22
# =============================================

"""
Host API Module

Owns the tokens and offers every other host-api call to host_serve, host_config_cli and host_pair_cli.
Reference: docs/host_api.md
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
from aipass.prax import logger
from aipass.api.apps.handlers.host import autostart as host_autostart
from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host import lifetime as host_lifetime
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import pairings as host_pairings
from aipass.api.apps.modules import host_config_cli
from aipass.api.apps.modules import host_pair_cli
from aipass.api.apps.modules import host_serve
from aipass.api.apps.handlers.host import tokens as host_tokens

HELP_FLAGS = ("--help", "-h", "help")


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
    console.print("  - api.apps.handlers.host.pairings")
    console.print("  - api.apps.handlers.host.server")
    console.print()

    console.print("[cyan]Available Workflows:[/cyan]")
    console.print("  - serve()          - Validate the bind, then run the server")
    console.print("  - issue_token()    - Mint a bearer token for a device")
    console.print("  - revoke_token()   - Revoke server-side, next request")
    console.print("  - set_bind()       - Validate and store the bind address")
    console.print("  - autostart()      - Render the boot unit (a running unit is left alone)")
    console.print("  - install_unit()   - Install the unit under the user's systemd (dry_run names the steps)")
    console.print("  - enable_unit()    - enable --now it, inside the graphical session (dry_run names the steps)")
    console.print("  - mint_pairing()   - A one-use, five-minute code the phone trades for its bearer")
    console.print("  - render_qr()      - A text's QR as terminal block characters")
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
    console.print("  [cyan]host-api pair <label>[/cyan]          [dim]A one-use QR the phone's camera redeems[/dim]")
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
    console.print("  [cyan]--ttl <seconds>[/cyan]  [dim]pair: the code's life, 30 to 900 (default: 300)[/dim]")
    console.print()
    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [dim]# Pair a phone: point its camera at the QR (the server must be up on a tailnet bind)[/dim]")
    console.print("  [cyan]drone @api host-api pair phone --scope operate[/cyan]")
    console.print()
    console.print("  [dim]# Enroll a device by hand, then start the server[/dim]")
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
    console.print("  [dim]A paired token has no receipt: the phone holds the only copy. Revoke it like any.[/dim]")
    console.print("  [dim]An existing receipt is never overwritten: its token is still live.[/dim]")
    console.print("  [dim]Bind refuses wildcards, hostnames, and addresses this machine lacks.[/dim]")
    # Read from the flag, never written down: a written sentence outlives the gate.
    if host_config.LOOPBACK_ONLY:
        console.print("  [dim]Loopback-only: every non-loopback bind is refused.[/dim]")
    else:
        console.print("  [dim]Non-loopback binds are open since the 2026-08-14 security review.[/dim]")
    console.print("  [dim]--detach validates the bind BEFORE spawning — a refusal never reaches a child.[/dim]")
    console.print()


def issue_token(label: str, scope: str = "read"):
    """Mint a bearer token. Returns (record, raw_value); the raw is never stored."""
    return host_tokens.issue_token(label, scope)


def revoke_token(token_id: str) -> bool:
    """Revoke a token by id. Effective on the next request, no restart."""
    return host_tokens.revoke_token(token_id)


def serve(host: Optional[str] = None, port: Optional[int] = None) -> None:
    """Validate the configured bind address, then run the server."""
    host_server.serve(host=host, port=port)


# The door for other branches' in-process calls (@aipass's installer), so none reaches into handlers.
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


# The install doors for `aipass install`: the CLI's autostart only prints its steps; these run them.
BindRefused = host_config.BindRefused
AutostartUnsupported = host_autostart.AutostartUnsupported
SupervisorUnreachable = host_autostart.SupervisorUnreachable
LifetimeError = host_lifetime.LifetimeError
TokenError = host_tokens.TokenError


def set_bind(host: str, port: int) -> dict:
    """Validate and store the bind, as set-config --host --port does. Unchanged = not written. Raises BindRefused."""
    return host_config.set_bind(host, port)


def autostart(host: Optional[str] = None, port: Optional[int] = None) -> dict:
    """Render the boot unit and report what installing it needs; a unit already running is left alone."""
    return host_lifetime.ensure_autostart(host, port)


def install_unit(dry_run: bool = False) -> dict:
    """Copy the rendered unit into the user unit dir and reload systemd; dry_run names the steps only."""
    return host_autostart.install_unit(host_lifetime.unit_path(), dry_run)


def enable_unit(dry_run: bool = False) -> dict:
    """enable --now the installed unit; refused while a hand-started server holds the port."""
    return host_lifetime.enable_autostart(dry_run)


def serve_detached(host: Optional[str] = None, port: Optional[int] = None) -> dict:
    """Start the server in its own session, as serve --detach does: {pid, host, port, log, started}.

    The install's door on a machine with no user systemd. Raises BindRefused, LifetimeError, SupervisorUnreachable.
    """
    return host_lifetime.serve_detached(host=host, port=port)


def receipt_path(label: str) -> Path:
    """Where issue-token writes a token's raw value by default. Raises TokenError for a label that is no filename."""
    return host_tokens.receipt_path(label)


PairingError = host_pairings.PairingError


def mint_pairing(label: str, scope: str = "read", ttl_seconds: int = host_pairings.DEFAULT_TTL_SECONDS) -> dict:
    """Mint a one-use code: {id, label, scope, code, expires_at, url}. Raises PairingError (bad input, no bind)."""
    return host_pairings.mint_pairing(label, scope, ttl_seconds)


def render_qr(text: str) -> str:
    """The QR of text as terminal block characters, no trailing newline. Raises PairingError for empty text."""
    return host_pairings.render_qr(text)


def handle_command(command: str, args: List[str]) -> bool:
    """Handle host API commands routed via drone."""
    # Both spellings: the self-map advertises the module name host_api. Literal, so a checker sees the match.
    mine = command in ("host-api", "host_api")

    if not args:
        if mine:
            print_introspection()
            return True
        return False

    if not mine:
        return False

    # A help flag anywhere means explain, never run (__main__ bypasses the router). Literal for the checker.
    if any(arg in ("--help", "-h", "help") for arg in args):
        print_help()
        return True

    subcommand = args[0]
    rest = args[1:]

    # Sub-routers decline what they do not own, so an unknown subcommand still reaches the error below.
    if host_serve.handle_command(command, args):
        return True
    if host_config_cli.handle_command(command, args):
        return True
    if host_pair_cli.handle_command(command, args):
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

    try:
        target = Path(os.path.expanduser(out_path)) if out_path else host_tokens.receipt_path(label)
    except host_tokens.TokenError as e:
        logger.warning("[host_api] token receipt path refused: %s", e)
        error(str(e))
        return

    # Before minting: a stored token with no readable receipt is a live credential nobody holds.
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
        # O_EXCL, not O_TRUNC: the check above is the sentence, this is the guarantee against a racing writer.
        fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, raw.encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as e:
        # The token is already in the store: say so, or the caller issues a second and leaves a live orphan.
        logger.error("[host_api] token %s issued but its file write failed: %s", record["id"], e)
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
    """
    parts = [f"minted by {record.get('minted_by') or host_tokens.UNKNOWN_MINTER}"]

    parts.append(f"last used {_stamp(record.get('last_used'))}" if record.get("last_used") else "never used")

    if record.get("revoked_at"):
        parts.append(f"revoked {_stamp(record.get('revoked_at'))}")

    return " · ".join(parts)


def _stamp(value: object) -> str:
    """Render a stored ISO timestamp for a human, without inventing precision."""
    text = str(value or "")
    try:
        return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M")
    except ValueError as e:
        # Shown raw to the operator; the log names the condition only, the value comes from the credential store.
        logger.warning("[host_api] unreadable timestamp in the token store (%s)", type(e).__name__)
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
        # error(), not a note: a scripted `revoke-token <id> && <next>` must not proceed believing the device is off.
        error(f"No active token with id: {token_id}")
    console.print()


if __name__ == "__main__":
    cli_args = sys.argv[1:]

    if len(cli_args) == 0:
        print_introspection()
        sys.exit(0)

    if any(arg in HELP_FLAGS for arg in cli_args):
        print_help()
        sys.exit(0)

    if handle_command("host-api", cli_args):
        sys.exit(0)
    else:
        error("Unknown command", suggestion="Run 'drone @api host-api --help' for available commands")
        sys.exit(1)
