[<- Back to the README](../README.md)

# `rm` and the record — every move and delete leaves one

**Branch** drone · **Code** `apps/modules/rm.py`, `apps/handlers/rm_handler.py`,
`apps/handlers/deletion_log.py`

`drone rm` is the fleet's only sanctioned delete path — raw recursive `rm` is gate-blocked — which
makes it the choke point where the record belongs: if something deletes, there is a record of it.
Inside the project it deletes nothing; the target moves to the `.archive` beside it. The rules and
the flags are `drone rm --help`.

---

## Inside the project, a move

A target under the project root moves to `<its folder>/.archive/<its name>`, the `.archive` made if
absent. From the caller's side it is gone and out of the way; nothing is lost.

- **One `os.rename`, never a copy.** It moves whole or not at all: a directory goes whole, and a
  target on another device fails with the error rather than a half-done copy. A failure is recorded
  `failed` and logged at ERROR.
- **Nothing is overwritten.** A name already in that `.archive` keeps both: the new one is
  `<name>.<YYYYmmdd-HHMMSS>`, with `-2`, `-3` added if that is taken too.
- **A target inside a `.archive`, or the `.archive` itself, is refused.** Emptying an archive is the
  owner's, by hand.
- **A symlinked `.archive` is refused**, because the rename would carry the target out of the tree.
- **A symlink target moves as the link**; what it points at is untouched.
- **The fences are the same** as for a delete: carve-outs, sibling branches, a folder holding a
  citizen. A move is judged before it runs, exactly as a delete was.

Truly deleted, and only where an archive keeps nothing worth having, each case named in
`rm_handler.py`: files in the system temp dir (outside the project), Python bytecode
(`__pycache__`, `*.pyc`, rebuilt on the next import) and stale-mode temps. Everything else is
moved. The broker lane (`apps/handlers/broker/daemon.py`) still deletes; `drone rm` never routes
through it.

Each result prints as a verdict line, then every path whole on a line of its own (a move shows the
source, then `-> ` and the destination), unwrapped, so a long path copies intact. A refusal ends
with a line saying the attempt is recorded, and a sibling-branch refusal names the next step: mail
@devpulse the path and why.

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
`path` (resolved), `reason`, `kind`, `size_bytes`, `entry_count`, `measured`. A move's record has
outcome `moved` and one key more, `moved_to`, the path it now lives at; the admin seat's crossing
of the sibling guard adds `exemption: "admin"`. A stale-mode record
carries two more, `mode` and `age` (as typed), and its prax line names both; a plain delete's
record keeps exactly the twelve, byte for byte.

Four things worth knowing:

- **Refusals are records too.** A blocked delete leaves no other trace of what was attempted, which
  is exactly what makes it worth finding later. Refused paths are deliberately *not* measured — the
  guard just said that tree is off-limits, so nothing goes and reads inside it. Their `kind` comes
  from one `lstat` of an absolute path (`file`, `directory`, `symlink`), which reads nothing inside;
  sizes stay null and `measured` stays `none`.
- **Measurement happens before the move or delete.** After a delete there is nothing left to ask
  how big it was. Directory walks stop at `_MEASURE_ENTRY_CAP` and say so via `measured: "capped"` rather than
  paying an unbounded walk.
- **Severity is INFO, ERROR only for a break.** A move, a delete and every deliberate refusal
  (containment, carve-out, sibling, `.archive`, a symlinked `.archive`, stale-mode DIRs) log at
  INFO: a refusal is the fence doing its job, already shown to the caller and kept in the ledger.
  An operation that was tried and broke (an `OSError`) is outcome `failed` at ERROR. WARNING is kept
  for a check that could not run: the admin rail dark, a kind or folder that could not be read.
- **Each channel tells the whole story alone.** The ledger's prax line reads
  `rm ledger: <outcome> <path>[ -> <moved_to>] by <caller>, lane <lane>[, exemption admin] (kind, ...)`;
  rm's own line reads `rm: <outcome> <path>[ -> <moved_to>] by <caller>[, admin exemption] — <reason>`.
  The json service's `deletion_record` entry carries `moved_to` and `exemption` when present, and
  `rm_command` stores every target under `targets`.
- **The record follows the deletion's project, not the process's.** `deletion_log_path()` takes an
  optional `project_root`, and the broker passes the `repo_root` it was constructed with. A daemon
  can serve a repository it is not standing in; resolving the store from cwd there files the record
  under the standing project instead. `AIPASS_DELETION_LOG` still outranks
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

Another branch's removals reach the same store through `apps/modules/door_deletion_log.py`, whose
one export `record_deletion()` takes `lane`, `outcome`, `caller`, `requested`, `resolved`, `target`
and `reason`, plus an optional `measurement` keyed like `measure()`'s and an optional
`project_root`. Its row reads back beside `rm`'s, with `target` added. It raises `ValueError` on an
empty `lane`, `outcome`, `caller`, `resolved` or `target`, or on a measurement with other keys, and
writes nothing: a half row is refused. @spawn's branch and project retirements write through it
under the `spawn_delete` and `spawn_retire` lanes.

