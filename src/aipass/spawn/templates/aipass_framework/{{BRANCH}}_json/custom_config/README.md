# Custom Config

Operator-owned runtime config for `{{BRANCHNAME}}`. The JSON here is the **authority** — it is what the branch actually runs on, and it is yours to edit.

Operational JSON (`config.json`, `data.json`, `log.json`) belongs one level up in `{{BRANCH}}_json/`, not here.

## The pattern

- **The file is the runtime authority.** Configs live inside JSONs, not inside code. Your values win over code on every load — nobody should have to search source to find a setting.
- **Code holds `DEFAULT_CONFIG` as the regeneration seed.** Its one job is to rebuild this file when it goes missing, so keep it aligned with the values we actually operate on: regenerate what we run.
- **Missing file = regenerated in full.** The loader writes the complete config back from the seed, so you are never left without a file to edit. Missing is safe, not an error.
- **Malformed file = fail loud, never clobbered.** A stray comma costs you nothing: the loader logs an ERROR, serves defaults in memory, and leaves your bytes untouched. Your values are live again the moment it parses.
- **Code writes here only on that self-heal path.** Nothing else in the branch writes to this directory. Partial files are fine — whatever you leave out is deep-merged from the seed at load.

## Naming

`<thing>.config.json` or `<thing>_config.json` — e.g. `memory.config.json`, `cadence_config.json`.

---

Source of truth for these rules: `drone @seedgo standards_query aipass_standards json_structure`
Reference loader: `src/aipass/memory/apps/handlers/json/config_loader.py`
