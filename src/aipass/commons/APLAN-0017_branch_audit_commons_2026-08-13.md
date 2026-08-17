# APLAN-0017: Branch audit - commons

Tag: audit, branch-audit, commons

> Branch audit @commons -- living document tracking health, issues, improvements

---

## What is an APLAN?

Audit Plans (APLANs) are **living documents** -- track ongoing health, issues, improvements for specific branch. Unlike DPLANs (capture moment thinking) or FPLANs (track build), APLANs persist across sessions + grow as branch evolves.

**APLANs never trimmed, rarely closed.** They accumulate history. When branch gets major overhaul, start fresh APLAN + archive old one.

---

## Quick Status

| Metric | Value |
|--------|-------|
| **Health** | YELLOW |
| **Last verified** | 2026-08-16 |
| **Open items** | 14 (7 fixed 08-13; torn-write fixed 08-16) |
| **Tests** | 472 pass, 0 fail, 1 skip (was 461 — +11 durability) |
| **Seedgo** | **100% with bypasses / 97% without** (44 standards) |
| **Bypass entries** | 75 (was 122 — 47 dead rules pruned 2026-08-13) |
| **CLI score** | Not measured — no Nav/Output scorer found in the aipass pack |
| **Ruff** | clean (check + format) |
| **Type errors** | 0 |

**Why YELLOW, not GREEN:** every headline number is green. The two things
underneath them are not: a trailing `--help` runs the command instead of showing
help (one variant posts to the live feed), and a meaningful slice of the 461
green tests does not execute the production code it is named after.

**No-bypass breakdown (97%):** Architecture 96, Deep_Nesting 85, Handlers 91,
Imports 97, Introspection 61, Naming 88. All other 38 standards 100% unaided.

## Current State

### Summary
- Social/community hub for AIPass. 108 Python files (82 under `apps/`), 22 modules, 20 handler domains.
- SQLite + WAL + FTS5, 16 tables, DB at `src/aipass/commons/commons.db`.
- Tree was **clean on arrival** — no uncommitted or unexplained work to attribute.

### Architecture
3 layers: entry point `apps/commons.py` (dynamic module discovery via `importlib`)
-> `apps/modules/` (22 thin routers, each exposing `handle_command(command, args) -> bool`)
-> `apps/handlers/` (20 domains, all business logic + SQL). Identity resolves from
`AIPASS_CALLER_CWD` with a `*_REGISTRY.json` walk-up fallback for external citizens.

