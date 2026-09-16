# context_standards — the startup budget

**Branch** seedgo · **Pack** `apps/handlers/context_standards/` · **Verb** `drone @seedgo audit context [@branch]`
**Status** advisory ROW, ratcheted FILES — the audit score gates nothing; the CI ratchet
holds `README.md` and the branch prompt at their caps (see [The ratchet](#the-ratchet)).
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

The README left the startup read fleet-wide on 2026-09-15 (the user, 16:02, with the 10,000
cap in the same ruling). A branch's breadcrumbs are its prompt from that moment on.

---

## Why the audit row is advisory

A checker that moved in one commit put 17 of 18 branches red on 2026-09-13. The ruling was
*advisory, then ratchet*: the score prints, `branch_audit` keeps it out of the gating
average, and the holding is done by a separate per-file gate over the files a clean checkout
can actually see.

It has no bypass, deliberately: a branch that needs a different number moves the CAP at its
owner — the one place every other branch reads it from. Granting per-branch exceptions to a
fleet-wide measurement would make the table's columns mean a different thing in each row.

---

## The ratchet

`apps/handlers/context_standards/startup_ratchet.py`, run from
`.github/scripts/seedgo_audit.py` in the **seedgo-audit** CI job. Landed 2026-09-15
(DPLAN-0347 / FPLAN-0593 Phase 5), after 17 README diets put every branch under cap.

The advisory row says how big things are. The ratchet is the part that holds: once a branch
is under its cap, the commit that pushes it back over turns the job red in the same run.

### What is gated

| File | Owner | Cap read from |
|---|---|---|
| `README.md` | **seedgo** | `context_standards/pack.json` → `caps["README.md"].max_chars` |
| `.aipass/aipass_local_prompt.md` | **hooks** | `grounding_content.BRANCH_CHAR_BUDGET` |

Both are **tracked in git**, so a CI checkout measures exactly what a local audit measures.
That is the whole selection rule.

### What is NOT gated, and why

| Not gated | Why |
|---|---|
| `.trinity/{local,observations,passport}.json` | gitignored — machine-local memory. A CI checkout holds none of them, so a gate on them would measure nothing on every run and pass by accident forever. |
| `DASHBOARD.local.json` | gitignored — same fact, same reason. |
| `docs/*.md` | measured by the advisory lane, not gated: the fleet holds pages that predate the 20,000-chars-per-page rule (two research pages at 126,181 and 37,180 chars are deliberately unsliced). A ratchet drops only where the corpus is already under. |

**An absent gated file is not a failure.** A branch with no README already fails
`readme_check`'s "README exists" unit inside the scored pack, which gates at 100% in the
same job. This rule is about *growth*; a second, differently-worded red for the same defect
only splits the diagnosis.

**Stabilise, do not expand.** Widening the gated set is a decision about what CI can see,
not a line of config.

### The boundary: `<=` passes

A file measuring **exactly** its cap is UNDER and passes. Over is **strictly greater**:
`chars > cap`. Same comparison the advisory checker makes, so a branch that diets to
precisely 10,000 is never told it missed by zero. The banner prints the rule so no reader
has to guess which side of the line is legal.

**Chars, `wc -m`** — decode utf-8, `len(text)`. Never bytes, never lines, never tokens. The
measurement is delegated to `startup_budget_check.measure_chars`, so the gate and the table
cannot drift into two different units.

### The failure line

Four things, always, on one greppable line — the file, the measured size, the cap, and the
**owning branch**:

```
  FAIL src/aipass/<branch>/README.md — measured 10,316 chars, cap 10,000 chars (OVER by 316), owner @seedgo (context_standards/pack.json -> caps["README.md"].max_chars)
```

A red that does not name the owner costs a seat a round trip. Paths print repo-relative, so
a log line reads the same from any machine.

### An unreadable cap is red, never a default

No cap number is written into the ratchet or into `.github/`. Each gated entry carries the
*name* of the reader on `startup_budget_check`, fetched with `getattr` and called on every
measurement — bind the function (or the integer) at import and the gate becomes a copy of a
number with someone else's name on it, still printing green after the owner moved the cap.

If `pack.json` will not parse, or @hooks cannot be imported, the line reads
`cap UNREADABLE`, names the owner, and the job goes red:

```
  FAIL src/aipass/<branch>/README.md — measured UNREADABLE, cap UNREADABLE, owner @seedgo (...): seedgo: cannot read its own pack.json (JSONDecodeError: ...) — cap not measured
```

A gate that quietly substitutes the number it saw last week has stopped measuring and has
not said so. **An unmeasurable gate is a failing gate.**

### Where it runs, and why there

Inside the existing **seedgo-audit** job, ahead of the standards audit, over the same branch
list the audit walks:

- **One branch list.** Two walks of `src/aipass` could drift, and a file gated on a branch
  the audit does not score — or the reverse — is a hole nobody would find until it was used.
- **First, because it is cheap.** 36 file reads against two caps, well under a second, where
  the audit runs pyright over eighteen branches. An over-cap README is self-diagnosing and
  needs nothing the audit would have printed, so a red stops the job instead of buying ten
  more minutes of a run that is already red.
- **Green changes nothing.** On the ordinary run everything after the ratchet executes
  exactly as it did before it existed — the `EXPECTED_STANDARDS` pack-count tripwire and the
  per-branch 100% threshold are untouched.

It depends on no warm cache (every file is read on every run), no registry lookup (a
directory walk, from whatever root the caller names), and no absolute path — which is why
the same code gates the live tree and a throwaway copy in a temp directory.

The module **never prints**. It returns rows and formatted lines; the `.github` runner
prints them.

---

## Related

- [audit_engine.md](audit_engine.md) — the engine, the cache and the external-inputs channel
- [aipass_standards.md](aipass_standards.md) — the scored pack, and the advisory docs-index lane in `readme`
