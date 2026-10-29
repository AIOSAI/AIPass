[<- Back to the README](../README.md)

# The update engine

**Branch** spawn · **Code** `apps/handlers/update_ops.py`, `apps/handlers/update_ignore.py`,
`aipass.aipass.shared.json_ops`, `apps/modules/update.py`

Update is **preview-only by default**; `--apply` is what executes. The verbs and flags live
in `drone @spawn update --help`. Everything below is what the engine decides once it runs.

---

## The walk

The engine walks the template and decides per path — no renames, no pruning, no snapshot
phase.

1. **Resolve** — Branch path from the registry, citizen class from its passport, template
   directory from the class.
2. **Owner protection** — Read the branch's and the project root's `.updateignore` and drop everything either claims,
   before any other rule. An `.updateignore` that exists but cannot be read raises
   `UpdateIgnoreUnreadable` before any write; `update <class> --all` reports it and goes on
   to the next branch.
3. **Directories** — Walk the template's directories and create any the branch is missing.
   Anything named in `file_ops.SKIP_NAMES` (tool caches, `.git`) is skipped, the same set
   the mint skips.
4. **Files** — Walk the template's files and decide per file: missing → add (placeholders
   replaced, atomically written) · existing `.py` → **skip by design** · existing `.json` →
   deep merge (existing values win, plus the list policy below), written and backed up only
   when the parsed document changes, never for key order alone · existing `.md` → compare
   and report, never write · `passport.json` → heal against a narrow allowlist only
   · create-only paths → skip entirely · a file already present under a
   `dropbox/` or `.archive/` directory → never read, compared or merged, and no report row
   (a missing one is still added).
5. **Refresh** — Regenerate `.spawn/.branch_meta.json` with current state.

---

## `.updateignore` — the owner decides what update skips

A branch protects its own files with a `.updateignore` at its root, beside `.trinity/`.
Same fashion as `.gitignore` and `.backupignore`: one pattern per line, `#` comments, blank
lines ignored, a trailing `/` for a directory and everything under it, and a pattern with no
slash also matching that filename at any depth. No negation in v1.

```
.trinity/passport.json
docs.local/
```

The `.updateignore` at the project root, beside the `*_REGISTRY.json` the update resolves,
protects that project's citizens too. Its patterns match the file's project-relative path, the
`.gitignore` model: a pattern with a slash is root-relative, so
`src/vera_studio/*/docs.local/` claims every citizen's `docs.local/`, and a slashless name
such as `README.md` matches at any depth. The branch's own file is optional, for a citizen's
own claims. Both are read before the walk, branch first, then root; a file either one claims
is skipped. An unreadable root file refuses the update the same way. A branch outside its
registry's root takes no root patterns.

A matched file is **never written, never merged, never backed up**, and the preview reports
it as a skip on its own line rather than as a warning — an owner-protected file is a
decision already made. Spawn never creates or modifies the file; its absence protects
nothing.

One name, two doors: `aipass init update` honours the same contract at *project* roots, so
an owner learns the syntax once. With a passport named in the ignore file, the passport is
the owner's, and the rest of the update proceeds instead of being refused wholesale.

The parser here is spawn's own copy on purpose: branches never import each other's
handlers, and the contract is small and frozen. If it grows, it grows in the plan first and
both doors follow.

---

## Markdown is reported, never written

The engine compares an existing `.md` against the **rendered** template and reports one
line per file: `matches`, `differs`, `absent` (it was missing, so it was added), or
`unreadable` when either side cannot be decoded as text. Unreadable is its own answer rather
than a guessed `differs`. The template is rendered with the branch passport's own purpose and
class; `{{DATE}}` renders as today, so a README stamped on an earlier day still reads `differs`.
A branch `.gitignore` is compared and reported the same way, one state per branch, and never written.

Nothing is written. A README or branch-prompt diet is the owner's judgment about what to
keep and what to move into `docs/`, not something a template overwrite can perform: every
branch's README and branch prompt differ from the template, so a guarded overwrite would
reach none of them and an unguarded one would erase each branch's own content.

---

## The list policy

`deep_merge` is additive for KEYS and existing-wins for VALUES, and a non-empty list is a
value: by default, a list entry ADDED to a template after a branch was born never reaches
that branch. Both halves of that behaviour are wanted, for different lists, so the split is
declared by name in `_TEMPLATE_OWNED_LISTS`:

- **Template-owned lists are additive.** Today that is `.spawn/.registry_ignore.json` →
  `ignore_files`, `ignore_patterns`, `patterns`. They are copy-engine machinery — spawn
  writes them, spawn reads them, and a missing entry is a scaffold that does not work.
  Template entries the branch lacks are appended; the branch's own entries and their order
  are never touched, so the list is only ever grown, never reordered or pruned, and a second
  pass reports `unchanged`.
- **Every other list stays existing-wins**, which is `deep_merge`'s default and needs no
  code. That includes `.claude/settings.local.json` permissions, which read like
  template-owned safety rules and are not: the branches that differ do so deliberately —
  the one citizen allowed to write the repository history carries many more deny rules than
  the template, and a union would re-deny the fleet's only publishing lane. Permission drift
  is a branch's own posture; it is handled by hand, never merged.

---

## The passport heal is not a migration

The heal repairs three derived fields (`branch_info.email`, `branch_info.git_branch`,
`identity.traits`) and every one of them exists in schema 1.0.0 and 2.0.0 alike, so a 1.0
passport gains no 2.0 shape and no version bump from an update and comes back
`unchanged`. Changing schema is `migrate-passports`' job and it
either completes (every field the target schema requires, `schema_version` bumped in the
same write) or raises `PassportMigrationError`; there is no partial write.
`tests/test_update.py` pins both halves, including the rule that any field added to the heal
allowlist must exist in every schema version it can meet.

The heal also answers "did anything change?" about the DOCUMENT, not about how it was
spelled. Passports written with `ensure_ascii=True` carry an escape where the heal's
serialiser writes the character itself, so the heal compares parsed documents: a passport
that differs only in escaping is `unchanged` and is not rewritten.

---

## Create-only paths

Never re-added, never overwritten: everything under `.trinity/` except the passport heal,
everything under `.ai_mail.local/` (a live mailbox is @ai_mail's data, not spawn's), plus
`DASHBOARD.local.json`, `artifacts/birth_certificate.json`, `.seedgo/bypass.json` and
`tests/test_scaffold.py`.

`.py` files are skipped by design in every branch, which is why a template `.py` change
needs a dispatch to the branch that owns the file rather than a fleet update.

---

## Batch updates

`update <class> --all` walks the registry, skips spawn itself (the lane runs in spawn's own
process, so it cannot rewrite the module it is executing), and reports per branch plus a
totals line: additions, updates, py-skipped, owner-protected, and markdown drift reported
but never written. With no `*_REGISTRY.json` above the cwd it exits 1.

---

**Last Updated:** 2026-10-24
