# v5 vs haiku — shadow diff #1

**Run** 2026-09-02 · seedgo · pack `pytest_quality` (11 rules, shadow/advisory) vs the FPLAN-0468 haiku triage
**Question this answers** does v5 convict tests the calibrated read cleared?
**Answer** on the one rule the two judgements overlap, no — v5 clears **308** of the 526 where haiku cleared **305**, a 3-row gap.
The false-conviction risk in this pack is carried entirely by **one rule, `docstring_pin`, which is already unscored on purpose.**

> **Read this first.** The per-test haiku verdicts were never written to disk. This diff is at the
> **population** level, not the row level. Section *Limits* says exactly what that costs.

---

## Headline

| | haiku triage (2026-09-01, LLM read of real bodies) | v5 `pytest_quality` (2026-09-02, AST) |
|---|---|---|
| population judged | 526 rows with `assertion_shape: NONE` | 511 of those 526 + 18,316 other units |
| **has an oracle** | **305** (58.0%) | **308** (58.6% of 526) |
| **no visible oracle** | **221** (42.0%) = 214 SMOKE + 7 NO_ORACLE | **203** flagged + **15** never entered its corpus = 218 |
| says a test is worthless | no — four-verdict rubric, SMOKE is a legitimate contract | no — every rule nominates, none convicts |
| corpus | 19,437 functions / 624 files (phase A inventory) | 18,827 units / 18 branches |

**The 3-row gap is not luck.** FPLAN-0468 names two mechanisms behind haiku's HAS_ORACLE class —
*"delegated `_assert` helpers, mock `assert_called`"*. v5 clears the 308 by exactly those two and
nothing else:

| v5's clear mechanism over the 511 in-corpus rows | count |
|---|---|
| delegating helper call (`assert*`/`_assert*`/`check*`/`verify*`/`expect*`) | 263 |
| mock / unittest `assert_*` call | 45 |
| bare `assert` statement | 0 |
| **cleared** | **308** |
| **flagged — no oracle visible** | **203** |

The inventory's own static `delegated_oracle` field cleared only 267. v5 clears 41 more that field
missed, and lands 3 rows from an LLM that read the bodies.

### The two disagreement directions, kept apart

| direction | what it costs | measured |
|---|---|---|
| **FALSE CONVICTION** — v5 flags what haiku cleared | would delete a healthy test | `no_oracle`: **0** of the 267 `delegated_oracle` rows flagged; aggregate clear-count gap **3 rows**. **`docstring_pin`: 264 of the 308 healthy rows (85.7%)** — but it reports 100 and scores nothing. |
| **MISS** — haiku flagged, v5 does not | costs coverage of the analysis only | **15 rows never enter v5's corpus**, including **all 7** `hook_engine_poc` functions — *5 of haiku's 7 NO_ORACLE*, its single most confident finding. |

### Rule ranking — who carries the disagreement

| # | rule | distinct flagged nodeids | flags on the 308 healthy rows | % of them | flags on the 203 both call thin | flags never judged by haiku |
|---|---|---|---|---|---|---|
| 1 | `docstring_pin` | 16,886 | **264** | **85.7%** | 167 | 16,455 |
| 2 | `no_oracle` | 203 | 0 | 0% | 203 | 0 |
| 3 | `mock_drift` | 342 | 0 | 0% | 0 | 342 |
| 4 | `assertion_shape` | 296 | 0 | 0% | 0 | 296 |
| 5 | `capture_never_read` | 132 | 0 | 0% | 2 | 130 |
| 6 | `unentered_assert` | 110 | 0 | 0% | 0 | 110 |
| 7 | `self_skip` | 99 | 0 | 0% | 1 | 98 |
| 8 | `empty_parametrize` | 34 | 0 | 0% | 0 | 34 |
| 9 | `coverage_slot` | 13 | 0 | 0% | 0 | 13 |
| 10 | `entry_point_diff` | 4 | 0 | 0% | 0 | 4 |
| 11 | `posix_literal` | 4 | 0 | 0% | 0 | 4 |