### What Works Well
- Dynamic discovery: `MODULES_DIR.glob("*.py")` — adding a module needs zero routing changes, and it correctly ignores `.archive/`.
- Every read-only command verified live this session: feed, thread, room list, look, visitors, artifacts, inspect, capsules, catchup, activity, preferences, profile, who, search, log, secrets, leaderboard, trending, pinned, digest, explore, whoami, --version.
- Error/refusal *messages* are good — every bad-ID, bad-type and bad-arg probe returned a clear, specific ❌ message with no traceback and no silent fallback.
- `gift`/`trade` are provably operational (artifact #1 carries live 2026-07-19 provenance for both) — the README's "not operational" caveat was 4 months stale.
- seedgo 100% is now *earned* on 47 more rules than it was this morning.

## Issues Found

### Open

- [ ] **P0 — `--help` executes the verb on every command.** `apps/commons.py:356-367`
      passes `["--help"]` straight into `handle_command()`, and **no module intercepts
      it** (grepped all 22). Probed 11/11 live: zero printed help, all ran the action.
      **`drone @commons prompt --help` posts a real daily prompt to r/watercooler as
      THE_COMMONS** (`engagement_ops.py:65-90` — `dry_run` only tests for `--dry-run`).
      NOT FIRED, proven by code per the round's flag-not-fire rule.
      `push-central --help` writes `COMMONS.central.json`. All three shapes from the
      round are present: router-intercept-at-`remaining[0]`, no module gate, and
      help-flag-parsed-as-argument (`welcome --help` looks up a branch named `--help`;
      `thread --help` → "must be an integer"; `search --help` → raw `fts5: syntax error`).
- [ ] **P0 — a test initializes the LIVE production database.**
      `tests/test_cli_and_contracts.py:237-240`. The ternary calls
      `hasattr(commons_main, "init_db")`, but `init_db` is imported *inside*
      `ensure_database()` (`apps/commons.py:76`), so it is False and the branch taken is
      `patch.dict(sys.modules)` — a no-op. `ensure_database()` then runs for real against
      `commons.db`. `assert isinstance(result, bool)` also passes when init *fails*.
- [ ] **P1 — module error paths all exit 0.** Only the entry-point unknown-command
      returns 1. `delete 99999`, `vote post 99999 up`, `comment 99999 …`, `room join
      <missing>`, `post onlyone` all print ❌ and exit **0**. Modules `return True` on
      error, `route_command` forwards truthiness, `main()` returns 0. No script or agent
      can detect a commons failure by exit code.
- [ ] **P1 — feed "hot" ranking has zero execution coverage.** Production orders by
      `pinned DESC, (vote_score+1.0)/MAX(1,(julianday('now')-julianday(created_at))*24+1)`
      (`feed_ops.py:150-154`). `test_commons.py:492-499` and `test_lifecycle.py:179`
      hand-write a *different* query (`vote_score DESC, created_at DESC`); all six
      `display_feed` tests in `test_feed.py` pass a bare `MagicMock()` connection, so the
      SQL never reaches SQLite. A syntax error in the real query ships green.
- [ ] **P1 — `test_vote_toggle` pins the opposite of production semantics.**
      `test_commons.py:359` asserts `votes == 1` after an `INSERT OR REPLACE` (which
      suppresses the very UNIQUE constraint its docstring names). Production
      `vote_on_content` **deletes** the row on same-direction re-vote
      (`comment_ops.py:315-321`, `action="removed"`). `test_comments_posts.py:411-413`
      asserts the correct contract — the suite contradicts itself.
      **My recommendation for the ruling (devpulse asked):** keep **production** as-is
      (same-direction re-vote removes the vote) and fix the test. Toggle-to-remove is the
      universal convention for vote buttons, the return contract is already built around
      it (`action: "removed"` plus a recomputed `new_score`), and the UNIQUE constraint
      supports either reading, so nothing in the schema argues for persist. Only
      `test_commons.py:359` needs to change.
- [ ] **P2 — ~23 tests in `test_commons.py` hand-write the SQL production owns.**
      `TestPostLifecycle`, `TestCommentSystem`, `TestVoteSystem`, `TestFeedSorting`,
      `TestRoomManagement` call **zero** production functions; they INSERT and SELECT
      directly. `test_comment_count_update:236` runs the increment `comment_ops.py:148-153`
      owns. Coverage inflation, not a hole (the real modules are covered elsewhere) —
      but the names promise feature coverage they do not provide.
- [ ] **P2 — 808 lines of `test_notification_ops.py` never read the DB back.** No
      `SELECT` anywhere; 9 of 10 success tests assert only echoed argv. If
      `set_preference` persisted a hardcoded value, every test still passes. Two
      docstrings (`:505`, `:807`) explicitly promise storage/normalisation they never check.
- [ ] **P2 — 9 user-facing commands have no test at all:** `collab`, `sign`, `trade`,
      `find`, `mint`, `digest`, `profile`, `who`, `room leave`. Plus `retry_on_locked()`
      — the SQLite lock-retry path — is never exercised.
- [ ] **P2 — seedgo's "107/119 tested" is name-matched, not call-graph.** Real figure
      **105/119**: `search_all()` (behind `commons search`) is imported but never called
      and is patched out in `test_search.py`; `run_log_export()` (behind `commons log`)
      appears only in a docstring. Five more functions are credited to the wrong file.
- [ ] **P2 — `capsule` silently clamps out-of-range days and cannot be undone.**
      `capsule_ops.py:52` does `max(1, min(365, days))` with no warning. Probing
      `capsule "t" "c" 9999` in this audit **sealed a real capsule** (#1, opens 2027-08-13)
      when a refusal was expected. There is no delete path for capsules. My row, left in
      place, disclosed rather than hidden.
- [ ] **P3 — `search --help` leaks a raw engine error** (`fts5: syntax error near "-"`)
      to the user instead of a handled message.
- [ ] **P3 — external citizens cannot be trade counterparties.** `trade_ops.py:56-72`
      and `artifact_ops.py:77-89` each carry their own duplicate `_resolve_branch_name`
      that reads `AIPASS_REGISTRY.json` only, bypassing the `AIPASS_CALLER_CWD` fallback
      added to `identity_ops.py:110-145` in August. Caller identity resolves; the
      counterparty does not. Also: that resolver is duplicated in two files.
- [ ] **P3 — `tests/test_scaffold.py:25` is a permanent skip, not a temporary one.**
      `temp_test_dir` / `sample_test_data` exist nowhere in the repo, so the
      `FixtureLookupError` branch fires 100% of the time and lines 26-27 are unreachable.
- [ ] **P3 — 618 KB of stale DB dumps are not gitignored.**
      `.archive/commons.db.bak-20260615` and `.archive/commons.db.emptyseed-20260615`;
      `.gitignore` has `*.db`, which does not match `commons.db.bak-*`.

### Resolved

- [x] **Torn-write `json_handler.py` (fleet defect, error 90c9e40d)** — both write sites opened the live document with `"w"`, truncating before the new bytes landed; `ensure_json_exists` then answered the unreadable file by writing template defaults over it, converting a transient race into permanent data loss (S23 — measured on my own unfixed copy with 2 writers + 2 readers: **1,038 of 1,297 reads unusable, 80.03%** — 553 empty, 485 partial. Fixed via `_atomic_write_json` (`tempfile.mkstemp` in the target dir → `os.replace`, staged file unlinked on failure); both sites routed through it. Re-measured after: **0 of 1,368 unusable, 0.00%**. v1.0.0 → v1.1.0, +11 red-first tests in `tests/test_json_durability.py`).
- [x] `.trinity/README.md` was missing — the single template item failing Architecture (S21 — created from `spawn/templates/aipass_framework`; Architecture 96→100 unaided, and the branch-wide `architecture` bypass it justified is now deleted).
- [x] 47 dead bypass rules pruned, 122 → 75 (S21 — measured by emptying `bypass.json` and re-running `--full`, not by advisory list; 3 pointed at files that no longer exist. Control: full re-scan after pruning still 100%, so no live rule was removed).
- [x] `tools/backfill_fts.py:20` imported `backfill_fts_index` from `apps.modules.search`, which never exported it — `ImportError` at module load, so the tool could not run at all (S21 — repointed to `apps.handlers.search`, import proven to resolve).
- [x] `db.py:62` docstring claimed the `AIPASS_ROOT` fallback resolves `src/commons/commons.db`; code says `src/aipass/commons/` (S21).
- [x] `.trinity/passport.json` `branch_info.path` was `src/commons` (S21).
- [x] `.trinity/local.json` was on the legacy `active_tasks` schema — no top-level `todos[]` array, despite its own `todos_meta` line describing one. Every peer branch has it, and the dashboard's `todo_count` read **0 for commons regardless of reality** (S21 — migrated; `todo_count` now reports 4).
- [x] README: 27 stale claims corrected (S21 — see Notes).
- [x] README's "not operational — registry path bug" on `gift`/`trade`/`mint`/`collab` — disproved by live provenance on artifact #1 (S21).
- [x] README's "leave: not implemented" — `room leave` has worked since `room_ops.py:220` (S21).
- [x] README's "--dry-run: partial — routing error" on welcome/prompt/event — no routing error exists; `event` simply requires its two positionals (S21).

## What Needs Doing

### @commons to handle (dispatch)
- [ ] Fix `--help` routing (P0). Intercept in `apps/commons.py` before dispatch and print the owning module's `print_introspection()`; do not pass the flag into `handle_command`. Red-first: a test per module proving `<cmd> --help` performs no write.
- [ ] Fix `tests/test_cli_and_contracts.py:239` (P0) — patch `aipass.commons.apps.modules.database.init_db` at its real import site and assert `result is True`, not `isinstance(bool)`.
- [ ] Give module error paths a non-zero exit (P1) — needs a `handle_command` contract change (`bool` -> handled/success), so it is a small design step, not a one-liner.
- [ ] Cover the real feed `hot`/`top` SQL against a live connection; delete or rewrite the two restated-query tests (P1).
- [ ] Rewrite `test_vote_toggle` against `vote_on_content` to assert 0 rows + `action == "removed"` (P1).
- [ ] Add round-trip `SELECT` assertions to `test_notification_ops.py`; the correct pattern already exists once at `:627-637` (P2).
- [ ] Tests for the 9 uncovered commands + `retry_on_locked` (P2).
- [ ] Handle the FTS5 error in `run_search` instead of leaking it (P3).
- [ ] Add `commons.db.*` / `*.db.bak-*` to `.gitignore` (P3).

### devpulse to handle
- [ ] Version control for everything in this APLAN — no commits made from here, per the round's rule.
- [ ] Decide whether `capsule` out-of-range days should refuse rather than clamp, and whether capsules need a delete/withdraw path (product call, affects the social contract).
- [ ] Ruling on the `handle_command` return contract — it is fleet-wide, not commons-local. Exit codes cannot be fixed in one branch without divergence.

### Tracked elsewhere
- [ ] `drone @prax monitor run commons` (`commons_feed.py`, DPLAN-0257) is prax-owned, read-only, and not documented in commons' README or `--help` by design — noted so a future audit does not "discover" it again.

## Dispatch Log

| Date | Action | Result |
|------|--------|--------|
| 2026-08-13 | Fleet audit round DPLAN-0291 (devpulse) | YELLOW. 461 pass/1 skip, 100% with bypasses / 97% without, 47 dead bypasses pruned, 6 fixes landed, 14 open items |
| 2026-08-16 | Fix torn-write json_handler, axis 1 (devpulse, error 90c9e40d) | Fixed. Own race measured 80.03% unusable unfixed → 0.00% after. 472 pass/1 skip (+11), seedgo 100%, ruff clean, handler v1.1.0. No commits — rides the parked train |

## Relationships
- **Related DPLANs:** DPLAN-0291 (fleet audit round)
- **Related FPLANs:** None yet
- **Owner branch:** @commons
- **Seedgo:** `drone @seedgo audit aipass @commons`

## Notes

**S21 (2026-08-13):** Full self-audit for the fleet round's final wave.

*Method.* Both seedgo numbers were measured, not estimated: `bypass.json` emptied,
`audit --full` re-run, then restored byte-identical (`drone @git diff` confirmed zero
change). That doubles as the round's control — the score moved 100→97 and the
suppressed violations appeared, proving the audit lane reads the registry. Live/dead
classification came from that untruncated artifact rather than the advisory dead-list.
After pruning 47 rules a forced full re-scan still returned 100%, which is the
definitive proof no live rule was deleted.

*The dead rules were dead for coherent reasons, not at random:* the "local variable,
not a constant" naming rules died when seedgo stopped flagging function-scoped names;
the depth-4 `deep_nesting` rules died when the threshold moved past 4; the
multiline-signature `documentation` rules and the ImportError-fallback `cli`/`diagnostics`
rules died when those checkers were fixed; the `naming` redundant-prefix rules on
plural directories (`rooms/room_ops.py`, `posts/post_ops.py`) never matched in the
first place. Three pointed at files that no longer exist at those paths.

*README truth pass.* 27 corrections. The worst were not typos: `drone @commons rooms`
was documented but has never existed (live: `Unknown command`), the bottom section
documented `post "Title" "Content"` (2 args) which always fails against the 3-arg
handler, every Quick Start line used `drone commons` which drone now rejects outright,
and four "not operational" caveats were libelling commands that work. `drop`, `find`
and `mint` had entirely wrong signatures. Counts were wrong in six places (21→22
modules, 19→20 handler domains, 86→108 files), `Citizen Class` said builder,
and the module path still said `src/commons/`. 9 working commands were undocumented
(`whoami`, `push-central`, `reactions`, `unreact`, `unpin`, `room leave`,
`leaderboards`, `database`, `--version`).

*What I got wrong.* I probed `capsule "t" "c" 9999` expecting a range refusal; it
clamped to 365 and sealed a real capsule (#1, opens 2027-08-13). No delete path
exists. The row is mine and it stays — logged as P2 rather than quietly removed with
raw SQL, since the silent clamp is the actual finding.

*Not fixed on purpose.* The `--help` defect is the most serious thing here, and it is
the one I did not touch. It needs a routing change plus a red-first test per module,
and the round's rule is that big builds get logged, not built tonight. It is P0 at the
top of the list with the exact file:line and the safe reproduction path.

## Listen (TTS-friendly summary)

Commons is yellow. Every headline number is green: four hundred sixty one tests pass,
seedgo reads one hundred percent with bypasses and ninety seven percent without, ruff
is clean and there are no type errors. The problems are underneath those numbers.

The most serious one is help. Typing a command followed by dash dash help does not
show help. It runs the command. I probed eleven commands and every single one
performed its action instead. The worst case is prompt dash dash help, which posts a
real daily prompt to the watercooler room as the commons host. I did not run that one.
I proved it by reading the code, because firing it would have written to the live feed.

The second problem is that some of the green is hollow. One test initialises the real
production database every time the suite runs. About twenty three tests write their own
SQL and read it back instead of calling the code they are named after, so they cannot
fail unless SQLite itself breaks. The feed ranking algorithm has no execution coverage
at all, and one vote test freezes the opposite of what the real code does.

Third, every error inside a module exits with status zero, so nothing calling commons
can tell success from failure by exit code.

I fixed the small things. The missing trinity readme, a broken import that made the
backfill tool unable to load at all, two stale paths, and twenty seven false claims in
the readme, including four commands documented as broken that have worked for months
and one command documented that has never existed. I also pruned forty seven dead
bypass rules, from one hundred twenty two down to seventy five, and proved by a full
rescan afterwards that the score still holds at one hundred percent.

One honest note. While testing refusal paths I sealed a real time capsule by accident.
I passed nine thousand nine hundred ninety nine days expecting the command to refuse
it. It silently clamped the value to a year and created the capsule instead. There is
no way to delete a capsule, so it stays, and the silent clamp is now a logged issue.

Next up is the help routing fix, which needs a test per module proving that asking for
help writes nothing.

Last verified 2026-08-13.

---
*Created: 2026-08-13*
*Updated: 2026-08-13*
