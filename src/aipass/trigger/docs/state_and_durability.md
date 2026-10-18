[<- Back to the README](../README.md)

# State files, the trio doctrine, and durability

**Branch** trigger · **Code** `apps/config.py`, `apps/handlers/json/`

Every runtime file this branch owns lives in `trigger_json/`, except the log watcher's own
position file at the branch root. This page is the naming rule that keeps live state off the
regenerated filenames, the one-shot migration behind it, and the durability rules of the
helpers underneath.

---

## What is on disk, and what a checkout contains

Nothing under `trigger_json/` is in git — it is runtime state, written by the
running system. The operator config lives at
`trigger_json/custom_config/trigger.config.json` and is created by
`config_loader.load()` on the first read, so on a fresh clone that directory
does not exist yet. It is named here in prose rather than drawn into the tree
above for exactly that reason: the tree describes what a checkout contains.

**Live state never sits on a trio filename.** `json_handler` owns every
`<module>_<config|data|log>.json` name in `trigger_json/`: it validates such a
file against the structure its type declares and regenerates it when the shape
does not match. That owner is the fleet json service behind the shim, and the
default it regenerates from is **in code** (`json_service._default_document`),
not an on-disk template directory. The service recomputes the target directory on
every call, so nothing here is captured at import.

A hand-written file on a trio name would be replaced with a blank template by the
first trio call that resolves to it, dropping every live mute, the persisted breaker
state, and the processed-hash set that stops already-handled errors being
re-dispatched. So medic state lives in `medic_state.json` and catch-up state in
`error_catchup.json`; `trigger_config.json` and `trigger_data.json` inside
`trigger_json/` are inert placeholders that `json_handler` is free to own.

`config.migrate_json_file()` moves state off a legacy name on first read: it is one-shot
(a file re-created at a legacy name afterwards belongs to its owner and is left
alone), never deletes — the old file moves to `trigger_json/.archive/` — and
leaves an unreadable legacy file in place for a human rather than guessing.

---

## Durability

- **Atomic writes:** All JSON state files use `config.atomic_write_json()` — writes to a temp file in the same directory, then an atomic rename. No partial writes on crash.
  The rename goes through `config.replace_with_retry()`, not a bare `os.replace()`: on Windows an antivirus scanner or the search indexer can hold a transient handle on the destination and `os.replace` raises `PermissionError`. 40 attempts, 5ms apart, `PermissionError` only — any other `OSError` propagates on the first attempt, and exhaustion raises rather than reporting a write that did not happen. Fleet-canonical shape, matching `@commons`.
- **File locking:** All read-modify-write cycles wrapped in `config.json_file_lock()` with `.lock` sidecar files — `fcntl.flock` on POSIX, `msvcrt.locking` on Windows. Prevents concurrent corruption from watcher + CLI. `flock` takes a fresh open file description per call, so it conflicts even inside one process. Both arms are pinned by tests: the win32 one by an injected fake `msvcrt`, the POSIX one by concurrent threads.
  Windows has no blocking `flock`, so the win32 arm polls: `msvcrt.locking(..., LK_NBLCK, 1)` on one byte of the sidecar, 100 attempts 50ms apart, and the final attempt is deliberately unguarded so the caller gets the OS's own `OSError` instead of running unlocked. The sidecar opens `"a+"`, not `"w"` — truncating a file another process byte-locks is a sharing violation on Windows.
  Scope: these two helpers serialise trigger's **own** state files — the error registry, the circuit breaker, medic state, escalation state, `.aipass/alerts.json` and `trigger_data.json`. Trio documents under `trigger_json/` are written by the fleet json service, which carries its own durability machinery; trigger's `config.py` is not on that path.
- **Atomic is not serialised.** `atomic_write_json` stops a *torn* file, not a *lost* one. Two unlocked read-modify-write cycles each produce a whole file and one update vanishes; only the lock prevents that.
- **Unreadable is not corrupt.** Reads go through `config.read_text_with_retry`, the mirror of `replace_with_retry`, because a reader meets the same transient Windows sharing window a writer does. A read still refused after 40 attempts raises `PermissionError`, and any other `OSError` raises at once: an unreadable document is never treated as a corrupt one to be regenerated.
- **Circuit breaker persistence:** Trip state, recent errors, per-fingerprint tracking all survive restarts via `trigger_cb_state.json`.
- **Off the trio path:** Hand-written live state uses filenames `json_handler`'s trio machinery does not own — see the trio doctrine above.


---

## Related

- [error_registry.md](error_registry.md) — the largest document under `trigger_json/`
- [escalation.md](escalation.md) — the operator config file and the `.jsonl` trail
- [medic.md](medic.md) — the state behind the mutes and the breaker
