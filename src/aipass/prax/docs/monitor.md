# monitor — Mission Control

The real-time terminal console: threads, multi-CLI session reading, the commons feed, the Telegram relay.

Moved out of `README.md` on 2026-09-15 (DPLAN-0347, the layer contract): the README is the
face, the depth lives here. Back to the [branch README](../README.md).

---

## Monitor — Mission Control

```bash
drone @prax monitor                      # Show monitor architecture
drone @prax monitor run                  # Launch Mission Control (all branches)
drone @prax monitor run seedgo,cli       # Monitor specific branches
drone @prax monitor run commons          # Live social feed of The Commons
drone @prax monitor run commons --logs   # Tail commons' technical logs instead
drone @prax monitor run --relay          # Mirror to Telegram (prax_monitor bot)
drone @prax monitor --help               # Monitor usage
```

**On request only — there is no monitor service.** Patrick's ruling, 2026-08-18:
*"monitor should only be running on request when i call it. not in background.
the logs are already running."* Mission Control is an operator console, and
logging does not depend on it: `system_logs/` and the branch-local logs are
written by the logging handlers whether or not a monitor is running. Start it
when you want to watch, quit it when you are done.

The `prax-monitor.service` systemd unit that used to run it always-on is
**retired and deleted from the repo**, which under Patrick's archive doctrine
(2026-08-18) is what retired means: *`.archive/` is always ignored, no
exceptions — and files there are not safe, they get cleaned without warning.*
So the retirement record lives here, in tracked prose, rather than in an archive
directory that neither ships nor survives. A convenience copy may sit in
`.archive/` on any given machine; nothing depends on it.

**Why it was retired.** Two rulings the same day landed on the one file. First,
the on-request ruling above. Second, Telegram was retired — and this unit's
entire stated purpose was `Description=AIPass Prax Monitor — Telegram relay`,
setting `AIPASS_PRAX_MONITOR_RELAY=1`; BAUD is the surface going forward. It was
also expensive: 3h23m of CPU consumed, 2.29GB RSS at the end, and it was one of
the six processes that lost their watchdog dispatcher at 02:19 that day and grew
unbounded (DPLAN-0305, fixed above).

**What the unit was**, for anyone reconstructing it: a `Type=simple` user unit
running `python3 -m aipass.prax.apps.modules.monitor run` with
`Restart=always`, `WorkingDirectory` at the repo root, `AIPASS_PRAX_MONITOR_RELAY=1`,
and both stdout and stderr appended to `~/.aipass/prax-monitor.service.log` —
deliberately *outside* `system_logs/`, because the monitor tails `system_logs/*.log`
and @trigger watches it too, so writing its own output there is a feedback loop.

**If an always-on monitor is ever wanted again**, two questions have to be
answered before reinstalling anything:

- **Log rotation.** `StandardOutput=append:` has no rotation. That log reached
  **117MB unrotated** before it was archived. A long-lived unit needs a rotation
  story first.
- **The ecosystem observer.** Any long-lived process that logs still lazy-starts
  a recursive observer over the ecosystem root (`start_file_watcher()` schedules
  one `WatchdogObserver` with `recursive=True`). Re-read 2026-09-05: the watch is
  unchanged and always-on processes still multiply it. What changed on 2026-09-04
  is *who waits for it* — the logger's first call now goes through
  `start_file_watcher_in_background()`, so the walk happens on a thread nobody
  joins (see "The watcher start does not block the first log line" below).
  DPLAN-0307, which tracked the design, was closed 2026-08-22 in a batch with
  three other prax plans — the plan is closed and the design is not.

Real-time unified console showing:
- File changes, log events, drone commands, agent activity
- **Branch scoping** — `monitor run seedgo,cli` shows only those branches (see below)
- **Caller attribution** — `CALLER → TARGET` for drone commands
- **Model tags** — `[BRANCH/model]` (e.g., `[DEVPULSE/opus]`, `[DEVPULSE/gpt-5.4]`)
- **Multi-CLI** — Claude Code (JSONL), Codex (JSONL) session monitoring
- **Rate tracking** — 4th background thread scans `system_logs/` for runaway log growth every 10s
- **Polling fallback** — automatic fallback when inotify watches are exhausted
- **Soft start** — only shows new activity after launch (seeks to EOF on startup)