*Column 3 counts distinct nodeids, because one unit can be flagged twice by the same rule.
Raw violation-row counts differ where that happens: `mock_drift` 468 rows → 342 nodeids,
`assertion_shape` 298 → 296, `entry_point_diff` 11 → 4, `posix_literal` 5 → 4 (the surplus rows are
file-level findings with no nodeid). Every other rule is 1:1.*

Ten of eleven rules land **zero** flags on the population the calibrated read judged healthy.
One rule carries 100% of the measurable false-conviction pressure, and it is already held back.

Fleet scores (advisory): 18/18 branches ≥ 94%, average 98%. Lowest standard average is
`entry_point_diff` at 77%; `no_oracle` averages 98% with 203 flags concentrated in prax (53) and
seedgo (46).

---

## The three disagreements, with one example each

### 1. `docstring_pin` — 264 of the 308 healthy rows. Correctly unscored; keep it that way.

**Real nodeid** `src/aipass/api/tests/test_host_api.py::TestDetachStatusAndStop::test_stopping_nothing_is_not_an_error`

```python
def test_stopping_nothing_is_not_an_error(self, store, quiet_module, detachable) -> None:
    """Running `stop` twice must be safe — the second has nothing to do."""
    detachable.stop.return_value = None
    handle_command("host-api", ["stop"])
    quiet_module["error"].assert_not_called()
```

**v5 said** two things at once. `no_oracle`: **cleared** (`assert_not_called` is an oracle).
`docstring_pin`: **flagged**, species `UNANCHORED_DOCSTRING` — *"the docstring names no symbol this
unit calls"* (it calls `handle_command` and `assert_not_called`; the docstring says `stop`).

**Haiku said** HAS_ORACLE — mock `assert_called` is one of the two mechanisms the record names.

**My read: both are right, and that is the finding.** They are not answering the same question.
`docstring_pin` measures documentation anchoring, which no independent judgement has ever
calibrated; haiku measured oracles. The danger is arithmetic, not semantics: at 89.7% of the fleet
unanchored (16,886 of 18,827 units), turning `SCORED = True` would red every branch on day one and
would, on the haiku-triaged slice, flag 85.7% of the tests the calibrated read called healthy.
`docstring_pin_check.py:83` ships `SCORED = False` and returns 100. **This diff is the measurement
that justifies that line. Do not flip it.**

### 2. Fifteen rows v5 never sees — including haiku's headline NO_ORACLE finding

**Real nodeid** `src/aipass/devpulse/tools/hook_engine_poc/test_engine.py::test_pre_tool_use_allow`

```python
def test_pre_tool_use_allow() -> bool:
    """Test PreToolUse with an Edit that should be ALLOWED (own branch file)."""
    ...
    dispatch("PreToolUse", stdin_data, config)
    logs = _read_log()
    hooks_run = [e for e in logs if "hook" in e and e.get("exit_code") is not None]
    blocked = any(e.get("exit_code") == 2 for e in hooks_run)
    sys.stderr.write(f"  Hooks fired: {len(hooks_run)}\n")
    return not blocked
```

**v5 said** nothing. `corpus.TEST_DIRS = ("tests", "test")`, so a `test_*.py` under
`devpulse/tools/` is outside the walk. All 7 POC functions are unmeasured, as are 8 rows under
`skills/lib/telegram/tests/` (a *nested* tests dir, also outside the walk).

**Haiku said** NO_ORACLE — and FPLAN-0468 records *"five are devpulse's own hook_engine_poc tool
tests… pytest ignores return values"*. This file is 5 of the fleet's 7 genuinely oracle-free tests.

**My read: haiku is right and v5 has a corpus hole.** `return not blocked` is a judgement pytest
discards; that is the textbook no-oracle shape. The direction is the harmless one — a MISS, not a
conviction — but a standard that cannot see the corpus's worst 7 tests cannot claim to replace one.
Cheap cure: widen the walk to any `test_*.py` outside `SKIP_DIRS`, or add nested-`tests` recursion.
(The POC file is gitignored via the repo-root blanket `tools/` rule, so CI would never see it
either — a fix here changes the local report, not the board.)

### 3. `no_oracle` clears on the *name* of the call, and 66 of those names are production symbols

**Real nodeid** `src/aipass/aipass/tests/test_install.py::TestCheckAndFixOwner::test_drone_not_found_is_silent`

