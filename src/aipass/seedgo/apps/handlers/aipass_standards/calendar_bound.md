# Calendar Bound
**Status:** Draft v1.0 (the 2026-09-13 CI red, daemon slot seeder)
**Date:** 2026-09-13

---

## What It Is

A standard that catches a test whose verdict is a fact about **today's date**
rather than about the code: it asserts a date literal against code that computes
with the clock, and nothing in the test owns the clock.

---

## Why It Matters

main (16bcf3c4, Windows run 34731222219) and PR #767 (Linux CI 34769664864 on all
four Pythons plus coverage, Windows 34769664829, macOS) went red on one test on
every host:

```
src/aipass/daemon/tests/test_run_module.py::TestSlotSeeding::test_a_slotted_job_is_seeded_before_it_can_fire
AssertionError: assert '2026-09-13T03:00:00' == '2026-09-06T03:00:00'
```

The weekly slot seeder rolls a slot forward to the latest occurrence at or before
`datetime.now()`. The test asserted the seeded value as a literal and froze
nothing, so it was true from 2026-09-06 to 2026-09-12. It merged green in v2.8.7
(PR #763) and turned red when the calendar reached 2026-09-13T03:00. Every gate
ran inside its one-week window.

**Why no existing rule saw it.** `pytest_quality` judges what a test proves, and
a literal equality is a strong oracle, so `no_oracle` and `assertion_shape` score
it as good. `platform_oracle`, `host_portability` and `windows_compat` ask which
HOST a test needs, never which DATE. `host_state` asks whether the machine is
restored, and reading the clock changes nothing. The execution lane
(`audit-tests`) runs the suite on today's date, which is exactly the blind spot.
No rule in either pack read the clock.

---

## What the Checker Scans For

AST-parses every `.py` file under the branch's `tests/` and each `lib/<skill>/tests/`,
and reads production through the tests' own imports under the package root. A unit
is convicted only when **all three legs** stand.

### Leg 1 — the unit asserts a date literal
An ISO string (`"2026-09-06"`, `"2026-09-06T03:00:00"`, with optional seconds,
fraction and offset) or `datetime(...)` / `date(...)` with integer literals for
year, month and day. It must be an operand of an `assert` comparison or a
unittest `assert*` method.

### Leg 2 — the unit reaches code that COMPUTES with the clock
Calls are followed by name, breadth-first, up to 6 hops: a bare name (local or
imported), `self.`/`cls.` methods, and `module_alias.function`. The walk stops at
the first function that feeds `datetime.now()` / `utcnow()` / `today()`,
`date.today()`, `time.time()` / `time_ns()` or a bare `localtime()` / `gmtime()`
(or a local name bound to one, or a one-level wrapper that returns one) into
**arithmetic, an ordering or equality, or another call**.

**A stamp is not a derivation.** A value turned into a string (`isoformat`,
`strftime`), checked against `None`, logged, formatted, or stored (`setdefault`,
`update`, `append`, `dump`) cannot change what another field holds. This is where
the noise died. The row message names the NEAREST computation on the path, which
need not be the one that produced the asserted value: the incident names
`runstate.py:321 is_catch_up_fire`, and the value came from `seed_interval_slot`.

### Leg 3 — the unit does not own the clock

**Owning the clock** (acquits, and is the cure):
- a `patch` / `patch.object` / `monkeypatch.setattr` whose target names datetime,
  date, time, now, today, clock, freeze or frozen — in the unit, its class's
  helper methods, or a same-file function the unit calls;
- an injected instant: a `now=` / `clock=` / `today=` / `at=` / `when=` /
  `timestamp=` / `ts=` / `moment=` keyword, or a `datetime(...)` literal passed
  positionally to a call;
- a fixture parameter named for a clock (`frozen_now`, `fixed_clock`);
- `@freeze_time` / `time_machine` on the unit or its class;
- an autouse fixture in the file or in a conftest.py above it that patches one.

**Not owning it:** a patch whose every named target is `sleep`, `monotonic` or
`perf_counter`. It stops a wait or a stopwatch, never the calendar.

**Cut from the walk:** every call the unit patched. A stubbed seam is not a road
to the clock.

### Also acquitted — a date production spells itself
`"2026-09-08" in step[2]` (ai_mail `test_wake`) is a ruling date written into the
refusal text: a fact about the code. The check reads production modules on the
trail only, and matches by substring inside a string constant. It excludes any
module under a `tests` directory and excludes docstrings. The first build read
the test module as production, and the incident's own helper default
(`slot="2026-09-06T03:00:00"`) acquitted it.

### Deliberately not claimed (all in the direction of fewer flags)
- an expected value held in a parametrize table or a variable is not read, only
  a literal operand (daemon's frozen-clock cure uses a table)
- a function reached through an object other than `self`/`cls`, a module alias
  or an import is invisible
- a unit that freezes the WRONG module's clock is acquitted
- the audit cache does not watch production in OTHER branches: a cross-branch
  clock change is picked up on the next `--full` or tests/apps edit

**Measured and rejected:** "the expected date appears nowhere else in the unit"
cut 58 to 12. It was rejected because the incident's date DOES appear as input
(the slot default), and inlining the helper would launder a real time bomb.

---

## Code Examples

### Violation — the expected value is a fact about now
```python
class TestSlotSeeding:
    def test_a_slotted_job_is_seeded_before_it_can_fire(self, capsys):
        runstate = {"jobs": {}}
        results, _save = self._tick(interval_job_with_slot(), runstate)   # seeder reads datetime.now()
        assert runstate["jobs"]["@seedgo/shadow-cycle-weekly"]["last_run"] == "2026-09-06T03:00:00"
```

### Fix 1 — freeze the clock the code reads (daemon's cure)
```python
def freeze_runstate_clock(monkeypatch, at: str) -> None:
    frozen = datetime.fromisoformat(at)
    real = runstate_mod.datetime

    class Frozen(real):
        @classmethod
        def now(cls, tz=None):
            return frozen

    monkeypatch.setattr(runstate_mod, "datetime", Frozen)
```

### Fix 2 — inject the instant
```python
seeded = seed_interval_slot(runstate, job, now=datetime(2026, 9, 13, 12, 31))
```

### Fix 3 — write the expected value by hand from a calendar, per frozen now
```python
@pytest.mark.parametrize("now,seeded", SLOT_SEED_CASES, ids=SLOT_SEED_IDS)
```

---

## Scoring
- **Scope:** AUDIT_SCOPE = "branch_level", entry point `check_branch()`
- **Corpus:** `tests/` and `lib/*/tests/` (the latter declared in `BRANCH_INPUTS`
  so the audit cache watches it)
- **Score:** `clean test files / total test files x 100`
- **Score 100:** no date literal asserted against an unfrozen clock
- **Failure message:** "N calendar-bound assertion(s) in M/T test files: …"
- **Context line:** a second `passed: True` check counts units that reach the
  clock and already own it, and units asserting a date production spells.
  Context, never scored.
- **Overall pass threshold:** 75%

---

## Measured Baseline (2026-09-13, 18 branches, 603 test files, 9.3 s)

The funnel, from the shape as first posed to the rule that landed. Every row was
read.

| Shape | Units convicted | On reading |
|---|---|---|
| date literal asserted + an imported module calls the clock + no freeze in the unit | 58 | 1 real (the incident), 57 round trips |
| + the expected date appears nowhere else in the unit (**rejected**) | 12 | 1 real, 9 round trips, 2 injected positionally |
| call-graph reach to ANY clock use + ownership | 7 | 1 real, 6 stamps |
| **reach to a clock COMPUTATION + ownership + production spelling (landed)** | **1 at HEAD, 0 after daemon's cure** | 1 real, **0 false** |

**Stamps named at the reach stage (all clear under the landed rule):** ai_mail
`test_dispatch_status::test_save_dispatch_log` (strftime into a dict);
ai_mail `test_wake::test_a_refusal_is_a_warn_step_naming_target_model_and_ruling`
(strftime into the lock dict); api
`test_tracking::test_store_usage_data_writes_back_the_keys_it_does_not_own`
(isoformat, then setdefault); daemon
`test_run_blocked_contract::test_record_job_blocked_leaves_last_run_untouched` and
`::test_blocked_is_named_in_the_record` (isoformat default); daemon
`test_runstate::test_a_caught_up_run_is_recorded_as_one` (isoformat default).

**Round trips named at the textual stage:** ai_mail `test_wake` x2 (ruling date),
api `test_host_fleet::test_rooms_carries_the_snapshot_timestamp`, devpulse
`test_admin_grant::test_mint_signs_and_preserves_existing_fields`, flow
`test_restore_ops::test_the_rows_own_metadata_survives_the_restore`, hooks
`test_post_compact_regrounding::test_stale_scaffold_names_both_versions_and_the_preview`,
memory `test_unified_schema::test_entry_number_and_date_land_in_metadata`, spawn
`test_passport_seeds::test_strips_no_more_than_that`, spawn
`test_repair::test_updates_path_preserves_fields`. Also daemon
`test_runstate::TestSlotAnchor` x2, where the clock is injected positionally.

**Acquitted under the landed rule (9, the context line):**

| Unit | Why |
|---|---|
| ai_mail `test_upsert::test_upsert_match_updates_in_place` | injects the instant |
| ai_mail `test_wake::test_a_refusal_is_a_warn_step_naming_target_model_and_ruling` | production spells 2026-09-08 (its helper's `time.sleep` patch owns nothing) |
| daemon `test_runstate::test_seeding_moves_the_first_fire_to_the_next_slot` | `now=` |
| devpulse `test_watchdog_schedule` x6 (`test_parse_schedule_*`) | clock fixture |

**The catch:** HEAD `test_run_module.py:404`, 4 calls in (`_tick` → `run_tick` →
`_tick_body` → `runstate.py:321`). daemon calendar_bound **95** (20/21 files).
The branch average falls below CI's 100 threshold. After daemon's cure: **100**,
fleet 18/18 at 100.

---

## Bypass

Line-level bypass (a date that is genuinely constant, reached through a path
the rule cannot see is a stamp):
```json
{"file": "tests/test_report.py", "standard": "calendar_bound",
 "lines": [88], "reason": "the header date is a release constant read from pyproject"}
```

---

## Reference
- **Checker:** calendar_bound_check.py
- **Scope:** branch_level
- **Entry point:** check_branch()
- **Standard label:** CALENDAR_BOUND
- **Sibling:** host_portability (which host a test needs; this is which date)
