# Templates

Branch-specific templates for `BACKUP`.

Any templates this branch provides to the system or uses internally. Examples: plan templates (flow), trinity templates (memory), test templates (sentry).

## Files

- **`backupignore.template`** — Seed content for a new project's `.backupignore`. Written at `register` time by `setup._build_backupignore()`. Edit this to change the default ignore patterns for newly registered projects.
