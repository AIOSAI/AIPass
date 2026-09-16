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
| `git_gate` false-fired on a **heredoc mail body**: `RAW_GIT_RE` scans command text after stripping *quoted* strings, and a heredoc body is not quoted, so prose containing "git" blocked an `ai_mail` reply | **Cured 2026-09-16** (FPLAN-0593 Phase 5): the gate scans `bash_writes.code_text()`, which blanks a read-only heredoc body and keeps a shell's program text (bash/sh/zsh; awk or python programs stay blanked as before) — closing the `bash -c "<write>"` hole in the same move. See [git_gate.md](git_gate.md) |
| `engine._log_detail()`'s env switch predates prax gaining `logger.debug()`; folding one onto the other is unstarted | Open cleanup |
| Bare `drone @hooks test` prints the module blurb and fires nothing (`apps/modules/hook_test.py`, the `if not args` branch). The documented command does not do the documented thing; the run needs an argument such as `--verbose` | Open — reported to @devpulse 2026-09-06, a behaviour change outside the doc scope |
| `.claude/provider_manifest.json` pins an older Claude Code version than the installed binary. The live reading is `aipass doctor`, which diffs the manifest against `~/.claude/settings.json` — a number written down here would be stale by the next release | Drift, re-read on demand |
| `git_gate` and `rm_gate` recognise the executable by name, so a Windows spelling is not read as the command: `git.exe <write verb>` and `rm.exe -rf <dir>` return allow, as does an upper-case `GIT`. Git Bash resolves `.exe`, and case-insensitive filesystems resolve the case | Open — measured on the gates' reading 2026-09-16 (on Linux, not on a Windows host). A command-recognition change to two gates, left out of the CI-red fix that found it |
| `auto_fix` (`"/.claude/hooks/" in file_path`) and `subagent_gate` (`"/.claude/" in file_path`) test a forward-slash substring, so on Windows they do not recognise a hook file | Open, low — both fail toward MORE checking (hook files get linted or checklisted), never toward allowing. Swept 2026-09-16 |
| The `dead_code` 40% / "29 of 49 files" figure quoted in [engine.md](engine.md) is **historic and not re-verified** — re-running unshielded needs a bypass-rule change this branch does not make for a doc pass | Unverified, marked in place |
| `tests/test_edit_gate.py::TestEditGateProjectBoundary::test_allow_host_seat_writing_down_into_nested_project` failed twice in ~70 runs on 2026-09-15, both on slow runs while other seats were writing, then passed ~60 consecutive times including under three overlapping pytest processes. The failure text was never captured | Open, intermittent, uncaptured |

## When the host-derived value was right (2026-09-16)

The fleet chased one class all day: a test value taken from the host it runs on. The first two
instances were tests failing spuriously on a host they did not expect. This one is the inverse, and it
is why the class matters. Phase 5 replaced a hardcoded POSIX home path in `test_git_gate.py` with one
built from `Path.home()`. On the Windows runner that produced a backslash path, and the gate **allowed**
an edit to the provider settings file and to `.claude/hooks/`. The protected-path regexes were written
with forward slashes and the path was never normalised. The hardcoded constant had fed the gate a path
no Windows host produces, so the test passed there while testing nothing. The hole predates the phase.
Cured in `git_gate` 1.2.0: the path is normalised before matching, and the match is case-insensitive.

The same run surfaced a second host-shaped defect with no path spelling in it. On Windows the temp dir
sits under the user's home, and `grounding_content._find_project_dir()` counted the per-user
`~/.aipass` (trust registry, commons.db) as a stamped tree. Every tmp_path therefore "promised" a kernel,
and tests expecting silence got the degraded banner. Linux never saw it, because `/tmp` is not under home.
Cured in 1.3.1: the walk skips that directory, compared with `samefile` because a Windows TEMP can
reach it through an 8.3 short name. Reproduced and re-proven on Linux by running the suite with
`--basetemp` under home. Live reach measured nil: the engine injects nothing in an unstamped tree under home.

**The rule this leaves:** a test fixture spelled for one host is not neutral. It can hide a defect on
every other host.

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
