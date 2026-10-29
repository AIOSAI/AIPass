# Switch to Codex

Purpose: move this chat from Claude Code to Codex in one turn, in this same terminal. It is still you: memories saved, the live thread written down, Codex opens where you stood. Works like a compaction, except the next model reads the summary.

**Workflow:** `/codex` → prep → handoff written → this pane becomes Codex, greeting it with the handoff.

**Fresh switch, no handoff:** `/codex fresh` (arguments: `$ARGUMENTS`), or a chat with nothing in it yet (a greeting, nothing done, nothing in flight): skip steps 0 to 2 and run step 3 with the `"$(cat .ai_mail.local/handoff.md)"` argument dropped from both lines, so Codex opens an empty chat in this directory. There is no thread to carry; the user greets it and the startup protocol runs as on any fresh chat.

## Execution

0. **Pin the live thread FIRST** — one sentence: what this chat was doing when `/codex` fired (the task, question or build mid-flight; "nothing in flight" counts). It becomes the Resuming line.
1. **Prep, compact form.** Do the memory steps of `.agents/skills/prep/SKILL.md` (session entry, key learnings, todos reconciled, observations if any) and update any plan this chat touched. Skip the compass review and the git suggestion; note uncommitted files in the handoff instead.
2. **Write the handoff** to `.ai_mail.local/handoff.md` (untracked, beside the session pointer). Overwrite; one file, the latest switch. The whole file is the first prompt Codex receives, so write it to the next model, in this shape:

   ```
   Hi. You are <branch>, the same citizen, continuing a chat that just moved from Claude Code to Codex on the user's /codex. Run your startup protocol first (memories one file per call, dashboard refresh, inbox), then read this handoff and pick up the Resuming line. Say in one line that you are here and what you are on; no recap.

   ## Handoff from Claude Code, <date time>
   Primary request and intent: what the user asked for, in their words where it matters.
   Decisions made: rulings, with who made them.
   Files touched: paths; which are committed, which are not.
   In flight: dispatches out (ids), sub-agents, background work, open mails.
   Errors met and how they ended.
   Current work: where exactly the chat stood.
   Resuming: the step-0 line, then the next concrete action.
   ```

   Facts only, no praise, no narration. Under 2,500 words. The next model has your memories; the handoff carries what memories do not: the live thread.
3. **Switch.** Run, with the Bash tool:

   ```bash
   p=$$; PANE=""; while [ "$p" -gt 1 ] && [ -z "$PANE" ]; do PANE=$(tmux list-panes -a -F '#{pane_id} #{pane_pid}' 2>/dev/null | awk -v pid="$p" '$2==pid{print $1}'); p=$(awk '{print $4}' /proc/$p/stat); done
   [ -n "$PANE" ] || PANE=$(tmux list-panes -a -F '#{pane_id} #{pane_current_command} #{pane_current_path}' 2>/dev/null | awk -v d="$PWD" '$2=="claude" && $3==d{print $1; exit}')
   test -n "$PANE" || { echo "not in a tmux pane: open Codex yourself: codex --dangerously-bypass-approvals-and-sandbox \"\$(cat .ai_mail.local/handoff.md)\""; exit 1; }
   tmux respawn-pane -k -t "$PANE" -c "$PWD" -e AIPASS_HOME="${AIPASS_HOME:-$(cd "$(dirname "$(readlink -f "$(command -v drone)")")/../.." && pwd)}" 'codex --dangerously-bypass-approvals-and-sandbox "$(cat .ai_mail.local/handoff.md)"'
   ```

   The posture mirrors BAUD's rooms (`claude --permission-mode bypassPermissions`): the hooks are the gates on both CLIs.

   This kills Claude Code in this pane and starts Codex in its place, in the same directory, with the handoff as its first prompt. The pane is found by walking up from this shell to the process tmux started, never from `$TMUX_PANE`; when the walk finds nothing, by the pane whose command is `claude` and whose path is this directory. Codex runs its shells and hooks from a long-lived app-server daemon that keeps the env of the first Codex that started it: `AIPASS_HOME` must be exported by the login shell (`~/.profile`), not only by `~/.bashrc`, or every hook exits 127 until that daemon is restarted. `-e` carries it to the pane for everything that reads the process env. Nothing runs after it; do not expect to see its output. The Claude transcript stays on disk, resumable by hand with `claude --resume`.

Never exist twice: do not open Codex in a new window or a second pane while this one lives. The pane is the seat.
