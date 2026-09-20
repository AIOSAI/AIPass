[<- Back to the README](../README.md)

# Command surface

What the entry point routes, what it answers, and what it exits with.
`apps/canary.py` holds no business logic: it discovers modules, routes to them,
and turns their answer into an exit code.

## The forms

| Form | What happens |
|------|--------------|
| `drone @canary` | The self-map: identity line, discovered modules with their one-line descriptions |
| `drone @canary --help` / `-h` / `help` | The reference: usage, commands, flags, exit codes, examples |
| `drone @canary --version` / `-V` | `CANARY v<version>` |
| `drone @canary <command>` | Routed to the first discovered module that claims it |
| `drone @canary <command> --help` / `-h` | That command's own help, without executing it |

The self-map and the reference answer different questions and neither contains
the other. The self-map lists modules and never lists verbs; the reference lists
verbs and never names the module count. Ask the self-map what is present today,
ask the reference how to call it.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | The command was handled |
| 1 | Unknown command |
| 2 | A routed command refused |

`handle_command` returning `True` means "handled", not "worked". `main()` clears
the shared failure flag first and returns `resolve_exit(True)`, so a refusal
printed through the shared `error()` becomes exit 2 rather than a silent 0. A
refusal that exits 0 is a lie to every non-human caller, and this branch told
that lie for every routed command until the note store's parse refusal needed
the flip. Refusal text goes to stderr; stdout stays empty.

## Subcommand help never executes

The `<command> --help` check runs against the remaining arguments *before*
routing, so the help path cannot fall through into the command. A stub module
pins it: help rendered, command not run.

## What the help pages were missing

Before deleting this page's predecessor — a hand-typed command table in the
README — the table was diffed against the dispatcher in both directions. The
table itself was accurate: every row routed, every exit code matched, no
documented verb was dead. The gap was the other way round.

Routed by the module, named on no help page:

- a bare `drone @canary note`, which prints the module's own map and its store path
- `note help` as a bare word, alongside the two flag spellings
- `note -h`
- `--help` or `-h` *anywhere* in a subcommand's arguments, so `note add --help`
  prints help and stores nothing

Routed by the entry point, missing from its own reference: the third help form
`help`, which the flags block never listed, and the exit-code contract above,
which lived only in the README. Both help pages were cured at the source rather
than described on a page; the entry point and the note module carry the fix.

## Versions

`--version` renders `__version__` in `apps/canary.py`. That constant is the one
value to change; the file header comment beside it carries the same number and
is never read by code, so the two are bumped together. The branch's test suite
pins the rendered output against the constant, not against a literal.

## Known defect, not cured here

A module that raises inside `handle_command` is misreported. `route_command`
catches the exception, logs it through the shared logger and answers `False`, so
`main()` prints `Unknown command: <cmd>` and exits 1 for a command that exists.
Read in source, unfixed, kept deliberately: this branch reports defects rather
than quietly repairing them, and the note module catches its own errors so no
live verb takes that path today.

[<- Back to the branch README](../README.md)