```python
def test_drone_not_found_is_silent(self, tmp_path) -> None:
    from aipass.aipass.apps.modules.install import _check_and_fix_owner
    with patch("....install.subprocess.run", side_effect=FileNotFoundError("drone")):
        _check_and_fix_owner(tmp_path)
```

**v5 said** cleared by `no_oracle` — `_check_and_fix_owner` starts with `_check`, one of
`DELEGATING_PREFIXES`. It also flagged the same test under `docstring_pin` (`NO_DOCSTRING`).

**Haiku said** — unrecoverable per-row, but this is the exact shape the record calls SMOKE:
*"must never crash a caller" contracts where no-raise IS the contract*.

**My read: v5 over-clears here, in the safe direction.** The prefix rule was written to spot a
*checking helper*; it fired on the *production function under test*. Measured: of the 263
delegating clears, **66 delegate to a name not defined anywhere in that branch's test corpus** —
i.e. a production symbol, not a helper. Not all 66 are errors (`_verify_registry_credential` raises
on failure, so calling it is a real if weak oracle), and static reading cannot separate a weak
oracle from an absent one — which is precisely why haiku's SMOKE verdict exists. So the honest
statement is: **66 is the upper bound on this over-clear, and it inflates the 308 figure by an
unknown amount below 66.** Tightening the rule to names defined in the test corpus is a one-line
change that would move v5 *toward* flagging more, not fewer.

### One agreement worth naming

Both `test_reimport_after_mock` copies — `drone/tests/test_json_handler.py:611` and
`seedgo/tests/test_json_handler.py:709`, the campaign's smoking gun — are in v5's 203. On the single
row where the 30-sample calibration disagreed (haiku NO_ORACLE, opus SMOKE), **v5 sides with haiku.**

---

## Method, and every command

Step 1 — hunt for the per-test verdicts (all returned nothing; see *Limits*):

```bash
ls -la /home/patrick/Projects/AIPass/src/aipass/seedgo/.seedgo/
grep -rIl -E 'HAS_ORACLE|TAUTOLOGY|NO_ORACLE' /home/patrick/Projects/AIPass --exclude-dir=.git
grep -rIl -i 'haiku' /home/patrick/Projects/AIPass --exclude-dir=.git
find /home/patrick/Projects/AIPass -iname '*haiku*' -o -iname '*triage*' -o -iname '*verdict*'
# every .json/.jsonl touched since 2026-08-30, scanned for the label:
for f in $(find . -name '*.json*' -newermt '2026-08-30'); do grep -lq HAS_ORACLE "$f" && echo "$f"; done
drone @memory search "haiku triage 526 assertion_shape NONE HAS_ORACLE SMOKE NO_ORACLE TAUTOLOGY verdicts"
drone @memory search "per-test verdict rows chunk sub-agent classification test bodies nodeid verdict artifact"
```

Step 2 — run v5 over the fleet:

```bash
drone @seedgo audit                      # confirms packs: aipass (46), pytest_quality (11)
drone @seedgo audit pytest_quality       # 18 branches, 339.6s, avg 98%
python3 /tmp/v5_fleet_scan.py            # imports each *_check.py, calls check_branch per branch,
                                         # keeps the `violations` list -> /tmp/v5_fleet_scan.json
```

*(The CLI verb reports scores but drops per-nodeid evidence: it is advisory, so `passed: True`
leaves `violations: []` in `last_audit.json` and check messages truncate at `MAX_REPORTED = 12`.
The direct `check_branch` call is the only path to the full flag list.)*

Step 3 — the diff:

```bash
python3 /tmp/v5_vs_haiku.py       # v5 flags x the 526 NONE population, per rule
python3 /tmp/v5_clear_reasons.py  # v5 corpus coverage of the 526 + why each row cleared
python3 /tmp/v5_rule_rank.py      # rule ranking by flags landing on the healthy population
python3 /tmp/v5_split.py          # clear mechanism breakdown (delegating / assert_* / assert stmt)
python3 /tmp/v5_deleg_audit.py    # of the 263 delegating clears, is the name a real test helper?
```

