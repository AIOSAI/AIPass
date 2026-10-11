# Exception Text In Response Standards
**Status:** v1
**Date:** 2026-10-10

---

## What It Is

An exception's text is written for the operator: a path, a module name, an argv, the state the
code was in. A web server that copies it into a response body hands all of that to whoever sent
the request. GitHub's CodeQL check calls it `py/stack-trace-exposure` ("Information exposure
through an exception"). It went red on PR #774's head `38166f35` with three MEDIUM rows in
@api's `apps/handlers/host/server.py`, at lines 848, 974 and 995 (check run 114369188515).

The shape the dispatch named, from the same file:

```python
except host_machine.MachineRefused as e:
    raise _deny(503, "machine_refused", e.detail, reason=e.reason) from e   # :976 the text is the body
except host_machine.MachineDoorFailed as e:
    raise _deny(503, "machine_door_failed", str(e)) from e                  # :978
```

`_deny` builds `HTTPException(detail={"error": {"code": ..., "message": message}})`, and FastAPI
serialises `detail` into the response a phone, or a stranger, reads.

---

## Scope

Product code that builds HTTP responses: a module that imports `fastapi` or `starlette`, or
defines a route (a decorator `<x>.get/post/put/delete/patch/head/options/route/api_route/
websocket("/...")` with a `/`-path). Any other file is **not applicable**: it declines and stays out
of the average, because no response is built there to leak into.

## The shape

Inside an `except` clause, exception TEXT reaches a RESPONSE. The row is the sink's line.

The text:

- the bound name (`except X as e`), any attribute or subscript of it (`e.detail`, `e.args[0]`,
  `e.reason`);
- any call that takes it (`str(e)`, `repr(e)`, a helper), an f-string, `%` or `+` that carries it;
- a local assigned from any of those earlier in the same clause;
- `traceback.format_exc()`, `format_exception()`, `format_exception_only()`, `format_tb()` in any
  except clause, bound or not: the traceback needs no name to leak.

The response:

- `HTTPException(detail=...)`, or its second positional argument;
- `JSONResponse`, `PlainTextResponse`, `HTMLResponse`, `Response`: `content=` or the first positional;
- a local helper that builds the response, named `deny`, `refuse`, `error_response` or `respond`
  (leading underscores ignored, so `_deny` is one), taking the text in any argument;
- a `return` of the text itself, or of a dict, list or tuple that holds it.

## What is not convicted

| case | why |
|---|---|
| the text goes only to a logger call | the log is the operator's; that is the cure |
| `type(e)`, `type(e).__name__`, `isinstance(e, ...)` | a class name is the fixed typed message the cure asks for |
| `raise Other(str(e)) from e` | a domain exception is not a response; the clause that turns it into one is judged |
| a local re-assigned to a fixed value before it is used | the text no longer flows |
| a module with no web import and no route | declined: nothing there builds a response |

## What it cannot see: CodeQL's own three rows

