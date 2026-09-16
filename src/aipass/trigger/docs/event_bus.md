# The event bus

**Branch** trigger · **Code** `apps/modules/core.py`, `apps/handlers/cli/help_flags.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

The verbs are in `drone @trigger core --help`; `drone @trigger list` prints the live
event/handler table. This page is what the bus guarantees and what it deliberately does not.

---

## Python API

```python
from aipass.trigger.apps.modules.core import Trigger

# Fire an event — all registered handlers run
result = Trigger.fire("plan_file_created", path="/path/to/FPLAN-0042.md")
# {'event': 'plan_file_created', 'handlers': 1, 'ran': 1, 'failed': 0}
# A nested fire (one issued from inside a handler) is queued, and says so:
# {'event': 'inner', 'deferred': True}

# Register a handler
def on_plan_created(**data):
    print(f"Plan created at {data['path']}")

Trigger.on("plan_file_created", on_plan_created)

# Remove a handler
Trigger.off("plan_file_created", on_plan_created)
```

**Handler failures are isolated, not hidden.** A handler that raises never
propagates to the caller and never stops the other handlers — that isolation is
the point of a bus. But isolation used to be indistinguishable from silence:
`drone @trigger fire` printed a green `Fired event:` whether every handler ran,
every handler crashed, or the event name was a typo nothing listened to. Firing
`plan_file_moved` with the wrong kwargs during the APLAN-0008 audit crashed the
handler and still reported success; the only trace was an ERROR line that the log
watcher later re-reported as a medic error. `fire()` now returns the counts above
and the CLI prints them, so a wrong-key or wrong-name fire is visible where it is
typed. Handler exceptions are still logged, still counted toward the
consecutive-failure auto-disable, and still never raised at the caller.

**A help flag anywhere explains; it never executes.** `--help` and `-h` are
matched exactly at *any* position in the argument sequence, so
`medic mute @branch --help` describes muting instead of performing it. Every
module's `handle_command` gates on `handlers/cli/help_flags.wants_help()`
before doing any work — but *after* checking that the module owns the command,
since a module that claimed any invocation carrying `--help` would hijack every
other module's help at the entry point. The bare word `help` is deliberately
positional (position 0 only): trigger's own commands take it as a legitimate
value — `errors suppress <id> help` is a reason and `fire evt message=help` is
event payload. Matching is exact for the same reason, so `message=--help` stays
a payload too. The fleet-wide version of this bug (seedgo `help_flag_safety`,
2026-08-13) performed a 17-branch config reset and a real backup run from
commands that were asked to describe themselves; trigger's own worst case was
a 24-hour medic mute with no unmute.

**Event data contracts are per-handler and are not published here.** Sibling
events do not share key names — `plan_file_created` and `plan_file_deleted` take
`path`, while `plan_file_moved` takes `src_path` and `dest_path`. Read the
handler in `apps/handlers/events/` before firing one by hand.

```python
from aipass.trigger.apps.modules.errors import report_error

# Cross-branch error reporting
result = report_error(
    branch="api",
    error_type="ConnectionError",
    message="Timeout reaching upstream",
    source_file="client.py",
)
# Returns: {"is_new": True, "fingerprint": "abc123", "count": 1, ...}
```

---

## Related

- [events.md](events.md) — the live event table, the aliases, and the names with nothing behind them
- [medic.md](medic.md) — what `error_detected` reaches once it is fired
- [error_registry.md](error_registry.md) — what `report_error()` writes
