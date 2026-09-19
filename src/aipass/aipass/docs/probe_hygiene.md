[<- Back to the README](../README.md)

# Probe Hygiene SOP

Standard operating procedure for throwaway test installs of AIPass.

## Principle

Temporary environments are used, then deleted, gone. Nothing permanent may ever point at a temp path.

## Rules

- Install probes and throwaway test installs live ONLY in throwaway directories (system temp dir, `/tmp`, Claude Code scratchpad dirs).
- Used = deleted = GONE. Delete the probe directory immediately after the test completes.
- NOTHING permanent may ever point at a temporary path: no global settings (`~/.claude/settings.json` `env.AIPASS_HOME`), no symlinks, no registry entries.
- `aipass install` now refuses throwaway homes automatically. The `--force-global-home` flag is the explicit unsafe override, for probe use only.
- `aipass doctor` now detects a hijacked global `AIPASS_HOME` (nonexistent or temp path) and flags it as an error with fix guidance.

## What the defenses do

1. **`is_throwaway_path()`** (bootstrap.py) — detects paths under `tempfile.gettempdir()`, `/tmp` (POSIX), or containing `scratchpad`. Shared gate used by both install and bootstrap.
2. **`run_install()` gate** (install.py) — refuses to proceed when the resolved home is throwaway. Prints a loud `REFUSED` message with guidance. `--force-global-home` overrides.
3. **`_claude_settings()` gate** (bootstrap.py) — refuses to write `env.AIPASS_HOME` into project settings when the detected home is throwaway. Defense-in-depth behind the install gate.
4. **`_check_global_aipass_home()`** (doctor.py) — reads `~/.claude/settings.json` and flags `env.AIPASS_HOME` pointing at a nonexistent or throwaway path as an error.

## Correct probe workflow

```bash
# 1. Create throwaway dir
cd /tmp && mkdir aipass_probe && cd aipass_probe

# 2. Run the probe (install will refuse — this is correct)
aipass install --here
# → REFUSED: '/tmp/aipass_probe' is a temporary/scratchpad path.

# 3. If you genuinely need a temp install (testing only):
aipass install --here --force-global-home

# 4. IMMEDIATELY after testing, delete the probe
rm -rf /tmp/aipass_probe

# 5. Verify global settings are clean
aipass doctor
```
