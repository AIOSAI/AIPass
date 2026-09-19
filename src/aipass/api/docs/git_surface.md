# The git surface

**Branch** api · **Code** `apps/handlers/host/git_reads.py`
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

---

## The git surface (DPLAN-0303)

*Where it lives: `git_reads.py`. The read lane started as one module and the
git surface grew until it crossed the 1500-line cap, so it split along the seam
that was already there — repository reads in `git_reads.py`, files and
directories and the name fence in `reads.py`. The remote lane lived apart in
`remotes.py` for one reason, that it shelled nothing at all; `drone @git remote
--json` retired that reason on 08-18 and it moved in with the other drone-door
readers. The dependency runs one way: the repository reads lean on the
resolution, never the reverse.*

**Every door here is asked in machine mode — and one of them had been lying.**
Since 08-18 the status, log, show and remote lanes ask `--json` and read the
document, with the document's own `ok` deciding refusals. That is not tidiness.
drone's rendered status line is built as `f"  {status.strip():>2} {path}"` —
their comment calls it *"for the screen only"* — which right-aligns a one-letter
porcelain code into the **second** column. So every index-only change reached
this server already dressed as a worktree one: `M ` arrived as ` M`, `A ` as
` A`, `D ` as ` D`. Measured against the shipped parser before the switch: of
six codes fed through drone's own renderer, **three came back as something git
never said**, and staged-vs-unstaged modify and staged-vs-unstaged delete were
each a single answer. No parsing could have recovered it — the columns were gone
before this process saw them. The refusal split follows the @memory config
precedent: `ok: false` is an **answer** and travels as a 400 in their words;
output that is not one JSON object is a 503, which is also the shape drone's
caller-verification refusal takes, since that one never reaches the door and
leaves its sentence on stderr.

**Measured shut, and said so rather than worked around:** `drone @git diff` has
no `--json` at all, so that half still reads an exit code. `drone @git show
--json` is an **envelope** — its `content` is git show's own text — so the
commit lane still parses that text on structure, and only its failure detection
moved. `drone @git show <ref> <path> --json` returns the file's *contents* at
that ref, not a per-file diff, so the per-file split stays server-side. The
brief for this round expected ~385 lines of scraping to retire; two of the three
doors did not carry what that assumed, and reporting the smaller true number was
cheaper than shipping against a shape nobody had measured.

The owner, on the phone's git screen: *"git diffs are pretty much useless. we need
a real diff setup."* The wall of text was one 308KB response. Tapping one file
in the same repository is now 5.8KB — **53× less**, measured on a real tree.

**Two grains, and every answer names its own.** The card's git tile is per-branch;
the git *app* is per-repository (the owner's ruling, 08-17). Both are honest and
they are not the same number, so `grain` is a parameter *and* a response field —
a file list that does not state its scope is one a client can silently read at
the wrong one. `grain=branch` keeps @baud's card contract untouched, including
its branch-local names. `grain=repo` reaches every branch in the repository and
**keeps the repo-relative names**, because there the prefix *is* the part that
distinguishes one branch's file from another's. A typo'd grain is refused naming
both, before any subprocess exists — falling back to a scope nobody asked for is
how a phone shows one branch while believing it shows a repository.

**A commit is always repo-wide, and the answer says so rather than obeying.**
Asking `/v1/git-log` or a `ref` for branch grain is *refused*, not silently
ignored: drone's log door runs from the repo root with no pathspec, so a branch
names *which repository*, never which history. Silently ignoring a parameter is
a lie told by omission.

**Two doors were measured shut, and neither is worked around in silence:**

- **`drone @git diff` takes no path and no `-U`.** `_handle_diff` recognises
  exactly `--staged` and `--all`; everything else in argv is ignored, `--json`
  included — re-measured 08-18, still the one door with no machine mode. So
  `path` is served by generating the patch and splitting it here, on the
  per-file headers — machine structure, which is the only thing this file still
  parses out of text anywhere. The consequence
  DPLAN-0303 needs to know: **context stays at three lines, not the `-U1` the
  design specified**, because context is baked in at generation time. Asked of
  @drone.
- **`drone @git log` is `--oneline` underneath, `--json` or not.** A row carries
  a sha and a subject and nothing else — no author, no relative date, however
  much a design asks for them; the document has exactly the two fields the
  rendered line had. Re-measured 08-18, and the door does not clamp either:
  asked for 99999 it answered with 1626, every commit in the repository, so this
  lane's own 1–50 refusal is the only thing between a phone and a whole history. Those live in `show`, one commit at a time, and fifty subprocesses each
  dragging a whole patch is not a list lane. `/v1/git-log` ships what exists;
  `/v1/commit` carries the author and date for the one commit being looked at.
  Asked of @drone.

**The 512KB cap changes meaning per file, deliberately.** The whole-tree case
still truncates and *reports* it, because a wall of text degrades into a shorter
wall. One file cannot: half a patch is not a small patch, it is a severed hunk
that renders as nonsense, so an over-cap single file is **refused** with its
size and the cap in words. A file with no changes in the patch is likewise
refused naming it — an empty string would read as "no changes, rendered fine",
and a tap on a stale list is a real event.

**± counts come from inside the hunks only.** The two file-header lines start
with the same characters as a changed line; counting them adds one phantom
addition and one phantom deletion to *every file in every commit*. Verified
against `git show --numstat` on a real 20-file commit: **20 of 20 rows
identical**. The same ordering rule protects filenames — a block's header is
emitted before its first hunk, so a deletion of a line reading `-- x` (which
produces exactly `--- x`) can never be read as the file's name. A guard at the
hunk boundary was written for that and then **deleted**: no mutation could kill
it, which is what proved it unreachable rather than careful.

**Status rides per row, in git's vocabulary and not a new one — and since
08-18 the data finally honours the contract.** @devpulse measured the first half
of the gap from the face: the lane read the porcelain code and then *discarded*
it, and untracked files never left the server as anything but a number. `rows[]`
carries every changed path with its code **verbatim and unstripped**, plus
`index` and `worktree` split out beside it. The second half was worse and took
the `--json` door to find: the code being passed through verbatim had *already*
been flattened by drone's screen rendering, so `A ` (staged new) and ` M`
(modified, unstaged) had been the same answer here for as long as rows existed.
All four VS Code chips (M/A/D/U) are derivable from `index` and `worktree` now,
and staged-vs-unstaged is a difference the phone can finally see. Which code means which chip is the face's decision, made once in their
`buildRows`; a letter invented here would be a second vocabulary for a fact git
has already stated. Untracked paths appear in `rows` by name and stay **out** of
`files` and `count` — additive, so @baud's desktop consumer parses exactly what
it always did, and untracked names leaking into the tracked list is the precise
disagreement this lane exists to avoid. Ignored paths are in no list at all.

---

[← api README](../README.md)
