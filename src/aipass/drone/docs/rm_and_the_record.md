# `rm` and the record — every delete leaves one

**Branch** drone · **Code** `apps/modules/rm.py`, `apps/handlers/rm_handler.py`,
`apps/handlers/deletion_log.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

`drone rm` is the fleet's only sanctioned delete path — raw recursive `rm` is gate-blocked — which
makes it the choke point where the record belongs. The owner's ruling: *"if something deletes, there
should be a record of it."* The rules and the flags are `drone rm --help`.

---

## Two channels

| Channel | Where | What it is for |
|---|---|---|
| JSONL store | `<project>/.ai_central/deletions.jsonl` | machine-readable, findable months later |
| prax line | normal logs, **INFO** | flows through observability without knowing this file exists |

The prax line is emitted **first**. If the store write fails it is reported at ERROR and the delete
still proceeds — losing the log must not turn into losing the delete, and the event has already
reached the logs either way.

A record carries: `timestamp`, `lane`, `outcome`, `caller`, `cwd`, `requested` (what was typed),
`path` (resolved), `reason`, `kind`, `size_bytes`, `entry_count`, `measured`. A stale-mode record
carries two more, `mode` and `age` (as typed), and its prax line names both; a plain delete's
record keeps exactly the twelve, byte for byte.

Four things worth knowing:

- **Refusals are records too.** A blocked delete leaves no other trace of what was attempted, which
  is exactly what makes it worth finding later. Refused paths are deliberately *not* measured — the
  guard just said that tree is off-limits, so nothing goes and reads inside it.
- **Measurement happens before the delete.** After `rmtree` there is nothing left to ask how big it
  was. Directory walks stop at `_MEASURE_ENTRY_CAP` and say so via `measured: "capped"` rather than
  paying an unbounded walk.
- **Severity is INFO on both channels** (compass #273). A deletion through the sanctioned path is
  chosen behaviour, not a fault. The guards keep their own WARNING when they refuse — that is the
  guard speaking, and it is a separate line from the record.
- **The record follows the deletion's project, not the process's.** `deletion_log_path()` takes an
  optional `project_root`, and the broker passes the `repo_root` it was constructed with. A daemon
  can serve a repository it is not standing in; resolving the store from cwd there files the record
  under the standing project instead — which is exactly how a sandbox suite's deletions came to sit
  in this ledger (see [known_issues.md](known_issues.md)). `AIPASS_DELETION_LOG` still outranks
  both, so the test and container seam cannot be defeated by a lane naming its own root. `rm`
  passes nothing and keeps the cwd walk, which is correct for it: the operator IS standing in the
  project they are deleting from.
- **Identity is resolved, never guessed.** `resolve_caller_identity()` — the same resolver routing
  and git attribution use, not a fifth one and not path-shape matching. Unresolvable callers are
  recorded as `unknown`; a wrong-but-plausible name on a deletion record is worse than an honest
  gap.

`AIPASS_DELETION_LOG` relocates the store (tests, containers). It cannot silence the prax line. The
store is bounded at 2 MB with one rotation, because a delete log that grows forever becomes the
runaway log the monitoring lane exists to catch.

Both delete lanes feed it: `rm`, and the broker (`apps/handlers/broker/daemon.py`), which deletes on
behalf of an HMAC-authenticated requester and therefore passes that identity in rather than reading
its own cwd. The broker's protocol audit log is unchanged — that records requests and error codes;
this records deletions.

**Known gap in the `caller` field.** The resolver's last resort before `unknown` is the *project*,
not a citizen: with no `AIPASS_BRANCH_NAME` assigned and no passport anywhere up the tree, it
derives a name from the registry that answered. A delete run from the repo root therefore records
`caller: "aipass"` — a directory, not the citizen who typed it. Nothing is fabricated (`aipass` is a
true statement about *where* the process stood, and `CallerIdentity.source` says `project`), but a
reader auditing a deletion months later wants the citizen, and for those records the ledger cannot
supply one. Writing it down beats a reader inferring a person from a project name.

---

## Sibling-branch guard — outermost `.trinity` wins

The guard refuses deletes inside another citizen's tree, and it finds the owning citizen by walking
up for `.trinity/`. It takes the **outermost** hit within the project, not the innermost, because
`.trinity/` is not proof of a citizen: @spawn ships a complete branch skeleton under its templates,
passport and all.

Innermost-wins produced two bugs from one mimicry — refusals named a template, which has no mailbox
to appeal to, and @spawn was locked out of its own templates because a skeleton's name never
matches the branch you are standing in. The same mimicry sent the commit gate running pytest inside
the template; outermost-citizen-wins is the mapping that fixed it there, applied here.

Safe because nothing above a branch carries `.trinity/` — not the project root, not `src/`, not
`src/aipass/` — so the outermost hit inside the project *is* the citizen. The walk stops at the
project boundary.

---

## A folder that contains a citizen

The sibling guard walks **up** from the target, so it only sees a citizen the target sits *inside*.
Nothing above a branch carries `.trinity/`, so a target above the branches passed it. From any
branch, `drone rm ..` is `src/aipass/` and `drone rm ../..` is `src/`. Both also passed
containment, and rmtree would have taken every branch, `.trinity/` and all (measured 2026-09-11
with the guards alone; DPLAN-0338 follow-up).

`check_contained_citizens()` walks **down** and refuses at the first foreign citizen, naming it.

- **Bounded.** The walk is sorted and stops at the first foreign `.trinity/`. The live `..` answers
  in about a millisecond.
- **The caller's own tree is pruned whole**, template skeleton included (outermost-wins makes the
  skeleton the caller's). A target already inside a branch returns at once, because the sibling
  guard has answered for everything below it.
- **Unchanged:** targets inside the caller's own branch, and targets in the system temp dir, where
  a `.trinity/` is test scaffolding, not a citizen. Stale mode is unaffected; it never reaches this
  lane.
- **A symlink is not a citizen.** rmtree unlinks the link and never touches what it points at.
- **A folder the walk cannot list refuses the delete.** A guard that could not look must not report
  clear.
- **Whether you may delete the folder you are standing in is the host's call, not ours.** POSIX
  allows it, so `drone rm ..` from a branch completes. Windows holds the current directory open
  without delete sharing and refuses with `WinError 32` — the fence's verdict is identical on both
  hosts, and what fails there is the removal. The message and the record name where the process was
  standing and say to run it from outside. The suite marks the end-to-end case `deletable_cwd`,
  which Windows skips, and pins the verdict itself beside it on every OS.
- Refusals are recorded like every other refusal. A caller standing outside every branch finds
  every citizen foreign.

Same lane, same change: the delete acts on the **resolved** path, the one every guard judged.
Before, it acted on the path as typed. `drone rm ..` handed rmtree `spawn/..`, which emptied the
tree and then failed its last `rmdir`, because `spawn` was gone by then — and the ledger recorded
`failed` for a delete that had happened.

---

## Stale mode — `drone rm --stale`

`drone rm --stale AGE [--dry-run] DIR [DIR...]` sweeps staging temps: the `*.tmp` a staged write
(temp + fsync + rename) leaves behind when its process is killed between the two (DPLAN-0338). It
is a second, narrower lane on the same verb; without `--stale` the verb is unchanged.

| Rule | What it means |
|---|---|
| AGE | A whole number and a unit: `10d`, `36h`, `90m`. Anything else is refused with a message naming the three forms. Zero is refused too, because an age of zero matches a write in flight, and unlinking its temp fails that write's rename |
| Candidate | A **regular file** (never a symlink, never a directory) whose name ends `.tmp`, whose **parent** folder's name ends `_json`, and whose mtime is older than now minus AGE. Nothing else is touched |
| DIR | Must resolve under the **project root**; the system temp roots the plain lane allows are not swept. Must be outside the carve-outs. The walk never enters a carve-out directory and never follows a symlink. Overlapping DIRs walk each folder once |
| Sibling fence | **Crossed, in this mode only, by design.** A stale staging temp is no citizen's work: the real json beside it is intact whatever happens to the temp. One weekly job has to sweep every branch's json folder in one call. The name + folder + age restriction is the fence instead. The plain verb still refuses the same file |
| Record | Every delete and every refusal goes to both channels with `mode` and `age`. `requested` is the DIR as typed; `path` is the file |
| `--dry-run` | Lists every candidate with its age and size and deletes nothing, so it records nothing either. Its refusals still print and still fail the run |
| Output | One summary line at the end: folders scanned, files matched (with their bytes), files deleted, bytes freed, refusals. Exit 0 when nothing was refused, including when nothing matched. Exit 1 on any refusal, including a folder the walk could not read |

**`--stale` is recognised in any slot, in any spelling that starts with it.** The plain lane reads
every token as a path to delete, so a flag that slipped past detection would not fail; it would
delete. Standing in @api, `drone rm api_json --stale 10d` is a stale sweep, not a removal of
`api_json`. `--stale=10d` is read. `--staleness`, a repeated `--stale`, and any other `-` token in
stale mode (most likely a mistyped `--dry-run`) are refused before anything is walked.

Proved from a branch directory, dry run only, on 2026-09-11: the old-era `tmpXXXXXXXX.tmp` temps
dominate the match set, concentrated in a handful of `*_json/` folders, and the new-era
dot-prefixed temps were all younger than the age given and correctly skipped. The first real sweep
is @prax's scheduled job (DPLAN-0338 wave 2). Re-measure with `--dry-run` rather than quoting that
run: the number is a moment, the command is the truth.

---

## Related

- [broker.md](broker.md) — the other delete lane, and how it verifies a path
- [caller_identity.md](caller_identity.md) — where the `caller` field comes from
- [known_issues.md](known_issues.md) — the forged records in the live store
