# Known Issues

The retired plugin system, the daemon's live known issues, and the defects already resolved.

[<- daemon README](../README.md)

---

## Plugins

**The plugin system is retired.** All five plugins are in `apps/plugins/.archive/`, and the
`discover_plugins()` entry point in `apps/plugins/__init__.py` has no live caller — its only
remaining import is from an archived file. Scheduling is now decentralized: each citizen owns
`<branch>/.daemon/schedule.json` and the daemon discovers and fires. See [Scheduling Jobs](../README.md#scheduling-jobs).

| Plugin | Target | Status |
|--------|--------|--------|
| `community_rotation` | @rotating | Archived — superseded by `rotation` module + `rounds` job |
| `daily_audit` | @seed | Archived — targeted @seed, renamed to @seedgo years prior |
| `heartbeat` | @vera | Archived — @vera was not in `AIPASS_REGISTRY.json` then and is not now. It *is* a live citizen tonight, via the federated-external tier (`external/VERA-STUDIO`), so the target exists again — the plugin does not |
| `botfather_reminder` | @dev_central | Archived — Telegram stripped |
| `dev_central_monitor` | @dev_central | Archived — @dev_central is in no registry tonight |

## Known Issues

*Re-verified live 2026-09-05 (FPLAN-0490 truth pass). Items are listed only if reproduced this session.*

- **`update` digest reads empty** — reproduced 2026-09-05: `drone @daemon update` printed 0 messages
  and 0 sessions while the mailbox held 2 opened emails and `.trinity/local.json` held 16 sessions.
  `data_loader` reads different paths than `.trinity/local.json`. Long-standing.
- **`apps/modules/wakeup_ops.py` is orphaned.** Not in the router's module list, so
  `drone @daemon wakeup-ops` returns "Unknown command"; `daemon_wakeup.py` names it only inside a
  print string. Its 9 tests are the only thing importing it.
- **`apps/plugins/discover_plugins()` is orphaned** — its sole caller is an archived file.

### Resolved

- ~~Torn writes in `json_handler`~~ (2026-08-16, fleet defect 90c9e40d axis 1) — every write opened
  the target with `"w"`, truncating it before the new bytes landed; worse, `ensure_json_exists`
  answers an unreadable document by writing a template over it, so a torn read became permanent
  data loss. Measured here first, unfixed, 2 writers + 2 readers over 13,103 reads: **74.6% empty,
  17.9% unparseable, 92.5% unusable**. Now every write site routes through `_atomic_write_json`
  (staged via `tempfile.mkstemp` in the *target's own* directory, then `os.replace`; the staged
  file is unlinked on failure and the helper raises rather than swallowing). Same probe after:
  **0 of 1,410 reads unusable**. The guards travelled with the subject: this branch's json handler is
  now the fleet shim over prax's service (DPLAN-0325 pair 5), so `tests/test_json_durability.py` moved
  to `tests/.archive/deleted_2026-09-04_json_durability.py` along with the handler it pinned. The
  durability contract is prax's to hold now, and it does: `aipass/prax/tests/test_json_durability.py`
  is live there (verified 2026-09-05). **Nothing in this branch tests it any more** — correctly, since
  nothing in this branch implements it.
- ~~Memory health is fleet-wide noise~~ (2026-08-15) — `validate_memory_structure()` demanded a
  `limits` field that schema 3.0.0 dropped, so **0 of 17** branches passed and every one read
  WARNING forever. Per @memory's schema call the check now asks whether the file is *usable*:
  a metadata section, a readable `schema_version`, and the entry containers for its filename
  (`sessions`/`key_learnings`/`todos` in `local.json`, `observations` in `observations.json`).
  Caps stay @memory's — they live in `memory.config.json` as defaults deep-merged with per-branch
  overrides, and a copy here would drift. Measured after: **17 of 17 clean**, while a real
  pre-3.0.0 file (`projects/speakeasy`) is still flagged with three concrete reasons. Tests now
  pin the live `.trinity` files, not just a fixture — that pin immediately caught this branch's
  own `local.json` carrying a `todos_meta` line with no `todos` container.
- ~~`drone @daemon activity_report` (underscore) fails~~ — works; an explicit alias branch handles it.
- ~~A trailing `--help` could execute the verb~~ — the router now scans every remaining arg, not
  just the first. `inbox-sweep --hours 48 --help` used to run a real sweep and wake branches.
