# Known issues

**Branch** hooks · **Code** across `apps/`, one row per open item
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

What is open, and what is *stated* rather than fixed. Each row carries the measurement behind it and
the date it was taken — a claim with no date is a claim nobody can check. Rows that closed are not
kept here: their record is the plan that closed them (FPLAN-0495, FPLAN-0513, DPLAN-0325,
FPLAN-0593). The live state of this branch is `drone @hooks status` and `drone @prax dashboard`, never
this page.

---

## Open

| Item | State |
|---|---|
| The git-gate allow-list refuses 8 measured ordinary read verbs (`tag`, `branch`, `remote`, `config --get`, `stash list`, `reflog`, `worktree list`, `notes list`) | Open — whether the list should grow is a code decision, not made in a doc pass. Measured 2026-09-05; surprised @devpulse live on `git tag --sort` |
| `testwrite_gate` has false-fired across the DPLAN-0325 campaign: it reads a path-shaped *argument* of a read-only command (a pytest target, a `cd`-compound resolved against the wrong cwd) as a new test file | Open, reported by @devpulse 2026-09-04, queued |
| `git_gate` false-fired on a **heredoc mail body**: `RAW_GIT_RE` scans command text after stripping *quoted* strings, and a heredoc body is not quoted, so prose containing "git" blocked an `ai_mail` reply | Open, reported by @devpulse/@seedgo 2026-09-04, queued. The cure is to reuse `bash_writes`' reader; it awaits the owner |
| `engine._log_detail()`'s env switch predates prax gaining `logger.debug()`; folding one onto the other is unstarted | Open cleanup |
| Bare `drone @hooks test` prints the module blurb and fires nothing (`apps/modules/hook_test.py`, the `if not args` branch). The documented command does not do the documented thing; the run needs an argument such as `--verbose` | Open — reported to @devpulse 2026-09-06, a behaviour change outside the doc scope |
| `.claude/provider_manifest.json` pins an older Claude Code version than the installed binary. The live reading is `aipass doctor`, which diffs the manifest against `~/.claude/settings.json` — a number written down here would be stale by the next release | Drift, re-read on demand |
| A `MagicMock/LOG_FILE/` directory sits in the branch root, created 2026-07-10 — test debris from a mock used as a path. Author unknown; not attributed | Unexplained, left in place |
| The `dead_code` 40% / "29 of 49 files" figure quoted in [engine.md](engine.md) is **historic and not re-verified** — re-running unshielded needs a bypass-rule change this branch does not make for a doc pass | Unverified, marked in place |
| `tests/test_edit_gate.py::TestEditGateProjectBoundary::test_allow_host_seat_writing_down_into_nested_project` failed twice in ~70 runs on 2026-09-15, both on slow runs while other seats were writing, then passed ~60 consecutive times including under three overlapping pytest processes. The failure text was never captured | Open, intermittent, uncaptured |

## Closed in the diet pass (2026-09-15)

`drone @hooks engine` ran but was absent from `--help`, and this README was the only place the verb was
written down. The diet deletes hand-typed command lists, so the verb went into `HELP_COMMANDS`
(`apps/modules/engine.py`) rather than survive only here: `--help` is the reference, and a verb it does
not name belongs there or nowhere.

---

## Related

- [git_gate.md](git_gate.md) — the allow-list itself
- [testwrite_gate.md](testwrite_gate.md) — what that gate deliberately does not catch, published as data
- [bash_writes.md](bash_writes.md) — the reader both false fires point at
