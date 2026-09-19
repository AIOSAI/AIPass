[<- Back to the README](../README.md)

# State files, the trio doctrine, and durability

**Branch** trigger · **Code** `apps/config.py`, `apps/handlers/json/`

Every runtime file this branch owns lives in `trigger_json/`, except the log watcher's own
position file at the branch root. This page is the naming rule that keeps live state off the
regenerated filenames, the one-shot migration behind it, and the durability history of the
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
does not match. Since the json sweep (2026-09-03) that owner is the fleet
service behind the shim, and the default it regenerates from is **in code**
(`json_service._default_document`), not an on-disk template directory — the
`json_templates/` this branch still carried was retired on 2026-09-07 precisely
because nothing read it. The service recomputes the target directory on every
call, so nothing here is captured at import.
Medic state and catch-up state used to live at `trigger_config.json` and
`trigger_data.json` — both trio names for module `trigger`, both hand-written,
neither matching the template. Any trio call resolving to caller module
`trigger` would have replaced them with blank templates, dropping every live
mute, the persisted breaker state, and the processed-hash set that stops
already-handled errors being re-dispatched. The state moved to
`medic_state.json` and `error_catchup.json`; the trio names are now inert
placeholders that `json_handler` is free to own.

`config.migrate_json_file()` performs the move on first read: it is one-shot
(a file re-created at a legacy name afterwards belongs to its owner and is left
alone), never deletes — the old file moves to `trigger_json/.archive/` — and
leaves an unreadable legacy file in place for a human rather than guessing.


A third, `json_templates/`, was retired on 2026-09-07 (FPLAN-0492 wave 5). It carried
an `__init__.py` and `default/{config,data,log}.json`, dead since the json sweep
because the fleet json service generates its defaults **in code** and reads no
on-disk template. Measured at zero references outside its own directory, then moved
to `apps/.archive/json_templates/` rather than deleted. `.archive/` is gitignored
with no exceptions, so in git this lands as a deletion of four files; the copy on
disk is a local recovery path only, and the disposal zone is cleaned without warning.

---

## Durability

> **On the numbers below.** Every concurrency count in this section (100 appends / 62 on
> disk, 98 of 100 on Windows CI, 99 of 100 on Linux CI, 0 losses in 1500 runs, 4 threads
> x 60 entries) is a **dated lab or CI measurement from the run that found the defect**,
> not a claim about tonight's tree. They are kept because the defect and its proof are the
> point. Re-measured tonight: only that the helpers still exist, are still imported by the
> handlers named, and that the suite pinning them is green. Anything else here is
> unverified as of 2026-09-05 by design — the original conditions no longer exist.

- **Atomic writes:** All JSON state files use `config.atomic_write_json()` — writes to a temp file in the same directory, then an atomic rename. No partial writes on crash.
  The rename goes through `config.replace_with_retry()`, not a bare `os.replace()`: on Windows an antivirus scanner or the search indexer can hold a transient handle on the destination and `os.replace` raises `PermissionError`. 40 attempts, 5ms apart, `PermissionError` only — any other `OSError` propagates on the first attempt, and exhaustion raises rather than reporting a write that did not happen. Fleet-canonical shape, matching `@commons`.
- **File locking:** All read-modify-write cycles wrapped in `config.json_file_lock()` with `.lock` sidecar files — `fcntl.flock` on POSIX, `msvcrt.locking` on Windows. Prevents concurrent corruption from watcher + CLI. Both arms are pinned: the win32 one by an injected fake, the POSIX one by measurement (4 threads x 60 entries, peak 1 holder — `flock` takes a fresh open file description per call, so it conflicts even inside one process).
  Scope, after the json sweep: these two helpers serialise trigger's **own** state files — the error registry, the circuit breaker, medic state, escalation state, `.aipass/alerts.json` and `trigger_data.json`. Trio documents under `trigger_json/` are written by the fleet json service, which carries its own durability machinery; trigger's `config.py` no longer sits on that path.
  This line said "all" from the day it was written and was **not true until 2026-08-16**: the then-local `json_handler`'s own `log_operation`, `increment_counter` and `update_data_metrics` read a document, changed it in memory and wrote it back with no lock at all. Those three moved to prax with the sweep — `increment_counter` and `update_data_metrics` no longer exist anywhere in this tree. Atomic is not serialised — `atomic_write_json` stops a *torn* file, not a *lost* one, and having the atomic helper is exactly what made the gap look closed. Measured on the unfixed handler across 4 processes: **100 appends asked, 62 on disk, 38 lost silently, every call returning `True`.** After the fix, 100 of 100. Found by checking my own paths against a defect @api reported in theirs (`6cd8f22c`), not by anyone auditing this claim.
