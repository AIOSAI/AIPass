[<- Back to the README](../README.md)

# Docs

Tracked public reference for the `seedgo` branch — the **depth** layer of the DPLAN-0347
contract: one file per module or handler group, each small enough for one read, each linked
from the branch README, opened when something breaks.

Work in progress, research and dated one-offs belong in `docs.local/`, not here. Anything on
this shelf is committed — write it as if it ships.

| File | What it covers |
|---|---|
| [aipass_standards.md](aipass_standards.md) | The scored checker pack: the standards table, how a rule is added, the `ruff`/`ruff_check` split, the fleet json shim |
| [pytest_quality.md](pytest_quality.md) | The v5 test-quality pack — the AST rules, and why it scores without gating |
| [context_standards.md](context_standards.md) | The startup-budget pack: the six startup files, their caps and their owners |
| [audit_engine.md](audit_engine.md) | Discovery, scoring, the incremental cache, the info channel, bypass and `.seedgoignore` |
| [checklist_and_hooks.md](checklist_and_hooks.md) | The per-file checklist lane and the PostToolUse hook that runs it |
| [proof_and_coverage.md](proof_and_coverage.md) | Proof certification, `test_map`, `test-inventory`, `audit-tests`, the weekly shadow cycle |

The live inventory of modules, packs and commands is not written down here — it is
`drone @seedgo` and `drone @seedgo --help`, generated from code.
