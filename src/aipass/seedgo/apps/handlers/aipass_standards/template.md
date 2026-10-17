# Template Standard

Detects files still in un-configured template form after spawn scaffolding.

## Severity

**Advisory (WARNING)** — never fails the audit or blocks commits. Surfaces loudly so branch owners notice.

## Target Files

- `.aipass/aipass_local_prompt.md` — branch prompt
- `README.md` — branch documentation
- `.trinity/passport.json` — identity file, the only spawn-templated `.trinity` artifact; checked when present

## Detection Markers

### Definitive (all file types)

- `NEEDS CONFIGURATION`
- `{{BRANCHNAME}}` / `{{BRANCH}}` — unfilled mustache placeholders from spawn
- `INSTRUCTIONS FOR FILLING OUT THIS TEMPLATE`
- `WHEN YOU'RE DONE`

### Markdown-only (.md files)

- Single-curly placeholders: `{role description}`, `{command1}`, etc.
- Double-curly `{{...}}` are handled by the definitive check above

## How to Fix

Open the flagged file and replace template markers with real content. The spawn template shows which sections need filling.

## Bypass

Add to `.seedgo/bypass.json`:

```json
{"file": "<path-substring>", "standard": "template", "reason": "intentionally left as template"}
```

## Scope

`AUDIT_SCOPE = branch_level` — runs once per branch via `check_branch()`.
