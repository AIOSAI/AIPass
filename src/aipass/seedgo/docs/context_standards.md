# context_standards — the startup budget

**Branch** seedgo · **Pack** `apps/handlers/context_standards/` · **Verb** `drone @seedgo audit context [@branch]`
**Status** advisory — it measures and prints; it gates nothing.
**Full rule** `apps/handlers/context_standards/startup_budget.md` (scoring groups, failure
modes, what the rule deliberately does not claim). This page is the short read.
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

---

## What it measures

Six files per branch, in **characters** (`wc -m`), each against the cap its OWNER publishes:

| File | Cap | Owner | Where the checker reads it |
|---|---|---|---|
| `README.md` | 10,000 | **seedgo** | `context_standards/pack.json` → `caps["README.md"].max_chars` |
| `.aipass/aipass_local_prompt.md` | 9,000 | hooks | `grounding_content.BRANCH_CHAR_BUDGET` |
| `.trinity/local.json` | 25,000 | memory | `memory.config.json` → `entry_limits.file_budgets` |
| `.trinity/observations.json` | 15,000 | memory | same key |
| `.trinity/passport.json` | 6,000 file, 600 per string | memory | same key |
| `DASHBOARD.local.json` | 6,000 | prax | `dashboard.DASHBOARD_CHAR_BUDGET` |

Nothing under `apps/` is opened: this is the cost of a greeting, not the cost of the branch.

**Read, never copied.** Every number is read off the owner's live module or config at call
time. Move a cap at its owner and the next audit moves with it; no file in seedgo is edited.
`external_inputs()` names those owner files so the incremental cache re-scores each branch
when a cap moves — without it, a branch keeps serving the row it cached against the old
number until someone runs `--full`.

**Chars, never bytes, never tokens.** The boardroom corrected bytes-for-chars three times in
one afternoon, so the unit is written into the rule.

---

## The layer contract it instruments

Settled in `drone @commons thread 16`, recorded in DPLAN-0347. One job, one cap, one owner
per layer, and nothing is said twice:

| Layer | Its one job |
|---|---|
| kernel | don't get lost |
| navmap | what the fleet is |
| branch prompt | how THIS branch works — breadcrumbs; the directory tree lives ONLY here |
| identity block | the passport |
| dashboard | status |
| `drone @<branch>` | the live inventory, generated from code |
| README | the face for strangers and other agents: purpose, how to reach me, self-map pointer, docs index |
| `docs/` | the depth — one file per module or handler group, each small enough for one Read, indexed from the README, opened when something breaks |

The README left the startup read fleet-wide on 2026-09-15 (Patrick, 16:02, with the 10,000
cap in the same ruling). A branch's breadcrumbs are its prompt from that moment on.

---

## Why advisory

A checker that moved in one commit put 17 of 18 branches red on 2026-09-13. The ruling is
*advisory, then ratchet*: once the numbers have a week behind them, a per-file CI ratchet
reads `pack.json` and gates each file where it already sits (DPLAN-0347 Phase 5).

It has no bypass, deliberately: there is nothing to be excused from while it gates nothing,
and a branch that needs a different number moves the CAP at its owner — the one place every
other branch reads it from.

---

## Related

- [audit_engine.md](audit_engine.md) — the engine, the cache and the external-inputs channel
- [aipass_standards.md](aipass_standards.md) — the scored pack, and the advisory docs-index lane in `readme`
