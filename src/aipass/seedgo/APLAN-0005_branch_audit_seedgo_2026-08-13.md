# APLAN-0005: Branch audit - seedgo

Tag: audit, branch-audit, seedgo

> Branch audit @seedgo -- living document tracking health, issues, improvements

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
| **Last verified** | 2026-08-13 (S86) |
| **Open items** | 12 (0 blocking) |
| **Tests** | 1648 pass, 0 fail, 0 skip |
| **Seedgo** | **100%** (44 standards + diagnostics, 126 files) -- `help_flag_safety` 100%, all 5 own defects fixed + 5 the checker never named |
| **Seedgo with bypass OFF** | 98% (was 97%) -- `audit aipass @seedgo --no-bypass` |
| **Bypass entries** | 28 (+1: the `wants_help` predicate vs `json_structure`, measured; a second `naming` bypass was minted and then retired by renaming the file instead) |
| **Ruff** | clean (189 files formatted) |
| **Type errors** | 0 |
| **Test map** | 243 public functions, 229 tested (94%) |
| **Proof** | NOT CERTIFIED -- 3 of 5 pass |

YELLOW, not GREEN: nothing is down and every command runs, but the auditor does not
pass its own proof pack, and one advertised lookup path (`standard ruff`) returns
"Unknown standard" for a standard the audit displays.

## Current State

### Summary
- Every command in `--help` was run live this audit. Two behave differently from what
  the docs say (`standard ruff`, `diagnostics @branch`); both are documented below and
  neither crashes.
- The 100% score is real, and it sits on 27 documented exceptions. With every bypass
  rule removed the branch scores 98% (94 violations). Publishing both numbers is the
  point of auditing the auditor.
- The dominant failure mode found this session is one class, three times over: **a
  checker cannot tell a document from a document about the document.** Standards content
  files describing bad code, a README bullet describing a detector's bug, and a test
  file holding bad-pattern strings as input data all read as violations.

### Architecture
Entry point `apps/seedgo.py` is a thin router: `discover_modules()` loads `apps/modules/*.py`,
`route_command()` offers the command to each module in discovery order and the first
returning True wins. 10 modules, 9 handler directories. Checker packs are discovered from
`handlers/*_standards/`; each standard is a `*_check.py` / `*_content.py` / `*.md` triplet.

Two independent lanes consume the same checkers and this matters for every measurement
below: the **audit** lane (`audit aipass [@branch]`) walks `apps/` per branch, and the
**checklist** lane (`checklist <file>`, driven by the PostToolUse hook) runs on any single
file including `tests/`. `APPLIES_TO` says which files a standard is eligible for;
`AUDIT_SCOPE` says where a result is reported. They are different axes (`applicability.py`).

### What Works Well
- 1500 tests green in 12s, 0 skips, ruff clean, 0 type errors.
- Live-verified working: bare introspection, `--version`, `--help`, `audit aipass @seedgo`,
  `audit inbox-ids` (109 inboxes, all ids valid), `standard`, `standard cli`,
  `standards_query aipass_standards ruff_check`, `checklist <file>` (32 standards),
  `proof aipass`, `proof_query aipass_proof triplet`, `test_map @seedgo`, `permissions`.
- The incremental audit cache, the exit artifact, and the non-scored info channel all
  behave as documented.
- `.seedgoignore` and the bypass matcher share one implementation (`utils.matching_rule`)
  since the third private copy was killed in FPLAN-0384.

## Issues Found

### Open

Use checkboxes. Mark resolved items `[x]` + note which session resolved them.

- [ ] **No bypass-rot detection -- and the obvious detector is wrong 5 times out of 6.**
  Nothing tells a branch that a bypass rule has stopped suppressing anything. The
  tempting measurement is to re-run the audit with `bypass_rules=[]` and match each rule
  against the violation records that appear. Run against this branch's own 28 rules it
  called 6 dead. **Five were live:**
  - four are `tests/*` rules -- dead in the audit lane (which walks `apps/`), live in the
    checklist lane, where they suppress real `error_handling`, `naming`, `silent_catch`,
    `commented_logger`, `log_structure` and `hardcoded_path` failures on every hook run;
  - one guards `dead_code`, a branch-level standard that reports through `checks[].message`
    prose rather than a `*_violations` list. Removing it drops that standard 100 -> 95.

  Only one rule was dead in both lanes. A correct detector must (a) evaluate each rule in
  the lane its file actually lives in, and (b) canary branch-level standards through
  `check_branch()` rather than reading violation lists. A third class -- rule points at a
  file that does not exist -- needs no audit at all and is the cheapest, safest signal.
  **Fleet risk: wave 1 pruned on the naive signal** (see Dispatch Log / reported to devpulse).
- [ ] **`proof aipass` = NOT CERTIFIED, 2 of 5 proofs fail.** `readme_currency` fails on
  three counts: it recognises standard names only in a `pack checks:` prose format this
  README does not use (so 42 of 43 documented standards read as undocumented); it scrapes
  any number near a pack reference as a claimed check count; and it harvests the README
  bullet *describing this bug* into `stale_refs`. Documenting the defect makes the
  detector fail harder. `triplet` reports 6 standards with no `.md` (cli_ux,
  hardcoded_path, json_structure, readme_quality, rich_markup, subcommand_help) plus 2
  orphans -- `applicability.py` and `skip_dirs.py`, shared infrastructure living in the
  pack directory that the triplet proof has no category for.
