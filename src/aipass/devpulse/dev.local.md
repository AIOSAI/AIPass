# dev.local.md - DEVPULSE
```
Branch: src/aipass/devpulse
Created: 2026-03-07
Updated: 2026-03-10
```

## Active Work

- **Flow dispatch**: DPLAN path fixes + FPLAN empty template detection — dispatched to flow, branch awake
- **Prompt architecture**: DONE — breadcrumbs in global+local, dev.local.md headers fixed system-wide

## Issues

- **flow/DPLAN**: All 10 handler files use Dev-Pass paths (`~/aipass_os/dev_central/dev_planning/`). Creates orphan dirs. Dispatched to flow.
- **flow/FPLAN**: `is_template_content()` too aggressive — deletes plans with real content if template boilerplate remains. Data loss bug. Dispatched to flow.
- **flow/FPLAN archive**: Closed FPLANs go to `src/aipass/backup_system/processed_plans/` — backup_system isn't a branch (Dev-Pass name). Leaving for later.
- **prax**: Missing `handlers/central/reader.py` — dashboard/refresh.py imports `read_all_centrals` but function never created
- **backup**: Missing `config.json` template in json_templates/
- **api**: `models` command not routed through drone
- **commons**: DB init failure (12/13 core branches operational)
- **ai_mail**: `get_current_user()` returns relative `mailbox_path` — causes doubled paths in reply
- **drone**: stderr kwarg crash

## Completed

- PR #31 merged: seedgo v2, 589 files, full system audit (2026-03-10)
- ai_mail sender identity bug FIXED by Patrick
- Renamed flow.local.md → dev.local.md system-wide (17 files)
- Fixed dev.local.md headers system-wide (16 branch files + spawn template)
- FPLAN-0021 dispatched+completed by flow: DPLANs wired into CLI router
- Revised devpulse branch prompt — breadcrumb pattern, working habits, expertise table
- Added Breadcrumbs section + dev.local.md awareness to global prompt
- Updated .trinity/ memories with Session 18
- Processed inbox: ai_mail fix reply, flow FPLAN-0021 completion, old stress test
- Full FPLAN lifecycle tested: create (default+master), list, close (empty+content)
- Full DPLAN lifecycle tested: create, list, status, close

---

## Todos

- [x] Update global prompt with dev.local.md awareness
- [x] Fix dev.local.md headers system-wide
- [ ] Re-send emails to prax and backup about their known issues
- [ ] Scaffold remaining modules with system prompts (.aipass/aipass_local_prompt.md)
- [ ] Test dispatch wake to branches beyond ai_mail
- [ ] Address drone stderr kwarg crash
- [ ] Close stale FPLANs (0017, 0021) once verified complete

## Notepad

- Dev-Pass reference: `/home/patrick/Projects/Dev-Pass/`
- seed=Dev-Pass name, seedgo=AIPass name
- FPLAN close 5-step process: template check → mark closed → background archival → dashboard update → finalize
- DPLAN close 3-step process: close → background memory bank archival → finalize
