# The ritual — updating a project's scaffold

*Why a merge to main does not bring a project's scaffold forward, and the one
sequence that does.*

Code is shared, scaffold is not. Every project's `.venv` is a symlink to the
AIPass runtime and hooks run from `$AIPASS_HOME`, so a merge to main updates
the *code* under every project the moment it lands. Only the project-local
files — `tier0_kernel.md`, `tier1_navmap.md`, `hooks.json`, the Claude
settings, `prep.md` — lag behind. **`setup.sh` never touches a project**; it
installs the source tree. Bringing a project's scaffold forward is this ritual,
and nothing else does it.

1. `aipass doctor` from the project root — the **Scaffold** group reports the
   stamped version, tier0 drift, missing hook handlers and retired ones.
2. `aipass init update <root> --dry-run` — reads the plan. Nothing is written.
   Exit 2 means there is a plan to read; exit 0 means nothing to do.
3. Paste the plan to the owner or devpulse and ask. **Apply only on a go** — an
   update can replace files, so it is a decision, not a repair. `doctor --fix`
   deliberately will not do it for you. **One exception (the owner, DPLAN-0337
   R1):** a *stamp-only* plan — no file would change, only the manifest's
   record of the version — applies without a go. The preview says so in its
   last line, and `--json` carries `"stamp_only": true`. The receipt apply
   prints is the contract, not the go.
4. `aipass init update <root>` — backs up every file it overwrites into
   `.aipass/.backup/scaffold_<stamp>/`, writes, stamps the manifest, re-enrols
   trust.
5. `aipass doctor` again — Scaffold current, hooks enrolled.

For a PyPI install the same ritual follows `pip install -U aipass`.

## What an update may and may not overwrite

`.aipass/scaffold_manifest.json` records the sha256 of every file AIPass wrote
and the version that wrote it. A managed file is overwritten only when its hash
still matches that record (so nobody has touched it) or it is absent. Otherwise
your copy stands, the plan says `kept-local`, and the template is written beside
it as `<name>.aipass-new` to diff. A project with no manifest yet is backfilled
conservatively: anything differing from the template is kept as
`unknown provenance`, so the first update of an existing project overwrites
nothing.

Root `CLAUDE.md` and `AGENTS.md` are **seeds** — created once, never rewritten,
because they exist to be filled in. Retired managed files are renamed
`<name>(disabled)`, never deleted.

## `.updateignore` — the owner decides what an update skips

Drop the file at the project root, beside the registry. Same fashion as
`.gitignore`: one pattern per line, `#` comments, blank lines ignored, `fnmatch`
semantics against the path relative to the project root, a trailing slash
meaning a directory and everything under it. A pattern with no slash also
matches a bare filename at any depth, so `tier1_navmap.md` finds
`.aipass/tier1_navmap.md`. Negation (`!`) is not in v1.

```
tier1_navmap.md
.aipass/prompts/
```

A matched file is never written, never backed up, and never gets a
`.aipass-new` beside it; the plan reports it as `skipped (.updateignore)` and
doctor counts it as owner-protected rather than as drift. `.updateignore`
outranks both the seed rule and the hash rule. AIPass never creates or edits
it — it is yours. Nothing is recorded in the manifest for a protected file, so
removing a pattern later puts that file back on the conservative backfill path
(kept, not overwritten) rather than handing AIPass a hash it never wrote.

Code: [`apps/handlers/init/bootstrap.py`](../apps/handlers/init/bootstrap.py)
and [`apps/handlers/init/scaffold_manifest.py`](../apps/handlers/init/scaffold_manifest.py),
reached from [`apps/modules/init_flow.py`](../apps/modules/init_flow.py).

---

[← Back to the AIPASS README](../README.md)
