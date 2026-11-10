# CPLAN-0003: Seed cleanup list: small items found along the way

Tag: 

> One-line description of what this captures

---

## What is a CPLAN?

Capture Plans (CPLANs) are **records, not plans** — a soft memo wearing the plan lifecycle. Something worth keeping just happened: an external review landed, a discovery connected systems nobody knew were connected, a dense session produced knowledge too big for a .trinity entry. Write it down, close it, done. Closing vectorizes it into @memory — recallable forever by concept via `drone @memory search`.

**Born to close.** A CPLAN is created, filled, and closed in the same sitting. If it stays open past a day, it probably wanted to be a DPLAN.

**This IS for:**
- External reviews, audits, contributions — capture the substance and our response
- Discoveries — a mechanism traced, a connection found, a mystery solved
- Rich session knowledge that would otherwise live only in chat scrollback
- The full context behind rulings, so the *why* survives the decision
- Anything worth recalling later that carries no work to execute

**This is NOT for:**
- Work to execute — that's FPLAN
- Designs to develop or decisions still open — that's DPLAN
- Standing health records — that's APLAN
- Curated decision verdicts — that's compass (`drone @devpulse compass add`); a CPLAN can *link* compass entries, not replace them

**No fixed structure below the Capture heading.** Write what happened the way it happened. Never trim — detail is the point; the vector store handles the size.

---

## Source & Context

Patrick, 2026-11-07 23:03: a side list of Seed cleanup items, added as we find them, worked in one cleanup session in a few days. Seed repo: ~/Projects/seed (main 973c155 onward, deployed v99).

## The Capture

Add items at the bottom, one line each: what, where, why.

- [ ] Laptop leftovers from test runs: ~/.config/seed/heads and ~/.config/seed/home (drone rm refuses outside AIPass; Patrick removes)
- [ ] /proc: Seed lists every process on the machine, Fly's hallpass included; mount /proc with hidepid=2 in the image
- [ ] tests/start.test.ts flakes under full-suite load, passes alone; give it a longer timeout or serialize it
- [ ] start.sh over the comment budget (16%, budget 10%)
- [ ] /context page lists only built-in tools, not MCP tools
- [ ] Workers get no MCP tools
- [ ] mcp.ts reaches the SDK's private _process to unref stdio children (shortcut; breaks on an SDK upgrade)
- [ ] MCP tools are always allowed: permissions.json names only the built-in tools
- [ ] Seed-made widget cards must be one self-contained card.html (the sandbox blocks loading files from the head)
- [ ] The six sample cards (Briefing, Focus...) are fixed markup in cards.html, not widget folders
- [ ] Voice and model menus still live in the head (/widgets/voices, /widgets/models), not widget folders
- [ ] nofollow.ts wraps the global sync fs: a library calling it with unhandled options on a home path fails loudly; globSync (Glob tool) still lists names through a linked folder
- [ ] Hook commands run as root shells in Seed's home and follow links
- [ ] Agents created after boot stay closed to seed until the next restart (start.sh sets modes at boot only)
- [ ] Seed's memory learnings [5] [8] [9] say he runs as root; Seed corrects them
- [ ] DPLAN-0454 leftovers: a corrected memory's old vector answers recall for up to 30 s; two waiters can both clear one stale lock; Node fetch's 300 s header timeout; the route test reads string literals only
- [ ] Root-command approvals held (Patrick 22:08): system changes are wiped on redeploy; revisit later
- [ ] Seed main not pushed to GitHub (Patrick: git later)
- [ ] SECURITY: Seed probed drone verbs with path args for the source (plan show ../../../../opt/seed/package.json, 2026-11-08 06:07). plan show refused, but every drone verb taking a path runs in the root head: audit them all for ../ traversal
- [ ] Agent tab: a failed turn's error line does not show there, so a refusal looked like "not delivered" (the message did reach Seed)
- [ ] agents.js (14%) and chat.css (12%) over the comment budget
- [ ] pid reuse after a restart: turn.lock fixed with stamp()/holds() (state.ts); the same bare-pid check remains in state.ts locked(), workers.ts running rows, daemon.ts's record, door.ts's head record
- [ ] A deploy kills a running turn mid-way with no note to the user; drain or say so
- [x] SECURITY: prompt.md sat in a seed-writable dir; moved to root-only SEED_HOME/prompts/ (seed 3e4154d)
- [ ] prompts/<name>.md is picked by the passport's branch_name, which Seed can edit: key it by the registry row instead
- [ ] Laptop: run the README step once (link ~/.config/seed/prompts/seed.md) or the local head can't load @seed
- [ ] Manager boundary: managers run as uid 1001 like Seed and can read/write his home; Patrick decides if they get fenced (Seed's audit, 2026-11-08)
- [ ] Connectors (2026-11-09, DPLAN-0460): a card joins the deck only after a page reload when a connector is switched on (a new page path, not a few lines)
- [ ] Connectors: holds are an in-memory map never pruned; a restart drops waiting cards
- [ ] Connectors: no search of the shelf by need, no pinned always-loaded connector, no saved "never suggest this"; none matter at three connectors
- [ ] Connectors: token numbers for on-demand loading are a chars/4 estimate; recount with claudeCounter on the deployed head
- [ ] Connectors: devpulse has not read the diffs of 0904 to 0908 line by line (rested on npm run check, grow's mutation proofs, live looks)
- [ ] Connectors: not yet run live: Load, the Wake timer and its lapse line, a mail-woken turn with short arms, TurnOn card from a settings box, gmail_label_delete; Patrick's Gmail cleanup test (unstar, unlabel, delete "Seed Test")
- [ ] Wake lever state is a line in Seed's cached context: each flip rewrites the cache once
- [ ] SEED_SHORT_ARMS (owner switch, on): settle after living with it; research says it is the Rule of Two, not overkill
- [ ] Unattended runs (Patrick 11-09): scheduled work in a container with no web, outside connectors unreachable, result waits for review; second instance allowed because isolated. Design only
- [ ] Web access: one agnostic, agent-safe solution for all agents; research when we get to it (Patrick 11-09). Does Seed's shell reach the open internet? Untested
- [ ] Google: publish the OAuth app (else Gmail consent expires weekly); move Seed's client out of the "AIPass Backup System" Cloud project
- [ ] Machine card redesign (bars, sparkline): proposed, no yes
- [ ] Matrix: a placed sphere can overlap another branch's nodes (grow, 0897)
- [ ] ~/.config/opencode/service.json holds a password a research sub-agent printed in its session on 11-09: rotate if it matters; briefs now exclude config files as a class
- [ ] ~/Externl-Repos/codex holds an unpacked tarball of openai/codex (no clone verb in drone); delete or keep

## Links

- **Related plans:** —
- **Commits:** —
- **Compass entries:** —
- **External:** —

## Status
- [x] Created
- [ ] Closed (same sitting — that's the design)

*Spoken summary: written only when the user asks for one, in plain sentences with no markup.*

---
*Created: 2026-11-07*
*Updated: 2026-11-07*