CodeQL's annotations put all three rows on the route's **return expression**, not on the `_deny`
lines (`server.py:848` columns 20-90 is `host_git.read_git_changes(...)`; `:974` is
`host_machine.read_machine()`; `:995` is `host_lock.read_lock()`). Each carries four "stack trace
information" flows. Those three routes, and no other, return through api's `ReadCache.get(key,
producer)` (`read_cache.py`; `git_reads.py:114`, `machine.py:98`, `lock.py:95` are its only three
instances). The machine and lock producers return @skills' door dicts verbatim, and those dicts
carry caught-exception text: `skills/lib/system_status/handler.py:361`
(`_refusal("switched_off", str(exc))`) and `:395` (`detail=_describe(exc)`), and
`skills/lib/screen_lock/handler.py`'s `_describe(e)` sentences (`:212`, `:259`, `:289`). One
shared helper taking a callable merges those flows, which is the most plausible reading of why
the git-changes route, whose own producer carries no exception text, shows the same four.

That flow crosses files, two branches, and a callable parameter, and `skills/lib/` is outside the
audit corpus (`apps/` and `shared/`). A file-local rule cannot follow it and does not pretend to.
The `_deny` rows this rule convicts sit in the same route bodies (850, 852, 976, 978, 997) and
are the same leak by a different door; curing them alone will not clear CodeQL's three.

Not a sink here, measured: `websocket.close(reason=str(e))` (`server.py:1357, :1365, :1377`)
also sends exception text to the client. It is outside the dispatch's sink list and is named,
not judged.

## The widening devpulse asked for (steer bb431525): measured, HELD

The steer: the sink is any value a handler returns or publishes (a dict built in an except clause
from exception text, text reaching the return through a same-file helper such as skills'
`_describe(exc)`, a value stored and later returned), and the scope widens past web modules to
skill handlers whose answers api serves to the phone. Logging stays the one allowed destination.

Measured 2026-10-10 with a prototype of exactly that (sinks: the current four plus any `return`
carrying the text, plus a store into a local the same function returns, `x[k] = ...` /
`x.append(...)`; scope: off) over 1,306 product files in `*/apps`, `*/lib` and `aipass/shared`:

| taint model | rows |
|---|---|
| any call taking the text carries it (this rule's model) | 533 |
| text calls only (`str`, `repr`, f-string, `%`, str methods), no helper hop | 471 |
| text calls plus the same-file helper hop (fixpoint over the file's functions) | 494 |

Per branch dir, hop on: seedgo/apps 94, commons/apps 83, memory/apps 65, drone/apps 53, api/apps 53,
ai_mail/apps 25, spawn/apps 21, flow/apps 20, hooks/apps 17, skills/lib 14, aipass/apps 9,
daemon/apps 9, devpulse/apps 10, canary/apps 7, skills/apps 7, prax/apps 6, backup/apps 1;
aipass/shared 0.

On the files as CodeQL read them (`drone @git show 38166f35`), the hop model convicts all six
lines api traced: `system_status/handler.py` 361 (`_refusal(..., str(exc))`), 395 (`vitals[name] =
_section(..., detail=_describe(exc))`, the store-then-return arm), 535; `screen_lock/handler.py`
212, 259, 289 (through `_describe`, 320-328). Without the hop it convicts none of the six. On
today's tree skills has cured system_status. screen_lock 214/269/300 are still convicted, because
its cured `_describe` names `exc.returncode`, an attribute of the exception.

**Why it is HELD.** A 30-row sample read by hand is almost all internal: `{"success": False,
"error": str(exc)}` to a module or CLI caller (commons, memory, spawn, drone lock), `return [],
f"git ls-files could not run: {exc}"` inside seedgo, api's own `lifetime.status()` reason, which a
CLI renders. The rows that do reach a client do so for reasons that are not in their own file:

- @skills `system_status` and `screen_lock` are served because @api imports them (`machine.py`,
  `lock.py`). The `Published:` line in system_status's docstring is prose, and screen_lock has none;
  the other skills `lib/` handlers return the same shapes to the runner.
- @drone's git handlers (`diff_handler.py:113`, `remote_handler.py:146`: `"message": f"git diff
  failed: {exc}"`) reach the phone through a PROCESS boundary: api runs `drone @git ... --json` and
  relays the refusal's `message` verbatim (`git_reads._sentence`, then `raise _deny(400, ...,
  str(e))`).

No decorator, registry or door shape marks "served to a client", so no file-local scope separates
the client-facing rows from the internal ones. The rule keeps its web-module scope.

"Stored in a cache that is later returned" is cross-function: `ReadCache.get()` stores into
`self._entries` and `_fresh()` returns from it, with the producer passed in as a callable. A
file-local rule cannot see that. A store into a local that the SAME function returns is visible,
and the prototype convicts 395 that way.

If the scope is widened later, `lib/` is outside the `all_files` corpus (`apps/` and `shared/`
only). Judging it would take a `branch_level` rule that walks its own roots, as `host_portability`
does (`_CORPUS_ROOTS = ("apps", "tests", "lib")`). Inside the web modules the hop adds nothing:
this rule already treats a call that takes the text as carrying it.

---

## Check first

Measured 2026-10-10 over `src/aipass/*/apps` and `*/shared`, 1,266 product files.

| | |
|---|---|
| files in scope | 2, both @api: `host/server.py`, `host/statics.py` |
| rows | 48, all in `server.py`, every one a `raise _deny(..., str(e) / e.detail ...) from e` |
| `statics.py` | in scope, 0 rows |
| the same arms with the scope gate off | 462 rows in apps/shared, 18 in `lib/`: returning exception text is ordinary outside a web server, which is why the gate exists |

## Scoring

Scored per file: 0 on any row, else 100; a file out of scope declines. Every row goes on ONE
check, as `<file>:<line> exception text reaches an HTTP response - <cure>`.

## Bypass position

Line-level bypass rows are honoured, as for every `all_files` rule. A bypass here is a decision
to show a stranger the server's internals, and the reason field should say who that stranger is.

## The cure

Log the detail with `exc_info` (prax `logger.error(..., exc_info=True)` or `logger.exception`)
so the traceback lands where the operator reads it, and return a fixed, typed message: a short
code and phrase. If traceability is wanted, add a correlation id that also appears in the log
line. Keep the branching on known error classes; only the detail string goes.

---
