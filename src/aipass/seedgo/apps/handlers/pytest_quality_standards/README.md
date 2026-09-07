# pytest_quality — test_quality v5

> A test earns its place by pinning a defect or a contract whose breach breaks a
> caller. This pack judges what a test **proves**, not what strings it contains.

**Pack key:** `pytest_quality` · **Kind:** scoring · **Status:** shadow (scores, gates nothing)
**Design:** DPLAN-0323 / FPLAN-0469

```bash
drone @seedgo audit pytest_quality @flow    # score one project
drone @seedgo audit pytest_quality          # score the fleet
```

---

## Why this pack exists

The standard it replaces — `aipass_standards/test_quality` v4 — scored a project by
searching its test files for 99 pattern substrings. The match was a bare `in` over
raw source text, so **comments and docstrings counted**. A file containing nothing
but those pattern strings — no code, no tests, no assertions — scored 94%.

It was also not optional. The raw percentage became the standard's score, that score
entered the branch average, and CI gates that average at 100. So every branch was
pushed to 51 of 51 pattern items. That is why `importlib.reload` appears in eighteen
of eighteen branches: not drift, not sloppiness — **compliance**. The checker asked
for strings, so it got strings.

The design was the defect. This pack is the correction.

## What is different

| v4 | v5 |
|---|---|
| substring match over raw text | AST, every time |
| comments and docstrings score | only code counts |
| 51 pattern items, all mandatory | eleven independent rules |
| one number, no evidence | every flag carries its nodeid, line and calls |
| gated the board at 100 | **advisory** — reports, never fails |
| AIPass-specific | generic: stdlib-only, lifts onto any Python project |

## The rules

| Rule | Asks |
|---|---|
| `no_oracle` | does this test verify anything a reader can see? |
| `assertion_shape` | is the assertion vacuous — a tautology, a bare literal, `len(x) >= 0`? |
| `unentered_assert` | can this assert silently never run? |
| `capture_never_read` | is a captured value asserted on, or just captured? |
| `empty_parametrize` | does this table have cases, or does the test never run? |
| `mock_drift` | does the patched target still exist in production? |
| `self_skip` | does this test skip itself into permanent silence? |
| `posix_literal` | does this test hardcode one platform's path shape? |
| `entry_point_diff` | does production declare a verb no test names? |
| `coverage_slot` | does this test confess, in prose, to existing for coverage? |
| `docstring_pin` | does the docstring name a symbol the test actually calls? |

## Two design commitments

**Generosity in the flagging direction.** A false flag costs a reader thirty
seconds; a missed one costs nothing visible. Every rule here is deliberately
generous, and each one's `.md` says where it is wrong on purpose.

**It nominates, it does not convict.** Static reading cannot tell a weak oracle
from an absent one, or a deliberate smoke test from an accident. No rule here says
a test is worthless. Each says: here is what I could not see, and here is the
evidence. A human decides. Nothing in this pack deletes anything.

## `docstring_pin` ships unscored, on purpose

The rule "every test's docstring must name the defect it pins" was accepted **only**
in a structural form: the docstring must name an importable symbol the test actually
calls. A prose match — scoring on words like *pins*, *contract*, *regression* —
would be the v4 defect one level up, satisfiable by writing "Pins the contract that
X" and nothing else.

Even structurally, it currently measures 89.8% of the fleet's tests as unanchored.
So it defaults to `SCORED = False`: it publishes the full violation list and the
measured number, and reports 100. Gating on it today would fail all eighteen
branches on day one, which is how a standard teaches people to game it.

## Classify and return — the third disposition

A caught exception has three honest dispositions, not two. The usual pair is *log
it* or *re-raise it*. This pack cannot log — being stdlib-only is the property that
makes it portable, and a framework logger would end that. So it does the third
thing: **it classifies the failure and returns the reason to a caller that must
render it.**

`corpus._parse` catches a syntax error and returns `(None, "SyntaxError: ...")`.
`build` records it in `unparseable_reasons`. Every rule surfaces it as a check line
naming the file as **not measured**. The error reaches the human reading the
report, which is strictly louder than a log entry nobody greps.

This matters beyond style. A rule that says *"production declares `purge-all` and
no test names it"* is only honest if it can also say *"and four production files
were unreadable"* — a hole and an unread file look identical from the outside.
Rules that read production must surface `production_limits()`. A broken file must
never read as a clean one, and an absent measurement must never read as a zero.

*The `silent_catch` standard in `aipass_standards` models only log-or-re-raise, so
this pack currently carries a bypass for it. When that standard learns the third
disposition, the bypass dies.*

## Scoring

Score is `clean_units / total_units * 100`, **deduped per unit** — a unit with three
findings costs one unit, not three, or the score goes negative.

A project with no test files reports `not_applicable`, never 0. Zero tests measured
is not zero quality found: a 0 would blame a project for a fact about its layout,
and a 100 would claim a measurement that never happened.

## What is NOT here

`ruff_pt` was not ported. It shells out to the `ruff` binary via `subprocess` and
imports the framework logger, so it is an **execution** check, not a static one.
Forcing it in would end this pack's stdlib-only property for one rule that
duplicates what `ruff` already does in CI. It stays in `tests_pytest_standards`,
where an execution pack is the right home for it.
