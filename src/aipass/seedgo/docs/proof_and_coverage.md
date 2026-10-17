[<- Back to the README](../README.md)

# Proof, coverage and the test lanes

**Branch** seedgo · **Code** `apps/handlers/aipass_proof/`, `apps/handlers/test_map/`,
`apps/handlers/test_inventory/`, `apps/handlers/shadow_cycle/`, `apps/handlers/audit_tests/`

Four different questions live here, and they are genuinely different. The verbs are in
`drone @seedgo --help`.

---

## 1. Proof — does the pack hold together?

`proof` runs the `aipass_proof` pack over a standards pack: five validators that audit the
auditor rather than a branch.

| Validator | What it certifies |
|---|---|
| `triplet.py` | Pack triplet completeness — every standard has `_check.py` + `_content.py` + `.md` |
| `interface.py` | `AUDIT_SCOPE` present and the checker function signatures match the contract |
| `plugin_integrity.py` | No hardcoded standard names anywhere in the plugin surface |
| `content_naming.py` | Content-module function naming conventions |
| `readme_currency.py` | README freshness against its own markers |

The verdict is CERTIFIED or NOT CERTIFIED for the whole pack — a single failing validator
withholds certification, deliberately. Seedgo does not currently certify its own pack.

---

## 2. `test_map` — which public functions have a test?

`test_map` scans a branch's public functions (`apps/handlers/test_map/function_scanner.py`)
and reports which ones are named by a test. It is a *nomination* instrument: the number it
prints is "functions a test mentions", not "functions that are proven". Run it on a branch
and read the untested list; do not read the percentage as a grade.

---

## 3. `test-inventory` — every test in a tree, ranked for reading

The static lane (`apps/handlers/test_inventory/`): collection, exclusions, ranking, twins,
history, shape. It lists every test function in a tree and ranks them so a human reading
budget goes to the rows most likely to be worthless. `--twins` reports same-named tests
across branches — the shape that means one of the two is a copy nobody re-read.

It runs nothing. That is the point: it is the phase-A inventory the scoring pack and the
execution lane both stand on.

---

## 4. `audit-tests` — the execution lane

`audit-tests` measures how much a suite proves **by running it**: the target's tests execute
inside a COPY, under a `sys.addaudithook` write gate, and the lane refuses to publish a score
unless a planted canary proves the gate can actually fire (`selfcheck.py`, `refusal.py`).
Every score is printed beside a statement of what the gate cannot see.

`tests_pytest_standards/` is its adapter pack: nominators, not checkers, and never scored.

---

## 5. The weekly cadence

`shadow-cycle` runs the three measurement passes back to back — the v5 score
([pytest_quality.md](pytest_quality.md)), the static inventory, the twins report — and mails
one summary. `--no-mail` prints instead of sending.

---

## How this branch's own tests are counted

Two numbers answer two different questions, and both are honest:

- **`def test_` functions** — what seedgo's own `readme_check._count_test_functions()`
  counts, and therefore what the `test_count_accuracy` standard compares a README claim
  against.
- **pytest cases** — what the run reports once parametrisation expands. A parametrised
  contract over every citizen is one function and many cases.

Neither number belongs in the README: it rots the day a test lands, and
`test_count_accuracy` only fires when a claim exists. Run the suite from the repo root in the
CI shape and read the real number:

```
python -m pytest src/aipass/seedgo -c pyproject.toml --rootdir=.
```

The json handler's behaviour is tested once, parametrised over every citizen's shim, in
`tests/test_json_handler_contract.py`.

**Skips are documented, not silent.** Every skip names its reason in its message: a sibling
branch's file that is not on this machine (`tests/test_checkers_batch7_json_structure.py`,
`tests/support_json_handler_contract.py`), a platform that cannot make a directory unlistable
(`tests/test_audit_tests_core.py`), or a live-state guard in `tests/test_trinity_check.py`
with no fleet tree, no live observations file or no drifted citizen to find.

**A live-state guard will go red on another branch's write.**
`TestFleetAcceptanceBar::test_exactly_six_citizens_are_canonical_on_observations` reads the
whole fleet's `.trinity/observations.json`. When it fails because a neighbour added an entry
without `tags`, that is their file and their cure — report it, do not edit it, and do not
loosen the equality to keep the board green.

---

## Related

- [pytest_quality.md](pytest_quality.md) — the rules the weekly score runs
- [aipass_standards.md](aipass_standards.md) — the pack the proof lane audits
