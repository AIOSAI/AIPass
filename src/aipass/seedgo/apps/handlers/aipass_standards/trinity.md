# Trinity Standards
**Status:** Live v1.1 — enforced by `trinity_check.py`
**Date:** 2026-09-15
**Standard:** `trinity` (branch_level, no bypass)
**Scope:** `local.json`, `observations.json`, `.template_version.json`. Passports and compass are separate systems with their own rules.

---

## What It Is

The trinity standard defines the canonical shape of every citizen's memory files: which sections exist, what each entry looks like, where the numbers and the prose come from, and what agents may and may not touch.

One sentence per file:

- **local.json** — your working draft: the context that keeps you YOU across sessions.
- **observations.json** — your memory of the USER: nontechnical collaboration patterns.
- **.template_version.json** — the receipt: which template version your files carry and when they last got it.

---

## Why It Matters

Memory files are what a fresh agent wakes up in, and an agent imitates the shape it finds. A drifted file teaches drift; a canonical file teaches the standard without anyone saying a word. One enforced shape keeps every citizen's memory readable by the machinery that caps, rolls, archives, and searches it — and keeps a citizen's continuity intact when that machinery runs.

---

## The One-Source Rule (text and numbers)

A memory file is two things: the MEMORIES and the STRUCTURE that holds them. The memories — session summaries, learnings, todos, observations — are written by the agent, freely, in its own words; that is the whole point of the files. The structure — the JSON skeleton, field names, metadata, meta lines, the receipt — is machine-owned and never hand-edited. Every structural piece has exactly ONE authoritative source:

| Piece | Single source | Reaches the live file via |
|---|---|---|
| Caps & keep-counts | `@memory memory.config.json` → `entry_limits` + `rollover` (per-branch overrides included) | rendered into each `*_meta` line by @memory's tab renderer |
| `_usage` prose + `*_meta` suffix prose | `memory/templates/*.template.json` (the gold source) | rendered by the same pass — the renderer reads the template, never carries its own copy |
| Entry content | the agent | normal edits, gated by @hooks char caps |
| Template version receipt | `memory/templates/` version stamp | written by push machinery, spawn at birth, or reset |

**Agent contract:** the agent writes entry CONTENT — its memories, in its own words — and stamps each entry's `number` + `date` into the canonical field names. Everything around the entries (`document_metadata`, `*_meta` lines, `.template_version.json`) is machine-owned — a hand edit there is drift by definition and is overwritten on the next render.

---

## Canonical Shape — local.json

Top-level keys, in order, and nothing else:

```
document_metadata
todos_meta        todos[]
key_learnings_meta key_learnings[]
sessions_meta     sessions[]
```

**document_metadata** (machine-owned): `document_type`, `document_name` (`<branch>.LOCAL`), `version`, `schema_version`, `created`, `last_updated` (bumped on EVERY write), `managed_by` (exact branch name, one casing across all files), `tags`, `_usage` (the template text, verbatim). No `status` block — health is not stored, it is computed by the checker at run time (a stored copy of a derivable fact is a second source of truth waiting to go stale).

**Entry shapes** (all lists newest-first, `number` monotonic per type = max+1, never reused).

**The shape is not written down here.** Field names, their types, which are required and the
per-field caps are `entry_limits.entry_types.<type>.fields` in @memory's `memory.config.json`
— one map, published by the branch that owns it. The checker resolves it at run time
(`trinity_groups.entry_shapes()` / `_resolve_entry_limits()`, with `entry_limits.per_branch`
merged over the defaults), and @memory's `trinity_push` derives its write gate from the same
key. A table in this document would be a fourth copy: right only while someone re-types it,
and silently wrong the day a field is closed, renamed or capped.

Read the key when you need the shape. What this document owns is what the config cannot say:

| Section | Where it lives | Rollover |
|---|---|---|
| sessions | `local.json` | keep-count from `rollover`; oldest archived to @memory |
| key_learnings | `local.json` | keep-count from `rollover`; oldest archived to @memory |
| todos | `local.json` | a pad sized by `rollover.defaults.local.todos.count`; the oldest roll to `.backup/todo/<branch>/backlog.json` (a plain file, never vectors) — delete one when done |
| observations | `observations.json` | no rollover; patterns live for weeks |

Two shape rules are this standard's own, not the config's, because they are prohibitions
rather than fields: a `todos` entry carrying `status` is an EXTRA (done means deleted), and a
`document_metadata` `status` block is a violation (health is computed, never stored).

**Meta lines** — every section's `*_meta` value is `⟦ machine tab ⟧ + one-sentence semantics`, fully rendered, never hand-edited:

