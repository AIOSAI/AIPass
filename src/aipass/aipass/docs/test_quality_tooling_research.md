# Open-source test-quality tooling — external research for the `audit-tests` lane

**Author:** @aipass · **Date:** 2026-08-29 · **Assigned by:** Patrick, dispatched via @devpulse
**Campaign:** DPLAN-0320 (methodology) / FPLAN-0457 (stage 1) — this doc is external input, not a taxonomy edit.
**Reads:** `devpulse/docs.local/test_quality/TAXONOMY.md` (rev 2) and `PITFALLS.md`, read-only.

**Constraint honoured throughout:** OPEN-SOURCE / FREE only. Every tool named carries its license.
Anything paid, freemium, source-available-but-not-OSI, license-absent, or paper-only is flagged 🔴 or ⚠️
and excluded from every recommendation.

**Method:** five research sub-agents (mutation · static smells · isolation/flakiness · oracles/coverage ·
AI+misc), each verifying licenses by reading `LICENSE` files or PyPI `license_expression`, maintenance dates
from the GitHub API on 2026-08-29, and — in many cases — **running the tools on this machine and against this
fleet**. Measured figures are marked *(measured)*. Unverified claims are marked **unconfirmed** rather than
smoothed over.

---

## 0. The five findings that should drive the design session

**1. The category is empty. `audit-tests` is not reinventing anything.**
There is no maintained, library-grade tool in any language that grades *oracle quality* in Python. The research
tools (PyNose, TEMPY, Pytest-Smell) detect *maintainability* smells and are dead. The living linters (Ruff,
pylint, Sonar) cover ~3.5 of 14 target species, and cover them as side effects of unrelated rules. Everything
that measures what this campaign measures — pseudo-tested methods, checked coverage, extreme mutation,
covered-oracle-gap — **exists only for Java**.

**2. 🔴 Mutation score alone will bless assertion-free tests. This qualifies law L0.**
Two independent studies measured it. Schuler & Zeller (ICST 2011, Table III): *"A test suite with no assertions
still detects over 50% of the mutations detected by the original test suite"* — 45% of all kills come from
*implicit* oracles (the runtime raising), not assertions. Zhang & Mesbah (FSE 2015) reproduced it: "killed by
assertions" was 66%, 73%, **28%**, **35%**, 65% across five subjects. **This will be worse in Python**, where
duck typing and `None`-propagation make a mutant raise `TypeError`/`AttributeError` far more readily than in
Java. Consequence for the lane: **split every kill by exception type — `AssertionError` vs everything else** —
and report the split. pytest gives it to you for free. Nobody has published this split for Python. This is the
cheapest high-value idea in the whole report, and it is a direct correction to reading "mutation is the only
ground truth" as "mutation score is the score."

**3. NULL-ORACLE and MIRROR-EXPECT appear to be unnamed in the literature. The campaign would be naming them.**
Checked against three independent catalogs: tsDetect's 19 smells, PyNose's 15 shipped inspections, and PyNose's
33-smell superset drawn from a systematic mapping of the whole literature to 2020. **No absence-only-assertion
smell in any of them.** *Redundant Assertion* catches tautologies (`assert 1 == 1`); NULL-ORACLE is not a
tautology — `assert result is None` is a real falsifiable predicate that a do-nothing satisfies. *Unknown Test*
catches tests with **no** assertion; these have one, which is precisely why they survived eyes-on review.
The nearest named neighbour is **pseudo-tested method** (§1.4), which names the production method rather than
the test-side pattern.

**4. The gutting probe already has a published name, a 10× cost advantage, and no Python implementation.**
"Extreme mutation" / "pseudo-tested methods" (Niedermayr et al. ICSE-CSED 2016; Vera-Pérez et al. EMSE 2018):
*"covered by the test suite, yet no test case fails when the method body is removed."* Descartes (the Java
implementation) measures **~10× cheaper and ~10× fewer mutants** than operator mutation, with published
side-by-side numbers. `gut.py` is already this — **at module granularity where the literature uses function
granularity**. Refactoring `gut.py` to per-function is likely a higher-value week than adopting any tool.

**5. `sys.addaudithook` is the fs-write gate, it costs nothing, and nobody in the pytest ecosystem uses it this way.**
*(measured)* ~40 lines of stdlib in a root `conftest.py`: caught the exact AUDIT-FORGERY case (a test appending
to an existing live log), attributed to the precise node id, **0 CPU overhead on a 1,000-test suite**. The one
off-the-shelf plugin with the same shape, `pytest-litter`, **passed that same case** — its snapshot is a
`frozenset` of path strings, so it sees creation and deletion but is structurally blind to modification.

---

## 1. Mutation testing for Python, and mutation at scale

### 1.1 The Python tool landscape

