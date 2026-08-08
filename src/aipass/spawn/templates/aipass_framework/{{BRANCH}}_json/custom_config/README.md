# Custom Config

Operator-owned override slot for `{{BRANCHNAME}}`. Hand-edited runtime settings live here — nothing auto-generated, nothing written by code.

Operational JSON (`config.json`, `data.json`, `log.json`) belongs one level up in `{{BRANCH}}_json/`, not here.

## The pattern

- **Code holds the defaults.** The values in code are the shipped truth. The branch must run correctly with this directory empty.
- **A file here holds ONLY overrides.** Just the keys you deliberately changed — never a full copy of the defaults.
- **Deep-merged over defaults at load.** Your keys win; everything you left out keeps following code.
- **Missing file = defaults = safe.** No file is the normal case, not an error.
- **Never write defaults to disk.** Code must not snapshot its own defaults into a file here. A snapshot freezes today's values and silently overrides every future change to them — the override slot becomes a stale mirror nobody remembers editing.

## Naming

`<thing>.config.json` or `<thing>_config.json` — e.g. `memory.config.json`, `cadence_config.json`.

---

Source of truth for these rules: `drone @seedgo standards_query aipass_standards json_structure`
