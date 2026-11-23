---
name: map
description: Map every action a branch or program performs into a page where the owner ticks keep or cut and leaves a comment per row. Three read-only passes (sub-agent slices, a second model, your own line-by-line read) consolidated into one verified list, published as an artifact with a shared decision store. Use when the owner wants to strip, refocus or audit a branch and needs the whole inventory first.
---

# Keep or cut map

Purpose: before a branch is stripped or refocused, lay out everything it does, one row per action, in plain English, and hand the owner a page to decide on: a green tick keeps, a red tick cuts, a comment box carries the why. The words after the command name the target (a branch path or a program) and the owner's question ("strip aipass to the install path"). The target is never changed: mapping reads code, runs `--help` and `--dry-run`, nothing else.

## What comes out

- A scratch folder `<scratchpad>/<target>_map/`: `brief.md`, `slice_*.json`, `codex_result.json`, `r3/*.json`, `items.json`, `map.html`.
- One artifact URL, republished in place each round. The page stores decisions in its `decisions` collection, one document per row id: `{verdict: "keep" | "cut" | "", comment, updated}`.
- A report in chat: counts, the bugs the read turned up, which second-pass corrections were accepted or rejected, what was not read line by line and why. Then a session entry and a todo to read the decisions back.

## Execution

Paths below are relative to the AIPass repo root; the skill folder is `.agents/skills/map/`.

0. **Brief.** Copy `assets/brief.md` into the scratch folder and fill the angle-bracket slots: target root, entry points, the groups, the commands that write (forbidden). The item shape and the `FLUFF?` convention live in it; every sub-agent and the second reader get the same file.
1. **First pass, slices.** Split the target by folder into at most three slices and give each to one background opus sub-agent: the brief, its file list, its output path `slice_<L>.json`, ids `<L>01` onward. A sub-agent validates its JSON before it reports. Then `python3 -I .agents/skills/map/scripts/merge.py <dir> "<target>"`, copy `assets/map.html` beside `items.json`, load the `artifact-capabilities` skill and publish the page with `files: {"items.json": ...}` and `capabilities: {db: {}, user: {}}`. Give the owner the link now; the first list is already useful.
2. **Second pass, another model.** Fill `assets/second_pass.md` (item count, paths, the read order, the forbidden list), copy `assets/second_pass_schema.json` beside it, and run it from the target directory in the background:

   ```
   codex exec --sandbox read-only -m gpt-6.1-sol --output-schema <dir>/second_pass_schema.json -o <dir>/codex_result.json - < <dir>/second_pass.md > <dir>/codex_run.log 2>&1
   ```

   The result is `{summary, missed[], corrections[]}`: missed rows get ids `X01` onward, corrections name `id`, `field`, `was`, `should_be`, `why`. No codex on the machine: an opus sub-agent with the same prompt writes the same shape. Re-merge and republish: corrections show as overlays under the row, missed rows wear a "2nd pass found" pill.
3. **Third pass, yourself.** Read every file of the target, file by file, and write one `r3/NN_<group>.json` per group: `verify` (ids confirmed as written), `fix` (`{id: {field: new text, r3: "what changed and where in the code"}}`), `add` (new rows `R01` onward, full item shape plus `source: "round3"`), `drop` (`{id: "the id it merged into"}`). `show.py <dir> <substring> [full]` prints the rows for a file; `left.py <dir>` prints the rows no r3 file has touched yet, the ids two files both touch, and any unknown id: you are done when left is 0. Every second-pass correction gets an explicit answer: accepted by folding it into the field, rejected by a `fix` that restates the original with an `r3` saying why. Tests are inventoried by class and test count, not read line by line; the owner's `.archive/` is listed, never processed; scratch under `docs.local/` is listed with sizes.
4. **Consolidate.** `merge.py` again: with `r3/` present it folds the overlays away, marks every row verified, adds the third-pass summary and prints the rows still unverified (must be none). Republish to the same URL with the same file path and no `capabilities` argument. A dropped id loses its stored decision, so read `ArtifactData list decisions` before dropping one that has been ticked.
5. **Report and remember.** The counts table, the bugs (each with its row id), accepted and rejected corrections, what was skipped. Session entry, a todo "read the decisions back, plan the strip", a learning if the read taught one.

## Rules

- Read-only on the target: no install, no fix, no create or adopt without `--dry-run`, nothing that writes; the brief names the forbidden commands and every prompt carries them. No test runs, no coverage, no git.
- Sub-agents run in the background, opus, at most four at once, briefed with the file and nothing from the chat.
- One row per distinct action: each command, each flag that changes behaviour, each step of a flow, each file write, each prompt to the user, each printed banner, each hook, schedule or outside caller, each helper another branch imports. `does` is plain English, no code in prose. Hand-holding gets `FLUFF?` in `note`; the owner decides.
- The scratch folder stays in the scratchpad. Nothing of the map lands in the tree; the artifact is the deliverable.

## Reading the decisions back

`ArtifactData` with `action: "list"`, the artifact `url`, `collection: "decisions"`, `query: {"limit": 1000}`. Each document id is a row id. Join on `items.json` to list the cuts with their comments; that list is the brief for the strip plan.
