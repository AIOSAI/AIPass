[<- Back to the README](../README.md)

# The git surface

**Branch** api · **Code** `apps/handlers/host/git_reads.py`

---

## The git surface (DPLAN-0303)

*Where it lives: repository reads, the remote lane included, are in `git_reads.py`;
files, directories and the name fence are in `reads.py`. The split follows the
1500-line cap along the seam that was already there. The dependency runs one way:
the repository reads lean on the resolution, never the reverse.*

**Every door here is asked in machine mode.** The status, log, show and remote lanes
ask `--json` and read the document, with the document's own `ok` deciding refusals.
That is not tidiness. drone's rendered status line is built as
`f"  {status.strip():>2} {path}"` — their comment calls it *"for the screen only"* —
which right-aligns a one-letter porcelain code into the **second** column, so on the
screen surface every index-only change reads as a worktree one: `M ` as ` M`, `A ` as
` A`, `D ` as ` D`, and staged-vs-unstaged modify and delete collapse into one answer.
No parsing can recover columns that are gone before this process sees them. The
refusal split follows the @memory config precedent: `ok: false` is an **answer** and
travels as a 400 in their words; output that is not one JSON object is a 503, which is
also the shape drone's caller-verification refusal takes, since that one never reaches
the door and leaves its sentence on stderr.

**Doors without a full machine mode, said so rather than worked around:**
`drone @git diff` has no `--json` at all, so that half reads an exit code.
`drone @git show --json` is an **envelope** — its `content` is git show's own text —
so the commit lane parses that text on structure, and only its failure detection
reads the document. `drone @git show <ref> <path> --json` returns the file's
*contents* at that ref, not a per-file diff, so the per-file split stays server-side.

**Two grains, and every answer names its own.** The card's git tile is per-branch;
the git *app* is per-repository. Both are honest and
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

**Two door limits shape the lanes:**

- **`drone @git diff` takes no path and no `-U`.** `_handle_diff` recognises
  exactly `--staged` and `--all`; everything else in argv is ignored, `--json`
  included. So `path` is served by generating the patch and splitting it here, on
  the per-file headers — machine structure, which is the only thing this file still
  parses out of text anywhere. **Context stays at three lines, not the `-U1` the
  design specified**, because context is baked in at generation time.
- **`drone @git log` is `--oneline` underneath, `--json` or not.** A row carries
  a sha and a subject and nothing else — no author, no relative date; the document
  has exactly the two fields the rendered line has. The door does not clamp either:
  asked for any count it returns up to the whole history, so this lane's own 1–50
  refusal is the only thing between a phone and every commit in the repository.
  Author and date live in `show`, one commit at a time, and fifty subprocesses each
  dragging a whole patch is not a list lane. `/v1/git-log` serves what exists;
  `/v1/commit` carries the author and date for the one commit being looked at.

**The 512KB cap changes meaning per file, deliberately.** The whole-tree case
still truncates and *reports* it, because a wall of text degrades into a shorter
wall. One file cannot: half a patch is not a small patch, it is a severed hunk
that renders as nonsense, so an over-cap single file is **refused** with its
size and the cap in words. A file with no changes in the patch is likewise
refused naming it — an empty string would read as "no changes, rendered fine",
and a tap on a stale list is a real event.

**± counts come from inside the hunks only.** The two file-header lines start
with the same characters as a changed line; counting them would add one phantom
addition and one phantom deletion to *every file in every commit*. The same
ordering rule protects filenames — a block's header is emitted before its first
hunk, so a deletion of a line reading `-- x` (which produces exactly `--- x`) can
never be read as the file's name.

**Status rides per row, in git's vocabulary and not a new one.** `rows[]` carries
every changed path with its code **verbatim and unstripped**, plus `index` and
`worktree` split out beside it, read from the `--json` document so the two columns
arrive as two columns. All four VS Code chips (M/A/D/U) are derivable from `index`
and `worktree`, and staged-vs-unstaged is a difference the phone can see. Which code
means which chip is the face's decision, made once in their `buildRows`; a letter
invented here would be a second vocabulary for a fact git has already stated.
Untracked paths appear in `rows` by name and stay **out** of `files` and `count` —
additive, so @baud's desktop consumer parses exactly what it always did, and
untracked names leaking into the tracked list is the precise disagreement this lane
exists to avoid. Ignored paths are in no list at all.

---

[← api README](../README.md)
