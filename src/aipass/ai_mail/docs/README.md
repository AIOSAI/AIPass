# Docs

Tracked, public reference for `@ai_mail` — the inter-agent messaging branch. The index with
one line per page is in [../README.md](../README.md); this page says what belongs here.

**This is the only one of the four directory stubs that rides a PR.** `docs.local/`,
`dropbox/` and `artifacts/` are gitignored by design, so anything written there is invisible
to a reviewer and to a fresh clone. If a document needs to survive review, it goes here or
in `README.md`; anywhere else is a local note, whatever it is titled.

Durable reference lives here — write-ups that outlive the session that produced them and
that another branch may need to read. Session scratch, research dumps and agent working
files belong in `docs.local/`.

**The shape of a page here** (DPLAN-0347, the layer contract): one file per module or
handler group, each small enough to read in one go, opened when something breaks rather than
at startup. The README is the face — purpose, how to reach me, a pointer to the generated
command surface, and the index of this directory. Depth is here. Breadcrumbs and the
directory tree are in `.aipass/aipass_local_prompt.md`, once, so they cannot disagree with
themselves.
