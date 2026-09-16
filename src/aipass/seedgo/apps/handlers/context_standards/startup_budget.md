# Startup Budget Standard

**Status:** Live — ADVISORY, enforced by nothing, measured by `startup_budget_check.py`
**Date:** 2026-09-15
**Standard:** `startup_budget` (branch_level, advisory, no bypass)
**Pack:** `context_standards` — `drone @seedgo audit context [@branch]`
**Scope:** `README.md`, `.aipass/aipass_local_prompt.md`, `.trinity/local.json`, `.trinity/observations.json`, `.trinity/passport.json`, `DASHBOARD.local.json`. Nothing under `apps/`.

---

## What It Is

The instrument for the layer contract the boardroom settled on 2026-09-15 (DPLAN-0347, `drone @commons thread 16`): every grounding layer gets one job, one cap and one owner, and seedgo owns the measurement.

It measures six files per branch in **characters** and compares each against the cap its OWNER publishes. It is a scoreboard, not a gate and not a writer.

`drone @seedgo audit context` prints one row per branch, one column per file, chars against cap, over-cap in red.

---

## Why It Matters

On the morning this rule was written, 17 of 18 branches read a README of 13k–96k characters at every greeting, and seedgo's 47 rules measured Python LINE counts and nothing else — no README, no branch prompt, no `.trinity`, no dashboard. Every context regression AIPass has taken was found by the user reading a percentage on a status line. Nothing measured the greeting.

A cap nobody measures is a preference. This is the measurement.

---

## The Caps and Their Owners

| File | Cap | Owner | Where the checker reads it |
|---|---|---|---|
| `README.md` | 10,000 | **seedgo** | `context_standards/pack.json` → `caps["README.md"].max_chars` |
| `.aipass/aipass_local_prompt.md` | 9,000 | hooks | `aipass.hooks.apps.modules.grounding_content.BRANCH_CHAR_BUDGET` |
| `.trinity/local.json` | 25,000 | memory | `memory.config.json` → `entry_limits.file_budgets` |
| `.trinity/observations.json` | 15,000 | memory | same key |
| `.trinity/passport.json` | 6,000 file, 600 per string | memory | same key (`max_chars`, `max_string_chars`) |
| `DASHBOARD.local.json` | 6,000 | prax | `aipass.prax.apps.modules.dashboard.DASHBOARD_CHAR_BUDGET` |

**Read, never copied.** The checker reads each name off the owner's live module — or the owner's config — at CALL time. It carries no copy of any of these numbers. Move a cap at its owner and the next audit moves with it; nothing in seedgo is edited.

**The README cap is seedgo's own**, so it lives in seedgo's own config rather than as a Python constant: Phase 5's per-file CI ratchet has to read and move that number without importing Python. The user ruled 10,000 on 2026-09-15 at 16:02 ("readme 10k and off from start up"). The room had proposed 6,000, and FPLAN-0593 lines 179 and 221 still say 6,000 — **those lines are stale**; `pack.json` says so beside the number.

**`external_inputs()`** names the four owner files (memory's config, hooks' `grounding_content.py`, prax's `operations.py` and its re-export) so the incremental audit cache re-scores every branch when an owner moves a cap. Without that channel each branch keeps serving the row it cached against the OLD number until someone runs `--full`.

---

## Units

`len(path.read_text(encoding="utf-8"))` — characters, the number `wc -m` reports.

Never bytes. Never tokens. A README of 23,478 chars is 23,498 bytes, and a rule that quotes the second number is measuring the encoding rather than the greeting. The boardroom corrected bytes-for-chars three times in one afternoon; it is written into the rule so it cannot be corrected a fourth time.

---

## Scoring

Four weighted groups, summing to 100:

| Group | Weight | Units |
|---|---|---|
| README | 30 | the one file |
| Branch prompt | 25 | the one file |
| Trinity files | 25 | one per present file, plus one per-string unit where the owner caps strings |
| Dashboard | 20 | the one file |

Each group's subscore is proportional over the files actually present. The standard's score is the weighted mean, never rounded up into a 100.

**A group with nothing present to measure scores `None`** and drops out of the mean; its weight is shared across the groups that measured something. A branch with none of the six files reports `not_applicable` — the third answer, neither 0 (which blames the branch for a gitignored file) nor 100 (which claims a reading that never happened).

---

## Advisory

`ADVISORY = True`. `branch_audit` (line 638) keeps every advisory standard out of the branch's gating average. This rule scores, prints and gates nothing.

A checker that moved in one commit put 17 of 18 branches red on 2026-09-13. The room's ruling is advisory first, then a **per-file ratchet in CI** once the numbers have a week behind them: once a file is under its cap, CI gates it there (DPLAN-0347, Phase 5). That ratchet reads `pack.json`.

---

## Failure Modes, and What Each One Prints

| Situation | Answer | Why |
|---|---|---|
| Cap cannot be read (owner module will not import, name missing, config unreadable, `file_budgets` absent) | **ERROR** unit, named owner, group fails | trinity's law on borrowed numbers: an auditor that substitutes its own number is no longer measuring the contract. There is no fallback constant in the checker. |
| File is absent | **absent**, leaves the denominator | `.trinity/` and `DASHBOARD.local.json` are gitignored; a branch may have no dashboard yet. Not 0 chars, not a violation. |
| File is present but unreadable | **ERROR** unit | A broken file must never read as a clean one. |
| Passport parses but carries an oversized string | over-cap unit + a footnote naming the field | A passport can sit well under 6,000 while one identity field runs to 869 chars. |
| Passport will not parse | size still measured, strings not | The size answer on the raw text is the honest half; guessing at fields inside a broken document is not measurement. `trinity` is the rule that fails an unparseable memory file by name. |

---

## What This Rule Deliberately Does Not Claim

- **It does not measure tokens.** Characters are what a file has; tokens are what a model makes of them.
- **It does not measure the greeting.** The injected kernel (≈3,034 chars), the navmap (≈8,178), the identity block and integration prompts are all real startup cost and none of them is in this table. hooks owns those at render.
- **It does not judge content.** A branch under every cap may still have a README that says nothing. `readme_quality` is a different rule.
- **It does not say "this branch is fine".** It says six numbers.
- **It never writes.** The fleet README diet is owner-run and seedgo-scored (DPLAN-0347, "Fleet README diet vehicle": spawn refused an `.md` rewrite arm — 18 of 18 READMEs differ from the template, and an unguarded arm is DPLAN-0199 again).
- **It has no bypass, deliberately.** There is nothing to be excused from while it gates nothing, and a branch that genuinely needs a different number moves the CAP at its owner — the one place every other branch reads it from. Per-branch exceptions would make the table's columns mean a different thing in each row.

---

## Commands

```
drone @seedgo audit context             # the fleet table, one row per branch
drone @seedgo audit context @flow       # one branch
drone @seedgo standard startup_budget   # this rule's content
```

---

## Reference

- **Design:** DPLAN-0347 (devpulse), FPLAN-0593 Phase 2, boardroom `drone @commons thread 16` (converged 2026-09-15), seedgo's comment on Q1/Q2
- **Rulings:** README 10,000 and off the startup read — the user, 2026-09-15 16:02. Branch prompt 9,000 — the room's measured number, against the harness's 10,000 persist line.
- **Sibling:** `trinity` (`aipass_standards/trinity_check.py`) — the shape this checker copies: `AUDIT_SCOPE`, `BRANCH_INPUTS`, `GROUP_WEIGHTS`, `external_inputs()`, and the doctrine that a number is never assumed.
