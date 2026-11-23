You are the second reviewer on a map of <TARGET NAME>. A first pass by <N> agents produced <COUNT> items describing every action the target performs. Your job: find what they MISSED and what they got WRONG. You change nothing on disk; read-only.

Read first:
1. <DIR>/brief.md (the contract the first pass followed: item shape, what counts as an action, the FLUFF? convention)
2. <DIR>/items.json (the <COUNT> items; `items[]` and `summaries[]`)

Then read the code, all of it, in this order, and tick off every function, flag, branch of behaviour, file write, subprocess call, prompt to the user, and printed banner against the items:
- <entry point and handler files>
- <module files, naming the big ones and their line counts>
- <shared helpers>
- <scripts outside the target that it reaches: setup script, launcher>
- <prompts, README, docs/*.md>
- <runtime config files: what they control, who reads them>
- tests/*.py (what each pins; count `def test_` lines; do not run them)
- Who calls the target from outside: grep <REPO ROOT>/src (skip any .archive) and the repo root (Dockerfile, .github/workflows, pyproject.toml entry points, setup scripts) for <the target's command spellings and import door>.

Report ONLY as the final message, JSON matching the schema you were given:
- `missed`: actions with no item in items.json. Same shape as the brief's items; ids `X01`, `X02`, ... in reading order. Be exhaustive: an action is anything a user or the system can trigger, each flag that changes behaviour, each step of a multi-step flow, each file write, each interactive prompt, each subprocess, each printed banner or hint, each hook or schedule or CI caller, each helper another branch imports. Flag hand-holding with the word FLUFF? in `note`.
- `corrections`: items whose `does`, `touches`, `file`, `tested_by` or `note` is wrong or materially incomplete against the code. Give `id`, `field`, `was` (short quote), `should_be`, `why` (the code line or fact).
- `summary`: 3-6 plain sentences: how complete the first pass was, where it was thin, and the two or three things the owner most needs to know that the first pass did not say.

Rules: never run <FORBIDDEN COMMANDS>, or anything that writes. `<ENTRY> --help`, `<ENTRY> <cmd> --help` and read-only verbs are fine. No test runs. No git commands. Plain English in `does`, no code in prose.