- [ ] **`standard ruff` returns "Unknown standard".** The checker file is `ruff_check.py`,
  so the audit displays the standard as `Ruff`, while content/doc files are
  `ruff_check_content.py` / `ruff_check.md`, so the query surface only accepts
  `ruff_check`. The name the audit shows is not the name the query takes. Also makes
  triplet report one check-only and one missing-check half-standard.
- [ ] **The `_content.py` blanket bypass mutes all 43 standards across 43 files.** One
  rule with no `standard` key covers ~35% of the branch's files and accounts for 70 of
  the 94 suppressed violations. Every one of the 22 non-`unused_function` hits was
  inspected this session and every one is a documentation example being read as code
  (a `print()` in a `# BAD` block, a `/home/patrick/` path in the hardcoded-path lesson,
  `TODO` in the todo standard's own text). Defensible item by item; unscoped as written --
  if a content file ever gains a real defect, nothing catches it.
- [ ] **`--help` advertises `drone @seedgo diagnostics @flow`, which the module rejects.**
  Standalone diagnostics is disabled; it runs only through the audit pipeline. The
  rejection is graceful but prints an empty `Module:` field.
- [ ] **This README has no auto-update markers,** so `readme check @seedgo` skips every
  section (TREE, MODULES, COMMANDS, HEADER, LAST_UPDATED). The branch that ships README
  generation does not consume it -- all README accuracy here is hand-maintained.
- [ ] **Audit-lane violation records carry no line or symbol,** only file + message text.
  Any analysis built on records is therefore blind to line- and function-scoped rules;
  `inert.py` avoids this by reading checker call sites from the AST. Worth stating in the
  bypass docs, since it is the reason the naive rot detector above cannot be fixed by
  simply matching harder.
- [ ] **`default_artifact_path()` interpolates the branch name into a filename unsanitised.**
  Not reachable today (branch names come from the registry via `normalize_branch_arg`),
  but a name containing a path separator would redirect the write. Cheap guard, no rush.

### Resolved

**DPLAN-0291 round encoding, dispatch f5be0d15 (S83)** -- 5 of 8 items landed, all red-first:

- [x] **ITEM 1 -- `help_flag_safety` shipped as the 44th standard.** AST, never substring. A
  naive `args[0]`-only scan hits **115 sites fleet-wide**; three precision cuts took it to
  **37 real hits / 7 branches, 10 branches clean**. Shape (b) is a *precondition*, not
  independently scored, because @memory -- one of the round's own reference fixes -- still
  reads `remaining_args[0]` and is safe only via its module predicate. A standard that
  fails its own reference implementation is wrong. Shape (c) standalone is not detectable
  without flooding, and that limit is written into the standard so stated coverage matches
  enforcement.
- [x] **ITEM 3 -- `.trinity/` removed from clone-facing scoring.** Ruling honoured; the
  round's framing corrected twice. devpulse is `citizen_class: manager` and never reached
  the check (it failed earlier on a missing manager template) -- only **prax** was
  genuinely scored on `.trinity/README.md`. And a fresh clone did not *fail* fleet-wide: it
  **silently returned zero checks**, a separate honesty bug, now announced on the
  non-scored info channel. Bypass-off effect at prax: 66 checks/3 failing -> 61/2.
- [x] **ITEM 5 -- delegated help predicates are visible to `introspection`.** Premise
  reproduced independently first. No-regression sweep, **916 files / 17 branches: exactly 2
  moved**, both the intended 85 -> 100. Still names 25 modules fleet-wide as not
  intercepting help, so it did not go permissive. Over-broad name matching rejected on
  evidence (`_has_credential_helper` at `drone/.../pr_handler.py:60`).
- [x] **ITEM 7 -- the inert-rule advisory now declares its own unreliability.** Deliberately
  NOT "fixed" -- the real fix is per-rule checklist-lane simulation, and half-fixing a
  signal branches prune on is how the 41-rule near-purge happens twice. Every conclusion
  carries an `unverified:` prefix, because info lines are re-rendered one at a time and a
  caveat at the top alone does not reach the artifact. Surfaced a second unreported defect:
  `audit_display` renders info lines through Rich, which was **eating the `[standard]`
  name** -- the advisory named a file while swallowing which standard it meant.
  Plus the round's "small" item: `FINDING_MARKER = "[FAIL]"` per finding in checklist,
  documented in `--help` with a grep recipe. Em dash kept as human layout, never a contract.
- [x] **ITEM 8 -- `--no-bypass` is a first-class flag.** Both argument orders, declares
  itself in header/summary/artifact, writes its own `last_audit_no_bypass.json`. Found and
  fixed a real **cache-poisoning bug**: the incremental cache fingerprinted the bypass
  *file*, byte-identical whether or not its rules were applied, so whichever mode ran second
  was served the other's score. Proven poisoned before, isolated after.
- [x] **`inbox_audit` swept backups and archives, not live mail** (S81) -- reported by
  @devpulse as a warning burst (trigger escalated `WARNING x10` from
  `captured_inbox_audit`). Their two asks were both wrong and the measurement says so.
  (a) Not repeat-logging on one path: **44 distinct paths, once each, per run** -- the
  day's 88 warn lines are exactly 2 runs x 44. Trigger's "x10 in one second" is the rate
  across distinct paths. (b) Not a `@backup` artifact to route: a **directory** named
  `inbox.json` *is* @backup's versioned-store layout, holding the current copy, a dated
  `inbox-baseline-<date>.json` and an `inbox.json_diffs/` sibling under the original
  filename. 47 on disk, 44 of them under `.ai_mail.local/` and therefore matched by the
  sweep's glob. The defect was mine: `_run_inbox_id_scan()` rglobbed from **repo root with
  no exclusions** -- the only repo-root-wide glob in the branch (all 30 glob call sites
  checked; every other is scoped to a branch tree or a pack dir). It matched 109 paths, of
  which 25 are live, 77 sit under `.backup/` and 7 under `.archive/`. 77% of what it
  announced as scanned was un-actionable, and a bad id inside a backup copy would have
  been reported as a violation nobody can fix. `_is_live_inbox()` now excludes those trees
  and requires `is_file()`; the run prints the skipped count rather than dropping it
  silently (the S77 rule -- every filter announces). Live: 25 scanned, 84 skipped, **0
  warnings**, down from 44 per run.
- [x] **`permissions.py` introspection leak** (S80) -- the gate keyed on the *arguments*
  (no args, or `--help`) instead of the command name, so the trust list printed above
  every bare subcommand, while `drone @seedgo permissions` -- the one command it belongs
  to -- answered "Unknown command" and then printed the block anyway. Now claims its own
  command and is silent for everything else. Two tests, both canaried red first. Note the
  first fix scored 99%: dropping the no-args gate violates seedgo's own `introspection`
  standard, which mandates that exact pattern. The compliant form keeps the no-args gate
  *inside* the command claim. Back to 100%.
- [x] **1 genuinely dead bypass rule deleted** (S80) -- `tests/test_coverage_arch_checklist.py`,
  verified dead in both lanes before removal (28 -> 27). The other 5 flagged by the naive
  detector were verified LIVE and kept; each already carried a note in its `reason`
  explaining why it reads as dead, which is how the false-dead trap was caught.
- [x] **`.gitignore` did not cover scoped audit artifacts** (S80) -- it listed
  `.seedgo/last_audit.json` only, so every `last_audit_{branch}.json` showed as untracked
  and was about to be committed as source. Glob added; `git status` clean of them now.
- [x] **`audit --help` contradicted the runtime** (S80) -- still claimed "Every run also
  writes .seedgo/last_audit.json" after the scoped-filename fix landed the same morning.
- [x] **README drift** (S80) -- claimed a `drone_adapter.py` at branch root that does not
  exist (archived as `.archive/drone_adapter(disabled).py`; no branch in the fleet ships
  one -- drone routes via `routing_config.json` -> `generic_adapter.py`). Misattributed
  the triplet proof's 2 orphans to the ruff naming split. Understated the
  `readme_currency` failure. Test count 1498 -> 1500.

### Found in the tree, authorship unattributed

Work landed in this branch between 06:08 and 06:24 on 2026-08-13, after the wave-2
dispatch arrived at 06:06 and before this session began. It is coherent with the dispatch
and every piece of it is verified green here, but no memory entry records it and this
session did not write it. Recorded as found, attributed to no one:
- `log_structure_check.check_branch_post()` gained the `bypass_rules` kwarg. The audit
  pipeline calls it as a keyword inside a broad `except`, so before this the call raised
  `TypeError`, was swallowed, and the post-check was **dead fleet-wide**. This was open
  todo #1 in `.trinity/local.json`; it is now fixed and pinned by a test that resolves the
  function the way the pipeline does (`getattr`), not the convenient way.
- Scoped audit artifacts: `default_artifact_path(specific_branch)` writes
  `last_audit_{branch}.json` so a one-branch run no longer overwrites the fleet document,
  and the discoverability line names the scope. 3 tests.
- `test_checkers_batch8.py` fixture false-green fix: the bypass package was replaced by a
  `MagicMock` whose truthy `is_bypassed()` bypassed every violation, so violation-detection
  tests passed vacuously and results depended on collection order.
- Stale `handlers/standards/` path text corrected in `branch_audit.py`, `readme_ops.py`
  and `readme_update.py` (that directory does not exist).
- **Two RED tests** in `test_hooks_track_e.py` importing `_is_live_inbox` from
  `inbox_audit.py` -- a symbol that did not exist. Their docstrings carry live-repo
  measurements (109 matched / 25 live / 84 archived) that match what S81 measured
  independently, so whoever wrote them did the same count. Correcting the S80 record:
  **the suite was red at session start, not the 1500 green reported.** The implementation
  they demand is now shipped (above) and both are green; one docstring number was off (47
  warnings -> 44) and was corrected.

## What Needs Doing

### From the DPLAN-0291 round -- open, untouched (S83)

- [ ] **PICK UP FIRST: the closed-vocabulary precision cut in `help_flag_safety` is wrong**
  (S85, found by @backup measuring their own module rather than working around the checker).
  The cut asks "is `args[0]` compared against a fixed set of literals?" and treats yes as
  "nowhere for a flag to hide". Counter-example, run live by them:
  `python apps/modules/drive_check.py foo --help` -> "Drive connectivity test PASSED",
  a real Drive auth + API call. `args[0]='foo'` misses the `'run'` comparison and falls into
  an **unconditional default branch**. The vocabulary was closed; the execution path was not.
  Their reformulation, adopted verbatim as the spec: *"comparing `args[0]` against a literal
  is not sufficient when the function has an unconditional default branch — the safe shape
  is 'no execution path reachable without an explicit non-help arg', not '`args[0]` is
  compared to something'."*
  NOT re-cut in S85 deliberately: the cut exists because the naive rule hit 115 sites
  fleet-wide, so loosening it carelessly floods and tightening it carelessly hides more.
  Needs a measured fleet A/B on one snapshot, not a tired edit. @backup's fix already
  satisfies the stricter shape and their test is written, so re-cutting costs them nothing.
  A first pass at scoping the affected population was inconclusive — the quick heuristic
  isolated the wrong class (22 no-gate-at-all modules, mostly @commons, already reported by
  `introspection`). The real population is still unmeasured. Measure it properly first.
- [ ] **Reference for ITEM 4 (owns-commands vs utility), from @backup:** the whole-sequence
  help check sits AFTER the `if not args` introspection gate in all 11 of their fixed
  modules, so introspection still fires on a bare call. The two constraints compose in that
  order with no conflict — existence proof that item 4 does not need a delicate re-sequencing
  of the two gates.

- [ ] **ITEM 2 -- exit-code honesty standard.** Error paths must exit non-zero; 6+ branches
  measured exiting 0 on failure. `skills apps/skills.py` is the reference fix.
- [ ] **ITEM 4 -- introspection: owns-commands vs utility distinction.** Build it *against*
  @backup's counterweight, not around it: they proved the no-args gate is RIGHT for
  command-owning modules (removal correctly caught at 97%). @api's 5 bypasses stay as
  honest markers until this ships -- nobody deletes them on my account.
- [ ] **ITEM 6 -- walk-scope disclosure.** @skills: `files_checked=14` on a 101-file /
  31k-line branch, and my own checkers disagree (`unused_function` reports `lib/` findings
  the headline never counts). Rule the intended walk; make the score refuse to imply
  branch-wide when it measured a slice.

### My checker bugs, reported by other branches (S83)

- [x] **RESOLVED same day: my router exemption manufactured 14 false negatives** (S84,
  found by @api pushing back on their own score rather than accepting it). `help_flag_safety`
  exempted modules on branches whose *router* normalises the flag, reasoning they were
  unreachable with a stray flag. Wrong: modules also carry a standalone
  `if __name__ == "__main__": handle_command(CMD, sys.argv[1:])` path that never touches
  the router. The exemption was scoring exposed branches at 100. Narrowed, AST-only,
  red-first: the exemption now applies only where the router is the *only* way in, and the
  standalone path must screen **both** dashed spellings — a `--help`-only screen still
  hands `-h` to a positional gate. Re-measured A/B on ONE snapshot (the fleet moves under
  a wall-clock comparison): aipass 100->92 (+1), backup 100->23 (+10), prax 100->50 (+3),
  daemon correctly unmoved; fleet **31 -> 45 hits, zero previously-reported hits lost**,
  verified as a per-file set difference rather than by count. Sharpest recovery:
  `python apps/modules/init_flow.py agent --help` **spawns an agent named `--help`** — the
  near-miss the round was written after, hidden behind my own exemption.
  Two of my own numbers corrected in the process: "12 exposed at backup" was 10, and the
  "37 hits fleet-wide" I published was already 31 by re-measurement because @devpulse fixed
  4 modules mid-session. Any fleet count in a mail has a shelf life of about an hour.
- [x] **RESOLVED: severity I published was overstated** (S84). I told @devpulse and this
  APLAN that `drone @api get-key <provider> --help` "prints a real key". It masks:
  `key[:6] + '****' + key[-4:]`. Accurate line: a help probe reached the retrieval path and
  disclosed masked key material plus confirmation the key exists. Real finding, correct hit,
  wrong severity word. @api corrected it against their own interest. Also from them, worth
  copying fleet-wide: an **empty** key on the audit machine returns "Failed to retrieve" and
  gives a **false all-clear** on this class — their synthetic-key regression test is the fix.

- [x] **RESOLVED same session: my own tests were coupled to live fleet state.** The new
  standard's tests were parametrised over live fleet files asserting "these branches are
  still broken". @api fixed the key leak within an hour of my dispatch and **my suite went
  red for it** — the test punished the exact outcome the standard exists to produce; the
  mirror block ("these stay fixed") was the same bug in reverse. Same class as @memory's
  encapsulation case (fixing dead code *lowered* the score). Both blocks now pin inline
  shapes with the origin branch named in a comment. Fleet state is a measurement — the
  calibration table above — never an assertion. 1579 -> 1573 tests, correction sent.

- [ ] **`log_structure` matches fixture data, arbitrarily** (@prax). Rule is
  `re.search(r'/home/\w+', stripped) and ('log' in stripped.lower() or ...)`. It flagged
  `cls._build_display_name(Path('/home/user/modules/logger.py'))` -- a string argument to a
  path parser, matched only because the fixture filename says "log". The kicker: the same
  file holds **21 more** `/home/user/` literals it misses. Catching 1 of 22 is not strict,
  it is arbitrary. Same class as `readme_currency` harvesting its own bug description.
- [ ] **`check_class_naming` has no allowance for module-private classes** (@prax). Capture
  takes `_Foo`; validity is `^[A-Z][a-zA-Z0-9]*$`, which `_Foo` can never match. **12
  classes across 6 branches**, including my own pack. False positive by construction -- a
  checker bug, never a bypass.
- [ ] **The bypass matcher is broader than any rule's text.** `utils.matching_rule` does a
  **substring** test, and a rule with **no `file` key matches every file**. Measured
  fleet-wide: exactly **2** rules are effectively branch-wide on an `all_files` standard --
  devpulse `architecture` (no file key, 106/106) and prax `architecture` (`"apps/"`, 70/105).
  Both branches' Architecture 100% is not a measurement. Fix the matcher, not 17 registries.
- [ ] **A fourth bypass species: the waiver whose stated reason no longer matches what it
  suppresses** (@prax, found via their own retraction). A rule justified for
  `_terminal_output_enabled` flags is also silently eating an unrelated class-naming
  finding. Distinct from dead / false-dead / widened; required case for the rot detector.
- [ ] **Unknown flags are silently dropped by the audit arg loop** -- `--no-bypas` yields a
  normal audit with no complaint. Same hazard class as ITEM 1.

### @seedgo to handle (dispatch)
- [ ] Build bypass-rot detection to the two-lane design above. Start with the free class
  (rule file does not exist) -- no audit run needed, and it is the class wave 1's prunes
  were actually safe on.
- [ ] Fix `readme_currency` to read a markdown table, and give `triplet` a category for
  non-standard infrastructure modules in a pack directory. Those two changes alone move
  the branch to CERTIFIED.
- [ ] Resolve the `ruff` / `ruff_check` name split in one direction and make the audit
  display and the query surface agree.
- [ ] Narrow the `_content.py` blanket to the standards it actually needs, once the rot
  detector can prove which those are.

### devpulse to handle
- [ ] Re-check the wave-1 bypass prunes (cli 21->8, drone 48->29) against the checklist
  lane before committing the round. Rules whose target file no longer exists are safe in
  any lane; rules deleted because they "suppress nothing" may have been live on the hook
  path. @drone's APLAN records 15 deleted on exactly that signal.

### Tracked elsewhere
- `audit_display.py` 16 hardcoded per-standard display blocks -- DPLAN-0047.
- **`edit_gate` deadlocks cross-file red-first TDD** -- dispatched to @hooks (S81, found
  while shipping the `inbox_audit` fix). A red test in file A importing a missing symbol
  from file B blocks every edit to B, the only edit that can clear it; `edit_gate.py:531`
  permits editing A, but no edit there can define a symbol that belongs in B. Second,
  separate defect: `.diagnostics_state.json` outlives the error when the resolving write
  does not come through the Edit tool -- verified pyright clean on the file while the
  state still listed 2 errors and the gate still blocked. Not seedgo's code; every branch
  doing red-first across a file boundary hits it.
  **FIXED by @hooks the same morning (S82)**, both defects, in `diagnostics_state.py` +
  `edit_gate.py:552/565`. They corrected me on the way: I had written that the stale-state
  fix "probably fixes most of the pain", and it does not touch the deadlock at all -- at
  the blocking moment the errors are genuinely live, so re-validation blocks identically.
  Canaried their fix in this tree in all three directions: cross-file now allowed, local
  type error still blocked (quoting the *live* message), and **a third deadlock found and
  reported** -- deleting the errored file blocks forever, because their "could not be
  established -> recorded errors stand" branch treats *file gone* as unknown. A missing
  file has no type errors. It fires on our own mandated cleanup pattern, since the house
  rule renames to `(disabled)` or moves to `.archive/` rather than deleting, and both are
  "file gone" at the recorded path. Escape: recreate the file clean, let re-validation
  drop the state, then remove it.
- **@hooks' 2 new bypass rules on `diagnostics_state.py` -- ruled VALID (S82).** Measured
  rather than read: stripping them drops `json_structure` 100 -> 0 on exactly 2 checks and
  `trigger` 100 -> 0 on exactly 1 (`.unlink()` at line 70 = `STATE_FILE.unlink()` inside
  `clear()`, the one site the reason names). Both file-scoped with no `lines` key, so
  neither can go inert the way five of mine did in S80; precedents real at code level
  (`auto_fix.py:253` writes the same file with stdlib `json.dumps`). Flagged one
  consequence for their own concurrency todo: together the two rules make every mutation
  of a **fleet-shared** state file invisible to the json log *and* silent to trigger.

### S86 -- the auditor closed its own gap, and the gap was bigger than the gap it was closing

Dispatch 4a266f0a asked for the 5 `help_flag_safety` defects my own standard named on me.
Fixing those took one agent; the finding is what the class sweep turned up alongside them.

**My 5 named defects, plus 5 the checker never named.** `seedgo_proof.py`, `proof_query.py`,
`checklist.py`, `standards_query.py` (two sites), `test_map.py` were the named five. A whole-branch
grep added `inbox_audit.py`, `diagnostics_audit.py`, `permissions.py`, `apps/seedgo.py`, and later
`standards_audit.py`. Two of those additions were real:

- `inbox_audit.py` -- `audit inbox-ids --help` has `args[0] == "inbox-ids"`, so the guard passes,
  the flag sits unread at `args[1]`, and `_run_inbox_id_scan()` runs a repo-root-wide `rglob`.
  Score before: **100**. This is the same file whose scope bug I fixed this morning.
- `standards_audit.py` -- passes the standard legitimately (it loop-scans the whole list), but
  `--artifact` consumes the next token *before* that scan is reached, so
  `audit aipass --artifact --help` ran a full audit and wrote the artifact to a file named `--help`.
  **No version of this checker can see that one** -- the module does scan; the scan is just too late.
  Found by a sub-agent reading past its brief, fixed red-first, live-verified.

`diagnostics_audit.py` and `permissions.py` were true negatives (error output / `return False` past
the gate, no work call) and are now pinned as regression shapes so the widening cannot swallow them.

**The checker gap, diagnosed and closed.** Consumption into a value slot was the only trigger. But a
work call needs no arguments: @flow's `registry_monitor` matched `"scan"` and wrote the registry,
@hooks' `cc_sessions` matched `"reclaim"` and stopped live sessions, mine matched `"inbox-ids"` and
walked the repo. Second trigger arm added -- gated slot matched against a *literal* subcommand word
(including through a name bound via an `IfExp`, which is how @flow's hid) **and** a non-display call
reachable below the gate. Both halves load-bearing: dispatch alone flags the two true negatives above;
work-call alone flags modules that dispatch on `command`, where the positional gate genuinely works.

**Fleet A/B, one snapshot, 142 files across 16 branches, seedgo excluded (it was mid-edit).**
Scoring 0 before: 1. After: 3. Newly flagged: 2, both @cli (`display.py`, `templates.py` -- `demo`
occupies the slot, `run_demo()` executes). Zero regressions, zero crashes, re-run showed zero drift.
3 of 3 spot-checked real, 0 false positives; 9 files that kept a fixed gate were checked for the
*opposite* error and all 9 were correct passes. Recall proven by reconstructing the three pre-fix
shapes: old rule MISS / new rule 0 on all three.

The delta is small only because the fleet already remediated today -- 79 of 142 now whole-list scan
and 16 more are router-protected. Measuring recall against reconstructed shapes, not against a
population that has already been fixed, is the only reason this number means anything.

**Independent live confirmation.** The new rule named `inbox_audit.py` at 18:32. The other agent,
working blind to that run, fixed the same file at 18:36 for its own reasons.

**Weakest point, stated rather than hidden.** The two @cli findings are cosmetic -- `run_demo()`
only prints. If this widening later produces a wave of print-only findings, the honest fix is
severity on the *result*, not narrowing the rule back. Second: `_INERT_CALLS`/`_DISPLAY_HINTS` are
name-based, so a destructive `render_and_purge()` reads as display -- a recall hole chosen
deliberately in the false-positive-safe direction. Third: only *literal* subcommand words are
recognised; `args[0] in HANDLED_SUBCOMMANDS` or `_ROUTES[args[0]]` behind a positional gate is still
invisible. No fleet file uses that shape today.

**A bypass I minted and then retired.** The new predicate tripped `naming` ("redundant prefix in
`help/` dir"). The first instinct was a bypass with a fleet-convention reason. @drone had written to
me the same hour that an over-broad rule is *an authorship problem* -- someone believed they were
scoping to a directory. Minting a bypass against my own standard when a rename satisfies it is the
same species. Moved to `apps/handlers/cli/help_flags.py`, which matches @memory, matches the path my
own standard content already cites, and passes `naming` with nothing suppressed. One bypass remains
and it is measured: `json_structure` on a pure predicate that runs before every command.

**Standard prose updated to match the code** -- "The Three Shapes" is now four, criterion 3 has both
arms, and the `wants_help` example in the content pack had drifted to a signature
(`wants_help(args, allow_bare_word=True)`) that no branch implements. Fixed to the fleet's actual
contract. A checker whose published example does not compile teaches the wrong fix.

### S86 -- two `dead_code` findings from @memory, one shipped, one queued as a real hole

Offered as data, not as a defect report; both were correct.

**Shipped.** The finding named the *frontier*, not the *closure*. @memory archived one named file,
re-ran, and a new one appeared -- its only referencer had just been removed. 95 -> 100 took two
rounds. The message now says `-- re-run after removing any of these: each removal can expose its own
referents`. Red-first. An owner who fixes once and stops was being invited to leave the tail behind.

**Queued -- and their guess about the mechanism was right.** They could not tell from outside whether
path-invoked scripts are cleared *by design* or *by accident*. It is by accident: `dead_code_check.py`
Rule 6 (:199-201) is a plain regex for the quoted filename in any source text. Their
`chroma_subprocess.py` survived because that literal appears in `_HANDLERS_DIR / 'storage' /
'chroma_subprocess.py'`. Build the name dynamically -- `f"{kind}_subprocess.py"` -- and the checker
calls a live subprocess dead. They checked before archiving; the next owner will not, and the checker
gives them no reason to. Until it is closed, a path-invoked script is *unproven* by this standard,
not cleared by it.

### S86 -- @cli returned my dispatch with two bugs in my checkers, and one is a design bug

I dispatched them 2 findings. They confirmed both, fixed both, and sent back 2 of mine.

**A third help-flag shape, and my two arms could not fire on it.** Both existing arms require a
fixed-position gate to *exist* first. @cli's `demo` module put the verb in the **command** slot with
no gate above it -- `if command == "demo": run_demo()` -- so `args` was not read at the wrong index,
it was never read. Scored 100. Shipped as arm (e), narrowly: the function is `handle_command` (a CLI
surface *by name*, which is the only reason this is detectable where a bare "no help gate" check is
not), it dispatches on `command` against a literal, `args` is never read anywhere in the closure, and
a work call is reachable. Fleet population **0 of 152 before and after** -- it flags nobody today
because they fixed theirs before reporting it. The router exemption deliberately does **not** apply
to this arm, with a test pinning it: a router protects a module by *rewriting* args, and a module
that never reads args discards the rewrite too. This is the one arm a correct router cannot cover.

**And the arm does not catch their actual file.** Reconstructing their real pre-fix `display.py` --
removing only the lines they added -- it still scores 100, because below the `run_demo()` block the
function reads `args` twice. "Never examined" was true of the demo *path*; my condition tests the
*function*. Told them plainly not to record their case as covered. "Never read *above* the work call"
would catch it, is unmeasured fleet-wide, and is not shipping at the end of a round. Queued, and
stated as a deliberate hole in both prose surfaces rather than left for the next branch to discover.

**`log_structure` was scoring runtime state -- the serious one.** They reported the false positive: a
branch whose only prax call sites are failure paths emits zero system logs *by construction*, so
"0 system logs -- prax dispatch may be misconfigured" penalised the success case. True, but the bug
underneath it was bigger and was sitting in their own "I cannot explain this" paragraph: the check
**read the live `system_logs/` directory**, so the score was a function of runtime state rather than
of code. That is why their standard read 100 in the morning and 50 at night with their code identical
on both days -- logs rotated, the number moved, no edit anywhere caused it. **An audit score that
moves on its own is worse than a wrong one, because nobody can act on it.** Fixed by removing the
scoring surface entirely and moving the observation to the non-scored `check_branch_info` channel,
where it renders dim and cannot move a number. Answer to their either/or was neither. @cli 99% -> 100%.

Their instinct to leave it visible at 99% rather than bypass it is what got it fixed; the bypass they
deleted that morning briefly cost them and was still the right call -- it turned an invisible
suppression into a visible question.

### S86 -- the audit disturbed what it measured, and I refused a false-negative report

**Dispatch artifacts counted as branch logs.** @devpulse measured it while I was still in session:
`logs/dispatch_stderr.log`, `dispatch_stdout.log`, `dispatch_wake.log` are written into a branch by
**@ai_mail's dispatch machinery** -- 54 of them across the fleet tonight. @cli was the only branch of
17 whose `logs/` held nothing else, so @cli was the only branch flagged, and it was flagged *because
I had dispatched them*. Patrick's 16:47 fleet run scored them 100 because those files did not exist
until 19:12. Excluded red-first, with a control pinning that a branch's own log still counts
alongside them. @cli's info line is now correctly silent -- they have no logs of their own.

That fix was theirs. The cause underneath it was mine and larger: the check **read the live
`system_logs/` directory**, so even with artifacts excluded the number would still move whenever real
logs rotated. De-scoring came first, the artifact exclusion second. Both were needed; only one was
reported.

**Queued, and I told @devpulse before their full-fleet proof rather than after: I have not swept the
other 43 standards for checks that read runtime state.** If the proof becomes the round's artifact,
that sweep is what stands between it and a number that can move on its own.

**The report I refused.** @aipass reported 15 gates across 13 modules with my checker naming only
`init_flow.py` -- read as a fourth false negative on a night that had already produced three. I
measured before answering: `router_normalises()` returns `aipass.py:main() comprehension scan at line
281`. Their router *does* scan and rewrite, so the other 12 were behind a **working** gate -- the
documented exemption that @memory is the reference implementation for. `init_flow.py` was named for
exactly the right reason: a standalone `__main__` dispatching raw argv, a second door past the router,
which is the narrowing that shipped this morning after @api proved the exemption too broad.

Three genuine false negatives tonight (@flow, @hooks, @cli), not four. Said so to @aipass and to
@devpulse before it hardened into the round record. Their fix was still worth doing and I said that
too -- the exemption is a claim about every way in, and their 12 were one `__main__` block away from
being live defects. Defence in depth, not redundancy.

If I accept a report that is actually the exemption behaving correctly, I lose the ability to tell
the two apart -- and so does everyone who reads the record.

## Dispatch Log

| Date | Action | Result |
|------|--------|--------|
| 2026-08-13 | Mail 28cce6ae (@devpulse) + 2d282aea (@aipass) | dispatch_*.log excluded from the local-log count (@cli only branch of 17 affected); @aipass's 1-of-13 measured and REFUSED as a false-negative report -- router exemption working as designed; runtime-state sweep queued and flagged pre-proof |
| 2026-08-13 | Dispatch reply 4c2e258c (@cli) | Both my findings confirmed + fixed by them; they returned 2 checker bugs of mine -- help_flag arm (e) shipped (0/152 fleet impact), log_structure de-scored to the info channel (runtime-state dependence removed). @cli 99% -> 100%. Corrected myself: arm (e) does NOT cover their real file |
| 2026-08-13 | Mail 029ac3dc (@memory) -- 2 dead_code measurements | Frontier-not-closure shipped red-first; their path-invocation suspicion confirmed as a literal-string accident and queued; my "all vestigial" correction accepted at 5 of 6 |
| 2026-08-13 | Dispatch 4a266f0a (@devpulse) -- close my own 5 help_flag_safety defects | 100% / 98% --no-bypass, 1636 tests. 10 modules fixed (5 named + 5 the checker missed); checker gap closed and measured (142-file A/B, +2 fleet-wide, 3/3 real); `--artifact --help` defect found that no checker can see; @cli dispatched |
| 2026-08-13 | Fleet audit round wave 2 (DPLAN-0291, dispatch 73273ca4) | YELLOW -- 1500 tests, seedgo 100% (98% bypass-off), 4 fixes shipped, 8 open items, fleet warning raised on wave-1 bypass prunes |
| 2026-08-13 | Mail 04d237e7 (@devpulse) -- inbox_audit warning burst | Both premises corrected; scope bug fixed and live-proven (44 warnings -> 0); @backup routing cancelled -- no artifact exists; edit_gate deadlock dispatched to @hooks |
| 2026-08-13 | Dispatch reply 9483aa9f (@backup) | All 10 fixed + an 11th they found themselves; help_flag_safety 23 -> 100, overall 98 -> 100, 313 tests. They proved `drive_check.py foo --help` runs a real Drive call -- my closed-vocabulary cut is wrong; reformulation adopted, logged as first pick-up |
| 2026-08-13 | Mail 806fbacd (@api) -- severity correction + `__main__` hole | Router exemption narrowed; fleet 31 -> 45 hits (14 recovered, 0 lost); @backup dispatched, @prax/@aipass mailed; my published severity corrected to masked key material |
| 2026-08-13 | Dispatch f5be0d15 VERIFIED + CLOSED by @devpulse | Build survived their checks; --no-bypass live-proven 100/98 back-to-back (cache-poisoning fix confirmed); help_flag_safety caught all 4 devpulse modules, fixed same hour; devpulse architecture rule measured control-first and restored with its width annotated |
| 2026-08-13 | Dispatch f5be0d15 (@devpulse) -- encode the DPLAN-0291 round findings | 5 of 8 landed (items 1/3/5/7/8), 3 open with reasons; 1579 tests; 99% / 97% --no-bypass; 4 live bugs found in other branches (@hooks zero-violation parsing, @api key exposure, 2 branch-wide bypass rules) |
| 2026-08-13 | Mail 35d22685 (@hooks) -- edit_gate fix returned | Accepted their correction of my defect-2 claim; canaried the fix 3 ways in this tree; **third deadlock found and reported** (deleted errored file blocks forever); their 2 new bypass rules measured and ruled valid |

## Relationships
- **Related DPLANs:** DPLAN-0291 (fleet audit round), DPLAN-0047 (audit_display refactor)
- **Related FPLANs:** FPLAN-0382, FPLAN-0384 (bypass scoping + applicability -- the work
  that made most `tests/*` bypass rules redundant in the audit lane)
- **Owner branch:** @seedgo
- **Seedgo:** `drone @seedgo audit aipass @seedgo`

## Answers to wave-1 findings

**1. Is @cli's permanently-skipped scaffold test doing its job as shipped?** No standard
requires `test_scaffold.py` -- I grepped the pack, nothing references it, so deleting it
violates nothing seedgo enforces. It runs here (seedgo's conftest still provides the
template fixtures) and skips in @cli, which is the honest behaviour for what it is: a
smoke test proving pytest infrastructure works in a branch that has no suite yet. Once a
branch has its own conftest the test is provably inert -- it cannot fail, so it cannot
inform. Recommendation: @spawn stops refreshing it into branches that already have real
test files; @cli may delete it today with no compliance consequence.

**2. Can the audit detect bypass rot?** Yes, and this session built and ran the
measurement -- see the first open item for the design and for the 5-of-6 false-dead rate
the naive version produces. Short answer: three rot classes, in increasing cost --
file-does-not-exist (free, safe, catches most of what wave 1 found), inert-by-scope
(already detected and named on the info channel by `inert.py`), and suppresses-nothing
(needs a bypass-off run **per lane**, and branch-level standards must be canaried through
`check_branch()`).

## Notes
Session notes, discoveries, changes. Stamp each entry: session number + date.

**S80 (2026-08-13):** First full audit. The finding that matters is not a defect in this
branch, it is a defect in a measurement this branch hands the fleet. Wave 1 pruned bypass
registries using seedgo's "suppresses nothing" signal; that signal is computed in the
audit lane only, and the audit lane never walks `tests/`. Re-measured in the checklist
lane, 4 of my own 6 "dead" rules turned out to be suppressing real failures on every hook
run, and a 5th guards a branch-level standard whose results never appear in a violation
list at all. The saving grace was that a previous session had written the reason each
would look dead into the rule itself -- the file argued back. Second theme, three
instances in one session: `readme_currency` now fails on the README bullet describing
`readme_currency`'s bug. A detector reading text cannot separate a document from a
document about the document, and this pack is almost entirely documents about code.

## Listen (TTS-friendly summary)

Seedgo is healthy but not spotless, so this audit is marked yellow rather than green. All
fifteen hundred tests pass, the branch scores one hundred percent against its own forty
three standards, there are no type errors, and every command was run live this morning and
works. The yellow comes from two things. The auditor does not pass its own certification
pack, failing two of five proofs. And one advertised lookup, asking for the ruff standard
by the name the audit itself displays, answers unknown standard.

The most important finding is not about this branch at all. Seedgo tells other branches
which of their bypass rules have stopped suppressing anything, and yesterday two branches
deleted dozens of rules on that advice. That signal is measured in only one of the two
places standards actually run. It walks the apps directory, but the hook that checks files
as you edit them also runs on the tests directory, and it never looks there. When I ran the
same measurement against my own twenty eight rules it told me six were dead. Five of them
were alive. Four are protecting test files on the editing path, and one protects a standard
whose results are written as a sentence rather than as a record, so a machine reading records
sees nothing. Only one rule was genuinely dead, and I deleted that one. The warning has gone
to devpulse before the round is committed.

The second theme is quieter and a little funny. The proof that checks whether the readme is
current now fails partly because the readme explains that this proof has a bug. It reads the
explanation as evidence. That is the same shape as two other findings this week. These
checkers read text, and almost everything in this branch is text about code rather than code.

Four small things were fixed today. A trust list that printed itself over every other
command now answers only to its own name. One dead bypass rule is gone. Audit result files
are ignored by git properly instead of being committed by accident. And a help screen that
described the old file naming was corrected. Eight items are open, none of them blocking.

Health is yellow. Last verified August thirteenth.

---
*Created: 2026-08-13*
*Updated: 2026-08-13*
