# One Logger

Prax is the only logging system. A production file that logs does it through a prax door; a file that logs nothing owes no prax import. Any other logger is rejected, in every production file: handlers, small files, doors and branch-root `.py` included.

## The doors

```python
from aipass.prax import logger        # door one: every file that logs
from aipass.prax import trail         # door two: a loop on the watched log path
from aipass.prax import append_jsonl  # a record (a ledger, a decision trail), not a log line
```

A transcript (a child process's captured output) is not a log: it leaves the `.log` suffix.

## The four keys

All four read the AST; nothing reads comments or strings as code.

| Key | Convicts | Example it catches |
|-----|----------|--------------------|
| K0 | `import logging`, `import logging.handlers`, `from logging... import` | `logger = logging.getLogger(__name__)` |
| K1 | a class defining two or more of `debug`, `info`, `warning`, `error`, `critical`, whether or not its own body writes | a JSONL logger class that hands each line to a module function |
| K2 | `open(p, "a"/"w"/"x"/"+")`, `p.open(...)`, `os.open(p, O_APPEND...)`, `p.write_text(...)` where `p` resolves to a `.log` name: a literal, a name bound to one (module constants and locals, followed to a fixpoint), or a call to a module function returning one | `with open(LOG_FILE, "a") as f: f.write(line)` |
| K3 | a write wrapper: a function with a parameter, at most six statements, returning nothing, calling only writes, flushes, stamps and string work, that sends a parameter to `sys.stderr`, or prints it with a time stamp | `def _log(msg): console.print(f"[{now}] {msg}")` |

stdout is not a log channel for K3: a CLI's answer and a child's protocol both ride it.

## No waivers

A bypass row waives nothing here. The only way through is `logging_allowed.py`, which names a file by its exact path under `src/aipass`, per key, with the reason:

| Key | File | Why |
|-----|------|-----|
| K0 | `prax/apps/handlers/logging/jsonl_writer.py` | prax's standalone writer: its own failure can only go to stderr |
| K1 | `prax/apps/modules/logger.py`, `prax/apps/handlers/logging/direct.py` | they are door one |
| K2 | `hooks/apps/handlers/bridges/{claude,codex,opencode,seed}.py` | crash floor: the break record, written when prax can be what broke |

The list is temporary: prax publishes the files allowed to hold stdlib logging, and this list then reads it.

## What the keys cannot see

- A log file reached only through a parameter from another module (`open(stderr_log, "a")` where the caller named the file).
- A shell redirect, a systemd unit's output file, and anything third-party libraries log.
- Non-Python code.

## Scoring

ADVISORY: each file is scored 100 or 0, outside the branch average. The checklist prints `[ADVISORY]` and does not fail the edit.

## Related

`imports` convicts stdlib logging in non-handler modules; `log_visibility` and `log_handler` judge getLogger and handler use. Their logging arms fold into this standard when it gates.
