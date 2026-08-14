# APLAN-0015: Branch audit - daemon

Tag: audit, branch-audit, daemon

> Branch audit @daemon -- living document tracking health, issues, improvements

---

## What is an APLAN?

Audit Plans (APLANs) are **living documents** -- track ongoing health, issues, improvements for specific branch. Unlike DPLANs (capture moment thinking) or FPLANs (track build), APLANs persist across sessions + grow as branch evolves.

**This IS for:**
- Recording branch health status + key metrics
- Tracking bugs, issues, improvement opportunities as discovered
- Logging what's been dispatched + results
- Maintaining clear picture: open vs resolved
- Serving as working memory next time we touch this branch

**This is NOT for:**
- Building code -- that's FPLAN
- One-off design thinking -- that's DPLAN
- Quick fixes -- just do those directly

**APLANs never trimmed, rarely closed.** They accumulate history. When branch gets major overhaul, start fresh APLAN + archive old one.

**Keep items current.** Check boxes when work done. Add ! issues as found. Update metrics when you verify. Document should always reflect reality.

---

## Quick Status

| Metric | Value |
|--------|-------|
| **Health** | YELLOW |
| **Last verified** | 2026-08-13 (S34, DPLAN-0291 fleet audit round) |
| **Open items** | 8 |
| **Tests** | 411 pass, 0 fail (406 at session start, +5 written this audit) |
| **Seedgo** | **100%** with bypasses / **99%** with the bypass list emptied (44 standards) |
| **Bypass entries** | 22 (pruned from 26) |
| **CLI score** | Nav 5/5 — all 12 documented commands route and all 12 `--help` paths render. Output 4/5 — `update` digest reads empty against live data |

**Why YELLOW, not GREEN:** the headline numbers are clean (100%, 411 green, ruff clean, no type
errors) but the audit found a live safety bug in the help path, a fleet-wide health detector that
reports pure noise, and a README that documented four archived subsystems as operational. Numbers
were never the weak part.

## Current State

### Summary
- Background scheduler. Discovers every citizen's `.daemon/schedule.json` and fires due jobs by
  waking the owner. Also runs the fleet inbox sweep and the nightly steward rotation.
- 9 modules registered in the router; 6 job types (`interval`, `daily`, `hourly`, `once`, `rotation`).
- Live fleet state at audit: 6 jobs discovered, **1 enabled** (`@daemon/inbox-sweep`, daily 09:00).
  The `fleet-steward` rotation job is deliberately OFF, parked awaiting Patrick's review session.

### Architecture
Standard 3-layer. `apps/daemon.py` routes to `apps/modules/*`, which call `apps/handlers/*`.
The scheduler is decentralized: daemon owns no schedule of its own beyond its own `.daemon/` file —
it discovers, evaluates due-ness, and fires. Two trees are swept (framework `src/aipass/*` and
project `projects/<name>/*`), each against its own registry.

### What Works Well
- **Scheduler core is sound.** `is_job_due` never reads the display-only `next_run`; due-ness is
  recomputed from `last_run` every tick, so a stale stored value cannot cause a wrong fire.
- **Fire path is well-guarded**: fcntl lock against concurrent ticks, orphan-runstate pruning
  persisted on every tick, failures stamped so a crash cannot re-fire through the rest of a window.
- **Retired CLIs degrade honestly** — `schedule` and `actions` print a migration notice pointing at
  `.daemon/schedule.json` rather than half-working.
- **Machine output is disciplined** — `queue --json` and `rotation --json` both pass
  `soft_wrap=True, markup=False` so non-TTY output stays parseable.
- Rotation state verified against @devpulse's independent disk read: OFF, 05:00, pointer clear,
  next up @backup. Matches.

## Issues Found

### Open

- [ ] **Memory health is fleet-wide noise (highest impact).** `memory_health.validate_memory_structure()`
      requires a `limits` field inside `document_metadata`. The `.trinity` schema (3.0.0) dropped it —
      caps now live in @memory's `memory.config.json` and surface as `*_meta` lines. **Measured: 0 of 17**
      branches carry the field, so `branch-health` reports **17/17 WARNING permanently**, including
      branches whose memory was updated 3 minutes earlier. A genuinely broken `.trinity` is
      indistinguishable from the noise. Not fixed here: what replaces the check is @memory's schema
      call, not daemon's.
