# The memory lane — shell refusal, tripwire, and the `.trinity` caps

**Branch** hooks · **Code** `apps/handlers/security/edit_gate.py`, @memory's `memory.config.json` → `entry_limits`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

How a write to `.trinity/local.json`, `observations.json` or `passport.json` is judged, on both lanes. Every cap named here is read from @memory's own module at call time; no number is copied into this branch.

---

## The shell refusal and the tripwire

**Memory files are not written from a shell (2026-09-13, DPLAN-0342 row 3).** A second rule runs on the
same targets: a claimed write to `.trinity/local.json` or `.trinity/observations.json` is refused for every
seat in every project, the admin seat included (its exemption is for the project fence, not for how memory
is written). @memory's caps are measured on the Edit/Write lane, so a shell write landed unmeasured: @baud
wrote 21 of 21 sessions over cap that way, @api 12 sessions and 16 learnings, @hooks 9 entries. The refusal
names the target and the verb, and says where memory is written: the Edit or Write tool, or a `drone @memory`
verb.

- **Known over-refusal.** An interpreter that only *reads* a memory path is refused too, because the
  interpreter rule cannot tell a read from a write. The refusal says so and names the tools that read: the
  Read tool, `cat`, `jq`.
- **Open shapes, measured 2026-09-13.** A bare file name in interpreter source after a `cd` (the `cd` *is*
  honoured; `./local.json` after it is caught), a path joined in program text, a path in a shell variable,
  and write verbs the reader has no grammar for (`sponge`, `ed`). All are in the list above.

**The tripwire reports what the refusal cannot see.** Two more functions in `edit_gate`:
`tripwire_snapshot` (PreToolUse, Bash) records `(mtime_ns, size)` for every watched memory file under the
call's `tool_use_id`, and `tripwire` (PostToolUse, Bash) compares. If a memory file changed during the call
and the command ran no `drone @memory` or `drone @spawn` verb, the whole file is measured on disk against
@memory's caps. An over-cap or unparseable file is charged: `MEMORY WRITTEN FROM A SHELL: <file> changed
during this Bash call, outside the caps gate`, followed by every over-cap entry with its cut point. A file
that measures clean is **said, not charged** (1.15.0): `MEMORY CHANGED DURING THIS BASH CALL`, which adds
that it may not have been this command — @memory's rollover, run by *any* seat's compaction, writes here
too. Measured 2026-09-16: a neighbour's PreCompact rolled this seat's `local.json` mid-call and the old
wording accused the seat. A clean change logs at INFO, a charged one at WARNING. It never blocks. Keying on `tool_use_id` is what keeps a memory Edit made just before the call from being blamed on it.

Since 1.13.0 (DPLAN-0347) it watches **every `.trinity` in the project**, not just the seat's, and
`passport.json` with `local.json` and `observations.json` — 24 directories and 72 stats, ~19 ms, measured on
this repo. A cross-branch shell write is exactly the shape the reader cannot always see. The wording follows
ownership: the seat's own file is reported as this call's write, another branch's as
`ANOTHER BRANCH'S MEMORY CHANGED`, which says plainly that a live neighbouring session may own it. That is
not hypothetical — the first fleet-wide run caught @devpulse and @memory saving their own memory inside a
76-second `pytest`. Its own limits: a call that ends in a tool error fires `PostToolUseFailure`, which this
engine does not wire, so a write followed by a failure goes unreported; and because the snapshot holds stats,
not text, entries already over cap before the call are listed too ("holds", never "wrote").

> **CONFIG WIRE — the tripwire is not live until two entries land in `.aipass/hooks.json`**, followed by
> `aipass trust <path-to-this-repo>` (any byte change voids the trust hash):
> `PreToolUse.trinity_tripwire_snapshot` → `aipass.hooks.apps.handlers.security.edit_gate.tripwire_snapshot`,
> matcher `Bash`; `PostToolUse.trinity_tripwire` → `aipass.hooks.apps.handlers.security.edit_gate.tripwire`,
> matcher `Bash`. No provider wire: tool events already run every enabled handler. The refusal needs no wire;
> it rides `pre_edit_gate`, which already matches Bash.

