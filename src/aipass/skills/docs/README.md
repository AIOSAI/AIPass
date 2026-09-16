# docs

Public, tracked documentation for the skills branch — the depth behind
[../README.md](../README.md), which stays a short face for strangers.

| Page | What is in it |
|------|---------------|
| [skill_contract.md](skill_contract.md) | The three tiers, the `SKILL.md` format, the search paths, creating a skill |
| [runner_notes.md](runner_notes.md) | How a skill is executed, and the doors that bypass the runner |
| [off_switch.md](off_switch.md) | What OFF means, what it stops, how it fails closed |
| [system_status.md](system_status.md) | The system_status skill and `machine_vitals()` |
| [telegram.md](telegram.md) | The retired Telegram bridge |
| [dead_cwd.md](dead_cwd.md) | Importing without a readable working directory |
| [json_handler.md](json_handler.md) | Why the JSON handler is a shim |
| [known_issues.md](known_issues.md) | Carried issues, closed incidents, what is unverified |

This is the only one of the branch's four side directories that ships —
`docs.local/`, `dropbox/` and `artifacts/` are gitignored by design, so whatever
is written there is true on this machine and invisible in a PR.

Write here when the reader is someone who cloned the repo: design notes that
outlive a session, reference material a stranger needs to understand a decision.
Anything scratch, inbound, or machine-local belongs in one of the other three.
