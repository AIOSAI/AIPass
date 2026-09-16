# Log watching — two watchers, one owner per directory

**Branch** trigger · **Code** `apps/handlers/log_watcher.py`, `apps/handlers/watchers/log_watcher.py`, `apps/modules/branch_log_events.py`, `apps/modules/log_events.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

The branch watcher reads `src/aipass/*/logs/*.log` and `system_logs/*.log`, parses the prax
line format, and fires `error_detected` and `warning_logged`. The centralized watcher module
still exists and deliberately declines to observe. Verbs:
`drone @trigger branch_log_events --help` and `drone @trigger log_events --help`.

---

## `drone @trigger status` reports this process, not the daemon

`drone @trigger status` prints the branch log watcher belonging to the CLI process you just
started — which has none — so it always says `Active: False` even while the systemd watcher
runs. For the live answer use `drone @trigger medic status`, which reads the service, or ask
systemd for the unit's own status. The README used to claim this command showed "event bus +
medic state", which it never did.

---

**`system_logs/` has exactly one owner: the branch watcher** (the owner's ruling,
2026-08-14). Both watchers used to register the directory.
`watchers/log_watcher.start_log_watcher()` now declines and returns `None`
(`SYSTEM_LOGS_OWNER` names the owner in the code); the rest of that module stays live,
because it is still the reader the startup catch-up scan uses. The ruling ends the
duplicate, not the watching — the branch watcher globs `system_logs/*.log` alongside the
per-branch logs and carries the branch mapping, the parsing and the staleness handling.
`drone @trigger log_events start` says so rather than reporting a failure — and since
2026-09-08 it also **exits 2** rather than 0. Both halves are the contract: the wording
must not send a reader hunting a broken watcher, and the exit code must not tell a
caller's `&&` that a watcher is running. Exiting 0 for eighteen months meant
`log_events start && <next>` ran `<next>` with nothing watching. The refusal now travels
through cli's `error()`, `main()` returns `resolve_exit(True)` instead of a literal `0`,
and `reset_command_state()` at the top of `main()` stops one refusal colouring the next
command in the same process. A clean routed command is still 0; an unknown command is
still 1; a routed refusal is 2. Ruled by @devpulse over this branch's own 2026-08-14
reading, following @daemon's identical call at `schedule.py:50-52`.

**One line is counted once, even though prax writes it twice.** Every prax call
lands in *two* files: `src/aipass/<branch>/logs/<module>.log` and
`system_logs/<branch>_<module>.log`. The branch watcher globs both trees, so a single
warning became two escalation signatures — and the two disagreed about who wrote it,
because the branch copy is attributed by the directory it sits in while the
`system_logs` copy is attributed by guessing at its filename. The reported pair
(2026-08-14) was `0249c13b4d64` `HOOKS` and `690de8d87cdc` `UNKNOWN`, the same three
sample lines, consecutive sequence numbers 8514/8515 — one reader, two files, not two
readers. `_should_process()` now drops a `system_logs` file when
`_system_log_branch_twin()` finds the branch copy that already covers it: measured
across the tree on 2026-08-14, 230 of 243 `system_logs` files were twin-backed and 229 of
those twins were written within one second of their system copy. Re-measured 2026-09-05:
**334 of 346 twin-backed, 12 with no twin** (`telegram-bot-*`, external projects such as
`chess_perft` and `marketstand_*`, and test-fixture logs). The untwinned ones keep being
watched — that is the only reason the directory is still read at all.

**Branch attribution comes from the live tree, not a list.** `_known_branch_names()`
reads the branch directories (60s TTL) instead of trusting a hardcoded roster. The
roster held 11 names against 17 branches, so every `system_logs` file belonging to
@hooks, @backup, @commons, @daemon, @skills or @aipass was reported as `UNKNOWN` — the
fault was the list, not the log. The static list survives as a floor for when the tree
cannot be read. `UNKNOWN` now means what it says: nobody in the tree owns this log.

**Path classification is separator-agnostic.** `_classify_log_path()` matches on
`PurePath.parts` — `"aipass" in parts and "logs" in parts` for a branch log,
`"system_logs" in parts` for a system log — not on `"/logs/" in path`. The string
form only ever matched forward slashes, so on Windows every branch log classified
as foreign and was silently skipped: the watcher would have run, reported healthy,
and processed nothing. Pinned on both platforms from either one with
`PureWindowsPath` and `PurePosixPath` (2026-08-18, reported by @devpulse from
Windows CI).

---

## Related

- [error_catchup.md](error_catchup.md) — the scan that covers the window no watcher was up for
- [medic.md](medic.md) — what happens to an error line once it is fired
- [escalation.md](escalation.md) — the warning lane, which has no dispatch path
- [service_and_reload.md](service_and_reload.md) — the systemd unit the watcher runs under
