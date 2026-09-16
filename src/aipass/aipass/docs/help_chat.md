# The help chat, and its model

*What answers `aipass help <question>` — and why there is no LLM behind it.*

## The model is a keyword model

There is no model call. `aipass help` is scripted keyword lookup, chosen so the
front door costs nothing to ask:

1. Keywords come out of the question by stopword filter — no ML, no embedding.
2. Those keywords are matched against branch names and README paths.
3. Each matched branch's `README.md` is **live-read** from disk.
4. The best-matching sections come back whole, heading-bounded, rendered as
   Markdown with a line-range citation like
   `(src/aipass/drone/README.md:3-8)`.
5. Depth is always offered: view the full README, or dispatch the question to
   the branch that owns it.

The one thing cached is the branch-name → README-path map. Content is never
cached: every question re-reads the real file, because a stale answer is worse
than a slow one. That is why a branch's README is worth keeping honest — it is
what this command quotes.

Free text falls through to it. `aipass what does drone do` and
`aipass help what does drone do` are the same call, because multi-word input
that matches no command reads as a question. A single unknown word does not —
it is far more likely a typo, and it gets an unknown-command answer.

Code: [`apps/modules/help_chat.py`](../apps/modules/help_chat.py), with the
path lookup and live reads in
[`apps/handlers/readme_map/`](../apps/handlers/readme_map).

## Reading a whole README — `aipass read`

`aipass read <branch>` renders a branch's README in the terminal, live-read the
same way. Bare `aipass read` prints module info and the branch list rather than
a page. This is the right command when the help chat's section answer is not
enough and you want the whole face.

Code: [`apps/modules/read.py`](../apps/modules/read.py).

## Where the README index comes from

`readme_map` resolves the AIPass root in three steps: `AIPASS_HOME` if it is
set, otherwise by walking up from its own file to the directory that contains
`src/aipass/`, and the root is that directory. Nothing is hardcoded, so the
same code answers from a source checkout, an installed package or a project.

---

[← Back to the AIPASS README](../README.md)