**Ground truth for the haiku side** — aggregates only, from
`.backup/processed_plans/FPLAN-0468_test_ranking_phase_a_the_43_second_static_pas_2026-09-01.md`
(lines 213, 222–226) and re-confirmed via `drone @memory search`.
**Ground truth for the population** — `.seedgo/test_inventory_rows.jsonl` (28.7 MB, 19,437 rows,
generated by `drone @seedgo test-inventory aipass`, 2026-09-01). Recount here: 526 NONE / 18,423
REAL / 488 MOCK_ONLY — matches the plan exactly.
Nodeids normalised by prefixing v5's branch-relative id with `src/aipass/<branch>/`.

Side effect to note: `drone @seedgo audit pytest_quality` rewrote
`.seedgo/last_audit.json` (previously the `aipass` pack's fleet run). Regenerable.

---

## Limits — what this diff cannot establish

1. **There is no per-test agreement number, and there cannot be one from this data.** The haiku
   verdicts were sub-agent output in a 2026-09-01 session and were never persisted. Searched:
   `.seedgo/` (all 60 artifacts), `.backup/processed_plans/`, a full-repo grep for the four verdict
   labels, a full-repo filename sweep for haiku/triage/verdict, a label scan of every JSON touched
   since 2026-08-30, and two `drone @memory` queries. Independently corroborated —
   devpulse's own `docs.local/deletion_dossier_2026-09-02.md:151` states *"The haiku triage's
   per-row output is not on disk."* **No confusion matrix, no true false-conviction count, no
   per-row precision/recall.** Everything above is population arithmetic.
2. **A matching 308-vs-305 does not prove the same rows.** In principle v5 could flag ~N rows haiku
   cleared while clearing ~N rows haiku flagged. The evidence against is mechanistic, not
   measured: v5's only two clear mechanisms are literally the two the record names for haiku's
   HAS_ORACLE class, and v5 clears 100% of the 267 `delegated_oracle` rows. Treat this as strong
   circumstantial agreement, not proof. Re-running the triage on the 526 (~373k tokens, ~2.5 min at
   the recorded rate) would settle it and is the single highest-value follow-up.
3. **995 of v5's 1,198 non-`docstring_pin` flags have never been judged by anything.** Haiku only
   ever looked at the 526. `mock_drift` (342), `assertion_shape` (296), `capture_never_read` (130),
   `unentered_assert` (110), `self_skip` (98) and four smaller rules fire almost entirely outside
   the triaged population. Their false-conviction rate is **unmeasured**, and this diff says
   nothing about it. Their zeros in the ranking table mean *"no overlap with the calibrated
   population"*, not *"validated as safe"*.
4. **Corpus definitions differ** — 18,827 v5 units vs 19,437 inventory functions. That is a 610-unit
   definitional gap (test-dir walk, class rules, parked dirs), not a disagreement about any test.
   15 of the 526 fall in it, and those 15 are named in section 2 above.
5. **No behavioural evidence anywhere in this document.** Neither judgement ran a test, mutated a
   line, or measured coverage. Whether a flagged test would have caught a real defect is untested by
   both. ISSTA 2018 still applies: a low signal means *look at this*, never *remove this*.
6. **v5 gates nothing today, and this diff does not argue that it should.** All 11 rules ship
   `advisory: True` and `passed: True`. The number relevant to a gate decision is in row 2 of the
   ranking table: gating `no_oracle` at 100 would red **203** tests, and the calibrated read says
   roughly **7** of the fleet are genuinely oracle-free. The rest are SMOKE — many deliberately so.

## What this diff supports, if a ruling is wanted

- **v5's `no_oracle` is safe to promote out of shadow as a *reported* number.** It reproduces a
  calibrated LLM read to within 3 rows of 526 using pure AST, and convicts none of the population
  that read cleared.
- **`docstring_pin` stays unscored.** This is the first measurement that puts a number on why.
- **Two cheap fixes before any gate ruling**: widen `TEST_DIRS` so the 15 blind rows enter the
  corpus, and tighten `DELEGATING_PREFIXES` to names defined in the test corpus (≤66 rows affected).
- **v5 is not yet ready to *replace* v4 at the gate** — not because it is wrong, but because 8 of
  its 11 rules fire on a population nothing has ever calibrated. Those need their own shadow diff.
