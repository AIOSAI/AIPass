# CLI — Branch Prompt
<!-- Before editing or adding to this file: read .aipass/PROMPT_STYLE.md (repo root) — the prompt format rules. -->
<!-- File: src/aipass/cli/.aipass/aipass_local_prompt.md — Injected every prompt when in cli directory. -->

Shared Rich display and formatting service for every AIPass branch. Headers, success/error/warning messages, section breaks, operation templates and the exit-code seam — so every branch renders the same without duplicating formatting code.

# Where things are

The face is `README.md`, kept short for strangers. Depth lives in `docs/`, one page per subject; the directory tree and the gotchas live here, where the person editing the code sees them.

 - `docs/display_api.md` — every public symbol, signature, import path
 - `docs/exit_seam.md` — the exit-code idiom the fleet copies
 - `docs/rich_markup.md` — literal brackets, what eats placeholders
 - `docs/testing_output.md` — assert visible output, never raw bytes
 - `docs/json_handler.md` — the json shim and the circular-import exception
 - `docs/known_issues.md` — open items

# Tree

```
cli/
├── __init__.py                     top-level exports + cli_entry()
├── apps/
│   ├── cli.py                      entry point: main, run_cli, discover_modules, route_command
│   ├── modules/                    public — import from here
│   │   ├── display.py              messages, fatal, section, exit-code seam
│   │   └── templates.py            operation_start, operation_complete
│   ├── handlers/                   private — do not import from outside
│   │   ├── cli/help_flags.py       wants_help() — whole-sequence help detection
│   │   ├── json/json_handler.py    shim binding the fleet json service in prax
│   │   └── templates/              package only, no implementation
│   ├── integrations/               scaffold, no Python
│   └── plugins/                    scaffold, required by the spawn builder template
├── docs/                           the depth pages listed above
├── tests/                          suites, conftest capture helper, parked/ and .archive/
├── cli_json/                       auto-created config, data, log
└── logs/                           branch logs
```

Re-derive this with `find` before trusting it. Scaffold and dot-directories are omitted.

# Public API

Import from `aipass.cli` (short set) or `aipass.cli.apps.modules` (full set): `console`, `err_console`, `header`, `success`, `error`, `warning`, `fatal`, `section`, `escape`, `operation_start`, `operation_complete`, plus the exit seam — `mark_command_failed`, `command_failed`, `reset_command_state`, `resolve_exit`.

Signatures and examples are in `docs/display_api.md`. Do not restate them here.

# The exit seam

Three lines in `main()`, in order: `reset_command_state()` on entry, route, then `return resolve_exit(handled)`. Codes: 0 routed and clean, 2 routed but a refusal went through `error()`, 1 not routed. Cancellation is 130, in `run_cli()`.

 - Only `error()` trips the failure flag. `warning()` deliberately does not.
 - Never return a bare 0 from `main()` — it discards the flag.
 - Full reasoning: `docs/exit_seam.md`.

# Gotchas

These are the things that have actually broken here.

 - `apps/modules/` must not import `aipass.prax` — circular, prax depends on this branch. Bypassed in `.seedgo/bypass.json`. The json shim is the one exception and is safe only because prax's `__init__` is lazy.
 - The json shim binds names (`log_operation = _h.log_operation`) and never wraps them. A `def` wrapper adds a frame and the service then logs to the wrong document.
 - Import the json handler as a module, then call through it. The seedgo AST checker matches that exact shape.
 - Help gates scan the whole argument sequence with `wants_help(None, args)` — never `args[0]` alone. A flag after a subcommand must still explain, not run.
 - Display tests assert visible characters. Build captures with `make_capture_console()` from `tests/conftest.py`; a raw-byte assert makes the suite a function of the shell.
 - The `suggestion` argument to `error()` must not start with "Try:" — display adds it.
 - `handle_command()` lives in `display.py` and `templates.py`, not in `cli.py`. Both are service modules, so a bare invocation lists them under services and reports no discovered modules. That zero is correct.
 - The surface is split on markup. `header`, `success`, `section` and the templates parse it (a bare `[count]` is eaten: pass `escape(value)`); `error`, `warning`, `fatal` print literally (escaping shows the backslash). A styled literal with a literal bracket is hand-escaped. Never `markup=False` on a styled line. See `docs/rich_markup.md`.
 - Project init belongs to the aipass branch. Never re-add init routing here.
 - Every other branch prints through this surface. A change to the render functions lands everywhere at once — treat behaviour changes as fleet changes.

# Verbs

 - Live top-level verbs include `display`, `templates`, `show` and a bare `demo`; `show` is an alias of `display`, and a bare `demo` resolves by module discovery order.
 - The entry point's help page is the reference. When a verb and the help page disagree, fix the help page and bump the entry point version.

# Integration

 - Depends on `rich`, on `aipass.prax` outside `apps/modules/`, and otherwise on the standard library.
 - Provides display, templates, console access and the exit seam to every branch.
 - The import is the real entry point; the command line is a demo of it.
