# The CLI contract: help flags, exit codes, output ordering

**Branch** ai_mail · **Code** `apps/ai_mail.py`, `apps/handlers/cli/help_flags.py`, `apps/modules/email.py`, `apps/modules/dispatch.py`, `apps/modules/email_send.py`, `apps/handlers/email/send.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

## Help Flags — Explain, Never Execute

A help flag anywhere in the argument list means *describe this command*, and all three
modules check for it as the first thing after the command-ownership guard in
`handle_command` — before any argument is read and before anything routes. It is not
literally statement one, and cannot be: a module has to establish the command is *its*
before it may answer for it (`email.py`, `dispatch.py`, `email_send.py`).

They used to gate help at `args[0]` only, so a flag one position later was discarded and
the command ran instead. On a messaging branch that is not a cosmetic bug:
`dispatch @target "Subject" "Body" --help` fell through to `_orchestrate_dispatch_send`
and would have **sent the mail and woken the branch** it was asked to describe. `email`,
`close all` and `reply` had the same shape against the mailbox. (Seedgo standard
`help_flag_safety`, DPLAN-0291 rule E — the router cannot fix this for us, because the
standalone `__main__` path calls `handle_command` with raw argv and never touches it.)

`apps/handlers/cli/help_flags.py` holds the whole check — `wants_help(args)`, a pure
predicate with no I/O and no imports beyond typing, so it can run ahead of every layer:

| Token | Counts as help | Why |
|---|---|---|
| `--help`, `-h` | anywhere in the sequence, **exact match** | unambiguous wherever they appear |
| `help` | position 0 only | a bare word is legitimate message content |

- **Exact match is what keeps real mail intact.** A body reading `run --help for usage`
  arrives as one quoted argument and is not that token, so it still sends. A body that is
  *exactly* `--help` explains instead — nonsense input, and explain-over-execute is the
  ruling.
- **Position 0 for the bare word**, because on this branch a subject or body can plausibly
  be the single word "help". None of the three modules owns a genuine `help` verb, so that
  slot is free; `allow_bare_word=False` exists for a module that ever does.
- **Tests assert both halves** — help printed *and* the send/wake target never called.
  Asserting only the first would pass on code that explains itself after sending the mail.
- The handler carries a documented `json_structure` bypass: the standard wants a
  `log_operation()` call, which would make the help gate depend on the JSON layer it must
  run in front of, and would log a non-event on every invocation. @memory, @trigger and
  @drone bypassed the identical file the same day.

## Exit Codes

`0` success · `1` unroutable command · `2` routed but failed.

Handlers return `True` for "I recognised **and ran** this command", which is not "it
worked". `error()` sets a process failure flag that `main()` maps through
`resolve_exit()`, so a failed delivery or an invalid reply_path exits nonzero instead of
reporting success to the caller's script.

Returning `False` for a failure is not a smaller mistake — it is a different bug:
`route_command()` walks modules until one returns `True`, so a handler that ran a send,
failed, and returned `False` sent the router on to the **next** module, which ran the
same send again and then printed `Unknown command: email` over a command it had just
executed. Two sent records, two error lines, one contradiction, exit 1 instead of 2.

Each module answers only for the commands it owns (`email_send.COMMANDS`,
`dispatch` for the dispatch module). A module that answers to any command name it is
handed will re-run its own work under someone else's.

### Output ordering

Progress goes to stdout and failures to stderr, and `drone` captures each stream whole
and replays **stdout first**. A progress line printed before an operation therefore
surfaces *below* the failure it preceded. Announce outcomes, not intent, on any path
that can fail — `dispatch` no longer prints `Sending dispatch email to ...` ahead of a
send that the fence may refuse.

The same rule still reads wrong on one path: `dispatch wake`'s failure line says "see the
step status **above**", and the steps replay below it. Tracked in APLAN-0006.

### Interactive send needs a terminal

`email` / `send` with no arguments means interactive mode. That is a human-only path, and
it now refuses up front when `sys.stdin` is not a TTY — usage to stderr, exit 2, no branch
list printed first.

Under `drone` the routed subprocess inherits an **open but silent** stdin pipe, so
`input()` does not raise `EOFError`; it blocks until drone's 30s routing timeout kills the
command. `EOFError` handling alone cannot cover this, because once you are waiting on the
first read, "no input yet" and "no input ever" are the same thing. The check has to happen
before the first prompt, and it lives in both halves — `send.collect_interactive_input()`
refuses, and `email_send._send_interactive()` refuses ahead of it so the listing never
prints and the exit code is right.


## Related

- [sending_and_delivery.md](sending_and_delivery.md) — the send and dispatch paths these
  help-flag and exit-code rules guard.
- [wake_pipeline.md](wake_pipeline.md) — what a `--help`-gate miss would have triggered:
  sending the mail and waking the branch it was asked to describe.
- [known_issues.md](known_issues.md) — `dispatch wake`'s output-ordering issue (the
  failure line pointing "above" the steps) is tracked there, open under APLAN-0006.
