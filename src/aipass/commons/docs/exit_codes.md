[<- Back to the COMMONS README](../README.md)

# Exit Codes


The owner's standing ruling: an unknown command or argument **fails** -- non-zero exit, message naming the token. Commons broke it everywhere at once until
this wave: `handle_command()` answers *handled*, not *succeeded*, so a module that printed a refusal still returned True and `main()` turned that into exit 0. Measured
before the cure, `drone @commons thread not_a_real_subarg_xyz` printed `Invalid post_id - must be an integer` and reported success to the shell that called it.

| Outcome | Exit | Example |
|---------|------|---------|
| Command ran | 0 | `drone @commons feed` |
| Command ran but printed a refusal | 2 | `drone @commons thread not_a_real_subarg_xyz`, `drone @commons room join no_such_room`, `whoami` with no detectable branch |
| No module claimed the command | 1 | `drone @commons nosuchverb nosucharg` -- names the whole invocation, not just the first word |

Commons owns no refusal machinery of its own. The flag lives in `@cli`, which three other branches already use: `error()` calls `mark_command_failed()` for its caller,
and `resolve_exit(handled)` maps the pair to 0 / 2 / 1 (`cli/apps/modules/display.py:57-81`). Commons' whole share is two lines in `apps/commons.py` -- 
`reset_command_state()` at the top of `main()`, and `return resolve_exit(handled)` on the routed branch. All 62 existing `error()` call sites across the 21 command
routers changed behaviour without being edited, and a refusal written tomorrow inherits the exit code for free.

One call site needed changing rather than inheriting: `commons_identity.py::_handle_whoami` announced a failed identity lookup with `warning()`, which prints but never marks, so
`whoami` reported success while telling you it could not answer (canary's warning-refusal sweep, 2026-09-07). It is an `error()` now.


---

[<- Back to the COMMONS README](../README.md)
