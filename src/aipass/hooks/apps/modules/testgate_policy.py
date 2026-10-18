# =================== AIPass ====================
# Name: testgate_policy.py
# Version: 1.0.2
# Description: Reads .aipass/test_write_policy.json — the switch behind the test-write gate
# Branch: hooks
# Layer: apps/modules
# Created: 2026-09-01
# Modified: 2026-10-17
# =============================================

"""Reads the test-write policy: may agents create new test files here?

Own file, not a hooks.json key: hooks.json is hash-enrolled, so every edit darks the engine.
Fails CLOSED on missing or unreadable: else deleting one file repeals the switch.
"""

import json
from pathlib import Path
from typing import NamedTuple

from aipass.cli.apps.modules import err_console
from aipass.hooks.apps.handlers.cli.help_flags import wants_help
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console

POLICY_DIR = ".aipass"
POLICY_FILENAME = "test_write_policy.json"

# An unrecognised value reads as unreadable, never rounded: "of" is not "off".
_ON = "on"
_OFF = "off"
_VALID_STATES = (_ON, _OFF)

HELP_COMMANDS = [
    ("testwrite", "Show the test-write policy in force here (and what the gate cannot catch)"),
]


class Policy(NamedTuple):
    """The policy in force for one session.

    A non-None ``error`` always means refuse.
    """

    writing_enabled: bool
    allow: frozenset[str]
    block_edits: bool
    path: Path | None
    error: str | None


def find_policy_file(start: str | Path) -> Path | None:
    """Walk up from *start* to the first ``.aipass/test_write_policy.json``.

    *start* is the payload's session dir, not cwd: a hook process's cwd may be another project.
    """
    try:
        search = Path(start) if start else Path.cwd()
        home = Path.home()
    except OSError as exc:
        logger.info("[HOOKS] testgate_policy: no usable start directory (%s)", exc)
        return None

    while search != home and search.parent != search:
        candidate = search / POLICY_DIR / POLICY_FILENAME
        try:
            if candidate.exists():
                return candidate
        except OSError as exc:
            logger.info("[HOOKS] testgate_policy: unreadable while walking %s: %s", candidate, exc)
            return None
        search = search.parent
    return None


def _missing(start: str | Path) -> Policy:
    """The fail-closed Policy for "no policy file anywhere above *start*"."""
    expected = f"<project>/{POLICY_DIR}/{POLICY_FILENAME}"
    return Policy(
        writing_enabled=False,
        allow=frozenset(),
        block_edits=False,
        path=None,
        error=(
            f"no test-write policy found (searched upward from {start} for {expected}).\n"
            "This gate fails CLOSED on an absent policy: a switch that unlocks when its own "
            "config disappears is repealed by deleting one file.\n"
            "The ruling it stands in for: the owner, 2026-09-01 (DPLAN-0323) — agents do not create "
            "tests while @seedgo's test_quality v5 pack lands. EDITING an existing test is untouched.\n"
            f'Cure: create {expected} with {{"agent_test_writing": "on"}} to permit test '
            'creation here, or "off" plus an "allow" array to enforce the fleet ruling.'
        ),
    )


def _unreadable(path: Path, problem: str) -> Policy:
    """The fail-closed Policy for a policy file that exists but cannot be followed."""
    return Policy(
        writing_enabled=False,
        allow=frozenset(),
        block_edits=False,
        path=path,
        error=(
            f"the test-write policy could not be read: {problem}\n"
            f"Policy: {path}\n"
            "The file exists, so a ruling WAS made here and this gate cannot tell what it "
            "says. Substituting a guess for it — in either direction — would be the gate "
            "deciding policy on its own.\n"
            f'Cure: repair the file. Expected shape: {{"agent_test_writing": "on"|"off", '
            '"allow": ["branch"], "block_test_edits": false}'
        ),
    )


def _read_allow(raw: object) -> frozenset[str] | str:
    """Parse the allow array, or return a problem string."""
    if raw is None:
        return frozenset()
    if not isinstance(raw, list) or not all(isinstance(name, str) for name in raw):
        return '"allow" must be an array of branch names'
    return frozenset(name.strip() for name in raw if name.strip())


def load(start: str | Path) -> Policy:
    """Read the test-write policy in force for a session standing at *start*.

    Never raises: every failure becomes a Policy carrying ``error``.
    """
    path = find_policy_file(start)
    if path is None:
        return _missing(start)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return _unreadable(path, f"{type(exc).__name__}: {exc}")
    return _validated(data, path)


def _validated(data: object, path: Path) -> Policy:
    """Turn parsed JSON into a Policy, or into the refusal that says why not."""
    if not isinstance(data, dict):
        return _unreadable(path, "the policy must be a JSON object")

    state = data.get("agent_test_writing")
    if not isinstance(state, str) or state.strip().lower() not in _VALID_STATES:
        return _unreadable(path, f'"agent_test_writing" must be one of {list(_VALID_STATES)}, got {state!r}')

    allow = _read_allow(data.get("allow"))
    if isinstance(allow, str):
        return _unreadable(path, allow)

    block_edits = data.get("block_test_edits", False)
    if not isinstance(block_edits, bool):
        return _unreadable(path, '"block_test_edits" must be true or false')

    return Policy(
        writing_enabled=state.strip().lower() == _ON,
        allow=allow,
        block_edits=block_edits,
        path=path,
        error=None,
    )


def print_introspection() -> None:
    """Print the policy in force plus the gate's published residual."""
    from aipass.hooks.apps.modules.testwrite_targets import NOT_CAUGHT

    policy = load(Path.cwd())
    CONSOLE.print("[bold cyan]testwrite[/bold cyan] — may agents create new test files here?")
    CONSOLE.print()
    if policy.error:
        CONSOLE.print("[red]REFUSING (fail-closed)[/red]")
        CONSOLE.print(f"[dim]{policy.error}[/dim]")
    else:
        state = "[green]ON — creation allowed[/green]" if policy.writing_enabled else "[yellow]OFF[/yellow]"
        CONSOLE.print(f"  agent_test_writing : {state}")
        CONSOLE.print(f"  allow              : {sorted(policy.allow) or '(none)'}")
        CONSOLE.print(f"  block_test_edits   : {policy.block_edits}")
        CONSOLE.print(f"  policy             : {policy.path}")
    CONSOLE.print()
    CONSOLE.print("[yellow]NOT CAUGHT — the residual, stated rather than discovered:[/yellow]")
    for gap in NOT_CAUGHT:
        CONSOLE.print(f"  - {gap}")


def handle_command(command: str, args: list) -> bool:
    """Route ``drone @hooks testwrite`` — read-only; the flip is a human edit."""
    if command != "testwrite":
        return False
    if not args:
        print_introspection()
        return True
    if wants_help(args):
        CONSOLE.print("[bold cyan]testwrite[/bold cyan] — show the test-write policy in force")
        CONSOLE.print()
        CONSOLE.print("  drone @hooks testwrite       Show the policy and the gate's residual")
        CONSOLE.print()
        CONSOLE.print(f"[dim]Policy file: <project>/{POLICY_DIR}/{POLICY_FILENAME}[/dim]")
        CONSOLE.print("[dim]Read-only on purpose: flipping an owner-level ruling is a human edit,[/dim]")
        CONSOLE.print("[dim]not something an agent can do to the gate that constrains it.[/dim]")
        return True
    print_introspection()
    return True
