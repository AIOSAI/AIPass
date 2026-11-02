# Standards Bypass

Sentry audit bypass config for `SENTRY`.

When an audit flags a false positive that doesn't apply to your architecture, add a bypass entry in `bypass.json` with a reason explaining why it's justified.

## Fields

| Field | Required | Description |
|-------|----------|-------------|
| `file` | yes | Relative path from branch root |
| `standard` | yes | Standard name (cli, imports, naming, etc.) |
| `lines` | no | Specific line numbers to bypass |
| `functions` | no | Function names for name-scoped bypass (required for `unused_function`) |
| `reason` | yes | Why this bypass exists |

## Name-scoped bypass (unused_function)

Use `functions` instead of `lines` for `unused_function` bypasses — function names are stable across edits, line numbers drift silently:

```json
{
  "file": "apps/handlers/registry.py",
  "standard": "unused_function",
  "functions": ["get_skill", "get_skill_names"],
  "reason": "Public API surface — called by external consumers"
}
```
