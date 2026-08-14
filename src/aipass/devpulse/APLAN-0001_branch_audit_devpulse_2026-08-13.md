# APLAN-0001: Branch audit - devpulse

Tag: audit, branch-audit, 

> Branch audit @ -- living document tracking health, issues, improvements

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
| **Health** | GREEN |
| **Last verified** | 2026-08-13 (S237 re-verify) |
| **Open items** | 5 |
| **Tests** | 495 pass, 0 fail, 4 skipped (all documented gates: 3× WATCHDOG_INTEGRATION=1 live-dispatch, 1× covered-by-unit-test note) |
| **Seedgo** | 100% with bypasses / 98% without (flag-measured, all 9 rules off; architecture-only pull = 99%, its 1 honest finding: spawn has no manager template — not ours to fix) |
| **Bypass entries** | 9 total: 1 measured live (architecture, branch-wide by mechanism, annotated) / 8 file-scoped unmeasured (last measured: 2026-08-13, architecture only) |
| **Test coverage** | 47/49 public functions (95%) — see open item 1 |

## Current State

### Summary
- Orchestration hub + admin seat: only agent with git write, only seat that dispatches any citizen (DPLAN-0288 signed birth-cert privilege, 5-leg verify, never cached).
- 4 modules discovered live: feedback, admin_grant, watchdog, compass — all four exercised in production within the last 24h (watchdog ran the entire DPLAN-0290 night shift; admin lane dispatched @baud; compass queried at forks; feedback checked at /prep).
- Suite 488 green in 177s. Seedgo 100%. Archive tidy (old plans + apps(disabled), nothing live pointing in).

