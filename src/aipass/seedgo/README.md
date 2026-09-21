[<- Back to AIPass](../../../README.md)

# SEEDGO

**Purpose:** Standards compliance platform for AIPass. Scores every citizen branch against a pack of code standards, runs the per-file gate that fires after each edit, certifies its own pack, measures how much a test suite proves, and measures what a greeting costs.
**Module:** `aipass.seedgo`
**Version:** 2.1.0
**Created:** 2026-03-05

---

## Quick Start

```bash
drone @seedgo audit aipass @flow        # Score one branch against the standards pack
drone @seedgo checklist <file>          # One file, every eligible standard
drone @seedgo standard cli              # Look up what a standard actually checks
```

---

## What It Does

- **Scores branches** against the `aipass_standards` pack — architecture, imports, logging, naming, silent catch, deep nesting, gateway boundary and the rest — and reports each violation with the file and line behind it.
- **Gates every edit.** The PostToolUse hook runs the per-file checklist on whatever was just written, so a violation is answered while the author is still there.
- **Answers "what does this standard mean?"** from queryable content beside each checker, so nobody has to read the checker to comply with it.
- **Judges test suites**, statically and by running them under a write gate, and says out loud what each reading cannot see.
- **Measures the startup cost** of every branch's grounding files against the caps their owners publish.
- **Certifies its own pack** — and reports honestly that it does not currently pass.

Not runtime monitoring (that is prax), not deployment, and never a writer of other branches' files.

---

## Live Inventory

The list of modules, packs and commands is **generated from the code that runs them**, so it
is never written down here and never stale:

- `drone @seedgo` — the self-map: every discovered module with its one-line description, every
  checker pack with its checker count, the version.
- `drone @seedgo --help` — the full command surface: every verb, its arguments and its flags.

---

## How To Reach Me

- Mail: `drone @ai_mail email @seedgo "Subject" "Body"` — standards questions, a checker you
  believe is wrong, a rule you want added.
- A false positive is a bug in the checker, not a fault in your branch. Say which file and
  which standard, and the claim gets reproduced here before anything is argued.
- A genuine exception is a bypass entry with a written reason, not a silenced rule.

---

## Commands

There is no command list on this page, deliberately: a hand-typed copy of the branch's own
help output rots the next time a verb is added. The generated surface is the one above under
**Live Inventory**, and it is always current.

---

## Architecture

Three layers. `apps/seedgo.py` is a thin router: it discovers modules, dispatches to the first
one that claims a command, and turns a refusal into an exit code. `apps/modules/` holds one
business-logic module per verb — audit_tests, checklist, diagnostics_audit, inbox_audit,
inventory, permissions, proof_query, readme_update, seedgo_proof, shadow_cycle,
standards_audit, standards_query and test_map. `apps/handlers/` holds the implementation,
grouped one directory per concern: the checker packs (`*_standards/`), the proof pack, the
audit engine, the bypass and ignore systems, the test lanes, and the json shim every branch
shares.

The full directory tree lives in this branch's own prompt
(`.aipass/aipass_local_prompt.md`) — one place, so it cannot disagree with itself.

---

## Documentation

Depth lives in [docs/](docs/), one file per module or handler group:

| Doc | What it covers |
|---|---|
| [docs/aipass_standards.md](docs/aipass_standards.md) | The scored checker pack: the standards table, how a rule is added, the `ruff`/`ruff_check` split |
| [docs/pytest_quality.md](docs/pytest_quality.md) | The v5 test-quality rules, and why they score without gating |
| [docs/context_standards.md](docs/context_standards.md) | The startup budget: which files, which caps, which owner publishes each |
| [docs/audit_engine.md](docs/audit_engine.md) | Discovery, scoring, the incremental cache, the info channel, bypass and `.seedgoignore` |
| [docs/checklist_and_hooks.md](docs/checklist_and_hooks.md) | The per-file lane and the hook that runs it |
| [docs/proof_and_coverage.md](docs/proof_and_coverage.md) | Proof certification, coverage mapping, the test inventory, the weekly cycle |
| [docs/test_gold_standard.md](docs/test_gold_standard.md) | What a good test is here, when NOT to write one, and how a justified pass is declared |

---

## Integration Points

### Depends On
- `aipass.cli` — Rich console and header formatting
- `aipass.prax` — structured logging, and the json service the local shim binds
- `aipass.drone` — branch resolution via `normalize_branch_arg`
- Python stdlib: `pathlib`, `ast`, `importlib`, `json`, `re`

### Provides To
- Every branch — standards scoring, content queries, and the per-file checklist the
  PostToolUse hook consumes
- `aipass.drone` — routed by drone's `generic_adapter.py` from `routing_config.json`; this
  branch ships no `drone_adapter.py`, and no branch in the fleet does

---

**Last Updated:** 2026-09-15

---
[<- Back to AIPass](../../../README.md)
