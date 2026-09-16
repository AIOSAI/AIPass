# pytest_quality — the v5 test-quality pack

**Branch** seedgo · **Pack** `apps/handlers/pytest_quality_standards/` · **Verb** `drone @seedgo audit pytest_quality [@branch]`
**Live roster** `drone @seedgo standards_query pytest_quality_standards`
**Status** shadow — it scores and gates nothing (`pack.json` says so, with the reason).
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

---

## What it is

A **generic** pack: it judges what a test proves, over any pytest project, not over AIPass
conventions. Every rule is an AST reading of a test function; none of them reads prose, and
none of them convicts — each one *nominates* a unit for a human read.

Corpus is declared in `pack.json` (`tests/` only; `apps/` is read by the rules that name it)
and measured by `corpus.py`. The banner over a score is that declaration, not the engine's
file count.

It replaced `aipass_standards/test_quality` (v4), which scanned test files as TEXT and
awarded items for substrings — see [aipass_standards.md](aipass_standards.md).

---

## The rules

Each rule ships the usual triplet; the `.md` beside the checker carries the failure case and
the escape hatch. One line each here, nothing more — the rule file is the source.

| Rule | The question it asks |
|---|---|
| `assertion_shape` | Can this test's assertion actually fail, or is it true of every possible program? |
| `capture_never_read` | Did the test look at what it arranged to capture? |
| `coverage_slot` | Does the test say out loud that it exists for coverage? |
| `docstring_pin` | Does the docstring name anything the test touches? Structural only, never a prose match — and unscored on purpose. |
| `empty_parametrize` | Did the table vanish at collection time, leaving a green skip? |
| `entry_point_diff` | Has the suite ever said this verb out loud? |
| `fresh_clone` | Would this pass on a machine that has only what the repo ships? |
| `host_state` | Did the test put the machine back? (About the restore, never the reach.) |
| `mock_drift` | Does this patch replace a function, or a whole module? |
| `module_eviction` | Did the test put the import cache back? |
| `no_oracle` | Does this test verify anything at all? |
| `platform_oracle` | Is the verdict about the code, or about the host it ran on? |
| `posix_literal` | Is this path claim only true on one platform? |
| `self_skip` | Where does the skip condition get its answer — the code, or a name that can vanish? |
| `unentered_assert` | Does the assertion ever actually run? |

---

## Why it does not gate

Shadow status is a calibration decision, not timidity. `docstring_pin` carries the pack's
whole false-conviction risk and is unscored for exactly that reason; the population-level
diff against the calibrated haiku triage is in
[v5_vs_haiku_shadow_diff.md](v5_vs_haiku_shadow_diff.md), including what a population-level
comparison cannot tell you.

---

## The weekly cadence

`drone @seedgo shadow-cycle run` runs the three passes back to back — the v5 score, the
static inventory, and the twins report — and mails one summary (`--no-mail` prints instead).
See [proof_and_coverage.md](proof_and_coverage.md).

---

## Related

- [proof_and_coverage.md](proof_and_coverage.md) — inventory, twins, test_map, the execution lane
- [aipass_standards.md](aipass_standards.md) — the v4 pack this one replaced a rule in
- [audit_engine.md](audit_engine.md) — how any pack is discovered and scored
