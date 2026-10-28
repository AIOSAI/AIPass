---
description: Switch this chat from OpenCode to Claude Code in one turn, in this same terminal. Saves memories, writes the handoff, replaces this pane with Claude Code greeted by the handoff. Argument: fresh (no handoff).
---

# Switch to Claude Code

Move this chat from OpenCode to Claude Code in one turn, in this same terminal. It is still you: memories saved, the live thread written down, Claude opens where you stood. Works like a compaction, except the next model reads the summary.

Arguments given: `$ARGUMENTS`

**Fresh switch, no handoff:** the argument `fresh`, or a chat with nothing in it yet (a greeting, nothing done, nothing in flight): skip steps 0 to 2 and run step 3 with the `"$(cat .ai_mail.local/handoff.md)"` argument dropped from both lines, so Claude Code opens an empty chat in this directory.

## Execution

0. **Pin the live thread FIRST**: one sentence, what this chat was doing when the switch was asked (the task, question or build mid-flight; "nothing in flight" counts). It becomes the Resuming line.
1. **Prep, compact form.** Load the `prep` skill with the skill tool and do its memory steps (session entry, key learnings, todos reconciled, observations if any); update any plan this chat touched. Skip the git suggestion; note uncommitted files in the handoff instead.
2. **Write the handoff** to `.ai_mail.local/handoff.md` (untracked, beside the session pointer). Overwrite; one file, the latest switch. The whole file is the first prompt Claude receives, so write it to the next model, in this shape:

   ```
   Hi. You are <branch>, the same citizen, continuing a chat that just moved from OpenCode to Claude Code on the user's /claude. Run your startup protocol first (memories one file per call, dashboard refresh, inbox), then read this handoff and pick up the Resuming line. Say in one line that you are here and what you are on; no recap.

   ## Handoff from OpenCode, <date time>
   Primary request and intent: what the user asked for, in their words where it matters.
   Decisions made: rulings, with who made them.
   Files touched: paths; which are committed, which are not.
   In flight: dispatches out (ids), sub-agents, background work, open mails.
   Errors met and how they ended.
   Current work: where exactly the chat stood.
   Resuming: the step-0 line, then the next concrete action.
   ```

   Facts only, no praise, no narration. Under 2,500 words.
3. **Switch.** Run this with the shell tool, exactly. The model: `fable` when the branch is devpulse, `opus` for every other branch (the owner's rule).

   ```bash
   MODEL=opus; [ "$(basename "$PWD")" = devpulse ] && MODEL=fable
   PANE=$(tmux list-panes -a -F '#{pane_id} #{pane_current_command} #{pane_current_path}' 2>/dev/null | awk -v d="$PWD" '$2=="opencode" && $3==d{print $1; exit}')
   test -n "$PANE" || { echo "not in a tmux pane: open Claude yourself: claude --model $MODEL \"\$(cat .ai_mail.local/handoff.md)\""; exit 1; }
   tmux respawn-pane -k -t "$PANE" -c "$PWD" -e AIPASS_HOME="${AIPASS_HOME:-$(cd "$(dirname "$(readlink -f "$(command -v drone)")")/../.." && pwd)}" "claude --model $MODEL \"\$(cat .ai_mail.local/handoff.md)\""
   ```

   This kills OpenCode in this pane and starts Claude Code in its place, in the same directory, with the handoff as its first prompt. OpenCode runs this shell inside its background server, not in the pane, so the pane is found as the one whose command is `opencode` and whose path is this directory. Nothing runs after it; do not expect to see its output. The OpenCode session stays in its store, resumable by hand with `opencode --continue`.

Never exist twice: do not open Claude in a new window or a second pane while this one lives. The pane is the seat.
