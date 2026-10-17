[<- Back to the README](../README.md)

# The comment budget

Every edit to a source file is measured: what share of its lines are full-line comments. Over 10%, the agent is told, with the heaviest runs, so old code cleans up as it is touched. The owner's ruling of 2026-10-16; the prompt half is the House rules line in `.aipass/tier1_navmap.md`.

**Branch** hooks · **Code** `apps/modules/comment_scan.py` (the counter), `apps/handlers/lifecycle/comment_budget.py` (PostToolUse), `apps/modules/comments.py` (the verb) · **Ledger** `logs/comments.jsonl`

---

## The metric

- **Judged kinds:** `.py .pyi`, `.ts .tsx .js .jsx .mjs .cjs`, `.sh .bash`, `.css .scss`. Anything else is silent and writes no row.
- **Body:** non-blank lines, minus the AIPass header in Python (a leading run of `#` lines whose first starts `# ====`).
- **Comment line:** Python, a comment token with only whitespace before it (read by `tokenize`); a bare string statement counts from its second line on, so a one-line docstring is free and a three-line one costs two. TS/JS/CSS, a `//` line or any line of a `/* */` block opened at a line's start (`{/*` too). Shell, a `#` line.
- **Free:** shebang, `# -*- coding`, `# noqa`, `# type:`, `# pyright:`, `# pragma`, `# fmt:`, `# ruff:`, `# pylint:`, `// eslint-`, `// @ts-`, `// prettier-ignore`, `/* eslint`.
- **Budget:** `over = comments - floor(body * 10 / 100)`; a file at exactly 10% is not over. `BUDGET_PERCENT` in `comment_scan.py`.

## What is not counted

- A trailing comment after code on the same line.
- A `/*` opened mid-line after code: a glob like `"src/**/*.ts"` holds `/*`, so only a block opened at a line's start is tracked.
- A Python fragment the tokenizer refuses (an Edit's `old_string` cut mid-string) is counted by its `#` lines alone, without docstrings.

## The answer

- Within budget: a statusline `systemMessage` only, `[comments] mod.py 4% ok`.
- Over: PostToolUse `additionalContext`, under 700 characters: the counts, the share, the over count, what this edit added or removed, the three heaviest runs, and the rule.
- `added`: Edit and MultiEdit count `new_string` minus `old_string`; Write is the file's comments now minus the ledger's last row for it, unknown on a first sighting.
- Scratch ground (`docs.local`, `dropbox`, `.backup`, `.archive`, the harness scratchpad) answers a skip line and writes no row: the same `_scratch_ground` auto_fix uses.
- Never blocks; an error is logged and the edit stands.

## The verb

`drone @hooks comments` with no argument shows the last 20 judged edits. `comments <path>` scans a file (every run) or a tree (worst first, then the totals; dot, scratch, `node_modules`, `dist` and `build` directories skipped). `comments --file <path>` is one file's trend, ending `first 37% → latest 29%`. `comments --over` lists the files whose latest edit was over.
