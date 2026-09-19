[<- Back to the README](../README.md)

# The service and the reload sentinel

**Branch** trigger · **Code** `apps/log_watcher_service.py`, `apps/handlers/service_control.py`, `apps/handlers/reload_sentinel.py`, `templates/trigger-log-watcher.service.template`

Persistent log watching runs as a systemd user unit, `trigger-log-watcher.service`. The unit
file is installed from `templates/` on first need and the process handles SIGTERM/SIGINT for
a clean shutdown.

---

## Asking systemd about the unit

```bash
systemctl --user status trigger-log-watcher    # Check watcher service
systemctl --user restart trigger-log-watcher   # Restart watcher
```

`drone @trigger medic on` installs and starts the unit if it is not running, and
`medic off --forever` stops it. On a host with no systemd at all — macOS, Windows, a bare
container — every door here probes `shutil.which("systemctl")` first and refuses by name
rather than reporting a unit that failed: `medic status` says the watcher is unavailable
because the host has no systemd, not that it is stopped.

---

## The reload sentinel

**The service reloads itself when handler code changes** (`handlers/reload_sentinel.py`). It is a long-running process that imports trigger's handlers once and holds them for its whole life, so a fix shipped to disk does nothing until it restarts. That gap cost this branch 25 hours of a signature fix reported live while the old code was still running, twice mistaken for the fix being incomplete. Remembering to restart after shipping is a human remembering something — the mechanism that already failed — so the process now notices for itself.

Every 30s it compares the mtimes of `apps/handlers/**.py` and `apps/modules/**.py` against the snapshot taken when it started. On a change it exits `75` (`EX_TEMPFAIL`) and systemd's `Restart=on-failure` brings up a fresh interpreter that imports everything from disk. Deliberately a restart, not `importlib.reload()`: handlers register callbacks on the event bus, and reloading in place leaves the bus holding the old function objects.

Two guards keep it from making things worse:

| Guard | Behaviour |
|---|---|
| **Settle** | A change is ignored until its mtime has been still for 15s, so an editor mid-save cannot restart the service into a half-written module |
| **Supervision** | A process with no `INVOCATION_ID` (run by hand, not by systemd) **never exits** — it logs loudly that it is running stale code instead. Exiting there would stop log watching entirely, trading a stale watcher for no watcher |

Reloads are recorded in `logs/reload_sentinel.jsonl` with the files that triggered them, so a restart is never indistinguishable from a crash. Tests and JSON state are not watched — only code the process actually imports.

Note the exit code is coupled to the unit: `Restart=on-failure` means exiting `0` would be read as a completed job and the watcher would stay down. If the unit ever moves to `Restart=always`, `RELOAD_EXIT_CODE` should become `0`; a test pins the two together.


---

## Related

- [log_watching.md](log_watching.md) — what the service actually watches
- [error_catchup.md](error_catchup.md) — the scan the service runs for itself at start
