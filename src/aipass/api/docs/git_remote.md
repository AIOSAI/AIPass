# The remote git lane

**Branch** api · **Code** `apps/handlers/host/git_reads.py` (remote verbs)
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

---

## The remote lane (DPLAN-0303 phase 4)

*Lives in `git_reads.py`. Was `remotes.py`, archived under
`apps/handlers/host/.archive/`, not deleted.*

Phase 4 is links-first: zero-auth link-cards to GitHub from constructible URLs,
so the face must be told the repository's remote.

**No door existed, so the lane lived apart** in its own module, that boundary
visible rather than buried under the git roof. Measured before design: not a verb
on drone's git surface, not on their public Python surface, and the fleet's gate
refused **both** raw readers, declining to call them reads. So it shelled
nothing: read the repository config as the INI file it is, chased `.git` pointer
files by hand for worktrees.

**`drone @git remote --json` shipped on 08-18 and retired all of it**, worktree
pointer-following included: git resolves commondir itself. 127 lines of functions
went outright — INI parse, pointer chase, remote selection off raw config. Their
replacement is a door call like every lane's, so the pin inverted: the *no
subprocess ever spawned here* test now asserts this lane routes through drone in
machine mode, and a second pin watches `Path.open` across the call for git's own
resolution growing back by any spelling.

**Two fields because they are two facts.** `url` is configured verbatim; `web` is
what a browser can open; collapsing them would lie about one. `web` drops the
clone suffix: `/pulls` on a `.git` URL 404s on every forge there is. The ssh forms
(scp-short, `ssh://`, `git://`) become `https`, having no browsable shape; **`http`
stays exactly as configured**, upgrading being this lane deciding something about a
host it cannot know. A filesystem-path remote gets `web: null`: a directory is not
a page. Trap: a Windows path carries a colon like `host:path`, so both halves are
checked — `C:\repos\thing` as a remote would emit a link card pointing at a machine
named C.

**Which remote answered is part of the answer.** `origin` wins by convention when
several exist, but `remote` travels either way: refusing a repository that named
its remote otherwise invents a rule that does not exist; choosing silently hides
the choice from the caller.

**A repository with no remote is refused in words — not hypothetical: two projects
in the real tree have none.** Verified live against the real Sentinel repo, which
answers `400 read_refused` with the sentence. An empty string would render as a
link card pointing nowhere.

**Credentials never travel** — not in the ask, and the doctrine outlived the module
that carried it. drone redacts too; this lane redacts again as the last stop before
a network: a rule living only in someone else's code dies silently the day that
code changes. Pins assert what **this** surface emits, never what upstream sent —
one feeds it a document claiming `redacted: true` that still carries the token. A
URL may carry `user:token@` (a machine cloning a private repository unattended),
and handing it to a client over a network is this lane's whole job. Password half
replaced, user half kept so an operator recognises their configuration, `redacted`
set so the change is not silent. The browsable form carries no userinfo. Bare
`git@`, the standard ssh user, is **not** flagged: an alarm on the commonest remote
form is one nobody reads. Nor does the URL reach an audit line; the log records
which remote answered and whether redaction fired, nothing else.

Verified live: the seat and a foreign project (`AIPL`, via @baud's census) both
return their GitHub URLs; Sentinel refuses; 8 mutations against this lane all bite.
One seemed to survive: its anchor had not matched, so the mutation never applied
and the green run proved nothing; re-run properly before counting.

Re-verified after the move to the door (08-18): 16 mutations across the whole
`--json` parse layer, all 16 biting under `PYTHONDONTWRITEBYTECODE`. **Two survived
the first pass — real gaps, not harness noise.** One flagged every userinfo as a
credential and lived: the only `git@` test used the scp short form, which carries no
`://` and leaves the redactor at its first line, never reaching the rule it was
meant to pin; an explicit `ssh://git@` case now does. The other dropped the log's
object-name requirement and lived: nothing fed it a commit row without a sha. Both
pins added; both mutations then bit.

Sixteen mutations against the finished lanes all bite too, `PYTHONDONTWRITEBYTECODE`
set so a same-length mutation cannot serve a stale `.pyc`. Live-verified end to end:
repo grain identical to raw porcelain **path and code**, 15 of 15; log shas identical
to raw; one file of one commit carrying no commit header; an untracked probe named
with `??` at both grains, out of the tracked list. One probe came back invisible; the
cause was checked, not assumed — `.tmp` is gitignored here, so the lane was right to
drop it.

**The one sentence this lane writes itself** is a write's `detail`. @memory's refusals
carry prose and it travels verbatim; their success payloads carry facts and no prose,
so `detail` is composed here from the values *they just returned*, never from those
sent to them. A `detail` field on their side retires it, and has been asked for.

**Every error answers `{"error": {"code", "message"}}` — including the ones this
server does not raise.** Validation fires in *front* of every handler, so it used to
emit FastAPI's `{"detail": [...]}`: a client coding to the documented shape lost the
sentence on every validation error, on every route. @baud found it: the owner's phone
read "HTTP 422" while the body named the exact field. Validation is now normalised
into the envelope, `{"code": "invalid_request", "message": "image: Field required",
"fields": [...]}`, the structured original kept beside the sentence: wider envelope,
nothing taken away.

---

[← api README](../README.md)
