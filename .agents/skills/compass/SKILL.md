---
name: compass
description: Record the decision just made into compass, the rated decision store, with the user's rating (good, bad, impressive, interesting) and note. The user fires it when they notice a decision worth keeping.
---

# Compass — Record a Decision

Purpose: Capture the decision just made into compass (the rated decision engine) with the user's rating and note. The user fires this when they notice a decision worth recording — they supply the judgement, you supply the decision text from the conversation. This is the human-triggered answer to the "noticing" problem: the user notices, you describe and store.

Usage: `/compass <rating> <note>` in Claude Code and OpenCode, `$compass <rating> <note>` in Codex — rating is one of: `good`, `bad`, `impressive`, `interesting`.

Examples:
- `/compass good chose to continue the dead agent instead of starting fresh`
- `/compass bad reached into the branch instead of dispatching`
- `/compass impressive` (rating only — you write context, decision, and note from the conversation)

Arguments: the words the user typed after the command name.

## Execution

1. Parse the words after the command name:
   - First token = `rating`. It MUST be one of `good | bad | impressive | interesting`. If it isn't, don't guess — ask the user which rating they meant and stop.
   - Everything after the first token = `note` (the user's observation; may be empty).
2. From the recent conversation, identify the decision being rated. Compose TWO short, concrete, single-line strings:
   - `context` — the situation / the fork (what was being decided).
   - `decision` — what was actually chosen.
   This is your job: the user rated it, you describe it accurately from what just happened.
3. Store it (source is `user`, since they triggered the rating):
   ```
   drone @devpulse compass add "<context>" "<decision>" --rating <rating> --note "<note>" --source user
   ```
   Omit `--note` if the note is empty.
4. Confirm in one line: the rating, the decision recorded, and the new id.

## Notes

- Compass is the curated truth-store of decisions — short entries only. Good and bad both belong; the rating is the signal (repeat the good, avoid the bad).
- Compass is separate from @memory. Do NOT also write this to `.trinity/` or memory — different store, different purpose.
- If the decision the user means is ambiguous, ask before storing. One good entry beats a vague one.
- Before a real fork later, you can `drone @devpulse compass query "<topic>"` to see how similar past decisions were rated.
