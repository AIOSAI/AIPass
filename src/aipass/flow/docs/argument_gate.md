[← Back to Flow](../README.md)

# Unknown Arguments Fail — one gate, every door

Why an unrecognised argument refuses instead of proceeding on a default, where the single gate lives, and what "absolute" has to mean in a registry shared by every branch.

---

An unknown command or argument FAILS: non-zero exit, a message naming the
token, a did-you-mean when one is close. It never proceeds as if a default were
meant. An answer to a question nobody asked, with exit 0, is a script reading
success.

`handlers/cli/arg_gate.py` DECIDES and raises `UnknownArgument` carrying the
door, the token, the message and the cure line; each module renders it through
`cli.error` and exits 1. The split is forced by two standards that meet here: a
handler may not import cli services, and the entry point may not import
handlers — so the decision cannot render itself and `flow.py` cannot catch it.
One decision, one vocabulary, nine doors.

| Door | Behaviour |
|------|-----------|
| `list <bogus>` | exit 1, names the filter |
| `list open <extra>` | exit 1 |
| `templates <bogus>` / `scan <bogus>` | exit 1 |
| `aggregate <bogus>` | exit 1, before any write |
| `post <bogus>` | exit 1 |
| `registry <bogus>` | exit 1, one message |
| `close <bogus>` / `restore <bogus>` | exit 1 |

A refusing door must not swallow `--help`. In `template_manager` the help gate
sits once in `handle_command`, scoped to the four verbs it owns
(`frobnicate --help` still falls through to the next module), and is pinned
across verb × flag rather than for `templates` alone.

`aggregate` and `scan` take no sub-verbs; `aggregate run` and `scan run` are
refused like any other token. `register` / `unregister` with MISSING arguments
print a usage error and exit 0: that is arity, not an unknown argument, and it
is an open question rather than a gate rule.

### What "absolute" means in a shared registry

`recover_plan_from_backup` reads the plan header's `**Location**:` line to decide
where a restored file lands. The registries are shared across install
histories, so a row written on Windows is read on POSIX and back: whether a
recorded path is absolute is the RECORD's answer, never the host's
(`startswith("/")` would send `C:\plans` into the relative branch and land the
plan under `FLOW_ROOT`, a directory its header never named).

`_recorded_is_absolute()` asks both dialects by name (`PurePosixPath` OR
`PureWindowsPath`), and the asymmetry is why both are needed: `PureWindowsPath`
accepts a POSIX-absolute path as drive-relative, while `PurePosixPath` refuses a
drive letter outright. A vanished absolute record is **refused by name**
rather than re-homed — recreate the directory or edit the header. Pinned in
`tests/test_restore_ops.py` for the drive-letter, UNC, vanished-POSIX,
live-POSIX and relative cases, none of which read the host.

---
