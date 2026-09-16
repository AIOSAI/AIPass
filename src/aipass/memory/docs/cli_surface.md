# The CLI surface

**Branch** memory · **Code** `apps/memory.py`, `apps/handlers/cli/`, `apps/modules/watch.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

How this branch's entry point routes, refuses, exits and logs. The verb list itself is
`drone @memory --help`; the bare `drone @memory` starts the watcher and prints the live
introspection block as its banner.

---

## A correct refusal must not become a runaway log

On 2026-08-16 @trigger raised `memory_extractor.log` CRITICAL at 634 lines/min. The safety valve was
working exactly as designed — it was refusing to archive entries an external branch had written at the
wrong end of its array — but it logged one `WARNING` **per refused entry**, each carrying the full
entry (~800 bytes). One pass over one file produced **97 warning lines in a single second**.

The valve's behaviour is unchanged; its volume is. One summary line per array per run names the
count and the reason; the per-entry detail moved to `DEBUG`, where it stays recoverable while
debugging without flooding a routine run.

The wall was also hiding the thing worth alarming on. When a file is over its limit and *nothing*
is archivable, the detector re-fires on it forever and refuses the same entries every run — a skip
loop. That case now says `NOTHING DRAINED` in words and names the two shapes that cause it: an
array that is not newest-first, or entries carrying no usable `number`. Same species as the
auto-compact skip loop behind DPLAN-0290 item 3: *a lane whose refusals are all correct can still
be a lane that never drains.*

The valve itself is in [rollover_pipeline.md](rollover_pipeline.md).

---

## An unknown argument exits non-zero

Patrick's standing ruling: an unknown command or argument **fails**. This branch printed the correct refusal
on all three shapes and then exited **0** — @devpulse's fleet sweep of 2026-09-07 named it as the only branch
failing every probe. Every door in `main()` returned `None` and the `__main__` block called `main()` without
passing the result to `sys.exit`, so the refusal was contradicted by the one half a script reads. Fixed in
FPLAN-0492 wave 6, 2026-09-07:

| probe | before | now |
|---|---|---|
| `drone @memory definitely_not_a_verb_xyz` | 0 | **1** — nothing routed |
| `drone @memory --definitely-not-a-flag` | 0 | **1** — a dashed token nothing routes is the same refusal |
| `drone @memory rollover not_a_real_subarg_xyz` | 0 | **2** — routed, then refused |

The two codes differ on purpose: `handle_command()` returning `True` means *I handled this*, not *it worked*,
so a refused sub-argument is indistinguishable from a successful run without the flip. The modules already
called `error()`, which marks the failure (`cli/display.mark_command_failed`) — only the seam was missing, so
the cure is `reset_command_state()` at the top of `main()` and `resolve_exit(True)` on the routed path, the
same idiom @ai_mail and @devpulse carry. `--help`, `--version`, a bare `drone @memory` and every working verb
still exit 0, pinned alongside the three refusals in `TestUnknownArgumentExitsNonZero`.

---

## A help flag is never an instruction

Every module routes its help check through `handlers/cli/help_flags.wants_help()`, evaluated **before** any subcommand dispatch. Modules used to read `args[0]` only, so a flag in a later slot was discarded and the subcommand ran instead — `drone @memory rollover push --help` performed the fleet-wide `per_branch` reset it was being asked to describe.

A dashed flag (`--help`, `-h`) counts anywhere on the line. The bare word `help` counts anywhere only for modules whose subcommands take no free text (`rollover`, `templates`, `pool`, `lint`); for `search`, `symbolic` and `verify` it counts in the first slot only, so `drone @memory search rollover help` stays a three-word query.

`handlers/cli/json_flag.py` is the sibling handler for `--json`, and `wants_json()` is deliberately read *after* the help check for the same reason: `--help --json` is still a question, so it prints help and emits no payload. The machine surface itself is in [config_verbs.md](config_verbs.md).

---

## `watch` is a module, and the entry point imports no handlers

`drone @memory watch` was a built-in on `apps/memory.py`, which therefore imported
two `monitor/` handlers directly — the one `encapsulation` violation on the branch.
It is now `modules/watch.py` (CLI routing) over `handlers/monitor/watch_runner.py`
(the session: start, report, block, shut down on Ctrl+C). A contract test fails the
suite if any handler import reappears in the entry point.

No-args still starts the watcher — that is the live contract — with the Level 2
introspection block printed as the watcher's banner, so the operator sees which
handlers it is wired to before it takes over the terminal.

**Every `apps/modules/*.py` ships a `__main__` block, so all of them must survive
direct execution.** Six relative imports in `rollover.py` and `pool.py` meant they
did not: `python3 apps/modules/rollover.py --help` died with *"attempted relative
import with no known parent package"* — the same defect class that left `watch`
dead, invisible because routing through the entry point imports them as a package.
All six are absolute now, and a contract test scans the whole directory.

---

## Related

- [rollover_pipeline.md](rollover_pipeline.md) — the engine `watch` and `rollover` drive
- [config_verbs.md](config_verbs.md) — `drone @memory config` and the `--json` machine surface
- [quality_and_proof.md](quality_and_proof.md) — the contract tests named above
- [known_issues.md](known_issues.md) — what is still open on this surface
