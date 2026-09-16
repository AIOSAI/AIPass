[← Back to Flow](../README.md)

# Unknown Arguments Fail — one gate, every door

Why an unrecognised argument refuses instead of proceeding on a default, where the single gate lives, and what "absolute" has to mean in a registry shared by every branch.

---

The owner's standing ruling (fleet CLI sweep 2026-09-07): an unknown command or
argument FAILS — non-zero exit, a message naming the token, a did-you-mean when
one is close. It never proceeds as if a default were meant.

Flow's verbs and flags were already clean; its SUB-arguments were the sweep's
worst class. `drone @flow list not_a_filter` warned and then printed the open
plans with exit 0 — an answer to a question nobody asked, and a script reading
success. Measured across every door flow owns, before the cure: six ran real
work on an unread token (`aggregate` performed the cross-branch write), two
named the token but still exited 0, and `registry` refused correctly then
printed a second, contradictory "Unknown command: registry" with the whole help
screen under it.

`handlers/cli/arg_gate.py` DECIDES and raises `UnknownArgument` carrying the
door, the token, the message and the cure line; each module renders it through
`cli.error` and exits 1. The split is forced by two standards that meet here: a
handler may not import cli services, and the entry point may not import
handlers — so the decision cannot render itself and `flow.py` cannot catch it.
One decision, one vocabulary, nine doors.

| Door | Before | After |
|------|--------|-------|
| `list <bogus>` | exit 0, listed the open plans | exit 1, names the filter |
| `list open <extra>` | exit 0, ignored | exit 1 |
| `templates <bogus>` / `scan <bogus>` | exit 0, ignored | exit 1 |
| `aggregate <bogus>` | exit 0, **ran the write** | exit 1, before any write |
| `post <bogus>` | exit 0, ran the archival pass | exit 1 |
| `registry <bogus>` | exit 1 + a contradictory second message | exit 1, one message |
| `close <bogus>` / `restore <bogus>` | exit 0 under a correct refusal | exit 1 |

A refusing door must not swallow `--help`. In `template_manager` the four
verbs each held their own help gate; routing them through a shared `_route()`
left `handle_command` with no visible help interception at all — seedgo's
introspection check caught it, and the guarantee was genuinely harder to read.
The gate now sits once in `handle_command`, scoped to the four verbs it owns
(`frobnicate --help` still falls through to the next module), and is pinned
across verb × flag rather than for `templates` alone.

Two notes. `aggregate run` and `scan run` were accepted-and-ignored sub-verbs —
undocumented, in no caller, alive only in the tests — and are now refused.
`register` / `unregister` with MISSING arguments still print a usage error and
exit 0: that is arity, not an unknown argument, and it is reported rather than
changed.

### What "absolute" means in a shared registry

`recover_plan_from_backup` reads the plan header's `**Location**:` line to decide
where a restored file lands. It tested that with `startswith("/")`, which is the
HOST's answer, not the record's: the registries are shared across install
histories, so a row written on Windows is read on POSIX and back. `C:\plans`
failed that test, fell into the relative branch, failed to resolve, and the
plan landed under `FLOW_ROOT` — a directory its own header never named.

`_recorded_is_absolute()` asks both dialects by name (`PurePosixPath` OR
`PureWindowsPath`), and the asymmetry is why both are needed: `PureWindowsPath`
accepts a POSIX-absolute path as drive-relative, while `PurePosixPath` refuses a
drive letter outright. A vanished absolute record is now **refused by name**
rather than re-homed — recreate the directory or edit the header (ruled
2026-09-07). Pinned in `tests/test_restore_ops.py` for the drive-letter, UNC,
vanished-POSIX, live-POSIX and relative cases, none of which read the host.

---