- **The Windows lock was a silent no-op until 2026-08-18.** `json_file_lock` carried `if sys.platform == "win32": yield` with the comment "single-user typical" — on Windows the context manager returned having taken *nothing*, and every caller ran unserialised while the code read as locked. Windows has no blocking `flock`, so the fix polls: `msvcrt.locking(..., LK_NBLCK, 1)` on one byte of the sidecar, 100 attempts 50ms apart, and the final attempt is deliberately unguarded so the caller gets the OS's own `OSError` instead of running unlocked. The sidecar opens `"a+"`, not `"w"` — truncating a file another process byte-locks is a sharing violation on Windows. Proven **from Linux** by a fake `msvcrt` injected into `sys.modules` with `sys.platform` patched: acquires and releases, retries-then-succeeds (exactly 3 waits, 4 lock calls), and refuses rather than yielding unlocked. A source-inspection test pins that the words "single-user typical" never come back.

- **The read side was the other half, and it was the one that lost data (2026-08-18).** `os.replace` was hardened against the Windows sharing window; every *reader* was left exposed to the identical transient. `ensure_json_exists` caught `OSError` alongside decode errors and answered both by writing a fresh template over the document — so a 5ms timing event was read as corruption and the file was thrown away. Windows CI counted it: **98 of 100** concurrent appends survived, the two lost being exactly the two on disk when one read was refused. Reproduced on Linux in three lines. Reads now go through `config.read_text_with_retry` (the mirror of `replace_with_retry`), **unreadable is no longer treated as corrupt**, and `log_operation` refuses rather than writing `[]` over a document it could not read. The lock was never involved — the destructive write lived outside the critical section, where no lock could reach it.
- **"Ensure this exists" is not "write this", and the difference was a lost entry (2026-08-19).** `ensure_json_exists` implemented create-if-missing as a replacing write, and it runs outside every lock — so two callers that both find a document missing both stage an empty template, and the loser's completes after a lock holder has written its first real entry. Linux CI counted **99 of 100**; reproduced locally at 3 losing runs in 400, with the instrumented write order naming the culprit outright (two empty-template writes staged first, one landing after a 1-entry write). No lock could have prevented it — the template write is outside every critical section by construction. Creation now goes through `config.atomic_create_json`: the staged file is **linked** into place, so a second creator is refused rather than overwriting, and the document is complete the instant it appears. 0 losses in 1500 runs after — with the same loop still losing when the replacing write is put back, so the loop has power. A filesystem without hard links degrades to the replacing write and says so in the log. **Since the json sweep this helper has no production caller left in trigger** — `ensure_json_exists` now lives in the fleet service, and `config.atomic_create_json` is reached only from `tests/test_json_durability.py` and the archived local handler (measured 2026-09-05). The account above is the history of a defect, not a description of tonight's live creation path.
- **Circuit breaker persistence:** Trip state, recent errors, per-fingerprint tracking all survive restarts via `trigger_cb_state.json`.
- **Off the trio path:** Hand-written live state uses filenames `json_handler`'s trio machinery does not own — see the trio doctrine above.


---

## Related

- [error_registry.md](error_registry.md) — the largest document under `trigger_json/`
- [escalation.md](escalation.md) — the operator config file and the `.jsonl` trail
- [medic.md](medic.md) — the state behind the mutes and the breaker
