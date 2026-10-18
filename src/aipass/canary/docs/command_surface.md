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
refusal that exits 0 is a lie to every non-human caller. Refusal text goes to
stderr; stdout stays empty.

## Subcommand help never executes

The `<command> --help` check runs against the remaining arguments *before*
routing, so the help path cannot fall through into the command. A stub module
pins it: help rendered, command not run.

The entry point checks the first position only. Every module goes further:

- a bare `drone @canary <command>` prints that module's short map (`note` adds
  its store path)
- `<command> help` as a bare word answers like the two flag spellings
- `--help` or `-h` *anywhere* in a command's arguments prints help and runs
  nothing, so `note add --help` stores nothing

## Versions

`--version` renders `__version__` in `apps/canary.py`. That constant is the one
value to change; the file header comment beside it carries the same number and
is never read by code, so the two are bumped together. The branch's test suite
pins the rendered output against the constant, not against a literal.

## Known defect, not cured here

A module that raises inside `handle_command` is misreported. `route_command`
catches the exception, logs it through the shared logger and answers `False`, so
`main()` prints `Unknown command: <cmd>` and exits 1 for a command that exists.
This branch reports defects rather than repairing them quietly. No live verb
takes that path: each of the five modules turns its handler's errors, unreadable
files included, into a refusal that exits 2.

[<- Back to the branch README](../README.md)
