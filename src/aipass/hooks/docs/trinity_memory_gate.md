[<- Back to the README](../README.md)

# The memory lane — shell refusal, tripwire, and the `.trinity` caps

**Branch** hooks · **Code** `apps/handlers/security/edit_gate.py`, @memory's `memory.config.json` → `entry_limits`

How a write to `.trinity/local.json`, `observations.json` or `passport.json` is judged, on both lanes. Every cap named here is read from @memory's own module at call time; no number is copied into this branch.

---

## The shell refusal and the tripwire

**Memory files are not written from a shell.** A second rule runs on the
same targets: a claimed write to `.trinity/local.json` or `.trinity/observations.json` is refused for every
seat in every project, the admin seat included (its exemption is for the project fence, not for how memory
is written). @memory's caps are measured on the Edit/Write lane, so a shell write would land unmeasured. The
refusal names the target and the verb, and says where memory is written: the Edit or Write tool, or a
`drone @memory` verb.

- **Known over-refusal.** An interpreter that only *reads* a memory path is refused too, because the
  interpreter rule cannot tell a read from a write. The refusal says so and names the tools that read: the
  Read tool, `cat`, `jq`.
- **Open shapes.** A bare file name in interpreter source after a `cd` (the `cd` *is*
  honoured; `./local.json` after it is caught), a path joined in program text, a path in a shell variable,
  and write verbs the reader has no grammar for (`sponge`, `ed`). All are listed in [bash_writes.md](bash_writes.md).

**The tripwire reports what the refusal cannot see.** Two more functions in `edit_gate`:
`tripwire_snapshot` (PreToolUse, Bash) records `(mtime_ns, size)` for every watched memory file under the
call's `tool_use_id`, and `tripwire` (PostToolUse, Bash) compares. If a memory file changed during the call
and the command ran no `drone @memory` or `drone @spawn` verb, the whole file is measured on disk against
@memory's caps. An over-cap or unparseable file is charged: `MEMORY WRITTEN FROM A SHELL: <file> changed
during this Bash call, outside the caps gate`, followed by every over-cap entry with its cut point. A file
that measures clean is **said, not charged**: `MEMORY CHANGED DURING THIS BASH CALL`, which adds
that it may not have been this command — @memory's rollover, run by *any* seat's compaction, writes here
too. A clean change logs at INFO, a charged one at WARNING. It never blocks. Keying on `tool_use_id` is what keeps a memory Edit made just before the call from being blamed on it.

It watches **every `.trinity` in the project**, not just the seat's, and
`passport.json` with `local.json` and `observations.json`. A cross-branch shell write is exactly the shape the reader cannot always see. The wording follows
ownership: the seat's own file is reported as this call's write, another branch's as
`ANOTHER BRANCH'S MEMORY CHANGED`, which says plainly that a live neighbouring session may own it. Its own
limits: a call that ends in a tool error fires `PostToolUseFailure`, which this
engine does not wire, so a write followed by a failure goes unreported; and because the snapshot holds stats,
not text, entries already over cap before the call are listed too ("holds", never "wrote").

> **CONFIG WIRE — the tripwire is wired in `.aipass/hooks.json`** (both entries are present, and both
> are in the built-in gate set in `handlers/config/gates.py`, so they run even when no config can be
> read): `PreToolUse.trinity_tripwire_snapshot` → `aipass.hooks.apps.handlers.security.edit_gate.tripwire_snapshot`,
> matcher `Bash`; `PostToolUse.trinity_tripwire` → `aipass.hooks.apps.handlers.security.edit_gate.tripwire`,
> matcher `Bash`. No provider wire: tool events already run every enabled handler. The refusal needs no wire;
> it rides `pre_edit_gate`, which already matches Bash.

**No grace window — the tripwire's "file did not parse" alarm is a real broken file.**
Every writer of these files is atomic (the Edit tool swaps the inode; @memory and prax write through
`os.replace`), so no reader can see a torn file. A grace-then-re-stat long enough to hide a real breakage
would stall every Bash call and hide the breakage it is meant to report. The guard sits at the source
instead: an Edit or Write that would leave a memory file **unparseable is refused** (the reason quotes the
parse error), and an edit that *repairs* an already-broken file is allowed with a WARNING that it was broken.

## `.trinity` caps — a write is judged on what it AUTHORS

`edit_gate` also measures `.trinity/local.json`, `observations.json` and `passport.json` against
@memory's published caps (`memory.config.json` → `entry_limits`, read through their `entry_limits`
module — this gate never restates a cap). A passport is measured by **size only** — 6,000 chars per
file, 600 per string, via `check_file_budget` — because @spawn owns its schema. @memory's two
newer refusal species are rendered as themselves: `unknown_field` names the allowed fields from
`fields_for` (never a copy), and `field_over_cap` prints `'status' is 917/40 chars (+877 over)` in the
units the violation carries, chars or items. An entry over its character limit is refused, and so is an entry whose
canonical field is *missing*: a renamed `learning` where the config says `value` leaves the extractor
with no key to read, and `""` and "cannot read this" are different answers.

**Both refusals apply only to entries the write authored.** An entry byte-identical to the one
already on disk is *carried*, not authored — reported at INFO with a pointer to `drone @memory lint`,
never blocked. This holds for every section: @memory's rollover removes a tail and writes the
*smaller* document back, and a gate that refused the whole file over an untouched entry in the head
would put the archiver on the losing side — the file could not get smaller because it is too big.

Drift on disk arrives through the shell, where the cap check does not run, so a shell write to a memory
file is refused when the reader can see it and reported by the tripwire when it cannot (see the shell
lane above). A gate that
judges a write still cannot refuse a file for drift it already carries: detecting drift already on disk
is `drone @memory lint`'s job, which reads the file.

Identity is the raw entry, never its index. A prepend shifts every position down, so an index-keyed
diff would call the whole file newly authored on exactly the write that authored nothing.

Carrying a drifted entry does not license adding another in the same shape: a NEW entry with a
missing canonical field is authored, and refused.

**The todo pad count is advised, never refused.** An 11th todo is legal on disk: the
oldest roll off to `.backup/todo/<branch>/backlog.json` at that branch's next PreCompact or
`drone @memory rollover run --branch @<branch>`. The pad size is @memory's own resolver
(`config_loader.get_todos_count`), the number its roll applies. A write that leaves the pad over it
gets an advisory as PreToolUse `hookSpecificOutput.additionalContext`, because the model writing the
todo is its audience; plain stdout on a PreToolUse exit 0 is shown in the transcript view and never
handed to the model. **The advisory fires at most once per cadence window per
session** (`cadence.should_fire_advisory("todos_count")`: 10 turns, or 600 s when the turn counter
cannot be read). An over-count pad is a standing condition, so a second over-count write in the same window is silent by design, its log line
drops to DEBUG, and the per-write INFO note that names the backlog still lands in `edit_gate.log`.

---

## Related

- [bash_writes.md](bash_writes.md) — the reader that decides what a shell command can be seen to write
- [edit_gate.md](edit_gate.md) — the project and branch fences on the same handler
- [prompt_injection.md](prompt_injection.md) — the other half of the layer contract, at render time