- [ ] **The tests pin the dead schema** (rule D instance, fleet count +1). `test_memory_health.py`
      builds a synthetic fixture that *does* carry `limits`, so the suite is green while the real
      world is 0-for-17. The suite proves code matches test; it never proved test matches reality.
- [ ] **`update` digest reads empty.** Shows 0 messages / 0 sessions / focus None against a live
      inbox and 30+ recorded sessions — `data_loader` reads different paths than `.trinity/local.json`.
      Long-standing, previously documented, re-confirmed live this session.
- [ ] **`apps/modules/wakeup_ops.py` is orphaned dead code.** Not in `daemon.py`'s module list, so
      `drone @daemon wakeup-ops` returns "Unknown command" (verified live). `daemon_wakeup.py`
      references it only inside a print string. Its 9 tests are the only importers — tests keeping
      dead code alive.
- [ ] **`apps/plugins/discover_plugins()` is orphaned.** Its only remaining caller is
      `handlers/schedule/.archive/plugin_processor(disabled).py`. Its bypass rule still justifies it
      as "used by scheduler_cron" — also archived. Decide: delete the plugins package or restore a caller.
- [ ] **18 of 22 bypass rules remain unmeasured.** Only the 4 pointing at deleted files were pruned
      (the class devpulse marked safe unmeasured). The rest need the checklist-lane diff with a
      control rule first. Note: with the bypass list emptied the audit lane still scored Architecture
      100%, which *suggests* the two entry-point architecture rules are now redundant — but the audit
      lane never walks `tests/`, so that is a hint, not a measurement.
- [ ] **Module-level `--help` guards still check `args[0]` only.** The router fix below covers the
      whole CLI surface, but a direct `handle_command("run", ["--dry-run", "--help"])` call still
      executes. Defense-in-depth gap, not currently reachable from the CLI.
- [ ] **`queue` can display a `next_run` in the past.** `_calc_next_run` stamps the next slot from
      `now` at write time and ignores the once-per-day rule, so a daily job run manually at 08:47
      records "today 09:00" — a slot that will never fire. Display-only; the fire path is unaffected.
- [ ] **`todos_meta` describes a `todos` array that does not exist** in `.trinity/local.json`.
      Benign (there genuinely are no open todos) but the schema is inconsistent.

### Resolved

- [x] **A `--help` in any non-first position executed the verb instead of printing help**
      (S34 — rule E, confirmed on this branch). Each module guarded `args[0]`, so the documented
      `<verb> --help` form was always safe; but `daemon.py` only intercepted `remaining_args[0]`,
      so anything after a flag or a stray token fell through to live execution.
      Proven live using `--dry-run` as a safe canary: `run --dry-run --help` ran a tick,
      `inbox-sweep --dry-run --help` ran a sweep. The unsafe forms were **not** typed:
      `inbox-sweep --hours 48 --help` would have woken up to 5 real branches, `run x --help` would
      have fired every due job, `install-timer x --help` would have written systemd units.
      Fix: one central guard in `daemon.py` scanning every remaining arg. 3 tests, red-first.
- [x] **`update` warned "ESCALATIONS NEEDED" on stderr unconditionally** (S34) — the section header
      was emitted before the emptiness check, so every quiet digest wrote a warning to stderr above a
      stdout body reading "None - all clear". Anything capturing stderr read it as a standing alarm.
      Now warns only when escalations exist. 2 tests, red-first (the positive case passed immediately,
      proving the test is not vacuous).
- [x] **README documented four archived subsystems as live** (S34) — the 3 plugins, `scheduler_ops`,
      `actions_registry`, `task_registry` and `scheduler_cron`. Architecture tree, Modules table and
      Plugins table all corrected against the real file listing; Known Issues rewritten to only what
      reproduced this session.
- [x] **README claimed `drone @daemon activity_report` (underscore) fails** (S34) — it works; an
      explicit alias branch handles it. Verified live, claim removed.
- [x] **Passport listed retired duties** (S34) — plugin dispatch, the action registry and the
      scheduled-follow-up CRUD were all still in `what_i_do`. Rewritten to the decentralized
      scheduler, inbox sweep and rotation.
