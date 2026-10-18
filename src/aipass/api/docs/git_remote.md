[<- Back to the README](../README.md)

# The remote git lane

**Branch** api · **Code** `apps/handlers/host/git_reads.py` (remote verbs)

---

## The remote lane

The lane is links-first: zero-auth link-cards to GitHub from constructible URLs, so the
face must be told the repository's remote. It lives in `git_reads.py` with the other
drone-door readers.

**It reads `drone @git remote --json`, like every lane's door call.** git resolves
worktree pointers and commondir itself, so nothing here parses repository config or
chases `.git` pointer files. A pin asserts the lane routes through drone in machine mode,
and a second watches `Path.open` across the call so git's own resolution cannot grow
back here by any spelling.

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

**A repository with no remote answers 200 with `remote: null`**:
the same shape, with `remote`, `url` and `web` all `null` and `redacted` false.
Projects in the real tree have none, and the phone reads `remote === null` as "no
remote configured". A repository the door cannot read stays a refusal, and a named
remote carrying no URL is refused rather than served as a link card to nowhere.

**Credentials never travel**, not in the ask. drone redacts too; this lane redacts
again as the last stop before a network: a rule living only in someone else's code
dies silently the day that code changes. Pins assert what **this** surface emits,
never what upstream sent — one feeds it a document claiming `redacted: true` that
still carries the token. A URL may carry `user:token@` (a machine cloning a private
repository unattended), and handing it to a client over a network is this lane's
whole job. Password half replaced, user half kept so an operator recognises their
configuration, `redacted` set so the change is not silent. The browsable form carries
no userinfo. Bare `git@`, the standard ssh user, is **not** flagged: an alarm on the
commonest remote form is one nobody reads. Nor does the URL reach an audit line; the
log records which remote answered and whether redaction fired, nothing else.

**The one sentence this lane writes itself** is a write's `detail`. @memory's refusals
carry prose and it travels verbatim; their success payloads carry facts and no prose,
so `detail` is composed here from the values *they just returned*, never from those
sent to them.

**Every error answers `{"error": {"code", "message"}}` — including the ones this
server does not raise.** Validation fires in *front* of every handler, so FastAPI's
`{"detail": [...]}` is normalised into the envelope: `{"code": "invalid_request",
"message": "image: Field required", "fields": [...]}`, the structured original kept
beside the sentence. A client coding to the documented shape gets the sentence on
every validation error, on every route.

---

[← api README](../README.md)
