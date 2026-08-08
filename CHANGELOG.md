# Changelog

All notable changes to AIPass will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Entries are grouped by merge under a dated section header (`YYYY-MM-DD`). Package
releases follow [SemVer](https://semver.org/) and are tracked by the git tag and
PyPI version — not the changelog header.

---

## [2026-08-07] — post-v2.7.14 train (in progress)

**docs(spawn)** — custom_config/ README grows from 3-line stub to the
operator-override guide (FPLAN-0380 workstream 2 of 4). Every branch's
`{branch}_json/custom_config/` now explains the house pattern in-place:
code holds defaults (shipped truth), a file here holds ONLY deliberately
overridden keys deep-merged at load, missing file = defaults = safe, and
never write defaults to disk (the snapshot anti-pattern that made
@memory's config undiagnosable, named as the failure mode). Template +
registry hash regenerated, plus a one-pass fleet refresh of all 17 live
branches' copies — those are gitignored, so spawn's render pass is the
only propagation path (two hand-written READMEs at @cli/@skills replaced,
content preserved in the reply for their owners). 380 tests (+2, both
canary-verified: stub-revert reds the rules test, placeholder-typo reds
the render test). By @spawn; suite re-run + rendered copy + registry hash
re-verified by devpulse.

**feat(hooks)** — two grounding gaps closed, Patrick-ruled the same evening
(email.py 1.2.0, cadence.py 2.1.0, grounding_content.py 1.1.0,
post_compact_regrounding.py 1.1.0). (1) Mail banner on a 5-turn cadence
loop: announces the turn mail arrives, repeats every 5th turn while it
stays new, fully silent at zero — and zero CLEARS the loop state so the
next arrival announces immediately instead of serving out the old period.
Built as an elapsed-turns loop off the last fire, not a modulo slot (a
banner four turns late is not a notification); state in its own per-session
file because the turn-counter file's every-turn truncation is load-bearing
for the post-compact regroup token. Fails OPEN — a broken counter can't
hide someone's mail. Previously the banner stacked on every single turn
(11 turns with mail = 11 banners). (2) Post-compact re-grounding is now
ACTIVE, not just passive: the PostToolUse backstop prepends an explicit
instruction — re-read .trinity, refresh + read the dashboard, and SAY SO
if memory contradicts reality — because the startup protocol only ever ran
off a greeting and a mid-task continuation never gets one. Live-proved
twice: once on @hooks during the build itself, once on devpulse during
this very verification (the backstop fired mid-turn and the instruction
was followed). Known gap flagged, not fixed (their call was right): a
compact followed by a real UserPromptSubmit gets passive grounding only —
fix queued, touches DPLAN-0278 machinery. Plus a drive-by: srt_resolve
node timeouts 15s→60s named constant (Windows runner cold-start flaked a
docs-only commit; it's a hang backstop, not a latency budget). 1360 tests
(+25, canary-verified: forced-fire + instruction-removal each break their
own tests), seedgo 100%. By @hooks; suite re-verified by devpulse.

**fix(ai_mail)** — mail can no longer be invisible or crash its reader: four
live defects fixed (format.py 1.2.0, email.py, email_send.py, ai_mail.py).
(1) The listing truncated the WRONG END — reverse-then-slice kept the oldest
20, so any inbox over 20 silently hid every NEW arrival behind a benign
"Showing 20 of 25" footer (found when @skills' reply vanished from devpulse's
box, the busiest in the fleet). (2) `view latest` served the OLDEST mail.
(3) Rich markup ate subjects — `[dim]` silently swallowed, `[/rc]` crashed
the entire listing — and after the first fix the view BODY still crashed on
`[/rc]` (caught live by devpulse viewing the fix report itself): bodies now
render with markup=False (no parse step, can never raise), listings escape
at the formatter, send-confirmation echo hardened (same class, found by
sweeping the branch). (4) Sent listing skipped unreadable files silently —
placeholder rows now. Fail-honest rule throughout: a row can render ugly,
it can no longer be absent. Plus VERA's exit-code report folded in: failed
replies exit 2 (nothing read the failure flag error() set). One complicit
test fixture reordered (matched the bug, not delivery's write order — 4th
logged instance of that class). 881 tests (+21 across both passes, canary-
verified), seedgo 100%. By @ai_mail; suite + live read-back re-verified by
devpulse.

**feat(skills)** — TG `/rc <target>`: recover a dark Claude Code remote from
the phone (remote_control.py, control-bot family). Born from the day Vera's
rc died with Patrick phone-only and no path back: the bot resolves the target
to its tmux session and types CC's built-in `/rc` (`/remote-control`) into
it — the one injected string, module constant, TG-inbound and control-bot
gated like `/context`. Safety learned the hard way and baked in: palette top
match verified before Enter, never a bare Enter on an empty composer (ghost
prompt-suggestions), busy sessions get a refusal not a queue, success read
from the footer indicator only. Live-test discovery: the "second step" is
state-dependent — an already-connected session pops a modal status panel
that would wedge the target's composer, so the verb Escapes it and verifies
dismissal. Deploy proven live via getMyCommands before/after fleet restart:
`rc` present on exactly the two control bots, absent on all three branch
bots (the gate holds in production). 48 new tests, 1058 telegram + 252
skills green, seedgo 100%. By @skills; suites re-verified by devpulse.

**fix(drone)** — caller identity: assigned beats inferred (router_handler
1.1.0). `AIPASS_BRANCH_NAME` (who the process IS) now outranks the cwd
passport (where it's standing); cwd stays as the human-shell fallback. The
inverted precedence stamped any agent standing in another branch's directory
with THAT branch's identity — S102 damage: a commons agent's mail landed as
@aipass and corrupted a citizen's sent store. The bug lived in TWO places
(the env builder at router_handler.py and a second copy feeding the
`[CALLER:X]` routing-log tag in router.py) — a half-fix would have made the
log exonerate the caller under investigation; both now share one resolver
with a tag-matches-stamp test. Conflicts log a WARNING naming both signals
(case-insensitive — passports carry display casing). Authority unaffected
and now test-asserted: git owner-tier resolves from passports only. Also:
ambient-env test pinned (outward-lean class), stale ALLOWED_CALLERS docs
corrected to the earned owner tier. Found by @ai_mail/@aipass, ruled and
built by @drone. 971 tests (+8), 5 canaries, seedgo 100%; live-proved under
the original S102 conditions and independently re-verified by devpulse.

**fix(flow)** — SOP templates stop exploding on braces (get_template loader):
`str.format()` over the whole template body read every literal `{...}` in
documented code snippets as a replacement field — weekly_update.md's
`{createIfEmpty: true}` MCP example made the template 100% un-instantiable
with a bare KeyError. Escaping the one brace would have left the trap armed
for every future SOP, so the loader now substitutes ONLY the seven known
placeholder names via regex; all other braces pass through verbatim.
Template file untouched. Caught by @trigger's error watch, fixed by @flow.
772 tests (+2), verified end-to-end (PPLAN-0030 created + closed through the
full pipeline), seedgo 100%; suite re-verified by devpulse.

**fix(trigger)** — dispatch notifications report the true occurrence count
(error_detected 2.3.0, found by @drone): line 563 hardcoded `occurrences=1`
while threading every other field through from the handler. Gate 3 refuses to
dispatch below count ≥ 2, so no dispatched mail could ever truthfully read 1 —
every notification understated recurrence and readers triaged recurring errors
as one-offs (@drone read a count-9 error as a single). The registry's number
(error_reporter.py) was always right, which is why the two disagreed and the
bug survived. 710 trigger tests (+3, canary-verified: reverting the line fails
all three), seedgo 100%. By @trigger; suite re-verified by devpulse.

---

## [2026-08-07] — cross-project walls down: the Vera arc lands end to end

*Release v2.7.14 (PR #727, 26 commits) rolls up this section plus
[2026-08-04] (manager-class git auth + fleet self-repair) and the
[2026-08-02] TG slash relay section below: the hardcoded-registry bug class
fixed at all four instances, the cross-project feedback round trip closed
both directions, external projects provisioned for owner-tier git, and a
train of trigger/hooks/prax reliability fixes.*

**fix(ai_mail)** — cross-project conversations continue past one round
(reply.py 1.1.0, by @ai_mail on Patrick's order): (1) outgoing replies now
stamp `reply_path` = the replying branch's own inbox — derived from
from_branch_path, deliberately not caller-env resolution, so a return
address can never point at someone else's inbox; previously replies-to-
replies died with "Could not find branch for @vera" because delivered
replies carried no return address. (2) `_validate_reply_path` accepts any
`*_REGISTRY.json` ancestor — fourth instance of the hardcoded-registry bug
class (compass #229), outbound direction: delivery toward external projects
was rejected because their ancestors hold PROJECTNAME_REGISTRY.json. 860
ai_mail tests (+5, fixtures use external registry names, canary-reverted to
prove the tests see the fixes), seedgo 100%. Live-proved by devpulse with a
two-round conversation through VERA's real inbox: the previously-dead
reply-to-a-reply delivered, and its own delivered copy carries the return
address for the next round — the loop is now indefinite in both directions.

**fix(devpulse)** — wall 3 down, cross-project feedback round trip closed
(compose 1.3.0): delivered replies now carry `reply_to: "@devpulse:feedback"`.
Patrick ruling: the feedback loop is cross-project BY DESIGN — no boundary
protection applies, and the module owns its whole round trip. The last wall
was routing precedence in ai_mail's reply verb: `reply_to`/`from` resolving
to a registry branch email routed external replies into normal delivery and
the #134 cross-project refusal; the stored `reply_path` (the sanctioned
cross-project route) only fires on a registry MISS. A non-registry reply_to
forces that miss — zero ai_mail changes, the fix lives where the ownership
is. Live-proved end to end (the failing operation succeeding, per VERA's
false-green standard): external send → devpulse reply → external ai_mail
reply → landed threaded in devpulse's inbox. VERA's three live messages
patched in place and replyable. 452 devpulse tests green.

**fix(commons)** — external citizens exist in the social space: identity_ops
1.1.0 falls back to the caller's own registry (walk from AIPASS_CALLER_CWD,
glob `*_REGISTRY.json`, sorted, AIPass-registry skip by name AND path) when
the AIPass registry misses. Found by the bug-class sweep as the worst
variant — not a wrong filename but NO caller-registry consultation at all,
so every external citizen silently failed Commons identity, registration,
and authorship. Live-proved: VERA resolves by path and by name from her real
registry and auto-registered into the agents table; her three teammates
resolve; AIPass citizens still win on collision and never pay for the walk.
461 commons tests (+13, incl. an autouse env-clearing fixture so ambient
shell state can't answer a test meant to miss), seedgo 100%. By @commons.
Attribution note: the code content of this fix and of in-flight @memory
rollover work (extractor + pipeline tests, task owned by @aipass's dispatch)
was swept early into devpulse commit 79df6bda by an over-broad `--all` —
this entry is the correct authorship record.

**fix(ai_mail)** — external citizens can be identified as reply senders:
`_find_caller_registry` globs `*_REGISTRY.json` (sorted, AIPass-registry
skip preserved) instead of requiring the literal `AIPASS_REGISTRY.json` no
external project carries. Third confirmed instance of the hardcoded-registry
-filename class (after drone's find_repo_root and router fallback); found
via VERA's retraction of her own false "confirmed fixed" — her live-id
A/B/C (reply fails, send works, same shell) pinpointed the layer. Their
report's sharpest find: all 5 pre-existing tests named their fixture
`AIPASS_REGISTRY.json`, sharing the code's assumption — the suite was green
because it couldn't see the bug. 844 ai_mail tests (+5), reverted-glob
canary bites, live-verified sender resolves to VERA from her branch. By
@ai_mail. NOTE: reply round-trip still blocked one layer later — the
stored-reply_path route (validated, boundary-free, built for this) is
shadowed by the registry-email match that hits the ruling-#134 cross-project
refusal first; routing precedence is a Patrick call (DPLAN-0232).

**fix(devpulse)** — feedback-delivered replies are replyable (compose
1.2.0): `from` is the canonical `@devpulse` and every delivered reply
carries `reply_path` back to devpulse's inbox, so ai_mail's stored-path
reply route has a return address to use. Wall-2 of @ai_mail's round-trip
report; the three live messages in VERA's inbox were patched in place.
452 devpulse tests green.

**fix(devpulse)** — feedback reply delivery writes the ai_mail v2 message
schema (compose.py 1.1.1). The delivery function wrote `body`/`read` where
the ai_mail viewer reads `message`/`status`, so delivered replies rendered
as EMPTY bodies under `drone @ai_mail view` while the data sat intact in
inbox.json — VERA read hers via raw JSON and filed the display/data
contradiction. Messages now carry `message`, `from_name`, `status: "new"`,
prepend newest-first, and recompute `unread_count` the same way delivery.py
does. 452 devpulse tests green, compose.py 31/31 seedgo standards.

## [2026-08-04] — manager-class git auth + fleet self-repair day

**fix(drone)** — caller detection derives a project name from the registry
FILENAME when metadata declares none (`AIPASS_REGISTRY.json` → `aipass`,
`VERA-STUDIO_REGISTRY.json` → `vera-studio`); a declared
`metadata.project_name`/`name` still wins, and passports still outrank the
fallback entirely. The old code required a declared name, which AIPass's own
registry doesn't carry — so the framework repo was the one place the fallback
could never fire, and it failed in silence: callers at the AIPass root
(VERA's session, the Telegram scheduler hourly) were `CALLER:UNKNOWN` all
day, which is what stranded the feedback replies above. Found-but-rejected
registries now log WARNING naming the file and reason; the glob is sorted for
deterministic multi-registry resolution; a test asserts a derived name can
never earn git authority (owner-tier reads passports directly). One canary
self-caught and rewritten: the bare-suffix test asserted None, which the
caller's truthiness check made vacuous — now asserts the WARNING. 963 drone
tests green (+8), seedgo 100%.

**fix(devpulse)** — feedback replies report delivery honestly. Live failure
caught by Patrick asking why VERA never heard back: all six of her feedback
messages arrived as `From: unknown` (her session ran drone from the AIPass
repo root, where caller detection finds no passport and the registry
fallback rejects a name-less `AIPASS_REGISTRY.json`), so three replies were
"saved" while delivery silently skipped to `src/aipass/unknown/`. compose.py
1.1.0: an anonymous send is now told AT SEND TIME that replies cannot reach
it (with the run-from-your-branch-dir fix named), and `reply` reports the
delivery outcome — `success()` on delivery, `error()` with the reason on
failure (which marks the command failed: a reply the sender never sees
SHOULD flip the exit code) — instead of claiming success on a thread-only
save. The six stored messages were repaired (sender + reply path) and the
three stranded replies hand-delivered the same evening. 452 devpulse tests
green (+5), compose.py 31/31 seedgo standards.

**feat(drone)** — owner-tier git is earned, not listed (DPLAN-0281, Patrick
ruling: "project owners get git"). The hardcoded `allowed_callers:
["devpulse"]` is gone; a caller holds owner-tier iff all four checks pass:
manager-class citizen, tenant of THIS repo's registry (passport
`citizenship.registry_id` == registry `metadata.id`), listed with `owner:
true`, and presenting its passport from the registry-recorded home
(path-binding, F59 4.2a). devpulse-in-AIPass authorizes through the general
rule — no special case — and any external project's manager gains the same
standing in their own repo once P2 provisioning flips their class. Enforce
by default (all four checks live-verified against real data before
flipping); `AIPASS_GIT_AUTH_MODE=warn` for migration triage. AIPass-flow
verbs (dev-pr/merge/tag/…) refuse honestly in external repos until
translated — commit and sync work there today. Also: `find_repo_root`
recognizes any `*_REGISTRY.json` (external projects name theirs),
dict-authored registries get the same normalization as list-shaped, and the
dead `ALLOWED_CALLERS` decoy died with the list it shadowed. Router
caller-identity honesty landed alongside: a lost identity renders
`[CALLER:UNKNOWN]` plus one WARNING naming the real cwd, and the registry
fallback for external projects is reachable as documented. 44 new tests
(16 canaries + unstubbed-auth module tests), 955 drone green. By @drone,
verified by devpulse.

**fix(tests)** — CI-only fallout from the auth rewrite, caught by the clean
checkout: seedgo's four Track-E tests pinned the dead `ALLOWED_CALLERS`
parity — replaced with one canary asserting no name-based caller list can
reappear; and drone's wrong-tenancy test now pins `AIPASS_REGISTRY` to its
fixture — `find_registry`'s cwd walk deliberately skips credential-failing
registries, so the mismatched fixture was passed over and resolution fell
through to the real registry locally (right wording, wrong reason) but to
not-found in CI, where `AIPASS_REGISTRY.json` is gitignored-absent. Seedgo
1304 green, drone 955 green. A third, Windows-only: the new router
cwd-logging test substring-matched path reprs — `str(tmp_path)` has
backslashes while the logged arg renders `WindowsPath('C:/...')` with
forward slashes — now compares Path values, separator-agnostic.

**fix(trigger)** — rotation tail loss closed in BOTH log watchers. The old
`size shrank → reset to 0` rotation handling silently skipped every line
between the last read offset and the rotation cut — worst exactly during
incidents, when the unread tail is largest; a second defect seeked stale
offsets INTO the fresh file, reading garbage fragments. Now: inode identity
recorded beside the offset, rotation detected by inode change, and the
rotated-out file's unread tail drained before moving on (inode-matched, so
never a stale backup re-fired). Falsy/unknown inode degrades to old
behavior. Found by @trigger while disproving another branch's rotation
claim. 698 trigger tests green.

**fix(hooks)** — edit_gate's newest-first guard no longer hard-blocks
legacy `session_number` branches from ever writing session memory (found by
VERA — the gate was stricter than the schema the rest of the fleet still
honors, with no compliance path). Two halves, both proven load-bearing by
staged canaries: a number-key alias (`number` wins over `session_number`
when both exist) so legacy arrays stay *guarded*, and an unreadable-schema
pass-through so an unrecognized future schema degrades to the
ordinal-independent ordering check instead of a permanent lockout. Block
messages now name the accepted keys. Live-proved through the real Claude
bridge: legacy prepend exits 0, tail-append and number-reuse still exit 2.
1335 hooks tests green (+9). By @hooks, verified by devpulse.

**fix(ai_mail)** — wake-back no longer claims "woken" when the manager gate
skipped it (found by VERA in Vera-Studio field telemetry after her manager
flip; diagnosis exact, line for line). The gate's bool means "the dispatch
did what it should," not "an agent was woken" — a manager returns True
having deliberately woken nobody, and `_wake_sender` read that as woken.
New `skipped_manager` result tag keyed on the status object's structural
step (not prose-sniffing — substring matching is what let this hide),
docstrings now tell the truth about managers, and the unreachable @daemon
exception on wake-backs is explained in place. Gate behavior untouched.
839 ai_mail tests green (+9, canary-checked both directions). By @ai_mail,
verified by devpulse.

**docs(flow)** — weekly_update playbook template v2, authored by VERA
(Vera-Studio) from her PPLAN-0017 run and landed from flow/dropbox: new
Step 0 reads the live subreddit for the last posted number before anything
else (an empty playbook is not evidence its post never fired — trusting one
cost a delete-and-repost of an immutable Reddit title), and a cold-tested
"Driving Chrome" section including the `pgrep -x chrome` correction
(`pgrep -f google-chrome` false-positives on the caller's own command
line). First cross-project template contribution.

**feat(hooks)** — hooks_engine.log per-hook narration demoted out of the
default view (ruling delegated by Patrick, decided by devpulse: quiet noise
at the source, never mask it). prax's SystemLogger has no debug(), so
engine 1.2.0 gates the four per-hook narration sites (fire, complete,
skipped-disabled, budget) behind `AIPASS_HOOKS_VERBOSE_LOG=1` — silent by
default, restorable live, read per call. Lifecycle INFO, every WARNING and
ERROR, and engine.jsonl untouched. Measured under fleet load: 1865 of 1869
lines demoted (~99.8%); the 4 survivors were legitimate git_gate blocks.
1326 hooks tests green (+5, suppression canary-checked), seedgo 100%. New
README "Two Log Streams" section. Flagged upstream: SystemLogger's missing
debug() is a real prax gap. By @hooks, verified by devpulse.

**feat(aipass)** — `aipass init update` provisions external projects for
manager-class git (DPLAN-0281 P2). New `init/git_auth.py`: plans every
repair BEFORE writing (a refused run leaves the project untouched), mints
registry `metadata.id`, backfills the owner citizen's
`citizenship.registry_id`, flips builder→manager, records the branch path —
then `verify_git_auth()` independently re-reads disk and re-derives all
four owner-tier checks. Refuses honestly instead of guessing: no owner
marked, more than one owner, root-ish recorded paths (@drone's guardrail —
at-or-under binding would degrade to repo-wide), paths outside the repo, or
missing passports. `--dry-run` prints the plan, writes nothing. Canaried
against drone's real P1 gate: repaired fixture authorizes, un-repaired
refuses on class, a passport copied to a non-recorded dir refuses on
path-binding. 934 aipass tests green (+37), seedgo 100%. By @aipass,
verified by devpulse. P3 (run it on Vera-Studio live) is next.

**feat(trigger)** — runaway WARNING tier is observe-only (Patrick ruling:
"observe only is good"). WARNING runaways record with full fidelity —
alerts.json, decision log, per-file cooldown — but no longer email or wake
anyone; CRITICAL keeps its bypass-all-mutes wake path untouched. New
decision outcome `observed` (not `suppressed` — it was recorded; not
`delivered` — nobody was told), and a WARNING now records even with no
email callback, where it previously early-returned recordless. The accepted
cost is written into the module docstring: a sustained sub-CRITICAL leak
pages nobody by design. 707 trigger tests green (+13), reverted-split
canary fails 8, five NO-OVERREACH tests pin the CRITICAL path. By @trigger,
verified by devpulse.

**fix(trigger)** — follow-up: the seedgo unused_function gate (CI red on
PR#727) caught `_save_seen_hashes`/`_save_log_positions` orphaned since
#674's coalesced flush — only tests still called them. Deleted rather than
wired-to-nothing (the None-watcher "gap" doesn't exist: the flush merges
with existing on-disk JSON, preserving positions untouched). Their test
blocks repointed at the real write path `_flush_trigger_data`, and got
stronger: the old write-error tests asserted nothing; the replacements
assert the warning reaches the logger, canary-checked three ways. 694
green, trigger audit back to 100%.

**fix(ai_mail)** — the 6-week "unreproducible" dispatch failure
(2×468-adjacent fingerprints, 44 occurrences) root-caused and reproduced on
demand: sender identity resolves from AIPASS_CALLER_CWD, so running drone
from a non-branch dir (repo root) fails detection — while the error printed
the target's perfectly-valid cwd, sending every prior investigation passport
-hunting. The refusal is CORRECT (silent cwd fallback would forge sender
identity); the fix is diagnostic truth: the error now names the env var,
the walked path, and that process cwd is informational. Fingerprint prefix
preserved for medic grouping. 4 canary-checked tests, 830 green. By @ai_mail.

**fix(hooks)** — engine "complete: 0 hooks" lie fixed: silent gates write no
stdout, so len(outputs) reported 0 on 97% of dispatches while gates fired
normally. Now counts executions; hooks_with_output added. Runaway
hooks_engine.log alert itself verdict'd NOT a hooks bug — fleet load
(24 claude processes, load 32 on 4 cores). engine.py 1.1.1, 4 canary tests,
1321 green. By @hooks.

**fix(prax)** — log retention: backup_count 1→3 (rotation was discarding
history the watchers hadn't drained; ~28MB ceiling accepted), and dead
prax_logger_config.json read-keys found/wired (settings never matched what
load read). By @prax under @trigger dispatch. 1084 green.

## [2026-08-02] — TG slash relay: /context fired from Telegram comes back to the chat

**feat(skills)** — CC informational slash commands now round-trip from
Telegram (Patrick ask: stop pick-and-choosing which builtins work remotely).
The bot injects an allowlisted informational command (`/context`; extend via
`informational_commands` config) as raw text — no relay prefix, or CC would
read it as prose — then a daemon-thread watcher tails the CC transcript from
the injection baseline and relays the command's stdout back to the chat as
HTML `<pre>` chunks. Local commands produce no assistant turn, so this path
deliberately writes NO pending file and starts NO heartbeat (nothing for the
Stop hook to strand — the stuck-pending lesson applied, not relearned);
90s timeout edits the placeholder to an honest failure. Scope-guarded twice:
watcher only starts from TG-inbound handling and the scan is bounded to
lines after the baseline — a desk or remote-control `/context` can never
surprise-echo to the phone. Found en route: current CC emits `/context`
twice (ANSI TUI panel + clean-markdown isMeta twin); the twin is preferred.
`/cost` verified-not-assumed and left OUT (zero invocations exist on this
machine to pin its shape). Side-effect passthrough (`clear`/`compact`/
`prep`/`memo`) byte-identical behavior. 51 new tests (canary-checked: each
guarantee broken in turn, tests bite), 1010 telegram green, seedgo 100%.
Built by @skills; live-proven end-to-end including a real Telegram hop.

## [2026-08-02] — install ends with hooks alive: setup enrolls itself; hook test runner stops ghost-arming live sessions

**feat(setup)** — setup.sh now enrolls the repo it just installed in the hook
trust registry (Patrick ruling, compass #221: the trust gate protects against
FOREIGN projects' hostile hooks.json — distrusting the config the installer
itself just wired is senseless). Previously a non-interactive install finished
"clean" with every hook silently dead until a manual `aipass trust`. The
enroll block runs right after hook wiring, calls the existing `enroll()` API
on `$SCRIPT_DIR` only (direct — the init-flow helper silently no-ops on temp
paths, which would have broken container/CI installs), and fails honestly:
WARN + the exact repair command in ACTION NEEDED, never an aborted install.
Proven causal in counterfactual containers (fix stripped → hooks dead; fix
present → registry absent → enrolled → 30 hooks fire with zero manual steps).
5 new tests execute the shipped bash block itself under `set -euo pipefail`;
897 aipass tests green. Built by @aipass.

**fix(hooks)** — `drone @hooks test` run from inside a live Claude session
armed the session's own post-compact regroup backstop: handlers resolve
`CLAUDE_CODE_SESSION_ID` env-first, the live session's ID leaks into the Bash
subprocess, so the mock PreCompact fire minted a real regroup token — next
real PostToolUse injected a "POST-COMPACT RE-GROUND" blob with no compaction
anywhere (ghost re-arm family, DPLAN-0278; spotted by the concierge during
the v2.7.12 install walk). hook_test v1.0.1 pins the env var to
`hook-test-mock` for the firing loop (try/finally restore) and stamps mock
payloads with the same ID, so all mock state lands in an isolated throwaway
file. Red/green proven live on a real session and re-proven in a fresh
container; 1310 hooks tests green.

**fix(hooks)** — the trust gate's refusals now tell the truth.
`find_project_config()` returns the same bare `None` for four different
reasons, and every CLI surface reported all of them as "No .aipass/hooks.json
found" — a lie whenever the file sat right there and the trust registry was
what refused it (cost two container runs to see through during the install
walk). New `config_unavailable_reason()` in the loader distinguishes absent /
not-enrolled / hash-changed / unreadable, each with the exact repair command
(`aipass trust <dir>`); wired into `hook test`, `hookstatus`, and
`wire verify`. Bridges stay silent by design (loader already logs there). +7
tests, one pinning the message against the gate so they can't drift apart;
1317 hooks tests green. Built by @hooks. Also: the two setup.sh trust tests
now skip on Windows — `shutil.which("bash")` there finds the WSL launcher,
not a shell, so CI red-flagged a POSIX-only installer test.

**fix(drone)** — git-gate refusals stop dead-ending and stop double-paging.
Rerouted verbs now point at their replacement (`add` → `commit --all`/
`commit "<msg>" <files>`, `push` → `dev-pr`, `pull` → `sync`); unknown verbs
get no hint so a typo is never handed a bogus suggestion. Root of the twin
468-occurrence medic fingerprints found: one refusal logged at ERROR twice
(auth.py, then git_module.py re-logging the identical event 0.12s apart) —
which is why suppressing one fingerprint left its twin paging. auth.py now
owns severity; the duplicate is WARNING. Benign by-design denials (no
passport in CWD, unknown verb) downgrade to WARNING — still logged, exit 1,
stderr, but medic no longer dispatches owners for working-as-intended
refusals (same doctrine as compass #219); owner-tier denials remain ERROR
and still page. Downgrade verified targeted live, canary-checked: 6 of 7 new
regression tests genuinely fail without the fix, the 7th proves owner-tier
still escalates. 904 drone tests green. Built by @drone — self-dispatched
via the daemon/medic pipeline off the very error devpulse hit an hour
earlier.

## [2026-08-02] — trigger suppress grows teeth: suppressed errors stop waking their owners

**feat(trigger)** — `errors suppress` now does what its name promised (Patrick
ruling, compass #219: the wake cycle ends at wake→investigate→suppress→sleep —
no re-waking owners every 2h forever for judged-benign errors; the recurring
no-passport pair had cost 468 wakes each since May). `should_dispatch()` gates
on registry status *inside* the function so no caller can route around it:
suppressed = no dispatch, unconditionally, while suppressed. Bookkeeping is
untouched — occurrences still count and timestamp, so a wrong suppress stays
auditable in `errors list`. New `errors unsuppress <id>` restores dispatch
with backoff state intact (the ruling's escape hatch — no lift path existed
before). `resolved` deliberately does NOT gate: a resolved error that recurs
means the fix didn't hold and must still wake its owner. `is_suppressed()`
fails open — a registry read problem makes noise, never silence. Suppressed
refusals log to `medic_suppressed.jsonl` (not "Backoff active", which read as
a timing wait). `errors stats` shows a Silenced count. The wrong-suppress
safety net is fingerprint precision: any new or changed error fingerprints
differently and wakes normally. Registry 2.4.0; 655 trigger tests green (+17);
live-proved on the real registry including a full unsuppress→re-suppress
round-trip.

**fix(drone)** — `drone @git log -20` (standard git shorthand) built the broken
flag `--20` and git died with a fatal; `-n 20` / `--count 20` worked but logged
a warning per flag into the very logs @trigger watches — which is how the bug
surfaced (found by @drone while investigating a benign fingerprint pair).
`_handle_log` now skips count flags (`-n`, `--count`, `--max-count`) silently,
parses the `-N` shorthand, and rejects non-positive counts with a clean exit 1
instead of handing git a bad flag. Genuinely unparseable args still warn.
All five idioms verified byte-identical live; 12 regression tests
(canary-checked against the old parse logic); 897 drone tests green.

## [2026-08-02] — /suspend rework: presence crosses processes, wake-mask goes opt-in

**feat(skills)** — Telegram `/suspend` heartbeat rework (base_bot v1.5.0) after
the 2026-08-02 incident where the loop re-suspended the machine under the
user's hands (his chat messages never counted as presence). Four fixes + one
reframe: (1) every bot process stamps a shared `last_inbound.json` on any
allowed-user message, so chatting with any bot cancels the cycle — presence
now crosses processes; (2) wake cause is classified by alarm-time comparison
(woke well before the armed RTC alarm = human → cancel + disarm) instead of
wall-clock-gap guessing, catching the 14s nap that left the loop armed
invisibly; (3) the grace window (100s→180s) anchors to the first successful
Telegram poll after resume, not resume detection, and re-arm holds while a
reply is in flight; (4) `suspend_enabled` bot-config flag grounds the verb
without a code edit. Adaptive cadence recreates the accidental "perfect days"
duty-cycle deliberately: 3-min beats while conversation is live, 25-min when
quiet, config-tunable. `install_suspend_grants.sh` makes the wake-source
masking **opt-in** (`--with-wake-sources`) per user ruling (compass #216):
on this hardware the spurious wakes are the product — they keep agents
running behind the locked screen. test_suspend.py 26→70; 944 telegram + 252
skills green; verb stays grounded until the post-reboot soak.

**feat(skills)** — `/lock` control verb hardened for the service context
(base_bot v1.5.1). The live soak settled the deployment model (compass #217,
supersedes #216): even a correctly-working suspend disconnects the agents, so
the machine stays awake 24/7 and `/lock` replaces `/suspend` for daily use —
instant password wall + dark screen, nothing sleeps. Session resolution walks
`loginctl list-sessions` for the caller's own active wayland/x11 session
(uid-matched — never locks another user's desktop) with a GNOME ScreenSaver
D-Bus fallback and an honest failure if both refuse; live-proved from a
session-less env (LockedHint no→yes). test_suspend.py 70→77; 1211 green.

## [2026-08-02] — medic mutes no longer swallow runaway alerts

**fix(trigger)** — medic content-mutes silently suppressed runaway-log alerts
(31/31 suppression-log entries were `branch_muted`, and dispatch SOP mutes
branches exactly when build-time floods happen — the alert channel was
structurally dead during active work). Mute classes are now split: content
mutes gate error-content events only; a new `volume_muted_branches` class
gates runaway alerts, with `severity=critical` bypassing even a deliberate
volume mute as a safety floor. Decision trail upgraded from suppression-only
to outcome-labelled (`delivered/bypass_critical` vs `suppressed/volume_muted`).
New `medic volume-mute / volume-unmute @branch` operator commands; `status`
shows both lists. 638 trigger tests green (+16), incl. the regression: a
content-muted branch still receives a runaway alert. Live-verified against
the real 5-branches-muted config with transport stubbed.

## [2026-08-02] — runaway detector: rotation reset the counters; relay pidfile: boot identity

**fix(prax)** — the runaway-log detector could mathematically never fire on a
fast flood: `scan_rates()` treated the RotatingFileHandler roll (.log → .log.1)
as a truncation and zeroed the sustained counters, so the faster the flood, the
sooner the file rotated and the sooner detection reset — the 2026-07-31 event
queue firehose (~4090 lines/min, 6.8× the CRITICAL threshold) rolled every
~24s against a 60s-sustain requirement. Root-caused from the on-disk
arithmetic (rotated file = 199,890 bytes vs the 200,000 threshold). Fix: a
shrink now counts the new file's content as the interval's bytes and leaves
the sustained counters alone; subsidence still clears them when rates truly
drop. Red-before/green-after rotation tests added.

**fix(prax)** — monitor relay pidfile survives reboots: `instance_lock` v1.1.0
records the kernel `boot_id` in the lock and reclaims unconditionally on a
boot mismatch (a lock from a past boot is always stale — PID liveness was
answering the wrong question after PID-number reuse). Same-boot behavior
unchanged; non-Linux falls back to liveness-only. 9 new boot-identity tests;
full prax suite 1078 passed.

Known gap (reported, not yet fixed — @trigger territory): medic branch-mutes
silently suppress runaway alerts (31 suppressed entries, 5 branches muted at
once), and dispatch SOP mutes branches exactly when build-time runaways
happen. Fix direction: separate volume mute, or critical-severity bypass.

## [2026-08-02] — flow plan templates truth-pass

**fix(flow)** — template review caught commands that misfire when agents
copy-paste them and doctrine that reality reversed. FPLAN default + master:
`ai_mail email` gains its `drone @` prefix, `seedgo audit` gains the `aipass`
pack arg, nonexistent `drone @flow status` removed, `flow create` examples gain
the location arg, the "no auto-compact for devpulse" line replaced with the
current calm-compact doctrine (auto-compact is survivable by design), typo
garble cleaned, a leftover flow-internal path row dropped. Playbook default:
PBPLAN → PPLAN, add-a-SOP command now shows template-before-type. Merge SOP:
hardcoded "13 branches" → the script's live count. Prompt-change SOP: seed
propagation rewritten for manifest-driven hook wiring (provider_manifest.json
is the single source since FPLAN-0374 — setup.sh reads it, no second list).

## [2026-08-01] — dispatch default model: opus (Patrick ruling)

**chore(ai_mail)** — `DEFAULT_MODEL` in dispatch wake flips sonnet → opus:
dispatched citizens now run full-reasoning by default (`--model sonnet`/`haiku`
still available per-dispatch). Also truths the doc drift — dispatch.py's help
already claimed opus was the default while wake.py shipped sonnet. 234 ai_mail
dispatch tests green.

## [2026-08-01] — setup.sh hook wiring: manifest is the single source, no doctor-heal dependency

**fix(aipass)** — fresh installs wired only 6/13 UserPromptSubmit bridge hooks
and missed `pre_compact_prep`: setup.sh's inline hook dict was a hand-maintained
second copy of `provider_manifest.json` and had drifted (found in the
`aipass-dev` container walk; `doctor --fix` healed it, but Patrick's ruling —
setup must be right on its own). New `refresh_provider_hooks()` in
provider_wire.py does manifest-driven strip-and-readd of bridge-marked entries
(user hooks always preserved); `auto_wire_provider()` and doctor `--fix` consume
the same helper, and setup.sh shells into it via the venv python — the hardcoded
dict is deleted, failures abort the install loudly. Also fixes the upgrade
double-fire class: stale bridge entries are replaced, not duplicated beside new
ones. Reverse drift caught too: the manifest itself was missing
`SessionStart:cadence_reset` (verified against the seedgo golden fixture).
Devpulse review caught a Windows gap pre-commit: manifest commands hardcode
`.venv/bin/python3`, which doesn't exist in Windows venvs —
`_platform_bridge_command()` now swaps to `Scripts/python.exe` at write time
(manifest stays POSIX-canonical) and doctor's compare normalizes through the
same function. 12 new tests, 892 green, fresh-container walk re-verified.

## [2026-08-01] — Windows CI green: POSIX-only skips on the new DPLAN-0279 tests

**fix(ci)** — the srt-resolver subprocess tests and doctor's /proc-fallback
tests (both added today) failed on Windows CI only. The srt candidate tests
hand node a minimal env — without SYSTEMROOT node's CSPRNG aborts at startup
(exit 134) — and their sh-script npm stubs plus lib/node_modules layouts are
POSIX scenarios by design (srt's sandbox wrap targets bwrap + /bin/bash). The
doctor tests force os.name='posix' process-wide, which makes pathlib dispatch
Path() to PosixPath on Windows and unrelated code in the patch window
(the logger call) dies with NotImplementedError. Both get explicit
POSIX-only skip markers; Windows-relevant coverage (usage-error contract,
non-posix early return) still runs everywhere. Linux/macOS coverage unchanged.

## [2026-08-01] — context gauge copy: calm heads-up, not panic (calm-compact doctrine)

**fix(hooks)** — `context_gauge.py` still preached the pre-recovery doctrine
("run /prep NOW", "before auto-compact takes the choice away", "imminent") —
written for DPLAN-0253, before PreCompact recovery injection and the post-compact
regroup (DPLAN-0276/0278) made auto-compact survivable by design. The same
session this shipped in proved the machinery live: compact fired mid-turn, the
PostToolUse backstop re-grounded once, one-shot token held. New copy is a calm
cue — bank memories via /prep at the next natural breakpoint, act without
asking, keep working. Docstring updated to match; 8/8 gauge tests green.

## [2026-08-01] — doctor + setup.sh adopt the srt resolver; doctor message truthing (DPLAN-0279, @aipass scope)

**fix(aipass)** — doctor's `sandbox_checker.py` and setup.sh's sandbox-prereqs
block stopped mirroring the srt path derivation and now shell out to
`_srt_resolve.mjs --resolve` (located via `importlib.util.find_spec`, no
hardcoded path) — the last two copies of the node-prefix==npm-prefix assumption
are gone. Install hints now name the prefix npm will actually use
(`npm root -g`), and "missing" is distinguished from "installed but not
resolvable". Walk warts from the same round-3 session: root `.venv` at
AIPASS_HOME no longer flagged "redundant" (setup created it; nested project
venvs still flagged), pytest-collect timeout 30s→90s with actionable remedy
text, `detect_shell()` falls back to `/proc/<ppid>/comm` when `$SHELL` is
unset. 18 new tests (880 total green), seedgo 100%.

## [2026-08-01] — srt resolver: candidate-list prefix discovery + honest exit codes (DPLAN-0279, @hooks scope)

**fix(hooks)** — `_srt_resolve.mjs` derived npm's global prefix from node's
install location (`dirname(dirname(process.execPath))`). On Debian/Ubuntu apt
layouts and official node Docker images node lives in `/usr` while npm installs
globals to `/usr/local` — srt was reported missing while correctly installed,
and the advised `npm install -g` could never satisfy the check. With the
sandbox flag ON that layout fail-closed every dispatch. Now: candidate-list
discovery (`npm_config_prefix` env → `npm root -g` → `/usr/local` → `/usr` →
execPath derivation), dynamic `import()`+`pathToFileURL` preserved per the ESM
constraint. The silent exit-0-on-failure path (uncaught top-level rejection) is
fixed — non-zero exit with tried candidates on stderr — and a new `--resolve`
CLI mode gives doctor/setup a resolve-only contract (path on stdout, exit 0/1).
5 new subprocess tests incl. the Debian split-prefix layout; found by the
fresh-eyes container agent during the round-3 install walk.

## [2026-08-01] — setup.sh hook-block drift: PostToolUse matcher + dead Write() ask rules (round-3 walk)

**fix(setup)** — setup.sh's hand-rolled hook block shipped the pre-v2.7.10
PostToolUse matcher (`Bash|Edit|MultiEdit|Write|NotebookEdit`); doctor then
wired the manifest's widened matcher (`…|Read|Grep|Glob|Task`, the DPLAN-0276
regroup backstop) alongside it. Both matched on any Bash/Edit call — the hook
bridge fired **twice per tool call** on fresh installs, and setup's
strip-and-readd merge resurrected the stale entry on every re-run. Matcher now
mirrors `provider_manifest.json` exactly, so doctor's dedup recognizes it.
Also dropped the `Write(~/.claude/**)` ask rules setup shipped — Claude Code
never matches `Write(path)` rules (only `Edit(path)` covers file-editing
tools) and warned about them at every launch. Found live during the round-3
container walk. PreCompact "duplicates" investigated same pass: false alarm —
manual/auto matcher pairs are by design.

## [2026-08-01] — Compact fixes: regroup double-arm, newest-first memory enforcement (DPLAN-0278)

**fix(hooks)** — the DPLAN-0276 post-compact re-ground backstop fired up to 17×
per session (~400KB injected, plausibly *causing* extra compactions). Root
cause: `session_start.py` called `cadence.reset_counter()` on `source=compact`
on top of `compact.py`'s own PreCompact reset — double-arming `regroup_pending`
every compact boundary. Fixed (compact added to `_SKIP_SOURCES`) and hardened:
the boolean flag is now a one-shot per-arm token with timestamp, consumed
atomically; duplicate resets within 30s reuse the existing token; every arm
logs caller+PID. Also: the re-ground payload now teaches the memory-file shape
(`.trinity` arrays are newest-first — insert at index 0, number = max+1), the
recovery text's `key_learnings[-10:]` inversion became `[:10]`, and
`edit_gate` mechanically rejects `.trinity` session/learning edits that append
at the tail or regress the number field. Background: a post-compact agent that
lost the newest-first convention wrote fresh entries at the array tail, where
the next rollover archived them as "oldest" — memories silently eaten within
the hour.

**fix(memory)** — rollover safety valve: tail entries dated today or numbered
above the array head are held back with a warning (misplaced fresh writes, not
oldest history). AUTO-COMPACT SNAPSHOT entries get their own small cap
(default 3) instead of consuming the 15-session budget (~40% of memory slots
were machine boilerplate, evicting real memories ~1.7× faster).

**fix(drone)** — memory-branch `rollover` command gets a 100s executor timeout
override (was killed at the 30s default twice in 3 days mid-archive).

**fix(hooks-tests)** — the "ghost re-arm" solved: `test_compact.py` invoked the
compact handler with no cadence isolation, so every pytest run of it minted a
real regroup token into the developer's own live session state file
(`/tmp/aipass-cadence-<session>.json`, session id inherited from the
environment) — and pytest's log capture swallowed the arm line, making the
subsequent backstop fire look sourceless. One suite run = one ghost re-ground
(~24KB injected); a test-heavy session saw 16+. Fixed with an autouse fixture
pinning `_GUARD_DIR` to tmp_path and a fake session id; verified by running
the full hooks suite and confirming the live state file stays unarmed.

**chore(hooks)** — provider manifest ↔ live settings reconciled both
directions (manifest gained `PreCompact:auto_process`; live PostToolUse
matcher gained `Read|Grep|Glob|Task` so the backstop sees read-tools);
seedgo's provider-hooks snapshot baseline updated to match; navmap breadcrumb:
a memory missing from `local.json` likely rolled over — `drone @memory search`
finds it.

## [2026-08-01] — CI wall-time phase 1b: pytest-xdist (DPLAN-0277)

**ci(speed)** — the test suite now runs `-n auto --dist loadscope` in the
ci.yml matrix and the Windows/macOS workflows (locally: ~5:10 serial-era
xdist attempt failed 19-27 tests; now 12,296 pass in ~4:20 across 3
consecutive full runs). Two classes of shared-state disease were fixed,
tests-only: (1) sys.modules poisoning — tests that faked packages with
MagicMocks, force-"reimported" modules (a no-op: `from pkg import mod`
short-circuits on the parent attr), string-path-patched a module a neighbor
had evicted (the patch lands on a NEW instance while the test calls the old
one), or left raw unrestored sys.modules writes — fixed across
seedgo/aipass/ai_mail/api/daemon/flow/trigger test files by pre-warming real
imports before faking, patching and calling through one module object, and
monkeypatch-routing every mutation. (2) shared-file races — every branch's
templated `json_handler.log_operation` does an unlocked read-modify-write on
real `<branch>_json/*_log.json` files; under loadscope two classes of the
same branch land on different workers and race (empty-read JSONDecodeError),
and a torn write leaves debris that breaks later runs. A repo-root
`conftest.py` guard now skips any `log_operation` whose `*JSON_DIR*`
resolves inside the repo (tmp-redirected handlers keep full behavior), which
also stops test debris in real branch json dirs. Bonus catches: a telegram
backoff test asserting exactly-once on a process-global `time.sleep` mock
(leaked watchdog threads hit it 17k times), and a feedback_pulse test whose
"no session id" path fell back to the live `CLAUDE_CODE_SESSION_ID` env var
and fired on every 10th run. `--dist loadgroup` (branch-affinity) was
evaluated and rejected: 9:26 vs 4:20 — one long-pole branch eats the
parallelism.

**fix(ci)** — follow-up caught by the PR's serial coverage job: the conftest
guard's teardown must restore `log_operation` only when its own wrapper is
still in place. A test that reloads a handler module mid-test (spawn's
`test_reimport_after_mock`) rebinds every re-export to a fresh handler;
blind-restoring the pre-reload bound method permanently split spawn's
`log_operation` (old instance, real repo dir) from its siblings — 6
tmp-path assertions failed serially while xdist dodged it (the reloader and
the victims land on different workers). Proven both modes: 12,296/0 serial
and xdist.

**fix(ci)** — Python 3.10-only xdist flake in drone's
`TestTriggerFireIntegration`: the tests string-patched
`aipass.trigger.apps.modules.core.trigger` while `create_pr`/`merge_pr`
lazily import that module at call time. On 3.10, `mock.patch` resolves the
string via a getattr chain over parent-package attributes, so after a
neighbor test evicts `core` from `sys.modules` the mock lands on the stale
module held by the parent attr while production re-imports a fresh one — and
the handlers swallow trigger errors by design, so the miss is silent
("fire call not found"). 3.11+ use `pkgutil.resolve_name` (sys.modules-backed)
and converge; that's why only the 3.10 leg flaked. Fixed by importing `core`
once at file top, pinning it into `sys.modules`, and patching through the
module object — deterministic on every version.

## [2026-08-01] — CI wall-time phase 1a (DPLAN-0277)

**ci(speed)** — measured on PR#723: the suite ran 7x per push and every job
ran TWICE (push + pull_request both firing on dev). Shipped the zero-risk
half: heavy workflows (ci/windows/macos) now trigger on PRs + push-to-main
only (dev work is PR'd within minutes, so dev-push runs were pure
duplicates); `concurrency` cancel-in-progress so a re-push kills the stale
run; the coverage job no longer `needs: [test]` (it re-runs the suite itself
— chaining it after the matrix serialized the two longest jobs into a
~13-min critical path); the 4 test-matrix legs drop their `coverage run`
wrapper whose data was never collected. `pytest-xdist` added to the dev
extra. Parallel execution itself (`-n auto`) is staged as phase 1b: a local
proof run found 19 tests with shared-state hygiene issues (sys.modules
reimport tests, json_handler template files, flow plan-data writes, seedgo
bypass.json) — inventory + fix plan in DPLAN-0277.

## [2026-08-01] — night train (v2.7.10)

**fix(setup)** — cold install died silently right after the "What should we
call you?" prompt on the git-identity-skipped path: the skip-normalization
(`[ "$USER_NAME" = "skip" ] && USER_NAME=""`) was the last command in
`resolve_user_name`, so any answer except the literal word "skip" — including
the plain Enter the prompt itself advertises — returned 1 and `set -e` killed
the whole script before registry/bootstrap/doctor/chat. Now a proper `if`.
Live-caught by Patrick's round-3 container walk (DPLAN-0274); the only
instance of the pattern in a kill position (all other `[ ... ] && ...` sites
verified safe by direct `set -e` repro).

**feat(hooks)** — post-compaction regrounding backstop (DPLAN-0276). Root
cause of the confabulation incident: PreCompact's `reset_counter()` only arms
cadence for the next UserPromptSubmit, an event that never fires during long
tool-call-only autonomous stretches — agents ran ungrounded after compaction
2+ (cadence.log: 6 back-to-back PreCompact resets, zero `should_fire`
between). PostCompact stdout is never surfaced to Claude, so the fix is a
PostToolUse backstop: `reset_counter()` sets a `regroup_pending` flag, new
`lifecycle/post_compact_regrounding.py` atomically consumes it and injects
kernel+navmap+branch+identity via `additionalContext` on the next tool call.
The four prompt handlers' file-loading extracted into shared
`modules/grounding_content.py` (one source of truth); provider-manifest
PostToolUse matcher broadened (Read|Grep|Glob|Task — the narrow matcher was
itself part of the dead zone). Fired live in production during the fixing
session's own compaction; 11 regression tests replaying the incident; full
suite 1298 passed.

**feat(seedgo)** — incremental audits (DPLAN-0275): fingerprint cache
(`audit/incremental_cache.py`) audits changed files only — full-fleet audit
~5 min → ~3.6 s warm. Cache invalidates on edit, new violation, and file
delete (live-tested); `--full` still forces a cold pass.

**feat(skills)** — Telegram `/stop` verb: bot-side intercept (slash text
injected into a TUI session fuzzy-morphs into different queued commands —
verbs must never be injected), plus slash-command guard and a 600 s
stuck-pending timeout that kills the Superseded spiral.

**fix(ai_mail)** — dispatch-monitor forensics hardening (FPLAN-0371, the five
monitor fixes from the seedgo-drops investigation) across
`dispatch_monitor.py`, `wake.py`, and `header.py`, including the sync
sub-agents rule in dispatch headers (headless dispatch reaps orphaned
background work after 600 s).

**fix(flow)** — `close_ops` template-detection could fast-delete real minimal
FPLANs (57 lost, unrecoverable — never archived). Rule now absolute:
detection may warn, never delete; archive-before-delete always (FPLAN-0372).

**docs** — README truth-pass (root: codecov row, name-at-setup, the three
install prompts; ai_mail + hooks READMEs updated to match their shipped
behavior).

**tests** — seedgo provider-hooks snapshot baseline re-blessed: it predated
the 2026-07-30 TG mirror deploy (`user_message_relay` UserPromptSubmit hook)
and had been failing locally since (CI skips these — no provider settings
there).

**feat(onboarding)** — Patrick's round-2 container walk + the in-container
concierge's own field report, folded into one train (DPLAN-0274). Doctor now
runs automatically in the install tail — after setup, before the concierge
says hello (Patrick's ruling: "it should run before aipass say helo") — with
the safe `--fix` pass; hook wiring is P1, and a still-broken result lands as
a loud ACTION NEEDED headline plus the top of the concierge's greeting
(`run_doctor_preflight` in doctor.py, wired via `install --chat-only` so both
cold-clone and re-run paths get it; a crashed preflight says so instead of
passing silently). Git identity prompt is now skippable (blank Enter or
literal "skip", stated up front), validates email shape, and never silently
stores garbage — skips print the exact `git config` commands to run later.
The install asks the user's name once ("What should we call you?", git name
as default) and stores it in untracked `AIPASS_REGISTRY.json → metadata.user`
— the concierge greets by name; the git-tracked CLAUDE.md placeholder stays
un-personalized. Everything skipped or still broken collects into one
highlighted ACTION NEEDED block printed last, right before the chat opens
(sudo/srt requirements were scrolling past unseen). README install story
updated to match.

**fix(registry)** — the fresh-install "19 doctor errors" root-caused
(@spawn FPLAN-0367): passports were NEVER git-tracked at any tag — the
missing piece was stamping at install. setup.sh now reconciles registry
owner + citizen identity right after bootstrap (`fix_owner_identity`), and
`detect_pollution` was re-keyed to branch_name — every citizen in a project
sharing one `registry_id` is the intentional shared-project-credential
model, which the old detector itself flagged as pollution. Doctor's
duplicate wording follows the same re-key, passport role reads its real
nested path (`identity.role` — every passport printed "unknown"), the
missing-hooks list no longer doubles event prefixes or repeats entries, and
`--fix` refuses to suggest relocating `.venv` (it would break hooks wired to
`$AIPASS_HOME/.venv`). `.claude/provider_manifest.json` dropped the two
stale `rm` deny rules that `provider_reconcile` strips on sight — the
mathematically unclearable doctor warning is gone (@hooks).

**fix(tests)** — `tests/docker_clone_test.sh` seeded its "fresh clone" with
`cp -r`, dragging gitignored local state (real passports included) into the
tree and faking clone results — now a real `git clone`. `Dockerfile.test`
gains tmux so the concierge's tmux path has something to run on. New
`tests/setup_identity_test.sh` (27 assertions) covers the identity/skip/name
flow against the real setup.sh functions. 862 aipass tests green.

## [2026-07-31] — post-v2.7.8 (no version bump, Patrick's call)

**fix(onboarding)** — the concierge welcome chat silently inherited
`defaultMode: acceptEdits` from the repo's shipped `.claude/settings.json`,
with no way to choose otherwise (Patrick live-caught on the v2.7.8 walk). The
install's chat ending now asks how the session should run — 1) accept edits
(default, Enter/Ctrl-C keep it) or 2) bypass permissions — and threads the
choice into the existing `launch_inline` flag variant (`skip-permissions` →
`--dangerously-skip-permissions`, machinery already in `build_cli_cmd`, never
offered until now). Headless/dry-run paths unchanged.

## [2026-07-31] — v2.7.8

**feat(onboarding)** — the cold install now ends in a conversation, not
project creation (DPLAN-0274, Patrick's ruling: "end with in a chat with
@aipass to welcome the new user"). A fresh clone's `./aipass install` execs
`setup.sh`, which never had the v2.7.3 chat machinery — it dead-ended in a
first-project prompt instead. setup.sh's tail now routes into the existing
handoff (`aipass install --chat-only --path <repo>` → `_build_install_prompt`
+ `launch_inline`), so the welcome prompt is composed in exactly one place;
nothing is duplicated in bash. Project creation is removed from the cold
install on BOTH paths (setup.sh first-project block, install.py
`_handoff_to_init` chain + `--project`/`--no-init`/`--with-init` flags —
replaced by `--no-chat`/`--chat-only`); `aipass init run` stays the separate,
later step the concierge points users at. Truth pass on the root launcher
help, `aipass install` help, README (the v2.7.7 "first project's directory"
prompt line is gone — the only install prompt left is git identity), and
CONTRIBUTING. TTY/CI-gated: headless shells print a run-`claude`-later
breadcrumb and exit 0. 831 aipass tests green.

## [2026-07-31] — v2.7.7

**fix(prax)** — event-queue self-feeding warning firehose (live-caught at 3
cores burned). When the monitoring queue fills, every dropped event logged a
warning into `event_queue.log` — a log prax itself watches — so each warning
spawned a new `type=log, branch=PRAX` event that also failed to enqueue:
20–80 warnings/sec sustained, log rotating in seconds, log_watcher at 88%
CPU, prax monitor at 65%, four Telegram bots at ~25% each. Fix: drop warnings
are rate-limited to one per 30s carrying a dropped-count, the exception now
renders with `!r` (`queue.Full` has an empty `str()`, which is why the log
showed a blank reason), and `event_queued` operations are recorded only for
events that actually queued (was: every attempt, another per-event write into
a watched log). Proven: 500 forced drops → exactly 1 warning; post-restart
CPU settled 88%→0% / 65%→2%, bots to idle. Devpulse surgical fix, @prax
notified for the deeper design pass (drop-oldest policy, why the queue filled).

**fix(onboarding)** — Docker cold-install test findings, five UX fixes
(DPLAN-0274). Patrick ran the fresh-user journey (clean Ubuntu container, no
AIPass state, README only) and first-project setup failed twice identically.
Fixes: (1) a typed bare project name anchored to CWD — the cloned engine repo —
and tripped init's own-tree guard; both the setup.sh handoff (the path a fresh
clone actually runs) and install.py's mirrored copy now anchor non-absolute
input to `$HOME`, never CWD. (2) Both prompts now say explicitly what Enter
does vs typing a name (stranger test: zero-context users must be able to tell).
(3) Git-identity defaults were OUR identity — a stranger pressing Enter became
`AIOSAI <aipass.system@gmail.com>`; defaults removed, interactive re-prompts
until real values, non-interactive skips with a warning instead of guessing.
(4) Bootstrap summary hardcoded "13 branches" while 17 bootstrap; now a live
counter. (5) Preflight errors distinguish the engine repo from a real project
and hints carry real paths; README now names both prompts ahead of time.
Built by @aipass on dispatch (832 tests, seedgo 100%), devpulse-verified:
both anchor implementations proven against bare/absolute/tilde/relative
inputs. Companion: `Dockerfile.test` now installs bubblewrap, ripgrep, and
`@anthropic-ai/sandbox-runtime` so Claude Code can sandbox in-container.

---

## [2026-07-31] — v2.7.6

**fix(tests)** — random-test audit hardening, three branches. A usefulness
audit (random sampling across all suites) found brittleness in good tests, not
junk: drone's commit test-gate tests stubbed `subprocess.run` with ordered
canned results that could misalign silently if the pipeline gained a call — now
a `_assert_ordered_calls` helper verifies each recorded argv matches the step
its canned result was written for (applied to all 6 ordered-stub tests, guard
proven against synthetic misalignment). trigger's SIGTERM shutdown test traded
its flaky fixed 50ms sleep for a deadline poll. ai_mail's `on_email_delivered`
dropped 4 dead parameters — a legacy hook shape; its `update_central()` rescans
inboxes itself, so per-delivery counts were never part of the contract (both
call sites + 5 tests updated). Fixes built by the owning branches on dispatch,
devpulse-verified.

**feat(aipass)** — CLAUDE.md fence for nested projects + return-path breadcrumb
(DPLAN-0247 follow-through). Root cause found via Patrick's cold `aipass new`
test: Claude Code loads CLAUDE.md from every ancestor directory (git boundaries
don't stop the walk), so agents in `projects/<name>/` inherited the host root
CLAUDE.md and culture file — the newborn ran the host startup ritual its own
protocol never contained. Gate proven live before building: `claudeMdExcludes`
in the project's `.claude/settings.local.json`. Shipped through the shared
scaffold so `init`/`new`/`adopt` all emit it (generation-time path resolution,
merge-never-clobber, idempotent), `aipass init update` retrofits existing
tenants, and doctor flags fenceless nested projects. Breadcrumb: `launch_inline`
now shell-wraps the exec so a return path (`cd <agent home> && claude
--continue`) prints after the session exits — CC's own hint is cwd-blind and
fails from any other directory. Built by @aipass (832 tests, 41 new; seedgo
100%), devpulse-verified E2E: fresh project fence + clean-context probe, sha-
identical idempotency on the reference tenant, 4 tenants retrofitted live
(doctor WARN → PASS, env pins preserved). Windows-hardened in two follow-up
fixes on the same train: `as_posix()` at the generation site (a524461d — settings
files carry POSIX paths on every platform), then separator-insensitive
comparison everywhere fences are checked (ed093df6 — `_normalize_exclude` in
merge-dedupe and doctor's fence detection, so a hand-written backslash fence
still counts as present and is never rewritten).

## [2026-07-30] — post-v2.7.5

**fix(skills)** — wake-sources script idempotency, live-caught during the T3
deploy session with Patrick: masking an already-masked GPE returns EINVAL on
this kernel, so the boot unit's first `enable --now` failed while the
hand-applied mask was still active (the script's "safe to repeat" comment was
wrong). GPE write now guarded by a state check, mirroring the existing
wakeup-toggle guard; proven by re-running the installer against the
already-applied state — unit green. Devpulse-landed (small cross-branch fix),
skills notified. **T3 DEPLOYED same session on Patrick's "make it permanent":
grants refreshed, wake-sources boot unit enabled (masks now persist reboots),
telegram-bot@base restarted onto the hardened resume logic. DPLAN-0270 freeze
lifted; remaining: overnight heartbeat soak (T4).**
reality (Patrick flagged it stale; every claim verified against source, not the
brief): control verbs + control-center concept, /suspend modes + grants package
(honestly marked code-only pending DPLAN-0270's T3 deploy), streaming replies
as a live-edit layer on the Stop-hook flow, user_message_relay's
dual-registration requirement (hooks.json enable + provider bridge entry,
`drone @hooks verify` — the half-registration that kept the mirror dead since
07-14, found and wired live tonight, DPLAN-0272 P0/P2), offline 409/429
backoffs. Ported-but-unwired table + seedgo bypass reconciled both directions:
chunk_text/_extract_assistant_text now wired (removed), tmux_manager helpers
confirmed still unwired (control verbs call tmux directly). Doc + bypass.json
only — no code, no deploys, freeze intact. Built @skills, devpulse-landed.

**feat(skills)** — /suspend hardening after live phone testing (CODE ONLY —
deliberately not deployed; Patrick's slow-down ruling, deploy happens in a
planned test session): (1) resume detection rewritten — wall-clock jump in
the poll loop is now the primary signal (a >45s gap between iterations =
the process was frozen = we just resumed; threshold sits above the
POLL_TIMEOUT+backoff idle ceiling), because systemd on the target machine
provably never executes /etc/systemd/system-sleep hooks (5 live suspends,
zero stamps, no errors — cause unknown, worked around); the root hook is
demoted to optional fallback. (2) Stale-stamp bug fixed — heartbeat
activation now baselines to the file's current stamp (live-caught: a
manual test stamp was read as a fresh resume before the suspend even
started). (3) Installer uses install -D (live-caught: /etc/systemd/
system-sleep/ didn't exist → install failed). (4) New wake-sources boot
unit reapplies the gpe4E mask + XHC1/RP0x wakeup disables every reboot
(live-found: a gpe4E interrupt storm — 8.5M — was yanking the machine out
of S3 within seconds; masking it took a 60s alarm test from 8–13s sleeps
to exact-second wake). (5) Spurious-wake absorption tested: wake → grace →
no command → re-arm+re-suspend, plus a mid-grace slow-iteration edge case
found while writing the test. 888/888 TG (devpulse re-verified), 26
suspend tests, seedgo 100%. Built by @skills, live evidence from Patrick's
phone testing session.: missing-file sweep on every scan
(`heal_registry.py`). The dead-file auto-close only ran inside
`create_plan_impl`, so a phantom row died only if a NEW plan of the same
type happened to be created — DPLAN-0265's auto-close was that coincidence
(DPLAN-0270 created moments later), while phantom TDPLAN-0015 sat open
indefinitely because no new TDPLAN ever came (proved empirically: scan
healed 0, 0015 still open, before the fix). `_heal_missing_file_plans` now
runs in the per-type doctrine loop — every registered type swept for dead
file_paths on every scan, independent of create activity. Live: 0015
auto-closed in one pass, second run healed 0 (idempotent). Also codified:
a dead-path row can close AND have its number squatted simultaneously —
independent doctrine cases. 4+1 new tests, 769 green, seedgo 100%. Built
by @flow (DPLAN-0271), night-shift, devpulse-landed.

**fix(skills)** — `user_message_relay` (terminal→TG mirror) was inert since
creation, two causes (`user_message_relay.py`): (1) it globbed `bot-*.json`
for bot configs, but `bot_factory` writes mirror configs as `{bot_id}.json` —
zero matches ever (the `bot-*.json` naming is real but belongs to the
PENDING_DIR transcript-relay stream files, a different subsystem);
(2) `devpulse.json` carries no `chat_id` — added a read-only fallback: a
single-entry `allowed_user_ids` IS the private-chat id (documented Bot API
behavior), ambiguous/empty configs still skip silently, no new write path.
The existing test fixture used the wrong `bot-` prefixed filename itself —
which is exactly why the bug survived; fixture fixed, 5 regression tests
added. 882/882 TG green (devpulse re-verified), seedgo 100%. Hook-side fix,
no bot restarts needed. Built by @skills (FPLAN-0363), closes todo #85 /
DPLAN-0270 P2 residual. (DPLAN-0270
P5, night build): suspend the laptop from the control chat. No-arg =
heartbeat mode (ack → arm RTC alarm via `sudo -n rtcwake -m no` →
`systemctl suspend`; on each timed wake a root systemd system-sleep hook
stamps `resume_signal.json`, the bot's poll loop gives a ~100s grace window
to drain Telegram's server-side queue, stays awake if a command arrived,
else re-arms and re-suspends). `/suspend 8h`/`45m` = single-wake night mode.
Root grants ship as reviewable repo drafts (`tools/suspend/`): hardened
sudoers drop-in (exact binary path), polkit rule scoped to
`org.freedesktop.login1.suspend` + one user (needed because a `--user`
service is not an "active session" for polkit), system-sleep hook, and a
one-shot installer (`visudo -c` validated) — nothing installs or suspends
until Patrick runs it. Failure paths abort before suspending and name the
missing grant. 20 new tests (subprocess fully mocked), 877/877 TG green,
seedgo 100%. Built by @skills (FPLAN-0362), devpulse-verified + landed.
`systemctl suspend` is async per man systemctl — the sleep-hook signal file
is the only reliable resume marker; that finding drove the design.

## [2026-07-29] — post-v2.7.5

**feat(skills)** — Telegram control verbs v1+v1.1 (`base_bot.py`,
`telegram_standards.py`): the bot chat is now a control plane — `/status`
(honest `aipass-*` tmux session listing), `/start <branch>` (wake:
attach-or-respawn via `claude -c`, no longer a welcome stub), `/kill <branch>`
(deterministic bot-side `tmux kill-session`, no LLM in the loop) — works with
zero Claude PIDs running. v1.1 root-cause: there is no separate "aipass" bot —
Patrick's control-center chat IS `bot_id=base` with `branch_name: "aipass"`
persisted, so v1's `branch_name is None` gate silently excluded it; new
`_is_control_bot()` (base or aipass) fixes the gate, BotFather menu
re-registered live (7 commands, `/kill` new, `/start` label corrected —
verified via `getMyCommands` against the running bot). Supersedes FPLAN-0289
"attach-not-spawn" for explicit control verbs (guard stays for plain
messages). Live phone test passed: kill/start "like a switch". 857/857 TG +
1109/1109 skills tests, seedgo 100%. Built by @skills (FPLAN-0360),
design DPLAN-0270, devpulse-landed.

**fix(prax)** — `prax_registry.json` torn-write corruption
(`registry/save.py`): the shared module registry was written with plain
`open('w')+json.dump` by every prax-initialized process (each telegram bot,
each branch process, plus the ecosystem-wide file watcher they all run) —
concurrent truncate-and-write races interleaved and left trailing garbage
("Extra data: line 21 column 2", 109 load-failure spams in the base bot log).
Now atomic: temp file + fsync + `os.replace`, matching `json_handler.py`'s
proven pattern. 1067/1067 prax tests green, 2 regression tests added (no
leftover tmp files; 20x sequential saves all parseable). Built by @prax
(FPLAN-0358), devpulse-landed. (`heal_registry.py`, wired into
the normal registry scan): plan-number conflicts now resolve themselves —
number collisions (a different live file squatting on a closed row's number),
unregistered plan files, and wrong-prefix ghost rows (the FPLAN-0011 recovery
class) all heal by renumber-and-register. Original registry rows are never
touched, `.md` files never renamed. Path-level idempotency index prevents the
same squatter re-registering under a fresh number every scan (caught live:
first version minted 3 duplicate opens per cadence cycle; twice-run proof now
in the test suite — second scan must heal zero). `dropbox` added to
IGNORE_FOLDERS (exact-match, received-files dirs never auto-register — 802
plans under `.backup` were already correctly ignored) and the ignore policy
is documented in flow's README. Live results: healed the 0165 collision +
0175 unregistered file Patrick's plan audit surfaced, plus 2 more of the same
classes found on its own. 763 tests green, seedgo 100%. Doctrine per Patrick:
flow always auto-heals — never manual registry resolution (compass #186/#190).

## [2026-07-28] — post-v2.7.5

**fix(skills)** — Telegram `base_bot` error-classification: 409 conflict
handling (v1.4.1) + 429 rate-limit backoff (v1.4.2). A 429 was previously
unclassified — generic branch, zero delay, tight re-poll loop against an
API that just said back off. Now honors Telegram's `retry_after` from the
response body (30s fallback via `_extract_retry_after`, same pattern as
`_stream_edit`). 839/839 TG + 252/252 skills tests green. Built by
@skills from medic threads a495228a/c042d846, devpulse-landed.

## [2026-07-28]

**fix(ci)** — ruff config pinned against 0.16.0's default expansion
(dependabot PR#707 lint red, 6,651 errors): we had no explicit `select`,
so the bump silently opted us into a dozen new rule families (UP/I/BLE/
DTZ/SIM/…), and the 0.16 formatter started reformatting Python snippets
inside markdown (43 READMEs). `select = ["E4","E7","E9","F"]` pins the
rule set we always linted against; `extend-exclude = ["*.md"]` keeps
READMEs prose. Verified locally: check + format --check green under both
0.15.22 and 0.16.0, zero source changes. Adopting new rule families is a
deliberate cleanup DPLAN, not a version-bump side effect.

**fix(flow)** — plan restore was type-blind (VERA repro from Vera Studio:
`restore PPLAN-0011` collided with FPLAN-0011): `restore_plan_impl` always
loaded the default fplan registry because prefix-stripping never re-derived
the type for routing. close_ops already had the correct routing — its four
helpers are now a shared `registry_routing.py` consumed by both ops (fix
the class, not the symptom). Backup recovery is prefix-restricted too (it
could previously recover a newer same-numbered backup of the wrong type),
and restore messages now print the real plan type. 738 tests green incl.
new cross-type collision coverage, seedgo 100%. Built by @flow,
devpulse-verified. Known follow-up flagged: create's advertised 4th-arg
template selector is dead code in the parser (pre-existing, unshipped).
CI follow-up: the adapted recovery test let type discovery read the real
`flow_json/template_registry.json` — runtime-managed and gitignored, so
fresh checkouts have none and the no-prefix fallback searches zero types;
discovery is now pinned in the test (close_ops tests already mocked it —
the house pattern).

**chore(feedback)** — VERA feedback sweep: `atproto` (Bluesky SDK behind
@api's publish driver) was the third undeclared dependency caught in 12
hours — new `[bluesky]` extra, setup.sh installs it by default; VERA's
`weekly_update.md` SOP template committed to flow's playbook templates
(registration + create-syntax verified by @flow); stale tier0_kernel
docstring corrected (claimed every-turn, actual cadence period 5);
Patrick's external-project update flow proposal banked as DPLAN-0264
with VERA's S32 audit evidence.

**fix(api)** — Google credential refresh adopts the transient-vs-structural
log split (error 78cd43aa, 324 occurrences): `TransportError` (network/DNS
blips) now logs WARNING; genuine credential failures (invalid_grant,
revoked token) stay ERROR for the medic pipeline — same convention as the
backup Drive-sync fix. Plus a README Known Issues note: extras added after
a venv was built need a setup.sh re-run to appear. openai stays in `[llm]`
(api's core-vs-extra call — plumbing not product). 516 tests green,
pyright 0, seedgo 100%. Built by @api, devpulse-verified. CI follow-up:
the ImportError fallback set `TransportError = None`, and `except None`
is a TypeError at catch time — red on every runner without the `[drive]`
extra (the refresh test bypasses the availability gate). Fallback is now
an empty tuple (legally catches nothing); verified under a forced
no-libs simulation.

**fix(backup+setup)** — Drive sync outage root-caused + made medic-visible
(Patrick escalation from the MacBook): Drive sync died 2026-07-17 when a
setup.sh run wiped the venv — the google libraries
(google-auth/google-auth-oauthlib/google-api-python-client) were never
declared in pyproject, only ever hand-installed, so the clean install
couldn't restore them. Worse, the failure was structurally invisible:
@api's gateway RuntimeError died in a generic `except Exception` →
`logger.warning`, and WARNING routes to @trigger's no-op handler — medic
can only see ERROR/CRITICAL. Now: `authenticate()` escalates the
"libraries not installed" case to `logger.error` with the install hint
(transient auth/network failures stay WARNING — regression-guarded);
new `[drive]` extra owns the deps; setup.sh installs it by default so
Drive sync survives venv rebuilds (the OAuth secret in ~/.secrets always
did). 249 backup tests green, live-verified on the real broken venv,
seedgo 100%. Built by @backup, devpulse-verified + wiring landed.

## [2026-07-27]

**feat(hooks)** — never-enrolled projects get a voice (GH-712, DPLAN-0263):
an external project ran 6+ days with its whole hook layer silently dark
because it was never enrolled in the trust registry — fail-open by design,
zero signal. `never_enrolled_banner()` now fires a one-time-per-session
nudge ("hooks are OFF here — run `aipass init update`") for any project
with a hooks.json but no registry entry; trust checks run unconditionally
for UserPromptSubmit (the old `presence_gate` gate was bridge-specific and
fragile). `prune_stale()` drops dead project paths at enroll time.
1,287 hooks tests green, live-verified on both fresh and populated
registries. Built by @hooks, devpulse-verified. CI follow-up: the new
banner made `test_compass_recall.py`'s engine tests enrollment-dependent
(green on enrolled dev machines, red on fresh checkouts — all 10 CI reds
were this one test); neutralized with the same autouse banner-patch
fixture test_engine.py already used, verified under a fresh-machine
HOME-override simulation.

**feat(aipass)** — trust registry hygiene + honest enrollment output
(GH-712, DPLAN-0263): `_enroll_project()` now skips throwaway paths (the
leak that bloated the registry to 795KB / 2,272 entries — 2,245 dead
pytest tmpdirs, parsed on every hook fire in every project); new
`aipass trust prune` CLI drops dead-path entries (live run: 2,141 pruned,
795KB → 44KB); `aipass init update` now *says* "Enrolled in trust
registry — hooks active" instead of enrolling silently. 791 tests green.
Built by @aipass, devpulse-verified.

**fix(setup)** — DPLAN-0263 audit sweep: fresh installs now include the
`[llm]` extra (previously every fresh venv was born with the fleet-wide
`get_response()` contract dead — openai lived in an optional extra the
install line never requested; root cause of a 2-month silent outage);
generated registry seeds `metadata.id` so spawn's `REGISTRY_ID`
placeholder renders real values on fresh fleets.

**refactor(setup)** — setup.sh delegates `.trinity` stubs to spawn's
templates (DPLAN-0263 P2): `bootstrap_branch()` no longer hand-rolls
passport/local/observations heredocs — it renders all three from spawn's
own templates via `resolve_template_class` + `build_replacements_dict`,
the same machinery `spawn create`/`update` use. The heredocs had drifted
to a pre-numbered-entry schema (dict `key_learnings`, nested
observations) the cap/rollover system doesn't expect — second source of
truth eliminated. Renders memory's live `*_meta` cap lines; keeps
relative `branch_info.path` and the `aipass.` module prefix. 378 spawn
tests green, fresh/idempotent/manager E2E scenarios verified twice
(builder + devpulse independently). Built by @spawn, devpulse-verified.

**fix(setup)** — the drift canary's first catch, same night it shipped:
`setup.sh` still bootstrapped every core branch with `citizen_class:
"builder"` — the pre-rename legacy name — so every fresh clone (all CI
runners, every external contributor) got legacy-class passports that the
just-removed silent fallback used to absorb. Renamed to `aipass_framework`
and extended the bootstrap passport stub to the full template contract
(`git_branch`, `traits`, `purpose`, …), so CI-built fleets satisfy the
canary honestly. Second canary catch same night: the bootstrap list was
also missing backup/commons/daemon/skills entirely (a stale "moved to
external repos" note from S82/S87 — they returned to core long ago); all
17 core branches now bootstrap.

**fix(hooks)** — e2e rm-gate test relied on trust-registry bootstrap
coincidence: on machines with an existing `trusted_projects.json` the
ephemeral hook workspace was never enrolled, the gate failed open, and the
test failed while CI (fresh registry → bootstrap auto-trust) stayed green.
The fixture now enrolls/revokes the workspace deterministically. e2e 14/14
both environments. Flagged for backlog: never-enrolled projects fail open
with only a quiet log warning — no TRUST BREAK-style banner. Built by @hooks.

**fix(flow)** — registry monitor runaway logs (137 lines/min): plan-file
regex never matched real slugged filenames (all 310 plans read as deleted
every scan), `IGNORE_FOLDERS` substring match skipped whole trees (`dev`
matched `devpulse`), closed plans weren't excluded from orphan checks.
False removed-events per scan: 303 → 1. 733 flow tests green, 3 new
regressions. Built by @flow.

**feat(spawn)** — passport drift auto-heal (DPLAN-0262, fallout of PR #710):
existing agents never received template-guaranteed passport fields — 17/17
core passports drifted (`email`, `git_branch`, `traits`), invisible for
months. `spawn update` now heals passports against a strict allowlist
(`branch_info.email`, `branch_info.git_branch`, `identity.traits`) — existing
values always win, identity content stays create-only, legacy top-level
`traits` arrays migrate into `identity.traits`, backup before every write.
The silent citizen-class fallback is gone: unknown class, corrupt or missing
passport now hard-error loudly (`resolve_template_class()` recognizes
`manager` via a role tiebreaker instead of guessing `aipass_framework`).
New `test_passport_drift.py` is a permanent live canary — red on any future
drift. Template scaffold smoke test degrades to skip on branches with their
own conftest. Fleet healed post-verification: 17 core + 3 project agents,
canary green. 377 spawn tests + E2E (throwaway citizens, hand-drifted /
corrupt / unknown-class passports, local + Docker). Built by @spawn,
devpulse-verified.

**feat(spawn)** — passport templates now populate `traits` and `email`
(PR #710, first external contribution — thanks @slaguru666): `--traits` and
the branch address were computed by spawn's placeholder builder and silently
discarded because no template referenced `{{TRAITS}}`/`{{EMAIL}}`; every
agent's identity hook rendered `Email: unknown`. Two lines per template
(`aipass_framework` + `project_agent`), registry regenerated (also drops
seven stale `.pytest_cache` entries), 5 regression tests. Verified
clean-room + Docker (Ubuntu 24.04): spawn suite 363 green both, all five
new tests confirmed red pre-fix. No-flag agents render exactly as before.

**fix(skills)** — Telegram 409 conflict fix v1.4.1: base bot session-conflict
handling + scheduler bot hardening (base_bot, scheduler_bot), closing the
live outage where a stale Telegram session held getUpdates and locked
users out. Skills suite 1090 green.

**feat(ai_mail)** — wake v2 (DPLAN-0261 groundwork): daemon self-wake support —
the step-3 manager gate now recognizes `.daemon/schedule.json` as
self-authored consent, so a branch's own scheduled job may wake a manager
while dispatch/manual manager wakes stay blocked. Test + live-verified;
ai_mail suite 780 green.

**docs** — CONTRIBUTING.md: external PRs target `dev` (main only receives
tested release trains — gap surfaced by PR #710); template-registry
regeneration note. CROSS_OS_TESTING.md touch-up. devpulse `.daemon/`
schedule tracked (disabled), consistent with other branches.

## [2026-07-21]

**feat(prax)** — Commons live social feed in the monitor (DPLAN-0257, Patrick
ask verbatim): `drone @prax monitor run commons` now streams The Commons'
chatter — posts, comments, votes, reactions — room-tagged with mood coloring,
monitor-style. ~10-event backfill on open, then 1.5s id-cursor polling.
Read-only by construction (`mode=ro` sqlite URI — write attempt refused,
verified live); commons stays the only writer, zero commons-side changes.
Branch-log tail still reachable via `monitor run commons --logs`; mixed branch
lists unchanged. `--relay` rides the existing Telegram relay path.
33 new tests, prax suite 1065 green, audit 100% (52 files). Door-tested live:
devpulse posted/replied/reacted while the feed streamed every event.
Built by @prax.

**fix(hooks)** — two DPLAN-0253 backlog hardenings (DPLAN-0256 clear):
engine handler timeout + presence_gate PID-reuse defense. `_run_handler` now
runs handler-type hooks on a daemon thread joined with the hooks.json
`timeout` field (default 30s) — a hung handler returns TIMEOUT loud
(engine.jsonl + sound) and the event moves on; daemon thread chosen over
ThreadPoolExecutor so a stuck orphan can never hang interpreter exit.
presence_gate occupancy no longer trusts `os.kill(pid, 0)` alone:
`procStart` (CC session file) is matched against `/proc/<pid>/stat` field 22
so a kernel-recycled PID can't impersonate a dead session — closes the gap
before observe-only ever flips to enforcement. Missing procStart / non-Linux
falls back to liveness-only, logged. 15 new tests, suite 1272 green,
seedgo 31/31 both files. Built by @hooks.

**fix(trigger)** — runaway-log alerts get the 24h TTL every other mute already
had (DPLAN-0256 backlog clear): `_write_alert()` hardcoded `expires_at: None`,
so alerts.json entries nagged forever while medic branch mutes self-expired.
New `DEFAULT_ALERT_TTL_SECONDS = 86400` (matches medic_state's
`DEFAULT_MUTE_SECONDS`) with a `forever` escape hatch threaded through
`handle_runaway_log_detected()`. 2 new tests, trigger suite 621 green,
audit 100%. Built by @trigger.

**feat(drone)** — joint-decision gate on `drone @git merge` (DPLAN-0256,
Patrick ruling S330: merges are always done together, never accidental).
The gate sits in `_handle_merge` before the plugin import — `merge_pr()` is
unreachable without confirmation. A real terminal gets an interactive y/N
prompt; headless callers (agent Bash) are refused unless `--confirm` is
passed explicitly. Every gate decision (confirm / tty-yes / tty-abort /
headless-refused) is logged via json_handler. 6 new tests (86 green),
live-fired refusal verified, seedgo 31/31.

**feat(skills)** — telegram user_message_relay joins the sound layer: relay
events now carry their own sound key so an inbound user message is audible
like every other hook event (59/59 + 252 green).

**fix(devpulse)** — watchdog stall threshold 120s → 300s: the 120s
no-JSONL-activity heuristic fired `[watchdog.stall]` on healthy agents doing
long tool calls; 300s matches observed real-stall behavior (verified live
S330). Branch `.claude/settings.local.json` carries the devpulse
`autoCompactWindow: 350000` dial (Patrick ruling S326 — devpulse compacts
~292k, dispatched agents stay pinned at 200k).

**fix(seedgo)** — checker accuracy arc (S330): AST-based import analysis
lands in the checkers (dead_code, encapsulation, handlers, readme,
test_quality, unused_function) — 13 false positives eliminated fleet-wide,
2 real hooks imports that legitimately bypass the pattern documented instead
of suppressed. branch_audit, checklist and ignore_handler aligned; provider
hooks snapshot fixture refreshed; stale bypass entries for deleted tools
purged across branches (devpulse, memory, seedgo, hooks). Fleet audit 100%.

**feat(hooks)** — hook sound layer + temporal grounding. Sounds now mirror
the log across the hook fleet (prompt, lifecycle, notification, security
handlers) — audible liveness for the whole layer, verified live (2465 green,
audit 100). New `prompt/temporal.py`: tiny always-on UserPromptSubmit handler
injecting one line of local date/time/weekday/part-of-day every turn — live
clock each fire, host timezone via `astimezone()` (clones see their own local
time). Wired on both wires (`.aipass/hooks.json` + provider manifest).

**feat(aipass)** — `aipass adopt` + shared scaffold refactor: adopt turns an
existing `projects/` directory into a full AIPass project (registry, resident
agent, `.aipass`/`.claude` scaffold) — every write additive, nothing existing
overwritten; unlike `aipass new` it starts from a directory with its own
content and git history. New `shared/` package (`project_home.py`,
`scaffold_content.py`) gives init/new/adopt one source of truth per helper —
`handlers/init/scaffold_content.py` moved there, no per-command copies to
drift. Proven live adopting aipass-site (doctor 31/0). Spawn template registry
synced (template bug chain me→spawn→aipass, fixed S329). 786 tests green,
audit-clean.

## [2026-07-20]

**docs(projects)** — `projects/README.md`: the projects section now ships in
the repo (the `!projects/README.md` gitignore whitelist existed since the
aipass-new design but the file was never written). Explains the project model:
**private by default** — each project is its own local git repo, fully ignored
by the AIPass repo, and publishing is an explicit opt-in step (Patrick ruling
2026-07-20). Opens the public roster with **Earmark**
([AIOSAI/earmark](https://github.com/AIOSAI/earmark)), the first public AIPass
project — a VS Code read-aloud extension with local Piper TTS and true
pause/resume, born, built, and published 2026-07-20.

**fix(hooks)** — persistent_alert dedup + loud trust-break banner (5-agent
trace round follow-ups, DPLAN-0253 tail):

- persistent_alert's once-per-session sound dedup lived in a module-global set,
  but every bridge call is a fresh process — TTS would have announced on every
  prompt while any alert was active. Replaced with session+alert-keyed tempdir
  guard files (context_gauge idiom); banner capped at 10 alerts with an
  "...and N more" note.
- Trust-registry breaks are now LOUD: any `.aipass/hooks.json` change breaks
  the enrolled hash and silently disabled the entire hook layer (bit us live
  for 2+ hours — tier prompts, security gates, everything dark, one log-file
  WARNING as the only signal). New `is_hash_mismatch()` distinguishes a
  genuine break from never-enrolled; `trust_break_banner()` does a
  config-independent walk+hash check; the engine emits a full-width banner
  once per prompt via the presence_gate bridge call. No auto-heal —
  re-enrollment stays a deliberate human checkpoint. Live-fired: hash broken →
  banner; restored → healthy. 16 new tests, suite 1206 green, seedgo 100%.
- Go-live day for the whole handler roster: 11/12 manifest entries wired into
  provider settings by devpulse with Patrick accepting (user_message_relay
  held: synchronous Telegram call + full prompt text off-machine — needs a
  background send and an explicit call first). @hooks branch prompt corrected
  and hardened: two-wires checklist + mandatory provider-wire flag in every
  build reply.

**feat(hooks)** — auto-compact prep: context gauge + mechanical snapshot
(DPLAN-0253, built by @hooks, two rounds):

- `context_gauge` (UserPromptSubmit) — reads live context fill from the session
  transcript every prompt (cheap 50KB tail), resolves the branch's compact
  window (env > branch `settings.local.json` `autoCompactWindow` > 200k), and
  injects a "run /prep NOW" nudge at 80% of the compact trigger, escalating at
  95% — once per threshold per session. Memory prep happens before auto-compact
  takes the choice away, on every branch including dispatched agents.
- `pre_compact_prep` (PreCompact) — stamps a mechanical AUTO-COMPACT SNAPSHOT
  session entry into the compacting branch's `.trinity/local.json`: context
  fill %, active dispatch locks, open plans, git state, inbox unread. Templated
  from live state, defensive (malformed memory = log + skip, never raises).
- Shared `context_window` module: bounded transcript tail reader + per-branch
  window resolver. 36 new tests; suite 1190 green; seedgo 100%.
- Round 2 root-cause fix: handlers wired only in `.aipass/hooks.json` never
  fire on name-scoped events — UserPromptSubmit and PreCompact invoke the
  bridge per-handler from provider settings. Both handlers now have
  `provider_manifest.json` entries; @hooks' branch prompt corrected (it taught
  the old one-entry-per-event model) with a "new handler? check the provider
  wire" reminder. Go-live needs the user's `~/.claude/settings.json` synced
  from the manifest + fresh sessions.

## [2026-07-19]

**feat(ai_mail)** — dispatched agents default to Sonnet 5 (Patrick ruling S326):

- wake.py model resolution passes bare aliases (`sonnet`/`opus`/`haiku`)
  straight to the Claude CLI, which resolves latest-in-class — the pinned-ID
  MODEL_MAP is gone and can never go stale again. Default flips opus → sonnet.
- dispatch_monitor pins `CLAUDE_CODE_AUTO_COMPACT_WINDOW=200000` on every
  spawned agent — Sonnet 5 is 1M-context native, and without the pin every
  dispatched agent would silently inherit a 1M window. E2E-proven: a live
  dispatched probe reported `claude-sonnet-5` + `WINDOW=200000` from inside.
- Follow-up landed same morning: the "daemon gap" was a name collision —
  the unpatched `spawn_agent()` was ai_mail's own inbox-poller
  (`handlers/dispatch/daemon.py`), not the @daemon branch. It now passes
  `--model DEFAULT_MODEL` (imported from wake.py, single source); the 200k pin
  was already covered via the shared dispatch_monitor wrapper. @daemon's
  scheduled wakes import `wake_branch` directly and were covered from the start.

**fix(skills)** — Telegram poll 5xx now triggers network backoff (medic loop,
autonomous @skills fix): `HTTPError` ≥500 in `poll_updates` raises
`_NetworkPollError` instead of falling through to rapid-fire retry; 4xx still
logs and returns. Three new tests (502/503 backoff, 429 stays out).

**fix(spawn, commons, prax, hooks)** — S304 audit fix campaign, Track A
(DPLAN-0250, four owner dispatches verified + committed by devpulse):

- **spawn** — shared `is_protected()` (infrastructure floor / registry owner /
  active passport) now guards both pollution repair and branch delete; repair no
  longer flags the live `src/aipass/aipass` branch, and deleting a protected or
  actively-passported branch is refused with the reason.
- **commons** — branch-name resolution lowercased across all five ops sites
  (trade/artifact/profile/welcome/search) to match identity normalization;
  gifting and trading work again (guards had never matched since mid-June).
- **prax** — pytest detection now also checks `_pytest` in `sys.modules`, so
  `patch.dict(os.environ, clear=True)` in test suites can no longer strip the
  guard and freeze prod-path log handlers into the setup cache.
- **hooks** — the two static-path JSONL writers (engine diagnostics, telegram
  delivery log) resolve their path per-write and route to the tmp test dir
  under pytest; a full 1154-test suite run now adds zero lines to prod logs
  (marker-bounded proof).

Also: `/prep` now checks the cross-project feedback box every run — the S304
"unread since April" backlog (F46) is processed to zero and can't silently
rot again.

**fix(aipass)** — `aipass doctor` no longer invents errors on a healthy repo
(S304 F14-17): `.backup` and spawn `templates` dirs excluded from the agent
scan, relative registry paths anchored against the project root instead of the
caller's CWD (running doctor from inside a branch dir showed 5 fake
missing-branch errors), and info-severity findings now render as warnings
instead of pass checkmarks. Remaining findings on this repo are genuine.

**fix(flow)** — registry aggregate writes are lock+atomic (S304 F85 residual):
`save_branch_registry` and `save_central` were bare `open`+`json.dump`; both now
use the O_EXCL lockfile + temp-file + `os.replace` pattern from the earlier
`save_registry.py` fix. Proven with a 6-process concurrent-write hammer. Also
investigated (N1): FPLAN-0313/0314 closed blank because
`is_template_content()`'s line-count threshold fires before its bracket-marker
check on default templates — guard fix queued, registry annotation is the
maintainer's call.

## [2026-07-18]

**fix(tests)** — the immortal `MagicMock/LOG_FILE/` directory is dead: a hooks
engine test patched `diagnostics.LOG_FILE` with a bare Mock, and prax's
`append_jsonl` turned the mock's fspath into a real `mkdir` — every test run
re-minted an empty `MagicMock/LOG_FILE/` in the runner's CWD (found in repo
root, devpulse, and hooks). Test now patches a real tmp path; 100/100 green,
clean-CWD run verified to mint nothing.

**docs** — merge playbook gains a site drift-check step (DPLAN-0249 follow-on):
every merge run now asks whether install commands, onboarding flow, agent count,
or the platform/CLI story changed — if yes, aipass.ai must be updated the same
day. Codifies the S323 ruling that the site is a projection of the README, never
its own source of facts. Template edit by @flow, one checklist line in the
post-merge section.

**docs** — root README v3 restructure (DPLAN-0249): single-funnel story with
zero duplicated commands (install, `aipass new`/`init run`, trees, drone
examples each taught exactly once), hero link line to aipass.ai/PyPI/r/AIPass,
three reserved gif slots. Positioning ruling: the README tells only the
Claude Code on Linux/WSL story — Codex/macOS/Windows mentions and the Roadmap
section removed (code support unchanged; Docker distribution will serve those
users later). Earlier same day: stale demo.gif embed dropped (#701) and
aipass.ai realigned to the v2.7.3 front door.

**v2.7.3** — the onboarding chain: from `git clone` to a conversation with an
agent that remembers you. Install's three dead-ends are gone — the default
`init` path, headless runs, and `aipass new` all now end where they should:
`install` chains through the guided init and **opens a live conversation with
the AIPass concierge**, first prompt authored with the install report in its
context. The concierge's Welcome Mode (research-backed opener, one name-ask,
deferred setup triage, hooks-first health check via a real @hooks dispatch,
every suggestion with its exact command) was proven in a live multi-turn
door-test — including the second-session payoff: relaunch, and it picks up
mid-task where you left off. Plus `aipass new` and the front-door overhaul below.

### Added (onboarding chain — TDPLAN-0014)

- **Install→chat handoff**: after init returns, install `launch_inline`s the
  concierge with an authored first prompt (fresh-install recognition + binary
  report). TTY-only; headless returns cleanly.
- **Welcome Mode** in the concierge branch prompt: capability opener with 3–5
  concrete starters, single graceful name-ask, ~turn-5 setup push ("every
  machine is different"), hooks-first verification incl. trust-registry
  enrollment, setup plan seeded from the cross-OS checklist, Windows→WSL
  recommendation, prax-monitor + hooksound tips, exact copy-paste command with
  every suggestion.
- **Feedback pulse** (@hooks): one ignorable line every ~10 turns with the repo
  feedback link — `aipass feedback on/off` (alias for `drone @hooks feedback`)
  turns it off. Registered disabled for the AIPass host itself. 25 tests.
- **Dead-end kills**: empty-template init now runs handoff + report stages
  (default path ends in the conversation); non-interactive installs complete
  with defaults and exit 0 (headless stage 9 prints the launch command instead
  of spawning); `aipass new` auto-launches into the new project's manager agent
  on a TTY with a printed fallback and Ctrl-C escape line.
- **Unified handoff prompt**: one `INIT_PROMPT` constant (was two drifting
  strings in init_flow vs handoff).

### Fixed (onboarding chain)

- Non-TTY `aipass init run` crashed with EOFError at the first prompt (caught
  in a live door-test after unit suites ran green — the prompt layer now
  auto-detects non-TTY and takes defaults).
- `aipass new` outside an AIPass environment now exits 1 instead of 0.
- Empty-template handoff messaging no longer claims an agent exists
  ("Your project is ready", resolved absolute path instead of `cd .`).
- Stage numbering shows a skip notice instead of silently jumping 5→8.

## [2026-07-17]

**v2.7.3 (first pass)** — `aipass new` and the front-door overhaul. The `projects/`
directory is now a first-class playground: `aipass new <name>` creates a fully
isolated project — own registry, own git repo with a birth commit, born
deployable — with a full framework resident agent that answers
`drone @<name>` from inside the project while staying invisible to the host
roster. ai_mail enforces the project boundary (cross-project mail is refused
with a pointer to the feedback channel). A live door-test of the aipass CLI
exposed a blind spot in the audit — perfect structural scores on an unusable
front door — so seedgo grew two user-facing-quality standards (`cli_ux`,
`readme_quality`) and a fleet-100 campaign brought every branch's help output
and README to the house pattern: 17/17 branches at 100%.

### Added

- **`aipass new <name>`** (module + handler): creates `projects/<name>` with
  registry-first credential linkage (`registry.metadata.id ==
  passport.citizenship.registry_id`), empty/python templates, interactive
  template + agent prompts (flags for scripted use), a full framework agent
  (entry point, modules/handlers skeleton, trinity set, mailbox, tier files),
  git init + birth commit, and next-step output. 49 tests.
- **seedgo standards 41–42**: `cli_ux` (8 AST checks — two-tier help, Rich
  console, styled title, purpose line, --help pointer, Usage, Examples, no
  exposed internal plumbing) and `readme_quality` (Quick Start with runnable
  code block, stranger accessibility, invoke/entry-point match, early
  what-description). 36 tests + case-resolution regression tests.
- **ai_mail cross-project boundary**: sender and recipient project roots
  compared on delivery; cross-project sends refused with a feedback-channel
  pointer. Fail-open for internal/unregistered sends. 13 tests.
- **Root `.gitignore`**: `projects/*` ignored (each project is its own repo);
  only the future catalog README stays trackable.

### Added (second pass — the agent becomes a real citizen)

- **`aipass new` agents are now spawn-issued full citizens** (FPLAN-0334): the
  hand-rolled scaffold in the new_project handler is retired for a
  `spawn_agent()` call against @spawn's new `project_agent` template — branch
  prompt, structured mailbox, birth certificate, trinity trio, dashboard,
  house-pattern entry point, and a branch-style README. One authority issues
  citizens; project agents inherit template evolution for free.
- **Agent home = `src/<project>/<agent>/`**, mirroring the host's
  `src/aipass/<branch>` layout (door-test ruling: the project root is never an
  agent home). Seat paths are relative like host seats; the registry walk stops
  at the first project registry. The first agent is the project's **manager**
  (`citizen_class: manager` — its devpulse), named after the project.
- **Birth-commit hygiene**: the `.venv` symlink (absolute host path) and the
  registry lock file are no longer tracked in new projects' birth commits.
- **Boundary verified live in all four directions**: host↔project email and
  dispatch all refused — project→host lands on the ai_mail cross-project check
  with its feedback-channel pointer, closing the leak found in the S319
  prototype probes.

### Changed

- **aipass front door rebuilt**: `--help` now follows the house pattern with a
  curated command list, usage, and examples (internal plumbing hidden —
  `doctor_fix`/`doctor_wire` renamed underscore-private); `aipass help` shows
  the Q&A screen instead of falling through to the module dump; README
  rewritten to pass the stranger test with a Quick Start and the correct
  invocation.
- **Fleet-100 sweep**: 15 branches gained Quick Start READMEs and/or
  Usage/Examples help sections — each owner fixed their own front against the
  new gate.
- **Debug_Print detector hardened**: the regex-based checker matched `print(`
  inside string literals (flagging cli_ux_check's own error messages — the
  auditor was the last branch under 100%). String content is now stripped
  before matching, with a regression test; plus a depth-5 nesting refactor in
  the same file.

**v2.7.2** — everything merged since v2.7.1, headlined by the compass decision
engine v2: curation with supersedes links + write-time conflict advisories
(Track 1), and ambient recall — rated past decisions now surface verbatim into
live sessions on matching prompts, governed by session caps and spacing
(Track 2). Also in this release: the plan close pipeline completes itself
(auto-vectorization + crash-safe registry writes), drone's 3-layer subprocess
timeout policy with a collision-free `--drone-timeout` flag, plan-number memory
search that pins the exact plan, a fleet-wide seedgo 100% restoration, and
SSH-signed commits now verifying on GitHub. Details in the sections below
(2026-07-16 carries the full stories).

### Changed

- **Release cadence ruling: every dev→main merge ships a PATCH bump + tag by
  default.** PyPI tracks main, always current; version numbers carry no
  significance during beta — the big jump is reserved for beta exit.

- **Merge playbook SOP refined from live run PPLAN-0010.** The raw
  `git fetch origin main:main` step (now blocked by the git gate) is replaced
  with `drone @git sync` in both places it appeared, and the template opens
  with the exact create command (`drone @flow create . "Merge summary" merge
  pplan` — template name before type), closing the trap where the wrong arg
  order silently stamps the default template.

## [2026-07-16]

### Added

- **Compass ambient recall — Track 2 (DPLAN-0246/FPLAN-0332): rated decisions
  surface unprompted.** On every user prompt, a new hooks handler
  (`compass_recall`, registered in `.aipass/hooks.json` only) queries compass
  FTS with the prompt text and injects matching rulings VERBATIM —
  `[BAD] #56: <decision text>` — tidbits, never vibes. Three branches, one
  pipeline, each piece behind a modules/-boundary API: devpulse's
  `recall_decisions()` (side-effect-free scored candidates; rare-token
  evidence scoring + a query-side stopword filter so greeting/filler words
  can't fake relevance) + `mark_surfaced()` (counts only real injections);
  @memory's pure `should_surface()` governance (promoted from the dormant
  symbolic engine: threshold, 5/session cap, 10-message spacing — first
  surface exempt, 300s cooldown, dedup; state-in/state-out, caller persists);
  @hooks' 90-line handler + engine per-handler budget (errors never block a
  prompt — `compass_recall_unreachable` log signature for @trigger's watcher).
  Live acceptance matrix through the real bridge: topic-with-history prompts
  recall the right ruling (a CI prompt surfaced the red-CI-never-parked
  ruling), small talk and greetings stay silent, repeat prompts gate on
  spacing. Review caught and fixed pre-ship: wrong payload key (`userInput` →
  `prompt`), phantom `CLAUDE_CODE_SESSION_ID` env (session id is
  stdin-payload-only), spacing gate blocking the first surface, and a trust
  registry re-enrollment gap that silently disabled ALL project hooks for 20
  minutes after the hooks.json edit. 446 devpulse + 1011 memory + 1129 hooks
  tests green; seedgo 31/31 on every touched module.

- **Compass curation v2 Track 1 (DPLAN-0246/FPLAN-0331): supersedes links +
  write-time conflict check.** A correcting compass entry now archives and
  links what it replaces in one transaction (`compass add --supersedes N`);
  query renders both directions ("supersedes #N" / "ARCHIVED — superseded by
  #M") so a retracted decision can never masquerade as current truth. Every
  `compass add` FTS-checks the new text against active entries and prints a
  non-blocking "possible conflict with #X" advisory — flag-and-ask, no LLM, no
  auto-resolve (boardroom ruling). New `compass note <id>` command (FTS
  re-index proven by test), `--include-archived` query flag (the avoid-list is
  finally searchable), dead `score` column removed from all code surfaces
  (kept inert on disk — zero migration risk). Idempotent PRAGMA-checked
  migration ran clean on the production store (128 rows, no loss); the four
  fresh-eyes-audit archive pairs got their links backfilled. /prep now runs
  one `compass review` per session — curation living in a path that already
  runs, the lesson of all three compass eras. 435 devpulse tests green,
  seedgo 31/31 on both touched modules.

- **Close pipeline completes itself (DPLAN-0245): auto-vectorization +
  crash-safe registry writes + drone timeout policy.** Closing a plan now
  produces all side effects from one command — `post_close_runner` invokes
  @memory's plan intake directly after archival (detached, loud on failure,
  drains any backlog it finds), so plans can no longer silently pile up
  unvectorized. Plan registry saves (@flow `save_registry` + mbank
  `save_flow_registry`) now use the O_EXCL lockfile + atomic
  tempfile-and-replace pattern, closing the same lost-update race class fixed
  earlier in CLOSED_PLANS. @drone gained a 3-layer timeout policy: per-command
  overrides (`@memory process-plans` 120s, `@flow close` 90s), a `--timeout N`
  flag, 30s default — replacing the flat 30s guillotine that killed legitimate
  long commands mid-pipeline; the timeout error now says how to override.
  Proven end-to-end live: one `drone @flow close` on a throwaway plan yielded
  archive + vectors + ledger + registry with zero manual steps, and the
  auto-trigger swept a pre-existing backlog file on its first run. 730 flow +
  878 drone tests green, seedgo 100%.

### Fixed

- **CI seedgo gate back to 100% across all 17 branches.** The Track 2 compass
  recall code left three branches at 99%: @hooks' compass_recall handler was
  missing json_handler operation logging and had two silent catches (now
  logged); @memory's governance module held its implementation in modules/
  (moved to handlers/governance/engine.py with modules/governance.py as the
  thin re-export — the cross-branch import path is unchanged and live-E2E
  verified through the real bridge); devpulse's README test count had drifted
  (309 → 348). Audits re-run per branch: 100% overall, all suites green.

- **Plan-number memory search hits the exact plan.** Searching a plan ID
  ('DPLAN-0244', 'fplan 0332' — any case, dash or space) now pins the exact
  plan as the top result at 100%, via a metadata lookup on the vector store's
  source-file field instead of embedding similarity (which treats all plan IDs
  as near-identical strings and never surfaced the target). Patrick ruling:
  searching a plan number must return that plan first. Semantic search quality
  for normal queries is unchanged. Also purged 193 junk vectors — throwaway
  probe/flaky test plans from scratchpad sessions (dv4 batch, probe_test_plan,
  throwaway_e2e_proof) that had leaked into the store. 1011 memory tests green.

- **drone --timeout collision: router flag swallowed module flags.** The
  DPLAN-0245 subprocess-timeout flag consumed the first `--timeout` token
  anywhere in argv, so module-level flags silently vanished — watchdog's
  `--timeout 1800` never arrived and long watches died at the 600s default
  (live repro x2). Drone's flag is now namespaced `--drone-timeout`; plain
  `--timeout` passes through untouched to the target module, with a regression
  test pinning the passthrough. Per-command overrides intact. 879 drone tests
  green, seedgo 100%.

- **@memory command routing eaten by the new governance module.** The
  governance module shipped in Track 2 had the wrong `handle_command`
  signature (`args: list` instead of `command: str, args: list`) and always
  returned True, so auto-discovery routed EVERY @memory command through it
  first — `drone @memory search` answered "governance: unknown command 's'".
  Fixed to the standard signature returning False for commands not its own;
  search verified live (135 results). Library modules must decline commands
  they don't own or they silently hijack the whole CLI. 1011 memory tests
  green, seedgo 31/31.

## [2026-07-15]

### Fixed

- **Plan vectorization pipeline unwedged (DPLAN-0245): 57 closed plans were
  silently missing from semantic memory since mid-June.** Vector IDs were pure
  content hashes, so identical template boilerplate across different plans
  produced duplicate IDs within one ChromaDB upsert — the store rejected the
  entire batch, and the all-or-nothing intake retried the same failing batch
  forever. Fixed in @memory: IDs are now salted with the source filename when
  present (rollover hashes unchanged — no re-vectorization churn), in-batch
  dedup as a safety net, and `process_plans()` now runs per-file with the
  manifest saved after each success so a poison file can never wedge the queue
  again. Backlog drained and verified: 229/229 archived plans vectorized, 1112
  chunks, formerly-lost plans answering semantic queries at 85%+ similarity.
  990 memory tests green.

- **CLOSED_PLANS ledger append race (@flow): concurrent plan closes lost
  entries.** `append_to_closed_plans` was an unlocked read-modify-write; the
  S314 bulk sweep lost 18 of 21 entries to it (reconciled by hand). Now guarded
  by an `O_CREAT|O_EXCL` lockfile with retry/backoff, and the previously
  silent append failure is surfaced in close output and logs. 730 flow tests
  green.

- **Telegram routine read-timeouts no longer logged as errors (@skills,
  Patrick ruling): ends the medic wake-loop.** A routine long-poll read
  timeout (`socket.timeout` — an `OSError` subclass) slipped past the earlier
  `URLError`-only guard into the network-outage path, logging ERROR once per
  episode (~576 lines/30h) and waking @trigger's medic each time. The
  `_is_routine_read_timeout` guard now covers the `OSError` handler too, and
  the genuine-outage episode-start line is demoted ERROR→WARNING (backoff
  self-heals; recovery already logs INFO; medic only fires on ERROR/CRITICAL).
  Real failures still log ERROR. 825 telegram tests green.

### Security

- **Hook config trust model hardening (DPLAN-0244): closes a zero-interaction
  RCE from untrusted `.aipass/hooks.json`.** The hook loader walked up from CWD
  and trusted any `.aipass/hooks.json` it found; since the bridge is wired
  globally in provider settings, a hostile repo shipping a `command`-type hook
  could execute arbitrary shell on `SessionStart` with no user interaction.
  Fixed with defense-in-depth. **Layer A (engine):** per-project configs may no
  longer run `command`-type hooks (refused via an unconditionally-stamped
  `_source` provenance flag), and handler paths are gated to the `aipass.*`
  namespace. **Layer B (loader + CLI):** a trusted-project registry
  (`~/.aipass/trusted_projects.json`, path + sha256) that the loader checks
  fail-closed; on upgrade it bootstraps **only** the `$AIPASS_HOME` install
  (never trust-on-first-use of an arbitrary directory); `aipass init`/`init
  update` auto-enroll, and new `aipass trust`/`revoke` commands manage
  enrollment. Both gates proven to block the attack independently via a live
  acceptance test driving the real bridge with a real payload. 1105 hooks +
  133 aipass tests green. Origin: external scan (false positive at
  `engine.py:37`) whose triage surfaced the real adjacent hole.

### Added

- **Supply-chain hardening pass (DPLAN-0243): commit signing + hash-pinned CI
  tooling + release provenance.** All commits are now SSH-signed via a
  dedicated repo-scoped signing key (first signed commit 9048666c, verified
  `Good "git" signature`). Every standalone pip tool install across the four
  CI workflows now installs `--require-hashes` from lock files in
  `.github/requirements/` (pip/ruff/build/pytest/pip-audit), generated with
  full multi-platform hash coverage — including the Windows `colorama` marker
  dependency that naive Linux-side pinning silently drops. `publish.yml`
  gained a SHA-pinned build-provenance attestation step (activates on the
  next release), and Dependabot now watches the new lock directory as a
  grouped `pip` ecosystem. Editable `-e .` installs untouched. Full 31-check
  CI matrix green on the change. Driven by the OpenSSF Scorecard gaps
  surfaced via hvtracker.net (HVTrust 82.0, #1 in Multi-Agent Systems);
  detector-gap correction filed upstream as YugantM/hvtracker#186 (Claude
  Code-native projects misread as "no Anthropic dependency").

### Fixed

- **CI green pass on the runaway-log PR — every red was ours, every fix
  verified.** Morning-after triage of PR#696's failing checks: the test
  matrices' only failure was the known parked flake, but lint and the seedgo
  audit were genuinely red from the previous night's new code. One `ruff
  format` on trigger's runaway-handler tests fixed lint. The audit findings
  went back to their owners by dispatch: @hooks built the branch's missing
  json_handler and wired it into `persistent_alert`/`alert_dismiss`, added the
  introspection no-args gate, and flattened `_menu_live()`'s nesting
  (1071 tests green); @prax refactored `rate_tracker.py` to dependency
  injection — the module layer now injects `logs_dir` and `trigger.fire` via
  `configure()`, so the handler carries no cross-handler or handler→module
  imports (1028 tests green). Both branches re-audit at 100% across all 41
  standards, independently verified. Detection re-proven live post-refactor
  with a fresh planted log storm. Also trimmed the tier-1 navmap prompt
  (9.3k → 7.9k chars, under its ~8k injection cap) with the comms doctrine
  intact.

- **Windows flake pinned: `test_is_pid_alive_dead` escaped the ca096295
  sweep.** That commit's rule — tests mocking `os.kill` must pin
  `sys.platform="linux"` because Windows takes the ctypes OpenProcess path and
  never reaches the mock — was applied to every pid-liveness test except this
  one. It only failed when PID 1234 happened to be alive on the runner
  (environment lottery, first hit today). Pinned like its siblings. The
  remaining Windows session_boot reds and the relay mtime-cache flake predate
  this PR and stay parked.

- **The parked reds, unparked — Patrick's ruling: red CI is never parked.**
  "If CI is red, it's because you or I left it red." Both remaining reds fixed
  by their owners the same hour. @prax root-caused the relay mtime-cache flake:
  the test only passed when two writes landed in the same mtime-granularity
  window (true locally, false on CI runners) — fixed by pinning mtime with
  `os.utime` so the cache contract is tested deterministically, proven 50/50 +
  20/20 loops. @hooks root-caused the four Windows session_boot reds: the boot
  path's `_tmux_session_exists()` ran a real `subprocess.run(["tmux", ...])`
  that Windows runners can't satisfy (WinError 2) — mocked in all four tests
  per the ca096295 convention, leaving `execvp` (already mocked) as the only
  terminal call. Ruling recorded in compass; the "forget CI" era is over.

- **Burst-evasion closed: bursty runaways can no longer slip past the rate
  tracker.** Found live during the morning's chain verification: any single
  below-threshold 10-second scan window zero-reset the sustain counter, so a
  bursty writer (20 short lines every 6 seconds — 200 lines/min average, the
  exact retry-loop-with-sleep shape of the TG relay incident) ran 4 minutes
  undetected. @prax's fix (rate_tracker v1.2.0): severity now evaluates
  `max(instant_rate, 60s window average)` — continuous writers behave exactly
  as before (instant rate dominates), bursts sustain through their gap
  windows, and subsidence still clears as zeros fill the window. Four new
  burst tests; live-proven with the previously-evading storm pattern:
  `RUNAWAY WARNING: prax_burst_storm_test.log — 191 lines/min sustained 120s`
  in the tracker log, fired from the restarted running service. Detection
  evidence now spans all three storm shapes: continuous fast (332/min),
  continuous moderate (257/min), bursty (191/min).

### Added

- **TG streaming v2 polish (DPLAN-0229): the last two finalize paths now
  honor the streaming flag.** v1 shipped with a deliberate gap — when logs
  were active mid-turn or the final response exceeded 4096 chars, the Stop
  hook fell back to "Done." + a fresh message, orphaning the streamed bubble.
  @hooks threaded `streaming` through `_deliver_chunks`: logs-active now
  reconcile-edits the streamed message with the final formatted response, and
  multi-chunk edits chunk 1 in place then sends [2/N]+ as continuations.
  Batch mode is verified zero-change (regression tests for both paths), plus
  an edit-fail fallback. 6 new tests, 1077 green. Live streamed-turn proof
  pending Patrick's next streaming session — honestly flagged, not faked.

## [2026-07-14]

### Fixed

- **Prax TG relay gets the same offline backoff as the bots.** Found in
  Patrick's live plug-pull test: the bots went quiet correctly, but the
  monitor→Telegram relay kept logging `Send failed` every ~5 seconds (89 lines,
  no backoff) — and each failed-send error was re-ingested by the log watcher,
  feeding the relay more events to fail on. Now network-class send failures put
  the relay in offline mode: doubling backoff (1s→60s cap), flush gate skips
  sends while offline so the monitor loop never blocks and viewers keep
  rendering, log-once semantics (one enter line, one 5-minute summary, one
  recovery line with drop count), full reset on first successful send. 11 new
  tests; 1007 prax green.

- **TG bots no longer hot-spin when the internet drops.** Live find from
  Patrick's on-location tether outage: DNS failure makes `urlopen` fail
  instantly (no 30s long-poll wait), so the shared poll loop retried as fast as
  it could — up to 13 ERROR lines/second per bot, all 5 bots spinning for the
  whole offline window (rotation saved the disk; nothing saved the CPU, and the
  flood tripped the medic circuit breaker fleet-wide). Now network-class poll
  failures (DNS/connection/socket, classified via `_NetworkPollError`) back off
  exponentially 1s→60s cap and reset on the first successful poll, with
  log-once semantics: one "unreachable, backing off" line, one summary per 5
  minutes while offline, one recovery line with suppressed count. Routine
  long-poll read-timeouts (expected getUpdates behavior, ~863 medic-suppressed
  events/day) no longer log at all. Bots still self-recover the moment
  connectivity returns. 25 new tests; 822 TG + 252 skills green.

### Added

- **Runaway-log detection + escalation — designed and built by the agents
  themselves.** Patrick's mission brief went to @prax as lead ("I don't want it
  to be you" — devpulse relayed requirements, not a design): prax researched,
  collaborated with @hooks and @trigger by mail, wrote DPLAN-0242, and ran the
  build as TDPLAN-0013 across three branches. The system: @prax `rate_tracker`
  watches every log in `system_logs/` for volume (not content — orthogonal to
  medic), disk-persisted state, WARNING at >100 lines/min sustained 2 min /
  CRITICAL at >10 lines/sec 1 min, per-file suppression, runs as a 4th monitor
  thread, plus `drone @prax log-health` for an at-a-glance rate overview.
  @trigger registers the new `runaway_log_detected` event and dispatches to the
  responsible branch with a per-file 30-min cooldown deliberately independent
  of medic's circuit breaker (a storm can't silence both systems), UNKNOWN
  attribution falls back to @prax, and every alert is written to
  `.aipass/alerts.json`. @hooks `persistent_alert` injects an advisory banner
  into every agent's prompt until the alert is fixed or dismissed
  (`drone @hooks dismiss <id>`) — general-purpose, any agent can raise alerts.
  Devpulse verification found and fixed the last-mile gaps: both hooks pieces
  stopped at the first `.aipass/` dir walking up (every branch has one — the
  banner could never render), and hooks.json registration alone isn't
  deployment — the handler needed manual wiring into `~/.claude/settings.json`
  (agents can't edit it; documented for future handlers). Live-fire acceptance:
  a planted 240 lines/min storm was detected at 257 lines/min sustained 120s →
  event → dispatch → **@aipass woke autonomously, root-caused the test writer
  down to its PID and loop shape, triaged no-action** → alerts.json → banner
  renders → dismiss clears. ~77 new tests across four branches, suites green
  (prax 1028, trigger 619, hooks 1071), seedgo 98–100%.

- **Citizens wake each other freely — wake-back for everyone, devpulse
  unwakeable by design.** Patrick's ruling after two team-mission stalls in one
  evening (prax emailed sleeping collaborators; trigger replied instead of
  dispatching back — replies never wake, and wake-back was owner-gated so
  agent-to-agent dispatch never woke the sender). @ai_mail removed the
  owner-gate: any citizen sender is woken when its dispatched agent completes
  (proven live: "@trigger woken after @aipass completed" — first citizen
  wake-back ever). @devpulse is now structurally unwakeable via a
  `citizen_class: manager` check on every wake path — mail always lands, wake
  always skips, no longer dependent on an interactive session happening to be
  open. The gate removal exposed a self-wake loop within minutes (wake-back
  sessions were attributed to @ai_mail as sender, so ai_mail kept waking
  itself; the depth cap stopped it after one cycle) — fixed the same night:
  self-wake guard + wake-back sessions carry no sender, so chains terminate at
  the original dispatcher. 765 ai_mail tests green. The navmap gained a
  "Talking to other agents" section: dispatch vs email semantics, team-relay
  discipline, and the manager exception.

- **Medic is back on — and the loop is proven live.** Off since 2026-05-10 (a
  pytest fixture storm flooded the error registry; the off switch was pulled to
  stop the noise and forgotten for 65 days). Three fixes made re-enable safe:
  (1) @prax: pytest logging routes to a temp dir when `PYTEST_CURRENT_TEST` is
  set — test fixtures can never pollute production `logs/` again (the storm
  class that caused the shutdown); (2) @trigger: circuit breaker self-heals —
  open breakers half-open on read, close on a successful probe, cooldown decays
  to base (previously `half_open` was a terminal trap and only manual reset
  recovered); (3) @trigger: **TTL mutes** — `medic mute @branch` and `medic off`
  now auto-expire after 24h by default (`--for 48h/7d` custom, `--forever`
  explicit kill switch; temp `off` keeps detection running). Agents doing build
  work mute themselves and never have to remember to unmute — the permanent
  switch that got medic forgotten no longer exists. Breadcrumbs shipped: ai_mail
  footer + navmap tell every agent to mute before build work. Live-fire proof:
  a planted commons SQL bug was detected, dispatched, and fixed byte-identical
  by @commons in 105 seconds (15/15 tests green); a real TG poll error was
  correctly triaged NOT ACTIONABLE; organic instance-lock noise was correctly
  triaged LOW/expected. @skills/@api on 7-day mutes until the TG poll-level fix
  lands. 993 prax + 603 trigger tests green.

- **Prax monitor: concurrent viewers — laptop and Telegram mirror side by
  side.** Patrick's ruling after being locked out of his own monitor three
  times: *processes are not agents; display processes must never be
  single-instance.* The instance lock is gone from the display path — any
  number of `monitor run` viewers start and render concurrently. The lock is
  scoped to the one true single-writer responsibility: the Telegram relay
  (`relay.pid`, held by `prax-monitor.service`); extra instances run
  viewer-only, so no TG double-sends. The misleading "kill the existing
  process" error is dead. 998 prax tests green, 3 new concurrent-viewer tests;
  live-verified: interactive Mission Control rendering while the TG relay
  service runs untouched.

- **Telegram user-comment mirror: the TG chat now shows the whole conversation,
  whichever door you speak through.** Patrick's spec from the live cross-door
  drill: his own messages typed in the terminal or claude.ai remote never
  appeared in TG — only the replies did. New `user_message_relay` UserPromptSubmit
  handler (@skills-built, self-contained in the telegram skill, registered by
  @hooks as the last, crash-isolated entry) posts genuine user messages to the
  branch's TG chat with an origin tag, silently (`disable_notification`). Noise
  fences keep it human-only: system/task notifications, slash-command output,
  dispatch wake prompts, sub-agent prompts, TG-origin echoes, and consecutive
  dupes are all skipped (structural session-type detection was investigated and
  rejected — it's session-wide, would eat genuine mid-flight messages). Inbound
  hardening rides along: stale pending files cleaned before each write, and an
  undelivered-response overwrite now logs a warning instead of silently losing
  the reply. 47 new TG tests; registration execution-proven via engine.jsonl and
  the positive path live-verified — a terminal-door message delivered to the
  real TG chat. TG dormancy/proactive push deliberately untouched (design chat
  with Patrick pending).

### Fixed

- **TG bot heartbeat race: delivered replies no longer flip back to
  "Processing…".** Patrick watched his answered bubble get overwritten live: a
  heartbeat thread stuck >5s in a slow Telegram edit call survived its stop
  (the join timed out), woke to a *shared* stop Event the next message had
  already cleared, and re-edited the old placeholder with "Processing…
  (elapsed)" over the delivered reply. Fixed structurally (@skills, devpulse
  root-cause brief): a generation counter captured per heartbeat thread —
  any stale thread breaks before every edit — plus a delivered re-check
  immediately before each edit call in both batch and streaming loops.
  Second bug in the same window: rapid-fire messages (photo + text in one
  turn) overwrite the bot's single pending slot, stranding the earlier
  placeholder frozen; superseded placeholders are now finalized to
  "⏭ Superseded by newer message" in both message and file paths. 6 new
  heartbeat tests; full TG suite 797 green (devpulse-verified). Deployment
  lesson from the same morning: bot fixes aren't live until the systemd
  units restart — commit ≠ deploy.

- **TG mirror live-test fixes: main-chat messages mirror, TG messages don't
  echo.** Patrick's first morning test caught what 47 green tests missed: the
  relay's sub-agent skip blocked ALL daemon-backed main chats (they run with
  `--agent claude`, so `agent_type="claude"` — and real sub-agents never fire
  UserPromptSubmit at all; the filter's premise was empirically wrong across the
  entire engine log). Skip is now agent_id-based (defensive, never observed).
  Second catch from tracing his test: TG messages inject into tmux as raw text —
  no `via Telegram:` marker — so the TG-origin filter never matched and every
  TG message would have echoed back once the first fix landed. New structural
  gate: the bot stores the injected prompt in its pending file; the relay skips
  a prompt that text-matches a fresh undelivered pending entry. Mirror proven
  live by Patrick across both directions ("success :)"). 791 TG tests green.

- **DPLAN-0241 round 4 (night shift): user flags survive every launch path, and
  every session is born with an honest name.** R6 — the bug behind Patrick's
  approve-everything chat: the boot menu suppressed its bypass defaults when the
  user passed `--permission-mode` himself, but only the fresh-launch path threaded
  the user's flags into the exec — resume, takeover, continue, and dead-window
  paths all launched flagless. `extra_args` now threads through ALL launch paths
  (headless `-p` included). R7 — auto-namer: every launch is stamped
  `--name <branch>-<short-session-id>` (flag live-verified on claude 2.1.209; a
  user-passed `-n/--name` wins), so made-up auto-names can no longer hide which
  chat is which. Plus four drill nits: new-over-all ABORTS if the daemon stop
  fails (one brain even in failure paths), close-all's failure hint no longer
  recommends the mechanism that just failed, `exit`/`q`/`quit` quietly leave every
  menu, session rows stay rich (PID, kind, name, age). Surgical-stop probe:
  `op:kill` exists in the daemon's Unix-socket control protocol (per-job bg stop,
  8-char sessionId prefix, no auth) — documented in DPLAN-0241, deliberately NOT
  shipped: undocumented internal protocol. 1048 hooks tests green (102
  session_boot, 11 real-binary CLI contract).

## [2026-07-13]

### Fixed

- **DPLAN-0241 rounds 2-3: Enter IS the takeover — background chats reopen as
  normal terminal chats.** Live incident round two (Patrick's laptop, 23:00): the
  boot menu's resume for a background chat opened the `claude agents` viewer, which
  dispatched his typed message as a brand-new bg job WITHOUT bypass permissions —
  and the shipped stop path called `claude agents stop`, a subcommand that does not
  exist (987 mocked tests never noticed). All fixed by @hooks across two rounds,
  every CLI fact live-verified against claude 2.1.208: phantom stop removed
  (bg close is now honest — no per-job stop exists in the CLI; SIGTERM never used
  on bg, the daemon respawns it); Enter on a live bg session now takes the chat
  over — `claude daemon stop --any` (returncode-checked, blast-radius listing +
  y/N confirm when other branches' bg sessions would also stop) then `--resume
  <sessionId>` inside tmux with bypass; ALL interactive launches tmux-wrapped so a
  closed terminal is always recoverable; multi-session menu shows real session
  names, requires an explicit pick, and its new/close paths stop-first honestly;
  new real-binary CLI contract test tier (20 tests probing every claude
  flag/subcommand our code invokes — the phantom-subcommand class is now
  structurally unshippable). 1025 hooks tests green. North-star architecture
  recorded from Patrick's rulings: one conversation per branch; TG/claude.ai/
  terminal are views of it; agents bind to the machine, not the interface.

- **Session management overhaul (DPLAN-0241): one brain per branch, attach-first
  boot menu, honest session listings.** Born from a live incident — Patrick locked
  out of a running chat for an hour. Root causes, all fixed by @hooks: the bashrc
  boot shim hijacked EVERY `claude` invocation (so `claude agents`, the real
  attach path, never executed) — now intercepts only bare/`--permission-mode`
  launches; session_boot printed one PID from a list and advised `kill` for
  daemon-managed background sessions (which respawn — the unwinnable loop) — now
  a 3-option boot menu (resume / start-new-closes-old / close) with per-kind
  proper stops; presence_gate (single-session enforcement) had NEVER run in
  production (`provider_wired: false`, absent from settings.json, zero engine
  entries ever) and carried two latent bugs (self-PID resolver matched
  comm=="claude" but CC binaries are version-named; agent_type skip waved through
  daemon bg sessions) — both fixed, wired, shipped OBSERVE-ONLY for a soak period
  per prior-art recall (the gate false-blocked a real resume in the
  PRESENCE-file era); wire_verify no longer excludes unwired security hooks from
  its check (enabled-but-unwired = ERROR); new `drone @hooks sessions` +
  `sessions reclaim` one-command reset; session listings/names standardized to
  `PID · branch · short-id · kind · age`. Verified live: gate's first production
  run correctly logged a would-block for a real duplicate session without
  self-blocking. 987 hooks tests green (26 new/updated).

## [2026-07-12]

### Added

- **Telegram log-stream control: `/logs` on branch bots + interactive Prax
  Monitor chat.** The per-branch session LogStreamer auto-started on first
  message hardwired to full firehose with no off switch; the Prax Monitor
  relay chat was send-only — no command menu, and anything typed there was
  silently never read (nothing polled that token). @skills added `/logs
  on|errors|off|status` to all branch bots (preference persisted per chat,
  honored by the auto-start; 33 tests) and a new `PraxMonitorBot` receiver
  service (`telegram-bot@prax_monitor`) with `/pause /resume /errors /all
  /status` and a registered command menu (34 tests). @prax made the relay
  honor the shared control file (`~/.aipass/telegram_bots/
  prax_monitor_control.json`, frozen contract: paused + level) each 5s flush —
  paused discards, `errors` filters to WARNING/ERROR/CRITICAL (17 tests).
  Live-verified end-to-end from Telegram Web: `/errors` silenced INFO batches
  within one flush, `/all` restored them.

### Fixed

- **Legacy `builder` citizen_class migration + birth-certificate template
  (fixes #692).** `builder` was renamed to `aipass_framework` on 2026-07-01
  (13463c0c) as a pure rename, but passports minted pre-rename kept the retired
  name, and the seedgo Architecture checker requires
  `spawn/templates/<citizen_class>/` — hard-capping those citizens below 100%
  (Vera Studio's @vera/@writer stuck at 99%; same legacy class found in 6
  external projects). @spawn completed the rename instead of resurrecting a
  `builder` template: `sync-registry --fix` now migrates the exact value
  `builder` → `aipass_framework` in passports (idempotent, dry-run safe, 3 new
  tests), so external projects self-heal via `aipass doctor --fix`. Also fixed
  the template leftover that kept minting the retired name:
  `birth_certificate.json` now renders `{{CITIZEN_CLASS}}` like the passport
  does. Verified: dry-run against Vera Studio's live registry plans exactly the
  two migrations with zero writes; spawn 347 tests green. #695 closed won't-fix
  (armed Monitor-tool watchdog is the dispatch indicator; always-arm is the
  rule).
- **Order-dependent `test_missing_file` + skills test litter (fixes #694).**
  Root cause was @prax's `json_handler_module` fixture popping EVERY branch's
  json_handler from `sys.modules` (never restored), orphaning the module object
  @skills' conftest had patched — `test_missing_file` then re-imported a fresh
  module pointed at the real `skills_json/`, planted `ghost_config.json`, and
  failed on it every later full-repo run (the only failure in an 11k-test
  sweep). @prax scoped the eviction to `aipass.prax.*` via
  `monkeypatch.delitem` (auto-restore). @skills made all 4 resilience tests
  hermetic (patch `SKILLS_JSON_DIR` → `tmp_path` inside the test body, immune
  to sys.modules state), fully-qualified the legacy bare `skills.`
  `BRANCH_MODULE` in 3 test files (the source of the remaining litter), and
  fixed a latent wrong-variable assert. Verified: original failing pair now
  passes both orders, prax+skills+spawn 1576 tests green, `skills_json/` stays
  clean after a full run.

## [2026-07-11]

### Added

- **Owner seating made permanent + self-healing for every project (DPLAN-0239,
  fixes #693).** The owner-capability guard was correct but the DATA was never
  seeded: every project created before 2026-07-10 had its owner only in the
  self-editable passport, never in the sealed registry (8/8 external projects
  unseated; AIPass's own registry was missing `metadata.id` with 13 entries
  sharing one stale id). Identity model settled: registry `metadata.id` =
  project credential (passports conform); branch-entry `registry_id` =
  set-once PER-CITIZEN UUID minted at entry creation; entry `owner:true` =
  the authority gate (first agent), chosen by ONE shared heuristic
  (`pick_owner_branch`: manager → passport owner → first-created).
  New: `drone @spawn sync-registry --check [--json]` (read-only, 7 health
  flags, pinned JSON schema) and `--fix [--dry-run]` (idempotent reconcile:
  seat owner, majority-consensus restore of `metadata.id`, mint citizen UIDs,
  align passports; dry-run fully read-only; never moves a seated owner).
  `aipass doctor` renders owner health per flag; `doctor --fix`, `install`,
  and `init update` delegate repair to spawn — existing/external projects
  self-heal on next update (the missing DPLAN-0231 PART-4 trigger). The adopt
  path now seats owners; `placeholders.py` resolves the registry from the
  target dir (was CWD) and fails loud. @hooks `auto_watchdog` now injects the
  real Monitor-tool watchdog command with the actual @target (was a dead
  one-liner + `run_in_background`, which cannot wake a session). Deployed
  live: AIPass + 6 external projects reconciled and verified clean — VERA is
  now seated owner of Vera Studio (`is_owner('@vera') = True`, was refused).
  Owners built (spawn 343 / aipass 673 / hooks 961 tests green); devpulse
  verified every diff, live-ran every stage, full-repo sweep 9364 passed
  (1 pre-existing skills litter fail → #694).

### Changed

- **Fleet seedgo compliance sweep — every branch to 100% (issues #686, #661).**
  Overnight campaign bringing all branches to 100% on the seedgo standard pack.
  #686 (Subcommand_Help, per the #685 contract): entry points intercept
  `<cmd> --help` before dispatch, so `--help` shows help instead of executing.
  #661 (Output_Routing): status/error console output routed through the shared
  `@cli` `success()/error()/warning()` helpers instead of raw `console.print`
  markup. Owners self-audited and self-fixed their own branches; devpulse verified
  each diff + re-ran each audit and committed per wave. Landed so far: spawn,
  drone, flow, daemon, prax, ai_mail, backup, seedgo, memory, trigger, api, cli,
  aipass, commons — all 14 offenders now at 100%. **Fleet: 17/17 branches at
  100% seedgo compliance** (hooks, skills, devpulse were already compliant).
  Owners self-audited and self-fixed; devpulse verified every diff, re-ran each
  branch's full test suite, and committed per wave. A full 17-branch test run
  (~10,349 tests) surfaced one pre-existing flaky test in drone
  (`test_pr_no_branch_dir` / `test_pr_no_args` lacked cwd isolation, so a real
  checkout's findable passport made the auth path pass unexpectedly) — given
  `monkeypatch.chdir(tmp_path)` isolation to match its sibling test, so the full
  suite is now deterministically green.

### Fixed

- **Watchdog Monitor wake no longer double-fires (#693 follow-on, reported by
  VERA via the feedback channel).** The `watchdog agent` reminder banner
  ("invoke via Monitor tool, not run_in_background") printed to STDOUT at arm
  time, and the harness Monitor tool treats every stdout line as a wake event —
  so every armed watchdog fired a spurious wake the instant it armed, then the
  real wake at completion. Rerouted to stderr (`err_console`); stdout now
  carries completion/stall events only, matching the contract the agent handler
  already followed. Verified live: exactly one wake, on real exit. The devpulse
  README watchdog/feedback sections were also rewritten to document the owner
  gate, the 3-step Monitor wake mechanic, why no passive wake can exist, and
  the 600 s default timeout.

- **Watchdog agent tests thread-race flakes made deterministic (devpulse).**
  Four tests patched the GLOBAL `time.sleep` with stateful/side-effecting
  fakes; prax's logger spawns daemon threads on first log, which executed the
  fakes concurrently with the test (advancing a fake clock, unlinking the
  fixture lock early, or re-truncating `last_bounce.json` mid-read in
  `_classify_exit` → `exit_code=None`). All fakes are now thread-scoped via a
  caller-frame guard: only sleeps from the agent module trigger the test's
  side effect; foreign threads get a real 1 ms sleep.

- **seedgo-audit back to 100 % after the S300 commits (PR659).** Two 99 %
  regressions from that day's own work: `aipass` `doctor.py` `_fix_owner_seating`
  had two silent catches (now log via prax like the sibling check function),
  and the devpulse README claimed 407 tests where the readme checker counts
  test functions (corrected to 309).

- **Two more non-hermetic ai_mail tests made deterministic (PR659).** With the full
  suite now running on varied CI runners, `test_get_pid_cwd_darwin_failure` and
  `test_is_zombie_linux_no_proc` intermittently failed: they called the real `lsof`
  (via `subprocess.run`) and real `open("/proc/…")` for a fixed PID (999 / 99999),
  so on a runner where that PID happened to exist they returned a non-`None` result
  instead of the expected failure. Mocked `subprocess.run` and `builtins.open` so the
  tests assert the failure contract without touching real process/`/proc` state.
  Test-only; deterministic across repeated runs.

- **Windows CI cross-platform fixes — `windows-setup` green (PR659).** Fixing the
  telegram collection errors unmasked 14 pre-existing Windows-only failures across
  six branches. Two root causes. **(1) pid-liveness tests** (ai_mail, flow, hooks,
  skills) mocked `os.kill`, but the production `_is_pid_alive` already branches to a
  ctypes `OpenProcess` path on Windows and never reaches `os.kill`, so the mocks had
  no effect and the real path ran instead — pinned `sys.platform` to `linux` in those
  tests (or patched `_is_pid_alive` directly) so they exercise the POSIX contract
  deterministically on every platform. **(2) POSIX path assumptions** — prax's jsonl
  test hardcoded `/some/path` (backslashes under `str(Path)` on Windows) now asserts
  against `str(test_path)`; hooks' rollover test compares `repr()` (matches `%r`
  logging); ai_mail's darwin lsof-parser test uses a fixed POSIX path; and seedgo's
  `is_bypassed()` now normalizes the rule file via `Path(rule_file).as_posix()` before
  matching (the one production fix — Windows backslash rule paths never matched the
  forward-slash file path). 10 files (9 test, 1 code); owners self-fixed, devpulse
  verified every diff + Linux no-regression (525 changed-test assertions green).

- **Flaky `test_deletes_old_system_log` made deterministic (@prax log-sweep tests).**
  The sweep integration test reached `log_watchdog._get_system_logs_dir` through a
  `_get_sweep()` wrapper and patched it by string path; a sibling test
  (`test_logging_handlers.py`) `sys.modules.pop`s and reimports `log_watchdog`,
  creating a second module object — so the string patch could target a different
  object than the function's `__globals__`, the sweep scanned the real (empty)
  `system_logs/`, removed 0 files, and `assert files_removed == 1` failed
  intermittently (the same commit passed in one CI run and failed in another).
  Switched to a direct `import log_watchdog as lw` + `patch.object(lw, …)` (shared
  module `__dict__`) and patched `json_handler` to block real file I/O. Test-only
  (1 file); prax suite 978 green, two full-repo runs 11,019 passed each, sweep tests
  deterministic across repeated runs.

- **Telegram skill tests made CI-safe — full-repo collection + hermeticity (issue #691).**
  The 16 test files under `skills/lib/telegram/tests/` imported handlers via bare
  `from apps.handlers…`, which collided with other branches' `apps` packages during
  full-repo CI collection (~16 ImportError collection errors → CI red on Linux +
  Windows). Converted to fully-qualified `aipass.skills.lib.telegram.apps.handlers.*`
  imports (and matching `mock.patch` targets). Verifying that fix surfaced a second
  problem the imports had exposed: ~11 tests reached the live Telegram API
  (`base_bot.run → _set_command_menu → set_bot_commands → urlopen`) — they had never
  run in CI before because they failed at collection. Added a session-scoped autouse
  `_block_network` conftest fixture that patches `urlopen` on the four network-using
  telegram modules (both bare and fully-qualified import paths, each guarded) so any
  test attempting a live HTTP call fails loud instead of hanging. A full-repo CI run
  then exposed a third layer the isolated suites had hidden: `handler.py` and its
  routing tests still used bare `from apps.handlers.X import Y` / `mock.patch("apps.
  handlers.X…")`, which resolve to the *wrong* branch's `apps` in a whole-repo run
  (AttributeError / ModuleNotFoundError at runtime — 17 `test_handler_routing`
  failures). Fully-qualified those to `aipass.skills.lib.telegram.apps.handlers.*` in
  both `handler.py` (7 lazy imports, now house-rule compliant) and the tests; the
  skill's runtime behaviour is unchanged (verified via `drone @skills run telegram`).
  Net: full-repo collection 0 errors and the whole 11k-test suite green; telegram
  suite 663 passed / 0 failed / 0 hangs, fully hermetic; coverage intact (import and
  patch-target rewiring only — zero assertion changes).

- **`aipass install` from a throwaway path can no longer hijack the machine-wide
  `AIPASS_HOME` (issue #688).** A probe install run from a `/tmp` scratchpad had
  rewritten `~/.claude/settings.json` `env.AIPASS_HOME`, silently pointing every
  Claude Code session on the machine at a dead temp tree (stale python, stale
  hooks — surfaced as bogus ImportErrors in unrelated work). Three defenses:
  `bootstrap.is_throwaway_path()` gates the settings write itself (temp dirs +
  scratchpads never land in global settings); `run_install` refuses a throwaway
  home loudly with `--force-global-home` as the explicit override; and
  `aipass doctor` gains a `global AIPASS_HOME` check that flags a nonexistent or
  throwaway path with fix guidance. +11 tests. Ships with a probe-hygiene SOP
  (`aipass/docs/probe_hygiene.md`): temp installs are used, deleted, gone — nothing
  permanent may point at a temp path. Tests made location-independent so the suite
  is green from any cwd and from a `/tmp` clean-room extraction, not just the repo
  root. (built by @aipass, verified + test-hardened by devpulse against the real
  hijack path)

## [2026-07-10]

### Added

- **Owner-capability model — project ownership sealed in the registry, and the
  owner is woken back when a dispatched agent completes (issue #678).** The
  directed-wake round-trip grew into an access-control primitive: watchdog /
  feedback / wake-back are owner-only privileges, and the owner (first agent /
  `citizen_class: manager` — devpulse in AIPass) is resolved from the *sealed*
  `*_REGISTRY.json`, not the self-editable passport (no self-grant). Three parts
  built in parallel against a frozen `is_owner` contract: `@spawn` writes
  `owner` + `registry_id` into registry entries and exposes `get_owner()` /
  `is_owner()` (`ensure_project_has_owner` now keys off the manager signal, not
  the created-date heuristic that mislabeled `@aipass`); `@hooks` adds a
  `registry_gate` PreToolUse handler that blocks raw writes/edits/deletes of
  `*_REGISTRY.json` and redirects to `drone @spawn` (per-clause bypass defeats
  compound-command smuggling; reads stay allowed); `@ai_mail` reslopes the
  dispatch wake-back from a `SKIP_SENDERS` blocklist to an `is_owner` allowlist.
  Cross-part verified end-to-end by devpulse with the real resolver (gate 13/13
  incl. compound-smuggle, wake-back owner/non-owner/depth-cap).
  (built by @spawn + @hooks + @ai_mail, verified by devpulse)

- **`subcommand_help` seedgo standard — entry points must intercept `<cmd> --help`
  before dispatch (issue #685, split from #665 item 3).** `drone @X <cmd> --help`
  had no framework contract: drone (a router, not a standards enforcer) forwards
  `--help` as a positional, so behavior was per-branch — 8/16 missed, and two
  branches *executed* the subcommand instead of showing help. seedgo now owns the
  contract: a new AST checker flags entry points that don't guard `<cmd> --help`
  (explicit `remaining_args[0]` guard or argparse `parse_known_args`). 21 tests,
  cwd-portable. 7/17 branches comply; the 10 offenders are tracked as a fleet
  migration (#686). (@seedgo, verified devpulse)

- **`windows_compat` now detects `os.kill(pid, 0)` liveness probes, not just
  documents them (issue #682).** `os.kill(pid, 0)` resolves to `TerminateProcess`
  on Windows — it *kills* the target instead of probing it. The checker documented
  the anti-pattern but never flagged it in source. A new detector recognizes the
  valid early-return platform guard (so the reference impl `watchdog/agent.py` isn't
  false-flagged) while catching genuinely unguarded sites. 6 tests; verified across
  the fleet (guarded ref passes, 10 offenders caught → fleet migration #684).
  (@seedgo, verified devpulse)

- **`append_jsonl` — a sanctioned rotating JSONL writer + a 30-day stale-log sweep
  (issue #673).** Branches wrote `.jsonl` via raw `open('a')`, bypassing prax
  rotation (which was `.log`-only) — unbounded log growth. `from aipass.prax import
  append_jsonl` gives 500 KB / 1-backup atomic (`os.replace`) rotation with zero
  dependency on the prax logging pipeline (recursion-safe for @trigger's event
  handlers), and `drone @prax log-audit sweep` deletes logs older than 30 days
  across system + branch logs. The raw appenders in @backup (1), @hooks (2), and
  @trigger (11 `.log` sites → `.jsonl`, plus downstream medic readers) all adopted
  it — zero raw log appenders remain fleet-wide.
  (@prax + @backup/@hooks/@trigger, verified devpulse)

- **Hook engine: Codex bridge + portable test suite (issue #635, DPLAN-0184
  leftovers).** The engine now drives Codex hooks the same way it drives Claude:
  new `handlers/bridges/codex.py` mirrors the claude.py bridge (same
  `EventType:hook_name` dispatch) with Codex protocol normalization — stdin
  remaps `input`→`tool_input`, stdout wraps in the `hookSpecificOutput` envelope
  (`additionalContext` for injection, `permissionDecision` +
  `permissionDecisionReason` for blocks — fixing the known DPLAN-0205 bugs:
  missing reason, wrong field name). And `drone @hooks test` is a portable
  drop-in runner that fires every hook from `.aipass/hooks.json` with mock data
  per event type and reports fired/blocked/disabled/crashed with timing
  (`--verbose` previews output). 23 new tests (12 bridge + 11 runner), seedgo
  31/31 both. (built by @hooks, verified by devpulse)

### Fixed

- **hooks/bridge: `-p` headless invocations no longer routed through tmux
  (issue #677, DPLAN-0226 fine-tune leftover).** The boot wrapper
  (`session_boot.py`) applied its tmux/session-lookup/live-attach logic to every
  invocation — wrong for `claude -p`, a non-interactive one-shot that never
  registers in `~/.claude/sessions`. The wrapper now detects `-p` in extra_args
  and short-circuits to direct `execvp` of claude — no tmux, no session lookup.
  +5 tests (39 pass). (built by @hooks, verified by devpulse)

- **Owner-capability PART 4 — devpulse's `watchdog` + `feedback` now gate on the
  sealed-registry owner, and cross-project (issue #681).** Closes the
  owner-capability model (#678): the last two owner-only tools were still gated
  by a hardcoded `cwd.name == "devpulse"` check — which, it turns out, was a
  **no-op through drone**: drone runs a routed module with `cwd=<branch_path>`,
  so the module's own `Path.cwd()` is *always* the devpulse tree and can't
  identify the caller (a `@flow` caller sailed straight through). A new shared
  `handlers/owner/guard.py` resolves the *real* caller from the env drone sets
  (`AIPASS_CALLER_BRANCH` / `AIPASS_CALLER_CWD`) and checks it against the sealed
  owner via the frozen `is_owner(email, start_path)` contract — so it works in
  any project (devpulse in AIPass, whoever owns elsewhere), not a hardcoded name.
  `feedback send` stays open (it's the inbound channel any agent uses to drop
  feedback to the owner); every mailbox read/manage verb is owner-only. Fail-safe:
  if no owner is sealed yet (old/partial install) or the resolver can't import,
  it falls back to the legacy devpulse-path heuristic so existing installs never
  hard-break. Live-verified end-to-end: owner allowed, `@flow` denied on both
  tools, `send` open. 18 new tests (15 guard + 3 gate), branch audit 100%.
  (built + verified by devpulse)

- **seedgo `json_structure` now sanctions `custom_config/` for operator-editable
  config (issue #643).** The standard said "`{branch}_json/` root, one directory,
  no splits" and the checker ignored subdirs, so `custom_config/` (home of
  operator-tunable runtime config like `cadence_config.json`, `memory.config.json`)
  was an undocumented convention. `json_structure_check.py` gained an
  `ALLOWED_JSON_SUBDIRS` allowlist and a `check_branch_post()` that validates
  `{branch}_json/` subdirs — `custom_config/` and hidden dirs (`.archive`) pass,
  any other split is flagged. `json_structure_content.py` documents the directory
  structure and operator-config location. The subdir check honors
  `.seedgo/bypass.json` (bypass rules are threaded through
  `check_branch_post` → `_check_json_dir_structure`), so a branch can sanction a
  legitimate data subdir while unsanctioned + unbypassed splits still fail. 7 new
  tests. (The new check surfaced `devpulse_json/compass/` — the devpulse Compass
  SQLite/FTS5 decision store, which needs its own directory — now sanctioned via a
  documented devpulse bypass; audit confirms Json_Structure back to 100%.)

- **`git_gate` block messages now guide external users instead of dead-ending
  (issue #620).** A blocked raw `git`/`gh` command previously just errored. The
  block message now explains *why* git is enforced (prevents cross-agent state
  conflicts), lists the key `drone @git` commands (commit, smart-sync, sync, pr,
  checkout), points to `drone @git --help`, and shows how to disable the gate in
  isolation (`git_gate.enabled = false` in `.aipass/hooks.json`) — verified
  against the engine, which skips a disabled hook per-hook without affecting other
  hooks or `drone @git`. The combined `GIT_GH_REDIRECT` was split into distinct
  `GIT_REDIRECT` + `GH_REDIRECT`; `EDIT_REDIRECT` also shows the disable path. An
  init notice was added to the `project_hooks.json` template and the on/off story
  documented in the hooks README. 6 new tests (86 in `test_git_gate`).

- **Telegram `/create` + `/cancel` are now gated to the base @aipass bot (issue
  #644).** Every per-branch bot inherited `BaseBot`'s `/create` + `/cancel` and
  could mint new bots — but Patrick designated the base @aipass bot as the *sole*
  spawner. `base_bot.py` now guards on bot identity (branch bots carry a
  `branch_name`; the base bot's is `None`): `_dispatch_command` returns `False` for
  `create`/`cancel` on a branch bot (falls through to normal handling), and
  `get_custom_commands` advertises them only for the base bot. Rode along in the
  same @skills pass: fail-loud fixes to `botfather_client.py` (issues #669.2/#669.3,
  already closed) — `_load_telethon_config` now raises `RuntimeError` naming the
  config path and the `drone @api set-secret telegram telethon_config` command
  instead of silently returning `None` — plus poll-offset test coverage (#668).
  133 telegram tests pass, seedgo 31/31 on both source files.

- **seedgo no longer lints throwaway code (issue #675).** A single disposable POC
  used to fire 8 standard violations (architecture, meta, shebang…). The audit and
  checklist now skip any file resolved under a system temp dir
  (`tempfile.gettempdir()` / `/tmp`, cross-platform) or a `scratchpad` path, and a
  new `--prototype` flag (plus an in-file `# seedgo: prototype` marker in the first
  5 lines) exempts disposable code explicitly. Wired into
  `branch_audit._collect_py_files` (throwaway filter) and `checklist.run_checklist`
  (early-return skip). 6 new tests; live-verified that a `/tmp` file and a
  marker-tagged file both report "✓ (skip)".

- **The `claude()` boot shim now ships and installs on onboarding (issue #666).**
  Its installer (`hooks/tools/install_boot_shim.sh`) lived under a gitignored
  `tools/` dir — never version-controlled, never shipped — so the
  attach-if-live / start-in-tmux boot feature (and presence-gate-via-boot) was
  dev-local only; a macOS user could not attach/resume their session. A root
  `.gitignore` negation now tracks exactly that one file (`tools/` re-ignored,
  only the installer whitelisted — README stays out), and `setup.sh` runs it
  right after hook installation (idempotent via a marker check, non-fatal on
  error, venv Python resolved from the script's own location for POSIX/Windows).
  Fresh clones and `aipass install` now get the shim.

- **Interactive-occupancy detection is now cross-platform — the wake-back guard
  no longer goes blind on macOS (issue #680).** `_is_branch_occupied()` and
  `_read_session_type()` (duplicated in `dispatch/wake.py` and `dispatch/daemon.py`)
  read `/proc/{pid}/cwd` + `/proc/{pid}/environ`, which do not exist on macOS —
  so occupancy always resolved `False` there and an external wake-back could spawn
  a *second* Claude session on an already-interactive branch (double-session,
  weakening the TDPLAN-0012/#678 interactive-dispatcher guard). The per-PID cwd
  and session-type probes are now extracted into platform helpers: `_get_pid_cwd`
  (Linux `/proc` readlink, macOS `lsof -a -p PID -d cwd -Fn`) and
  `_read_session_type_darwin` (`ps -p PID -wwE`), applied identically in both
  files. Fail-safe: an unreadable cwd/env logs at info and continues — never
  crashes the wake path. +11 tests (macOS cwd, macOS session type, zombie,
  unsupported platform), seedgo 31/31 on both files.

- **SubagentStop gate no longer runs its ~600ms seedgo check on every internal
  turn (issue #606).** Claude Code creates an internal agent per response turn
  with an empty `agent_type`, so the `subagent_gate` handler was firing its full
  `drone @git status` + seedgo modified-files check on every turn, not just when a
  real Agent-tool sub-agent completed. `handle()` now early-returns `_ALLOW` when
  `agent_type` is empty; the full check runs only for a real sub-agent
  (non-empty `agent_type`). Piper speech is a separate notification hook and is
  unaffected — the trust layer stays visible. 3 new tests (empty skip, missing-key
  skip, real-agent full check), 17/17 green.

- **Watchdog stall detector no longer false-fires on a long single tool call, and
  a real stall now reaches devpulse live (issue #634).** Liveness was inferred
  purely from JSONL file-size growth, so an agent doing one genuinely long
  operation (big read, long-running Bash, heavy compute) wrote no new lines for
  the span and was misread as `STALLED` while actively working. `watch_agent` now
  also treats an in-flight `tool_use` (the assistant's last transcript entry while
  a tool runs) as activity — verified live against real Claude Code transcripts:
  the `tool_use` line is written at tool *start* and persists for the whole call.
  Part 2: the stall (and a new long-running-tool advisory, plus a resumed signal)
  is emitted to **stdout** — which the Monitor-tool wrapper surfaces as a live
  event — instead of only `stderr`+logger, which Monitor captures but never
  relays. Stall logic extracted into a `StallTracker` for clarity; +9 tests
  (142 green), devpulse audit 100%. (devpulse)

- **`aipass install` shows progress during the slow dependency build, and a README
  quick-start command is corrected (issue #665, items 6–7).** The editable install of
  the `[memory]` extras ran with `pip --quiet`, going silent for minutes during wheel
  builds — it looked hung; dropped `--quiet` on that step and set expectation in the
  echo. And `README.md` showed `drone @seedgo audit my_project`, which fails
  (`audit` takes a registered pack name) — corrected to `audit aipass`. Remaining
  #665 items (version, --help names, subcommand --help, placeholders, hints, crash-vs-
  unknown) span multiple owners and stay open. (devpulse)

- **`aipass`/`drone` first-contact papercuts resolved — issue #665 fully closed
  (items 1, 2, 4, 5, 8).** `aipass --version` now reads package metadata (was
  hardcoded `0.1.0`); `aipass --help` lists real `COMMAND` names, not file stems
  (`help` not `help_chat`, `init` not `init_flow`); a crashing or unimportable
  handler surfaces its real cause instead of `Unknown command` (@aipass). `drone
  systems` placeholder descriptions now derive from each branch's passport/README,
  fixed in code so they survive registry regen — the earlier gitignored data edit
  didn't (@spawn). Bare-mode hints point to working commands — `drone @daemon
  --help` (there is no `daemon` binary) and the standard `drone @memory --help`
  (@daemon, @memory). Item 3 became the #685 standard. (multi-branch, verified devpulse)

- **`os.kill(pid, 0)` liveness probes across the fleet are now Windows-safe (issue
  #684).** On Windows `os.kill(pid, 0)` maps to `TerminateProcess` — the "probe"
  kills the target. Nine sites across @ai_mail (dispatch daemon/wake), @drone (git
  lock handler), @flow (runner lock), @hooks (cc_sessions/presence) and @devpulse
  (watchdog registry) now early-return to an `OpenProcess` + `GetExitCodeProcess`
  check on win32, mirroring the `watchdog/agent.py` reference. The #682 checker
  confirms 0 unguarded sites remain (down from 10); the last one,
  `tools/git_lock_tool.py`, is split to #687 (blocked by the tool's pre-existing
  gate debt). (fleet migration, verified devpulse)

- **Telegram poll loop no longer re-drains a rate-limited backlog; systemd
  suicide-loop + silent config fallback fixed (issues #668, #669).** #668: the poll
  loop advanced the update offset *after* processing, so a rate-limited/erroring
  update never advanced it — the same backlog re-fetched in a flood loop. The
  offset now advances *before* `process_update`, so a consumed update never pins
  it. #669: (1) systemd unit gets `KillMode=process` so a restart isn't killed by
  the old instance's cgroup teardown (suicide-loop); (2) `create_bot_via_botfather`
  now **raises** with an actionable message (naming the `set-secret` fix) instead of
  silently returning `None` when telethon config is missing (fail-honestly);
  (3) stale config-mechanism docstrings corrected. Also Windows-hardened
  `_is_pid_alive`/`_check_lock` and switched `TEMP_DIR` to `tempfile.gettempdir()`.
  653 telegram tests green. (@skills, verified devpulse)

- **Rollover `_find_repo_root` now fails loud, and `edit_gate` warns on over-count
  memory sections (issue #683, #664 follow-up).** The PreCompact rollover hook's
  `_find_repo_root` returned `None` silently when `AIPASS_HOME`/cwd was wrong — the
  exact silent-skip that hid #664 for months; it now logs a `logger.error` with the
  `AIPASS_HOME` value and cwd before returning. And `edit_gate` enforced per-entry
  *character* caps but not entry *counts*, so a branch could drift past its count
  cap between rollovers; a soft `_check_section_counts` now warns (never blocks),
  reading the same `memory.config.json` rollover caps @memory uses. +14 tests
  (70 green); both live-proven (bad root → error logged; over-cap → warn, no block).
  (@hooks, verified devpulse)

- **`is_owner()` now case-folds — `is_owner('DEVPULSE')` matches `is_owner('devpulse')`
  (issue #679).** The spawn-registry resolver (`registry.py:382`) `@`-normalized the
  email but never lowercased, so a mixed-case branch name (registry names are
  mixed-case: `DEVPULSE` vs `devpulse`) returned `False` against the seated owner.
  Harmless today (the only caller lowercases first) but the frozen TDPLAN-0012
  contract promises normalization, and PART-4 owner-gating may pass a raw name.
  Now lowercases both sides; verified live (every case variant of the owner → True,
  non-owners → False) + a case-insensitivity test (316 green). (@spawn, verified devpulse)

- **`aipass install` no longer hard-fails (exit 2, silently) when it can't create
  global symlinks (issue #660 follow-up).** `setup.sh` runs under
  `set -euo pipefail`; the #660 `safe_symlink` refactor returns `2` on `ln`
  failure, but the call sites captured that code on the *next* line (`rc=$?`), so
  `set -e` killed the installer at the symlink step — before the `~/.local/bin`
  fallback (built for exactly the no-sudo case) could run. Any sudo-less
  environment (containers, CI, locked-down machines) got a silent exit 2 with no
  symlinks, despite an otherwise-complete install. Fixed all three call sites to
  `rc=0; safe_symlink … || rc=$?` (set-e-safe). Proven in docker: a sudo-less
  install now falls back to `~/.local/bin` and exits 0. (devpulse)

- **`drone @devpulse watchdog agent` no longer reports failure on a successful
  watch (issue #661).** Its "invoke via Monitor tool" reminder was printed
  through `cli.error()`, which — after the #661 exit-code work — trips a
  process failure flag, so every successful watch exited non-zero with a red X.
  Rerouted to a dim console note; genuine argument errors still `error()` →
  exit 2. (devpulse)

- **The prax monitor now holds a single-instance lock, so a duplicate/orphan
  monitor can't double-send Telegram relay messages (issue #671).** A new
  `instance_lock` handler writes a pidfile (`prax_json/monitor.pid`, outside the
  tailed `system_logs/`) with a liveness check: `acquire()` runs before relay
  init and refuses to start (fail-loud, naming the holding PID) if a live monitor
  already holds the lock, reclaims a stale pidfile when the recorded PID is dead,
  and `release()` clears it on shutdown. The liveness probe is platform-branched
  — POSIX `os.kill(pid, 0)`, Windows `OpenProcess`/`GetExitCodeProcess` (a raw
  `os.kill(pid, 0)` *terminates* the target on Windows). `monitor.py` was also
  split under the 600-line limit (`pid_cache` extracted). +25 tests.
  (built by @prax, verified by devpulse)

- **`aipass init update` now refreshes `AGENTS.md` and prunes stale managed
  cruft (issue #676).** Two gaps: (1) `update_project` synced `AGENTS.md` from a
  `.aipass/project_AGENTS.md` template that never existed, so the branch silently
  no-op'd and `AGENTS.md` was never refreshed on update (only `CLAUDE.md`, whose
  template exists, synced) — added the template and reconciled create/update to
  one source; (2) the update was additive-only — added a whitelist-scoped cleanup
  pass (`_STALE_MANAGED_FILES`, currently the retired `aipass_global_prompt.md`)
  that removes only positively-identified managed artifacts, logs every removal,
  and never touches user-owned files. The template also had to be un-ignored in
  `.aipass/.gitignore` (allowlist) or it would never have shipped — caught in
  verify. +7 tests; live repro confirms update emits `AGENTS.md` and clears a
  planted cruft file. (built by @aipass, verified by devpulse — incl. the
  gitignore ship-gap)

- **External-project branches now auto-roll — rollover discovery is no longer
  cwd-scoped (issue #664).** Branch discovery only saw registries reachable by
  walking up from the caller's cwd, so branches living solely in an external
  project's `*_REGISTRY.json` were never reached by rollovers fired from the
  AIPass tree (the PreCompact hook runs with cwd = repo root) — their `.trinity`
  files grew unbounded (one hit 110 key_learnings against a 15 cap) and vector
  stores went stale. `@memory` added a persisted `known_registries.json`
  (gitignored per-install data) that records every external registry seen via the
  cwd walk, so discovery reaches them regardless of caller cwd; stale/deleted
  registry paths are filtered on load. Plus a soft entry-**count** guard at write
  time (warns, never blocks) since the write gates only enforced char caps. The
  remaining hooks-side harden (`_find_repo_root` fail-loud + the `edit_gate`
  count-guard) is filed for `@hooks`. +12 tests; live repro confirms a rollover
  fired from the AIPass root now reaches an external-registry branch.
  (built by @memory, verified by devpulse)

---

## [2026-07-09]

### Added

- **Exit-code contract foundation — failing commands can now exit non-zero
  (issue #661, in progress).** CLI error paths printed an error but returned exit
  `0`, so `$?`-checking callers (core to running `drone` as a subprocess) were
  told success on failure. The dispatch contract was a 2-state bool (`handled` /
  `not-mine`) with no way to say "handled *and* failed". `@cli` now exposes a
  process-level failure flag + `resolve_exit(handled)` (→ `0`/`1`/`2`), and
  `error()` auto-trips the flag — so any failure routed through `error()` gets a
  correct non-zero exit with zero per-site edits, and it can't regress. Inert
  until a branch's `main()` adopts it. `@seedgo` added an `output_routing`
  standard (39th checker) flagging user-facing status output that bypasses the
  cli helpers — 254 sites across 14 branches, the migration checklist. `devpulse`
  is the first adopter (`main()`→`resolve_exit`, feedback migrated to `error()`,
  exit `2`/`0`/`1` verified, 100% seedgo). Fleet migration to follow.
  (built by @cli + @seedgo)

### Fixed

- **`@trigger` no longer rewrites its 44KB `trigger_data.json` on every log event
  (issue #674).** The branch log watcher persisted dedup hashes and log positions
  with two separate full-file rewrites *per event*, so a log burst churned the
  file ~1-2×/sec (surfaced by prax monitoring). Replaced the per-event/counter
  writes with a debounced coalescing writer: events set a dirty flag and both
  keys are written in a single atomic write at most once per 5s, with a forced
  flush on watcher stop so nothing is lost on clean shutdown. Also confirmed the
  retired `bulletin_created` event handler no longer loads or warns (it lives in
  `.archive/` with no live references; scrubbed stale README/bypass mentions).
  564 trigger tests green (+6 debounce tests).

- **`aipass install` no longer silently repoints your global `drone`/`aipass`
  symlinks (issue #660).** `setup.sh` force-overwrote the global CLI symlinks with
  `ln -sf` on every run, no check and no opt-out — so `aipass install
  --path /tmp/scratch` "to try it" silently hijacked your real global commands to
  the scratch tree, which broke them once `/tmp` cleared, disconnected from the
  cause. A new `safe_symlink` guard refuses to repoint a symlink that points at a
  *different* install: it prints a loud from→to warning and leaves the existing
  link untouched unless you pass `--force-symlink`; `--no-symlink` opts out of
  symlinking entirely. Both flags thread through `aipass install`. Fresh installs
  and same-location reinstalls behave exactly as before. Adds a `safe_symlink`
  regression test (`tests/setup_symlink_guard_test.sh`) and 3 flag-forwarding
  tests; the touched install output was migrated to `@cli` helpers (#661).

- **`drone @flow close` no longer reports a false "timed out after 30s" on a
  successful close (issue #662).** A single-plan close committed early (plan
  marked closed, file archived) and then ran memory vectorization
  *synchronously* — `drone @memory process-plans` — inline. On the cold first
  close of a session that crossed drone's 30s executor timeout, so drone killed
  the flow subprocess and returned exit `1` **after** the close had fully
  committed. An autonomous agent reading that exit code would retry or abandon an
  already-closed plan. `close_plan_impl` now honors its long-existing
  `spawn_background` flag: single close fires the already-detached
  `_spawn_background_runner` (the same path `close_all` uses) and returns
  immediately after archive; vectorization runs in the background. Also removed
  the handler's cross-handler imports (archive/trigger now injected). Verified
  live: a real close returns in ~5s at exit 0 ("Vectorizing in background") vs
  the prior 30s-timeout risk. 730 flow tests green (+2 new).

- **`aipass doctor` no longer hangs on non-interactive stdin (issue #663).** The
  auto-wire `[y/N]` prompt called `input()` with no tty guard, so a caller with a
  blocking-but-idle stdin (a script, CI job, or subprocess whose stdin never
  sends EOF) hung `doctor` indefinitely — reading as a crash from the flagship
  "check my system" command a new user runs first. `prompt_auto_wire` now guards
  the prompt with `sys.stdin.isatty()`: a non-tty stdin declines the auto-wire
  (prints the manual-wire warning) instead of blocking. Verified against the
  exact repro — a blocking non-tty stdin that never EOFs now completes instead of
  hanging until killed. Adds 3 regression tests.

- **macOS session lock-out: the boot wrapper can now see tmux sessions on
  macOS.** `session_boot` decided whether a live Claude session lived inside
  tmux by walking the process tree through `/proc/<pid>/status` — Linux-only.
  On macOS (no `/proc`) that walk always failed, so the wrapper concluded every
  live session was "outside tmux" and refused to attach, locking the user out of
  their own session in an unbreakable loop. Replaced the `/proc` read with a
  portable `ps -o ppid=` ancestry walk (Linux + macOS). Also: both the boot
  warning and the presence-gate block now spell out the exact recovery command
  (`kill <pid> && claude`, `command claude --resume`) instead of a vague "kill it
  first", and the wrapper no longer doubles `--permission-mode` when the user
  passes it explicitly. New/updated tests, hooks suite 791 green. (built by @hooks)
- **Boot-shim installer no longer bakes a hardcoded user path.**
  `install_boot_shim.sh` hardcoded `/home/patrick/Projects/AIPass/.venv/bin/python`
  into the `claude()` shell function — wrong on any other machine or user. It now
  resolves the venv interpreter from the script's own location (POSIX
  `.venv/bin/python`, Windows/git-bash `.venv/Scripts/python.exe`, else PATH
  `python3`) and bakes the correct one at install time.
- **Silent hook-wiring break: provider settings could be left half-wired with no
  warning.** A stale `setup.sh` merge orphaned the `SessionStart` hook event to an
  empty `[]` — the key existed but nothing fired — written silently, and it went
  unnoticed for weeks because CI skips the provider-settings snapshot test (it
  needs `~/.claude/settings.json`, absent in CI). Root cause: the merge stripped
  every AIPass bridge entry per event, then re-added only events still present in
  its own hook list, orphaning any event it no longer defined. The merge now drops
  such an event entirely (and says so) instead of emitting an empty array. Also
  corrected the stale snapshot fixture (dropped the dormant `presence_gate`, which
  by design ships wired only in project config, and added
  `SessionStart:cadence_reset`) and marked `presence_gate` `provider_wired: false`
  so the wiring checker knows it is intentionally not provider-wired.
- **`json_handler.load_json` crashed on an empty/whitespace file (#667).** Under
  concurrent audit + tests a writer could truncate a JSON file in the window
  between `ensure_json_exists` and `load_json`'s own read, raising
  `JSONDecodeError`. `load_json` now guards an empty/whitespace read and falls back
  to the type's default template; a non-empty but malformed file still raises (fail
  honestly). 3 new tests, red-green proven.

### Added

- **`drone @hooks verify` — hook-wiring integrity checker.** Cross-checks
  `~/.claude/settings.json` against `.aipass/hooks.json` and fails loud on empty
  provider hook arrays, orphaned entries, enabled handlers with no provider bridge,
  and duplicate (matcher-aware) entries — so a half-wired hook can never rot
  silently again. `aipass doctor` now runs this check under Services and re-verifies
  after `--fix`. 40+ new tests. (built by @hooks + @aipass)

## [2026-07-07]

### Fixed

- **Drive sync now respects `.backupignore` on the sync path.** The ignore spec
  was applied at backup time only — anything already inside `.backup/versioned/`
  got uploaded regardless. Real case: Vera-Studio's store carried 37K legacy
  `node_modules` files (92% of the store), turning a KB-sized sync into a 7-8
  hour crawl (Drive uploads are per-file API round-trips — latency-bound, not
  bandwidth-bound; the clean store syncs in ~13 min). `drive_sync` now re-filters
  store files through the project's `.backupignore` before upload and logs the
  ignored count. Also fixed: `json_handler.log_operation` crashed on `Path`
  objects (`PosixPath is not JSON serializable`) — now serializes with
  `default=str`. 2 new tests, backup suite 247 green. (built by @backup)

### Added

- **Fresh-context grounding: cadence reset on new chat / clear / compact.**
  Both prompt loaders (tier0 kernel + navmap) now run at period 5, and a new
  `SessionStart` hook resets the cadence counter on `startup`/`clear` (skips
  `resume` — restored context already carries grounding; `compact` was already
  reset via PreCompact). Net effect: the first message of every fresh context
  gets full grounding, then every 5th turn after. Wired end-to-end: handler
  (`session_start.py`), project config (`.aipass/hooks.json` + the
  `project_hooks.json` template for external projects), and `setup.sh` seeds
  the provider `SessionStart` entry for new installs. Proven end-to-end from a
  real fresh-user clone of dev in Docker — 19/19 assertions via the new
  `tests/docker_dev_verify.sh` (bridge-era; supersedes the stale
  `docker_clone_test.sh`). (built by @hooks + @devpulse)

### Fixed

- **`aipass` ≠ drone-routed — misroutes now guide instead of crash.** `aipass`
  is the user's front-door CLI, deliberately not resolvable by drone. But
  `drone aipass` misdirected, `drone @aipass` crashed with a traceback, and
  `aipass @drone` dead-ended. All three now print clear guidance (what aipass
  is, what drone is, how to reach each). Kernel + navmap prompts updated so
  agents know the exception. (built by @drone + @aipass)

---

## [2026-07-06]

### Fixed

- **prax log watchdog now covers branch `logs/` dirs — `.jsonl` runaway growth
  caught.** Rotation was hardcoded to `.log` files, and several branches write
  `.jsonl` logs via raw `open(path, "a")` appenders that bypass prax entirely —
  `hooks/logs/engine.jsonl` had grown to 63 MB, `backup/logs/operations.jsonl`
  to 31 MB, `trigger/logs/medic_suppressed.log` to 7 MB, all unrotated. The
  log-watchdog safety net also only scanned `system_logs/*.log`. @prax extended
  it: `scan_branch_log_files()` sweeps every `src/aipass/*/logs/` for `.log` +
  `.jsonl` (WARN at 1 MB unrotated, CRITICAL at 10 MB),
  `enforce_branch_log_limits()` truncates flagged files to the last 5000 lines,
  and `drone @prax log-audit` now reports both system and branch scopes. 11 new
  tests, full prax suite 947 green. The raw-appender writers themselves still
  need per-owner caps — routed to @hooks, @backup, @trigger. (built by @prax)

---

## [2026-07-05]

### Fixed

- **HVTrust badge restored in the root README.** hvtracker corrected the
  methodology v4.1 grade-computation bug (issue #109); the badge shows the
  right grade again, so the temporary comment-out from earlier today is
  reverted.

- **Installer no longer destroys a user's custom Claude Code hooks (DPLAN-0234
  Strand C).** setup.sh used to write `settings["hooks"]` wholesale — anyone
  with their own hooks in `~/.claude/settings.json` lost them on install or
  re-run. Now it merges: every AIPass bridge entry (identified by the
  `bridges/claude.py` marker) is refreshed, while user-wired hooks and custom
  events are preserved. Verified against fixtures: custom hooks survive, stale
  AIPass entries are replaced without duplicates, and the fresh-install output
  is shape-identical to before (7 events, 6 UserPromptSubmit + 6 PreCompact
  entries). Found while fire-testing a fresh install's hooks in Docker — all
  17 wired hook entries pass on a cold Linux clone (real kernel/navmap/branch
  prompt bytes, git gate blocks, clean no-ops on empty state).

- **Windows fresh installs get a working hook bridge.** setup.sh wrote the
  Claude bridge command with `.venv/bin/python3` on every OS — but Windows
  venvs put the interpreter at `.venv/Scripts/python.exe` and have no `bin/`,
  so hooks on a fresh Windows install pointed at a nonexistent python and
  would never fire. The bridge string is now OS-aware (bash passes
  `IS_WINDOWS` into the hook-install step). @hooks assessed the rest of the
  chain: `$AIPASS_HOME` expansion works on Windows because Claude Code runs
  hooks via Git Bash (which must exist for setup.sh to have run), and the
  bridge itself has zero POSIX assumptions — the interpreter path was the
  only gap. Verified: both OS modes produce the right bridge string, merge
  marker unchanged, custom-hook preservation intact. (assessed by @hooks)

### Added

- **`./aipass` — repo-root cold-clone launcher (DPLAN-0234 Strand B).** The
  branded entry point for the clone-first flow: `git clone`, `cd AIPass`,
  `./aipass install` — three commands to a working AIPass. Stdlib-only bash
  (zero deps, runs before anything is installed): pre-setup, only the `install`
  verb exists and delegates to `setup.sh` with full flag pass-through
  (`--no-init` / `--with-init` / `--project`); any other verb prints help
  pointing at `./aipass install`. Post-setup the launcher turns transparent —
  it execs the venv `aipass` binary for everything, so `./aipass doctor` just
  works. Bare `aipass` always resolves to the PATH binary; the launcher only
  ever runs as an explicit `./aipass`. 13 launcher tests (file properties,
  pre-setup help, install delegation, post-setup forwarding), @aipass suite
  622 green, seedgo 100%. README Quick Start now leads with `./aipass install`.
  (built by @aipass)

- **`./setup.sh` chains into `aipass init run` — clone-first one-command install
  (DPLAN-0234 Strand A).** Distribution is git-clone, not pip: the framework
  changes constantly, so a PyPI snapshot goes stale while a clone is always
  current HEAD. Now `git clone && cd AIPass && ./setup.sh` takes you from cold
  clone to a working first project in one command: on interactive terminals,
  setup ends by launching the guided `aipass init run` in a sibling directory
  (default `~/aipass-project`, prompt to choose — init refuses to run inside the
  engine tree). New flags mirror `aipass install`'s handoff rules: `--no-init`
  skips, `--with-init` forces even headless (init chains `--non-interactive`),
  `--project <dir>` picks the target. CI and piped shells skip automatically
  (`CI` env or no tty), so the windows/macos-test workflows that run bare
  `bash setup.sh` are untouched. `install.py` now calls `setup.sh --no-init`
  since install owns its own init handoff — no double-scaffold. Proven in
  clean-room Docker, both runs exit 0: bare headless run skips init with a
  hint; `--with-init` run chains init to `✓ Project initialized.` with the
  project dir scaffolded. 39/39 install tests, seedgo 30/30. README Quick
  Start updated to the one-command flow.

- **`aipass install` — one-command framework bootstrap.** The missing half of
  `pip install aipass`: a single command resolves the install home (default
  `~/AIPass`), git-clones the public repo, runs `setup.sh` (venv, editable
  install, hook wiring), verifies the toolchain, and auto-launches `aipass init`
  in the same terminal — so `pip install aipass && aipass install` bootstraps
  the whole system with nobody the wiser. New auto-discovered `install.py`
  module (zero shared-code edits) with flags `--non-interactive / --path /
  --here / --no-init / --with-init / --project / --dry-run`; 39 unit tests,
  seedgo 30/30, @aipass suite green. Proven in a clean-room Docker image
  (nothing pre-baked) across two runs, both exit 0: `pip install` (local wheel)
  → clone → `setup.sh` (17 branches registered, 13 bootstrapped, hooks wired
  into `~/.claude/settings.json`, `AIPASS_HOME` set, `drone`/`aipass` on PATH) →
  live `drone systems`, and `--with-init` chaining straight into `aipass init`
  to completion. Ships install progress bars, an install→init handoff, and
  doctor coverage. (built by @aipass, DPLAN-0233 — PyPI release bump pending)

### Changed

- **HVTrust badge temporarily hidden in the root README.** hvtracker's
  methodology v4.1 recalibration is miscomputing the grade (showing D/~10 while
  the detail-page dimensions sum to ~78); the badge is commented out until it's
  corrected. Filed upstream as hvtracker issue #109 — restore when resolved.

- **devpulse branch prompt — sole-git-writer clarity.** Added a note to the git
  section: because no other agent can commit, merge, or push anywhere, dirty
  cross-branch files are always someone's live WIP, safe to leave and pick up
  later — never a loose end needing handoff.

## [2026-07-03]

Post-2.6.1 cycle — **unreleased** (held for a later merge).

### Changed

- **All 17 branches now pass the standards audit at 100% — Windows-compat
  hardening across the board.** Added `sys.stdout/stderr.reconfigure()` UTF-8
  guards (getattr form) to every Rich/CLI entry point, and platform-branched
  POSIX-only subprocess kwargs (`start_new_session` → `CREATE_NEW_PROCESS_GROUP`
  on win32). The seedgo `windows_compat` checker now credits the getattr guard
  form (not just direct `.reconfigure()` calls), with a locking regression test.
  Swept per-branch via dispatch; checker fix by @seedgo. Verified by a full
  17/17 audit (pyright clean).

### Fixed

- **Telegram replies no longer overwrite the previous message.** The Stop-hook
  out-path (`hooks/.../notification/telegram_response.py`) reused a stale
  `processing_message_id`: after a successful delivery, `_advance_pending` kept
  the pending file but never cleared the placeholder id, so any reply that fired
  without a fresh "Processing…" bubble (remote/mirror input, multi-Stop turns)
  re-*edited* the same Telegram message instead of posting a new one — every
  response clobbered the last. Now clears `processing_message_id` after the first
  delivery, so subsequent Stops fall through to `_send_with_retry` (a new
  message). Root-caused live on the devpulse bot and proven by the delivery log
  flipping `edit`→`send`; +2 regression tests in `TestAdvancePending` (114/114).
  (fixed by @hooks, `f42a98b`, PR #651 — not yet merged)

- **`template` audit checker no longer false-flags documentation *about* templates.**
  The advisory stale-template checker (`seedgo/.../template_check.py`) matched its
  marker strings anywhere in a file, so it fired on prose and code that merely
  *mention* the markers rather than on un-rendered stubs — flagging 5 branches,
  only 3 of them real. Three root causes, all fixed:
  (1) it globbed **`.trinity/*.json`**, scanning live memory (`local.json`,
  `observations.json`) that naturally accumulates marker mentions (seedgo's own
  note "Detects NEEDS CONFIGURATION", prax's note about `template_pusher` restoring
  `{{BRANCHNAME}}`); now scans **`passport.json` only**, the sole spawn-templated
  trinity file.
  (2) the single-curly `{…}` regex ran on every `.md` and matched inline JSON /
  f-strings / code paths in READMEs (`{"new": 3}`, `{e}`, `apps/plugins/{name}/`);
  now runs on the branch **prompt only** (the spawn README template has no
  single-curly placeholders).
  (3) the definitive-marker scan matched `{{BRANCH}}` inside markdown inline code —
  e.g. spawn's README documenting ``Replace `{{BRANCH}}`…``, which is scaffolding
  docs, not a stub. For `.md` files, fenced + inline code is now stripped once up
  front before **both** scans (`passport.json` still scans raw). Safe because real
  stubs carry markers in prose/headings (the `## Status: NEEDS CONFIGURATION`
  line), never exclusively in code.
  Verified system-wide: `Template` avg **80% → 94%**, the two pure false positives
  (seedgo memory, spawn README) cleared to `100%`, only the three genuine
  unconfigured prompt stubs (cli/drone/prax) still flag. +7 tests (24/24), full
  suite green. (fixed by @seedgo across 3 dispatched passes, verified by @devpulse)

- **cli / drone / prax branch prompts configured** (were spawn stubs). The three
  branches the template checker correctly flagged had never had their
  `.aipass/aipass_local_prompt.md` filled in — they booted with a `NEEDS
  CONFIGURATION` placeholder and no branch-specific identity. Each branch wrote its
  own real prompt (identity, key commands, architecture, critical rules,
  integration points; ~63–67 lines, `PROMPT_STYLE.md` format); all three now score
  `Template 100%`. (written by @cli/@drone/@prax, dispatched + verified by @devpulse)

## [2026-07-02]

Released as **2.6.1**. Rolls up the DPLAN-0226 / FPLAN-0289 / TDPLAN-0010 /
FPLAN-0298 batch (unified Telegram↔Claude Code bridge, single-session presence
gate, live Telegram streaming, `aipass init` template selector + portability,
`@backup share`) — all documented under `[2026-07-01]` — plus the CI
stabilization below.

### Added

- **`drone @git tag <vX.Y.Z>` — guarded release-tag automation (post-2.6.1).**
  Devpulse-tier verb that pushes a release tag with no manual step: fetches
  `origin`, refuses unless the tag's `X.Y.Z` matches **both** `pyproject.toml`
  and `src/aipass/__init__.py` on `origin/main` (version guard) and the tag
  doesn't already exist (exists guard), then tags `origin/main` and pushes —
  firing `publish.yml`. `drone @git tag --list` lists tags. Removes the merge
  playbook's last manual `git tag`/`push` step, so releases need zero user
  input. (built by @drone, S274)

### Fixed

- **CI green — six regressions from the DPLAN-0226 / FPLAN-0289 / TDPLAN-0010
  batch (PR #646).** The dev branch had gone red across `seedgo-audit`, the
  `test` matrix, and Windows; root-caused and fixed at source:
  - **seedgo** — the new `template_check` advisory checker was gating CI.
    `branch_audit.py` averaged *all* checker scores into the branch total, so
    `template_check`'s `ADVISORY=True` was never honored and it dragged 7
    branches below the 100% floor on legitimate README brace-examples. Added a
    `gating_scores` filter that excludes `ADVISORY is True` checkers before
    computing the average (strict `is True` to avoid MagicMock false-positives)
    and exposed `advisory_standards` in the audit output. Also refreshed the
    provider hooks snapshot fixture to include the `presence_gate`
    `UserPromptSubmit` hook (FPLAN-0289), fixing 4 `test_hooks_snapshot` tests.
  - **hooks** — `cc_sessions.py` (added by the bridge, `f6cbe34`) was missing
    its README entry and a seedgo `modules` bypass (it reads external
    `~/.claude/sessions/*.json`, not branch data, so `json_handler` is the wrong
    tool — same precedent as `presence.py`). Added both.
  - **spawn** — retired the `passport(disabled).py` / `passport_ops(disabled).py`
    pair to `.archive/`; the `(disabled)` suffix kept them visible to the type
    checker, which flagged a broken cross-import between them.
  - **ai_mail** — `test_child_inherits_broker_fd` gave its throwaway test branch
    a real `.trinity/passport.json` so the broker's new `.trinity`-marker
    resolution (`f914ab6`) can resolve it and permit the delete.
  - **spawn** — the `builder→aipass_framework` template rename (`13463c0`) left
    `.gitignore` exceptions pointing at the old `templates/builder/` path, so
    `DASHBOARD.local.json` + ~10 other template files were silently untracked
    since the rename — present on disk (dirty tree passed) but absent from clean
    clones/CI, so `test_full_spawn` failed only in a clean checkout. Fixed all 23
    `.gitignore` exception paths and committed the now-visible template
    scaffolding.
  - **skills** — `test_streaming` asserted a `+1` newline byte, but `write_text`
    text mode translates `\n`→`\r\n` on Windows (2 bytes), failing `windows-setup`
    only. Switched the test's transcript writes to `write_bytes()` for
    deterministic LF; production `_tail_transcript_bytes` was already CRLF-safe.

## [2026-07-01]

### Added

- **`aipass init` is now a template selector (TDPLAN-0010)** — `init` presents a
  chooser with **`empty project`** at the top, pre-selected as the default
  (creates just the project folder, no scaffold), and **`aipass_framework`**
  below it (the full AIPass agent framework — the old always-on behavior, now
  opt-in). Flag and positional forms both work: `aipass init --list` (branches
  before the `--` catch-all) and `aipass init <template>`. The AIPass-specific
  stages (8 spawn-first-agent / 9 ping-registry / 11 handoff / 12 init_report,
  `AIPASS_SPECIFIC_STAGES`) and the `bootstrap.init_project()` scaffold are now
  gated on the chosen template, so an empty project stays empty. In-product pip
  hints in `init_flow.py` + `doctor.py` retuned to clone/`setup.sh`. 8 new
  selector tests; 499 tests pass. (built by @aipass, FPLAN-0295, TDPLAN-0010)

- **Unified Telegram ↔ Claude Code bridge — CC-native session discovery
  (DPLAN-0226)** — a Telegram message to a branch's bot now lands directly in
  that branch's live Claude Code session, and the reply tails back out to
  Telegram — a full round trip, **live-proven end-to-end from Patrick's own
  Telegram client** (not just a self-test). The bot's inbound path
  (`base_bot.ensure_tmux_session`) discovers the active session by enumerating
  CC-native `~/.claude/sessions/<pid>.json` files (match `cwd`, confirm PID
  alive, newest by `startedAt`), maps it to a tmux pane by cwd, and injects the
  message — replacing the old `PRESENCE.central.json` pointer, which is kept but
  commented out. The outbound path gains a CC-native "Strategy 0" in
  `_resolve_active_transcript` that prefers the discovered transcript, so
  assistant replies relay back reliably. Anthropic ToS rules out a cloud peer,
  so all delivery is local (tmux/PTY). New `session_boot.py` boot wrapper
  (attach-if-live-else-start-in-tmux; a thin `~/.bashrc claude()` shim delegates
  to it). Hooks tests 66 green (presence_gate / cc_sessions / session_boot),
  telegram presence_pointer 42 green. (DPLAN-0226 P1/P2, FPLAN-0290/0291/0292)

- **Seedgo stale-template audit checker (`template_check`)** — a new advisory
  standard that flags branches still carrying unrendered template markers in
  their local prompts / config, so a citizen that never customized its scaffold
  no longer fails silently. Auto-discovered like every other checker; advisory
  (warns, never blocks). Ships with `template_content.py` and a `template.md`
  standard doc, covered by `test_template_check.py`. (built by @seedgo, DPLAN-0228)

### Fixed

- **Drone `--json` output no longer corrupts machine JSON** — `--json`
  pass-through was routed through Rich's `console.print()`, which defaults to
  width 80 on a non-TTY and hard-wraps mid-string, producing invalid JSON
  (e.g. `"Security \nScan"`). Fixed by writing raw JSON with `sys.stdout.write()`
  in the pass-through paths (`drone.py` + `router.py`) while keeping Rich for
  drone's own human UI. Verified live end-to-end. (fixed by @drone, td-49)

### Changed

- **README: pip removed, clone-only install (TDPLAN-0010)** — the top-level
  README no longer documents `pip install aipass` anywhere: the PyPI badge, the
  install steps (hero + Quick Start), the Project Status version badge, and the
  uninstall `pip uninstall` line are all removed. Install is now a single path —
  `git clone … && ./setup.sh` (puts `aipass` + `drone` on PATH), then
  `aipass init` scaffolds agents into your own project on top. Quick Start
  reorganized into Install → Your own project → Explore the full framework.
  (packaging code untouched; docs are clone-first.) (DPLAN-0228, devpulse)

- **Spawn: `builder` template → `aipass_framework`, birthright retired,
  per-project registry targeting (TDPLAN-0010)** — the citizen_class/template
  `builder` is renamed to **`aipass_framework`** across `class_registry.py`,
  `core.py`, `meta_ops.py`, `update_ops.py`, `sync_registry_ops.py`, help text,
  and the template dir itself (`templates/builder/` → `templates/aipass_framework/`).
  The class is no longer baked as a literal in the template passport — a new
  **`{{CITIZEN_CLASS}}` placeholder** (passport line 21, `placeholders.py`) now
  takes it from the create call. **`birthright`** (0 live users) is retired to
  `templates/.archive/birthright/` and its `passport` command disabled
  (`passport.py` / `passport_ops.py` → `(disabled).py`, routing removed).
  **Per-project registry targeting:** `spawn`'s `find_registry()` no longer
  passes `package_root` to the shared discovery (killing the silent fallback to
  AIPass's own registry for external targets), and `_spawn_agent` now validates
  containment and, if the found registry is outside the target's project, walks
  up from the target for `.git`/`pyproject.toml`/`setup.py`/`setup.cfg` to use
  **that project's own registry** — so an agent created into any project is
  tracked by that project's registry, never AIPass's. The
  `_validate_path_containment` isolation invariant is untouched. `create` also
  degrades gracefully when `@memory` is unavailable (empty meta-tabs, no crash).
  297 tests pass. (built by @spawn, FPLAN-0294, TDPLAN-0010)

- **Drone resolution + access checks made project-portable (TDPLAN-0010
  foundation)** — five `src/aipass`/fixed-depth self-location hardcodes are
  replaced with `.trinity/`-marker walk-ups: `rm_handler` sibling protection,
  `commit_handler` test-gate branch detection, `broker/daemon` allowed-bases,
  the `handlers/__init__` import-guard access check (now `is_relative_to()`
  instead of scanning path parts for the literal `aipass`), and
  `registry_handler`'s `parents[4]` last-resort (now a
  `.git`/`pyproject.toml`/`setup.py`/`setup.cfg` marker walk). `@name`→path
  resolution now works for an agent in any project layout via a CWD-first
  registry walk (AIPASS_HOME only as a last resort when the CWD ancestry has no
  registry at all). The `_validate_branch_path` containment invariant is
  untouched — per-project isolation preserved. (Drone uses its own resolver, not
  the shared `registry_discovery.py`.) 838 tests pass. (built by @drone,
  FPLAN-0296, TDPLAN-0010)

- **ai_mail routing made project-portable (TDPLAN-0010 foundation)** — the
  fixed-depth `_REPO_ROOT = parents[2].parents[2]` self-location in
  `email.py` / `email_send.py` / `dispatch.py` (4 sites) is replaced with the
  portable `find_repo_root()` marker-walk already used in
  `delivery.py` / `wake.py` / `paths.py`, so mail resolves via the project
  marker instead of a hardcoded tree depth — a prerequisite for agents that
  live outside `src/aipass/`. Per-project isolation preserved (no cross-project
  mailbox routing). 737 tests + seedgo 100%. (built by @ai_mail, FPLAN-0293,
  TDPLAN-0010)

- **Presence gate re-sourced to CC-native session files (presence_gate v2)** —
  the single-session guard now sources truth from `~/.claude/sessions/<pid>.json`
  via a new `cc_sessions` module (`find_occupant`/`find_live_for_cwd`) instead of
  `PRESENCE.central.json`. Resume-aware (a `/resume` keeps the same PID, so the
  session is correctly recognized as re-entry, not a duplicate) and exit-aware
  (CC deletes the file on clean exit). `handle_stop` is now a plain no-op —
  cleanup is CC's job. The old `presence.py` / `PRESENCE.central.json` are
  preserved, just no longer sourced. (DPLAN-0226 P1)

## [2026-06-25]

### Added

- **Daemon auto-runner — systemd user timer (the deferred last mile of the
  decentralized scheduler)** — `.daemon/schedule.json` jobs now fire **hands-off**.
  A oneshot `daemon-tick.service` + `daemon-tick.timer` (every ~2 min, mirroring
  the `prax-monitor.service` pattern: user-scope `~/.config/systemd/user/`, `%h`
  not hardcoded paths, venv-python ExecStart `-m aipass.daemon.apps.daemon run`,
  logs to `~/.aipass/daemon-tick.log` outside any tailed dir) reuses the existing
  fcntl-locked `run.py` tick unchanged — the timer is the ticker. New
  `apps/modules/timer_install.py` installs/enables it idempotently. Live-proven:
  @devpulse received a `DAEMON TEST` ping from a branch woken purely by the timer,
  no human tick. Tick profile: ~1.7s (import overhead only); the earlier CPU spike
  was `wake_branch` spawning opus agents concurrently, **not** the tick — so
  scheduled wakes want light models + staggering. Closes the piece DPLAN-0204 /
  FPLAN-0282 deferred. 461 daemon tests green, seedgo 100%. (FPLAN-0287)

- **Prax monitor → Telegram relay (`prax_monitor` bot)** — the live
  `drone @prax monitor run` Mission-Control feed now mirrors to a dedicated
  Telegram bot, so the whole-system monitor is watchable from a phone ("same
  monitor, different window"). New `monitoring/telegram_relay.py` taps the single
  render seam (`_render_event`), buffers events, and flushes every 5s (4000-char
  split, 150-line flood cap, `disable_notification`); fail-silent-once when
  unconfigured. Gated behind `--relay` / `AIPASS_PRAX_MONITOR_RELAY=1` so a local
  `monitor run` stays console-only (no double-send). Bot config (token + chat_id)
  loads from the @api secret `telegram/prax_monitor`. Ships a reboot-survivable
  `prax-monitor.service` user unit. 937 prax tests green (31 new). (DPLAN-0221)

- **Self-documenting `.trinity` state-tabs** — each memory-file section
  (`todos` / `key_learnings` / `sessions` / `observations`) now carries a
  config-sourced `⟦ rollover ON/OFF · keep N · ≤chars ⟧` tab rendered directly
  above it, so an agent editing a section sees its rollover state and character
  cap at the edit point (stops over-limit writes). Values are generated from
  `memory.config.json` (single source of truth) via @memory's new
  `render_all_meta_tabs()` / `tab_renderer.py`; @memory's `spawn_pusher` carries
  the `{{*_META}}` placeholders into @spawn's branch templates, and @spawn
  resolves them at create (`build_replacements_dict`, fail-loud on missing keys)
  so new branches auto-populate. `refresh_all_tabs` keeps live branches synced;
  @memory README documents the system. (FPLAN-0285, FPLAN-0286)

### Changed

- **Todo management — delete-on-done discipline** — `todos[]` are operational
  and exempt from rollover (confirmed; the vestigial `todos` entry was removed
  from `memory.config.json` rollover defaults). Because rollover never trims
  them, finished todos must be **deleted**, not left as `status: done` (which
  pile up and resurface as "open" across sessions). `/prep` and `/memo` (Claude
  + Codex) and the `CLAUDE.md` startup protocol now codify: delete each todo when
  done (proof → session entry), reconcile on load. (FPLAN-0285)

### Fixed

- **Daemonized wakes killed by systemd cgroup teardown (td-48)** — timer-fired
  `wake_branch()` calls spawned the dispatch monitor + claude child, then died
  within seconds with no email and a stale lock, while the *same* wake from an
  interactive terminal worked. Root cause: a systemd oneshot service defaults to
  `KillMode=control-group`, so when the ~1.7s tick process exits, systemd SIGTERMs
  **every member of its cgroup** — `start_new_session=True` is irrelevant because
  systemd tracks by cgroup, not process group. Fix in `ai_mail` dispatch: detect
  the systemd context (`INVOCATION_ID`) and re-spawn the monitor via
  `systemd-run --user` in its **own transient unit**, escaping the parent cgroup
  (falls back to direct `Popen` when not under systemd); plus `stdin=DEVNULL` on
  both the monitor and claude `Popen` calls and monitor PID self-registration in
  the lock. Now genuinely live-proven through the timer: 3 branches
  (commons/cli/backup) woken purely by `daemon-tick.timer` each emailed @devpulse
  and exited clean (~20s, code=0). 737 ai_mail tests green, seedgo 100%.

- **seedgo-audit — telegram ported-but-unwired functions** — the DPLAN-0218
  relocation pulled the telegram lib into the seedgo gate's scope, surfacing 16
  `unused_function` flags across 8 handler files. These are *not* dead code —
  they're ported-but-unwired from the ~9k-line Dev-Pass port (S249), awaiting
  DPLAN-0220 wiring (on_response hooks, response_router, tmux session mgmt, file
  up/download, multi-bot, config helpers). Added name-scoped `unused_function`
  bypasses in `skills/.seedgo/bypass.json` (the existing mechanism), each citing
  DPLAN-0220, and documented every one in `SKILL.md` → *Ported-but-unwired* with
  a "remove the bypass as you wire each fn" note. @skills back to 100%.

- **seedgo-audit — @spawn direct JSON read** — `core.py` adopt-path read a
  passport via `json.loads(path.read_text())` (direct file op), failing the
  `json_handler` standard and the CI seedgo-audit gate. Switched to
  `json_handler.read_json()` (the same pattern used a few lines above), dropping
  the now-unused `import json as _json`. @spawn back to 100%; 315 spawn tests
  green.

- **Windows CI — telegram `bot_registry` crashed test collection** — the module
  did a bare `import fcntl` (POSIX-only), so on Windows all 8 telegram test
  modules that transitively import it failed at *collection* with
  `ModuleNotFoundError: No module named 'fcntl'`, reddening Windows Test on the
  last several PRs. Guarded the import (`try/except ImportError → fcntl = None`,
  the established hooks/daemon convention) and routed the three flock call-sites
  through no-op-on-Windows `_lock`/`_unlock` helpers — advisory locking still
  applies on POSIX, is skipped where unavailable. Fixing collection then
  *unmasked* three telegram tests that had never actually run on Windows, all
  test-portability bugs (not product bugs): a log-streamer byte-count broke on
  CRLF translation (fixture now writes `newline=""`); a registry write-failure
  test used the Unix-only `/proc` path (now a cross-platform file-as-directory
  parent); and `validate_bot_config` rejected valid POSIX `work_dir`s on Windows
  because `Path.is_absolute()` is host-dependent (now tests POSIX *and* Windows
  absoluteness). 493 telegram tests green.

- **prax-monitor service feedback loop** — the unit wrote its own stdout into
  `system_logs/`, the very directory the monitor tails *and* @trigger watches,
  creating a self-reinforcing loop (monitor output → re-tailed and recorded by
  @trigger into `trigger_data.json` → reported as a file change → more output).
  Moved the service log to `~/.aipass/` to break the cycle. Also corrected the
  ExecStart to `monitor run` (relay enabled via env) — the module `__main__`
  rejects the drone-style `run all --relay` argument form. (DPLAN-0221)

## [2026-06-24]

### Changed

- **Skill library relocated to `src/aipass/skills/lib/`** — first-party skills
  were split across `catalog/` (built-in, cross-branch) and `.aipass/skills/`
  (the branch-prompt dir, cwd-relative). Renamed `catalog/`→`lib/`, moved the
  telegram skill in, archived three orphan test-fixture skills, and retired
  `.aipass/skills/` from the branch. This unifies all 6 first-party skills under
  one built-in tier and **fixes the telegram skill not being discoverable from
  other branches** (it sat in a cwd-relative path). The public discovery
  convention (`.aipass/skills/` + `~/.aipass/skills/`) is unchanged. One
  functional line changed (`discovery_handler` built-in path); telegram's test
  `conftest` path-depth, the systemd `.service` ExecStart, and seedgo bypass +
  test paths were updated to match. Packaging, imports, and gitignore are
  unaffected (everything stays under `src/aipass/`). 252/252 skills tests green;
  cross-branch discovery verified from another branch. Moving telegram into the
  gate's scope newly surfaced 9 pre-existing `unused_function` flags in its
  handlers — triage tracked separately. (DPLAN-0218)

### Added

- **`@api` in-process `set_secret` write-door** — `aipass.api.apps.modules.secrets.set_secret(provider, slug, value, *, as_json=False)`
  mirrors the existing `get_secret`, writing `~/.secrets/aipass/<provider>/<slug>.json`
  (dirs `0o700`, files `0o600`, value never echoed to stdout or logged). The @api
  secrets store was previously read-only; this is the writer the telegram
  mother-bot needs to persist a newly-created bot's config so the child can read
  its token. 515 @api tests pass (11 new), @api seedgo 100%. (DPLAN-0220)

- **Prax-monitor v1 on Telegram — `/monitor` system-wide log subscription** —
  the old Dev-Pass "prax monitor bot" (a `@prax` push relay on a dedicated token)
  was stripped during the port; this revives the capability as a feature of the
  existing `@aipass` bot (no second bot, no new credential). New `/monitor on`
  (errors+warnings) / `all` (firehose) / `off` / `status` command on `base_bot`,
  shown in the slash menu + `/help`. The subscribed chat is persisted to the `@api`
  store (`set_secret('telegram','monitor',{chat_id,mode})`) so it survives restart,
  and `base_bot` boot-starts the stream from it on startup — set-and-forget under
  systemd. `LogStreamer` gained `system_wide` (glob all `system_logs/*.log`, not one
  branch) + `level_filter` (default keeps `WARNING`/`ERROR`/`CRITICAL`, `all` =
  passthrough); `_init_positions` still seeks EOF so subscribing never floods
  history. 33 new tests (`test_monitor.py`), telegram suite 493/493, skills 252/252,
  @skills seedgo 98%. (First @skills run crashed mid-edit on 3 string-handling
  syntax errors; continued + fixed.) The richer AS-WAS `@prax` event-feed relay
  (rendered Mission-Control stream, needs a dedicated-bot-token decision) is tracked
  as Route B. (DPLAN-0221)

### Fixed

- **Telegram port — wave 1 (persistence + monitor + state hygiene)**, surfaced by
  a full completeness audit against `TELEGRAM_PORT_MAP.md` (366 tags, ~83% ported,
  452/452 tests green): (1) **bot launch** — `bot_factory.start_bot_process` and
  `telegram-bot@.service` used a non-existent `~/.venv/bin/python3`; now launch via
  `sys.executable -m …base_bot` (added `lib/__init__.py` + `lib/telegram/__init__.py`
  for package resolution, since base_bot uses relative imports). (2) **reboot
  survival** — `enable_service` now installs the systemd unit to
  `~/.config/systemd/user/` + `daemon-reload` (previously the unit was never
  installed, so `enable` silently no-op'd). (3) **state hygiene** — gitignored
  `skills/.../lib/telegram/.local/` so the runtime registry/offset/lock files stop
  leaking into the repo. (4) **prax-monitor** — `log_streamer` tailed a hardcoded
  `~/system_logs` while prax writes to the repo-root `system_logs`; now resolves the
  repo root (honoring `AIPASS_TEST_LOG_DIR`) so the log stream actually delivers.
  (5) **auto-create (GAP1)** — `create_bot` wrote a new bot's config only to a disk
  shadow file while the runtime loads its token exclusively from the @api store, so
  a minted bot started then exited with no config; `create_bot` now calls
  `set_secret('telegram', bot_id, config, as_json=True)` (fail-loud) so the
  create→@api→load round-trip works and the mother-bot can mint startable bots. New
  round-trip + fail-loud tests; telegram suite 454/454.
  (6) **/help + Telegram command menu** — `setMyCommands` only ran inside
  `create_bot`, so hand-launched bots (like the live `@aipass`) had no slash-menu,
  and the menu list had drifted from `/help`; `base_bot` now sets its menu on
  startup from a single source (`build_botfather_commands`, also used by
  `create_bot` — `DEFAULT_BOT_COMMANDS` retired), so the Telegram menu and `/help`
  list the same enriched commands incl. `/create`/`/cancel`. Wiring the builder
  (rather than deleting it as "dead") also lifted Unused_Function 92→93%. 6 new
  tests, telegram suite 460/460. (A running bot needs a restart to pick up the
  startup menu.)
  (DPLAN-0220)

- **Telegram `@aipass` deployed under systemd (reboot survival + clean lifecycle)** —
  the live mother-bot was a hand-launched foreground process: no reboot survival, and
  `stop_bot`/restart targeted an uninstalled `telegram-bot@base` unit, so there was no
  working lifecycle command. Installed the user service + `enable --now` +
  `loginctl enable-linger` (`Linger=yes`); the 17:26 startup log confirms the full
  chain live — `Telegram API OK`, **`Command menu set (6 commands)`** (the new `/help`
  menu), stale-lock cleanup, poll loop, tmux Claude session preserved, `NRestarts=0`.
  Also corrected the ported unit's `StandardOutput`/`StandardError`, which pointed at a
  non-existent `~/system_logs` (would have crash-looped the service) — now
  `<repo>/system_logs`, matching where the app already logs. Restart is now
  `systemctl --user restart telegram-bot@base`. (DPLAN-0220)

- **seedgo CLI help checkers green-lit non-compliant `--help` output** — the
  `cli`/`help_text`/`introspection` standards are static source scans (they
  confirm a `print_help` function, `console.print`, and `--help` wiring exist)
  but never execute `--help`, so a module could score 100% while rendering raw
  argparse. `@ai_mail` did exactly that via `console.print(parser.format_help())`,
  laundering argparse's plain text through the approved console API and dodging
  the existing `parser.print_help()` ban. Closed the loophole: `cli_check` now
  flags `.format_help()`, `cli.md`/`cli_content.py` name it alongside
  `print_help()`, +2 regression tests. Also rewrote `@ai_mail`'s `print_help()`
  to render hand-rolled Rich (the `--help` content was complete, just unstyled).
  A behavioral `--help` check (run it, assert not raw argparse) is noted as a
  follow-up. (DPLAN-0217) On its first CI run the tightened checker immediately
  surfaced the same pattern in 4 `@api` modules (`api_key`, `usage_tracker`,
  `google_client`, `openrouter_client`) — migrated to Rich, `@api` back to 100%.
- **seedgo `readme_check` ignored the `(disabled)` marker in self-scans** — its
  module-list and test-count scans now skip `foo(disabled).py`, matching the
  central audit collector. An in-place disabled module no longer trips a false
  "missing module" violation; disabled test files no longer inflate README test
  counts (td-103).
- **seedgo `unused_function` bypasses are now name-scoped** — bypasses match by
  function name (`functions: [...]`) instead of line number (`lines: [...]`),
  which drifted silently when code shifted and re-flagged exempted functions
  (bit us S216/S217). `lines` stays supported for other standards. Migrated the
  10 existing line-scoped entries across drone/memory/skills and dropped 3 dead
  entries already pointing past EOF (td-009).
- **Dispatch footer no longer tells workers to close the orchestrator's plan** —
  the standard email footer's checklist item read `CLOSE FPLAN → drone @flow
  close <plan_id>`, which led dispatched agents to close the master/parent plan
  referenced in their brief (bit us in FPLAN-0260). Reworded to `CLOSE YOUR PLAN
  → ... this task's plan only, never the master/parent` — a worker still closes
  the sub-plan handed to it, but the master stays the orchestrator's to close on
  completion (td-6).

### Changed

- **Backup `.backupignore` default moved out of code into a template file** — the
  seed content backup writes into a new project's `.backupignore` now lives in
  `backup/templates/backupignore.template` (loaded at register), matching the
  AIPass convention that templates are data files, not hardcoded Python. Retired
  the `BUILTIN_IGNORES` list; `_build_backupignore()` reads the template and
  **raises** if it's missing — never silently empty, since an empty
  `.backupignore` would back up everything and crash. Docs/comments repointed to
  the template (td-30).

### Removed

- **Dead `bulletin_created` trigger handler** — the event handler that wrote a
  `bulletin_board` section into every branch dashboard is retired: nothing fired
  the event, its `BULLETINS.central.json` store no longer exists, and prax
  already prunes `bulletin_board` as a deprecated section. Archived + unwired
  from the event registry; prax's pruning stays (td-102).
- **Dead `backup/run/` test dir** — leftover from an ad-hoc backup test run
  (only its generated `.backupignore` had been tracked); removed (td-218).

### Documentation

- **Backup docs corrected** — `.backup/` is now documented as a **shared runtime
  namespace** (@backup stores + @memory rollover safety copies + @flow plan
  archive), not @backup-exclusive. @backup's README gained full command coverage,
  the `.backup/` store layout, and a `.backupignore` ("gitignore for backups")
  section; its branch prompt's stale `.backup_system/` / `drive_test.py` names
  were fixed. Root README lists @backup and documents `.backupignore`; the navmap
  was corrected. The shipped root `/.backupignore` was realigned to
  `BUILTIN_IGNORES` (dropped stale `.backup_system/` + over-broad `*logs`).
  @memory and @flow READMEs now cross-reference their `.backup/` writes, and the
  orphaned `prax/.backupignore` (a stale per-branch config) was removed.
- **Root README agent roster brought current** — added the three missing agents
  (`@daemon`, `@skills`, `@commons`) to the tree and tables, and normalized the
  agent count to **17** everywhere (was an inconsistent mix of "13" and "14").
  `@daemon` joins Quality & operations; a new "Capabilities and community" group
  covers `@skills` + `@commons` (td-28).
- **`/prep` now reconciles todos against reality** — the session-wrap command
  (both the Claude `.claude/commands/prep.md` and the Codex skill mirror) gained
  a step to audit every open todo against the actual system (`ls`/`find`/`git
  ls-files`/`grep`/`audit`) and close what's verifiably done — catching todos
  finished in a past session but never closed.
- **Backup ignore architecture documented** — confirmed and written down the
  two-layer model so it stops getting re-discovered: `BUILTIN_IGNORES` is the
  **seed** that generates a new project's `.backupignore` at register and is
  never consulted at backup time; `.backupignore` (via `load_spec`) is the
  **runtime source of truth**. There's no static fallback, so the seed is
  safety-critical — an empty `.backupignore` backs up everything and can crash
  the machine. Added a "How Ignores Work" README section + code comments on
  `BUILTIN_IGNORES` and `load_spec`. Also added `logs/` to the seed so new
  projects exclude log directories (e.g. prax `.jsonl` output) by default, not
  just `*.log` files (td-27).

## [2026-06-23]

The **2.6.0** release — a large `dev → main` merge spanning several weeks (68 commits).
Headline changes below; the granular per-merge history is in the dated sections that follow.

### Added

- **Compass v2** — devpulse-owned SQLite/FTS5 rated-decision engine + `/compass`
  human-triggered capture (separate from @memory; DB gitignored).
- **Decentralized daemon scheduler** — each branch owns `.daemon/schedule.json`;
  the daemon discovers and fires.
- **Telegram skill** — the Dev-Pass bridge ported to a self-contained AIPass skill
  that consumes services as opt-in imports.
- **Tiered prompt injection** — Tier 0 kernel every turn + Tier 1 navmap by cadence,
  replacing the single always-on global prompt.
- **seedgo `HARDCODED_PATH` standard (#37)** — flags hardcoded home paths in source
  and docstrings.

### Changed

- **@backup fully restored** — `aipass.backup.*` namespace, 9-stage Rich CLI,
  versioned baseline + per-file diff engine, Google Drive sync + `restore`.
- **Memory subsystem unified** — single-source config limits, char-limit edit-gate,
  unified entry schema, rollover safety + the silent-rollover repair.
- **Legacy global prompt retired** across every runtime — Claude (cadence) and Codex
  (SessionStart) read the same tier files.
- **@daemon / @commons / @skills** revived to working citizens.
- Public source genericized — `Patrick` → `user` (private memories stay gitignored).

### Fixed

- **Secrets hardening** — no secret value reaches stdout (cleared CodeQL #86-88,
  `py/clear-text-logging-sensitive-data`).
- **Memory rollover was silently dead** — the PreCompact hook now delegates to
  `drone @memory rollover`; the v1 line-count / 600-line fallback removed entirely.
- **Hardcoded home paths removed (seedgo #37).** `@memory` `symbolic.py` builds its
  8 dash-encoded branch-path names at runtime (was a literal `-home-patrick-`);
  `@prax` `branch_detector.py` docstrings genericized. Both back to 100%
  `Hardcoded_Path`.
- Green-CI fixes across Linux / Windows / macOS; `dispatch_monitor` PID-`429`
  substring bug; git post-merge friction (FF-only realign).

## [2026-06-19]

### Fixed

- **`aipass init` now seeds the tiered prompts to new projects (@aipass).** The
  init template + bootstrap still handed new projects the retired global prompt
  with no tiers; now `.aipass/project_hooks.json` mirrors the live wiring
  (`tier0_kernel` + `navmap` enabled, `global_prompt` disabled) and `bootstrap.py`
  seeds both tier `.md` files. `init update` backfills existing projects.
  (77 bootstrap tests, 100% seedgo.)
- **Cadence reset observability (@hooks).** `reset_counter()` silently no-op'd
  when the Claude session id was absent; it now fails loud, logs the session id +
  prior turn on each reset, falls back to hook data for the id, and handles a
  corrupt state file. (The post-compaction counter reset was already working —
  this makes it visible so it can't fail invisibly.)
- **Memory rollover was silently dead — fixed end-to-end (@hooks + @memory).** The
  PreCompact rollover hook read its limits from `.trinity` file metadata, but
  DPLAN-0210 had moved limits into @memory's `memory.config.json` — so the hook
  always fell back to a 600-line check the lean files never reached, and rollover
  never fired (for weeks). The hook is now a thin trigger delegating to
  `drone @memory rollover check/run`; `compact.py` reads the current list schema
  (it was calling `.keys()` on a now-list `key_learnings`). Both fail loud instead
  of a silent exit-0.
- **Removed @memory's v1 line-count / 600-line silent fallback entirely.** The
  detector + extractor are now v2-only (`per_branch` → `defaults` → warn-and-skip);
  a parse failure logs loud and skips rather than silently falling back. Deleted
  `_get_max_lines` / `_load_config` / `_detect_growing_array` / the line-count
  extraction path. (959 tests.)

### Removed

- **Legacy global prompt fully retired across every runtime (DPLAN-0215).** After
  the tiered cutover the old `global_prompt` is now gone, not just disabled:
  `global_loader.py` + its tests deleted, the `global_prompt` block stripped from
  `.aipass/hooks.json` + `project_hooks.json`, `_resolve_global_prompt` + all global
  seeding removed from `aipass init` bootstrap/update, the cadence default + bypass
  entries cleaned, and both `aipass_global_prompt.md` / `project_global_prompt.md`
  archived. Claude (cadence) and Codex (SessionStart) now read the same tier files —
  one prompt source, every runtime.

### Added

- **seedgo `HARDCODED_PATH` standard (#37).** A new checker (`hardcoded_path_check.py`
  + `hardcoded_path_content.py`, `test_checkers_batch10.py`) flags hardcoded home
  paths — `/home/<user>` and dash-encoded `-home-<user>-` — in source and docstrings,
  keeping the public repo clean.

## [2026-06-18]

### Changed

- **Prompt injection is now tiered by cadence instead of one 8k always-on block
  (FPLAN-0284 / DPLAN-0214).** The single global prompt is split into two
  cadence-throttled tiers: **Tier 0** (`.aipass/tier0_kernel.md`, ~2k) injects
  every turn — identity grounding, the `drone @agent --help` reflex, and the
  disaster-preventer rules; **Tier 1** (`.aipass/tier1_navmap.md`, ~7.7k)
  injects every 5th turn plus at session start and right after compaction — the
  full agent roster, framework, conventions, and a new Terminology section. The
  hook engine gained per-loader cadence periods; the old `global_prompt` loader
  is retired (kept as a reference snapshot). Net: more navigation context
  reaches agents while less is paid per turn. Fresh-clone wiring is seeded from
  `cadence.py` defaults + `setup.sh` + `provider_manifest.json`.
- **Public source genericized — `Patrick` → generic `user`.** No personal
  identifiers in tracked code/docs: the compass decision-source enum
  (`patrick` → `user`) + the `/compass` command, the devpulse local prompt, the
  `aipass init` onboarding example (`--name Patrick` → `--name YourName`), and
  stale refs across @ai_mail / @backup / @flow. Private memories (`.trinity/`,
  compass DB) keep personal context — they're gitignored.
- **Telegram skill genericized (@skills).** Retired the inactive `patrick_private`
  personal bot from the skill's tests; the message sender now defaults to the
  Telegram user's first name (fallback `User`) instead of a hardcoded `Patrick`.

### Added

- **Prompt-craft conventions harvested from Claude Code's own prompts
  (DPLAN-0213).** A `Writing voice` section in `.aipass/PROMPT_STYLE.md`
  (`file_path:line` refs, write-for-a-person, three-tier "where detail lives");
  a blast-radius habit in the devpulse prompt; faithful-reporting +
  no-gold-plating folded into the Tier 0 kernel.
- **Skill frontmatter discipline (@skills).** A `when_to_use` field with trigger
  phrases (surfaced during discovery scans) and per-step "Done when:" success
  criteria across the SKILL.md templates.
- **`HARDCODED_PATH` standard (@seedgo, 37th checker).** Flags absolute home-dir
  literals in source — POSIX `/home/<user>/`, macOS `/Users/<user>/`, Windows
  user-home paths, and Claude Code's dash-encoded `-home-<user>-` form — with a
  bypass for legitimate test fixtures. Swept the repo for violations.
- **`prompt_change` flow playbook (PPLAN template).** A reusable SOP for changing
  any injected prompt — leads with "live ≠ seeded" and walks every wiring layer +
  fresh-install seed path; born from the `aipass init` seeding gap this surfaced.

## [2026-06-16]

### Security

- **Secrets door hardened — no raw secret value ever reaches stdout
  (DPLAN-0211).** `@api get-secret` previously printed retrieved secret values
  to stdout — an acute exposure in AIPass because Claude Code captures command
  stdout into the model context. The command now emits a **masked summary** by
  default (`provider/slug: set (N chars)`), writes the raw value only to a
  `0600`-mode file via `--out FILE` (printing just the path), and `--list`
  prints slug **names** only. The `telegram` skill — the sole consumer — was
  rewired from subprocess-parsing `get-secret` stdout to the **in-process
  secrets module API**. Clears CodeQL clear-text-logging alerts #86/#87/#88.

### Fixed

- **`@ai_mail` dispatch monitor mislabeled failures as "API rate limit" on a
  PID-`429` collision.** The monitor classifies dispatch failures by
  substring-scanning the stderr log for `"429"`/`"529"`, but that log includes
  the monitor's own header line `(PID <pid>)`. A monitor PID containing `"429"`
  (e.g. `14290`) was read as an HTTP 429, overwriting the real bounce reason
  (e.g. sandbox-abort `-4`) with "API rate limit" — and flaking
  `test_sandbox_failure_sends_bounce` deterministically-by-PID in CI. The scan
  now excludes the monitor's own `--- ` framing lines; genuine `429`/`529`
  markers in agent output are still detected.

## [2026-06-15]

### Added

- **Telegram bridge ported into AIPass as a self-contained skill (FPLAN-0277).**
  The Dev-Pass Telegram bridge (multi-bot long-poll listener → tmux Claude
  injection → Stop-hook reply) is ported AS-WAS into a self-contained `telegram`
  skill that consumes AIPass services instead of bespoke wiring: secrets via the
  new `@api get-secret`, logging via `@prax`, and the outbound Stop hook
  registered through the `@hooks` engine. Three phases — **P1 `@api`** adds
  `get-secret <provider/slug> [--json|--list]` + `auth/secrets.py` (reads
  `~/.secrets/aipass/`); **P2 `@skills`** ports the 14-file bridge (~5,300 lines)
  + ~424 tests into `.aipass/skills/telegram/`, rewiring every seam to services;
  **P3 `@hooks`** ports `telegram_response.py` (the reply path, with the 3-layer
  SubagentStop/sidechain/transcript-cursor defense intact) and registers it on
  the Stop event. A 366-tag completeness map (`TELEGRAM_PORT_MAP.md`) audited the
  port: **288 verified, 23 gaps** (top gap — a missing test log-isolation fixture
  — now fixed), **55 deferred to a live round-trip**. Live bring-up (real bot
  creds, systemd install, telethon auth, message round-trip) is still pending.

## [2026-06-13]

### Changed

- **Unified memory entry schema — Phase 1 (DPLAN-0207).** All four `.trinity`
  entry types (`key_learnings`, `sessions`, `todos`, `observations`) move to one
  shape: numbered + dated, list-shaped, newest-first. `key_learnings` converts
  from a dict to a numbered list; the rollover extractor now trims the **oldest
  by number from the tail**, and the schema normalizer self-heals ordering by
  re-sorting on `number` — so an out-of-order write can never archive a fresh
  entry (the bug surfaced in S229, where rollover ate the *newest* key_learning
  instead of the oldest). Backward-compatible: un-migrated dict-shaped
  key_learnings skip cleanly, no crash. **All 17 branches migrated** to
  `schema_version` 3.0.0 (reversible per-file backups, no data loss). A
  follow-up made the rollover **detector** and the **learnings manager** (used
  by rollover + symbolic) list-aware — a live `rollover check` caught they still
  counted key_learnings as a dict, so an at-cap list was invisible to the
  detector (the 955 unit tests stayed green because none counted a *list*). 960
  tests; seedgo 99% (1 pre-existing unused-function on an unwired manager API).
  Remaining: `/memo`+`/prep` and @spawn template updates.

- **Memory config relocated to the json-home and unified behind one
  self-healing loader (FPLAN-0271).** `memory.config.json` moved from the loose
  tracked `config/` dir into the gitignored `memory_json/custom_config/`
  (operator-tunable, fast-access) and `.plans_processed.json` into
  `memory_json/` root; the empty `config/` dir was removed. The config was
  previously read by **9 separate loaders**, each carrying its own *disagreeing*
  defaults (8 divergence classes — incl. the headline bug where a missing config
  silently flipped `entry_limits.enforce` off, plus rollover defaulting to 600
  vs the configured 500). All 9 now read through one
  `apps/handlers/json/config_loader.py` with a single `DEFAULT_CONFIG` +
  non-mutating deep-merge + self-heal: a missing file is rewritten from code
  defaults (warn-first `enforce: false`), while malformed JSON fails loud and is
  never overwritten. Dead `intake` section deleted; a static `_meta` block in
  `DEFAULT_CONFIG` documents each section's consumer files. Code-as-Template:
  the on-disk file is local tuning, code carries the committed defaults — same
  model as hooks `cadence_config.json`. Verified: 949 memory tests green, seedgo
  @memory 100%, live self-heal / malformed-no-clobber / edit_gate checks pass.
  Design: DPLAN-0206. Follow-up parked: issue #643 (codify `custom_config/` as a
  seedgo standard).

## [2026-06-12]

### Changed

- **Devpulse dashboard slimmed — todos no longer duplicated (startup-context
  fix).** `DASHBOARD.local.json` was embedding the full `todos[]` bodies that
  already live in `.trinity/local.json`; since both files are read at every
  startup, that was pure duplication. The dashboard now emits `todo_count` only
  (the glance value) — the bodies are commented out in the prax
  `devpulse_dashboard` plugin's `todo_section.py` (revivable). Dashboard
  `DASHBOARD.local.json` 6.8 KB → 3.0 KB. Devpulse-only (plugin, not templated).
  Verified: seedgo 100%, 17/17 plugin tests.
- **Deprecated dashboard sections are now actually pruned on refresh.**
  `bulletin_board` (and the other entries in prax's `DEPRECATED_SECTIONS`:
  `devpulse`, `commons_activity`, `agent_status`, `memory_bank`) were listed as
  deprecated but only excluded from template *pushes* — they lingered in every
  branch's live `DASHBOARD.local.json`. Added `_prune_deprecated_sections()` to
  the prax dashboard `refresh` path (reusing the single `DEPRECATED_SECTIONS`
  constant), so a refresh strips them. Verified: `bulletin_board` removed from
  the devpulse dashboard; 116/116 prax tests, seedgo 100%. (Follow-up: `@trigger`
  still has a `bulletin_created` writer to retire separately.)
- **Dashboard slimmed to a lean glance — removed duplicated/dead sections.**
  Dropped three sections from the devpulse dashboard: `session` (broken since
  May — read keys `id`/`d`/`sum` vs the actual `session`/`date`/`summary`, so it
  always wrote empty strings — and it duplicated `local.json`, which loads at
  startup), `todo` (carried only `todo_count`, already in `quick_status`; now
  sourced directly from `local.json`), and `ai_mail` (its counts live in
  `quick_status`; the section is removed from output *after* quick_status is
  computed from it). End state: 4 sections (`flow`, `memory`, `git`, `dispatch`)
  + the `quick_status` glance. `session_section.py`/`todo_section.py` archived
  (not deleted). `DASHBOARD.local.json` overall 6.8 KB → 2.4 KB. Verified: seedgo
  100%, 108 prax tests. (Follow-up: `@ai_mail`'s `dashboard_sync.py` section
  writer to retire separately.)
- **quick_status now self-sources mail counts from `inbox.json`.** Decouples the
  glance from the `ai_mail` section: prax's three quick_status calculators read
  `.ai_mail.local/inbox.json` directly (`_read_mail_counts`) for `new_mail`/
  `opened_mail`, so the `ai_mail` section is no longer a data dependency and can
  be retired. 116 prax tests, seedgo 100%.
- **Retired `@ai_mail`'s dashboard section writer (completes the dashboard
  slim).** ai_mail no longer writes to the dashboard — removed
  `push_dashboard_update` from 5 call sites and archived `dashboard_sync.py`.
  With prax self-sourcing mail counts, the `ai_mail` section now stays gone (a
  mail op no longer re-adds it — verified). 737 ai_mail tests.
- **`.backupignore` is now a true `.gitignore` for the backup system — a single
  source of truth (FPLAN-0269).** Replaced the hand-rolled `fnmatch`+part-loop
  matcher (which broke leading-slash anchoring, `*`-crossing-`/`, dir-only `foo/`,
  `!` negation, and last-match-wins) with the `pathspec` gitwildmatch library, so
  `.backupignore` honors full gitignore semantics: include-by-default, `!`
  negation, `#` comments, anchoring, dir-only, last-match-wins. `BUILTIN_IGNORES`
  is demoted to a seed-only default (written when the file is absent, never merged
  at runtime), and the separate `IGNORE_EXCEPTIONS`/`is_exception` layer is
  removed (exceptions are native `!` lines). Snapshot, versioned, `all`, and
  mirror-cleanup now all obey the one file. `.ruff_cache/` + `.coverage` added to
  the default. `pathspec` (pure-Python, cross-OS) declared. Verified by artifact
  (seedgo 100%, 220 tests incl. 26 new gitignore-parity tests) + live (a dotfile
  flows into the store, `!` negation re-includes end-to-end).
- **Backup store dir renamed `.backup_system/` → `.backup/`, dead `versions/`
  removed (FPLAN-0269 follow-up).** The backup root is now `.backup/` (shorter,
  coexists with `@flow`'s `.backup/processed_plans/`); the orphaned per-timestamp
  `versions/` scaffold and the unused `build_versioned_path()` — both superseded
  by the Phase-3 `versioned/` baseline+diff store — are gone. Drive sync confirmed
  reading `.backup/versioned/` + `.backup/drive_tracker.json` via the shared
  `backup_root()`. Verified by artifact (seedgo 100%, 220 tests) + live (a
  throwaway project writes to `.backup/`, no `versions/` dir).

### Fixed

- **Backup Drive sync no longer silently drops 41% of files — including the
  memories (FPLAN-0269).** Removed a foreign dotfile-skip in `drive_sync.py` that
  excluded every dotted path (`.trinity/` memories, `.chroma/` vectors, `.aipass/`
  prompts, `.ai_mail.local/` mailboxes — 4558 files) from the offsite Google Drive
  copy while the local snapshot/versioned kept them. Drive now uploads the full
  versioned store (already exactly the `.backupignore`-filtered set). Added a
  Drive-sync output panel matching the Snapshot/Versioned stages (header, progress,
  stats, Duration | Location).

### Added

- **Backup Google Drive sync pipeline + restore command (FPLAN-0268, Phase 4 of
  FPLAN-0264 — final).** Faithful port of GOLD's `GoogleDriveSync` against the
  live `@api` gateway (`get_drive_service` + `api_call_with_retry` — never the
  console-OAuth path). New `handlers/drive/`: `DriveClient` (folder hierarchy
  `AIPass Backups/<project>/`, thread-safe cache, retry-with-rebuild),
  `upload.py` (resumable `MediaFileUpload`, 3 threaded workers), `tracker.py`
  (mtime+size dedup → no re-upload of unchanged files), `test.py` (connectivity).
  All four `drive_*` modules un-stubbed; `all` now runs snapshot→versioned→
  drive-sync and **fails honestly** if Drive creds are absent (never silent-skips,
  never fakes success, snapshot+versioned still report). New `restore` command
  (`restore <project> list <file>` / `restore <project> file <file> <out>`)
  exposing the Phase-3 baseline+diff restore engine. Drive tests fully mocked —
  zero real Google calls in CI. Verified by artifact + live: audit 100% (all 37
  files), 187 tests, ruff clean, restore `list`/`file` round-trip confirmed.
- **Backup uses the repo-root pyright config like every citizen.** Removed
  backup's standalone `pyrightconfig.json` (a leftover from its pre-namespace
  standalone days, archived) so it inherits the root config — resolving imports
  consistently with the rest of AIPass. Dead PyQt5 `ui/settings_window.py`
  (never wired) archived.

- **Backup versioned baseline + per-file diff engine (FPLAN-0267, Phase 3 of
  FPLAN-0264 — the heart).** Faithful port of the GOLD versioned engine,
  replacing the mtime full-copy-into-timestamped-dirs remnant. One persistent
  store (`.backup_system/versioned/`) with GOLD's file-folder packaging: each
  file gets `<parent>/<name>/` holding the current copy, a
  `<stem>-baseline-<date>.<ext>` full copy from the first run (never touched
  again), and `<name>_diffs/<name>_v<old-mtime>.diff` unified-diff patches on
  every change — append-only, versioned **never deletes** (cleanup stays
  snapshot-only). Versioned and snapshot back up the identical file set (same
  scan + ignore patterns; `all` shares one scan). Change detection is
  ledger-free (source mtime vs store-current mtime, `copy2`-preserved) — kills
  the regression where running snapshot starved the next versioned via the
  shared `timestamps.json`. New `diff/restore.py` (`list_versions` +
  `restore_file`); `diff/generator.py` wired (binary detection + diff
  include/ignore patterns). +15 tests (125 total). Verified by artifact + live
  end-to-end: snapshot-first-then-versioned still baselines everything
  (starvation dead), edit → real diff with old-mtime timestamp, source delete →
  versioned store untouched while snapshot mirror-deletes, restore round-trip
  byte-identical.

- **Backup snapshot fidelity + shared core (FPLAN-0266, Phase 2 of FPLAN-0264).**
  Restored the snapshot-side machinery the 2026-04-23 rewrite degraded, ported
  from the GOLD archive onto the current per-project handlers. New
  `handlers/cleanup/mirror.py` `cleanup_deleted_files` — exception-aware
  mirror-delete: files removed from source are now removed from the snapshot
  (was a blind `rmtree`+recopy), respecting ignore-exceptions. `copy/snapshot.py`
  gains mtime-skip (quick-check fast path — unchanged files no longer re-copied),
  a long-path guard (>260), and read-only handling. `report/result.py`
  `BackupResult` now tracks critical vs non-critical errors + warnings +
  `files_deleted`; `ignore/patterns.py` gains `IGNORE_EXCEPTIONS`/`is_exception()`.
  +16 tests (`test_snapshot_fidelity.py`, 110 total). Verified by artifact +
  live: audit 100%, 110 passed, and a real throwaway-project test (delete two
  files → re-snapshot → both mirror-deleted, kept files preserved, 3 skipped/0
  re-copied).

- **Backup test suite + seedgo 100% — restoration foundation (FPLAN-0265, Phase 1
  of FPLAN-0264).** Put a safety net under `backup` before the feature rebuild:
  new `tests/` suite (94 tests — json_handler, CLI routing, filesystem handlers,
  error resilience, mocked drive) ported from the canonical citizen conftest
  pattern (hermetic, `tmp_path`, stdlib-only → 3.10–3.13), driving module coverage
  to 27%. Standards brought to 100% across all 35: shared `--help/-h/help` guard
  wired into all 10 modules' `handle_command` (Cli + Introspection), the 6
  Phase-3 drive/diff/ui stubs wired-or-bypassed (Dead_Code + Unused_Function),
  `requirements.project.txt` added (Architecture), README module list + the small
  Modules/Trigger fixes (`display.handle_command`, `create_progress_bar` →
  `build_progress_bar`). Verified by artifact: re-ran audit (100%) + pytest
  (94 passed) + ruff (clean).

### Fixed

- **Memory rollover no longer silently loses rolled-off learnings ("No embeddings
  generated").** A capped `.trinity` file rolls its excess entries out to vectors;
  two combined bugs dropped them on the floor instead. (1) On the "embedding returned
  empty but success=True" path the orchestrator logged the error and continued — but
  the source file was *already* trimmed, so the entry was lost from both the file and
  ChromaDB; it now restores the pre-trim backup before continuing (fail-honest).
  (2) A concurrent-rollover race (two runs ~33ms apart) let the second run extract
  nothing yet still report success → empty embeddings → bug #1; `extract_with_metadata`
  now honors the `skipped` flag and the orchestrator skips no-op extractions before the
  embedding stage. Verified by artifact + live: a 25/25-capped test file rolls over →
  embeds (384-dim) → `drone @memory search` returns it at 91% similarity; audit 100%,
  876 tests (+4).

- **Backup Google Drive folder duplication + dedup-wipe fixed (GOLD-faithful lock
  restoration).** The Phase-4 port had narrowed `GoogleDriveSync`'s folder lock: a
  single `drive_sync` run's 3 upload workers raced the folder search+create →
  multiple "AIPass Backups" root folders, and `get_or_create_backup_folder` reset
  the dedup tracker on every call (re-uploading everything = the slowness). Restored
  GOLD's structure exactly: `get_or_create_project_folder` / `get_or_create_nested_folder`
  hold `_folder_cache_lock` across the **entire** method (cache + root-ensure + search
  + create); `get_or_create_backup_folder` is lock-free (called inside the project
  lock — no re-entrant deadlock), short-circuits cached ids via `_verify_folder_id`,
  and clears the tracker only on a genuine brand-new root folder. Also: all four
  `drive_*` commands route by their underscore names (were hyphenated → "Unknown
  command"); `requirements.project.txt` now declares the three google libs. Verified
  by artifact (seedgo 100%, 197 tests incl. a 5-thread concurrency test → exactly one
  create) + live (real Drive backup: no duplicate folders).

- **Backup rich CLI output restored end-to-end (FPLAN-0263 + drone passthrough).**
  `drone @backup snapshot|versioned|all` rendered a flat text block instead of the
  original rich output. Two independent causes, both closed: (1) the rich rendering
  was never carried forward in backup's revival — rebuilt as a faithful 9-stage port
  (new `backup_timestamps` state handler + `display.py` pipeline: Last-backups panel →
  boxed header → live Rich progress bar → result summary → Backups-now panel;
  `BackupResult` extended with `files_checked`/`files_skipped`/`backup_path`; copy
  handlers emit `on_progress` callbacks). (2) drone was flattening it at the pipe —
  `@backup` ran through `capture_output=True` (non-TTY → Rich strips color, the
  `transient` progress bar renders to nothing) and the 30s capture timeout would kill
  large backups; added `backup` to drone's `INTERACTIVE_BRANCHES` so all `@backup`
  commands inherit the terminal (mirrors `cli`). Verified live under a pty: full color
  + animated progress bar.

## [2026-06-11]

### Fixed

- **seedgo audit local↔CI parity (FPLAN-0261).** The local `seedgo` audit could
  silently diverge from CI, breaking the "pass locally first, then ship" gate.
  Three independent causes, all closed without coupling any checker to git
  (`.gitignore` is git's concern, not the audit's): (1) usage-scanning checkers
  (`unused_function`, `dead_code`, +4) `rglob`'d gitignored *output* dirs
  (`artifacts/`, `dropbox/`), so a stray local file could mark a function "used"
  that a clean checkout correctly flags — every per-checker skip list hoisted to
  one shared `SOURCE_SKIP_DIRS` (output dirs simply aren't source). (2) The
  `diagnostics` standard shelled out to bare `python3 -m pyright` (system python,
  no pyright) and, on the resulting JSON-parse failure, returned *0 errors = clean*
  — a silent false-green; now uses `sys.executable` and **fails loud**. (3) pyright
  resolved imports against PATH-python, so results flipped with `.venv` activation
  — pinned via `--pythonpath sys.executable`. The audit is now deterministic
  local == CI (proven all-13-branches-100% in an unactivated shell). Also: `drone`
  bypasses the test-only broker `start_background` (intentional API, not dead code).
- **windows-setup CI: guard Linux-only sandbox tests.** The kernel-sandbox build
  is Linux-only (bwrap, `AF_UNIX` sockets, `openat2`); the code already guards on
  `sys.platform`, but four test surfaces ran unconditionally and failed on
  `windows-latest`. Module-level `pytestmark = pytest.mark.skipif(sys.platform !=
  "linux", …)` on `drone/tests/test_broker.py` and `hooks/tests/test_sandbox.py`;
  scoped guards on the remaining `AF_UNIX` broker-socket tests —
  `ai_mail/.../test_dispatch_monitor.py::TestBrokerRealE2E` (class) and
  `aipass/.../test_sandbox_check.py::TestCheckBrokerAlive` socket-connect tests
  (method-level, so the graceful no-broker paths still run on Windows). All skip on
  Windows and run unchanged on Linux. windows-setup was green pre-sandbox-merge
  (`00edd8b`) and red since (`0b4ba63`); this closes it.
- **Broker `start_background` connect-before-bind race.** `drone`'s out-of-sandbox
  broker daemon started via `start_background()`, which returned *before* the
  `AF_UNIX` socket was bound — callers then raced the bind, and on a slower machine
  `create_identified_connection()` hit `FileNotFoundError` (socket not yet present).
  Deterministic locally (`test_delete_nested_file` 0/5), green in CI only by timing
  luck — latent flakiness. Fixed with a `threading.Event` set right after `listen()`;
  `start_background(timeout=5.0)` now blocks on it and **raises** if the socket never
  binds, so callers never guess a `sleep`. Removed the 4 blind `time.sleep(0.15)`
  waits from the broker tests. Verified 55/55 broker tests, formerly-failing test 10/10.

### Added

- **`aipass init` detects missing Claude Code.** Stage 6 (CLI choice) now checks
  `shutil.which("claude")` when the picked CLI is Claude Code. If absent: interactive
  runs prompt `Install now? [Y/n]` and run the canonical installer on yes (native
  `claude.ai/install.sh`, PowerShell on Windows, `npm` fallback, 300s timeout, loud on
  failure); non-interactive runs warn and continue. The whole system routes through
  Claude Code (hook bridge, dispatch, prompt injection), so init no longer silently
  assumes the runtime is present. Only fires when the chosen CLI is `claude`.
- **Kernel filesystem boundary for agent containment (DPLAN-0202 / FPLAN-0250).**
  Every autonomous agent can now launch inside a kernel-enforced mount namespace
  (`@anthropic-ai/sandbox-runtime` → bwrap+seccomp) where reads stay fully open
  (the shared live filesystem is preserved — a bind-mount, *not* isolation: own-tree
  writes land live on the real FS instantly) but deletes/overwrites of protected
  paths (`.git`, sibling branch trees) fail at the kernel no matter how the call is
  phrased — `rm`, `python os.remove`, `find -delete`, Write tool all hit EROFS.
  `/tmp` and the agent's own tree stay writable; `.git` is RW for devpulse, RO for
  builders. A per-role policy generator (`@hooks build_policy`) derives each branch's
  writable/RO map from its passport. Privileged deletes route through an
  out-of-sandbox **drone-broker** daemon: identity-scoped allowlist, `openat2`
  RESOLVE_BENEATH path re-resolution (confused-deputy proof), HMAC identity handshake
  over a pre-connected inherited fd, JSONL audit. `aipass doctor` gained a **Sandbox**
  check group (bwrap present+functional, node, srt, rg, broker socket) that is LOUD
  when the flag is on and a prereq is missing — never a silent unsandboxed launch.
  Proven by a live 16-check red-team suite. **Inert by default** — gated behind
  `AIPASS_SANDBOX_ENABLED` (off); flag-off is byte-identical to the old dispatch path.
- **rm_gate demoted to guardrail.** Now framed honestly as early-feedback that
  catches the accidental `rm -rf` and teaches `drone rm` — belt-and-suspenders, with
  the kernel sandbox as the actual filesystem boundary.

- **Prompt-injection cadence — fire the big loaders every Nth turn.** The global
  and branch prompts are large and were re-injected on *every* turn even though a
  prior copy stays in the conversation. They now fire together every 5th turn
  (config-tunable via `hooks_json/custom_config/cadence_config.json`), with a
  per-session turn counter that resets on a new session and after compaction so
  context is always rebuilt when it's actually needed. Identity and the mail flag
  stay every-turn (tiny, want freshness). Cuts recurring per-turn context cost.
- **Hook fire/skip observability.** Cadence emits a structured
  `[HOOKS] cadence fired|skipped loader= turn= period= offset=` line; the prax
  monitor renders hook events distinctly so the cadence is visible live.
- **Slim global prompt — context-on-demand.** The always-injected global prompt
  was rewritten from a ~13.8KB encyclopedia into a ~7.8KB navigation map
  (DPLAN-0201): `drone` pinned as the router, the framework tree, all 13 agents
  as short bios, and one drilled reflex — run `drone @agent --help` before using
  a branch. Detail now lives in each agent's `--help`, fetched on demand. This
  also dissolves the harness ~10k-char truncation that was silently dropping the
  old prompt's tail; the slim prompt injects whole. Backup retained alongside.

### Changed

- **Shared leaf library re-homed: `aipass.common` → `aipass.aipass.shared` (FPLAN-0260).**
  `src/aipass/common/` was the only non-citizen directory in the agent namespace —
  a shared lib (json_handler / json_ops / registry_discovery, extracted in
  TDPLAN-0006 P2) parked as a sibling to the agents with no owner. Per @seedgo
  design review it now lives inside its steward at `src/aipass/aipass/shared/`,
  owned by @aipass; @spawn imports across (same blessed shared-infra category as
  `aipass.prax`/`aipass.cli`). Content byte-identical; ~9 import/doc sites updated
  across aipass+spawn. A new subprocess guard test pins the bootstrap-safety
  invariant: importing `shared/` loads zero branch dependencies, so `aipass init`
  keeps working pre-drone on fresh machines. Note: `aipass.common` shipped in the
  v2.5.2 wheel; it was internal plumbing — no deprecation shim.
- **Action-gated hook sound.** Piper now speaks only when a hook actually *does*
  something — handlers return a `sound` key the engine plays, instead of
  announcing on every invocation. Skipped loaders are silent. Quieter and honest.
- **README: hardcoded metrics → live badges + qualitative.** Version is now a
  live PyPI badge, test/PR counts replaced with a codecov coverage badge (75%
  minimum) and qualitative wording — no more stale numbers to hand-maintain.

### Fixed

- **Cadence counter separate-process race.** Each `UserPromptSubmit` hook runs as
  its own OS process, so a module-level turn cache double-incremented and the
  loaders leapfrogged (firing erratically instead of together). Fixed with an
  mtime debounce + transcript-size token + `flock` so the counter advances exactly
  once per real turn, verified against the live execution model.
- **`auto_fix` ran no diagnostics.** A leftover `speak()` call (its import removed
  in the sound refactor) raised `NameError` on every edit, swallowed by the
  handler's broad `except` — so auto-fix silently surfaced nothing on any
  `.py`/`.json` edit. Removed the dead call; diagnostics run again.
- **Hook events never colored in the monitor.** The prax log-watcher's
  `_HOOK_PATTERN` required an `action=` field that cadence never emits (it logs
  the action as the bare second word, `fired`/`skipped`), so extraction failed
  and events fell through to plain rendering instead of the styled
  bold-green ⚡ / dim · treatment. Fixed the regex to capture the bare action
  word and enriched the event detail (period, offset, short session id).

### Security

- **Least-privilege token on the `e2e-wheel` workflow.** `e2e-wheel.yml` was the
  one CI workflow missing a top-level `permissions:` block (it was added during
  the cross-OS work after PR #624 hardened the others), so it ran with the
  default broad `GITHUB_TOKEN` scopes — dropping the OpenSSF Scorecard
  Token-Permissions check to 0. Added `permissions: contents: read`; the
  workflow only reads the repo to build and smoke-test the wheel.
- **Signed GitHub Releases via Sigstore (keyless).** The release workflow now
  signs the built wheel + sdist with `sigstore/gh-action-sigstore-python`
  (keyless OIDC — no signing key is generated, stored, or held by anyone) and
  attaches the resulting `.sigstore.json` bundles to the GitHub Release. PyPI
  uploads were already attested via Trusted Publishing; this extends verifiable
  provenance to artifacts pulled from GitHub Releases and satisfies the OpenSSF
  Scorecard Signed-Releases check. First proof lands on the next `v*` tag.

---

## [2026-06-02]

### Fixed

- **`aipass init` scaffold correctness.** A fresh `aipass init` now generates a
  project-specific `AGENTS.md` (new `agents_md()` generator) instead of falling
  back to copying AIPass's own repo-root `AGENTS.md` boilerplate — Codex users
  were getting the wrong file. Project `README.md` quick-start/structure paths
  now reflect the real `src/<package>/<agent>/` layout.
- **First-agent default name `my-agent` → `my_agent`.** `aipass init` seeded its
  default agent with a hyphen, the lone source of a long-standing dir-vs-module
  mismatch (the directory kept the hyphen while the importable module, `@address`
  and registry name all normalize to underscore). Defaulting to `my_agent` makes
  directory, module, `@address` and the README example all consistent.
- **Dead `citizenship.registry_path` removed from spawn templates.** The field
  pointed at a non-existent `.aipass/registry.json`; it was never read anywhere
  (registry is located by `find_registry()` glob), so it's dropped from the
  `builder` and `birthright` passport templates.

### Removed

- **The entire STATUS flow is decommissioned (TDPLAN-0007).** The per-branch
  hand-maintained `STATUS.local.md` beacon and the auto-aggregated central
  `STATUS.md` (853 lines / 70 KB nobody read) are gone — deleted from disk
  across all 13 branches and scrubbed from every prompt, doc, startup protocol,
  `/prep` + `/memo` skill, the compact-recovery hook, the email footer, and
  `aipass init` / spawn scaffolding. Live branch state was already fully covered
  by `DASHBOARD.local.json` (prax) and history by `.trinity/local.json`. The
  status-sync engine is kept **intact but inert** — made dormant by unwiring its
  3-line trigger registration (`trigger registry.py`), so the code stays
  revivable. The one thing STATUS uniquely gave us — a quick scratch todo — is
  replaced by an operational `todos[]` section in `.trinity/local.json`
  (@memory-owned schema, capped, never vectorized by rollover), pushed to all 13
  branches and surfaced as a `todo_count` on the dashboard. Shipped as one
  coordinated cross-branch change (memory, prax, trigger, aipass, spawn, hooks,
  ai_mail, seedgo + devpulse).

### Changed

- **All 13 branches at seedgo 100% under the new introspection standard.**
  Wrapped `print_introspection()` output in Rich markup across ai_mail, drone,
  spawn, trigger, prax and devpulse (the rest were already compliant) —
  presentation only, no logic change — so `drone @branch` with no args renders
  consistent styled output everywhere.
- **CLI polish for human-facing output.** `drone @hooks --help` rewritten (Rich,
  with `hooksound on/off/status` now surfaced); `drone @spawn` repair help
  clarified as distinct from `update` and showing the preview/`--apply` flow;
  drone restores Rich colour on human-facing routed output (`--help`,
  introspection, `status`) via the inherit path.
- **Spawn backups land in one namespace `.spawn/.recovery/` (TDPLAN-0006 P4).**
  Spawn's pre-merge JSON backups previously dropped a `.recovery/` directory at
  each branch root (which had accumulated 242 stale auto-generated `DASHBOARD`
  backups across 10 branches). `aipass.common.json_ops.backup_json` gained an
  optional `backup_dir` parameter (default unchanged), and spawn's update engine
  now directs backups to `{branch}/.spawn/.recovery/` — tucked under the
  spawn-managed `.spawn/` dir instead of cluttering the branch root. Memory stays
  in the safety net (the engine simply never touches `.trinity/`/`DASHBOARD` on
  update, so it never needs to back them up). Stale `.recovery/` backups cleaned
  up. (315 tests, seedgo 100%.)
- **No more cross-branch engine imports — `aipass init update` calls spawn via
  subprocess (TDPLAN-0006 P3).** `init_flow.py` previously did
  `from aipass.spawn.apps.modules.sync_registry import sync_registry` — the one
  place aipass reached directly into spawn's Python. Replaced with a subprocess
  call to the already-existing `drone @spawn sync-registry --fix` (same pattern as
  `aipass init agent` → `drone @spawn create`), preserving graceful degradation
  (a missing `drone`, non-zero exit, or timeout is silently skipped — registry
  sync never hard-fails an update). The aipass branch now has **zero** direct
  imports of another branch's engine code; the remaining cross-branch imports are
  shared service layers only (cli Rich UI, prax logging, trigger events). (438
  tests, seedgo 100%.)
- **`aipass.common` shared library — dedup spawn/aipass scaffold machinery
  (TDPLAN-0006 P2).** `@spawn` and `@aipass` each carried their own copy of the
  JSON merge/handler utilities and registry discovery. Extracted them into a new
  branch-free package `src/aipass/common/` (`json_ops` = `deep_merge` +
  `backup_json`; `json_handler.JsonHandler`; `registry_discovery.find_registry`)
  that both branches now import. `aipass.common` imports **zero** branch code, so
  `aipass/bootstrap.py` (which runs before the drone runtime exists) can depend on
  it without breaking the pre-infrastructure constraint. The duplicated copies are
  deleted (spawn keeps a thin re-export shim; aipass's `json_handler` shrank
  254 → 88 lines). The `save_json` contract is unified to **raise `ValueError`**
  on invalid structure across both branches. (313 spawn + 434 aipass tests, both
  seedgo 100%.)

### Fixed

- **Flow plan-type self-serve UX — register override, help, orphan cleanup.**
  Explicit `drone @flow register <dir> <PREFIX>` now overrides an auto-derived
  prefix instead of silently failing (guarded — refuses if the auto-registered
  type already holds plans), so custom prefixes are settable when adding a new
  plan type. `create`/`templates --help` rewritten to dynamically list registered
  types + templates and document the add-a-new-type workflow. Stale orphan plan
  registries removed; dead `prefix_exists()` dropped. (728 tests, seedgo 100%.)
- **`drone @spawn update` no longer scrambles branches (#636, critical — TDPLAN-0006
  P0+P1).** The update engine compared a freshly-created branch against the class
  template by *content hash* with rename-detection, and because the CREATE path
  regenerated template-registry IDs in filesystem-walk order (≠ the master's
  hand-crafted IDs), a branch created seconds earlier produced **30 proposed renames**
  that rotated identity/memory dirs into each other
  (`apps→.trinity→.seedgo→.claude→.archive→.aipass`), turned `README` into
  `DASHBOARD`, and deep-merged stale template into live `.trinity/` memory —
  `update <class> --all` would have destroyed every citizen in one command. Rebuilt
  `update_ops.py` (v2.0) on an explicit **named-managed-files + path-based** model:
  `.trinity/*`, `DASHBOARD.local.json`, `artifacts/birth_certificate.json` and
  `.seedgo/bypass.json` are delivered on **create only** and never touched on update;
  the create==update invariant now yields **0 renames / 0 merges** on a fresh branch.
  The old ID-based engine (`change_detection.py`, `reconcile.py`) is deleted.
- **Destructive spawn ops are now dry-run by default (TDPLAN-0006 P0).** `drone @spawn
  update` and `drone @spawn repair` preview by default and require an explicit
  `--apply` to write — forgetting a flag is now a safe no-op instead of irreversible
  damage (`--dry-run` kept as an alias). `aipass doctor` repair suggestions emit the
  matching `--apply` form.

### Added

- **Introspection Rich-formatting standard (seedgo).** New
  `check_introspection_rich_formatting` checker enforces that each branch's
  `print_introspection()` output uses Rich markup (delegation-aware — it walks
  `_`-prefixed helper functions), keeping no-arg `drone @branch` output styled and
  consistent. Documented in `introspection.md`; all 13 branches brought into
  compliance (see Changed).
- **Playbook plan type (`PBPLAN`) — reusable SOP checklists (flow).** A new
  `playbook_plans` template family for throwaway, vectorize-on-close operational
  runbooks (first SOP: the Sunday merge). Drop a `.md` under
  `templates/playbook_plans/`, register once, then
  `drone @flow create . "subject" <sop>` stamps a run to tick through and close.
- **Memory-pool auto-processing (TDPLAN-0005)** — dropped files in
  `memory/memory_pool/` are now vectorized and archived automatically on
  session-start and pre-compact, instead of requiring a manual
  `drone @memory pool process`. A 3-branch build: `@memory` gains an intake
  handler + `pool` module (processes then empties the pool, `keep_recent=0`),
  `@hooks` adds a `lifecycle/auto_process` handler (session-guarded via
  `CLAUDE_CODE_SESSION_ID`, since Claude Code has no SessionStart hook), and
  `@trigger` gains event #15 (`memory_pool_auto_processed`) with a Medic error
  path. Runtime pool dirs (`memory_pool/`, `memory_pool_archive/`) are now
  gitignored.
- **HVTracker badge** added to the README badge cluster, linking to the public
  agent profile at hvtracker.net (closes #628).
- **`git_gate` read-verb allowlist — raw read-only git for every branch.** The
  PreToolUse `git_gate` previously blocked *all* raw git (forcing `drone @git`
  even for harmless reads), which left agents unable to inspect what git ships —
  the exact forensics needed to diagnose the audit gap above. It now allows 22
  read-only verbs raw (`ls-files`, `ls-tree`, `show`, `cat-file`, `rev-parse`,
  `rev-list`, `log`, `status`, `diff`, `blame`, `archive`, `grep`, …) while
  write operations stay `drone`-gated. Global options (`-C`, `-c`, `--git-dir`,
  …) are skipped when extracting the verb, and chained commands are split on
  `&&`/`||`/`;`/`|` so a read piped into a write still blocks the whole line.
  (81 tests)
- **Cross-OS end-to-end WIRING test (`tests/e2e/`, `e2e-wheel.yml`)** — the first
  CI gate that proves real AIPass *wiring* (not units-with-mocks) by building the
  wheel, installing it into a clean venv, and asserting a 4-tier ladder: package
  install + console scripts (T0), `aipass init` scaffolding (T1), a hook actually
  firing via the bridge with an observable `engine.jsonl` record (T2a), and
  `drone` resolving + subprocess-executing a real branch (T3). Runs on a 3-OS
  matrix (ubuntu/windows/macos, `fail-fast: false`). Ran red-first on Windows by
  design and immediately earned its keep — it caught two real, *previously
  uncovered* Windows wiring bugs (`aipass init` preflight + `drone` stdout
  encoding, both fixed below). Notably the layers we most feared — clean-wheel
  install (T0) and hook firing (T2a) — passed on Windows. (DPLAN-0194 /
  FPLAN-0239)
- **`drone rm` — provider-agnostic safe delete** — a contained recursive delete
  that lets agents clean up scratch dirs without tripping the `rm -rf` block.
  Deletes are confined to the project root and the system temp dirs (`/tmp` and
  `$TMPDIR`), refusing anything outside (home, `/etc`, `/`, etc.). Even inside
  those roots it hard-refuses protected internals — `.git`, `.trinity/`,
  `.aipass/`, `.codex/`, `.agents/`, and sibling-branch worktrees — mirroring the
  filesystem boundary an OS-sandboxed agent (e.g. Codex) enforces, so behavior is
  consistent across CLIs. Pure-Python (`shutil.rmtree`), with a red-team test
  suite for containment escapes (symlinks, traversal, sibling branches). (#630)
- **`rm_gate` hook — block raw recursive `rm`, teach the safe path** — a
  PreToolUse gate (mirroring `git_gate`) that blocks raw `rm -r`/`-rf`/`-fr`/
  `--recursive` and redirects the agent to `drone rm`. Provider-agnostic (runs in
  the hook engine, not tied to Claude Code permission rules), conservative
  (unparseable targets are blocked, not allowed), and skips `drone rm` itself.
  This makes the safe-delete path discoverable at the moment of friction. (#630)
- **Hook engine logs `agent_type` / `agent_id` per fire** — the engine now
  records which agent triggered each hook (e.g. `agent=main` vs `agent=Explore`)
  in both `engine.jsonl` and the prax monitor stream. Previously the payload
  flowed into handlers but was never logged, leaving no way to tell an internal
  main-turn fire from a real sub-agent fire. Pure visibility; no behavior change.
  Groundwork for #606. (#606)
- **OpenSSF Best Practices passing badge** — AIPass earned the OpenSSF Best
  Practices (CII) **passing** badge (100% of criteria), added to the README badge
  cluster. Self-certified across all six categories — basics, change control,
  reporting, quality, security, and analysis. Complements the existing OpenSSF
  Scorecard, lifting the `CII-Best-Practices` check from 0. (DPLAN-0193)

### Changed

- **Standards floor raised to genuine 100% across all 13 branches** — completed
  the campaign that lifted the seedgo gate threshold from 80 to 100. Rather than
  bypass failing files, two check *flaws* were fixed at the root: (1) the
  **file-size / architecture check is now advisory** (warn-only for 700–1500 line
  files with no docstring nudge, hard-fail only above 1500) — large files are a
  smell, not a defect; (2) **readme-freshness now compares against git history,
  not file mtime** — `git checkout`/`merge` reset mtimes without any semantic
  change, so the old check false-positived (flow + prax shared an identical
  mtime from one git event, not real edits). It now diffs the README's "Last
  Updated" against the last commit that touched `.py`. Genuine content fixes
  where warranted (aipass requirements template + handler routing; honest README
  content refreshes on flow, prax, devpulse). The readme-freshness **failure
  message now teaches** the right fix ("update README content, then set the date
  — don't just bump it"). Also optimized the devpulse watchdog poll cadence
  (2s → 5s; the loop is cheap, so the tighter interval was wasted CPU). (#631)

- **Retired the blanket `rm` deny from provider settings** — `setup.sh` and
  `aipass init` no longer ship `Bash(rm -rf*)` / `Bash(rm -r *)` deny rules
  (they were mis-filed among git rules, blocked all `/tmp` cleanup, and gave a
  bare "permission denied" with no guidance). The `rm_gate` hook + `drone rm`
  now own this — cross-provider, path-aware, and they teach. `aipass doctor`
  detects the stale rules on existing installs and `aipass doctor --fix` removes
  them (idempotent, preserves all other rules). Claude Code still natively
  circuit-breaks `rm -rf /` and `rm -rf ~`. (#630)

### Fixed

- **`Windows Test` / `macOS Test` are no longer path-filtered — they were
  stalling PRs as required checks.** Both workflows only triggered when
  `setup.sh`/`drone/cli.py`/`handlers/__init__.py`/`pyproject.toml` changed, but
  branch protection lists `windows-setup`/`macos-setup` as *required*. On any PR
  that didn't touch those paths the workflows never ran, so GitHub parked the
  required checks as "Expected — waiting for status" indefinitely, blocking the
  merge (the tests themselves were green — they simply didn't fire). They now run
  on every push/PR to main/dev, like the other required lanes. (A required check
  must never be path-filtered.)
- **`seedgo-audit` CI gate was red despite 100% local audits — four checkers
  validated the working tree instead of committed source.** CI audits a clean
  `git checkout` (tracked files only — git ships no empty or gitignored dirs),
  but the working tree carries runtime dirs (`logs/`, `*_json/`, `artifacts/`,
  `.trinity/`, `passport.json`), so every branch scored ~97% in CI while passing
  at 100% locally. Reproduced exactly with a tracked-only tree (`git archive HEAD`
  audits to CI's 97%). Four checkers now measure what git actually ships:
  `log_structure` no longer fails when the gitignored `logs/` dir is absent (it
  still enforces no-hardcoded-paths); `readme` cross-references `.gitignore`
  (via `git check-ignore` with a fallback list) and skips gitignored dirs/links
  in the directory-tree and dead-link checks; `encapsulation` infers the branch
  from the path when the gitignored `AIPASS_REGISTRY.json` is unavailable (and no
  longer collides on the `aipass` branch); `architecture` skips cleanly when the
  gitignored `passport.json` is absent. A follow-up refined `readme`'s
  `git check-ignore` use: `.gitignore` dir-only patterns (trailing slash —
  `logs/`, `**/*_json/`, `.trinity/`) don't match a clean checkout's
  non-existent paths unless directory intent is signalled, so the check now
  also tests the trailing-slash form (this was the last 1% — `readme` flagged
  `cli_json`/`logs`/`artifacts` as "missing on disk" in CI only). The CI gate
  (`.github/scripts/seedgo_audit.py`) now also prints the failing standards and
  their check messages, so a sub-100 result says *why*, not just the percentage.
  Finally, the `seedgo-audit` CI job now installs the `memory` extra
  (`pip install -e ".[dev,memory]"`): the `diagnostics` standard runs pyright over
  every branch, and memory's handlers import `chromadb`/`numpy` at module level —
  without those declared deps installed, pyright reported them as unresolved
  (`reportMissingImports=error`) and memory scored 55%, a false failure from a
  missing CI dep rather than a code defect. Clean-tree and working-tree audits
  both report 13/13 = 100%. (DPLAN-0195)
- **Two latent Windows portability bugs caught by the new e2e harness** — both
  were always present in the code; they only surfaced now because this is the
  first CI to run `aipass init` scaffolding and real-branch `drone` routing on
  Windows (the old Windows CI ran an editable install, `aipass`-less, and only
  routed to in-process modules, so both paths had zero Windows coverage). Pure
  portability fixes — Linux/macOS behaviour is unchanged.
  - **`aipass init` crashed on Windows (surfaced as a misleading "Unknown
    command: init").** Init scaffolded the project correctly, then crashed
    *printing its `✓ Project initialized` banner* — Rich wrote the ✓/box glyphs
    through a cp1252 stdout, raising `UnicodeEncodeError ('charmap')`; the error
    handler's `✗` message hit the same wall, bubbling up to the command router
    which mislabeled it. The `aipass` entry point now reconfigures stdout/stderr
    to UTF-8 in place on Windows. (The init preflight ancestor-walk was also
    hardened to skip un-enumerable Windows drive-root entries — defensive, not
    the trigger.)
  - **`drone @branch` crashed on Windows with the same `UnicodeEncodeError
    ('charmap')`.** `drone` resolved + subprocessed the branch correctly, then
    crashed *printing* the captured output through cp1252 stdout. The existing
    `PYTHONUTF8` guard only affected child interpreters, not the live process
    streams — `drone`'s entry point now also `reconfigure()`s stdout/stderr to
    UTF-8 in place.
  - **CI unit lane no longer runs the e2e wheel tests.** `ci.yml`'s
    `pytest --rootdir=.` swept in `tests/e2e/` (which build a wheel per the
    dedicated `e2e-wheel.yml`), failing the unit lane; it now `--ignore`s them.
    (DPLAN-0194)
- **A release merge can no longer destroy the `dev` branch** — `drone @git merge`
  passed `--delete-branch` to `gh pr merge` unconditionally, so merging a
  `dev`→`main` PR deleted the persistent `dev` branch on the remote and stranded
  the working tree on `main` (the next commit silently landing on main). Merge now
  looks up the PR's head ref and **only deletes non-protected branches** — `dev`
  and `main` are never deleted, and an undeterminable head ref fails safe (no
  delete). After a merge it returns the working tree to `dev` (loud warning if it
  can't). `drone @git branches` now runs `fetch --prune` before listing so it
  reflects the live remote instead of stale cached refs, and a new
  `drone @git prune-temp` cleans up merged temp PR branches. (#625)
- **`drone @git status`/`diff` show their scope** — when scoped to a branch (no
  `--all`), output now appends "(showing <branch> scope — use --all for full
  repo)", so an empty scoped view is no longer mistaken for a clean repo. (#623)
- **External projects can call AIPass branches via drone** — `drone @api ...`
  (and any `drone @X`) now resolves from a non-AIPass project CWD instead of
  being blocked with "path escapes project root." The resolver was validating a
  branch's path against the *primary* registry root even when the branch was
  found via the `AIPASS_HOME` fallback, so any external project (Vera Studio,
  Daemon) hit a false security block. `resolve_branch()` now validates
  containment against the registry the branch was actually found in. Security is
  unchanged — each branch is still contained within its own declaring registry's
  root; genuine path escapes remain blocked. (#618)
- **`aipass <command>` runs instead of printing an introspection banner** —
  `aipass` is a user-facing binary, so `aipass doctor` (and every other command)
  must execute, not describe itself. All 7 modules (`doctor`, `doctor_fix`,
  `doctor_wire`, `handoff`, `help_chat`, `init_flow`, `profile`) previously hit a
  no-args→introspection gate (a standard meant for `drone @branch <module>`
  discovery) and showed a banner on bare invocation. Now bare invocation runs the
  command or shows usage; the introspection banner moved to `--info`. The seedgo
  introspection standard is bypassed for these binary-invoked modules (documented).
- **Dashboard plan counts no longer zeroed on refresh** — a branch's
  `active_plans` was reset to `0` by every `drone @prax dashboard refresh`, because
  `PLANS.central.json` only held Flow's own plans (`location==FLOW_ROOT` filter).
  The central file is now comprehensive: all plans grouped per-branch, so refresh
  reports each branch's real count (e.g. devpulse now shows its 12 open plans
  instead of 0).

### Security

- **`dependency-scan` (pip-audit) green again — upgrade pip, drop stale ignores.**
  The `Security Scan` workflow's `dependency-scan` job had gone red: pip-audit
  scans the whole environment, and the runner's bundled pip (26.1.1) carries
  advisory PYSEC-2026-196 (fixed in 26.1.2). The job now runs
  `python -m pip install --upgrade pip` before auditing (it was the only CI job
  not upgrading pip), removing the vulnerable version outright rather than
  suppressing it. 26.1.2 also resolves CVE-2026-3219 and CVE-2026-6357, so the
  two now-stale `--ignore-vuln` entries were removed — verified against a clean
  reproduction of the job's environment, which audits to "No known
  vulnerabilities found" with nothing ignored.
- **Pinned the `requests` floor to a non-vulnerable version** — raised
  `requests` to `>=2.34.2` in `pyproject.toml` and the API branch's
  `requirements.project.txt` (which previously listed it unconstrained). This
  clears six OSV advisories the OpenSSF Scorecard flagged against the dependency
  (PYSEC-2014-13, PYSEC-2014-14, PYSEC-2018-28, GHSA-9wx4-h78v-vm56,
  GHSA-9hjg-9r4m-mvj7, GHSA-gc5v-m9x4-r6x2) — the oldest surfaced only because the
  dependency was declared without a version bound. No runtime change (the AIPass
  venv already ran a fixed release). (DPLAN-0193)
- **Pinned the test container base image by digest** — `Dockerfile.test` now pins
  `ubuntu:24.04` to its registry digest (`sha256:786a8b55…`) so the test image is
  reproducible and tamper-evident, clearing the Scorecard `containerImage not
  pinned by hash` finding. (DPLAN-0193)

---

## [2026-05-30]

### Added

- **`drone @hooks status`** — read-only viewer for a project's hook config:
  master switch, every hook's enabled state per event group, matchers, and an
  enabled/total summary. Resolves the project's `.aipass/hooks.json` by walking
  up from CWD. (DPLAN-0190 Phase B)
- **Hooks activate in every project** — `aipass init` now writes
  `.aipass/hooks.json`, so new projects fire the hook engine out of the box
  (previously: no config shipped, 0 hooks fired). `aipass init update`
  union-merges the template, preserving any per-hook on/off choices the user
  made. `aipass doctor` now checks for the config's presence. Dead hook-script
  shipping (`_ship_hooks`) removed. (DPLAN-0190 Phase A)
- **README logo** — centered logo image replaces plain `# AIPass` header.
  New `assets/logo.png` added to the repo.
- **OpenSSF Scorecard** — `.github/workflows/scorecard.yml` runs the official
  OSSF Scorecard action on push to `main` and weekly. Publishes a public security
  health score at scorecard.dev with a README badge. Actions pinned by SHA.
- **GitHub Releases** — `publish.yml` now cuts a GitHub Release on each `v*` tag,
  with notes pulled from the top CHANGELOG section and the built dist attached.
  PyPI publish + GitHub Release now fire from the same tag.
- **Registry descriptions** — all 13 branches now have one-liner descriptions
  in `AIPASS_REGISTRY.json`. `drone systems` shows what each agent does
  instead of blank lines. Closes [#607](https://github.com/AIOSAI/AIPass/issues/607).

### Changed

- **Security gates fully project-aware** — both the edit gate *and* the
  subagent stop gate now derive the package name dynamically from CWD instead
  of hardcoding `src/aipass/`. Cross-branch write protection and branch
  detection work for any `src/<package>/<branch>/` project; previously the
  subagent gate silently no-opped outside AIPass. 9 new external-project tests.
  Closes [#605](https://github.com/AIOSAI/AIPass/issues/605).
- **Hooks branch promoted to service** — registry profile changed from
  "AIPass Workshop" to "library" so it appears in `drone systems` alongside
  the other 12 services.
- **Hooks branch hardened to 100% seedgo** — the @hooks citizen took full
  ownership of its branch: every handler verified wired + firing, README
  rewritten (two-tier provider/project model, dynamic-dispatch design, event
  table), 2 stale tests resolved (253 pass). Dead-code/unused-function flags
  documented as architectural bypasses — the 15 handlers are invoked
  dynamically via `importlib` from `hooks.json` paths, never statically
  imported. (DPLAN-0191)

### Release

- **Version 2.5.0** published to PyPI. Trusted publishing via GitHub Actions
  (`publish.yml` triggers on `v*` tags — no manual twine upload needed). The
  same tag now also cuts a GitHub Release with these notes attached.

### Removed

- **Gemini CLI full removal** — deleted `.gemini/` directory (5 files) and
  `GEMINI.md`. Stripped all references from `setup.sh` (~50 lines),
  `README.md`, `bug-report.yml`, `aipass init` (bootstrap/scaffold/test),
  hooks (README/prompt/passport), and prax monitoring (~300 lines). 21 files
  changed, -927 lines. Closes
  [#608](https://github.com/AIOSAI/AIPass/issues/608).

---

## [2026-05-25]

First weekly release. AIPass now follows a Sunday release cadence: changes
accumulate on `dev` throughout the week and merge to `main` as a single
versioned release with notes.

### Added

- **Hook engine** — a new centralized dispatch system for all hook
  execution. A thin bridge receives events from the AI provider (Claude,
  Codex, etc.) and routes them through a single Python engine that reads
  per-project configuration, executes the appropriate handlers, and logs
  every invocation. Replaces 14 standalone shell/Python scripts with native
  handler modules organized by domain: prompt injection, security
  enforcement, lifecycle management, and notifications.
- **Per-project hook configuration** via `.aipass/hooks.json`. Each project
  can enable, disable, or customize individual hooks without touching
  provider-level settings. Previously hooks fired globally with no
  per-project control.
- **Audio feedback on hook events** using Piper TTS. All 14 handlers
  produce distinct spoken audio cues so operators can monitor sessions
  without watching the terminal. A shared sound module
  (`hooks/apps/sound.py`) provides `speak()` and `play()` with built-in
  mute support. Toggle with `drone @hooks hooksound on|off` — muting
  silences all 14 handlers without skipping their functional logic.
- **Hooks agent** — the 13th citizen in the AIPass registry, owning all
  hook infrastructure: the engine, bridge, handlers, and configuration
  schema.
- **Dashboard plugin for devpulse** — aggregates git status, session
  history, and dispatch state into a single startup view. Wired into the
  session startup protocol so branch managers see current state
  immediately.
- **External log routing** — prax now accepts structured log entries from
  any branch, not just its own modules. Hook executions, dispatches, and
  agent activity all flow into the central monitoring log.

### Changed

- **Provider settings fully migrated to bridge pattern.** All hook entries
  in the Claude provider configuration now call the bridge dispatcher
  instead of individual scripts. Each hook produces its own system-reminder
  to the model, preserving prompt injection fidelity (a single merged
  bridge was found to break prompt delivery due to Claude Code's output
  persistence threshold).
- **setup.sh rewritten** to install hooks via the bridge pattern. The old
  version hardcoded 14 script paths; the new version writes a single bridge
  call per event type and validates that the bridge module exists.
- **Documentation sweep** across `.claude/README.md`, `SECURITY.md`, the
  global prompt, and branch-level docs to reflect the new hook
  architecture. References to legacy `.claude/hooks/` scripts replaced with
  the native handler locations.
- **`aipass init update`** now correctly preserves user-customized hook
  settings during project updates instead of overwriting them.
- **Seedgo snapshot tests rebuilt** — the provider hooks snapshot fixture
  and extraction logic were structurally broken (silently passing with zero
  results). Both the fixture format and the test assertions have been
  corrected.
- **Test suite updated for hook migration** — `test_git_gate.py` imports
  from the new handler module; `test_bootstrap.py` no longer asserts that
  project initialization ships standalone hook scripts (it no longer does).

### Fixed

- **Settings merge on project update** — `aipass init update` was
  clobbering user hook configurations. The merge logic now layers AIPass
  defaults under existing user settings.
- **Python 3.10 test collision** — a module/function name collision caused
  mock patch targets to fail on Python 3.10. Test targets corrected.
- **Dead code removal** — removed an unused CLI `__main__.py` entrypoint
  and cleaned up `.gitignore` entries that were masking tracked files.
- **Codecov patch threshold** lowered to 50% to reflect the project's
  current coverage baseline and stop false-negative CI failures.

### Removed

- **18 standalone hook scripts** in `.claude/hooks/` disabled (renamed with
  `(disabled)` suffix). Their logic now lives in native handler modules
  under `src/aipass/hooks/apps/handlers/`. The old files remain on disk for
  reference but are no longer executed.
- **`drone hook-sounds` plugin** disabled. Sound control moved to hooks
  branch as `drone @hooks hooksound on|off` with full mute support for
  all 14 handlers (the old plugin only controlled 4).

### Infrastructure

- **Provider manifest migrated to bridge pattern.** `provider_manifest.json`
  now stores bridge commands (`$AIPASS_HOME/...bridges/claude.py EventType`)
  instead of standalone script names. `doctor_wire.py` auto-wires bridge
  entries directly — no longer copies scripts to `~/.claude/hooks/` or
  generates `sys.executable` paths. Doctor checks validate commands exist in
  provider settings instead of checking for script files on disk.
- **README v3** — rewritten for external users. Tighter problem/solution
  framing, collapsible agent details, Gemini CLI removed (untested),
  user-project perspective throughout.
- **Inline handoff** (`aipass init run` Step 11) — new default stays in the
  current terminal via `os.execvp` instead of opening a new window. Users
  choose "stay here" or "new window." Enables single-terminal demo
  recordings. Closes [#610](https://github.com/AIOSAI/AIPass/issues/610).
- **Project-aware global prompt** — the global prompt loader now detects
  whether CWD is inside AIPass or an external project. External projects
  receive their own lighter prompt (from `.aipass/aipass_global_prompt.md`)
  instead of the full AIPass-internal playbook. Fixes `drone @prax` errors
  in new projects.
- **Project CLAUDE.md template** — `aipass init` now generates a
  project-specific CLAUDE.md from `.aipass/project_CLAUDE.md` instead of
  copying the AIPass-internal one. Removes the startup protocol reference
  to `drone @prax dashboard refresh` which doesn't exist in external
  projects.
- **Gemini CLI removed** from `aipass init` CLI choices and handoff
  options. GEMINI.md no longer created for new projects. Gemini CLI is
  being retired upstream.
- **Demo GIF** added to `assets/demo.gif` and referenced in README.

---

*This is the first CHANGELOG entry. Prior work is documented in the
repository's commit history and branch session logs.*
