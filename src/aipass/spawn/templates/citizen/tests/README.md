# Tests

Pytest unit tests for `{{BRANCHNAME}}`.

- `conftest.py` — Shared fixtures: temp dirs, sample data, a capturing logger, an
  isolated `JsonHandler`, and an autouse guard that repoints this branch's
  json_handler singleton at a tmp dir so tests never write into `{{BRANCH}}_json/`.
- `test_cli_routing.py` — Starter suite for the entry point: no-args introspection,
  `--help`/`-h`/`help`, `--version`/`-V`, subcommand `--help` (never executes the
  command), and the unknown-command refusal exiting non-zero.
- `test_json_handler.py` — Starter suite for the JSON handler shim: provisioning,
  defaults, validation, load/save round-trips, log rotation, and error resilience
  (missing, corrupt and empty files).
- `test_scaffold.py` — Smoke test proving pytest infrastructure works here.
- `test_*.py` — Your own tests. Custom tests cover branch-specific domain logic.

The two starter suites are yours to replace as this branch grows its own — they
ship at birth so a newborn is not born failing its own standards gate, and they
are listed in the template's `.spawn/.registry_ignore.json` so a mature branch
that has moved past them is not marked structurally incomplete for dropping them.
