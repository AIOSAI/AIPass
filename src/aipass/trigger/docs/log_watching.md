[<- Back to the README](../README.md)

# Log watching — two watchers, one owner per directory

**Branch** trigger · **Code** `apps/handlers/log_watcher.py`, `apps/handlers/watchers/log_watcher.py`, `apps/modules/branch_log_events.py`, `apps/modules/log_events.py`

The branch watcher reads `src/aipass/*/logs/*.log` and `system_logs/*.log`, parses the prax
line format, and fires `error_detected` and `warning_logged`. The centralized watcher module
still exists and deliberately declines to observe. Verbs:
`drone @trigger branch_log_events --help` and `drone @trigger log_events --help`.

---

## `drone @trigger status` reports this process, not the daemon

`drone @trigger status` prints the branch log watcher belonging to the CLI process you just
started — which has none — so it always says `Active: False` even while the systemd watcher
runs. For the live answer use `drone @trigger medic status`, which reads the service, or ask
systemd for the unit's own status.

---

**`system_logs/` has exactly one owner: the branch watcher.**
`watchers/log_watcher.start_log_watcher()` declines and returns `None`
(`SYSTEM_LOGS_OWNER` names the owner in the code); the rest of that module stays live,
because it is still the reader the startup catch-up scan uses. One owner ends the
duplicate, not the watching — the branch watcher globs `system_logs/*.log` alongside the
per-branch logs and carries the branch mapping, the parsing and the staleness handling.
`drone @trigger log_events start` says so rather than reporting a failure, and **exits 2**.
Both halves are the contract: the wording must not send a reader hunting a broken watcher,
and the exit code must not tell a caller's `&&` that a watcher is running. The refusal
travels through cli's `error()`, `main()` returns `resolve_exit(True)`, and
`reset_command_state()` at the top of `main()` stops one refusal colouring the next
command in the same process. A clean routed command is 0; an unknown command is 1; a
routed refusal is 2 — the same convention as @daemon's `schedule.py`.

**One line is counted once, even though prax writes it twice.** Every prax call
lands in *two* files: `src/aipass/<branch>/logs/<module>.log` and
`system_logs/<branch>_<module>.log`. Read as two, a single warning would become two
escalation signatures that disagree about who wrote it, because the branch copy is
attributed by the directory it sits in while the `system_logs` copy is attributed by
its filename. `_should_process()` drops a `system_logs` file when
`_system_log_branch_twin()` finds the branch copy that already covers it. Most
`system_logs` files are twin-backed; the ones with no twin (external projects, bots,
test-fixture logs) keep being watched — that is the only reason the directory is still
read at all.

**Branch attribution comes from the live tree, not a list.** `_known_branch_names()`
reads the branch directories (60s TTL) instead of trusting a hardcoded roster, so a new
branch is attributed the moment its directory exists. A static list survives as a floor
for when the tree cannot be read. `UNKNOWN` means what it says: nobody in the tree owns
this log.

**Path classification is separator-agnostic.** `classify_log_path()` matches on
`PurePath.parts` — `"aipass" in parts and "logs" in parts` for a branch log,
`"system_logs" in parts` for a system log — not on `"/logs/" in path`, which matches
forward slashes only and would skip every branch log on Windows while reporting healthy.
Pinned on both platforms from either one with `PureWindowsPath` and `PurePosixPath`.

---

## Related

- [error_catchup.md](error_catchup.md) — the scan that covers the window no watcher was up for
- [medic.md](medic.md) — what happens to an error line once it is fired
- [escalation.md](escalation.md) — the warning lane, which has no dispatch path
- [service_and_reload.md](service_and_reload.md) — the systemd unit the watcher runs under
