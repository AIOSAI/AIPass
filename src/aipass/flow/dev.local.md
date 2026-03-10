# dev.local.md - FLOW
```
Branch: src/aipass/flow
Created: 2026-03-07
Updated: 2026-03-10
```

## Active Work

- **FPLAN-0017**: Implement Two-Level Introspection Standard (from seedgo)

## Completed

- **FPLAN-0021**: Wire DPLANs into flow CLI router and clean up templates (2026-03-10)
  - Remapped dplan_flow.py imports from aipass_os to aipass.flow local handlers
  - Fixed template.py, display.py, dplan_post_close_runner.py Dev-Pass imports
  - Added DPLAN examples to --help, updated all references to drone syntax
  - Fixed routing order so `plan` subcommands work through flow.py
  - Updated FPLAN templates: @memory_bank to @memory
- **Dispatch**: Handler path migration + template detection fix (2026-03-10)
  - All 9 DPLAN handler data paths migrated from aipass_os/aipass_core to Path(__file__).parents[N]
  - DPLANs now create/list/close in flow/dev_planning/ (verified)
  - Removed all sys.path hacks from handlers
  - Fixed is_template_content() data loss: removed section headers from markers, added user content detection

## Issues

- None currently tracked

---

## Todos

- (none)
