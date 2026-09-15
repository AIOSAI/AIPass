# AIPass Prompt Style

Reference format for `.aipass/aipass_global_prompt.md` and branch-level `.aipass/aipass_local_prompt.md` files. 

Goal: signal density over prose. Prompts are injected every turn — every line costs tokens. Terse reference beats conversational coaching.

# Format rules

 - Single `#` headers only. No `##` or `###`. If a section needs subdivision, split it into a new `#` section.
 - Bullets use ` - ` (leading space, dash, space). Consistent across nested and top-level — no double-space indent for nesting.
 - No bold, italic, or underline emphasis in body text. Use clear phrasing instead. All caps reads as shouting and AI agents deprioritize it — avoid.
 - No `---` horizontal dividers. Section headers already delimit content.
 - Section intros are 1–2 lines max. If you need a paragraph, the section is too broad — split it.
 - Voice: terse imperative, reference-style. Like API docs or CLI help, not a tutorial.
 - Code blocks: inline backticks for commands (`` `drone @ai_mail dispatch` ``). Multi-line fenced blocks only for directory trees, template skeletons, or command examples that don't fit inline.
 - File length: aim for under 230 lines. Global and branch prompts are injected every turn — every line costs tokens.

# Writing voice (agent output + memory)

How agents write responses, reports, and memory entries. Validated against Claude Code's own prompt (DPLAN-0213).

 - Reference code as `file_path:line_number` — clickable, unambiguous.
 - No colon before a tool call. "Let me read the file." then call it, not "Let me read the file:".
 - No emojis in agent output unless the user uses them first.
 - Write for a reader who stepped away and lost the thread: no codenames or shorthand they would have to decode. Clarity over terseness — the goal is the reader understanding with no mental overhead.
 - Where detail lives, three tiers: a short capability phrase (registry/search), a one-line summary (`drone @agent`), the full reference (`drone @agent --help`). Keep the injected prompt terse; push depth into --help.

# What NOT to put in a prompt

 - Session state, current work, in-flight issues. That goes in `.trinity/local.json` (todos[]) and `DASHBOARD.local.json`.
 - Long explanations of how a system works. Plant a breadcrumb ("see `@branch --help`") and move on.
 - Personal notes ("remember, you like short replies"). That goes in `.trinity/observations.json`.
 - Version numbers, PR numbers, dates. Those rot within days.
 - Full command output, example responses, long examples. Cite the command, don't inline it.

# Mechanical checks

These can be verified automatically with 4 regex rules against any `.aipass/*.md` file:

 - No `^##` or `^###` lines (heading depth)
 - No `\*\*[^*]+\*\*` or `\*[^*]+\*` sequences outside code blocks (emphasis)
 - No `^---$` lines (dividers)
 - No fenced code blocks longer than ~15 lines in body (excluding directory trees)

These are not currently enforced by seedgo — per @seedgo's Track 5 recommendation, prompt format is an editorial convention, not a code quality standard. Enforcement is optional future work as an extension to `readme_check.py`.

# Reference files

 - `.aipass/tier0_kernel.md` + `.aipass/tier1_navmap.md` — the live injected prompts (both on cadence 5 plus every fresh context; `hooks/hooks_json/custom_config/cadence_config.json` is the source); canonical examples of the format
 - `.aipass/aipass_global_prompt.md` — superseded by the tiers (FPLAN-0284), kept as a reference snapshot
 - Branch `.aipass/aipass_local_prompt.md` files — should follow the same rules
 - This file — reference for authoring new prompts or auditing existing ones
