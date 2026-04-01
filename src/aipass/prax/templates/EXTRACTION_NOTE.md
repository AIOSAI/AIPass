# Dashboard Templates - Extracted from AIPass (legacy devpulse)

Extracted from AIPass devpulse on 2026-03-08. Adapted for `aipass.prax`.

## Files extracted

- `DASHBOARD.template.json` - v3 dashboard schema template with `{{BRANCHNAME}}` placeholder
- `.dashboard_version.json` - Version tracking file (schema v3.0.0, last push metadata)

## Original location (historical)

`/home/aipass/AIPass/devpulse/templates/`

## Notes

- `DASHBOARD.template.json` uses `{{BRANCHNAME}}` placeholder -- replaced at push time
- `.dashboard_version.json` contains AIPass push history (28 branches) -- informational only
- Template defines 5 sections: ai_mail, flow, memory, devpulse, commons_activity
- AIPass may need different sections depending on which modules are active
