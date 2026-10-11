# Tests

Pytest unit tests for `{{BRANCHNAME}}`.

- `conftest.py` — Shared fixtures: a capturing logger, and an autouse guard that
  points this branch's json writes at a tmp dir so tests never write into
  `{{BRANCH}}_json/`. Use pytest's own `tmp_path` for a scratch directory.
- `test_cli_routing.py` — Starter suite for the entry point: no-args introspection,
  `--help`/`-h`/`help`, `--version`/`-V`, subcommand `--help` (never executes the
  command), and the unknown-command refusal exiting non-zero.
- `test_scaffold.py` — The handler guard's structural pin: it never walks `inspect.stack()`.
- `test_*.py` — Your own tests. Custom tests cover branch-specific domain logic.

The starter suite is yours to replace as this branch grows its own — it ships at
birth so a newborn owns real, readable tests from day one, and it is listed in the
template's `.spawn/.registry_ignore.json` so a mature branch that has moved past it
is not marked structurally incomplete for dropping it.

A JSON-handler starter suite shipped here until 2026-09-07. It was retired
(FPLAN-0492) because its six shim-pin checks now live once in @seedgo's json
handler contract suite, which discovers every branch's shim by walking the
installed package — this branch is covered by that run without carrying a copy.
