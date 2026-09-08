# Docs

Tracked, public reference for `@ai_mail` — the inter-agent messaging branch.

**This is the only one of the four directory stubs that rides a PR.**
`docs.local/`, `dropbox/` and `artifacts/` are gitignored by design (repo root
`.gitignore` lines 55–58), so anything written there is invisible to a reviewer
and to a fresh clone. If a document needs to survive review, it goes here or in
`README.md`; anywhere else is a local note, whatever it is titled.

Durable reference lives here — write-ups that outlive the session that produced
them and that another branch may need to read. Session scratch, research dumps
and agent working files belong in `docs.local/`.

Contents:

- `s84_multiline_reply_truncation.md` — the multiline reply truncation defect
  and its fix.

The branch's own operating reference is `../README.md`: the mail store layout,
the notification feed, the dispatch register (including `monitor_pid` /
`monitor_alive` and the close-on-reply rule), and the measured test numbers.
