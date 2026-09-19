[← Back to the cli README](../README.md)

# The exit seam — the idiom to copy

`mark_command_failed`, `command_failed`, `reset_command_state` and `resolve_exit`
live here, so this is the reference spelling for the whole fleet. **Three lines,
in this order**, in your branch's `main()`:

```python
def main() -> int:
    reset_command_state()                     # 1. clear the flag on entry
    ...
    handled = route_command(command, args, modules)
    if not handled:
        error(f"Unknown command: {command}")  # 2. refuse through error()
    return resolve_exit(handled)              # 3. let the seam pick the code
```

| code | meaning |
|------|---------|
| `0`  | routed, and nothing called `error()` |
| `2`  | routed, but a refusal went through `error()` |
| `1`  | not routed at all |

Why each line is load-bearing:

- **`reset_command_state()` first.** The flag is process-level state. Without
  the reset, one refused command makes every later command in the same process
  exit 2 — and under a test suite, one red test colours the next.
- **The refusal goes through `error()`, not `warning()`.** Only `error()` calls
  `mark_command_failed()`. `warning()` deliberately does not: it is for things
  that proceed. Swapping the colour without the flag changes nothing an exit
  code can see.
- **`return resolve_exit(handled)`, never a bare `0`.** A `main()` that returns
  0 on any truthy route discards the only thing the flag was recorded for. This
  is what made refusals exit 0 across the fleet (@canary's sweep): the machinery
  existed, three branches consulted it, and everywhere else `error()` printed
  red and the shell read success.
- **A caller's own `1` is never overwritten.** `resolve_exit()` checks
  `handled` *before* it looks at the flag, so a command that was never routed is
  a 1 whether or not `error()` also tripped the flag.

Cancellation is **130** (128 + SIGINT), not 0 — an interrupted run is not a
successful one. In this branch that lives in `run_cli()`, which exists as a
function rather than as bare code in the `__main__` block precisely so both it
and the crash path (`1`) can be pinned by test.

`run_cli()` in `apps/cli.py` is the process wrapper the `__main__` block calls:
it runs `main()` and maps a `KeyboardInterrupt` to 130 and an escaped exception
to 1.

Owning this API is not the same as using it. This branch owned all four names
while its own `main()` called none of them, and most of the fleet was the same
way — measure your own doors rather than assuming the seam is wired.

---
[← Back to the cli README](../README.md)
