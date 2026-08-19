"""Nothing in this directory is a test. The barrier that makes that true.

The park's own convention — the house `(disabled)` suffix instead of a `test_`
name — is what keeps `host_terminal_capture_lane(disabled).py` out of pytest's
`python_files = test_*.py`, and it works: this directory contributes zero
collected items today, verified from the repo root.

@memory proved that convention is NOT self-enforcing (2026-08-19): a file that
keeps a `test_` prefix is collected no matter what suffix it also carries, and
theirs was. The suffix is a naming habit; this is a rule. Both are kept because
they fail differently — the habit keeps the file readable as parked, the rule
holds even when someone renames it back.

`collect_ignore_glob` is pytest's own door for exactly this, and it is scoped to
the directory the conftest lives in, so it can never quiet a real suite next
door. Pinned by test_parked_is_not_collected.py, which fails if this file stops
working rather than if it stops existing.
"""

collect_ignore_glob = ["*"]
