[<- Back to the README](../README.md)

# The CLI contract

How daemon's shared argument gate refuses unknown commands and flags, and what the two retired verbs still do when called.

---

## Unknown arguments are refused

The owner's standing ruling (2026-09-07, FPLAN-0492 wave 2b): **an unknown command or argument fails with a non-zero exit and a
message naming the token.** Never default, never silently ignore.

Every verb below routes its arguments through one shared gate,
`apps/handlers/cli/arg_gate.py`. An unexpected positional or an unrecognised flag is refused by
name on stderr, the usage line follows, exit is 1, and **nothing the verb was asked to do runs**.

```
$ drone @daemon queue not_a_real_subarg_xyz
❌ queue: unknown argument 'not_a_real_subarg_xyz'

Usage: drone @daemon queue [--json]
$ echo $?
1
```

The gate knows two kinds of flag, because they consume different amounts of argv: boolean flags
stand alone (`--json`), value flags swallow the token after them (`--hours 48`) — and that token
must not then be judged a stray positional. A help request outranks the gate and always exits 0.

Twelve surfaces are gated (`update`, `queue`, `rotation`, `activity`, `activity-report`,
`activity_report`, `inbox-sweep`, `install-timer`, `uninstall-timer`, `schedule`, `actions`,
`run`), plus `branch-health`, which gates a positional in its own module. Each has a pin in
`tests/test_cli_routing.py`, and each pin was mutation-checked: disable that verb's refusal and
its pin goes red.

The two retired verbs behave slightly differently and deliberately: bare `schedule` / `actions`
still print the migration notice and exit 0, because that notice is the right guidance. A retired
*subcommand* (`schedule create x`) prints the notice **and then refuses** — it did not create
anything, and exiting 0 told the caller's `&&` that it had.

The gate is a **handler**, so it decides and does not print: it raises `UnknownArgument`, and the
router in `apps/daemon.py` renders it once — one message shape for twelve verbs. The router may
not import a handler (seedgo *encapsulation*), so the exception is re-exported through
`apps/modules/__init__.py`; the router talks to the modules layer, the modules layer talks to the
handler. `gate()` is called **outside** each module's `try`, because a module that catches its own
refusal turns exit 1 back into exit 0 — `update` did exactly that before this was fixed.

**No test suite in this branch is parked.** Every `tests/test_*.py` file runs in CI; the only
disabled files under `apps/` are archived, carry a `(disabled)` marker, and are not tests. If a
suite ever has to be parked, the rule is: say so here, name the file, name the reason, and name
what has to be true to un-park it — a silently skipped suite reads as coverage that does not exist.

---

`schedule` and `actions` are still routable, but only as retirement notices — they ignore every
argument and print the same migration text pointing at `.daemon/schedule.json`. There is no
`schedule list`, `schedule create`, `schedule run-due`, `actions list`, `actions set` or
`actions <id> on/off`; those subcommands were documented here long after the modules were retired.
Use `run`, `queue` and per-branch `.daemon/schedule.json` instead.
