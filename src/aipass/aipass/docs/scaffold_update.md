[<- Back to the README](../README.md)

# The ritual — updating a project's scaffold

*Why a merge to main does not bring a project's scaffold forward, and the one
sequence that does.*

Code is shared, scaffold is not. Every project's `.venv` is a symlink to the
AIPass runtime and hooks run from `$AIPASS_HOME`, so a merge to main updates
the *code* under every project the moment it lands. Only the project-local
files — `tier0_kernel.md`, `tier1_navmap.md`, `AGENTS.md`, `hooks.json`, the
Claude settings, the prep skill, `.gitignore` — lag behind. **`setup.sh` never touches a project**; it
installs the source tree. Bringing a project's scaffold forward is this ritual,
and nothing else does it.

1. `aipass doctor` from the project root — the **Scaffold** group reports the
   stamped version, tier0 drift, missing hook handlers and retired ones.
2. `aipass init update <root> --dry-run` — reads the plan. Nothing is written.
   Exit 2 means there is a plan to read; exit 0 means nothing to do.
3. Paste the plan to the owner or devpulse and ask. **Apply only on a go** — an
   update can replace files, so it is a decision, not a repair. `doctor --fix`
   deliberately will not do it for you. **One exception, set by the
   owner:** a *stamp-only* plan — no file would change, only the manifest's
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

Root `AGENTS.md` is managed under the same hash rule, against
`.aipass/project_AGENTS.md`: an unedited copy follows the template, an edited
one is `kept-local` with the template beside it. A manifest written before
AGENTS.md was managed lacks `agents_md_managed`; its AGENTS.md hash may be an
edit adopted by an older update, so it is not trusted and that first update
overwrites nothing. A project that keeps its own AGENTS.md lists it in
`.updateignore`.

`.aipass/tier1_navmap.md` is a project stub: the project's name, its citizens
read from the registry one line each, and the drone basics. An unedited stub
follows the roster; a file without the stub's marker line (the host's map an
older scaffold copied, or the project's own) is `kept-local`, the stub written
beside it.

A live `CLAUDE.md`, `.claude/CLAUDE.md` or `CLAUDE.local.md` beside AGENTS.md
makes Claude Code skip AGENTS.md; the update renames it `<name>(disabled)` with
doctor's own `instruction shadow` fix and its refusals. Hook scripts under
`.claude/hooks/` that the manifest still records are retired the same way while
they hold the bytes AIPass wrote. Retired managed files are renamed
`<name>(disabled)`, never deleted.

## The three ignore files

| File | Written | On update |
|------|---------|-----------|
| `.gitignore` | from the template | lines-merge: each template line the file lacks is appended under one `# Added by aipass init update <date>` comment; no owner line is removed or moved. `--dry-run` prints the lines |
| `.aipass/.gitignore` | whitelist: `*`, then the kernel, navmap, `hooks.json`, itself | created when absent, never rewritten: the manifest and `.aipass/.backup/` stay uncommitted |
| `.updateignore` | its comment header only | created when absent, never rewritten |

The root template ignores what spawn and the services write into one
installation: `.trinity/`, `docs.local/`, `dropbox/`, `artifacts/`, `tools/`,
`**/*_json/`, `.spawn/`, `.chroma/`, `.backup/`, the registry and roots json,
`.env`, plan files. A citizen whose tools ship negates its own folder, as the
template's comment shows. An owner who wants a template line gone lists
`.gitignore` in `.updateignore`, or the merge appends it again.

## The shared prep skill

`/prep` is a skill both CLIs read: `.agents/skills/prep/SKILL.md`, a managed
file under the hash rule above, with `.claude/skills` a symlink to
`../.agents/skills` so Claude Code sees what Codex reads. An update makes a
missing link. A project scaffolded before the skill holds `/prep` as
`.claude/commands/prep.md`: the update renames it `prep(disabled).md` when it is
still what AIPass wrote (the manifest's hash, or the old template unedited), and
keeps an edited one, saying so in the plan. Where the filesystem refuses the
link, a copy is written into `.claude/skills/` and the run says the copy will
not follow `.agents/skills`; [`two_clis.md`](two_clis.md) has the rest.

## The provider switch files

Each CLI's switches to the other two are managed files under the same hash rule:
`/codex` and `/opencode` (`.claude/commands/codex.md`, `.claude/commands/opencode.md`),
`$claude` and `$opencode` (`.codex/skills/claude/SKILL.md`, `.codex/skills/opencode/SKILL.md`),
and OpenCode's `/claude` and `/codex` (`.opencode/commands/claude.md`, `codex.md`), with
its ritual commands `/memo`, `/prep` and `/compass` (`.opencode/commands/memo.md`,
`prep.md`, `compass.md`), which load the shared skill of that name.
An update writes a missing one, keeps an edited one as `kept-local`, and adopts
a hand copy that matches the template into the manifest as current.

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
outranks every rule above. AIPass seeds it with its header and never edits
it after — it is yours. What AIPass never rewrites lives in code, so the file
holds only the owner's choices; `drone @spawn update` reads the same root file,
so a pattern like `src/<pkg>/*/docs.local/` reaches every citizen. Nothing is recorded in the manifest for a protected file, so
removing a pattern later puts that file back on the conservative backfill path
(kept, not overwritten) rather than handing AIPass a hash it never wrote.

Code: [`apps/handlers/init/bootstrap.py`](../apps/handlers/init/bootstrap.py)
and [`apps/handlers/init/scaffold_manifest.py`](../apps/handlers/init/scaffold_manifest.py),
reached from [`apps/modules/init_flow.py`](../apps/modules/init_flow.py).

---

[← Back to the AIPASS README](../README.md)