```
⟦ rollover ON → oldest archived to @memory · keep 15 · summary ≤300 chars · draft to 240 ⟧ The chronicle — what happened and how it ended; one entry per session.
```

`draft to N` is the length to write to, not a second cap: 80% of the resolved cap, floored (`300/200/150 → 240/160/120`, `77 → 61`), per_branch overrides included (DPLAN-0342). It is derived, never stored, so it cannot go stale beside the cap.

The ⟦⟧ tab carries the live numbers (rendered from config — a config change re-renders every file); the sentence after it carries the section's meaning (owned by the template). The agent reads the cap where it writes; it never has to know the config exists.

The todos tab (DPLAN-0345) names the pad instead of a keep count:

```
⟦ pad of 10 · oldest roll to .backup/todo/memory/backlog.json · task ≤100 chars · draft to 80 · next #41 ⟧ One line of what to do: ...
```

The pad size is `rollover.defaults.local.todos.count` through @memory's resolver (a per-branch `local` block without a todos count falls back to the default); no usable count renders `⟦ no pad size configured — nothing rolls · task ≤… · next #N ⟧`. `next #N` is the highest number on the pad or in the backlog plus one, derived when the tab is RENDERED — adding a todo does not re-render, so the checker reads that slot by shape (a number or `?`), never by value. A render with no branch context (spawn birth) writes `<branch>` and `#?`, and that line is accepted whole.

