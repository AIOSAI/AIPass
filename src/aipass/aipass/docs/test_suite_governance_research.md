# Test-suite governance — ranking, culling, and the AI angle

**Author:** @aipass · **Date:** 2026-09-01 · **Assigned by:** Patrick, dispatched via @devpulse
**Round 2.** Round 1 is `docs/test_quality_tooling_research.md` (2026-08-29) and is the foundation; this
document does not re-research it. Where round 1 was wrong, §0.1 says so.

**The question that changed.** Round 1 asked *can we measure test quality* and answered it. This round asks
a different question: **20,320 tests, most written by AI agents, and nobody can say which 5,000 matter.**
That is volume governance, not measurement.

**Constraint honoured throughout:** OPEN-SOURCE / FREE only. Every tool named carries its license, verified
from a LICENSE file, the GitHub API `license.spdx_id`, or a PyPI license field — never guessed. Anything
proprietary, source-available-but-not-OSI, freemium, or license-absent is excluded.

**Method:** four research sub-agents (culling precedent · the AI angle · per-test tooling feasibility ·
seedgo's existing lane), which themselves spawned three more. Papers were read as full text via
`pdftotext`, not from search snippets — one agent explicitly caught its own PDF summariser inventing
plausible round numbers for the Google TAP paper and re-extracted. Tooling costs were **measured on this
machine against this fleet**. Measured figures are marked *(measured)*; scaled figures are marked
*(extrapolated)* with the basis stated; anything else is marked **unconfirmed**.

**Resource note (round-1 lesson applied):** every agent was given an explicit budget — no installs, no
docker, no clones, scratch in `/tmp` and named. Nothing was installed. `/tmp/q1/` holds 48 MB of raw
measurement artifacts; the paper extracts are in `/tmp/*.txt`. The repo tree was verified unmodified by
`git status --porcelain` diff before and after.

---

## 0. The five findings that should drive the design session

**1. 🔴 The metric you would use to authorise a deletion does not predict the harm the deletion causes.
This is the single most important result in the literature and it refutes the obvious plan.**

Shi et al. (ISSTA 2018) reduced test suites on 32 real projects, then replayed **1,478 real failed CI
builds** against the reduced suites. At the moment of reduction it looked nearly free: **51.9% of tests
removed for a 2.7% mutant-detection loss**. Measured against what actually happened next, those same suites
**missed between 26.1% and 52.2% of real failed builds**. Mutation-guided reduction — suites constructed to
kill *exactly the same mutants* — still missed **13.1% to 36.2%**.

The predictors all fail: size reduction R² ≤ 0.26; mutant-detection loss R² = 0.25 (0.02–0.03 for most
variants). Their own sentence: *"mutation testing is not a good predictor of FBDL for reduced test
suites."* And the verdict: *"Automated TSR is more risky than suggested by prior research."*

**Consequence: rank with mutation score, never authorise deletion with it.** A zero mutation-score delta
earns a test a demotion, not a grave.

**2. Neither Google nor Meta deletes tests. Both run them less often. There is one published numeric
deletion rule on Earth and it has a human approval gate.**

Google TAP (ICSE-SEIP 2017, 5,562,881 test targets): **91.3% of tests never failed once**; only **1.23%**
of executions ever caught a real breakage. Their remedy is explicitly *"re-executed less frequently"* —
MinDist ≤ 10 ran 61% of targets, saved 42% of resources, and *"did not miss a single breakage or fix."*
The word *delete* never appears as a remedy. Meta's predictive test selection accepts a <5% test-recall
miss **only because every test still runs in the stabilization stage every few hours**.

The sole published numeric retirement rule found anywhere is **GitLab's**: fast quarantine 3 days →
long-term quarantine 3 months → 1-week deletion warning → removed. And GitLab's own text calls it
*"semi-automatic process, not fully automatic"* — a human merges the deletion MR. Mozilla, Chromium,
Google, Uber, LinkedIn, Slack, Dropbox, Shopify, Microsoft, Kubernetes and every commercial CI vendor
publish automation for *entering* quarantine and **nothing automated for retirement**.

Every "delete after N quiet cycles" rule in circulation traces to vendor marketing with no data and no
organisation named. **If we adopt a numeric retirement rule we are ahead of published precedent, not
following it — and we should instrument accordingly.**

**3. ✅ The enabling technology is free, and we already run the job it belongs in.** *(measured)*

`coverage.py` dynamic contexts (`--cov-context=test`) record **which test covered which line**. The
surprise: **turning contexts on costs nothing.** In three of four paired runs on this fleet the context run
used *less* CPU than plain coverage — inside the ±13% noise floor of this box. The expensive step is
enabling coverage at all (+45% to +83%); attributing each line to a test on top of that is free.

Mechanism verified in installed source, not guessed: `coverage/core.py:77` refuses `sys.monitoring` when
dynamic contexts are set, but `coverage/env.py:56` gates `sys.monitoring` on Python ≥ 3.14 — so on 3.10–3.13
(what CI runs) the C tracer is used either way and there is no penalty. **This is a dated finding that flips
when the fleet moves to 3.14.**

It survives xdist unchanged (measured: 207 contexts / 262 line_bits rows under `-n 4`, byte-identical to
serial). Database size **≈6 MB at 20k tests** (extrapolated from a measured marginal 293 B/test; 20–40 MB
if the fleet average is 3–5× heavier than the module measured). **`ci.yml:105` already runs a coverage
job.** This is a one-flag change to existing infrastructure.

One trap: never call `coverage json --show-contexts` — measured **21.8 s and a 27.4 MB JSON from a 401 KB
database**. Read the SQLite directly with `coverage.numbits`: **0.02 s** for the same data.

**4. The cheapest useful signal needs no infrastructure at all, and it already found something.**
*(measured, and independently re-measured by me with a separate implementation)*

A pure-static pass over the fleet — `git blame` once per file plus AST line-range mapping, plus an
assertion-shape scan — takes **~43 seconds for all 20k tests** and needs no CI change, no plugin, no
coverage run.

It has already produced: **478 test functions that contain no assertion, no `pytest.raises`, no `assert_*`
call, and no check of any kind** (my count over 626 files / 19,471 functions; the sub-agent's independent
run said 466 over 584 files / 18,283 functions — the gap is corpus definition, both ≈2.5%). Also ~465
mock-assert-only change-detector risks, a full age distribution (p50 = 53 days, p90 = 149 days), and
authorship: **AIOSAI 15,146 tests, AIPass 3,036, humans 52**.

Two findings fell out that nobody was looking for: **10 test files on disk are not in git at all**, and two
of them — `api/tests/test_devto_driver.py` and `api/tests/test_bluesky_driver.py` — **are collected and run
on this machine and can never run in CI**. The other eight are under `.archive/` and excluded by
`norecursedirs`.

**Corrected 2026-09-02** (@devpulse caught it; re-verified independently before editing). This paragraph
first said those two files were "collected and run by CI with no history." **That was backwards.** They are
gitignored *by name* at `src/aipass/api/.gitignore:15-16`, deliberately — DPLAN-0133 makes the
private-integration driver layer gitignored, so its tests are too. A CI runner clones from git, so those
files have never existed there and CI has never collected them.

The corrected version is the more interesting finding: **25 test functions (13 + 12, counted by AST) run
locally that no CI leg can ever run.** A local composed verify and a CI run therefore measure slightly
different universes — the exact class of divergence worth instrumenting.

**The label is what was wrong, and the fix generalises:** an UNTRACKED column has to distinguish
**IGNORED-BY-RULE** (a deliberate local/CI divergence) from **MISSING-BY-ACCIDENT** (a lost file). The
first is a governance signal; the second is a defect. Collapsing them is how the original error happened,
and a ranked inventory that reports "untracked" without that split will mislead whoever acts on it.

**5. Build it inside seedgo's lane — the argument is from what the lane already has, and the blocker is a
law, not architecture.**

The lane **already enumerates every test in the fleet as a first-class object with a pytest nodeid**
(`corpus.py:77-95`, `TestUnit.nodeid`), **already emits a per-test row schema** (`corpus.py:355-377`:
`{species, file, line, nodeid, test, verdict, why, deletion_safety, evidence}`), and **already records the
full runtime nodeid order** (`executed_order`, 2,924 nodeids on seedgo) with per-(nodeid, phase) write
attribution. The join key, the enumerator and the row shape all exist and run today.

What is missing is small and specific: (a) a row for *unflagged* tests — today only nominations survive
(163 nodeids published out of 2,639 scanned); (b) per-test outcome and duration, which is **two pytest
hooks** on a plugin that is already installed and already proven by canary; (c) history, which the artifact
model has none of.

**The real blocker is Law S7a** (`laws.py:184-186`): any artifact where a non-`hygiene` group carries a
score is *refused*. And `ALLOWED_VERDICTS` is a closed set of four words with a `DELETE_FAMILY`
(`useless, delete, remove, worthless, dead`) refused outright. **A ranked inventory that published
anything resembling "this test is worthless" would be rejected by the lane's own validator — which,
given finding 1, is the lane being right.**

---

## 0.1 Correction to round 1: the category is no longer empty

Round 1's finding 1 read: *"There is no maintained, library-grade tool in any language that grades oracle
quality in Python."* **That claim was too strong, and it was already false when I wrote it.** Two
MIT-licensed Python tools existed on 2026-08-29 and I missed both. I verified them myself against the
GitHub API rather than taking the sub-agent's word:

| Tool | What it does | License | Created | Last push | Stars |
|---|---|---|---|---|---|
| [`falsegreen`](https://github.com/vinicq/falsegreen) | *"Find false-green tests: tests that pass without verifying anything. Deterministic Python/pytest AST scanner (C1-C59), zero-dep, CI-ready."* | MIT (API `spdx_id`) | 2026-06-02 | 2026-08-11 | **2** |
| [`TestIQ`](https://github.com/pydevtools/TestIQ) | Duplicate/redundant test detection via per-test coverage overlap | MIT (LICENSE file read) | 2026-01-13 | **2026-01-18** | **5** |

`falsegreen` is the closer miss and the more embarrassing one: its check family C is literally
*"Tests checking themselves, not the program (mocking the unit under test, self-confirming assertions)"* —
our exact problem statement — and its README says *"This matters more now that a large share of tests come
from AI assistants."*

**The honest restatement: the category is EMBRYONIC, not empty.** `falsegreen` is alpha (`Development
Status :: 3 - Alpha`), v0.9.2, single-author, 2 stars, unproven at any scale, let alone 20,320 tests.
`TestIQ` had five days of development in January and nothing since, and its PyPI homepage URL 404s. Round
1's *conclusions* — that we are not duplicating a mature ecosystem, and that everything comparable and
load-bearing exists only for Java — still stand. The *sentence* did not, and the difference matters because
somebody could have installed `falsegreen` in five minutes at any point in the last three months.

**Why I missed it:** round 1 searched for tools that grade *oracle quality* as a category term. `falsegreen`
markets itself on "false-green tests" and `TestIQ` on "duplicate tests" — neither uses the vocabulary I
searched. A negative result is only as good as the vocabulary it was checked against, and mine was one
vocabulary deep.

**Also unchanged and worth restating:** Descartes / extreme mutation / pseudo-tested methods remain
**Java-only with no Python port**. That half of round 1's negative result was re-checked and holds.

---

## 1. Q1 — The ranked inventory

### 1.1 What it costs to compute each score component

All costs measured on this machine (4 logical cores, Python 3.12.3) against this fleet unless marked.
Fleet ground truth *(measured)*: **20,320 tests collected in 24.78 s**; 584 collectable test files;
174,594 non-blank source lines.

| Component | Tool | License | Cost at 20k | Cadence |
|---|---|---|---|---|
| Per-test runtime | pytest core hook (~20 lines) | MIT | **~0** — measured inside the noise band | Weekly, free rider |
| Per-test coverage footprint | `pytest --cov-context=test` | pytest-cov MIT, coverage Apache-2.0 | contexts **+0%** on top of coverage; DB ≈6 MB | **Weekly** |
| Redundancy / subset | ~150 lines over `coverage.numbits` | Apache-2.0 | **~16 s** with an inverted index | Weekly |
| Assertion vs implicit kill | `pytest_runtest_makereport` + `call.excinfo.typename` | MIT | ~0 — **but yields nothing on a green suite** | Weekly (static proxy) |
| Static assertion shape | AST scan | stdlib | **12.4 s** for all 18,283 functions | Weekly |
| Age & author | `git blame` per **file** + AST mapping | GPL-2.0 / PSF | **30.8 s** whole fleet | Weekly |
| Flakiness history | `pytest-reportlog` → own SQLite | MIT | sink ~0; **signal costs N× the suite** | Weekly accumulation, matures over weeks |
| Mutation-kill attribution | cosmic-ray (MIT) or mutmut 3 (BSD-3) | verified | **tens of CPU-hours** *(extrapolated from 174,594 LOC → ~150k–350k mutants)* | **One-off, sampled** |

**Three traps found by measuring rather than assuming:**

- **`--durations` is the wrong sink.** Output is `%.2f`-formatted — 60,960 lines of terminal text at 20k
  scale with most tests rounding to `0.00s`. `TestReport.duration` carries full float precision
  (measured: `0.00033979900763370097`). One hookwrapper gets duration *and* exception type together.
- **JUnit XML cannot carry the assertion/implicit split.** *(measured)* pytest emits **no `type=`
  attribute on `<failure>` at all** — verified in `_pytest/junitxml.py`, `_add_simple` builds
  `ET.Element(tag, message=message)`. Worse, `exconly(tryshort=True)` strips the `AssertionError:` prefix
  specifically for rewritten bare asserts, so any prefix-parsing heuristic is asymmetric and wrong. JUnit
  XML is structurally unusable here. `report.__dict__` *is* serialized, so a custom attribute rides
  through xdist and `--report-log` for free.
- **`git log -L` per function is ~100× worse than blame-per-file.** *(measured)* 0.05–0.12 s each →
  ~27 minutes for the fleet, versus **31 s** for blame-once-per-file plus AST line-range mapping.

**And one trap in the redundancy signal itself, which is the finding that keeps this honest:**
*(measured on real data)* **39–75% of tests in the modules analysed execute a strict subset of another
test's lines.** Example: `test_help_flag_returns_zero ⊆ test_help_preempts_command_routing`. These are
**not deletable** — they assert different things about the same code path. Combined with finding 1,
**line-subset is a wildly over-eager retirement signal and must never be more than one column.**

Algorithmically it is cheap if done right *(measured, synthetic 20k × 60k)*: inverted index on the
rarest covered line cuts 200M comparisons to **466k — a 430× reduction — total ~16 s**. Naive all-pairs is
22.4 min in pure Python and **20.3 min with 5.3 GB RSS in numpy** — vectorising bought nothing because the
problem is memory-bandwidth bound. **The algorithm is the win, not the array library.**

### 1.2 Does a ranked-test-inventory tool already exist?

**No.** Searched across five vocabularies (suite reduction/minimisation, test impact analysis,
coverage-context analysis, test smells, suite health). *"Test value score"* and *"ranked test inventory"*
are not established terms.

**Every existing tool answers "which tests should I run right now?" Almost none answers "which tests should
still exist?"** The closest is `TestIQ`, whose score is **suite-level 0–100, not per-test**, and which uses
`sys.settrace()` (conflicting with coverage.py). Read it as a design reference, not a dependency.
Commercially the gap is nearly as wide: CircleCI Test Insights is literally a ranked list — **capped at 100
rows, 14-day window**. The nearest published work is Apple's *Modeling and Ranking Flaky Tests* (ICSE-SEIP
2020) and Microsoft's THEO (ICSE 2015), the only formal per-test economic value model in the literature.
Both are papers, not tools.

### 1.3 Recommendation: upgrade the lane, do not build a separate piece

**Arguments from what the lane already has** (all file:line verified by a read-only sub-agent audit):

1. `TestUnit` with a `nodeid` property already enumerates every test function — 2,639 on seedgo alone
   (`corpus.py:77-95`, `:148-152`).
2. The per-test row schema already exists and is published (`corpus.py:355-377`).
3. **11 static nominator groups already emit per-test rows keyed by nodeid** — a fact the dispatch's
   summary omitted, and the single most decision-relevant thing in the codebase.
4. The runtime side already has the join key: `executed_order` (2,924 nodeids), per-(nodeid, phase)
   attribution (`payload:356`), `"attribution": "nodeid"` declared in `gatelog.py:176`.
5. The missing runtime fields are **two hooks**. The plugin implements `logstart/logfinish/setup/call/
   teardown` but not `pytest_runtest_logreport`. Outcome and duration are the cheapest possible addition to
   a plugin already installed, already proven, already inside the gated child.
6. The isolation infrastructure a from-scratch tool would need is expensive and built: rsync copy-first
   with a measured M10 proof, adapter contract, wall-clock budget, refusal vocabulary, atomic lawful
   publication, and 4,907 lines of tests defending it.
7. Adding a static species is **three files and one line**, pinned by a test that asserts
   `nominators.declared_groups() == sorted(adapter.STATIC_GROUPS)`.
8. **Cost is already sunk** — the fleet pass runs ~893 s anyway. A separate piece runs every suite a
   second time.
9. **The lane's honesty machinery is a feature for this product, not friction.** Law S1 (`not_applicable`
   with a reason, never 0), S8 (a scored group must declare its blind spots), M11 (`deletion_safety.probed:
   false` on every row today). Given finding 1, a ranked inventory published *without* these is precisely
   the confidently-wrong number that would get tests deleted.

**The honest arguments against, which shape the design rather than defeat it:**

- **Law S7a forbids a score outside `hygiene`**, and promotion into `SCORED_GROUPS` requires *"a measured
  fleet-wide distribution of those counters in hand at ruling time"* plus a `gate_coverage.blind` list or
  the artifact is refused. **This is a governance step, not a code step, and it should be taken
  deliberately.**
- **No history.** One artifact per target, overwritten; the previous copy read only for the S3 group diff.
  Flakiness ranking needs N runs. **History is a new store, not a new field.**
- **Granularity inversion downstream.** `exit_code_for()`, `render.py`, the fleet summary and the 5-rows-
  per-group render cap are all written around one score per target.
- **Artifact size.** Already 6 KB–1.7 MB with ~163 flagged nodeids; a row per test is ~18× that.
- **Serial-only, and not CI's configuration.** The lane measures branch-rootdir serial and says so in
  words; the design states the gate *cannot* run under xdist as built (module-singleton state, one log
  path). **Per-test durations under the configuration people actually run cannot come from this harness
  today.**
- Two execution groups (`scoped_survival`, `targeted_mutation`) are already queued with binding rev-4
  contracts. A ranked inventory would land ahead of sequenced work.

**Proposed shape, which respects all of the above:**

- **Phase A — outside the lane, this week.** The pure-static pass (§0 finding 4). 43 seconds, no CI change,
  no governance event, and it has already produced 478 actionable rows. Ship it as a report, not a verdict.
- **Phase B — one flag on an existing job.** Add `--cov-context=test` to the CI coverage job and start
  writing the per-test line-set database. Note: that job currently uses `coverage run -m pytest`
  (`ci.yml:105`), which must become `pytest --cov=... --cov-context=test` or **parametrized cases collapse**
  — pytest-cov keys contexts on the full nodeid including `[param]`, coverage.py's own `dynamic_context =
  test_function` does not.
- **Phase C — two hooks in the lane's payload.** `pytest_runtest_logreport` for outcome, duration and
  `excinfo.typename`. Emit a row for **every** test, not only nominations.
- **Phase D — the governance step.** Take the S7a/S8 ruling deliberately, with the fleet-wide distribution
  in hand, and publish the score as a **rank with declared blind spots** — never a delete verdict. The
  closed `ALLOWED_VERDICTS` set should stay closed.

---

## 2. Q2 — Culling precedent and the safe-deletion ladder

### 2.1 What the big shops actually do

| Org | Mechanism | Retirement rule |
|---|---|---|
| **Google TAP** | MinDist run-less-often; auto-quarantine on flakiness | **None published.** No threshold, no timeout, no deletion rule |
| **Meta** | 4-stage: pre-submit → diff-time ML → land-time ML → **stabilization runs everything** | **N/A — no test ever leaves** |
| **GitLab** | fast quarantine 3d → long-term 3mo → 1wk warning → removed | **The only published numeric rule. Human-merged.** |
| **Mozilla** | Stockwell: 150 failures/21d → disable-recommended; 75/wk → 1 week; 30/wk → 2 weeks. Tier 1/2/3 visibility. ML scheduler −70% tasks, backstop every 20 pushes / 4 hours | Disable, never delete. `StaleTestExpectations` is a manual graveyard, quantifier *"many months"* |
| **Chromium** | `DISABLED_`, expectations files | **Mechanism documented, no policy.** No deadline, no threshold, no re-enable procedure |
| **LinkedIn** | *"if a test passed before but failed later… should be disabled"* — auto-disable on a single flake | **No restoration rule, no deletion rule** |
| **Slack** | Auto-disable by renaming, auto-opened auto-approved PR into merge queue | Restoration was explicitly future work |
| **Uber** | Has a `deleted` state | **Administrative only — no timer or threshold drives it** |
| **Microsoft** | Quarantine suppresses the failure, test still runs | *"will continue to treat it as such until it is manually unmarked"* |
| **Vendors** (Buildkite, Trunk, Datadog, Develocity, CircleCI) | Automated entry *and* automated exit | **No vendor product can delete a test** |

**The design principle worth stealing:** every automatic *release* rule in the survey is keyed on
**continued observation**, not elapsed time — Buildkite's *"seven days or 100 executions"*, Uber's
*"100 consecutive successful runs"*, GitLab's *">100 local runs"* dequarantine bar. **A test that stops
running cannot earn its way back.** Any "delete after N quiet cycles" rule inherits this directly: if
quarantine means *skip*, quiet cycles measure nothing and the rule degenerates into "delete after N days."
GitLab is the one org that took that trade explicitly — and paired it with a human gate and a warning week.

### 2.2 Selection beats deletion on the published evidence

This is worth stating plainly because it reframes the whole request. Shi et al. (ESEC/FSE 2015) put the two
head to head: **regression test selection ran on average 40.15pp FEWER tests than suite reduction, while
safe selection cannot miss any change-related fault the full suite would find.** Reduction missed up to
5.93% of change-related mutants. The authors' phrase is *"the peril of using test-suite reduction."*

And the theory says this will not improve: Yoo & Harman's survey concludes that minimisation *"would not be
safe unless the surrogate metric perfectly captures the fault detection capability… the empirical studies
so far have shown that there is no such single metric."* **Selection has a formal safety definition.
Minimisation does not and cannot.** That is why Google and Meta both built selection systems and neither
built a minimisation system.

**The one hopeful number, and it is a taunt:** Shi et al.'s oracular reduction — knowing every future
failure in advance — needed only **~20% of the suite and missed nothing**. So ~80% of a real suite genuinely
is dead weight, and **no published method can identify which 80% in advance.** That is exactly the gap this
fleet sits in.

### 2.3 The ladder

Steps 0–4 are copied from documented industrial practice. Steps 5–6 go beyond published precedent and are
marked as such.

**Step 0 — Stop the inflow. This is the only step with unambiguous support and it is already ruled.**
Patrick's rule — never add a test without a defect it pins — is the highest-leverage action available,
because everything downstream of it is statistically unreliable. Enforce at review: every new test names
the defect it pins. Free, zero false-negative risk.

**Step 1 — Instrument before touching anything.** Per test per run: pass/fail/flake/skip, commit, duration,
exception type. Two mandatory refinements: **separate flakes from failures by retry** (Meta reruns up to
10× — without it, "has ever failed" is contaminated; at Google **40.5%** of ever-both-passed-and-failed
targets were flakes), and **record per-test coverage attribution** via contexts. Budget 60–90 days before
the signal is usable; Meta trains on 3 months.

**Step 2 — Rank. Delete nothing.** Publish the ranking. Expect the Google/Shi shape: ~90% never caught
anything, ~20% would have sufficed in hindsight.

**Step 3 — Shadow-run the proposed cut against history.** This is the step that catches the mistake, and it
is the only metric with meaningful predictive power (historical FBDL, R² = 0.57 — still weak, and still the
best there is). Replay the reduced suite against every recorded failed build; compute our own FBDL. Run
Microsoft's two-task pattern continuously: T1 = reduced, T2 = full, alert on divergence. **Do not proceed
past this step on any candidate whose historical FBDL is non-zero.**

**Step 4 — Demote to a reduced-frequency lane. Still not deletion.** This captures essentially all of the
cost saving — Google got **42–55% resource savings** this way while missing *zero* breakages, because the
tests still ran, just later. Keep an unconditional full run on a fixed cadence. **For a 20,320-test suite
this is where the ladder should stop for the foreseeable future.**

**Step 5 — Quarantine, with a human exit and a bug.** Reserve it for *flaky*, not merely low-value — they
are different diseases. The governing number: **1 in 6 newly-flaky tests is a real production bug**
(Google, 2017, over 4.2M tests). A quarantine chute with nobody reading the bugs converts a sixth of its
contents into silent production defects.

**Step 6 — Delete only on a *reason*, never on a *statistic*. [NO INDUSTRY PRECEDENT — ours to invent]**
- Code under test is gone → delete. Safe and uncontroversial.
- Provable duplicate: same call path, same assertions, no exclusive coverage, zero mutation delta → delete
  in a **separate revertible commit, one cluster at a time**.
- Asserts something no longer required → delete, and say so in the message.
- **"It has never failed" is grounds for demotion, never deletion.** At Google that describes 91.3% of all
  tests, including the ones that later caught things.

If a time-based rule is adopted, adopt it as an **audit trigger** — "after 2 quiet quarters a human must
justify keeping it" — not an auto-delete. **Asymmetry to keep in view: demotion is cheap to reverse;
deletion destroys the knowledge of why the test existed, and in an AI-written suite that knowledge may
never have been written down anywhere.**

---

## 3. Q3 — The AI angle: yes, it is named, as of five months ago

**The institutional naming.** Thoughtworks Technology Radar Vol. 34 (April 2026), *Mutation testing* blip,
ring **Trial**:

> *"With AI-generated test cases now commonplace, mutation testing acts as a reinforcement layer for
> catching **'perpetually green' tests** — those that pass regardless of logic changes due to missing
> assertions or decoupled mocks."*

That is our exact problem, named by a citable institution, with the remedy prescribed. Note the Radar names
Stryker, Pitest and cargo-mutants — **no Python tool**, which is itself a finding.

**The academic naming**, mid-2026, and the numbers are unflattering:

- **"All Smoke, No Alarm: Oracle Signals in Agent-Authored Test Code"** (arXiv:2606.18168) —
  **86,156 test patches from 33,596 agent-authored PRs** across five agents including Claude Code.
  **80.2% contain weak or no explicit oracle signals.** Strong-oracle rate ranges 18% (Codex) to 67%
  (Claude Code). Their taxonomy W1–W5 includes **W4: mock/call-verification only** — the "test defends the
  test" species — and is directly implementable as a static check.
- **"Beyond Test Presence"** (arXiv:2607.12068) — 204,673 artifacts, **Python is the largest agent slice at
  35.7%**. Agent "unrecognized assertion patterns" **10.93% vs human 1.46% — roughly 8×**. Coins
  **"stealth technical debt."** Honest counterpoint: agents *beat* humans on edge-case variety (0.62 vs
  0.32).
- **"Do LLMs generate test oracles that capture the actual or the expected program behaviour?"**
  (arXiv:2410.21136) — assertion classification accuracy 40.8–46.3%, **dropping a further 8.4–9.5% exactly
  when the code is buggy**. The model follows the implementation rather than the intent. Mutation score of
  LLM oracles: **19.10%**.
- **"Rethinking the Value of Agent-Generated Tests"** (arXiv:2602.07900) — resolved and unresolved SWE-bench
  tasks showed *similar* test-writing frequencies; *"value-revealing print statements appear much more often
  than assertion-based checks"*; prompting for more or fewer tests *"does not significantly change final
  outcomes."* Conclusion: *"current agent-written testing practices reshape process and cost more than final
  task outcomes."* **This is the strongest published support for the hypothesis that an AI campaign's test
  output is process exhaust.**
- **Coverage is the wrong metric for AI suites specifically** (arXiv:2607.22880, ISSTA 2026, 101,123 test
  cases): coverage↔mutation r ≤ 0.443, and coverage *"loses predictive power for bug detection"* precisely
  on buggy code.

**The gap we could fill:** **no study measures redundancy *between* LLM-generated tests**, and nobody has
measured the specific species suspected here — tests asserting on other tests, fixtures, or the harness
rather than production code. The nearest operationalisation is TestPilot's *"non-trivial assertion"*
(does the assertion depend on a function from the package under test?) — under which **a median 38.6% of
its generated tests assert nothing touching the code under test; 91% in the worst package.** Implementing
that check against this fleet would be measuring something the literature has not.

**A cautionary case study, because it is the exact mistake available to us.** The one published AI-test-
sprawl case study with numbers (Oliphant, 2026-03-24) reports *"287 of those 489 tests (78%) covered zero
unique lines"* and *"ForkHub went from 489 tests to 119. A 76% reduction with zero coverage loss."*
**Two problems: the arithmetic is wrong** (287/489 = 58.7%), **and they measured coverage only and never ran
mutation testing.** "Zero coverage loss" does not establish zero fault-detection loss — and per §2.2 and
finding 1, unique-line coverage is the *worst* available deletion criterion. **Do not replicate this
method.**

---

## 4. What nobody has solved

1. **No published method predicts which tests can safely be deleted.** Every predictor tested — size
   reduction, coverage loss, mutant-detection loss — was weak (R² ≤ 0.26). The best, historical FBDL,
   reaches 0.57 and its own authors call it *"not strong in most cases."*
2. **The 80/20 gap is provable in hindsight and unreachable in advance.**
3. **No organisation has published a data-backed numeric retirement policy** — GitLab's is published but
   human-gated and unaccompanied by outcome data. Whether such rules work is genuinely unknown.
4. **No published unsafety rate for any test-selection system in production.** Meta publishes a calibrated
   design target, not an observed escape rate. Microsoft publishes a validation procedure and no results.
5. **Flakiness contaminates every history-based signal** and no retry scheme fully removes it; Meta calls
   its own retry-based estimate *"a lower-bound."*
6. **`pytest-testmon` — the most relevant Python TIA tool — has no published miss rate or benchmark at
   all.** Its safety rests on four self-declared assumptions plus coverage.py's own documented blind spots.
7. **Every TIA system shares one blind spot: non-source files.** testmon says so about itself; RTSCheck's
   bug `All-1` says so about all three Java tools it checked. Fixtures, golden files, JSON/YAML config and
   test data are invisible to all of them.
8. **Nothing is published about culling AI-generated suites specifically.** The LLM test-smell literature
   measures *quality*; nobody has studied whether AI-written tests are *more* safely deletable than human
   ones — even though the "why did this exist" knowledge that makes deletion risky may never have existed
   for them. **Our situation is not covered by the literature.**

---

## Sources

Papers read as full text: Memon et al. [*Taming Google-Scale Continuous Testing*](https://dl.acm.org/doi/10.1109/ICSE-SEIP.2017.16) (ICSE-SEIP 2017) ·
Machalica et al. [*Predictive Test Selection*](https://arxiv.org/abs/1810.05286) (ICSE-SEIP 2019) ·
Shi et al. [*Evaluating Test-Suite Reduction in Real Software Evolution*](https://mir.cs.illinois.edu/marinov/publications/ShiETAL18TSRinReal.pdf) (ISSTA 2018) ·
Shi et al. [*Balancing Trade-offs in Test-Suite Reduction*](https://mir.cs.illinois.edu/awshi2/publications/FSE2014.pdf) (FSE 2014) ·
Shi et al. [*Comparing and Combining Test-Suite Reduction and RTS*](https://mir.cs.illinois.edu/marinov/publications/ShiETAL15ReductionSelection.pdf) (ESEC/FSE 2015) ·
Yoo & Harman [*Regression testing minimisation, selection and prioritisation*](https://onlinelibrary.wiley.com/doi/abs/10.1002/stvr.430) (STVR 2012) ·
Inozemtseva & Holmes [*Coverage Is Not Strongly Correlated…*](https://www.cs.ubc.ca/~rtholmes/papers/icse_2014_inozemtseva.pdf) (ICSE 2014) ·
Zhang & Mesbah [*Assertions Are Strongly Correlated…*](https://people.ece.ubc.ca/~amesbah/resources/papers/fse15.pdf) (ESEC/FSE 2015) ·
Gligoric et al. [*Ekstazi*](https://mir.cs.illinois.edu/marinov/publications/GligoricETAL15PracticalRTS.pdf) (ISSTA 2015) ·
Zhu et al. [*RTSCheck*](https://users.ece.utexas.edu/~gligoric/papers/ZhuETAL19RTSCheck.pdf) (ICSE 2019) ·
Petrović et al. [*Practical Mutation Testing at Scale*](https://arxiv.org/pdf/2102.11378) (IEEE TSE 2021).

AI-angle: [arXiv:2606.18168](https://arxiv.org/abs/2606.18168) · [arXiv:2607.12068](https://arxiv.org/html/2607.12068v1) ·
[arXiv:2607.22880](https://arxiv.org/abs/2607.22880) · [arXiv:2602.07900](https://arxiv.org/abs/2602.07900) ·
[arXiv:2410.21136](https://arxiv.org/abs/2410.21136) · [arXiv:2410.10628](https://arxiv.org/abs/2410.10628) (TOSEM) ·
[Thoughtworks Radar Vol 34 — Mutation testing](https://www.thoughtworks.com/radar/techniques/mutation-testing).

Policy: [GitLab quarantine process](https://handbook.gitlab.com/handbook/engineering/testing/quarantine-process/) ·
[Mozilla Stockwell](https://wiki.mozilla.org/Auto-tools/Projects/Stockwell/Robot) ·
[Chromium on_disabling_tests](https://chromium.googlesource.com/chromium/src/+/main/docs/testing/on_disabling_tests.md) ·
[Google flaky tests](https://testing.googleblog.com/2016/05/flaky-tests-at-google-and-how-we.html) ·
[Dropbox Athena](https://dropbox.tech/infrastructure/athena-our-automated-build-health-management-system) ·
[Slack auto-suppression](https://slack.engineering/handling-flaky-tests-at-scale-auto-detection-suppression/).

Tools verified this round: [falsegreen](https://github.com/vinicq/falsegreen) (MIT) ·
[TestIQ](https://github.com/pydevtools/TestIQ) (MIT) · [coverage.py contexts](https://coverage.readthedocs.io/en/latest/contexts.html) ·
[pytest-testmon](https://testmon.org/blog/determining-affected-tests/) (MIT).

**Claims explicitly NOT verified and recommended against publishing:** Chromium "delete after 10K/20K
revisions"; Microsoft's ~49,000 flaky tests (the cited devblogs post 404s); Elastic's muted-then-removed
policy; Spotify Master Guardian "skips" pre-merge (its own deck says *retries*); Kafka's 10% threshold; all
vendor-blog quarantine SLA numbers (2% flake threshold, "max stay two to four weeks", "escalate after 30
days") — these appear only on commercial marketing pages with no organisation named. The widely-repeated
*"flaky tests cost Google 16% of developer time"* is a **distortion**: the primary source says 16% of
*tests* have some flakiness. There is no primary source for a 16%-of-developer-time claim.
