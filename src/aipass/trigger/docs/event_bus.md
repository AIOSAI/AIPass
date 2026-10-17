[<- Back to the README](../README.md)

# The event bus

**Branch** trigger · **Code** `apps/modules/core.py`, `apps/handlers/cli/help_flags.py`

The verbs are in `drone @trigger core --help`; `drone @trigger list` prints the live
event/handler table. This page is what the bus guarantees and what it deliberately does not.

---

## Python API

```python
from aipass.trigger.apps.modules.core import Trigger

# Register a handler
def on_report_ready(**data):
    print(f"Report ready at {data['path']}")

Trigger.on("report_ready", on_report_ready)

# Fire an event — all registered handlers run
result = Trigger.fire("report_ready", path="/path/to/report.md")
# {'event': 'report_ready', 'handlers': 1, 'ran': 1, 'failed': 0}
# A nested fire (one issued from inside a handler) is queued, and says so:
# {'event': 'inner', 'deferred': True}

# Remove a handler
Trigger.off("report_ready", on_report_ready)
```

**Handler failures are isolated, not hidden.** A handler that raises never
propagates to the caller and never stops the other handlers — that isolation is
the point of a bus. `fire()` returns the counts above and `drone @trigger fire`
prints them, so a wrong-key or wrong-name fire is visible where it is typed: a
crashed handler shows in `failed`, a name nothing listens to shows `handlers: 0`.
Handler exceptions are still logged, still counted toward the consecutive-failure
auto-disable, and still never raised at the caller.

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
a payload too. Without the gate, `medic mute @branch --help` would set a 24-hour
mute while appearing to print help.

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
