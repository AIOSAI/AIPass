# The command surface

[<- Back to BACKUP](../README.md)

How the router behaves, which flags exist, and the two entry forms that are easy
to miss. The live list of verbs is `drone @backup` and `drone @backup --help` —
this page covers what those two cannot tell you about themselves.

## The router

The router auto-discovers every file in `apps/modules/` that exposes a
`handle_command()`. One of them, `display`, is a rendering helper rather than a
backup verb — it answers only to its own name (`drone @backup display` prints
its introspection and does nothing else) and is intentionally undocumented as a
command.

**A `--help` anywhere in the arguments prints help and runs nothing** — `drone
@backup snapshot @myapp --help` is a safe probe, not a backup. That rule is a
cure, not a convenience: checking only the first argument once let `snapshot
<project> --help` fall through and execute a real backup.

**Relative paths resolve where you are.** Backup runs as an installed entry
point, so its process CWD is its own branch directory. Drone exports
`AIPASS_CALLER_CWD`; `handlers/path/caller.py` re-anchors every user-supplied
relative path to it, so `drone @backup share docs/notes.md` means the caller's
`docs/notes.md`. Absolute paths are untouched.

## Flags, by verb

Flags live in the verbs, not in the router, which is why the top-level command
reference lists verbs and this page lists their options.

| Verb | Flag | Effect |
|---|---|---|
| `register` | `--name <name>` | Register under a short name, so `@name` resolves to the path |
| `all` | `--quiet` | Suppress the Rich panels; the run itself is unchanged |
| `drive_sync` | `--force` | Re-upload files the tracker already recorded |
| `drive_sync` | `--project <name>` | Sync a registered project by name |
| `drive_sync` | `--note <text>` | Attach a note to the sync record |
| `drive_clear` | `--force` | Required — the verb refuses to clear the tracker without it |
| `share` | `--public` | Share the uploaded file with anyone holding the link |

`restore` takes subcommands rather than flags: `list <file>` and `file <file>
<output>`. See [restore](restore.md).

## Two entry forms

The documented form is `<verb> <project>`: the verb first, the project second.

There is also a legacy form, `backup <project|@name>`, which runs `snapshot` by
default and accepts `--versioned` or `--all` to pick another lane
(`apps/backup.py`, in `main()`). It resolves registered names the same way the
verbs do. It predates the auto-discovery router, nothing in the tree calls it,
and no test exercises it — it is documented here because it is live, not because
it is recommended. Use the verbs.

`--version` and `-V` both print the entry point's version; `help` on its own
behaves like `--help`.

---

[<- Back to BACKUP](../README.md)
