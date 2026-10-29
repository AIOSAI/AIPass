---
name: claude
description: Switch this chat from Codex to Claude Code in one turn, in this same terminal. Use when the user says /claude, "switch to claude", "back to claude" or "hand over to claude". Saves memories, writes the handoff, replaces this pane with Claude Code greeted by the handoff.
---

# Switch to Claude Code

Purpose: move this chat from Codex to Claude Code in one turn, in this same terminal. It is still you: memories saved, the live thread written down, Claude opens where you stood. Works like a compaction, except the next model reads the summary.

**Fresh switch, no handoff:** `$claude fresh` (the word arrives after the skill name in the message), or a chat with nothing in it yet (a greeting, nothing done, nothing in flight): skip steps 0 to 2 and run step 3 with the `\"$(cat .ai_mail.local/handoff.md)\"` argument dropped from both lines, so Claude Code opens an empty chat in this directory. There is no thread to carry; the user greets it and the startup protocol runs as on any fresh chat.

## Execution

0. **Pin the live thread FIRST** — one sentence: what this chat was doing when the switch was asked (the task, question or build mid-flight; "nothing in flight" counts). It becomes the Resuming line.
1. **Prep, compact form.** Do the memory steps of `.agents/skills/prep/SKILL.md` (session entry, key learnings, todos reconciled, observations if any) and update any plan this chat touched. Skip the git suggestion; note uncommitted files in the handoff instead.
2. **Write the handoff** to `.ai_mail.local/handoff.md` (untracked, beside the session pointer). Overwrite; one file, the latest switch. The whole file is the first prompt Claude receives, so write it to the next model, in this shape:

   ```
   Hi. You are <branch>, the same citizen, continuing a chat that just moved from Codex to Claude Code on the user's /claude. Run your startup protocol first (memories one file per call, dashboard refresh, inbox), then read this handoff and pick up the Resuming line. Say in one line that you are here and what you are on; no recap.

   ## Handoff from Codex, <date time>
   Primary request and intent: what the user asked for, in their words where it matters.
   Decisions made: rulings, with who made them.
   Files touched: paths; which are committed, which are not.
   In flight: dispatches out (ids), sub-agents, background work, open mails.
   Errors met and how they ended.
   Current work: where exactly the chat stood.
   Resuming: the step-0 line, then the next concrete action.
   ```

   Facts only, no praise, no narration. Under 2,500 words. The next model has your memories; the handoff carries what memories do not: the live thread.
3. **Switch.** Run in the shell. The model: `fable` when the branch is devpulse, `opus` for every other branch (the owner's rule: Fable is devpulse's seat only).

   ```bash
   MODEL=opus; [ "$(basename "$PWD")" = devpulse ] && MODEL=fable
   p=$$; PANE=""; while [ "$p" -gt 1 ] && [ -z "$PANE" ]; do PANE=$(tmux list-panes -a -F '#{pane_id} #{pane_pid}' 2>/dev/null | awk -v pid="$p" '$2==pid{print $1}'); p=$(awk '{print $4}' /proc/$p/stat); done
   [ -n "$PANE" ] || PANE=$(tmux list-panes -a -F '#{pane_id} #{pane_current_command} #{pane_current_path}' 2>/dev/null | awk -v d="$PWD" '$2=="codex" && $3==d{print $1; exit}')
   test -n "$PANE" || { echo "not in a tmux pane: open Claude yourself: claude --model $MODEL \"\$(cat .ai_mail.local/handoff.md)\""; exit 1; }
   tmux respawn-pane -k -t "$PANE" -c "$PWD" -e AIPASS_HOME="${AIPASS_HOME:-$(cd "$(dirname "$(readlink -f "$(command -v drone)")")/../.." && pwd)}" "claude --model $MODEL \"\$(cat .ai_mail.local/handoff.md)\""
   ```

   This kills Codex in this pane and starts Claude Code in its place, in the same directory, with the handoff as its first prompt. Codex runs this shell from its long-lived app-server daemon, not from the pane: the shell's ancestors never reach the pane, and `$TMUX_PANE` is whatever pane first started the daemon. So the pane is the one whose command is `codex` and whose path is this directory. The daemon also carries the env of the Codex that first started it; when that env lacks `AIPASS_HOME`, every hook exits 127 and the value here falls back to the repo that owns the `drone` on PATH. Nothing runs after it; do not expect to see its output. The Codex thread stays on disk, resumable by hand with `codex resume`.

Never exist twice: do not open Claude in a new window or a second pane while this one lives. The pane is the seat.
