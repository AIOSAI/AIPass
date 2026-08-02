# {plan_number} - {subject} (PROMPT CHANGE)

**Created**: {today}
**Branch**: {location}
**Status**: Active
**Type**: Playbook — Prompt Change SOP

---

## Purpose

Any change to an injected prompt — the kernel, the navmap, a branch-local prompt, identity, a brand-new tier, a cadence tweak, or retiring one — must propagate to **every place that injects it AND every place that seeds it into a fresh install**. This SOP is the checklist that makes sure nothing is half-done. Run by **devpulse** (orchestrator); tick as you go; dispatch the owning branch where a step lives in its core. Born from FPLAN-0284, where the live wiring was fixed but `aipass init` kept handing new projects the retired global prompt for days because the *seed* template was never updated.

---

## The Law (read first — this is the trap)

1. **LIVE ≠ SEEDED.** Editing the repo's own `.aipass/hooks.json` makes the change work *for us* — it does **nothing** for a fresh clone, a new `aipass init` project, or a freshly spawned branch. Those are built from **separate seed sources**. A prompt change is not done until every seed path carries it.
2. **Three wiring layers, each with its own seed.** A prompt only injects if all three agree:

   | Layer | Live file | Seeded for fresh installs by |
   |---|---|---|
   | Handler registration | `.aipass/hooks.json` | git-tracked (travels with clone) **+** `.aipass/project_hooks.json` (what `aipass init` copies) |
   | Cadence (period/offset) | `hooks_json/custom_config/cadence_config.json` (machine-local, gitignored) | `cadence.py` `DEFAULTS` (the committed backstop) |
   | Event→handler bridge | `~/.claude/settings.json` (machine-local) | `.claude/provider_manifest.json` (single source — `setup.sh` reads it, FPLAN-0374) |