The door's second export, `record_gate_refusal()`, records a `drone rm` the hooks rm gate refused
before drone ran. It writes lane `rm_gate`, outcome `refused`, and takes `caller`, `cwd`,
`requested` (the text as typed), `resolved` (a path, or `None` when the gate could not resolve it;
`path` is then null), `reason` and an optional `project_root`. An empty `caller`, `cwd`,
`requested` or `reason` raises `ValueError` and writes nothing. A store that cannot be written raises the `OSError`
after its ERROR line; the `drone rm` lanes log that failure and carry on.

---

## Sibling-branch guard — outermost `.trinity` wins

The guard refuses deletes inside another citizen's tree, and it finds the owning citizen by walking
up for `.trinity/`. It takes the **outermost** hit within the project, not the innermost, because
`.trinity/` is not proof of a citizen: @spawn ships a complete branch skeleton under its templates,
passport and all.

Innermost-wins would name a template in a refusal, which has no mailbox to appeal to, and would
lock @spawn out of its own templates, because a skeleton's name never matches the branch you are
standing in. The commit gate maps a file to its branch by the same outermost rule.

Safe because nothing above a branch carries `.trinity/` — not the project root, not `src/`, not
`src/aipass/` — so the outermost hit inside the project *is* the citizen. The walk stops at the
project boundary.

### The admin seat crosses it

The verified admin seat, and only it, works inside every branch: for it the sibling guard does not
apply, and the target moves into the `.archive` beside it, in that branch. The record carries
`exemption: "admin"` beside the caller, and the result line says the fence was crossed.

- **Verified on @ai_mail's rail**, the one the hooks gates use: `repo_door.admin_verdict()` stamps
  the caller and asks `door_verified_caller.is_verified_admin_caller()`, the 5-leg grant. Never a
  name, a cwd string or an env var the caller sets.
- **Fails closed.** An unimportable rail or a raising verifier is a refusal, logged at WARNING; a
  plain no is logged at INFO. Either way the sibling refusal stands as it reads for everyone.
- **Asked only when the guard would refuse**, per path, never cached.
- **Still refused for the admin:** every carve-out (judged first), a target inside a `.archive`,
  the sibling's branch root itself (retiring a citizen is @spawn's), and a folder that contains a
  citizen, which is a separate guard below.

---

## A folder that contains a citizen

The sibling guard walks **up** from the target, so it only sees a citizen the target sits *inside*.
Nothing above a branch carries `.trinity/`, so a target above the branches passes it. From any
branch, `drone rm ..` is `src/aipass/` and `drone rm ../..` is `src/`. Both pass containment, and
rmtree would take every branch, `.trinity/` and all, so a second guard looks the other way.

`check_contained_citizens()` walks **down** and refuses at the first foreign citizen, naming it.

- **Bounded.** The walk is sorted and stops at the first foreign `.trinity/`. The live `..` answers
  in about a millisecond.
- **The walk skips the caller's own tree**, template skeleton included (outermost-wins makes the
  skeleton the caller's). A target already inside a branch returns at once, because the sibling
  guard has answered for everything below it.
- **A target that is the caller's own branch, or holds it, is refused** by a check of its own after
  the walk: `drone rm .` and `drone rm ..` from a branch both refuse with `Protected: path is your
  own branch <name>/ or holds it`.
- **Unchanged:** targets inside the caller's own branch, and targets in the system temp dir, where
  a `.trinity/` is test scaffolding, not a citizen. Stale mode is unaffected; it never reaches this
  lane.
- **A symlink is not a citizen.** rmtree unlinks the link and never touches what it points at.
- **A folder the walk cannot list refuses the delete.** A guard that could not look must not report
  clear.
- **You may delete the folder you are standing in.** Removing a folder of your own branch while
  standing in it completes.
- Refusals are recorded like every other refusal. A caller standing outside every branch finds
  every citizen foreign.

The delete acts on the **resolved** path, the one every guard judged, never the path as typed: a
typed `spawn/..` would empty the tree and then fail its last `rmdir`, because `spawn` is gone by
then, and the ledger would record `failed` for a delete that happened.

---

## Stale mode — `drone rm --stale`

`drone rm --stale AGE [--dry-run] DIR [DIR...]` sweeps staging temps: the `*.tmp` a staged write
(temp + fsync + rename) leaves behind when its process is killed between the two. It
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

To see what a sweep would take, run it with `--dry-run`: the match set is a moment, the command is
the truth.

---

## Related

- [broker.md](broker.md) — the other delete lane, and how it verifies a path
- [caller_identity.md](caller_identity.md) — where the `caller` field comes from
