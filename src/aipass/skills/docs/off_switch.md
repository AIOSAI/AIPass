[← Back to the skills README](../README.md)

# The Off-Switch

A skill can be disconnected from AIPass and reconnected later. The setting
persists across restarts and reboots (`skills_json/switch_state.json`).

```bash
drone @skills off screen_lock "not on this host" # disconnect
drone @skills switch                              # who is on, who is off
drone @skills on screen_lock                      # reconnect
```

**OFF** means no code of the skill runs, from any angle:

1. Every systemd user unit the skill declares is **stopped**.
2. Those units are **disabled and masked**, so nothing can respawn them — not a
   manual `systemctl start`, not a dependency, not a script.
3. `drone @skills run <name>` **refuses** in one line that carries the recorded
   reason, before the skill's handler is imported.
4. `drone @skills info <name>` imports nothing: it shows the metadata and the
   SKILL.md text, says the skill is OFF, and exits 0.
5. `drone @skills validate <name>` imports nothing: it says the skill is OFF and
   was not validated — neither valid nor invalid — and exits 1, so
   `validate x && next` never treats an unchecked skill as checked.
6. Every function served through `from aipass.skills import ...` refuses.

An unreadable switch state counts as OFF for all of these, with the error shown;
`info` then exits 1. `list` still shows an OFF skill, marked OFF.

A refusal because a skill is off on purpose is logged as INFO: the switch did
its job, and that is not a fault. An unreadable switch state is logged as ERROR:
it is a fault, and someone has to repair the file.

What OFF cannot stop: reading a SKILL.md straight off disk. For a markdown-only
skill the text is the skill.

**ON** reverses the systemd steps: unmask, enable, start. A unit that does not come back
is reported rather than assumed — the switch never prints "dark" over a live
process, or "running" over a dead one.

A skill declares what belongs to it in its own SKILL.md frontmatter:

```yaml
switch:
  systemd_user:
    - my-skill-worker@main
```

A skill that declares nothing still toggles; it simply owns no processes to
stop. If `switch_state.json` is ever unreadable, skills **refuse to run** rather
than defaulting to on — defaulting to on would restart exactly what someone
deliberately switched off. `on` and `off` refuse too: they write nothing, leave
the file as it is for repair, and name the fix on stderr — repair the file, or
`drone rm` it to reset every skill to on. A missing file is a clean start: every
skill on.

A function that is imported in-process never passes the runner's gate, so it
asks the switch itself — `machine_vitals()` and `machine_processes()` in the
system_status skill (see [system_status.md](system_status.md)), `lock_screen()`
and `lock_state()` in the screen_lock skill.

---

*Owned by the skills branch. The face is [../README.md](../README.md).*
