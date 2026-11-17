[<- Back to the README](../README.md)

# The event bus

**Branch** trigger · **Code** `apps/modules/core.py`, `apps/handlers/cli/help_flags.py`

The verbs are in `drone @trigger core --help`; `drone @trigger list` prints the live
event/handler table. This page is what the bus guarantees and what it deliberately does not.

---

## Python API

Another branch takes the bus through the package door, `aipass/trigger/__init__.py`:
`trigger` (the bus instance) and `Trigger` (its class). Every other name raises
`AttributeError`. The door reads each name from `apps/modules/core.py` on every access and
stores nothing on the package, so a patch on core reaches the next read.

```python
from aipass.trigger import Trigger

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
Handler exceptions are never raised at the caller, and a failing handler is never
disabled: it runs on every event, so it recovers the moment its cause clears. The
failure goes through `handlers/failure_report.py`: an ERROR line on the
`logs/failures.jsonl` trail at most once per `LOG_INTERVAL_SECONDS` (600 s) per handler
and branch, never on a watched `.log` the bus would read back. Its first failure is recorded in `medic_state.json`
(`failing_handlers`, shown by `drone @trigger medic status`) and mailed to @devpulse
once per handler; a success clears the row.

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

**A test silences or records the bus one way: patch `fire` on the class, through the door.**
`fire` is a classmethod and `trigger` is one `Trigger()` instance, so the class attribute is
the one place every caller passes: a module that bound `trigger` at import, one that imports
it at call time, and one that calls `Trigger.fire`. A recorder sees `fire(event, **data)`.

```python
from aipass.trigger import Trigger

def test_x(monkeypatch):
    fired = MagicMock()
    monkeypatch.setattr(Trigger, "fire", fired)   # or mock.patch("aipass.trigger.Trigger.fire")
```

A plain function standing in for `fire` needs `staticmethod(fn)`, or it binds the instance.
Two other forms miss callers: patching the name `aipass.trigger.trigger` never reaches a
module that bound `trigger` at import, and patching `fire` on the instance never reaches
`Trigger.fire`. Pinned in `tests/test_core.py::TestFrontDoor`.

`report_error` is not on the door; inside trigger:

```python
from aipass.trigger.apps.modules.errors import report_error

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
