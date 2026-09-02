# =================== AIPass ====================
# Name: testgate_policy.py
# Version: 1.0.0
# Description: Reads .aipass/test_write_policy.json — the switch behind the test-write gate
# Branch: hooks
# Layer: apps/modules
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""Reads the test-write policy: may agents create new test files here?

Patrick ruled on 2026-09-01 (devpulse DPLAN-0323) that agents are stripped of
self-directed test creation while @seedgo's test_quality v5 pack lands. The
ruling is enforced by ``handlers/security/testwrite_gate.py`` and lives as DATA
in ``<project>/.aipass/test_write_policy.json``, so turning it back on later is
a field flip rather than a rebuild.

WHY ITS OWN FILE, NOT A KEY IN hooks.json. hooks.json is hash-enrolled in the
trust registry: any edit to it darks every hook for the project until a human
re-runs ``aipass trust``. A policy meant to be flipped — off, one branch in
``allow``, on — cannot live in a file whose every edit disables the engine that
reads it. Same directory, same walk-up, separate hash.

THE FAIL MODE, ruled here rather than inherited (the dispatch left it to this
branch, naming two precedents that point opposite ways):

    Fail CLOSED. Both when the file is missing and when it cannot be read.

``bash_writes`` allows-and-logs what it cannot parse, and that is right there
for a reason that does not transfer: an unparseable command taught the fence
nothing ABOUT THAT COMMAND, so the policy question was never reached and
convicting on ignorance would refuse correct work. Here the file IS the policy
question. "No answer" read as "allow" means the switch is defeated by deleting
one file — and a ruling that a stray ``rm`` silently repeals is not a ruling.
Fail-closed makes deletion self-defeating instead.

Two things make fail-closed safe rather than a lockout:

 1. The gate only consults this policy for writes that are already test-file
    shaped. Ordinary work never reaches the policy read at all, so a broken
    policy cannot brick the branch.
 2. Writing the policy file is not itself a test-file write, so a session
    locked out of creating tests can always create or repair the policy.

Every refusal carries the path it looked for, what went wrong, and the exact
cure — a fail-closed gate that does not say how to open is a wall.
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

# The only two spellings of the switch. An unrecognised value is not a ruling
# this module can follow, so it is read as unreadable rather than guessed at —
# "of" is not "off", and silently rounding it to one of the two would decide
# fleet policy on a typo.
_ON = "on"
_OFF = "off"
_VALID_STATES = (_ON, _OFF)

HELP_COMMANDS = [
    ("testwrite", "Show the test-write policy in force here (and what the gate cannot catch)"),
]


class Policy(NamedTuple):
    """The policy in force for one session.

    Attributes:
        writing_enabled: True when agents may create new test files here.
        allow: Branch names exempted while ``writing_enabled`` is False.
        block_edits: True when EDITS to existing test files are also refused.
        path: The policy file that was read, or None when none was found.
        error: None when the policy was read cleanly; otherwise a human-facing
            explanation of why the gate is refusing. A non-None error always
            means refuse — the fail-closed ruling in this module's docstring.
    """

    writing_enabled: bool
    allow: frozenset[str]
    block_edits: bool
    path: Path | None
    error: str | None


def find_policy_file(start: str | Path) -> Path | None:
    """Walk up from *start* to the first ``.aipass/test_write_policy.json``.

    Mirrors ``handlers/config/loader.find_project_config``'s walk — same
    directory, same stop at ``Path.home()`` — with one deliberate difference:
    the start is an ARGUMENT rather than ``Path.cwd()``. A PreToolUse hook is
    handed the session directory in its payload, and that is the ground the
    write is being made from; a hook process's own cwd is not guaranteed to be
    it. Reading the wrong ground would find the wrong project's policy.

    Args:
        start: Directory to begin the walk from.

    Returns:
        The first policy file found, or None.
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


def _read_allow(raw: object, path: Path) -> frozenset[str] | str:
    """Parse the allow array, or return a problem string."""
    if raw is None:
        return frozenset()
    if not isinstance(raw, list) or not all(isinstance(name, str) for name in raw):
        return '"allow" must be an array of branch names'
    return frozenset(name.strip() for name in raw if name.strip())


def load(start: str | Path) -> Policy:
    """Read the test-write policy in force for a session standing at *start*.

    Never raises: every failure becomes a Policy carrying ``error``, which the
    gate turns into a refusal that names the file and the cure.

    Args:
        start: The session working directory from the hook payload.

    Returns:
        The Policy in force. ``error`` is None only on a clean read.
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
    """Turn parsed JSON into a Policy, or into the refusal that says why not.

    Every field is checked by TYPE and by VALUE. An unrecognised switch value is
    read as unreadable rather than rounded to the nearest legal one — "of" is not
    "off", and guessing would decide fleet policy on a typo.

    Args:
        data: Whatever ``json.loads`` returned.
        path: The file it came from, for the refusal text.

    Returns:
        A clean Policy, or one carrying ``error``.
    """
    if not isinstance(data, dict):
        return _unreadable(path, "the policy must be a JSON object")

    state = data.get("agent_test_writing")
    if not isinstance(state, str) or state.strip().lower() not in _VALID_STATES:
        return _unreadable(path, f'"agent_test_writing" must be one of {list(_VALID_STATES)}, got {state!r}')

    allow = _read_allow(data.get("allow"), path)
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
    """Print the policy in force plus the gate's published residual.

    A switch you can read from a terminal is one an agent can plan around; a
    switch that only speaks through refusals gets discovered by hitting it.
    """
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
        CONSOLE.print("[dim]Read-only on purpose: flipping a Patrick-level ruling is a human edit,")
        CONSOLE.print("not something an agent can do to the gate that constrains it.[/dim]")
        return True
    print_introspection()
    return True
