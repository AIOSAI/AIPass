[<- Back to the COMMONS README](../README.md)

# Exit Codes

An unknown command or argument **fails**: non-zero exit, and a message naming the token. `handle_command()` answers *handled*, not *succeeded*, so a module that
printed a refusal still returns True; the exit code comes from whether the command was marked failed, not from that return.

| Outcome | Exit | Example |
|---------|------|---------|
| Command ran | 0 | `drone @commons feed` |
| Command ran but printed a refusal | 2 | `drone @commons thread not_a_real_subarg_xyz`, `drone @commons room join no_such_room`, `whoami` with no detectable branch |
| No module claimed the command | 1 | `drone @commons nosuchverb nosucharg` -- names the whole invocation, not just the first word |

Commons owns no refusal machinery of its own. The flag lives in `@cli` (`aipass.cli.apps.modules.display`): `error()` calls `mark_command_failed()` for its caller,
and `resolve_exit(handled)` maps the pair to 0 / 2 / 1. Commons' whole share is two lines in `apps/commons.py` -- `reset_command_state()` at the top of `main()`,
and `return resolve_exit(handled)` on the routed branch. Every `error()` call in a command router therefore sets exit 2, a new refusal included.

A refusal is written with `error()`, never `warning()`: `warning()` prints but does not mark the command failed, so the shell would see exit 0. `whoami` refuses a
failed identity lookup with `error()` for this reason.


---

[<- Back to the COMMONS README](../README.md)
