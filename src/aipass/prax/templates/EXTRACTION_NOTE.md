# Dashboard Templates - Extracted from Dev-Pass

Extracted from Dev-Pass devpulse on 2026-03-08.

These files need adaptation for AIPass before use.

Original imports use `aipass_os.dev_central.devpulse` -- must be converted to `aipass.prax`.

## Files extracted

- `DASHBOARD.template.json` - v3 dashboard schema template with `{{BRANCHNAME}}` placeholder
- `.dashboard_version.json` - Version tracking file (schema v3.0.0, last push metadata)

## Original location

`/home/aipass/aipass_os/dev_central/devpulse/templates/`

## Notes

- `DASHBOARD.template.json` uses `{{BRANCHNAME}}` placeholder -- replaced at push time
- `.dashboard_version.json` contains Dev-Pass push history (28 branches) -- informational only
- Template defines 5 sections: ai_mail, flow, memory_bank, devpulse, commons_activity
- AIPass may need different sections depending on which modules are active
