[← Back to the skills README](../README.md)

# The Runner

How a skill is executed, what the runner refuses, and which callers never reach it.

## How A Skill Runs

`drone @skills run <name> [action] [args]` resolves the name through discovery,
then the loader parses its `SKILL.md` and imports `handler.py` if it has one.
A handler-based skill is dispatched: the runner calls the handler's `run(action,
args, config)` and returns its `{"success", "output", "error"}` verdict. A
markdown-only skill has nothing to dispatch, so the runner renders its
instructions for the agent to follow. Extra arguments are parsed as `key=value`
pairs, and a bare word becomes a positional `arg0`, `arg1` and so on.

`run <name> --help` is not an action. It prints the skill's own `SKILL.md`,
because handlers that fall through to a default reading used to answer requests
for help by complaining that a skill named `--help` does not exist.

## Running a Skill

```bash
# Run a handler-based skill
drone @skills run my-skill action-name key=value

# Run a markdown skill (displays instructions)
drone @skills run my-skill

# List all available skills
drone @skills list

# Get details about a skill
drone @skills info my-skill

# Check requirements
drone @skills validate my-skill
```


## The Gate, And The Doors That Miss It

The off-switch is consulted here, before the loader imports anything: a
switched-off skill is refused in one line naming the recorded reason, and an
unreadable switch state refuses too rather than defaulting to on. Stopping a
skill's systemd units only quiets the machine — this is the door that keeps its
code from being started in-process. See [off_switch.md](off_switch.md).

Not every caller comes through this door. A function published for in-process
import — `machine_vitals()` in the system_status skill, the notifier in the
telegram skill — is called directly and never meets the gate, so each one asks
the switch itself. A door that forgets to ask keeps working after the skill is
switched off, which is exactly what happened to the telegram notifier: see
[telegram.md](telegram.md).

---

*Owned by the skills branch. The face is [../README.md](../README.md).*