- [x] **README header said "Citizen Class: builder"** (S34) — passport says `aipass_framework`.

## What Needs Doing

### @daemon to handle (dispatch)
- [ ] Retire `wakeup_ops.py` and its 9 tests, or wire it into the router — currently neither.
- [ ] Decide the fate of `apps/plugins/` — delete the package or restore a live caller.
- [ ] Run the checklist-lane diff over the remaining 18 bypass rules, with a control rule first.
- [ ] Tighten the module-level `--help` guards to match the router (defense in depth).
- [ ] Make `_calc_next_run` respect the once-per-day rule so `queue` stops showing dead slots.

### devpulse to handle
- [ ] **Route the memory-health schema question to @memory.** What is the current health marker for
      a `.trinity` file now that `limits` is gone — presence of the `*_meta` lines, or nothing at all?
      Until that is answered, `branch-health` memory health is unusable fleet-wide, and it is @memory's
      schema to define, not daemon's to guess.
- [ ] Fleet rule-D counter +1 (the `limits` fixture above).
- [ ] `update` digest's `data_loader` paths — long-standing, spans the inbox/memory layout; worth a
      scoped FPLAN rather than an in-audit patch.

### Tracked elsewhere
- [ ] Steward rotation flip ceremony, `include_managers` decision, steward-prompt red-pen —
      all parked pending Patrick's review session. See DPLAN-0287.

## Dispatch Log

| Date | Action | Result |
|------|--------|--------|
| 2026-08-13 | DPLAN-0291 fleet audit round, self-audit | YELLOW — 3 fixes shipped red-first, 8 open items logged |

## Relationships
- **Related DPLANs:** DPLAN-0287 (rotation, parked), DPLAN-0291 (this audit round), DPLAN-0204 (decentralized scheduler)
- **Related FPLANs:** FPLAN-0394 (inbox sweep)
- **Owner branch:** @daemon
- **Seedgo:** `drone @seedgo audit aipass @daemon`

## Notes
Session notes, discoveries, changes. Stamp each entry: session number + date.

**S34 (2026-08-13):** Full self-audit for the fleet round. Every command probed live including
error and refusal paths; scheduler caution respected — no other branch's job was fired, every probe
was `--dry-run` or a read-only surface, and the rotation pointer was never touched.

The `--help` finding is worth remembering for its shape: I checked the module guards first, saw every
module correctly handle `args[0] == "--help"`, and nearly signed the surface off as safe. The hole was
one layer up in the router, and only showed when the flag was not first. Reading the code path before
typing the probe (as briefed) is what kept a real fleet wake from being the way I discovered it.

The memory-health finding is the inverse lesson: the suite has been green over a detector that has
been wrong for every branch, every run, since the schema changed. A synthetic fixture that carries a
field no real file has is worse than no test — it actively certifies the break.

## Listen (TTS-friendly summary)

Daemon is in yellow health as of August thirteenth. The numbers look green: four hundred and eleven
tests pass, seedgo scores one hundred percent with bypasses and ninety nine without, ruff is clean and
there are no type errors. But the audit found three real problems and fixed them, and logged eight more.

The most serious fix was in the help system. Every module correctly handled a help flag in first
position, but the router only checked the first argument, so a help flag typed after any other word
fell through and actually ran the command. Because daemon is the scheduler, that meant a help probe
could have woken up to five real branches, fired every due job, or installed system timer units. It was
proven safely using dry run as a canary, then fixed with a single guard that scans every argument, and
verified live.

The second fix stopped the status digest from crying wolf. It wrote escalations needed to the error
stream on every single run, even when it went on to report that everything was clear.

The biggest open problem is memory health. The checker still requires a field called limits that the
memory schema removed some time ago. Zero of seventeen branches have it, so every branch is reported
as warning forever, even one updated three minutes ago. That means a branch with genuinely broken
memory would be invisible. Daemon did not fix this because deciding what a healthy memory file looks
like now belongs to the memory branch, not the scheduler. Notably the unit tests hide this completely,
because they build a fake file that does have the field.

Also open: a module called wakeup ops that nothing imports and no command reaches, an orphaned plugin
system, and eighteen bypass rules that still need proper measurement.

Last verified 2026-08-13.

---
*Created: 2026-08-13*
*Updated: 2026-08-13*