### Architecture
Standard branch layout. apps/handlers split: watchdog (agent/registry/schedule/timer), owner/admin_grant (ceremony verbs: keygen, mint, verify), compass (SQLite/FTS5 store), feedback (cross-project mailbox). Watchdog resolves targets through main registry THEN projects/*/*_REGISTRY.json sweep (local wins — added DPLAN-0290 item 0).

### What Works Well
- Watchdog: battle-proven — armed 7 times over one night (5 dispatch watches + baud long-build), zero misses, projects/* resolution fresh and tested both ways.
- Admin grant lane: ceremony complete, 5-leg verify live, tamper canary in place, 486-suite era closeout audit 100%.
- Compass: curation cadence holding (one review per /prep since DPLAN-0246).
- Memory hygiene: todos reconciled against reality at every /prep; rollover healthy.

## Issues Found

### Open

- [ ] canonical_payload() + compute_signature() (apps/handlers/owner/admin_grant.py) have no DIRECT tests — covered only through mint/verify flows. Small red-first test add; signing primitives deserve first-class pins.
- [ ] Measure the 8 file-scoped bypass rules control-first (both lanes, rule C method) — the S232 audit never opened bypass.json at all; only the architecture rule is measured so far.
- [ ] observations.json health flag reads at_limit (15/15) — rollover will drain on next @memory pass; verify it actually fires (ties to DPLAN-0283 date-valve fix, dark until rollover runs).
- [ ] docs.local/design_backlog.md holds 10 open design items (incl. checks-watch-per-push #9, memory threshold asymmetry #10) — periodic triage with Patrick.
- [ ] docs.local/patrick_queue.md holds 16 pending decisions — walk when Patrick says clear-some-calls.

### Resolved

- [x] Rule E in our own house (S237) — all 4 modules gated help at args[0] only; seedgo's new help_flag_safety standard caught what the S232 self-audit missed (never probed trailing position). Fixed with whole-sequence _wants_help predicate in all four, red-first, +7 tests incl. an over-match guard (bare 'help' only at position 0). Live-verified through drone.
- [x] APLAN's own "0 bypasses" line was FALSE (S237) — 9 rules existed since 2026-03-25; the S232 audit never opened bypass.json. Quick Status corrected, both seedgo scores now published, architecture rule measured live (1 real finding) and annotated with its true width (no file key = all 106 files).
- [x] Zero-todo BAUD card (quick_status two-writer clobber) — fixed fleet-side in DPLAN-0290 item 4, live-proven twice incl. a real plan close 08-13.

## What Needs Doing

### devpulse to handle
- [ ] Direct tests for canonical_payload() + compute_signature() — red-first, small.
- [ ] Verify observations rollover drains after @memory's date-valve fix goes live.

### Tracked elsewhere
- [ ] spawn manager-template gap — the one honest architecture finding (and the reason the branch-wide bypass rule exists; the rule dies when spawn ships the template). @spawn's queue; branch-level bypass scope routed to @seedgo.
- [ ] Design backlog triage — docs.local/design_backlog.md (10 items).
- [ ] Patrick decision queue — docs.local/patrick_queue.md (16 items).
- [ ] Hooks perf work PARKED (todo #130, only with Patrick fully present) — listed here for completeness, not devpulse-owned.

## Dispatch Log

| Date | Action | Result |
|------|--------|--------|
| 2026-08-13 | Initial self-audit (DPLAN-0291 fleet round) | GREEN — 488/488+4 skip, seedgo 100%, "0 bypasses" (WRONG — see S237), 4 open items logged |
| 2026-08-13 | S237 re-verify after seedgo's help_flag_safety standard shipped | GREEN — help-flag trap fixed in all 4 modules red-first (+7 tests, 495 green), bypass line corrected (9 rules, 1 measured live), scores 100%/98% both published (98 = flag-measured all rules off) |

## Relationships
- **Related DPLANs:** DPLAN-0291 (fleet audit round, this APLAN is the self slot), DPLAN-0290 (night shift — watchdog projects/* fix), DPLAN-0288 (admin lane)
- **Related FPLANs:** FPLAN-0401 (admin grant closeout — last full-branch polish before this audit)
- **Owner branch:** @devpulse
- **Seedgo:** `drone @seedgo audit aipass @devpulse`

## Notes
Session notes, discoveries, changes. Stamp each entry: session number + date.

**S232 (2026-08-13):** Initial audit created as the system's FIRST APLAN, during the DPLAN-0291 fleet round (Patrick's directive: every citizen audits, waves of 2, devpulse included). All four modules live-verified in production within 24h rather than re-probed synthetically — the night shift was the integration test. Suite 488 green / 4 documented skips, seedgo 100%, no type errors, 0 bypasses, archive tidy. Two signing primitives found untested directly (only via flows) — logged, not patched mid-audit.

**S237 (2026-08-13):** Seedgo's new help_flag_safety standard caught all four devpulse modules gating help at position zero only — the exact rule E trap this branch routed around the fleet all day, missed in our own house because the S232 self-audit never probed the trailing position. Fixed with a whole-sequence predicate in all four modules, red-first, seven new tests including an over-match guard. The same session corrected a false line in this very document: "0 bypasses" — nine rules existed since March. The architecture rule was measured control-first (pulled, audited, restored): genuinely live, one real finding (spawn manager-template gap), but branch-wide by mechanism — reason annotated with the measured width. Both scores now published: 100% with bypasses, 99% without. The auditor's own audit had the auditor's own blind spots; the standard built from the round is what caught them.

## Listen (TTS-friendly summary)

Devpulse is healthy. As of the August thirteenth re-verify, four hundred ninety five tests pass with four documented skips, seedgo scores one hundred percent with bypasses and ninety eight without, the one honest finding being a missing manager template in spawn. The help flag trap that hit the whole fleet was found in all four devpulse modules by seedgo's new standard and fixed the same afternoon, red first. The earlier claim of zero bypass entries was wrong: nine rules exist, one measured live and annotated, eight file scoped still to measure. Open items: signing primitives lack direct tests, the eight unmeasured bypass rules, the observations rollover check, and the two standing queues, design backlog and Patrick's decision queue. Nothing red, nothing urgent.

Last verified 2026-08-13.

---
*Created: 2026-08-13*
*Updated: 2026-08-13*