**Semantics — the one-line definitions:**
- **sessions** = the chronicle — what happened and how it ended; one entry per session.
- **key_learnings** = transferable technical lessons — what future-you needs to know again; the story itself lives in sessions[].
- **todos** = a sticky-note pad — one line of what to do ('Check on seedgo's errors in logs', 'fix drone help'). No status, no log: the story lives in plans and sessions. Delete it when done.

**Where the full story goes** — the session entry is a headline, not a container:
- `summary` holds the headline and nothing more. Extra fields bolted onto a session entry (`findings[]`, `verification`, …) are shape violations, however well-intentioned — the shape is closed.
- A transferable lesson from the session → its own `key_learnings` entry.
- The depth is already kept: rollover archives whole entries to @memory's vector store — recall with `drone @memory search "query"` (own branch first, global when needed). Nothing is lost by keeping the entry small.
- `tags` is the findability hook — tag the session with related files/topics so search lands on it later.

**Forbidden:** any other top-level section; duplicate keys; renamed fields; text fields holding anything but a string; entries without `number` + `date`.

---

## Canonical Shape — observations.json

Top-level keys: `document_metadata`, `guidelines`, `observations_meta`, `observations[]`.

**Entry shape:** `entry_limits.entry_types.observations.fields` in `memory.config.json` — read it there, as with every other type. No other field names, no other types: the map is closed, and a field it does not name is an extra.

**Semantics:** observations capture how THIS user works — nontechnical, per-user. Every user is different; capture this one. **No cadence duty** — add one only when a real pattern shows; sessions without a new observation are normal. Patterns live for weeks; local.json is the working draft.

`guidelines` carries the template text verbatim.

---

## Canonical Shape — .template_version.json

A per-branch receipt in each `.trinity/`, machine-owned:

```json
{
  "template_versions": { "local": "3.0.0", "observations": "3.0.0" },
  "stamped": "2026-XX-XXTXX:XX:XX",
  "stamped_by": "memory push | spawn birth | reset",
  "config_rendered": "2026-XX-XXTXX:XX:XX"
}
```

- `template_versions` — which gold-source version each file's structure carries.
- `stamped` / `stamped_by` — when and by which lane the templates last touched this branch. Honest: a branch a push skipped shows its OLD stamp, not the fleet's.
- `config_rendered` — when caps/meta lines were last re-rendered (the renderer bumps it).

Written only by @memory/@spawn machinery. Its entire job: "who actually carries the current standard" is a lookup, not an audit. (The template-side push log in `memory/templates/` is a separate file and keeps its own role.)

---

## What the Checker Scans For

Read-only, per branch. Fails loud — a field it cannot measure is a VIOLATION, never a silent pass.

1. **File set** — `.trinity/` contains exactly `passport.json`, `local.json`, `observations.json`, `README.md`, `.template_version.json`, plus **versioned backups** of those files. A versioned backup is `<canonical name>.pre<sep><token>` (`local.json.pre_v3_backup`, `observations.json.pre-aipl`), where `<sep>` is `-` or `_` and `<token>` is `[A-Za-z0-9][A-Za-z0-9_-]*`. Renaming the current file as a version and leaving it in place is the house convention, so those are expected residents, not strays; the rule matches the SHAPE rather than a list of suffixes, so the next migration's token needs no code change. Still strays: a dotted token (`local.json.pre_v3_backup.tmp`), a non-canonical base (`STATUS.local.md.pre_v3_backup`), a directory whatever its name, and all other runtime state, lock files and status notes — a rule loose enough to admit `local.json.tmp` would hide torn writes in the one directory whose job is durable memory.
2. **Top-level keys** — exact set and order per file; stray sections and duplicate keys flagged.
3. **Entry shapes** — required fields present with required TYPES; renamed fields flagged by name; entries missing `number`/`date` flagged.
4. **Ordering & numbering** — newest-first, numbers strictly descending, no reuse.
5. **Char caps** — measured against the CONFIG (not the meta line), on the canonical field; an unmeasurable field is a violation.
6. **Meta lines & `_usage`** — byte-match against what the renderer would produce from config + template (the todos tab's `next #N` slot is read by shape, see above).
7. **Freshness** — `last_updated` ≥ newest entry date.
8. **Receipt** — `.template_version.json` present, machine-shaped, `template_versions` matching the gold source.

**Retired 2026-09-15 — Todos hygiene** (was group 8, weight 5). It flagged a todo kept as `status: done`. Todos v2 (DPLAN-0345) has no `status` field, so that trophy can only be spelled as a key outside the closed shape, which Entry shapes flags by name; the 5 points moved there. A replacement was measured first and not built: a done-marker read of task text (`DONE`, `✅`, `[x]`, …) found 1 hit in 191 fleet todos, and it was not a trophy. Nor is a pad over its size a violation: the roll cures it, the same as sessions past their keep count.

---

## Examples

### Violations

```json
// BAD — note is not a string: measures as 0 chars, dodges every cap
{"number": 41, "date": "2026-05-01", "note": [{"title": "...", "detail": "..."}], "session": 12}

// BAD — renamed field: invisible to the char gate
{"number": 90, "date": "2026-04-11", "learning": "merged key+value into one 600-char blob"}

// BAD — todo carrying status: the shape is closed, done means deleted
{"number": 12, "date": "2026-03-02", "task": "fix the thing", "priority": "high", "status": "done"}
```

### Fixes

```json
// GOOD — observation: string note ≤300, tags list
{"number": 209, "date": "2026-08-25", "note": "User wants initial tests run before handover — never say it works untested.", "tags": ["verification"]}

// GOOD — key_learning: key names it, value ≤200 carries the transferable lesson
{"number": 512, "date": "2026-08-25", "key": "Docs rot both directions", "value": "Overclaim AND underclaim both poison a fresh agent; every number written must be one measured now."}
```

---

## Scoring

- **Scope:** per-branch, the three in-scope `.trinity/` files
- **Score 100:** all eight scan groups clean
- **Failure message:** names the file, the rule, and the offending entry numbers — up to 3 samples

**Group weights** (set by @seedgo at build time, per the contract's proposal — shape/type
heaviest because it breaks the machinery, freshness lightest):

| Group | Weight |
|---|---|
| Entry shapes | 30 |
| Top-level keys | 15 |
| Ordering & numbering | 12 |
| Char caps | 12 |
| File set | 10 |
| Meta lines & `_usage` | 10 |
| Receipt | 8 |
| Freshness | 3 |

Final score = weighted sum of each group's own 0-100 subscore. Subscores are proportional
where a natural denominator exists (entries checked, files checked), binary otherwise.

**One scoring rule carries THE ONE LAW:** a group holding any violation record never scores
100, whatever its denominator says. A record raised with nothing measurable behind it — an
unreadable section, a config with no spec for it — divides by zero entries, and the first
build of this checker scored that a clean 100. The records decide *whether*; the denominator
only decides *how bad*.

---

## Bypass

None for shape rules, by design — a bypassable memory standard recreates the drift it exists to end. A branch that genuinely needs different numbers gets a per-branch entry in @memory's config (the one source), not a bypass file.

---

## Reference

- **Gold source:** `memory/templates/LOCAL.template.json`, `OBSERVATIONS.template.json`
- **Numbers:** `memory/memory_json/custom_config/memory.config.json` → `entry_limits`, `rollover`
- **Renderer:** `memory/apps/handlers/tracking/tab_renderer.py`
- **Checker:** `seedgo/apps/handlers/aipass_standards/trinity_check.py`
- **Tests:** `seedgo/tests/test_trinity_check.py` — 170 test functions (2026-09-15), including the live fleet
  acceptance bar (exactly 6 of 18 citizens canonical on observations shape). That bar is
  deliberately coupled to fleet state: as branches migrate, UPDATE the expected set —
  never loosen or delete it.
- **Origin:** this file is `devpulse/dropbox/trinity_pattern.md`, graduated on landing.
