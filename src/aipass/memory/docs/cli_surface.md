[<- Back to the README](../README.md)

# The CLI surface

**Branch** memory · **Code** `apps/memory.py`, `apps/handlers/cli/`, `apps/modules/watch.py`

How this branch's entry point routes, refuses, exits and logs. The verb list itself is
`drone @memory --help`; the bare `drone @memory` starts the watcher and prints the live
introspection block as its banner.

---

## A correct refusal must not become a runaway log

The safety valve logs **one summary line per array per run**, naming the count and the reason. The
per-entry detail (each refused entry, in full) goes to `DEBUG`, where it stays recoverable while
debugging without flooding a routine run: a per-entry `WARNING` turns one pass over one file into a
wall of log lines.

When a file is over its limit and *nothing* is archivable, the detector would re-fire on it forever
and refuse the same entries every run, a skip loop. That case says `NOTHING DRAINED` in words and
names the two shapes that cause it: an array that is not newest-first, or entries carrying no usable
`number`. *A lane whose refusals are all correct can still be a lane that never drains.*

The valve itself is in [rollover_pipeline.md](rollover_pipeline.md).

---

## An unknown argument exits non-zero

An unknown command or argument **fails**: the refusal is printed and the exit code says so, because
the exit code is the one half a script reads.

| probe | exit |
|---|---|
| `drone @memory definitely_not_a_verb_xyz` | **1** — nothing routed |
| `drone @memory --definitely-not-a-flag` | **1** — a dashed token nothing routes is the same refusal |
| `drone @memory rollover not_a_real_subarg_xyz` | **2** — routed, then refused |

The two codes differ on purpose: `handle_command()` returning `True` means *I handled this*, not *it worked*,
so a refused sub-argument would be indistinguishable from a successful run without the flip. The modules
call `error()`, which marks the failure (`cli/display.mark_command_failed`); `main()` calls
`reset_command_state()` at its top and `resolve_exit(True)` on the routed path, and the `__main__` block passes
the result to `sys.exit`, the same idiom @ai_mail and @devpulse carry. `--help`, `--version`, a bare
`drone @memory` and every working verb exit 0, pinned alongside the three refusals in `TestUnknownArgumentExitsNonZero`.

---

## A help flag is never an instruction

Every module routes its help check through `handlers/cli/help_flags.wants_help()`, evaluated **before** any subcommand dispatch. A flag in a later slot is never discarded in favour of running the subcommand: `drone @memory rollover push --help` describes the fleet-wide `per_branch` reset, it does not perform it.

A dashed flag (`--help`, `-h`) counts anywhere on the line. The bare word `help` counts anywhere only for modules whose subcommands take no free text (`rollover`, `config`, `templates`, `pool`, `lint`, `push`, `todo`, `health`); for `search`, `symbolic` and `verify` it counts in the first slot only, so `drone @memory search rollover help` stays a three-word query.

`handlers/cli/json_flag.py` is the sibling handler for `--json`, and `wants_json()` is deliberately read *after* the help check for the same reason: `--help --json` is still a question, so it prints help and emits no payload. The machine surface itself is in [config_verbs.md](config_verbs.md).

---

## `watch` is a module, and the entry point imports no handlers

`drone @memory watch` is `modules/watch.py` (CLI routing) over `handlers/monitor/watch_runner.py`
(the session: start, report, block, shut down on Ctrl+C). `apps/memory.py` imports no handlers
(`encapsulation`); a contract test fails the suite if any handler import appears in the entry point.

No-args starts the watcher (the live contract), with the Level 2
introspection block printed as the watcher's banner, so the operator sees which
handlers it is wired to before it takes over the terminal.

**Every `apps/modules/*.py` ships a `__main__` block, so all of them must survive
direct execution.** Their imports are absolute: a relative import dies with *"attempted relative
import with no known parent package"* under `python3 apps/modules/<module>.py --help`, invisible when
routing through the entry point imports them as a package. A contract test scans the whole directory.

---

## Related

- [rollover_pipeline.md](rollover_pipeline.md) — the engine `watch` and `rollover` drive
- [config_verbs.md](config_verbs.md) — `drone @memory config` and the `--json` machine surface
- [quality_and_proof.md](quality_and_proof.md) — the contract tests named above
