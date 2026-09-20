[<- Back to the README](../README.md)

# Where this branch writes

Everything this branch puts on disk, and which of it means anything. Short
answer: none of it is load-bearing for anyone. It is test data by definition.

## The entry point writes nothing

Measured with the test seam unset: `apps/canary.py` performs no filesystem write
at all. The only state it touches is two process-local `os.environ.setdefault`
calls, for the branch name the logger resolves at import and for UTF-8 on
Windows consoles. Everything below is written by a module or by a service acting
on this branch's behalf.

## The json handler shim

`apps/handlers/json/json_handler.py` is the byte-identical fleet shim, checked
by hash across every branch. It imports exactly one thing — the shared json
service — and binds its public names to a per-branch handle. It imports nothing
from the old shared handler, which was retired to an archive directory; this
branch's dead-cwd pins dropped their preload of it in the same sweep.

Path resolution, measured with the test seam unset: a config, data or log
document for a given name resolves under `canary_json/` as
`<name>_<type>.json`. The service accepts only those three types.

## canary_json/

Test data, git-ignored, nothing depends on it. Each module's operation trail
creates its own documents there on that module's first live run: `note_*` and
`store_*` for the note store, `span_*` for the duration parser, config, data
and log apiece.

`canary_json/custom_config/` is a leftover directory holding only a placeholder
README. Nothing routes there, because the json service accepts only the three
types above. Left in place, named here so the next reader does not go looking
for its purpose.

## docs.local/

Git-ignored working space. It holds the note store, `notes.jsonl`, and whatever
a sub-agent drops during a test.

## logs/

Prax log output *and* dispatch transcripts, which is worth knowing before
reading anything there. `dispatch_stdout.log`, `dispatch_stderr.log`,
`dispatch_wake.log` and the `.dispatch_env` snapshot are written by the mail
branch when work arrives here — they are not this branch's own output.
`note.log` and `span.log` are: each module logs its own refusals and I/O
failures to a file named for it.

The entry point's own logger call sites — an import fallback, a module that
fails to load, a module that raises mid-route, and an unhandled error in
`main()` — have never fired. No log file named for the entry point exists
anywhere in the repository, which is a fact about how little goes wrong here,
not about the wiring.

## Archives

`apps/handlers/.archive/` and `apps/handlers/json/.archive/` hold the pre-sweep
path helper and the retired local json handler. `tests/.archive/` holds retired
suites. Archive directories are untracked by doctrine: present on disk, absent
from the repository.

[<- Back to the branch README](../README.md)