| Tool | License (SPDX) | Latest release | Last commit | ★ | Incremental | Sampling | Cov-guided | Parallel | Execution model |
|---|---|---|---|---|---|---|---|---|---|
| **mutmut 3** | **BSD-3-Clause** | 3.7.0 (2026-07-31) | 2026-08-17 | 1,409 | **Yes** — per-function source hash + caller invalidation | No ([FR #278](https://github.com/boxed/mutmut/issues/278)) | Yes (`mutate_only_covered_lines`, plus a dynamic test→function map by default) | `fork()` per mutant, `--max-children` | **Mutant schemata**: copies source to `mutants/`, emits every mutant as its own `def`, dispatches at call time via a **trampoline** |
| **cosmic-ray** | **MIT** | 8.7.0 (2026-08-09) | 2026-08-09 | 654 | Session resume only | No | No | 🔴 **local distributor is strictly serial** | **In-place** source mutation + full test command as a subprocess per mutant |
| **Poodle** | **MIT** | 1.3.4 (2026-04-05) | 2026-04-05 | 5 | No | No | No | Yes (`cpu_count − 1`) | Copy to `.poodle-temp` per worker + full subprocess |
| **mutatest** | **MIT** | 3.1.0 (**2022-02-20**) | **2023-02-17** | 101 | No | **Yes** — `-n`/`-r`, the only reproducible sampling | Yes, by default | `multiprocessing` + `PYTHONPYCACHEPREFIX` | Mutates `__pycache__` **bytecode** |
| **MutPy** | **Apache-2.0** (GitHub's `NOASSERTION` is a metadata artifact) | 0.6.1 (**2019-11-17**) | 2019-11-17 | 367 | No | No | Yes | No | AST + import hooks, unittest-oriented |
| **pytest-mutagen** | MIT | 1.3 (2020) | 2020 | 5 | — | — | — | — | Hand-written mutants via a decorator DSL |
| **PyTation** | MIT | not on PyPI | 2026-01-16 | 2 | No | No | Yes | via cosmic-ray | ICSE 2026 artifact, 7 Python-specific deletion operators |
| **Mutahunter** | 🔴 **AGPL-3.0** + requires a paid LLM API | 1.3.2 (2025-04-17) | 2025-04-17 | 299 | — | — | — | — | LLM-generated mutants. **Double-flagged, excluded** |

Everything in the adopt zone is license-clean: mutmut BSD-3-Clause, cosmic-ray and Poodle MIT, PIT Apache-2.0.
🔴 Excluded: **Mutahunter** (AGPL-3.0, network copyleft, and dormant 16 months), **arcmutate** (proprietary),
**Cornelius** (the e-graph equivalence detector — **no LICENSE file at all**, so all rights reserved).
⚠️ `pitest-descartes` is LGPL-3.0 — fine to run, care if vendoring.

### 1.2 mutmut 3's trampoline structurally solves two instrument species

This is the finding that matters most for the campaign's own harness. mutmut 3 copies the source into
`mutants/`, emits every mutant of a function as its own `def`, and binds the original name to a **trampoline**
that dispatches at *call time*.

- **FALSE-LANDING (aliases):** because the mutation lives inside the callable every alias already points at,
  `from x import fn` in a test module, a decorator that captured the function, or a reference stashed in a
  registry all still route through the same trampoline. **There is no `sys.modules` alias set to rebind.**
- **`fn.__defaults__`:** sidestepped by construction — each mutant is a separate `def` with its own defaults.
- **RELOAD-RESURRECTION:** `importlib.reload()` re-reads `mutants/<file>.py`, which *contains* the mutants.
  The mutation survives the reload. **AIPass has 113 uses of `importlib.reload` across the tree, including
  inside `conftest.py` in `backup` and `skills`** — a large surface for a `sys.modules`-stubbing harness and a
  non-issue for mutmut 3. This is the single strongest argument for moving `gut.py` off module stubs.
- **CONCURRENT-HARNESS:** the real tree is never touched. 🔴 By contrast **cosmic-ray's local distributor mutates
  your real source in place** and restores in a `finally` — a hard kill leaves the tree mutated.

**Where mutmut 3 is blind** (verified in `file_mutation.py::_skip_node_and_children`): decorated functions are
skipped entirely except a sole `@staticmethod`/`@classmethod`; module-level code is never mutated; annotations,
non-simple defaults, `len()`/`isinstance()` calls and triple-quoted strings are excluded.
🔴 **Released 3.7.0 additionally skips every decorated class, including every `@dataclass`** — [issue #558](https://github.com/boxed/mutmut/issues/558)
measures a real project at 59% of statements unreachable. **Fixed on `main`, not in any release.** Pin `main`.

*(measured, this tree)* AIPass's exposure to those skip rules is **13.4% of statements blind / 86.6% mutable**
(module-level 12.9%, decorated function 0.4%, decorated class 0.2%) — far better than #558's 59%, because the
fleet does not lean on `@dataclass` domain types. 154 of 1,333 files yield zero mutants (almost certainly
`__init__.py` and config modules — verify a sample rather than assuming).

### 1.3 🔴 mutmut's scoring has three honesty defects the lane must not inherit

Verified in source:

1. **Timeouts are counted as kills** — `score = (killed + timeout) / tested`. A mutant that *hung* scores as caught.
2. **This is dangerous on exactly this hardware.** [Issue #545](https://github.com/boxed/mutmut/issues/545): the
   per-mutant budget is computed from a *solo-run* estimate while `mutmut run` defaults to one child per core.
   A 6-core reporter measured *"616 ⏰ at ~1 s per 'timeout' — contention artifacts, not scores"* at default
   parallelism, versus 708 killed / 24 survived / 366 timeout at `--max-children 2`. **Worse: cached ⏰ verdicts
   replay across runs.** On a 4-thread 15W i5 this is not hypothetical. **Run `--max-children 2` and treat every
   ⏰ as *unscored*, never as killed.**
3. **pytest exit code 3 (INTERNALERROR) is scored as "killed"** — a mutant that breaks a conftest at collection
   time counts as caught though nothing asserted anything.

Also: [#555](https://github.com/boxed/mutmut/issues/555) and [#528](https://github.com/boxed/mutmut/issues/528)
make `mutate_only_covered_lines` silently produce zero mutants after regeneration and crash on C-extension deps.
**Leave it off.**

⚠️ **A silent-failure mode AIPass is specifically exposed to.** [Issue #515](https://github.com/boxed/mutmut/issues/515)
and siblings #341/#351/#416/#419: the trampoline records hits under `module.__name__` but looks mutants up by
*file path*. When a test does `import foo` rather than `from pkg.foo import ...` — enabled by a conftest
`sys.path.insert` — the keys never match, **every mutant reports "No Tests" at 0.00 mutations/second, and the
forced-fail control still passes.** Three `conftest.py` files under `src/aipass/skills/` do `sys.path.insert`
or `append`. **Do not report a skills mutation number without checking the association diagnostic first.**

### 1.4 Extreme mutation / pseudo-tested methods — the highest-leverage idea in this section

Descartes ([STAMP-project/pitest-descartes](https://github.com/STAMP-project/pitest-descartes), ⚠️ LGPL-3.0,
Java-only) implements Niedermayr, Juergens & Wagner: don't perturb an operator, **delete the whole method body**
(`void` → empty; otherwise → a single constant return).

Published side-by-side against PIT's standard engine:

| Project | Descartes | Gregor (operator mutation) | Speedup | Fewer mutants |
|---|---|---|---|---|
| spoon | 2 h 25 m / 4,713 | **56 h 48 m** / 43,916 | **23.5×** | 9.3× |
| jgit | 1 h 30 m / 7,152 | 16 h 02 m / 78,316 | 10.7× | 11.0× |
| commons-lang | 2 m 07 s / 3,872 | 21 m 02 s / 30,361 | 9.9× | 7.8× |

**~10× cheaper, ~10× fewer mutants — and the output taxonomy is the real product:**
**pseudo-tested / partially-tested / tested**, reported **per function name**, not per line diff. Vera-Pérez et
al. (EMSE 2018) found pseudo-tested methods in **all** studied subjects across 28,000+ methods.

This maps onto Python trivially (`pass` / `return None` / `return []` / `return ""` / `return 0`) and it covers
the **statement-deletion gap that both mutmut and cosmic-ray leave open** — SBR is **68% of Google's mutant
volume and their most productive operator at 84.1%**, and neither Python tool has it
([mutmut FR #241](https://github.com/boxed/mutmut/issues/241), open since 2022).

🔴 **No Python extreme-mutation tool exists.** But a starting point does: **Pynguin** (`se2p/pynguin`, **MIT**,
1,384★, pushed 2026-08-27) ships a working Python-native mutation engine wired to assertion evaluation
(`assertion/mutation_analysis/` with `controller.py`, `mutators.py`, `operators/`, and `_MutantInfo` carrying
`get_survived()`/`get_killed()`). Better than greenfield.

**One free corroboration from Pynguin's source, worth putting in the taxonomy:**
```python
allow_stale_assertions: bool = False
    """Allow assertion on things that did not change between statement executions."""
```
A production Python tool independently concluded that an assertion about an unchanged value is worthless and
**declines to write one**. That is MIRROR-EXPECT, confirmed by running code rather than by a paper.

⚠️ **Do not use Pynguin to *generate* tests.** Its own README calls it *"only a research prototype… not tailored
towards production use whatsoever"*, and it emits **regression assertions**, not oracles — it would freeze
current behaviour, including current bugs, into thousands of new tests.

### 1.5 Google's cost model — the numbers, and what is OSS

Papers: [State of Mutation Testing at Google](https://static.googleusercontent.com/media/research.google.com/en//pubs/archive/46584.pdf)
(ICSE-SEIP 2018) · [Practical Mutation Testing at Scale](https://arxiv.org/abs/2102.11378) (TSE 2021) ·
[Does mutation testing improve testing practices?](https://arxiv.org/abs/2103.07189) (ICSE 2021) ·
[MuRS](https://arxiv.org/pdf/2306.09130) (FSE 2023).

**Arid nodes, precisely.** `arid(N) = expert(N)` if `simple(N)`, else `1 iff ⋀ arid(b) = 1 ∀b ∈ N`.
`expert()` is *"a boolean function encoding manually curated knowledge"* — **rule-based and hand-written, not
learned**, over *"more than a hundred rules"* plus fuzzy name suppression for 200+ function families. The second
clause is the transitive rule: **a compound node is arid iff all its parts are arid**, which is what lets you
kill an entire `if DEBUG: log(...)` block *including its condition*.

**Their three highest-yield categories, in their words:** *"suppression of mutations in **logging statements**,
**time-related operations** (deadlines, timeouts, exponential backoff), and finally **configuration flags**."*
For Python specifically they suppress `if __name__ == "__main__"`, `print`, `assert`, and **default argument
values**. They validated the fuzzy log rule by sampling 100 arid-marked nodes and finding **99 correct**, and
state a preference worth adopting: *"we have had much more important improvements of perceived mutant usefulness
from unsound heuristics"* than from provably-sound ones.

**The sampling rule, exactly:** shuffle `{UOI, ROR, SBR, LCR, AOR}`, walk the covered lines of the diff, take the
**first operator that can produce a mutant, then break**. One mutant per covered changed line, **no retry**.
Justified empirically: *"if a surfaced mutant in a given line survives, then most mutants that could be generated
for that line will survive."*

**The cost reduction, quantified** (TSE RQ1, 5,000 changelists, median mutants per changelist):

| Strategy | Median | p25 | p75 |
|---|---|---|---|
| No suppression | **820** | 460 | 1,734 |
| 1-per-line only | **77** | 31 | 138 |
| **Arid + 1-per-line (production)** | **7** | 3 | 19 |

**≈99.15% reduction**, and note the ordering: two orders of magnitude *before* any execution optimisation.
Mutants are suppressed at **generation** time — *"they are never created in the first place."*

**The feedback loop is the engine, not a nicety.** Mutants surface only as code-review findings on changed lines
with "Please Fix" / "Not useful" buttons; a "Not useful" click gets generalized into an `expert()` rule so that
class never regenerates. That drove productive-mutant rate **15% → 89%**. Their warning:
*"without it, users would become frustrated with non-actionable feedback and opt out of the system altogether."*
Caps: **≤3 mutants per file, ≤10 per changelist**.

**Evidence that mutation beats coverage as a behaviour-changer** (ICSE 2021): as mutant exposure rises developers
write more tests, while the coverage-only control group shows a **negative** correlation (r_s = −0.24). Coverage
delta in the mutant group was also negative (−0.17) — *"they wrote tests to kill the reported mutants."*
Mutants were coupled with **70% of high-priority bugs**, on changes where *"code coverage had exhausted its usefulness."*

🔴 **Open source: none.** No artifact statement in any paper, no `google/*` mutation repo; the system is bound to
Bazel/Piper/Critique/Tricorder and is structurally unreleasable. The 17M-mutant dataset was not published.
**Reusable assets: the arid-rule catalogue (SEIP 2018 Appendix A), Equation 1, and MuRS's identifier-template
algorithm — all prose.**

### 1.6 Meta

- **Mutation Monkey** (ICSE-SEIP 2021): inverted Getafix's learned bug-fix patterns to *inject* realistic bugs —
  16 learned operators with **~60–70% survival rates vs "15% at Google."** Higher survival = far less compute
  burned on mutants that die instantly. 🔴 Not released.
- **ACH** ([FSE 2025, arXiv 2501.12862](https://arxiv.org/abs/2501.12862), prompts under CC BY 4.0): three LLM
  agents — generate a mutant *targeted at a stated concern*, judge equivalence, write a killing test. The
  head-to-head that matters: versus coverage-guided TestGen-LLM it generated tests for a *smaller* fraction of
  classes (5.3% vs 32%) but killed **15% of mutants vs 2.4%**. Their conclusion:
  ***"Targeting mutants can also elevate coverage, but targeting coverage will be inadequate to kill mutants."***
  And **49% of accepted hardening tests added zero line coverage.** 🔴 Not released; both third-party
  reimplementations (qodo-cover, mutahunter) are **AGPL-3.0**.

### 1.7 PIT/pitest — Apache-2.0 ideas worth stealing

[hcoles/pitest](https://github.com/hcoles/pitest), **Apache-2.0**, 1,856★, release 1.30.0 (2026-08-27) — the
healthiest mutation codebase in any language, Java-only but full of transferable design.

- 🟢 **`EquivalentReturnMutationFilter`** *is literally the NO-OP-MUTANT species, solved*: before generating a
  "replace the return with empty" mutant, pattern-match whether the method **already** returns that empty value
  and never generate it. The transferable rule is one line: **before emitting "replace X with Y", check whether
  X already *is* Y.** In Python: `return []`, `return None`, `return 0`, `return False`. Sound, static, free, and
  it prevents the execution rather than explaining the survivor afterwards — for this narrow shape, static
  analysis **convicts the mutant as a non-experiment** without running it.
- **`LoggingCallsFilter`** — Google's #1 arid rule, shipping in OSS.
- **Infinite-loop filters** (`AvoidForLoopCounterFilter`, `InfiniteForLoopFilter`) — *statically prove* a mutant
  would hang and drop it, instead of burning the full timeout to learn nothing. Directly relevant to SELF-CAP,
  where a cap raised the wrong way makes a test **hang rather than fail**.
- **Gating knobs better than mutation score:** `maxSurviving` (an **absolute** survivor budget that doesn't drift
  as the codebase grows) and **`testStrengthThreshold` = killed / *covered* mutants** (ignores no-coverage
  mutants). Both beat a percentage of a population you can change by editing one regex.
- **Incremental decision table** — the clever bit: when a class hash *changes*, don't merely invalidate,
  **re-run with the previously-recorded killing test hoisted to the front of the queue**. Staleness seeds a good
  guess. Carry their honesty forward too: the scheme rests on an assumption they call *"currently unproven."*
- 🔴 **"Mutants surviving on changed lines only" PR gating is PAID** (arcmutate, proprietary — gratis for OSS
  projects on request, which does not make it open source). The free OSS analogue is cosmic-ray's `cr-filter-git`.

### 1.8 Equivalent mutants — and TCE works in Python, measured

The problem is undecidable; every practical technique is a conservative partial detector, which makes it safe to
bolt on (false negatives cost nothing, no false positives).

**Trivial Compiler Equivalence** (Papadakis et al., ICSE 2015): *"declares equivalent any two program versions
with identical machine code."* Two outputs — **equivalent** (mutant == original) and **duplicated** (mutant ==
another mutant). C/gcc: 7.4% equivalent + **21% duplicated** = ~28% of mutants discarded. Java/javac alone:
**0/196 detected**; with SOOT `-O`: 105/196 (54%). *"In Java almost all, **99 percent**, of the detected mutants
are due to failed propagation."*

🟢 *(measured, CPython 3.12.3)* **TCE is implementable in pure stdlib and the economics are far better in Python
than in C or Java.** `compile()` + `dis.get_instructions()`, discard `NOP`/`CACHE`/`RESUME`/`PRECALL`/
`EXTENDED_ARG`, hash `(opname, argval)` pairs, recurse into nested code objects. Cost: **microseconds per
mutant**, versus the hours of compilation that dominated the C study.

- Raw `co_code` already catches `2*3` vs `6`, `'x'+'y'` vs `'xy'`, `while True` vs `while 1`, implicit vs
  explicit `return None`.
- 🔴 **The ~20-line NOP-strip is mandatory** — CPython leaves a `NOP` placeholder for line-number bookkeeping, so
  raw comparison is the "javac alone / 0% detection" case. With it, `if True: return 1 / return 2` vs `return 1`
  comes out EQUIVALENT while `return a<b` vs `return a<=b` correctly stays different.
- CPython 3.12 gives you free: constant folding, dead-branch elimination, implicit-`None` normalisation,
  `True`/`1` unification. It will **not** give you `a*1 → a`, `1<2 → True`, `not not a`.
- 🟢 **Do the duplicate half first** — in C, duplicates were 3× more numerous than equivalents (21% vs 7.4%), and
  duplicate detection needs **no** compiler optimisation at all.
- ⚠️ Normalised-bytecode equivalence is a CPython-version-specific fact. Pin the interpreter; re-validate the
  skip-list on every upgrade.

🔴 **No Python mutation tool implements equivalence or duplicate detection.** No Python weak-mutation
implementation was found either — a shame, because `sys.monitoring` (PEP 669, 3.12+) makes state-snapshotting at
a line far cheaper in Python than JVM instrumentation ever was.

**Minimal mutant sets** (Ammann, Delamaro & Offutt, ICST 2014): *"on average, only **1.2%** of mutants are in a
minimal set"*; even after removing indistinguishable duplicates, only **6.6%**. Tooling: none usable. **But the
reporting form is free:** after a run you already hold the kill matrix, so **collapse mutants by kill-vector and
report one representative per subsumption class**. 200 survivors on one function then present as 3 distinct
problems. Zero extra compute, large reduction in reviewer load — the cheapest high-value item in §1.

### 1.9 Cost arithmetic at fleet scale

**Baseline:** 18,042 tests, 514 s at `-n4` → 2,056 CPU-s → **0.114 CPU-s/test**.

*(measured, this tree — 1,333 non-test files, 117,297 statements)* **Estimated mutant population: 241,469** over
18 sub-projects, at **2.16 mutants/statement**. The distribution is the finding:

| Operator family | Mutants | Share |
|---|---|---|
| **String literal** | 106,830 | **42.8%** |
| Call arg → `None` | 65,551 | 26.3% |
| Call arg dropped | 35,864 | 14.4% |
| Number / comparison / bool / `None` / binop / boolop / break-continue / augassign | ~41,000 | **~16.6%** |

**String-literal mutants are 42.8% of the population and are exactly Google's #1 arid category** (log messages,
error text). Call-argument mutants are another 40.6%. **The classic logic mutants anyone actually cares about are
~16.6%, about 40,000.** A single `do_not_mutate_patterns` regex over `logger\.\w+` and message strings roughly
halves the bill before running anything.

Worst mutants-per-test ratios: **devpulse 38.3**, **commons 31.2** — least test-dense, where survivors will
concentrate. Largest population: seedgo 39,966.

**Two per-mutant cost models:**
- **Model A** — cosmic-ray / Poodle / mutatest (full test command as a subprocess per mutant): plan at **20 s/mutant**.
  Anchor: the ICSE 2026 PyTation paper measures **cosmic-ray at 24.8 s/mutant**.
- **Model B** — mutmut 3 (fork, covering tests only, `-x`, fastest-first): plan at **1.5 s/mutant** (conservative;
  mutmut issue #470 shows a real project at 0.024 s/mutant).

**The ratio is ~13×, entirely down to test selection. This is the biggest architectural decision in the lane.**

| Configuration (fleet, 241,469 mutants) | Wall |
|---|---|
| cosmic-ray, local distributor (serial) | 🔴 **56 days** |
| cosmic-ray HTTP distributor, 4 workers | 🔴 14 days |
| mutmut, `--max-children 4` | 25.2 h |
| **mutmut, `--max-children 2`** (safe here, per #545) | 50.3 h |
| mutmut + strings suppressed, 2 children | **28.8 h** |

**The affordable lane is diff-scoped.** *(measured)* Commit sizes over the last 120 non-merge commits: median
**183 added non-test lines**, p75 337, p90 1,307.

| Commit | ≈Statements | Mutants | mutmut @ 2 children | + 1-mutant-per-line |
|---|---|---|---|---|
| p25 | 26 | 56 | 42 s | 20 s |
| **median** | **120** | **260** | **3.3 min** | **1.5 min** |
| p75 | 220 | 475 | 5.9 min | 2.8 min |
| p90 | 850 | 1,836 | 23 min | 10.6 min |

**Under 4 minutes for a median commit — that is a CI lane.** The same lane under cosmic-ray's execution model is
87 minutes at the median, which is why the diff filter alone doesn't save you: **you need the diff filter *and*
the fast engine.**

⚠️ **Assumption to replace with a measurement before budgeting:** "10 covering tests per mutant" is unmeasured.
Run mutmut's stats phase on `canary` (237 mutants, ~3 min). If covering sets are 30+, Model B's 1.5 s becomes
4 s and every figure above triples.

### 1.10 The two controls to steal today, regardless of tool

~30 lines each, and the cheapest possible defence against a lane that silently measures nothing:

- **Positive control** (mutmut's `run_forced_fail_test`): make *every* mutation point raise; **at least one test
  must fail**. Proves the plumbing can kill.
- **Negative control** (cosmic-ray's `NoOp` operator + `cosmic-ray baseline`): run the whole harness with a
  mutation that provably changes nothing; the suite must still **pass**. Proves the harness isn't killing spuriously.
- 🔴 **A third the tools lack:** assert that **at least one recorded test key matched at least one mutant key**.
  mutmut's forced-fail control passed straight through the #515 silent key-mismatch bug.

**Steal mutmut's 7-way verdict taxonomy** — killed / survived / **no-tests** / skipped / timeout / type-invalid /
segfault. "🫥 no test reaches this mutant" is precisely the *unreachable-vs-untested* distinction §3 of the
taxonomy asks for. cosmic-ray offers only killed/survived/incompetent/no-test.

---

## 2. Static test-smell detection

### 2.1 Coverage matrix — the 14 target species × what exists

**●** direct hit · **◐** partial/over-broad · **○** expressible but must be written · **—** nothing

| # | Species | Ruff (MIT) | pylint (GPL-2.0) | Sonar Python (🔴 SSALv1) | PyNose (Apache-2.0, dead) | flake8-* | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | **NO-ORACLE** | — | — | ◐ `S5899`,`S5918` | ● *Unknown Test* | — | **BUILD** |
| 2 | **TAUTOLOGY** | ● `PT015`,`B011`,`PLW0129`,`PLR0124`,`PLR0133`,`F631`,`B015` | ● `W0129`,`R0124`,`R0133`,`W0199` | ● **`S5914`** (best rule anywhere) | ● *Redundant Assertion* | — | **ADOPT + extend** |
| 3 | **TYPE-ONLY** | — | — | — | — | — | **BUILD** (nothing exists, anywhere) |
| 4 | **OR-ESCAPE** | — | — | ◐ | — | — | **BUILD** |
| 5 | **MIRROR-EXPECT** | — | — | — | — | — | **BUILD** (hardest; needs import resolution) |
| 6 | **MOCK-DRIFT** | — | — | — | — | ● **flake8-mock-spec** `TMS010–013`,`TMS020–022` | **Port the rule, not the dep** |
| 7 | **VACUOUS-GUARD / -LOOP** | — | — | ◐ `S5918` | ◐ (89.5% hit rate — useless) | — | **BUILD** |
| 8 | **SWALLOW** | ● `S110`,`S112`,`SIM105`,`PT017` | ◐ `W0702` | ○ | ◐ | — | **ADOPT** |
| 9 | **SELF-SKIP / SKIP-ON-DRIFT / PERMA-SKIP** | — | — | ◐ `S5918` | ◐ | — | **BUILD** + runtime helper |
| 10 | **RETURN-ONLY / capture-never-read** | ◐ `ARG001` | ◐ | — | — | ◐ flake8-aaa | **BUILD** |
| 11 | **DUPLICATE** | — | ◐ `R0801` (line/token, noisy) | ○ | ◐ | ◐ (fixtures only) | **BUILD** (~30 lines) |
| 12 | **COVERAGE-SLOT** | — | — | — | — | — | **BUILD** |
| 13 | **SOURCE-GREP-VACUOUS** | — | — | — | — | — | **BUILD** (or one Semgrep rule) |
| 14 | Classic literature smells | ◐ | ◐ | ◐ 8 rules | ● 18 | ◐ | **Steal definitions, not tools** |

**Species covered by an existing, maintained, OSI-licensed rule: 2, 8, and half of 6. Everything else must be written.**

### 2.2 The license verdicts that decide build-vs-adopt

- 🟢 **Ruff — MIT**, 49,384★, pushed 2026-08-29. *(measured on this fleet, 634 test files, `--no-cache --isolated`,
  16 rule families:* **0.96 s user CPU, 64 MB RSS**.*)* The only serious adopt.
  🔴 **But Ruff has no plugin API** — [meta-issue #283](https://github.com/astral-sh/ruff/issues/283) open since
  2022, described as "untouched in essence" as of Sept 2025. Custom rules mean forking Rust.
  **This single fact decides the architecture: the lane is necessarily two-tool.**
- 🔴 **SonarQube — do not adopt.** Since 2024-11-29 every bundled analyzer including `sonar-python` is under the
  **Sonar Source-Available License v1.0 (SSALv1)**, which is **not OSI-approved**. The Community Build core
  remains LGPL-3.0 — **the Python rules are precisely the part that isn't open source.** Also verified by listing
  the rules tree: **`S2699` "Tests should include assertions" has NO Python implementation** — the one rule
  everyone assumes covers NO-ORACLE does not exist for Python. Its rule *specifications* are still the best in
  the survey (see §7).
- 🔴 **CodeQL — not free for this use.** Free terms cover OSI-licensed codebases and academic research, and
  **explicitly do not authorize generating databases "for or during automated analysis, CI or CD."** A local
  `codeql` CLI in your own CI needs paid GitHub Advanced Security. It has no test-quality queries anyway.
- ⚠️ **Semgrep — engine LGPL-2.1, but the Registry rules moved (Dec 2024) to the Semgrep Rules License v1.0**
  ("internal business use" only, not OSS — do not vendor into a public repo). **And cross-file/interfile dataflow
  is Pro-only, which kills it for MIRROR-EXPECT** ("is this expected value imported from the module under test?"
  is inherently cross-file). Fine as a prototyping playground for one or two single-file rules.
- ⚠️ **pylint GPL-2.0 + astroid LGPL-2.1.** astroid's `node.infer()` can resolve `EXPECTED_TIMEOUT` back to its
  defining module — exactly what MIRROR-EXPECT needs and the one thing plain `ast` doesn't give free. But GPL on
  a public repo is a real question, it is 10–100× slower, and inference returns `Uninferable` often enough that
  you write the fallback anyway. **Keep it as an optional deep resolver in one removable file, gated behind a
  flag, run only over pre-nominated candidates.**

### 2.3 The research tools are all dead

| Tool | License | Status | Verdict |
|---|---|---|---|
| **PyNose** (JetBrains, ASE 2021) | Apache-2.0 | **Last push 2022-02-23**; a **Kotlin IntelliJ plugin**; CLI requires a headless IntelliJ per project; `build.gradle.kts` pins the sunset **JCenter** | Unusable. **Steal the paper.** |
| **TEMPY** (SBES 2022) | MIT | 1★, 2022; detectors are **line-string matching**, not AST | Steal definitions only |
| **Pytest-Smell** (ISSTA 2022) | ⚠️ PyPI says MIT, **repo has no LICENSE file** | Abandoned 2022. *(measured)* On a 2-test file it reported "1 test", **missed the assertion-free test entirely**, and counted `def test_...():` lines as asserts | 🔴 Broken |
| **PythonTestSmellDetector** | 🔴 **NO LICENSE** | 2018 | Legally unusable; *(measured)* also flags tests that **do** call `assertEqual` as assertion-free |

**PyNose's prevalence data is the reusable part** (248 mature projects): Assertion Roulette 89.9% of projects /
52.4% of suites · Conditional Test Logic 89.5/31.9 · **Unknown Test (= NO-ORACLE) 81.5/22.5** · Duplicate Assert
78.2/17.4. **98% of projects and 84% of suites had ≥1 smell.** Detection accuracy where it committed: weighted
F1 94.9% (Unknown Test F1 90.1%, precision 83.3%); tsDetect scored 96.5%. **~90% is the realistic ceiling for
pure-AST nomination — the empirical argument for law M1, "nominate, don't convict."**

🟢 **And the lesson buried in the paper:** PyNose *deliberately excluded* Eager Test and Lazy Test because they
*"rely on the production code being tested"* and reliable test-to-code traceability *"is difficult"* statically.
**MIRROR-EXPECT lives in exactly that excluded zone** — which is why nothing covers it, and why building it is
genuinely novel rather than reinvention.

### 2.4 ⚠️ Prior art that overlaps the lane

**`pytest-tidy`** ([az-pz/pytest-tidy](https://github.com/az-pz/pytest-tidy), **MIT**, pushed 2026-07-15) is
substantially the tool being designed. Its 32-rule catalog includes, by name: `PTD001 assert-on-constant`,
**`PTD003 test-without-assertion`**, `PTD005 assert-redundant-compare`, **`PTD006 assert-self-comparison`**,
`PTD101 except-pass`, `PTD403 return-in-test`, **`PTD501 mock-uncalled-assert`**, **`PTD502 mock-nonexistent-attr`**,
`PTD602 unconditional-skip`. AST-based, zero execution, pre-commit hook, autofix.
**`kriskimmerle/testsmell`** (MIT, archived, single file, zero-dep, 14 rules including `TS13 Assertion-Free`) even
emits a letter grade. Both MIT, both 0–1★ indie 2026 projects. **Read them before writing ours — but note neither
touches the oracle species that matter here (NULL-ORACLE, MIRROR-EXPECT, SELF-CAP, INSULATED).**

### 2.5 Build-vs-adopt recommendation: **stdlib `ast`**

| Criterion | stdlib `ast` | LibCST | Semgrep CE | Ruff plugin | pylint checker |
|---|---|---|---|---|---|
| Available? | ✅ | ✅ | ✅ | 🔴 **no plugin API** | ✅ |
| License | PSF-2.0 | MIT | engine LGPL-2.1; **rules not OSS** | n/a | **GPL-2.0** |
| Cross-symbol resolution | ⚠️ manual (~150 lines, fully controlled) | ⚠️ same | 🔴 **cross-file is Pro-only** | n/a | ✅ `infer()`, often `Uninferable` |
| Speed at 19k tests *(measured)* | **7.6 s** parse+walk | ~10–30× slower | OCaml startup per rule | n/a | 10–100× slower than Ruff |
| Memory | **27 MB streaming** | high | moderate | n/a | high |

**Reasoning:** Ruff can't be extended, so the two-tool split is forced. 10 of 14 species need custom logic
anyway. `ast` beats LibCST because we are *nominating*, not *fixing* — LibCST's whole advantage is lossless
rewriting, a feature we don't use (add it later if an autofix mode appears). `ast` beats Semgrep because the hard
cases are cross-file and Semgrep CE isn't. `ast` beats pylint on license and speed, with the astroid carve-out
above.

*(measured, prototype 10-species nominator over the real fleet)* **39.3 s CPU unoptimized → ~0.5 ms/test as a
single-pass visitor ≈ 10 s CPU ≈ 3 s wall on 4 workers**, plus 0.3 s for Ruff. **Total static pass: under 4
seconds on an idle 4-core.** Two traps hit so nobody repeats them: **never retain parsed trees** (streaming 27 MB
vs 462 MB retained — will OOM-adjacent this laptop), and **never `ast.unparse()` + re-`ast.parse()` to normalize**
for DUPLICATE (blew a 2-minute budget; emit a token stream and hash it, ~50× cheaper).

### 2.6 ⚠️ Prototype nominations on the real fleet — read as suspects, not verdicts

| Species | Nominated | Note |
|---|---|---|
| MOCK-DRIFT (`patch(...)` with no `spec`/`autospec`/`new`) | **10,167** call sites | Largest exposure. Needs sub-classification (module vs function target) before actionable |
| Mock without `spec` | 4,679 | |
| DUPLICATE (normalized AST hash) | 7,133 → **1,286** | 🔴 See the trap below |
| **NO-ORACLE** | **558** (2.9%) | Loose; acquits any `assert*` call and `pytest.raises` |
| TYPE-ONLY | 167 | Every assert is a bare `isinstance` |
| **CAPTURE-NEVER-READ** | **133** | High-precision — nearly all real |
| SELF-SKIP call sites | 159 | Needs predicate analysis |
| VACUOUS-GUARD | 22 | |
| OR-ESCAPE / SWALLOW / TAUTOLOGY | 9 / 9 / 5 | Ruff independently found 3 `B011` + 3 `PT015` + 1 `PLW0129` |

🔴 **The DUPLICATE normalization trap, and it is worth more than the numbers.** Two prototype runs differing
*only* in whether constant values are folded:

| Normalization | Clusters | Tests in clusters | Meaning |
|---|---|---|---|
| Constants **folded** | 1,882 | **5,206 (27.5%)** | **Parametrize candidates — NOT redundant** |
| Constants **kept** | 1,045 | **2,331 (12.3%)** | **True duplicates** |

`test_pycache_ignored` and `test_venv_ignored` are structurally identical and differ only in a string — they are
*different assertions about different inputs*. **A DUPLICATE rule that folds constants would recommend deleting
real coverage, and would silently reclassify 15% of the suite.** The true duplicates have a clear cause —
**seedgo template propagation**: `test_conftest_fixtures_available` ×18 branches, `test_validate_valid_config` ×8,
`test_retry_waits_between_attempts` ×7. That is the template system working as designed; whether 18 copies earn
their maintenance cost is a human call.

⚠️ **Also measured: `S101` (bare `assert`) fires 30,777 times on this fleet. It is the inverse of what the lane
wants — ignore it on tests.** And **12 files fail to parse** under Ruff, all in `spawn/templates/citizen/` —
Jinja templates, not breakage. **Any audit lane must exclude template directories or it drowns in false positives.**

⚠️ **Two agents measured Ruff's `PT` hits at slightly different numbers** (127 vs 134 `PT018`; 84 vs 94 `PT011`)
because they scoped different file sets (3,426 vs 634 test files, one including templates). **Re-measure with a
pinned scope before quoting either.**

### 2.7 Assertion-quality metrics

**Checked coverage** (Schuler & Zeller, ICST 2011 / STVR 2013): coverage restricted to statements on a **dynamic
backward slice from an assertion**. Measured: checked coverage averaged **43%** vs statement coverage **67%** vs
mutation score **75%**; lower in **all seven** projects, average gap 24 pp. Oracle-decay: *"when 75% of the
assertions are removed, checked coverage decreases by 23%, whereas the mutation testing score only decreases by
14%."* Cost is genuinely modest — AspectJ: **43 minutes** trace+slice vs **20 h 18 m** for mutation testing.

🔴 **There is no Python implementation, and building one is not recommended.** The original uses **JavaSlicer**
(GPL-3.0, dormant 2020); the whole family (State Coverage, Observable MC/DC, HCC) is Java/.NET/Lustre. The
Python substrates are: **`debuggingbook.Slicer`** (Zeller's own, MIT code / CC-BY-NC-SA prose, self-described
proof of concept whose own docs disclaim **exceptions**, if-expressions and multi-statement lines) and
**DynaPyt** (`sola-st/DynaPyt`, **MIT**, pushed 2026-08-27, 97 hooks, **measured 1.2×–16× overhead**). Slicer is
a fine *forensic* tool on one suspicious test — *"show me the backward slice of this assertion"* is exactly the
question the eight NULL-ORACLEs defeated by eye. It is not a fleet metric.

🟢 **Take the covered-oracle gap instead.** Jain, Kalburgi, Le Goues & Groce,
["Mind the Gap"](https://arxiv.org/abs/2309.02395) (2023, ⚠️ peer-reviewed venue **unconfirmed** — cite as
preprint), whose own index terms are *"code coverage, oracle strength, mutation testing"*:

> `oracle_gap(X,T) = cov(X,T) − mut(X,T)`
> *"We distinguish between **raw oracle gap** and **covered oracle gap**, or the gap … over covered code only.
> The covered oracle gap **directly speaks to the quality of the developer-written oracles**."*

Validated directionally: the gap **increases as assertions are removed** and decreases otherwise. Well-covered
files show large positive gaps — *"code that is executed, but poorly checked."*

🔴 **No Python mutation tool ships the split.** cosmic-ray's `TestOutcome` is `SURVIVED|KILLED|INCOMPETENT` —
**an uncovered mutant is reported SURVIVED, indistinguishable from a weak-oracle survivor.** mutmut avoids the
problem (mutating only called functions) rather than reporting it. PIT gets it right with `NO_COVERAGE` — Java
only. **Buildable today from coverage.py + mutmut/cosmic-ray; nobody ships it.** Use the published name so it's
recognizable to reviewers, and copy Hossain et al.'s (ICSE 2023, artifact MIT) presentation: **the gap in
percentage points, per module, ranked** — which makes "executed but poorly checked" the headline number instead
of a coverage percentage.

**Assertion density** (Kudrjavets et al., ISSRE 2006) ⚠️ measured *production* `ASSERT` macros, not test
assertions — do not cite it as licence to grade tests by assert-count. The paper that did measure test
assertions is **Zhang & Mesbah (FSE 2015)**, and it is the campaign's best citation:
- Assertion count ↔ effectiveness, controlling for suite size: **Pearson/Kendall 0.78–0.98** (p < 2.2e−16).
- Assertion coverage ↔ mutation score: **τ = 0.88–0.91**, adjusted R² 0.94–0.99.
- 🔴 **With assertion coverage controlled, statement coverage ↔ mutation score is only τ = 0.50–0.76, and ↔
  *explicit* mutation score only τ = 0.01–0.63.**
- 🟢 **Finding 8**, from 9,177 JFreeChart assertions, ANOVA + Tukey HSD (F = 87.87, p ≈ 0): effectiveness ranks
  **(1) assert(Not)Null → (2) assert(Not)Equals → (3) assertTrue/False.**
  **`assertNull`/`assertNotNull` ranks statistically LAST.** ⚠️ One project, one language, with an acknowledged
  confound — cite as *supporting* evidence for prioritizing NULL-ORACLE, not proof.

**Prioritization evidence worth carrying:** Spadini et al. (ICSME 2018) — tests affected by test smells have
higher change- and defect-proneness, **and the production classes they test are more defect-prone over their
history.** Tufano et al. — test smells are usually introduced **at the first commit of the test** and persist a
long time ⇒ **gate at PR time; a retro-sweep will find mostly ancient debt.** ⚠️ The flakiness↔smell paper in
*EMSE* was **RETRACTED** — don't cite it.

---

## 3. Isolation enforcement

### 3.1 🟢 The recommendation: `sys.addaudithook`, and it is the highest-value item in this report

🔴 **Negative result, stated plainly: there is no mature pytest plugin that asserts "no writes outside `tmp_path`."**
PyPI has no `pytest-hermetic`, `pytest-sandbox`, or `pytest-fs`. The only two candidates:

- **`pytest-litter`** (Apache-2.0, **1★, last push 2024-04-11**) — has the right *shape*: snapshot the path set
  under `rootpath`, re-walk after every test's call phase, name the offending test. 🔴 *(measured)* **It passed
  the reproduced AUDIT-FORGERY case** — a test appending 214 lines to an existing live log. Its snapshot is a
  `frozenset` of path *strings*: no mtime, no size, no hash. **It sees creation and deletion; it is structurally
  blind to modification.** Its ignore-specs are hardcoded with no ini option, and it costs O(files) *per test*
  → 18,042 × 0.9 s = **4 h 30 m** at this fleet's size. **Read it, don't adopt it.**
- **`hermetic-seal`** — 3 months old, single maintainer, monkeypatches `builtins.open`; bypassable by construction.

Corroboration from the other direction: **Bazel specifies the rule and declines to enforce it** —
*"Tests should create files only within `$TEST_TMPDIR`… Currently, such behavior is not enforced."* Google, with
the industry's best sandbox right there, treats test write-locality as an unenforced contract.

🟢 *(measured)* **`sys.addaudithook` (PEP 578, stdlib, 3.8+), ~40 lines in a root `conftest.py`:**

```
AUDIT: 5 out-of-sandbox writes
  <none>                                          os.mkdir  /tmp/littertest/t/__pycache__
  t/test_litter.py::test_appends_to_existing_file open      /tmp/littertest/existing_log.txt
  t/test_litter.py::test_creates_new_file         open      /tmp/littertest/brand_new.txt
  <none>                                          os.mkdir  /tmp/littertest/.pytest_cache/v/cache
```

- **Catches modification** — the case pytest-litter misses.
- **Exact node-id attribution, in-process, no race.**
- **Cost on 1,000 tests, gate off vs on, 4 interleaved rounds: user+sys 2.52 s vs 2.49 s — no measurable
  overhead.** Pure-CPU code is untouched (3 hook fires across 14 ms of `fib(21)`); cost scales with I/O
  operations, not runtime. Theoretical worst case at fleet scale: 18,042 × 200 events × 0.79 µs = **2.9 s (+0.6%)**.
- The same hook covers `socket.connect`, `socket.getaddrinfo`, `urllib.Request`, `http.client.connect`, **and
  flags `subprocess.Popen` with its argv** — one mechanism for filesystem *and* network *and* the subprocess
  blind spot.
- 🔴 **Blind to C extensions.** *(measured)* An entire `sqlite3.connect()` + `CREATE TABLE` + `commit()` produced
  **zero** `open` audit events. This is why layer 2 below is not optional.

### 3.2 🔴 Two corrections to the current plan

**(a) `PYTEST_CURRENT_TEST` attribution works in-process and fails out-of-process.** *(verified)*
`os.environ[...] = ...` calls `putenv()`, which swaps a heap pointer; the kernel keeps serving
`/proc/<pid>/environ` from the original `execve` stack region. `PYTEST_CURRENT_TEST visible in
/proc/self/environ: None`. **Any external observer (strace/fanotify/eBPF) must attribute by timestamp join,
never by reading `/proc/<pid>/environ`.**

**(b) The snapshot tuple must include `st_ctime_ns`.** *(measured)* `(path, st_mtime_ns, st_size)` is defeated by
`os.utime()` restoration after a rewrite — a forge-then-restore round-trip left mtime and size identical.
**`st_ctime_ns` cannot be set from userspace and caught it.** Snapshot `(st_mtime_ns, st_size, st_ctime_ns, st_ino)`.

**(c) Scale the snapshot to per-suite, not per-test.** *(measured, this repo)* Full tree = **37,494 files /
13,989 dirs**, of which **`.backup` alone is 26,111 (70%)**. A `scandir`+`stat` walk costs 2.2–3.3 s unscoped,
**0.77–0.98 s** scoped (excluding `.backup`/`.archive`) — corroborating the "<1 s prototype". Per-test that is
**4 h 30 m**; **per-suite it is 31 s** (17 suites × 2 walks); once per fleet run, **1.8 s**.

### 3.3 The layered design

```
Layer 1  audit hook       every run, ~0 cost, per-test attribution, ~95% of escapes
Layer 2  snapshot diff    once per suite (31 s), ground truth, catches C-ext + subprocess
Layer 3  Landlock         opt-in flag / nightly, turns escapes into test failures
Layer 4  canary test      a deliberate out-of-sandbox write that MUST be caught, every run
```

🔴 **Layer 4 is not optional, and this branch's own history is the argument.** The `user_message_relay` defect
was a kill switch *"registered in provider_manifest.json BY FILE PATH, so run_skill is never on its path"* — a
gate silently off the code path, reporting green for 508 sends. Every mechanism here has a fail-open mode:
`fsatrace` fails open, `strace --seccomp-bpf` **silently falls back to full tracing** if filter setup fails,
Landlock returns `ENOSYS` on old kernels, and an audit hook inside a `try/except ImportError` is simply off.
**Ship a canary that writes outside the sandbox on every run and fails the build if it is *not* flagged.**

**Layer 3 — Landlock**, if wanted: kernel ≥5.13 (this box is 6.8 → ABI 4), **no root needed**, works in
unprivileged containers and GH Actions. Bindings: **`landlock`** (Edward-Knight, **MIT**, pure-ctypes, zero deps)
worked first try. Overhead **+8.7%** on a write-saturated micro-loop, ~0% realistic. Gotchas, all verified:
rulesets only ever **narrow** (per-test allowances need a fresh process); max 16 stacked layers; files opened
*before* sandboxing stay unrestricted; **you must allowlist `/dev/null`** or pytest's `LoggingPlugin` dies with
`INTERNALERROR> PermissionError`.

### 3.4 What the survey rules out

- 🔴 **Do not build on FUSE.** Google shipped `sandboxfs`, maintained it four years, then **deleted it in Bazel
  7.0**: *"it didn't work for most users and it was not consistently faster while being complex to set up…
  **Overall it is not worth its weight.**"* Repo archived. Clearest published negative result in the survey.
- 🔴 **strace is a forensic tool, not a gate** — *(measured)* **4.4× with `--seccomp-bpf`, 6.3× classic**
  → +38 min on this fleet.
- 🔴 **inotify cannot attribute at all** — it carries no PID, structurally. fanotify exists to fix exactly that
  and needs `CAP_SYS_ADMIN`.
- **pyfakefs** (Apache-2.0, pytest-dev, 750★, active) is excellent for the *unit* that must not touch disk, but
  it is not a gate: its documented escape routes — **C libraries ("no way to make such a module work"),
  `sqlite3`, `subprocess`, `multiprocessing`** — are exactly the routes AUDIT-FORGERY could take.
- ⚠️ `pytest-forked` is formally **"Development Status :: 7 — Inactive"**; `pytest-xdist`'s `--forked`/`--boxed`
  **no longer exist in 3.x** (verified against the installed 3.8.0).

### 3.5 🟢 NOOP-FIXTURE — the four-attribute-name theory doesn't hold, and the real gate is 30 lines

*(measured, Python 3.12.3 / pytest 9.1.1)* **Both `monkeypatch.setattr` and `mock.patch` DO raise `AttributeError`
on a missing attribute.** So `mock_infrastructure` was not silent because of misspelled names — unless someone
passed `raising=False` or `create=True`.

| Call | Missing attribute | Escape hatch |
|---|---|---|
| `monkeypatch.setattr("mod.missing", v)` | ✅ `AttributeError` | `raising=False` |
| `mock.patch("mod.missing")` | ✅ `AttributeError` | `create=True` |
| `monkeypatch.setattr(obj, "name", v)` where `obj` is a plain object / `SimpleNamespace` / `MagicMock` | ⚠️ **succeeds silently** | — |

**The overwhelmingly likelier cause — and the one neither library can *ever* catch — is patching the right name
in the wrong module:**

```python
# victim.py
def real(): return "real"
# consumer.py
from victim import real          # consumer.real is now its OWN name
def use(): return real()

patched victim.real    -> consumer.use() returns "real"   # patch SUCCEEDED. protected NOTHING.
patched consumer.real  -> consumer.use() returns "FAKE"   # correct target
```

The patch is *valid*: the attribute exists, is replaced, is restored. No error at any layer. **This is the same
failure mode as `AIPASS_TEST_LOG_DIR` — a control surface nothing on the hot path consults.**

🔴 **Negative result: nothing detects a fixture that patches successfully but protects nothing.**
`pytest-deadfixtures` catches *unrequested* fixtures — `mock_infrastructure` was `autouse`, requested by every
test, and would score perfectly clean.

🟢 **Build it — ~30 lines, zero judgment, and it would have caught the incident on day one.** The behavioural
test is: **at teardown, walk every mock the fixture created and assert `call_count > 0`.** A mock installed by an
`autouse` "protection" fixture and never called across the whole suite is, by definition, protecting nothing.
Wire it as: fixture registers its mocks in a session-scoped registry → `pytest_sessionfinish` reports any mock
with a lifetime call count of zero.
**Complementary free check:** run the audit-hook gate **with the protective fixture removed**; if the write count
is unchanged, the fixture wasn't protecting anything. That is a mutation test on the fixture itself.

---

## 4. Flakiness and order-dependence

### 4.1 🟢 The number that justifies the whole lane

**Gruber, Lukasczyk, Kroiß & Fraser, "An Empirical Study of Flaky Tests in Python", ICST 2021**
([arXiv:2101.09077](https://arxiv.org/abs/2101.09077)) — **22,352 PyPI projects, 876,186 test cases, 7,571 flaky
tests**:

> ***"Order dependency is a much more dominant problem in Python, causing 59% of the 7,571 flaky tests"***
> (vs 28% infrastructure, 13% network/randomness)
> *"A 95% confidence that a passing test case is not flaky on average would require **170 reruns**."*

Java's comparable figure (iDFlakies, 683 projects) is **50.5%**. **Python is worse.** The instinct that
ORDER-DEPENDENT is a high-yield gate is backed by the largest study ever done on Python specifically.

⚠️ **And Google's priorities do not transfer.** Their "Sources of Flakiness" slide lists resource waits,
`sleep()`, WebDriver, UI tests, multithreading, environment — **test-order dependence is not on it.** Their data
(16% of 4.2M tests flaky; 1.5% of *executions*; 84% of pass→fail transitions; 2–16% of compute spent re-running
flakes; 10× rerun on transitions) is real but describes a different profile. Do not import it wholesale.

Gruber et al. again, ICST 2023 industrial dataset: *"The best model achieved an **F1-score of 95.5% using only 3
features: the tests' flip rates**, changes to source files in the last 54 days, and changed files in the most
recent PR."* — **flip rate from CI history alone is nearly all the signal. No instrumentation required.**

### 4.2 Plugin comparison

| Tool | License | Latest | ★ | What it does | xdist |
|---|---|---|---|---|---|
| **pytest-randomly** | **MIT** | 4.1.0 (2026-04-20) | 721 | **Not `random.shuffle`** — a deterministic sort by `crc32(f"{seed}::{key}")`; functions in class, classes in module, then modules. **Never interleaves across modules.** Reseeds `random`/factory_boy/Faker/model_bakery/NumPy **3× per test** | Seed pushed to workers, but `--dist load` dispatch stays nondeterministic |
| **pytest-random-order** | MIT | 1.2.0 (2025-06-22) | 79 | Bucket-based; **`global` = true cross-module interleave** — the only tool that finds interleaving-dependent OD | runs |
| **pytest-reverse** | MIT | 1.9.0 (2025-09-09) | 30 | Literally `items[:] = items[::-1]` — **12 lines** | fine |
| **detect-test-pollution** | **MIT** | 1.2.0 (2026-08-17) | **205** | Bisects a known-failing test down to its polluter; `--fuzz` | 🔴 serial only |
| **pytest-replay** | MIT | 1.7.1 (2025-12-23) | 63 | Records `{nodeid,start,finish,outcome}` JSONL **per xdist worker**; `--replay=file` re-executes that exact order | ✅ built for it |
| **pytest-repeat / -flakefinder / -rerunfailures / flaky** | MPL-2.0 / Apache-2.0 / MPL-2.0 / Apache-2.0 | — | — | Repeat-N and rerun | 🔴 **rerun-as-policy hides the species the lane hunts** |

### 4.3 🟢 Three measured facts that shape the design

**(a) pytest-randomly has subset-order stability; pytest-random-order does not.** Deliberate since 3.10.0:
*"running a subset of tests with the same seed will now produce the same ordering as running the full set…
This allows narrowing down ordering-related failures."* **This is exactly the invariant ddmin/bisection
requires** — delete tests from a failing order and the survivors keep their positions, for free.
**Prefer pytest-randomly for anything you intend to bisect.**

**(b) 🔴 xdist destroys order reproducibility.** *(measured, fixed `--randomly-seed=4242`)* Serial: two runs
byte-identical. `-n2`: worker split 504/496 vs 413/587, **diverging at index 0 of worker 1**. `--dist load` sends
tests *"to any worker that is available, without any guaranteed order."*
**Run the order-dependence lane with `-p no:xdist`.** Use `--dist loadfile` in normal CI (free, keeps a module's
tests in one worker so per-file pollution stays observable) and `pytest-replay` to capture what actually
happened when a parallel run goes red.

**(c) ⚠️ Seed reproducibility is version-fragile.** pytest-randomly **4.0.0 (2025-09-10)** moved from MD5 to CRC32
and to a per-test seed. **A seed recorded under 3.x will not reproduce under 4.x.** Pin the plugin version
alongside every recorded seed, or the audit trail is worthless.

**(d) 🟢 `PYTHONHASHSEED` is a free Python NonDex — with a trap.** *(measured)* Sets of **strings** iterate in a
different order per seed; sets of ints don't (`hash(int) == int`); dicts preserve insertion order regardless
(language guarantee since 3.7 — shuffling them would be a category error). `os.listdir`/`glob` are documented
*"in arbitrary order"* and returned neither alphabetical nor creation order.
🔴 **`PYTHONHASHSEED=0` *disables* randomization** — pinning it to 0 "for reproducibility" hides the entire bug
class. **Pin a recorded non-zero seed and vary it per CI run.**

### 4.4 The polluter-identification algorithms

🔴 **`pytest` has no built-in `--bisect`** (RSpec has one; GitLab's published workflow depends on it).
**`detect-test-pollution`** (asottile, **MIT**, 205★, active) fills the gap in ~300 LOC:

```
1. DISCOVER   --collect-only with a plugin dumping nodeids; always -p no:randomly
2. GUARD A    run([victim]) must PASS   3. remove victim from the list
4. GUARD B    run(all_others + [victim]) must FAIL
5. BISECT     while len(ids) != 1:
                  part1, part2 = ids[:len(ids)//2], ids[len(ids)//2:]
                  ids = part2 if run(part1 + [victim]) passed else part1
6. GUARD C    re-confirm the survivor still fails
```

⚠️ **Three limitations to budget for.** Step 5 is a **plain binary search, not ddmin** — it assumes a *single*
polluter, so a two-test cause split across the halves makes both probes pass and it dies in
`AssertionError('unreachable?')`. **iPFlakies measured that 26% of Python OD tests need more than one polluter
(31% of victims), versus 3% in Java** — this bites materially harder here than in the tool's home ecosystem.
The `--fuzz` seed is **hardcoded and not exposed**, so re-running buys no new coverage. No xdist.

**iFixFlakies' Minimizer** (ESEC/FSE 2019) is the ~200-line ddmin upgrade when that happens. Three things a
reimplementation must get right: (1) `deltadebug` is **ddmin**, producing a **1-minimal *subsequence*** — a
possibly non-consecutive subset preserving original relative order, which is exactly what finds multi-test
causes; (2) victim-vs-brittle is decided by an **isolation run repeated 10×** — if isolation is itself
inconsistent the test is NOD, bail out; (3) the prefix must preserve relative order (pytest-randomly gives this
free at a fixed seed).

**iDFlakies' configuration mapping** (ICST 2019), with measured single-round yields:

| iDFlakies config | pytest equivalent | Yield |
|---|---|---|
| original-order | plain `pytest` | 2.7% of rounds fail |
| **reverse-class-method** | **`pytest --reverse`** | **50.0% of rounds fail; 46.8% attributable to OD.** Run **once** |
| random-class-method *(best — found 88.0% of all OD tests)* | **pytest-randomly** | repeat N rounds |

Their own recommendation: *"first run the reverse-class-method configuration once to quickly detect a portion of
the OD tests and then use the random-class-method configuration to detect more."* The two are **complementary,
not redundant** — reverse found 4 tests random missed; random found 119 reverse missed.
🟢 **Cost shortcut from the authors:** the truncated-*original* rerun in the OD/NOD classifier changed the verdict
in only **3 of 7,441 runs. Skip it** — halves classification cost for a rounding error of accuracy.

### 4.5 🟢 RankF_O — the cheapest polluter finder, zero extra test runs

From *"Ranking Relevant Tests for Order-Dependent Flaky Tests"* (Rahman, Chanumolu, Rafi, Shi, Lam). Ranks
candidate polluters purely from **logs of orders you already ran**. For each recorded order, for every test `gt`
positioned before the OD test `ot`: add to `gt`'s **positive** score if that order **failed**, **negative** if it
**passed**. Scoring variants: `+1` per appearance; `1/indexOf(ot)`; `1/(indexOf(ot) − indexOf(gt))`; combined.

| Strategy | Tests run to find the first relevant test | Wall |
|---|---|---|
| iFixFlakies delta-debugging | — | **419.0 s** |
| One-by-one baseline | 15.5 | 60.9 s |
| **RankF_O (log analysis only)** | **1.0** | **1.9 s** (ranking itself <100 ms) |

**~50 lines of Python over `pytest-replay` JSONL you're already producing, and 220× faster than delta-debugging.
Run it *before* any bisection.**

### 4.6 Cost and a recommended schedule

*(measured)* Bisection: a planted polluter/victim pair in a 1,002-test suite took **14 pytest processes, 30.3 s
wall — 9.4× one full suite run**, dominated by process startup.
Model: `bisect ≈ (⌈log₂N⌉ + 4) × T_startup + 2 × T_suite_serial`

| Scope | Total |
|---|---|
| **Fleet-wide** (N=18,042) | **≈ 59 min per victim** |
| **One suite** (N=1,443, 60 s) | **≈ 2.5 min per victim** |

🟢 **Bisect within the suite, never across the fleet** — same answer in ~95% of cases (pollution is
overwhelmingly intra-suite: shared module state, shared conftest fixtures). Escalate only when intra-suite
bisection returns "passes with the whole suite."

| Lane | Contents | Cost |
|---|---|---|
| **Every PR** | audit-hook gate + `--reverse` on **changed suites only** | +0 s gate, +11–60 s per changed suite |
| **Nightly** | 1 × `--reverse` fleet + 3 × random-order rounds (`-p no:xdist`), all with `pytest-replay` recording | **~34 min** |
| **Weekly** | 20 × random-order rounds; RankF_O over accumulated replay logs; auto-file top-ranked candidates | **~2 h 51 m** |
| **On triage** | `detect-test-pollution` scoped to the failing suite | ~2.5 min/victim |
| **Quarterly** | one-test-per-process census, one suite at a time (48 min per 1,443 tests) | rotates |

⚠️ **No organisation publishes an explicit "we shuffle nightly at HH:MM" schedule.** The consistent industry
pattern is **cheap perturbation continuously, expensive analysis on demand after triage** (Google: 10× rerun on
transitions, continuous; GitLab: 1 automatic retry, bisection on demand by a human after triage).

**Two industry moves worth copying regardless:** Spotify published a per-team table of each test with fast/slow
and flaky flags and *"By making this table available and doing nothing else this reduced test flakiness at
Spotify from 6% to 4% in two months"* — **visibility alone, no enforcement, cut the rate by a third.** And
Shopify's guardrail on retries: *"we detect all the tests that pass after a retry and notify the developers…
a test that passes in a second attempt shouldn't be treated like a failure, but **as a warning**."*

---

## 5. Oracle quality

### 5.1 🟢 Coverage contexts — adopt; this is the execution-tier enabler

**Licenses all clean:** `coverage` **Apache-2.0**, `pytest-cov` **MIT**, `pytest-xdist` **MIT**, `slipcover`
**Apache-2.0**. No paid tiers.

Use **`pytest-cov`'s `--cov-context=test`**, not `dynamic_context = test_function` — richer labels, xdist-safe.
Context strings are `<node id>|<phase>` where phase ∈ `setup|run|teardown`; if a static context is also set the
two join with `|`, so **always `rsplit("|", 1)`, never `split("|")`**.

Query via `CoverageData.contexts_by_lineno()` (schema-stable) or raw SQL with
`coverage.numbits.register_sqlite_functions()` (fast path). ⚠️ The docs warn *"the schema can change without
changing the major version"* — **pin `coverage` or use the API.**

**🔴 The overhead finding that decides the architecture:** dynamic contexts force the slow `ctrace` core.
Verbatim from the config docs on `[run] core`: *"The sysmon core does not yet support plugins, dynamic contexts,
or some concurrency libraries."* Still true in **7.16.0** (2026-08-28). On Python 3.12, contexts → `ctrace`, and
branch coverage → `ctrace` too.

*(measured, this hardware)*

| Configuration | Ratio to baseline |
|---|---|
| line, sysmon, serial | 1.14× |
| line, ctrace, serial | 2.36× |
| line + contexts, serial | ~2.1× |
| **line + contexts, `-n4`** | **~1.5×** |

🟢 **Contexts are nearly free on top of `ctrace`, and xdist parallelizes the overhead away.** Contexts survive
xdist correctly (verified: combined DB identical to serial).

**The scoped-survival loop, demonstrated end to end.** A planted NULL-ORACLE and TYPE-ONLY test alongside a real
one; build the map; gut every function body to `return None`; re-run **only the covering set**:

```
=== gut lib.py, re-run ONLY its covering tests ===
FAILED tests/test_weak.py::test_real_oracle - AssertionError: assert None == ...
1 failed, 2 passed in 0.03s
```

**The two survivors are exactly the two weak oracles. 3 tests run instead of 1,088.** *(Control: on a healthy
synthetic module, all 600 covering tests died on gutting — 0 false survivors.)*

**Cost at fleet scale:**

| Operation | Cost |
|---|---|
| One-time map build, line + contexts, `-n4` | **~13 min** *(measured 1.5×)* |
| Per-module gut with 100 / 500 / 2,000 covering tests | ~17 s / ~28 s / ~71 s (**30× / 18× / 7×** cheaper than 514 s) |
| **Fleet sweep, 400 modules** | **~2 h 15 m**, versus **~57 hours** unscoped |

🟢 **Free bonus:** modules with **zero** covering contexts need no gutting at all — they are a *coverage* failure,
not an *oracle* failure. The query separates them for free.

**🔴 Four gotchas that will silently corrupt results:**

1. **Module-level lines land in the EMPTY context.** `def`/`class`/import lines execute during *collection*.
   [Issue #974](https://github.com/nedbat/coveragepy/issues/974), open since 2020. Filtering `context != ''` is
   correct, but a module whose only executed lines are definitions reports **zero covering tests** — do not read
   that as "untested."
2. 🔴 **Subprocess-executed code is measured but attributed to NO test.** *(measured — the one that will bite
   AIPass hardest.)* The child starts a fresh `Coverage` with an empty context, so every line it executes is
   orphaned. **Any test driving the CLI through `subprocess` is invisible to the scoped-survival map.** Given
   how much of this fleet does exactly that: detect and exclude such tests from scoped runs, or fall back to the
   full suite for CLI-driven modules. **Do not let it fail silently.**
3. **Branch mode uses the `arc` table, not `line_bits`**, and `fromno` can be negative (entry/exit sentinels).
4. **The SQLite schema is explicitly unstable.** Pin, or use `CoverageData`.

**GATE-SHADOW: branch coverage is strictly better, with a limit.** *(measured)* Line coverage reports
`if not path: return []` **on one line** as covered because the `if` ran; only branch coverage's `11->exit`
exposes it. 🔴 **But coverage.py does not track short-circuit sub-conditions** — `if a and b and c` with `c`'s
discriminating case never exercised reports **100% branch coverage** in all three shapes tested. *(This
contradicts a widely-cited blog post, which did not reproduce on coverage 7.15.2 / Py3.12.)*
**A guard shadowed inside a compound boolean is invisible at any setting**, [issue #660](https://github.com/coveragepy/coveragepy/issues/660)
is open, and the only Python condition-coverage tool (`instrumental`) is **GPL, last released 2014**.

⚠️ **slipcover** (Apache-2.0, active, 5% median overhead vs coverage.py's 180%) **has no context support** —
verified against its full argument parser. Good for a fast plain-coverage gate; **irrelevant to this lane.**

🔴 **No maintained tool exists for per-test coverage diffs or test-to-code traceability from contexts.**
`pytest-rts` (Apache-2.0) is built on exactly `--cov-context=test` and is **dead since 2021**; `smother` (MIT)
has the right CLI shape and is **dead since 2017**. **Write the ~40 lines.**

### 5.2 🟢 `typeguard` — one ini line, and it attacks NULL-ORACLE structurally

The question for contract tools is *activation mechanism*, not features.

| Tool | Activation over 18k existing tests | Edits |
|---|---|---|
| **typeguard** (MIT, 1,782★) | **Bundled pytest plugin**; `--typeguard-packages=aipass` | **Zero. One ini line.** |
| **beartype** (MIT, 3,488★) | `beartype_packages([...])` in root `conftest.py` **before** imports | One line |
| icontract / deal (MIT) | none — write every contract first | high |
| pydantic | 🔴 no import hook, no plugin; `@validate_call` **does not validate returns by default** | prohibitive |

```toml
[tool.pytest.ini_options]
addopts = "--typeguard-packages=aipass"
```

**A gutted function annotated `-> str` that returns `None` raises `TypeCheckError` at the return, regardless of
what the test asserts.** That is a direct, free, structural NULL-ORACLE detector across all 18,042 existing tests.

⚠️ **Verified default that will fool you:** `collection_check_strategy = CollectionCheckStrategy.FIRST_ITEM` —
`list[int]` is validated by inspecting **one element**. Set `ALL_ITEMS` for real checking, at O(n).
⚠️ **No published overhead figures** — measure the delta against the 514 s baseline before committing.
🔴 **Ship a control test that must fail before trusting it** — a deliberately type-violating function. The scar
tissue here is exact: the relay tests that passed against ungated code because the mock was failing on its own.

`beartype` is nearly as cheap and formally fastest — its O(1) claim is real and honestly stated as *"a one-way
random tree walk"*, i.e. **O(1) by sampling**, ~1 µs/call. Two footguns: `beartype_this_package()` **raises** from
a test-runner context (use `beartype_packages`), and calling it after import *"silently reduces to a noop."*
`deal`'s `@deal.has()` for declaring purity/no-I/O is a genuinely novel oracle unavailable elsewhere — small
high-value set only.

### 5.3 🟢 `dirty-equals` — if you adopt one thing, adopt this

**MIT, 1,004★, 2.8 M downloads/mo.** No plugin, no files, no discipline, no CI change. Predicate objects that
override `__eq__`:

```python
assert user == {'id': IsPositiveInt, 'avatar': IsStr(regex=r'/[a-z0-9\-]{10}/example\.png'),
                'settings': IsJson({'theme': 'dark'}), 'created_ts': IsNow(delta=3)}
```

**It kills TYPE-ONLY** (upgrades `isinstance(x, int)` to a *constrained* assertion a gutted default can't satisfy)
and **cannot MIRROR-EXPECT** (the expected side is a predicate from a test library, never a symbol from the
module under test). ⚠️ It does **not** help NULL-ORACLE, and it composes with **inline-snapshot only** — not with
syrupy/approvaltests/pytest-regressions, which compare serialized strings.

### 5.4 🔴 Property-based, symbolic and generated oracles — three clear negatives

**Hypothesis** (MPL-2.0, 8,919★, releases roughly daily — zero maturity risk) **never invents an oracle. It
amplifies the one you wrote.** Point it at a NULL-ORACLE and you get 100× more executions of a test that still
cannot fail. `RuleBasedStateMachine` is the best structural answer to SELF-CAP and SMOKE-ONLY (an `@invariant()`
cannot be satisfied by a gutted function) — but a state machine is *a second implementation of your semantics*,
0.5–2 days each plus drift. Realistic scope: **3–8 machines on genuinely stateful subsystems** (mail queues,
registries, switch state, watchdog handles), not fleet-wide.
🔴 **HypoFuzz is NOT OSI** — "LicenseRef-HypoFuzz", explicitly non-commercial, *"use in continuous integration or
development pipelines"* requires a paid license. **Excluded.**

🔴 **The ghostwriter is not a credible auto-upgrade path** — and it generates the very species being hunted.
*(measured on a realistic 5-function module: `hypothesis write` produced **five tests, all `test_fuzz_*`, zero
assertions**.)*

| Mode | Emitted assertion | Verdict |
|---|---|---|
| `fuzz` / `magic` (default) | **none** — bare call | 🔴 **NULL-ORACLE, auto-generated** |
| `ufunc` | `assert result.dtype.char == expected_dtype` | 🔴 **TYPE-ONLY, auto-generated** |
| `idempotent` | `assert result == repeat` | Weak — satisfied by `return None`, identity, any constant |
| `roundtrip` | `assert first_param == value{n-1}` | Strongest it emits — hostage to strategy quality |
| `equivalent` | `assert result_0 == result_1` | **Vacuous with only one function** |

🔴 **And even the good mode produced a NULL-ORACLE.** Told explicitly `--roundtrip`, it emitted a real oracle with
`cfg=st.builds(dict)` — *(measured)* **`st.builds(dict)` produced exactly one distinct value, `{}`, over 200
draws.** Against a fully gutted `dump_config` returning the constant `"{}"`: **`1 passed in 2.09s`.**
**Use it as a worklist generator, never as a test generator.** Read where it finds roundtrip pairs and where it
emits `st.nothing()` (= a missing annotation), act, **delete the output.**

🔴 **`crosshair diffbehavior` is NOT a mutation substitute.** *(measured, real-vs-gutted)*

| Pair | Result | Wall |
|---|---|---|
| `redact` vs `return None` | ✅ found | 114 s |
| `truncate` vs `return text` (SELF-CAP shape) | ✅ found | 17 s |
| 🔴 **`redact` vs `return answer`** (subtle gut) | ❌ **"No differences found"** | 21 s |
| 🔴 same, `--max_uninteresting_iterations=50` | ❌ **still nothing** | **400 s** |
| ⚠️ `write_report` (file I/O) vs `return 0` | ⚠️ **bogus "difference"** — `SideEffectDetected` | 58 s |

Three disqualifiers: **the false negative is silent and exits 0** (`redact('abc','b')` → `'a***c'` vs `'abc'` is
a difference a human sees instantly; SMT string theory chokes on `str.replace` with a symbolic needle — *the most
security-relevant function shape is the shape it is worst at*); **I/O code yields guaranteed false positives**;
and **one function pair costs 20–400 s against a 514 s full-fleet budget**. **Keep it on a dev machine for
refactoring pure annotated functions; never in CI.**
🔴 **Avoid `crosshair cover` entirely** — its own docs say *"CrossHair only reports what your code does, not what
it is supposed to do."* It snapshots current behaviour into assertions: **MIRROR-EXPECT by construction.**

🟢 **Metamorphic testing — hand-roll it, fifteen lines, no dependency.** No credible library exists (`gemtest`,
MIT, has 10 stars and 3 commits). It is **the right conceptual weapon against NULL-ORACLE** because it asserts a
**relation between two runs**, which `return None` cannot satisfy:

```python
assert redact(payload + SECRET, SECRET) == base + "***"   # MR1: extra occurrence
assert redact(base, SECRET) == base                        # MR2: idempotent
assert redact(payload, "\x00nonexistent") == payload       # MR3: no-op secret
```

🟢 **Schemathesis is the WRONG-LAYER instrument, and it is MIT.** *(route enumeration executed)*

```python
schema = schemathesis.openapi.from_asgi("/openapi.json", app)   # no server needed
declared = {r.ok().label for r in schema.get_all_operations()}  # "GET /users/{user_id}", ...
```

Then record `request.method`/`request.url.path` in a test-client fixture and **fail CI when
`declared - exercised` is non-empty** — that is exactly the set the 97%-covered handler lane was hiding.
~1 day of work. Its 13 built-in checks default to enabled and include **`ignored_auth`** (endpoint still answers
with auth stripped) and `response_schema_conformance`, **a genuine auto-derived non-absence oracle** — a gutted
route returning `None` fails schema validation. 🔴 **Flag the irony:** schemathesis.io sells "TraceCov —
schema-level coverage for your OpenAPI spec" as paid SaaS. **You do not need to buy it.**

### 5.5 Snapshot testing — and the distinction that resolves the MIRROR-EXPECT question

🟢 **Snapshot testing does not have the bug that was actually measured.** Its mirror is **temporal** (past output
vs present output); the measured MIRROR-EXPECT is **referential** (module symbol vs itself). **They fail
completely differently: a referential mirror can *never* fail; a temporal mirror fails on *every real change*.**
The 78 tests survived a garbage production constant because the expected value was the same live symbol. Had it
been a recorded rendering on disk, changing that constant would have turned all 78 red.

The field's own framing is a feature declaration, not a warning — Feathers: *"The purpose of characterization
testing is to document your system's actual behavior; not to check for the behavior you wish your system had."*
And the sharpest statement of the risk, from Jakub Sobolewski: ***"The first snapshot is a decision, not a fact.
That green check does not mean the output is correct. It means the output now exists."***

Gazzinelli Cruz, Rocha & Valente, **JSS 204 (2023) 111797**, 50 practitioner documents — top drawback is
fragility (14/50), specifically *"blindly updating the test results… 'when tests fail, it is very easy to update
the snapshots without fixing the code.'"* ⚠️ **Note the tension with the obvious rule:** the surveyed consensus is
snapshots committed **alongside** the code, **not** in a separate commit.

🔴 **Negative result: no tool flags "a snapshot file was updated in the same commit as the source that produced
it."** Searched GitHub repo + code search, the Semgrep registry (structurally cannot see git history), Danger
(danger-python is one release in six years). **Build it in under an hour** — `git diff --name-only`, grep for
`__snapshots__/|\.ambr$|\.approved\.` alongside `^src/.*\.py$`. Given the JSS finding, **ship it as a warning
demanding a declared review, not a hard failure.**

🔴 **The NULL-ORACLE species survives *inside* snapshot testing, in every tool.** *(measured)* `syrupy` recorded
`snapshot == None` and re-ran → *"1 snapshot passed"*, forever. `inline-snapshot`'s `snapshot(None)` passes
silently. `approvaltests` passed a gutted function returning `""` against a 1-byte approved file. **No
off-the-shelf trivial-snapshot lint exists — and snapshot files are far easier to lint than arbitrary assertion
ASTs, because they are a small set of known paths holding serialized values.**

**Verdict: `inline-snapshot` + `dirty-equals` for output-shaped code only**, after building the trivial-snapshot
linter. inline-snapshot is right because (a) the expected value lives **in the test source**, so it appears in
every diff and can't be reviewed away in a folder nobody opens; (b) it is the **only** tool that hard-fails an
unfilled snapshot in both local and CI mode; (c) it **auto-disables in CI across 12 env vars**, so a green build
can never have been produced by a write; (d) it integrates dirty-equals as **"unmanaged values"** — the only
mechanism in Python where a snapshot can contain hand-written predicates the tool is contractually forbidden to
overwrite. **That last property is what converts a recording into an oracle.**
⚠️ inline-snapshot has a $10/mo "Insiders" *early-access* tier — delayed-open-source, not open-core; the MIT
package is fully functional. Flag it in the ADR.
🔴 **Reject `snapshottest`** — 0.6.0 does `import imp`, removed in Python 3.12; the fix exists on master and was
never released; its 402 k downloads/mo are pure inertia.
🔴 **Do not install `approvaltests`** — *(verified today)* merely `import approvaltests`, with no test executed,
creates `.approval_tests_temp/` in the CWD and **downloads two scripts over HTTPS and chmods them 0755 at import
time, inside a bare `except:`**. One of them, `approve_all.py`, is a **mass re-baseline button**. Opt out with
`APPROVALTESTS_DISABLE_SCRIPT_DOWNLOADS=1`. **Study its doctrine; never its runtime.**

🟢 **Steal its doctrine though:** ApprovalTests encodes review as a state machine, not advice. A new test has no
`.approved` file so *"the test will always fail the first time you run it"* — the node in their own flowchart is
labelled `Fail(Forced)`, and their TDD loop is `Write Code → **Assess the Result** → Approve`. **In approval
testing the human assessment step is not an add-on to the test — it *is* the test.**

🟢 **The redaction budget** (a rule that generalizes well beyond snapshots): every `matcher=`, `exclude=`,
`path_type(`, `with_scrubber` is a field **no longer asserted**. Count them; more redacted than asserted → not an
oracle. **Always prefer an asserted predicate (`IsNow()`) over a redaction** — that single preference is what
stops an oracle draining away as a suite matures.

### 5.6 The charter framing

**Jahangirova, Clark, Harman & Tonella, ISSTA 2016:** an oracle has two failure modes — **false positives**
(rejects correct behaviour, revealed by test generation) and **false negatives** (accepts incorrect behaviour,
revealed by mutation).

🟢 **Every species in the taxonomy is an oracle FALSE NEGATIVE.** That gives the lane a defensible one-sentence
charter: ***"this lane measures oracle false-negative rate."***

And **Barr et al.'s TSE 2015 taxonomy** gives the sharpest one-line description of the species: the pytest suite
is *nominally* a **specified** oracle; a NULL-ORACLE test silently degrades to an **implicit** one — it only
fails when Python itself raises. ***"This test has degraded from a specified oracle to an implicit one."***

---

## 6. Free AI-assisted review

### 6.1 🔴 OpenRouter's free tier is disqualified — but read the caveat

*(verified against the live API, 2026-08-29: 396 models, exactly 18 with a `:free` suffix)*

Two things the docs don't say, found by querying `/models/{id}/endpoints`:
- **Free endpoints are more aggressively quantized than paid.** `z-ai/glm-5.2:free` is served at **fp4 / 256k
  ctx**; the paid endpoints for the same model are **fp8 / 1M ctx**. You are not getting the same model.
- **`google/gemma-4-*:free` routes to Google AI Studio**, so Google's unpaid-service terms (training + human
  review) attach to code laundered through a second vendor's API.

**Rate limits:** 20 RPM; **50 requests/day** under 10 lifetime credits; 1,000/day once you have **purchased ≥10
credits ($10)**. So the useful tier is not free.

🔴 **The disqualifier is the data policy.** To use `:free` models you must enable **both** "free endpoints that
may train on request data" **and** "free endpoints that may publish prompts" — the latter meaning **prompts and
completions may be published to public datasets**.
⚠️ **Flagged honestly:** the source article is Cloudflare-gated (403 to both WebFetch and curl), so this is via
search-engine extraction of that page rather than a direct read, and **one research pass read the same toggle as
an optional 1%-discount opt-in instead.** The two readings disagree. **Verify in Settings → Privacy before
sending any code.** Either way, the fp4 quantization and the $10 floor are independently disqualifying.

### 6.2 The routes that survive

| Provider | Free tier real? | Best free model | Binding limit | Trains on your data? | Verdict |
|---|---|---|---|---|---|
| **Cloudflare Workers AI** | ✅ renewable daily, forever | `llama-3.1-8b-fp8-fast`, `qwen3-30b-a3b` | 10,000 Neurons/day | 🔴 **explicit, unconditional NO** | 🟢 **Best overall** |
| **Groq** | ✅ renewable daily | `qwen/qwen3.8-27b` | 1,000 RPD / 2M TPD | 🔴 **contractual no; ZDR available** | 🟢 **Best terms** |
| **Google Gemini** | ✅ | `gemini-2.5-flash` | unpublished | ⚠️ **YES + human reviewers** | ❌ except EEA/UK/CH |
| **Mistral** | ✅ "Free mode" | Mistral Small | unpublished | ⚠️ yes by default | ⚠️ only after opt-out |
| **Cerebras** | 🔴 **no free tier** | — | $5 credits, 30-day expiry, card required | — | ❌ |
| **GitHub Models** | 🔴 **RETIRED 2026-07-30** | — | — | — | ❌ **gone** |

**Three findings that invalidate any stale plan:** GitHub Models was **fully retired on 2026-07-30** (playground,
catalog, inference API, BYOK). Cerebras' own FAQ: *"Is there a permanently free tier? — No."* And Gemini's free
terms, verbatim: *"human reviewers may read, annotate, and process your API input and output… **Do not submit
sensitive, confidential, or personal information to the Unpaid Services.**"*
⚠️ **One carve-out worth a human ruling:** *"If you're in the European Economic Area, Switzerland, or the United
Kingdom, the terms under 'How Google uses Your Data' in 'Paid Services' apply to all Services… even though they
are offered free of charge."* That is a jurisdiction question, not something to infer.

**Cloudflare's clause is the cleanest:** *"Cloudflare does not use your Customer Content to (1) train any AI
models made available on Workers AI or (2) improve any Cloudflare or third-party services."* Free and Paid get
the identical 10,000 Neurons/day. **Groq's is the strongest written:** *"Groq is not permitted to use Inputs or
Outputs for training or fine-tuning any AI Model Services or other models."*
🟢 **Running Cloudflare and Groq concurrently gives ~1,830 reviews/day *and* satisfies the two-model-agreement
control for free** — different vendors, different model families.

### 6.3 🔴 Local models: honest numbers

*(profiled, this machine: Intel i5-4308U Haswell-ULT, 2 physical cores / 4 threads, 15 W, AVX2+FMA, no AVX-512,
15 GB RAM, no usable GPU; **measured STREAM-like memory bandwidth 16.5 GB/s copy**)*

Token generation is memory-bandwidth-bound. At ~11 GB/s effective:

| Model | Weights | Gen | Per review (800 in / 250 out) |
|---|---|---|---|
| 7B Q4_K_M | 4.4 GB | ~2.5 tok/s | ~153 s |
| 3B Q4_K_M | 1.9 GB | ~5.8 tok/s | ~66 s |
| 1.5B Q4 | 1.0 GB | ~11 tok/s | ~36 s |

**Nothing useful at full-sweep scale** — 7B over all tests is **33.6 days of continuous 15 W compute**. But
**local becomes genuinely attractive on a triaged subset**: 935 candidates on a 3B model is **~17 hours** — one
overnight run, zero network, zero data-policy exposure, no third party involved at all.

### 6.4 OSS LLM test tooling — licenses all verified

| Project | License | ★ | Last push | State |
|---|---|---|---|---|
| **Pynguin** | **MIT** (was LGPL ≤0.29; relicensed at 0.30) | 1,384 | **2026-08-27** | Active — but generates **regression assertions, not oracles** (§1.4) |
| **Qodo Cover-Agent** | 🔴 **AGPL-3.0** | 5,627 | 2026-04-05 | 🔴 README: *"no longer maintained"* |
| **CoverUp** | Apache-2.0 | 112 | 2026-04-05 | "Work In Progress" |
| **mutahunter** | 🔴 **AGPL-3.0** | 299 | **2025-04-17** | 🔴 ~16 months dormant |
| **PR-Agent** | **MIT** | 12,757 | **2026-08-29** | Active; ⚠️ **moved org** to `The-PR-Agent/pr-agent` |
| **TestGen-LLM** (Meta) | — | — | — | 🔴 **Paper only, no code** |

🔴 **Nothing exists that critiques existing tests.** The entire OSS field is *generation* (Pynguin, CoverUp,
Cover-Agent) or *evaluation of LLM apps* (DeepEval, promptfoo). **There is no OSS tool that reads your test suite
and tells you which tests are weak.** This is a real gap, and it means `audit-tests` is building something that
doesn't exist.

🟢 **But TestGen-LLM's method is the most valuable thing in this section, because it is the campaign's own law
already proven at industrial scale.** Extracted from the paper:

> **Pre-process → Builds? → Passes? → Improves coverage? → Post-process → "Assuredly onward code"**

Filter 2 discards any test not passing **on first execution**. Flakiness filter: *"does not pass on every one of
five executions is deemed flaky"* — **5 repeated runs, all must pass**. Filter 3 discards any test not increasing
coverage. Measured funnel: **75% built, 57% passed reliably, 25% increased coverage**, and per-candidate success
was only **~4%** — yet **50%+ of submitted diffs were accepted by engineers (70% of those actually reviewed)**.
Their framing: it *"submits, for human review, only test cases clearing all filters."*
**That is ADVISORY-ONLY with numbers proving the discipline pays. Steal the funnel wholesale.**

### 6.5 🔴 The failure mode that is anti-correlated with the target

Documented LLM-as-judge biases: **verbosity bias** (long answers score higher regardless of merit), position
bias (~10–15 points to the first slot), self-preference (10–25% for own family), overconfidence.

🔴 **Verbosity bias is the dominant risk here, and it points the wrong way.** CLAIM-DRIFT lives in tests whose
*prose is excellent* and whose *body is wrong*. **A verbosity-biased judge is anti-correlated with the target.**
Published work confirms LLM-generated tests are riddled with Assertion Roulette and Magic Number smells — LLMs
rate and produce tests **by surface style**.

**Controls to require before trusting a nominator:**

1. 🟢 **Invert the claim-drift prompt.** Never show the name/docstring and the body in a way that lets the model
   grade prose. Instead **hide the body, ask the model to *predict* what it must do from the name alone, then
   diff its prediction against the real body mechanically.** This converts a subjective rating into an objective
   mismatch and structurally defeats verbosity bias.
2. **Force structured output** — a verdict enum **plus a quoted span from the test**. If the span isn't literally
   in the file, discard the verdict. Free hallucination filter. (Only 4 OpenRouter free models support structured
   outputs; Cloudflare and Groq support JSON mode.)
3. **Seed with negative controls.** Inject known-good tests into every batch; a judge that flags them is
   miscalibrated that day. Same trick as the "the CONTROL failed too" catch in the telegram-relay work.
4. **Two models, different families, agreement required** to promote a nomination.
5. Calibrate on a corpus with known bug-catching power (§7.3), not on human taste.
6. Cap the blast radius: a queue of candidates for human review, never a CI status.

**Reusable eval harness:** `promptfoo` (MIT, 24.6k★, active) — side-by-side model comparison and assertion-based
grading, enough to A/B two free models on a labelled sample and measure agreement. ⚠️ `openai/evals` is
`NOASSERTION` on GitHub.

### 6.6 ⚠️ The CLAIM-DRIFT proxy was prototyped, and it over-fires

Rather than speculate, the proposed deterministic proxy was implemented against the real suite:

```
18,938 test functions scanned
 4,091 (21.6%)  name/docstring claims a FAILURE scenario
 1,511          ...of those also patch a collaborator
   935 (61.9%)  ...with NO exception constructed anywhere in the body
```

🔴 **Spot-checking shows a high false-positive rate.** `test_registry_updated_even_on_archive_failure` models
failure as `patch(..., return_value=False)` — perfectly valid, the collaborator returns a failure value rather
than raising. `test_save_json_write_error_raises_handling` writes to a genuinely nonexistent directory, so a
*real* OSError fires inside the code under test — **better** than a mocked one. **The rule as specified flags
both.** An earlier variant ("docstring names a collaborator absent from assertions") produced 222 hits that were
mostly correct tests — patching the named collaborator is often exactly the *right* way to build a failure scenario.

🟢 **The sharp signal is narrower:** the claim promises failure, the collaborator is patched, **and the patch
installs a *success-shaped* return with no `side_effect`** — the notifier isn't down, it's absent. Encoding
"success-shaped" is where the deterministic rule gets hard and where an AI nominator genuinely earns its place.
🟢 **And a free high-precision rule falls out:** `test_save_json_write_error_raises_handling`'s docstring says
*"pytest.raises contract"* but the body contains no `pytest.raises`. **Docstring mentions a pytest API the body
never uses** — cheap, deterministic, precise.

**935 candidates (4.9% of the suite) is the right order of magnitude for an advisory AI pass.**

### 6.7 Cost arithmetic

*(measured from the real corpus: 18,938 test functions, mean 10.7 lines, median 9, p90 20; 9.3 M chars of test
bodies ≈ 2.58 M tokens, **mean 136 tokens per test body** — the suite is **shorter** than the 15–30 lines assumed)*
Per-review budget: 800 in (136 body + ~300 rubric + ~350 context) + 250 out = **1,050 tokens**.
Full sweep 18,938 × 1,050 = **19.9 M tokens**. Triaged sweep (935) = **0.98 M**.

| Route | Cap/day | Full sweep | **Triaged (935)** |
|---|---|---|---|
| **Groq free** `qwen3.8-27b` | 1,000 RPD | 18.9 days | **0.9 days** ✅ |
| **Cloudflare** `qwen3-30b-a3b` | 883 | 21.4 days | **1.1 days** ✅ |
| Cloudflare `gpt-oss-120b` | 235 | 80.5 days | 4.0 days |
| OpenRouter `:free`, no credits | 50 | 378.8 days | 18.7 days |
| **Local 3B Q4** (this laptop) | — | 14.5 days | **17.2 hours** ✅ |

🔴 **A full AI sweep is infeasible on every route (19–34 days of continuous grinding). A deterministically-triaged
sweep finishes in about a day on all of them — or overnight, locally, with nobody else touching the code.**

---

## 7. Anything else that tests the tests

### 7.1 🔴 Fault injection: the Python gap is real, and it doesn't matter

*(verified by downloading the **complete PyPI index — 880,621 package names** — and grepping it)*

| Name | Verdict |
|---|---|
| `pytest-antipatterns` | 🔴 **DOES NOT EXIST** (PyPI 404; GitHub repo search `total_count: 0`) |
| `pytest-fault-injection`, `pytest-chaos`, `pytest-faults` | 🔴 do not exist |
| `failpoint` / `fail-point` / `fail_point` | 🔴 **ZERO matches across all 880,621 packages** |
| `exception-coverage`, `errorinject`, `error-path` | 🔴 zero matches |

🔴 **There is no Python failpoint library.** `fail-rs` (Rust, Apache-2.0, 377★), `gofail` (Go, Apache-2.0, 426★)
and `pingcap/failpoint` (Go, Apache-2.0, 894★) all exist; Java, JS, Ruby and C have one. **Python has none.**
GitHub's `failpoint in:name` returns 17 repos across all languages; the single Python one is a Streamlit ML
web app — a pure name collision.

⚠️ **libfiu** ([blitiri.com.ar/p/libfiu](https://blitiri.com.ar/p/libfiu/), 168★, Ubuntu 24.04 `apt install
fiu-utils python3-fiu`) genuinely does LD_PRELOAD libc interposition with failure points covering exactly the
target list (`posix/io/oc/open`, `posix/io/rw/{read,write}` with `ENOSPC`/`EIO`, `posix/io/net/{socket,connect,
send}`, `posix/stdio/oc/fopen`, malloc). **But:** the fault is **process-wide** — it hits pytest's own imports,
conftest reads and coverage output — and `enable_stack_by_name` scopes by **C** function name, useless for Python
targeting. Its license is the **BOLA "Buena Onda License Agreement v1.1"**, which opens *"I don't like
licenses…"* and states *"this work is to be considered Public Domain"* — effectively permissive but **not
OSI-approved, no SPDX identifier, GitHub reports `NOASSERTION`**. Needs a human ruling under a strict policy.
**The authors' own verdict**, from `bindings/python/fiu.py`: *"For fault injection in Python, a native library
would be more suitable."*

🟢 **None of this matters, because the gap isn't tooling.** `unittest.mock.patch(..., side_effect=OSError)` **is**
library-level fault injection, and this fleet already uses it **1,511 times**. The gap is *systematic
application*: nobody enumerates "every `open()`/`json.load`/socket call in module X" and asks "does a test force
each one to fail?" **That is a checker over your own AST, not a dependency.** libfiu's discipline is the thing
worth stealing, not libfiu.

🔴 **chaostoolkit** (Apache-2.0, 2,020★, active, genuinely not open-core) is **infrastructure** chaos —
Kubernetes/AWS/Azure, JSON experiment definitions, no pytest integration. **Wrong layer.**

### 7.2 🟢 Mutation testing already has exception operators — and this is the actionable find

**cosmic-ray `ExceptionReplacer`** (MIT, active) rewrites the exception **type in an except clause** to a
sentinel:

```
try: raise OSError        →   try: raise OSError
except OSError: pass          except CosmicRayTestingException: pass
```

The handler becomes unreachable. **If the suite still passes, the handler was never exercised.** Registered as
`core/ExceptionReplacer`, isolable with `cr-filter-operators`, scopable with `cr-filter-git`/`cr-filter-lines`.
⚠️ Documented limitation visible in its own `examples()`: **a bare `except:` is left unmutated.**

**MutPy** has the richer pair — **`EHD` ExceptionHandlerDeletion** (handler body → bare `raise`) and
**`EXS` ExceptionSwallowing** (handler body → `pass`). `EXS` is exactly "break the error handling, see if
anything goes red." 🔴 **But MutPy is dead** (last commit 2019-11-17). **Steal the operator design.**

🔴 **Verified negatives, by reading the operator source:** mutmut (16 operators), mutatest (12 categories) and
poodle (12 mutators) have **no exception operator**. And **none of the five has (c) "force a call to raise" — an
exception injected at a call site.** That capability is exactly what `fail-rs`/`gofail` provide for Rust and Go,
and it is absent from Python's mutation tools, from PyPI, and from GitHub.

🟢 **The free tier first, though:** *(measured)* `pytest --cov-branch --cov-report=term-missing` already flags a
never-executed `except OSError:` block. Fault injection is only needed for the harder case — *the except block
runs, but nothing meaningful is asserted*.

🔴 **Disable `flaky` and `pytest-rerunfailures` during audit runs** (`-p no:rerunfailures`, `--reruns 0`) — they
rerun failing tests until green, which is the exact mechanism that hides "the code is broken but the suite is
green." **Keep `pytest-timeout` on**: injected faults frequently cause *hangs* rather than exceptions, and
without a timeout the audit run wedges.

### 7.3 🟢 The calibration corpus — SWE-bench is the answer

This was chased hardest, because a corpus of known-real bugs is the only thing that turns the checker from
opinion into measurement.

| Corpus | Code license | **Dataset license** | Size | Verdict |
|---|---|---|---|---|
| **SWE-bench** | **MIT** (harness) | ⚠️ **undeclared on HF** | 2,294 test / 225 dev / 19,008 train | 🟢 **Best fit** |
| SWE-bench Verified | MIT | undeclared | 500 human-validated | 🟢 |
| **SWT-Bench** | **MIT** | — | SWE-bench-derived | 🟢 88★, pushed 2026-07-23 |
| **TDD-Bench-Verified** (IBM) | **Apache-2.0** | — | **449 instances** | 🟢 pushed 2026-07-21 |
| **BugsInPy** | 🔴 **NONE** | 🔴 **NONE** | **501 bugs, 17 projects** | ⚠️ unlicensed |
| **TestGenEval** (Meta) | 🔴 **CC-BY-NC-4.0** | NonCommercial | 1,210 file pairs, 11 repos | 🔴 excluded if commercial |
| Defects4J | MIT | — | 854 bugs | Java only |

🟢 **SWE-bench is the most valuable single find in this report.** Every instance carries:
- **`FAIL_TO_PASS`** — *"tests resolved by the PR and tied to the issue resolution"*: **tests that provably fail
  on buggy code and pass on fixed code.**
- **`PASS_TO_PASS`** — **tests that pass in both states: tests that provably do NOT catch this bug.**
- plus `base_commit`, `patch`, `test_patch`, `environment_setup_commit`.

**That is a ready-made, labelled, all-Python ground truth for exactly this question. The calibration protocol
writes itself:**
- Run the checker over `FAIL_TO_PASS` tests. These *demonstrably* catch a real bug. **Any of them the checker
  calls weak is a measured false positive.**
- Run it over `PASS_TO_PASS` for the same instance. These demonstrably miss *this* bug. The checker should not
  rate them higher.
- **The gap between the two distributions is a single honest number for checker quality** — reproducible, and
  defensible to a skeptic.

⚠️ **The licensing caveat, stated plainly:** none of `princeton-nlp/SWE-bench`, `SWE-bench_Verified` or
`SWE-bench_Lite` declares a license field on HuggingFace. **Mitigation:** the instances are just
`(repo, base_commit, test_names)` tuples pointing at public OSS repos (django, sympy, scikit-learn, pandas —
each with its own OSI license). **Use the MIT harness plus the public commit SHAs to reconstruct locally, relying
only on each upstream project's own license, and never redistribute the compiled dataset.** That is a question
for a human, but the path exists.

⚠️ **BugsInPy** (501 bugs across pandas=170, keras=45, youtube-dl=43, scrapy=40, luigi=33, thefuck=32,
matplotlib=30, black=23…, with built-in `bugsinpy-mutation` and `bugsinpy-coverage` commands and a Dockerfile)
would be ideal **but has no license file at all** — probed `LICENSE`, `LICENSE.md`, `LICENSE.txt`, `COPYING`, all
404. Under default copyright that is all rights reserved.

⚠️ **One corpus left UNFINISHED, reported rather than guessed at: BugSwarm.**
A follow-up agent was researching **BugSwarm** (fail-pass build pairs mined from CI) when it began pulling
multi-gigabyte reproduction containers on this laptop; **I stopped it before it reported.** Its license,
Python coverage and per-instance test labelling are therefore **unverified here** — nothing about BugSwarm is
claimed in this doc. It is the obvious next thing to check if SWE-bench's undeclared dataset license blocks the
calibration plan. *(Two container images, 28.7 GB total, were pulled to this machine at 19:17 and 19:34 today by
that agent — flagged in §9.)*

🟢 **And a corpus that costs nothing and starts today:** the `PASS_TO_PASS` pattern generalizes. **For any bug
fixed in AIPass, record which tests went red.** Tests that never go red for any real bug are earning nothing —
a measurement accumulable for free from your own git history.

🔴 **Other negatives worth recording.** **MutantBench** (GPL-3.0) — grepping its RDF shows **19 Java + 18 C
programs, zero Python**, and it targets the Equivalent Mutant Problem, not suite effectiveness.
**Inozemtseva & Holmes (ICSE 2014)** — the artifact page now returns **HTTP 410 Gone** and the domain is parked
and for sale; a Wayback CDX sweep shows only paper/figures/video ever existed. **No coverage-vs-effectiveness
corpus was ever published.** The **JNose accuracy dataset** (CC-BY-4.0) is the only true manual-vs-tool ground
truth found in any language — **Java**. **There is no accepted benchmark for evaluating test-quality tools, in
any language.**

**Flakiness corpora, if needed:** 🟢 use **Gruber et al.** (Zenodo `10.5281/zenodo.4450435`, **CC-BY-4.0**,
876,186 tests, plus **100 human-classified flaky tests by root cause**), **not IDoFT** — IDoFT does have Python
(1,618 labelled tests, 343 projects, actively maintained) but **has no license**, and ~50% of its Python entries
point at repos that are archived, deleted or unmaintained.

### 7.4 Test impact analysis — the framing changes the answer

| Tool | License (verified from LICENSE) | Latest | State |
|---|---|---|---|
| **pytest-testmon** | **MIT** core | 2.2.0 (2025-12-01) | Alive; ⚠️ `--tmnet` swaps local SQLite for a **proprietary unpublished hosted backend** — MIT core, open-core-adjacent. ⚠️ Watch out for `pytest-testmon-dev` on PyPI, which declares **AGPL** |
| pytest-picked | MIT | 0.5.1 (2024-11-06) | alive |
| pytest-incremental | MIT | 0.6.0 (**2021**) | 🔴 officially deprecated |
| pytest-split | MIT | 0.11.0 (2026-02-03) | healthy |
| diff-cover | Apache-2.0 | 10.5.1 (2026-08-16) | very active — but **saves zero seconds**; it reports coverage on the diff |

🔴 **testmon's blind spot is disqualifying for AIPass specifically.** Its `is_python_file()` is literally
`file_path[-3:] == ".py"`. **Changes to JSON, YAML, TOML or fixture data are invisible** — affected tests will not
re-run. This architecture is dense with JSON state (`.trinity/*.json`, `provider_manifest.json`,
`switch_state.json`). **Testmon would not have re-run a single test for a manifest edit — and a manifest edit is
exactly the bug class that produced the 508-message telegram relay incident.** Also `check_data_version()` does
`os.remove(datafile)` on schema mismatch, so upgrading testmon silently costs a full run.

🟢 **And the framing that changes the answer:** 18,042 tests in 514 s is **~28 ms/test**. Much of that wall time
is *fixed overhead* — ~17 interpreter startups, imports, collection — not execution. **TIA only compresses the
variable part.** Selecting 400 tests does not give you 11 seconds; it gives you the floor set by 17 pytest
startups. **The marginal return of true TIA here is lower than it looks; the correctness risk is not.**

Ranked for per-PR use: **(1) sub-project gating on changed paths** (`dorny/paths-filter`, MIT, or a plain Actions
matrix) — 8m34s → ~30–90 s for a single-branch PR, high soundness, auditable, no coverage tracing, and the 17
sub-projects are already the natural boundary. **(2) `-n4 --dist loadfile`** — zero soundness risk, already
installed. 🟢 **Free adjacent win: every `pytest.ini` in the fleet carries `addopts = -v`** — that's 18,042
formatted lines to a terminal nobody reads on CI. **(3) pytest-split** across a runner matrix. **(4) testmon on
dev laptops only, never as the sole gate.**
**Guardrails for any selector:** the full fleet stays the merge gate; force a full run on
`conftest.py`/`pytest.ini`/lockfile/**manifest** changes; and **fail open** — a selector that fails closed
produces exactly the invisible-green failure this lane exists to prevent.

### 7.5 Suite reduction — do not auto-delete

🔴 **The academic warning is stark.** Rothermel et al.: minimized suites achieved ~**80% size reduction while
losing ~48% of fault-detection effectiveness**. Wong et al.: 9–68% reduction for only 0.19–6.55% loss.
**The spread between those two results *is* the finding** — reduction is sometimes nearly free and sometimes
catastrophic, and you cannot tell which without measuring fault detection. **Report advisory only, never
auto-delete.** (See §2.6 for the measured duplicate picture and the constant-folding trap.)

---

## 8. Shortlist

### 8.1 🟢 Top 5 adoptable now

**1. `sys.addaudithook` write-gate — stdlib, PSF, ~40 lines, measured 0 CPU overhead.**
Exact node-id attribution, **catches modification** (the AUDIT-FORGERY case `pytest-litter` passes), and the same
hook covers network and flags `subprocess.Popen`. Layer it: audit hook every run → per-suite snapshot diff with
`(path, st_mtime_ns, st_size, st_ctime_ns, st_ino)` as the C-extension/subprocess backstop (31 s, not 4½ h) →
Landlock behind a flag → **a canary that must be caught on every run.** *Highest value, lowest cost in the entire
report, and it upgrades taxonomy rule #1 rather than replacing it.*

**2. Coverage contexts + a ~40-line query script — Apache-2.0 + MIT.**
`--cov-context=test`, ~13 min for one fleet map at `-n4` *(measured 1.5×)*, then per-module gutting at ~20 s
instead of 514 s. **A 400-module sweep goes from ~57 hours to ~2¼ hours.** The full loop was built and run
end-to-end and found exactly the two planted weak oracles out of three tests.
🔴 **Handle the subprocess-attribution gotcha explicitly (§5.1#2) — it is the one that will bite this fleet hardest.**

**3. `mutmut 3` pinned to `main`, `--max-children 2` — BSD-3-Clause.**
The only Python engine whose architecture defends against the campaign's own instrument species: the trampoline
makes FALSE-LANDING structurally impossible for aliased imports, running against `mutants/` makes
CONCURRENT-HARNESS impossible, and **`importlib.reload` cannot resurrect a healthy binding** (this tree has 113
reload sites). `main` not 3.7.0 because the release skips every decorated class. **Leave
`mutate_only_covered_lines` off**, treat every ⏰ as unscored, and verify the `skills` test-to-mutant association
before quoting any number for it. Pair with **cosmic-ray as a component, not a runner** — `cr-filter-git` is the
only free OSS diff-scoping primitive in Python, and `cosmic-ray baseline` is the negative control.

**4. `typeguard` (`--typeguard-packages=aipass`) + `dirty-equals` — both MIT, both ~one line.**
typeguard turns all 18,042 existing tests into return-type-checking runs: **a gutted function annotated `-> str`
returning `None` raises regardless of what the test asserts.** dirty-equals kills TYPE-ONLY and structurally
cannot MIRROR-EXPECT. Set `collection_check_strategy = ALL_ITEMS`, measure the wall-time delta, and **ship a
control test that must fail before trusting either.**

**5. Ruff's `PT` family on test paths — MIT, measured 0.96 s CPU on this fleet.**
`PT`, `B011`, `B015`, `B018`, `F631`, `PLR0124`, `PLR0133`, `PLW0129`, `S110`, `S112`, `SIM105`.
**Explicitly `ignore = ["S101"]` on tests** (30,777 hits — the inverse of the goal), exclude
`spawn/templates/citizen/`, and investigate the 12 files Ruff cannot parse. **The 84–94 `PT011` hits are the real
prize** — `pytest.raises(OSError)` with no `match=` passes for *any* OSError from *any* line: "green while
production is broken differently," deterministic and free today.
*Runners-up worth the same breath:* **`pytest --reverse` nightly** (12 lines of MIT source, one extra full run,
**~47% OD yield vs 2.7%**), **`pytest-randomly`** for its subset-order stability, **`detect-test-pollution`**
scoped per-suite, and **`pytest-replay`** recording on every run.

### 8.2 🟢 Top 3 ideas worth stealing without adopting the tool

**1. Split every mutant kill by exception type — `AssertionError` vs everything else.**
Two independent studies say a raw mutation score will lie: **45% of kills are implicit** (Schuler & Zeller) and
"killed by assertions" ranged **28–73%** (Zhang & Mesbah). **It will lie more in Python**, where duck typing and
`None`-propagation raise on far more mutants. pytest gives the split for free; **nobody has published it for
Python.** This is the guard-rail that stops the lane from certifying assertion-free tests as well-tested, and it
is a necessary qualification of law L0 — *mutation is the ground truth for "can this test fail," not for "does
this test's oracle do the work."*

**2. Extreme mutation at function granularity, under its published name.**
`gut.py` is already an extreme-mutation harness — at *module* granularity where the literature uses *function*
granularity. Descartes measures **~10× cheaper and ~10× fewer mutants** than operator mutation, and its output
taxonomy — **pseudo-tested / partially-tested / tested, per function name** — is far more actionable than a
line-level survivor list. It also covers the **statement-deletion gap** both mutmut and cosmic-ray leave open
(SBR is 68% of Google's mutant volume and their most productive operator at 84.1%). It has a citable name
(**pseudo-tested methods**, EMSE 2018), **does not exist in any Python tool**, and Pynguin's MIT
`assertion/mutation_analysis/` is a better starting point than greenfield. **Refactoring `gut.py` to per-function
is likely a higher-value week than adopting any tool in this report.**

**3. Google's cost model — diff-scope, one mutant per changed covered line, then arid nodes — in that order.**
Two levers before any execution optimisation: **820 → 77 → 7 median mutants per changelist (≈99.15%)**. At this
fleet's commit sizes that is the difference between a 50-hour run and a **3.3-minute** one. The gap to close is
~50 lines of glue (`git diff` → changed lines → enclosing function names → `mutmut run "pkg.mod.x_func*"`;
cosmic-ray has the filter but the wrong engine, mutmut has the right engine but no filter). Then arid nodes,
**with the transitive clause** — a compound node is arid iff all its parts are arid, which kills an entire
`if DEBUG: log(...)` including its condition. Start with their three highest-yield categories — **logging,
time/deadline/backoff, configuration flags** — and note that **string-literal mutants are 42.8% of this fleet's
mutant population**, so one regex roughly halves the bill. **Suppress at generation time, never at display time**,
and take their bias: *"we have had much more important improvements from unsound heuristics."*
Ride along free: **PIT's `EquivalentReturnMutationFilter` rule** (before emitting "replace X with Y", check
whether X already *is* Y — this is the NO-OP-MUTANT species solved in Apache-2.0 code), **TCE in ~20 lines of
`dis`** (do the *duplicate* half first — 3× more numerous than equivalents), and **kill-vector collapse** so 200
survivors on one function present as 3 problems.

---

## 9. Honest caveats

- **Wall-clock benchmarks were taken on a heavily loaded machine** (five research agents running concurrently).
  **CPU-time deltas and ratios are sound; absolute wall times are pessimistic.** Re-measure the fork-per-test,
  pytest-startup and coverage-context numbers on an idle box before committing to a schedule.
- **Two agents measured Ruff `PT` hits at different numbers** (127 vs 134 `PT018`; 84 vs 94 `PT011`) because they
  scoped different file sets. **Re-measure with a pinned scope before quoting either.**
- **Two agents read OpenRouter's free-tier data policy differently** (§6.1). The disqualifying reading is
  reported, with its own sourcing weakness flagged. **Verify in Settings → Privacy before sending code.**
- The **"10 covering tests per mutant"** assumption underpinning every mutmut cost figure is **unmeasured**. Run
  the stats phase on `canary` (~3 min) first.
- The **branch + contexts `-n4`** figure (~2.4×) is extrapolated from synthetic runs; the real `-n4` branch runs
  were too noisy to trust.
- **DB size at fleet scale (~50–100 MB line, ~5× branch)** is extrapolated from a 50-file subset, not measured.
- **Scratch left on this machine by the research fleet:** `docker pull` of `bugswarm/cached-images`
  (`getnikola-nikola-366580817` 15.9 GB, `AntonLydike-riscemu-14023981409` 12.8 GB) — **28.7 GB, pulled today**
  by the corpus agent I stopped. Not deleted without a ruling since re-pulling costs the same bandwidth;
  `docker rmi bugswarm/cached-images:getnikola-nikola-366580817 bugswarm/cached-images:AntonLydike-riscemu-14023981409`
  reclaims it. Disk is not tight (172 G free, 61% used).
- Licenses and free-tier limits change. Everything here was read on **2026-08-29**; primary sources are linked
  throughout so any claim can be re-checked rather than re-researched.
- **`TAXONOMY.md` moved to revision 2 while this research ran.** Nothing in this doc was written against
  revision 2's changes; **read the taxonomy, not this doc, for any species verdict.** This doc is external input
  only — no file outside `aipass/docs/` was touched.

---

*Research: 5 sub-agents + their own nested sub-agents, ~840k subagent tokens, ~630 tool calls, all foreground.
Every license read from a `LICENSE` file or PyPI `license_expression`; every maintenance date from the GitHub API
on 2026-08-29; measured figures run on this machine and against this fleet. No file outside this branch was
modified.*