**No grace window — the tripwire's "file did not parse" alarm is a real broken file (FPLAN-0593 Phase 5).**
A grace-then-re-stat was proposed for the tripwire's false alarms and measured first. Every writer of these
files is atomic (the Edit tool swaps the inode; @memory and prax write through `os.replace`), so no reader
can see a torn file. The retained logs (09-12 → 09-16) held 2 real breakages, open for 9 s and 8 s — one was a
seat's own Edit that left `observations.json` invalid until its next Edit. A grace long enough to hide those
would stall every Bash call and hide the breakage it was meant to report. The cure landed at the source
instead: an Edit or Write that would leave a memory file **unparseable is refused** (the reason quotes the
parse error), and an edit that *repairs* an already-broken file is allowed with a WARNING that it was broken.

## `.trinity` caps — a write is judged on what it AUTHORS

`edit_gate` also measures `.trinity/local.json`, `observations.json` and `passport.json` against
@memory's published caps (`memory.config.json` → `entry_limits`, read through their `entry_limits`
module — this gate never restates a cap). A passport is measured by **size only** — 6,000 chars per
file, 600 per string, via `check_file_budget` — because @spawn owns its schema. @memory 1.11.0's two
newer refusal species are rendered as themselves: `unknown_field` names the allowed fields from
`fields_for` (never a copy), and `field_over_cap` prints `'status' is 917/40 chars (+877 over)` in the
units the violation carries, chars or items. An entry over its character limit is refused, and so is an entry whose
canonical field is *missing*: a renamed `learning` where the config says `value` leaves the extractor
with no key to read, and `""` and "cannot read this" are different answers.

**Both refusals apply only to entries the write authored.** An entry byte-identical to the one
already on disk is *carried*, not authored — reported at INFO with a pointer to `drone @memory lint`,
never blocked. This was narrowed to `todos` on 2026-08-27 and made universal again on 2026-08-30
after @memory measured what the narrowing did: their rollover lane failed identically every 20
minutes for three hours, because the extractor removed a tail, wrote the *smaller* document back, and
this gate refused the whole file over an entry in the head the extraction never touched. The archiver
is always on the losing side of that trade — the file cannot get smaller because it is too big.

The other half of the evidence is how that drift arrived: through the shell, where the cap check never
ran. Since 2026-09-13 a shell write to a memory file is refused when the reader can see it and reported
by the tripwire when it cannot (see the scripted lane above), and the refusal text says so. A gate that
judges a write still cannot refuse a file for drift it already carries: detecting drift already on disk
is `drone @memory lint`'s job, which reads the file.

Identity is the raw entry, never its index. A prepend shifts every position down, so an index-keyed
diff would call the whole file newly authored on exactly the write that authored nothing.

Carrying a drifted entry does not license adding another in the same shape: a NEW entry with a
missing canonical field is authored, and refused.

**The todo pad count is advised, never refused** (DPLAN-0345). An 11th todo is legal on disk: the
oldest roll off to `.backup/todo/<branch>/backlog.json` at that branch's next PreCompact or
`drone @memory rollover run --branch @<branch>`. The pad size is @memory's own resolver
(`config_loader.get_todos_count`), the number its roll applies. A write that leaves the pad over it
gets an advisory as PreToolUse `hookSpecificOutput.additionalContext`, because the model writing the
todo is its audience. Until 2026-09-15 it went out as plain stdout, which Claude Code shows in the
transcript view on a PreToolUse exit 0 and never hands to the model (@canary measured it: 227 bytes
logged, nothing in the Edit result). **The advisory fires at most once per cadence window per
session** (`cadence.should_fire_advisory("todos_count")`: 10 turns, or 600 s when the turn counter
cannot be read). An over-count pad is a standing condition, and per-write firing once wrote 209
identical lines. So a second over-count write in the same window is silent by design, its log line
drops to DEBUG, and the per-write INFO note that names the backlog still lands in `edit_gate.log`.

---

## Related

- [bash_writes.md](bash_writes.md) — the reader that decides what a shell command can be seen to write
- [edit_gate.md](edit_gate.md) — the project and branch fences on the same handler
- [prompt_injection.md](prompt_injection.md) — the other half of the layer contract, at render time
