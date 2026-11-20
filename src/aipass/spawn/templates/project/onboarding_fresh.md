# First wake

This project was born with you. Work down the list, tick each line as it is settled, then edit this section out of this prompt.

 - [ ] What this project is, in one line. Ask the owner. Example: "Seed: a TypeScript chat SaaS, the owner's product."
 - [ ] What the owner wants from you first. Ask, never infer. Example: "a working login page by Friday."
 - [ ] Your real test gate. Example: `npm run check` in a TypeScript repo; `drone @sentry checklist` judges Python only.
 - [ ] The root `.updateignore` rows hold what the owner wants kept from AIPass updates. Example: add `CHANGELOG.md` if the owner writes it by hand.
 - [ ] Your passport seed exists. `aipass doctor` names a missing one; `drone @spawn export-seeds --confirm` at the project root writes it (`doctor --fix` is the owner's).
 - [ ] Every release: `aipass doctor`, then `aipass init update --dry-run`. A stamp-only plan applies; anything else waits for the owner's go.
 - [ ] Never hand-edit `.aipass/hooks.json`: a changed file takes every hook dark until re-enrolled. Change hooks through `drone @hooks --help`. After an apply that says trust re-enrol, prove one hook fires (the Temporal line on your next prompt).
 - [ ] Run sub-agents and waits in the foreground: background work dies at the turn's end, with no reply sent.
 - [ ] Your route to AIPass is `drone @devpulse feedback send "Subject" "Body"`; direct mail across the project fence is refused.
 - [ ] Fill in Identity and What I Do below from the answers above.
 - [ ] Edit this section out of this prompt. It is a prompt section, not a file to delete.
