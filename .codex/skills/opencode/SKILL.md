---
name: opencode
description: Switch this chat from Codex to OpenCode in one turn, in this same terminal. Use when the user says $opencode, "switch to opencode" or "hand over to opencode". Saves memories, writes the handoff, replaces this pane with OpenCode greeted by the handoff.
---

# Switch to OpenCode

Purpose: move this chat from Codex to OpenCode in one turn, in this same terminal. It is still you: memories saved, the live thread written down, OpenCode opens where you stood, on whatever model it is set to. Works like a compaction, except the next model reads the summary.

**The words after the skill name:** `fresh` skips the handoff; a word with a slash in it (`opencode/glm-5.3-flash-free`, `openai/gpt-6-sol`) is the model OpenCode opens on, passed as inline config; nothing means OpenCode's own default model.

**Fresh switch, no handoff:** `$opencode fresh`, or a chat with nothing in it yet (a greeting, nothing done, nothing in flight): skip steps 0 to 2 and run step 3 with the `--prompt` argument dropped, so OpenCode opens an empty chat in this directory. There is no thread to carry; the user greets it and the startup protocol runs as on any fresh chat.

## Execution

0. **Pin the live thread FIRST** — one sentence: what this chat was doing when the switch was asked (the task, question or build mid-flight; "nothing in flight" counts). It becomes the Resuming line.
1. **Prep, compact form.** Do the memory steps of `.agents/skills/prep/SKILL.md` (session entry, key learnings, todos reconciled, observations if any) and update any plan this chat touched. Skip the git suggestion; note uncommitted files in the handoff instead.
2. **Write the handoff** to `.ai_mail.local/handoff.md` (untracked, beside the session pointer). Overwrite; one file, the latest switch. The whole file is the first prompt OpenCode receives, so write it to the next model, in this shape:

   ```
   Hi. You are <branch>, the same citizen, continuing a chat that just moved from Codex to OpenCode on the user's $opencode. Run your startup protocol first (memories one file per call, dashboard refresh, inbox), then read this handoff and pick up the Resuming line. Say in one line that you are here and what you are on; no recap.

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
3. **Switch.** Run in the shell, with `MODEL` set to the slash word from the message or left empty:

   ```bash
   MODEL=""; CFG=""; [ -n "$MODEL" ] && CFG="OPENCODE_CONFIG_CONTENT={\"model\":\"$MODEL\"}"
   p=$$; PANE=""; while [ "$p" -gt 1 ] && [ -z "$PANE" ]; do PANE=$(tmux list-panes -a -F '#{pane_id} #{pane_pid}' 2>/dev/null | awk -v pid="$p" '$2==pid{print $1}'); p=$(awk '{print $4}' /proc/$p/stat); done
   [ -n "$PANE" ] || PANE=$(tmux list-panes -a -F '#{pane_id} #{pane_current_command} #{pane_current_path}' 2>/dev/null | awk -v d="$PWD" '$2=="codex" && $3==d{print $1; exit}')
   test -n "$PANE" || { echo "not in a tmux pane: open OpenCode yourself: $CFG opencode --standalone --auto --prompt \"\$(cat .ai_mail.local/handoff.md)\""; exit 1; }
   tmux respawn-pane -k -t "$PANE" -c "$PWD" -e AIPASS_HOME="${AIPASS_HOME:-$(cd "$(dirname "$(readlink -f "$(command -v drone)")")/../.." && pwd)}" ${CFG:+-e "$CFG"} 'PATH="$HOME/.opencode/bin:$PATH" opencode --standalone --auto --prompt "$(cat .ai_mail.local/handoff.md)"'
   ```

   The `PATH` prefix is the curl installer's bin, which `~/.bashrc` adds for login shells only: a respawned pane runs `sh -c` with the tmux server's env. `--auto` is OpenCode's bypass posture, as `--dangerously-bypass-approvals-and-sandbox` is Codex's: the hooks are the gates on every CLI. This kills Codex in this pane and starts OpenCode in its place, in the same directory, with the handoff as its first prompt. Codex runs this shell from its long-lived app-server daemon, not from the pane: the shell's ancestors never reach the pane, so the pane is the one whose command is `codex` and whose path is this directory. `--standalone` gives this seat a private server with this pane's env: without it the TUI joins the user's shared server, which keeps the env of whoever started it, so the inline model config and `AIPASS_HOME` carried by `-e` never reach the model call or the hooks. Nothing runs after it; do not expect to see its output. The Codex thread stays on disk, resumable by hand with `codex resume`.

Never exist twice: do not open OpenCode in a new window or a second pane while this one lives. The pane is the seat.