3. **Never delete a retired prompt.** Mark `(superseded)` in its header / disable it in `hooks.json`, or move it to `.archive/`. If a disabled handler still reads it **by path** for rollback, leave the file exactly where the handler looks.
4. **The `.md` files travel by git; the wiring does not.** Prompt/tier `.md` files are tracked → a clone gets them free. The machine-local wiring (cadence_config, settings bridge) must be regenerated from the committed seed sources, so those seeds are what you must update.
5. **One prompt source, every runtime — retire for one = retire for all.** There is ONE source of prompt truth (the tier `.md` files); both runtimes inject *the same content*, only delivery differs: **Claude Code** tiers by cadence (`UserPromptSubmit`, per turn — tier0 every turn, navmap periodically); **Codex CLI** injects the combined tiers once at **SessionStart** (`.codex/hooks/session_start_identity.py`). A change or retirement is NOT done until *both* runtimes point at the new content. (FPLAN-0284 retired the 8k global for Claude via cadence, but Codex's SessionStart kept reading the old global for days until separately rewired — the classic "fixed one runtime, forgot the other.")

---

## 1. Identify the change
- [ ] Which prompt? (`.aipass/tier0_kernel.md` / `.aipass/tier1_navmap.md` / a branch's `.aipass/aipass_local_prompt.md` / identity / a NEW prompt / retiring one)
- [ ] Kind? edit content · change cadence · add a new injected prompt · retire one
- [ ] Owners of the files you'll touch — devpulse owns the tier files + project prompts; **@hooks** owns the engine, handlers, cadence, **and the Codex SessionStart hook** (`.codex/hooks/`); **@aipass** owns init/bootstrap; **@spawn** owns branch templates

## 2. Content
- [ ] Edit the `.md`. Follow `.aipass/PROMPT_STYLE.md`.
- [ ] ⚠️ Size caps: tier0 kernel target **< 2,000 chars**; navmap **< 8,000** (the hook truncates near 10k). To shrink, cut CONTENT, not whitespace — newlines are nearly free, so trimming spaces saves almost nothing.
- [ ] ⚠️ An unclosed `<!-- comment` swallows the whole prompt downstream — confirm every comment is closed.

## 3. Wiring — make it inject LIVE (3 layers)
- [ ] **Registration** — `.aipass/hooks.json`: handler entry present + `"enabled": true` (or `false` + a `_retired` note if retiring). New prompt → add the handler entry.
- [ ] **Cadence** — `cadence_config.json` loaders: correct `period`/`offset` (tier0 `period:1` = every turn; navmap `period:5`). New loader → add it.
- [ ] **Bridge (Claude Code)** — `~/.claude/settings.json`: a `UserPromptSubmit:<handler>` bridge line exists (machine-local — edit directly for the live machine). Retiring → remove the stale line.
- [ ] **Codex runtime** — `.codex/hooks/session_start_identity.py` reads the tier `.md` files at SessionStart (tier0_kernel + tier1_navmap, each size-capped). New tier → add it to what this hook reads; retiring → stop reading the old prompt. Same content as Claude, different delivery. **@hooks owns — dispatch.**
- [ ] New handler file lives at `src/aipass/hooks/apps/handlers/prompt/<name>.py` — **@hooks owns it; dispatch them to build it.**

## 4. Seed propagation — so FRESH installs get it (the step that's always forgotten)
- [ ] **Fresh clone + doctor — ONE source:** `.claude/provider_manifest.json`. Add/retire the `UserPromptSubmit:<handler>` bridge entry THERE. `setup.sh` no longer carries an inline hook list — it reads the manifest (`refresh_provider_hooks` strip-and-readd, FPLAN-0374) and doctor checks against the same file. There is no second list to sync.
- [ ] **Cadence backstop** — `cadence.py` `DEFAULTS`: contains the loader (so a clone with no `cadence_config.json` still fires it). Remove retired loaders' crumbs.
- [ ] **`aipass init` (new projects)** — ⚠️ TWO files, both easy to miss:
  - `.aipass/project_hooks.json` (the template init copies into new projects) — mirror the live `hooks.json` (right handlers enabled, retired ones off/removed).
  - `src/aipass/aipass/apps/handlers/init/bootstrap.py` — seeds the prompt `.md` files into the new project's `.aipass/`. New tier → it must copy that `.md`; retiring → stop seeding the old one. **@aipass owns — dispatch.**
- [ ] **`@spawn` (new branches)** — branch local-prompt template `src/aipass/spawn/templates/*/.aipass/aipass_local_prompt.md` + any stale doc-prose referencing old prompts. **@spawn owns — dispatch if more than cosmetic.**
- [ ] **Codex for new installs** — if a fresh project/clone runs Codex, confirm its SessionStart hook reads the seeded tier files, not a retired prompt (the Codex entry point `AGENTS.md` is generated by `bootstrap.py`). **@hooks/@aipass own — dispatch.**

## 5. Verify LIVE (don't trust the edit)
- [ ] Watch it actually inject — right content, right turns. Tier0 every turn; periodic tiers on their cadence.
- [ ] After a `/compact`, confirm the prompt you expect reloads (post-compaction is exactly when the map matters most).
- [ ] **seedgo** the touched branches to 100%. ⚠️ importlib-dispatched prompt handlers trip dead-code / unused-function / json-structure false-positives — add **3 `bypass.json` entries per new handler**, mirroring an existing prompt handler (DPLAN-0191).

## 6. Tidy superseded prompts
- [ ] Disable in `hooks.json` (`enabled:false` + `_retired` note pointing at the replacement).
- [ ] Mark the file `(superseded-<plan>)` in its header, or move to `.archive/` — **but** if a disabled handler reads it by path for rollback, leave it in place.
- [ ] Archive pure snapshots/backups + stale design docs. Never delete.

## 7. CHANGELOG + wrap
- [ ] `CHANGELOG.md`: entry under the dated section (Added / Changed / Fixed).
- [ ] Update `.trinity/` memories.
- [ ] Fill the Run Summary below; close (vectorizes the run to @memory).

---

## Run Summary

Fill as you go — this becomes the vectorized trail.

- **Date:** {today}
- **Prompt(s) changed:**
- **Layers touched:** (hooks.json · cadence · bridge · setup.sh · manifest · DEFAULTS · project_hooks · bootstrap · spawn)
- **Dispatched to:** (@hooks / @aipass / @spawn …)
- **Verified live:** (how — which turns, post-compaction reload)
- **Seedgo:** (touched branches @ 100%?)
- **Issues hit:**
- **Notes for next run:** (refine this SOP — what was missing or wrong?)

---

## Listen (TTS-friendly summary)

This playbook is the checklist for changing any injected prompt in AIPass. The big lesson it captures is that live is not the same as seeded. When you change a prompt, editing the repository's own hook configuration makes it work for us right now, but it does nothing for a fresh clone, a newly initialised project, or a newly spawned branch, because those are all built from separate seed files. So the checklist walks you through three things. First, the content of the prompt itself, watching the size limits. Second, the three wiring layers that make it inject live, which are the handler registration, the cadence timing, and the event bridge. Third, and most important, every seed path that a fresh install is built from, including the provider manifest which both the setup script and doctor read as the single source, the cadence defaults, the two files behind the aipass init flow, and the spawn templates. There are also two runtimes — Claude Code and Codex — both injecting the same prompt content, so retiring or changing a prompt for one means doing it for the other; Claude reads it on a per-turn cadence, Codex reads it once at session start. Then you verify it actually injects, including right after a compaction, tidy away any retired prompt without deleting it, and update the changelog. Run it any time a prompt changes so nothing is left half wired.

---

## Close Command

When all steps are ticked and the Run Summary is filled:
```bash
drone @flow close {plan_number}
```
