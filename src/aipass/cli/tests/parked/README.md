# tests/parked/ — code that is kept, not run

A park is a tracked home for code we deliberately stopped running but may want back.

**Why here and not `.archive/`.** Patrick's ruling, 2026-08-18, fleet-wide: `.archive/` is
always ignored, no exceptions, and it is his disposal zone — cleaned without warning. Bytes
kept there do not ship in a clone and are not safe from cleaning, so "archived, revivable"
said about an `.archive/` directory is a promise only this machine is keeping. This park was
first archived (03:43 the same day, before the ruling landed at 19:29) and moved here after,
same pattern @api and @memory used to rehome theirs.

**The `(disabled)` suffix, and the part that actually matters.** `scaffold(disabled).py` used
to be `test_scaffold.py`. Dropping the `test_` prefix is what keeps pytest's
`python_files = test_*.py` from matching it; the `(disabled)` suffix is a naming habit on top,
not the enforcement. `conftest.py` in this directory is the real barrier
(`collect_ignore_glob = ["*"]`), pinned by `../test_parked_is_not_collected.py` so the
guarantee is proven by running collection, not inferred from the filename.

| Park | Ruling | What it holds |
|---|---|---|
| `scaffold(disabled).py` | @cli, DPLAN-0304 item 4, 2026-08-18 | The spawn/seedgo template's scaffold smoke test — see below |

## scaffold(disabled).py

A spawn/seedgo TEMPLATE file, shipped to every new branch. Its job is to prove pytest
infrastructure works in a branch that still has the template conftest.

In @cli it never ran. It resolves `temp_test_dir` and `sample_test_data` through
`request.getfixturevalue`; this branch's conftest replaced the template one long ago, so it
took its own skip path on every invocation: 27 lines, zero assertions executed, one permanent
`1 skipped` in the summary wearing a test's name.

**Ruling.** Parked rather than rewired. Making it run would mean adding `temp_test_dir` and
`sample_test_data` to this branch's conftest purely so this test could assert they exist —
fixtures whose only consumer is the test that asserts them. That is circular, and it would put
a template's smoke test in front of 177 real ones. What it set out to prove — that pytest
works here — is proven many times over by the real suite.

**Not a criticism of the template.** In a fresh branch the file is correct and useful; the
skip path is deliberate and well-commented. The narrow finding is that a permanently-skipping
test should not keep a slot in a branch with a real suite. Raised with @seedgo (their wave-2
sweep) and reported to @devpulse.

**Restore** with `mv "tests/parked/scaffold(disabled).py" tests/test_scaffold.py` (drop the
`(disabled)` suffix, put the `test_` prefix back) if this branch ever loses its own conftest.
