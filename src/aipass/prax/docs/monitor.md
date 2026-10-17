[<- Back to the README](../README.md)

# monitor — Mission Control

The real-time terminal console: threads, multi-CLI session reading, the commons feed, the Telegram relay.

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

**On request only — there is no monitor service.** Mission Control is an operator
console, and logging does not depend on it: `system_logs/` and the branch-local
logs are written by the logging handlers whether or not a monitor is running.
Start it when you want to watch, quit it when you are done.

No systemd unit ships for it. An always-on monitor would need a rotation story
for its own output first, and that output must stay *outside* `system_logs/`:
the monitor tails `system_logs/*.log` and @trigger watches it too, so writing
there is a feedback loop.

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
directory. Path
shape is never used: matching path segments against known names labels every
file under the `AIPass` directory as AIPASS, and misattribution is worse than
UNKNOWN — events land on the wrong screen and are filtered off the right one.

**Branch scoping.** A comma-separated list (`monitor run seedgo,cli`) restricts the
display to those branches; bare `run` and `run all` show everything. A
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

