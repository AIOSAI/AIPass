# {plan_number} - {subject} (RECOVERY)

> **Create:** `drone @flow create . "What broke" recovery pplan` (template name before type). When drone does not run, read this file where it lies and work it without a plan.

**Created**: {today}
**Branch**: {location}
**Status**: Active
**Type**: Playbook — Recovery SOP

---

## Who this is for

An agent with no memory of AIPass, started by the owner because the agents inside it cannot work. Also the admin seat (@devpulse) in safe mode. Read the whole page before you run anything.

**Finished = closed.** When drone runs again and the break is cured, whoever finished closes this plan, no permission asked: `drone @flow close {plan_number}`. Closing loses nothing: `drone @flow restore {plan_number}` reopens it. When several open plans orbit one break, any agent may close the lot and open ONE new plan for the live remainder, pointing back to the closed IDs.

## Owner: your whole job

Open a terminal and start a fresh Claude from your home directory — not inside the project:

```
cd ~
claude
```

Paste this prompt, with the path corrected if your AIPass checkout is somewhere else:

```
AIPass is broken: every agent inside it refuses tools with a message that
starts HOOKS BROKEN. My checkout is at ~/AIPass. Read
~/AIPass/src/aipass/flow/templates/playbook_plans/recovery.md
and follow it exactly: run diagnose first, then only the cure the guide
picks from the traceback. Delete nothing, commit nothing, push nothing,
edit no code. If neither cure applies, stop and tell me what you saw.
```

Then answer what the agent asks and read what it reports. The rest of this page is for that agent.

## What the break is

AIPass runs a hook engine before every tool call of every agent. The engine loads code from the working tree on each call (`src/aipass/prax`, `src/aipass/hooks`, `src/aipass/cli` and what they import). An edit left half done in that code makes the engine fail, and it then refuses every tool of every agent with a message that starts `HOOKS BROKEN`. No agent inside can read, edit or run, so none can fix it.

The work is not lost. The code has to go back to its last commit, and the half-done edit has to be kept aside. That is the whole cure, and one command does it. The rarer break is a bad promoted copy of the hooks themselves; a second command serves the copy before it.

## The law

1. **Nothing is deleted.** No `rm`, no `git reset --hard`, no `git checkout` or `git restore` of files, no `git clean`, no `git stash drop` or `pop`.
2. **Nothing is published.** No commit, no push, no pull, no branch change.
3. **Never touch** `.trinity/`, `.ai_mail.local/`, `.archive/`, `.git/`, the keys under `~/.aipass`, `~/.claude`, `~/.codex`, or any secrets file.
4. **Two cures only: park and rollback.** When neither cures it, stop and tell the owner what you saw. Do not edit code to fix it.
5. **A fresh agent starts outside the project**, in the home directory. A session started inside the project is under the broken hooks.

## Steps

The recovery command is one file, written with the full path of the checkout (the folder that holds `AIPASS_REGISTRY.json` and `src/aipass`):

```
python3 -I CHECKOUT/src/aipass/hooks/apps/handlers/bridges/safe_mode.py diagnose
python3 -I CHECKOUT/src/aipass/hooks/apps/handlers/bridges/safe_mode.py park src/aipass/BRANCH/apps
python3 -I CHECKOUT/src/aipass/hooks/apps/handlers/bridges/safe_mode.py rollback
```

- [ ] **1. Diagnose.** Run `diagnose`. It answers one of two things.
  - "The hook engine runs": this is not that break. Stop. Ask the owner what he sees.
  - "THE HOOK ENGINE IS BROKEN", a traceback, and a list of uncommitted code.
- [ ] **2. Name the code that failed.** It is the last `File` line of the traceback.
  - Under `src/aipass/BRANCH/apps`, and that branch is in the list of uncommitted code: step 3, park.
  - Under `src/aipass/hooks/.live-` and a time stamp: the promoted copy of the hooks is bad. Run `rollback` instead of step 3. It serves the copy promoted before it, and puts things back by itself when that is no cure. Then step 4.
  - Neither: the break is already committed, or it is not code. Nothing here cures it. Stop and report.
- [ ] **3. Park that branch's code.** Run `park src/aipass/BRANCH/apps`. Only a path inside a branch's `apps/` folder is accepted. It prints `PARKED`, the name of the git stash that now holds the changes, and the path of a readable patch. That path of the tree is as it was at the last commit.
- [ ] **4. Read the result.** Park and rollback re-check the engine themselves.
  - "The hook engine runs again": done, go to step 5.
  - "STILL broken", and the new traceback names another branch with uncommitted code: park that one. Three parks at most, then stop and report.
- [ ] **5. Prove it.** The owner opens a session inside the project and runs any command. It runs.
- [ ] **6. Report to the owner**, in plain words: what was broken (the last lines of the traceback), what was parked (each stash name and patch path) or which copy was rolled back from, and that every command is in `~/.aipass/recovery/log.jsonl`.

## After

- The parked work stays in the git stash until the owner decides. `git stash list` shows it by name. Bringing it back as it was brings the break back.
- The seat that wrote it reads the patch and builds the change again in a copy beside the live file, proves it, and swaps it in with one write. Code the engine loads is never edited in place.

## The admin seat in safe mode

While the engine is broken, the Claude bridge lets the admin seat run exactly the three commands above, spelled as the `HOOKS BROKEN` text prints them, and refuses everything else. Steps 1 to 6 are the same. When the engine runs again safe mode is over by itself, and on a healthy system the git gate refuses the command.

## What this page does not cure

- A break that is committed: the last commit itself is broken.
- A broken config file outside `apps/`.
- `drone` failing while tools still run: the engine is healthy, so park refuses. Read the error and report it.
- A session on Codex, OpenCode or Seed: their bridges refuse while broken and have no safe mode. Recover from a Claude Code session or a plain shell.

## Notes

What you saw, what you ran, what it answered.

---

*Spoken summary: written only when the user asks for one, in plain sentences with no markup.*
