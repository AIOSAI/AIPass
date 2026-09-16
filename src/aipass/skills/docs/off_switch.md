[← Back to the skills README](../README.md)

# The Off-Switch

A skill can be disconnected from AIPass and reconnected later. Design record: `DPLAN-0306`.

A skill can be disconnected from AIPass and reconnected later. The setting
persists across restarts and reboots (`skills_json/switch_state.json`).

```bash
drone @skills off telegram "retired 2026-08-18"   # disconnect
drone @skills switch                              # who is on, who is off
drone @skills on telegram                         # reconnect
```

**OFF** means three things, not one:

1. Every systemd user unit the skill declares is **stopped**.
2. Those units are **disabled and masked**, so nothing can respawn them — not a
   manual `systemctl start`, not a dependency, not a script.
3. `drone @skills run <name>` **refuses** in one line that carries the recorded
   reason, before the skill's handler is imported. Stopping units only quiets the machine; this is what makes the
   skill dark.

**ON** reverses all three: unmask, enable, start. A unit that does not come back
is reported rather than assumed — the switch never prints "dark" over a live
process, or "running" over a dead one.

A skill declares what belongs to it in its own SKILL.md frontmatter:

```yaml
switch:
  systemd_user:
    - telegram-bot@base
```

A skill that declares nothing still toggles; it simply owns no processes to
stop. If `switch_state.json` is ever unreadable, skills **refuse to run** rather
than defaulting to on — defaulting to on would restart exactly what someone
deliberately switched off. Design record: `DPLAN-0306`.

A door that is imported in-process never passes the runner's gate, so it asks
the switch itself — `machine_vitals()` in the system_status skill, and the
telegram notifier. See [system_status.md](system_status.md) and
[telegram.md](telegram.md).

---

*Owned by the skills branch. The face is [../README.md](../README.md).*