Interactive commands inside the monitor: `help`, `status`, `quit`/`exit`/`q`.

**Who counts as a branch.** Names and paths come from declarations, never from
path shape. Three sources, in precedence order: `AIPASS_REGISTRY.json` for
`src/aipass/*` branches; then a sweep of `projects/*/*_REGISTRY.json` for in-repo
project citizens; then, for any file still unresolved, the nearest
`.trinity/passport.json` walking up to the repo root. A relative registry path
is resolved against *its own registry's* directory, not the process CWD. First registration wins, so a project cannot
claim a name AIPass already uses.

The project sweep resolves whoever the registries *declare*, not whoever has a
directory. Measured 2026-09-05: **22 known branches** — the 18 in
`AIPASS_REGISTRY.json` (AIPASS, AI_MAIL, API, BACKUP, CANARY, CLI, COMMONS,
DAEMON, DEVPULSE, DRONE, FLOW, HOOKS, MEMORY, PRAX, SEEDGO, SKILLS, SPAWN,
TRIGGER) plus the four project citizens that ship a registry today: BAUD,
EARMARK, AIPASS_SITE and FINCH.

Two names this page used to list are no longer resolvable, and the tree
explains both without naming anyone: `projects/` now holds exactly four
directories (`aipass-site`, `baud`, `earmark`, `finch`), so **MARKETSTAND** has
no registry to declare it and `projects/speakeasy(on_hold)/` — previously cited
here as an empty-`branches[]` citizen — is not in the tree at all. The count
moved because the declarations moved; the rule did not change. Earlier revisions
also listed a `TESTING` citizen — no such project registry exists.

That third shape was missing until 2026-08-14: `monitor run baud` answered "BAUD
is not a known branch", and — worse — BAUD's files were labelled **AIPASS**,
because the old fallback matched path segments against known names and the repo
directory is called `AIPass`. Misattribution is worse than UNKNOWN: events land
on the wrong screen and are filtered off the right one. Same family as the
watchdog fix (c247fce8) and the statusline passport walk-up.

**Branch scoping.** A comma-separated list (`monitor run seedgo,cli`) restricts the
display to those branches; bare `run` and `run all` show everything, unchanged. A
scope covers each named branch's log lines, file changes and CLI sessions —
including session labels that carry a project prefix or model tag
(`AIPASS/SEEDGO/opus`) — plus commands the branch issued or was targeted by
(`devpulse → prax` appears in both scopes). Filtering happens at the queue, so
out-of-scope traffic never occupies a display slot and cannot push wanted events
out under load. The banner and `status` name the active scope, `status` also
reports how many events the scope is holding back, and a name that is in no
branch registry is called out at launch rather than showing a silently empty
screen. The monitor's own health warnings (file watcher unavailable, and similar)
bypass the scope — a filter must never hide the reason the screen is empty.
The scope is set at launch; there is no runtime `filter` command outside commons
feed mode.

**Display resilience.** Everything on screen is other branches' output, so every
dynamic value is escaped before it reaches Rich — a tailed line containing
`[/usr/bin]` is shown, not parsed. If a line still cannot be drawn, the failure
costs that one line: the display thread reports it (rate-limited, in plain
language) and keeps consuming. It is the queue's only consumer, and a consumer
that dies leaves the queue permanently full with nobody to empty it. The
Telegram relay is fed before the console for the same reason — one sink failing
must not take the other with it.

**Commons feed mode** (`monitor run commons`) is a different watcher, not a branch
filter — it renders live social activity in The Commons (posts, comments, votes,
reactions) read-only, instead of file/log events. `--logs` opts back out to tailing
the commons branch's technical logs. Feed mode adds two interactive commands of its
own: `filter <room>` (comma-separated) and `filter clear`. `--relay` works in both
modes, and is also enabled by `AIPASS_PRAX_MONITOR_RELAY=1`.

