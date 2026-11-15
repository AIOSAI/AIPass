# CPLAN-0005: Linux-only purge, end of onboarding, fallback map: capture of 2026-11-14

Tag: linux-only, purge, onboarding, fallbacks, sentry-bypass, docker

> The day AIPass became Linux only: what was cut, what the three sweeps found, the end of onboarding, and the fleet-wide fallback map.

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

Devpulse session #902, 2026-11-14, the owner at the seat all day. Work plan: FPLAN-0923 (purge AIPass of every Windows and macOS piece). Raw evidence lives in the session scratchpad (per-task report.md files, the two scanners and their TSVs, the per-branch lists); the scratchpad is temporary, so the substance is written here.

## The Capture

### 1. Rulings of the day (the owner's, in order)

- AIPass is Linux only: Ubuntu, native or WSL2. Docs say what we are ("Linux only, built and tested on Ubuntu"), never a list of what we are not.
- The line for every cut: a piece that exists only because of Windows or macOS goes; a piece whose removal changes what happens on Linux stays. WSL pieces stay and we keep building with WSL in mind, even though we cannot test it.
- History is never rewritten. Bad tests are removed, not improved. Do not trust green as green.
- Nothing is deleted: whatever comes out is moved to the owning branch's .archive (said 22:49, after earlier briefs had said "delete"; corrections were mailed).
- Map fully before removing: callers, importers, tests, bypass rows, docs, prompts.
- No fallbacks. Fail loud and fix the root. A defined empty state is fine; a substitute answer is not. (Compass #304 already says this.)
- Docker: an image is published on a release tag, never inside CI, never blocking CI. Secrets must never live in the image. Testing the image is parked.
- Onboarding is over. AIPass is a CLI infrastructure heading toward an operating system for power users who build on it (Seed, BAUD). Not sold, no hand-holding; a small group of people who put the effort in is the audience. Seed is the easy product. The install stays helpful about the machine: it shows what it installs, runs the full doctor, prompts only before a machine change (yes/no, with a warning on no), ends on a list of warnings, writes a report into devpulse's dropbox and prints one command to wake devpulse. No chat, no terminal launch. Devpulse is the admin seat the user talks to; aipass is the machine concierge (Wi-Fi, USB, heat, battery, flicker). The aipass branch's main functions (init, doctor, spawn-facing pieces) stay untouched: they are intertwined.
- STATUS.local.md was retired long ago and every reader of it goes.
- Open at capture time: whether the install should end by auto-launching BAUD and whether --no-baud goes (the owner floated BAUD as a mandatory part of the install).

### 2. What was cut (sweeps 1 and 2, committed on dev, unpushed)

Sweep 1 removed the Windows and macOS code, tests, CI lanes and docs across all branches. Sweep 2 used two scanners (os_scan.py, the gate; wide_scan.py, 17 word families) and cut stragglers in ten branches: sentry (.pyd extension, os.sep no-ops, skip reasons), api (getpgid/getsid/SIGKILL guards, creationflags), hooks (WinError docstring, tzset skip), drone (O_BINARY, symlink-utime skip), prax, aipass (scaffold gitignore, geteuid fallback), spawn, flow (SIGPIPE skip), ai_mail (double-spelled venv check), memory (parked win32 block). backup kept its *.dll / *.dylib / *.exe filters: they are a binary filter that .NET on Linux also hits. BAUD got its own cleanup (repo commit 38795ab, 13 files, 157 lines out): windows_subsystem, the win32 block, the non-Linux stubs in browser.rs / sessions.rs / screenshot.rs, target-specific Cargo tables.

Kept on purpose: hooks' security gates for .exe/.cmd/.bat/.ps1 and backslash or drive-root spellings; sentry's /Users/ and C:\\Users\\ home-path privacy guards; the stdout reconfigure(utf-8) blocks; CRLF handling; WSL interop (git.exe from Linux).

Docs: README banner "AIPass is Linux only. It is built and tested on Ubuntu: native, WSL2, and a Docker image to come."

### 3. Docker

Dockerfile (ubuntu:24.04 pinned by digest, non-root user, the release wheel installed into /opt/aipass, then `aipass install --non-interactive --no-baud --source /src` run at build from a BuildKit named context repo=.git, so generated and ignored files exist in the image). .github/workflows/docker-publish.yml publishes to ghcr on a v* tag or by hand (:version + :latest, :edge for manual), plain docker CLI, no third-party actions. Never yet run on GitHub. Local build ~2 minutes, 3.09 GB (about 2.1 GB reachable with safe cuts). Inside: 18 agents with memory files, Claude settings wired, Codex hooks and the OpenCode plugin present; OpenCode answered headless on a free model with no login; Claude and Codex ask for a login, which is all a user should have to do. Finding on the way: hatch reads only the root .gitignore, so a locally built wheel swept in memory's private archive (6,107 files); fixed with an exclude in pyproject.toml. The local test image still holds that archive and must never be shared.

### 4. The dead-cwd guard (settled by experiment)

On Linux a process's working directory can be deleted under it. Path('/abs').resolve() still works; Path('rel').resolve() and os.getcwd() raise FileNotFoundError. All 1,297 aipass.*.apps modules were imported from a tree whose cwd had really been deleted, on Python 3.10, 3.12 and 3.14: zero resolve errors (3.11 and 3.13 read, not run). So the guard around __file__ (module_root.py, module_file(), the _THIS_FILE try) is Windows-only and goes; the _frame_path try in the 19 handler fences protects a real Linux case and stays. Tests that truly delete the directory or deny os.getcwd stay; tests that fake a Windows failure go. 34 line-pinned bypass rows and three agent prompts (api, hooks, skills) reference the helper and must move with it. Real Linux bug found beside it: ai_mail/apps/handlers/paths.py:66 falls back to Path.cwd() at import.

### 5. Sweep 3: do not trust the green

- Sentry bypass rows (about 1,072 active): a waived finding is scored as a pass at 100 and the output never says how many were waived. With --no-bypass the fleet goes from 4 violations to 848 (sentry 268, hooks 136, commons 69, memory 56, prax 54, aipass 44). Up to 373 rules match no finding at all; most waive a whole file. Sentry's own prune sees a line-pinned row as dead only when the line is past end of file, and the row's `pattern` field is never read by the matcher (26 rows waive a whole standard because of it). hooks alone had 130 dead rows.
- Sentry never audits: shell scripts, workflows and other YAML, Dockerfiles, tests/e2e, tools/, .claude/hooks, skills/lib, anything under tests/ not named test_*.py or conftest.py, anything named (disabled), and aipass/shared/ (no ruff, no type check). A file that does not parse scores 100 on about 40 checks. A standard that fails to import is dropped from the audit at INFO and the rest stays green. A corrupt registry audits zero branches.
- CI: ci.yml runs lint only; the full lane is parked as ci.yml(full_disabled) "until the Linux-only structure settles".
- Tests: skips guarding things Ubuntu always has (bash, /dev/fd, /proc, symlinks); tests that never run (sentry batch7 json structure, three in test_aipass_standards, memory test_vector, the WATCHDOG_INTEGRATION pair); drone's commit-gate tests skip when ruff is not on PATH; one false pass in memory test_watcher.
- Command smoke: about 514 help, read and dry-run commands across 18 branches, no traceback. Help-text defects only (hooks lists two commands that do not exist; trigger, skills, memory, prax wording).
- Test litter: skills/tests/test_dead_cwd_imports.py creates a real probe-skill in ~/.aipass/skills.

### 6. The fallback map (about 5,600 sites counted, about 870 read by eye)

Two patterns repeat in every branch.

Corrupt file read as empty or default, then overwritten or acted on: hooks trust_registry.py (wipes every enrollment), prax json_service.py:253-280 (replaces any branch's config or log with defaults; reproduced), api host/tokens.py, devpulse watchdog registry/timer/feed (a bad cursor drops the whole backlog), memory config_loader.py (per-branch overrides vanish), ai_mail registry/read.py (a broadcast reaches 0 branches) and wake.py (default model grant), trigger ci/ledger.py, memory auto_process.py (half-written lock read as stale).

A gate or check that cannot run reads as passed: hooks engine.py:319-325 (unparseable stdin skips every pre-tool gate), hooks edit_gate.py (shim for "an older @memory"), memory memory_files.py:222-226 (writes past its own limits check), drone commit_handler.py:103 (no ruff means lint passed), trigger error_detected.py (breaker stand-ins always allow), sentry branch_audit.py and discovery.py, spawn registry.py:58 (delete protection answers "not protected"), devpulse owner/guard.py (import error falls to a path-name check with no email).

Also: crashes in memory and ai_mail routing surface as "Unknown command"; a broken drone module is reported as "unknown command"; prax logs at INFO so every debug-level fallback is silent; a corrupt project registry hands over to the home registry; pyyaml is not a declared dependency, so skills parse frontmatter with a second parser on a base install.

In the code the word itself appears about 350 times in product Python and 450 in tests; sentry already has standards named silent_catch and logged_fallback, and "best effort" and "graceful" are the usual disguises.

Caution recorded: making prax's shape check raise would break any live config that fails it today; that list must be made first.

### 8. Process notes (for a possible write-up; the owner wants this as a case study)

Scale: about 299,000 lines of product Python in 1,637 files and about 346,000 lines of tests in 785 files, across 18 branches, plus BAUD (Rust and Python) in its own repo. One owner, one admin seat (devpulse), one host with limited CPU.

How the day ran:
- The owner spoke in plain dictated speech, often garbled by the speech-to-text, never in tickets. Rulings came mid-work ("WSL stays", "we hate fallbacks", "nothing is deleted, archive it", "done with onboarding") and each became a rule in the next brief within minutes.
- Three kinds of worker, by cost. Citizens (branch owners with persistent memory): heavy on CPU, max two awake, they own their code and do the edits. Sub-agents (disposable, opus or sonnet): light, up to ten at once, read-only investigators or one-branch builders. The seat: reads reports, decides, briefs, reviews diffs, commits.
- Every investigator got the same written brief: read-only, map before proposing a removal, do not trust green, "not checked" beats a guess, write a report file, say what you read by eye versus by pattern. Reports land as files, so the seat's context holds conclusions, not file dumps.
- Sweep 3 in numbers: 10 investigators on bypass rows, skips, the fleet audit, command smoke (514 commands) and the dead-cwd map; then 5 on fallbacks (5,641 sites); 1 to merge 15 reports into 18 per-branch lists; then builders and owners. About 190 background tasks over the session.
- Budgets were set in conversation: "ten sub-agents", "sentry gets five, you get five".
- Disagreement between agents was useful: one agent said keep the dead-cwd guard, another proved by importing 1,297 modules from a deleted directory that only half of it matters on Linux. Both were right about different halves.
- What went wrong, honestly: the seat misread one instruction (told aipass to cut the init stages; the owner meant only the concierge chat) and three briefs said "delete" before the owner said "archive"; corrections were mailed and nothing had been committed. One sub-agent ran a write command against a read-only brief. A few greps touched .archive. An idle sub-agent kept waking on its own timers until stopped. Each was caught because nothing lands without a diff review and a commit by the seat.
- What made it work: every branch has an owner who knows its code and keeps memory; git and mail go through one door (drone); hooks refuse the dangerous shapes; the seat's own memory files survive context compaction. The chat was compacted several times during the day; continuity came from .trinity, the plan files and the report files, not from the chat window.
- The owner's estimate: with a machine of 24 cores and 128 GB the same work would finish in about an hour after an hour of planning; on this host it takes several, the limit being CPU for citizens, not coordination.
- Lesson of the day: a green audit meant "nothing unwaived was seen in the files it looks at". 848 findings sat behind waivers and about 5,600 fallbacks behind no name at all. A purge for one reason (Linux only) exposed a second problem (false green) and a third (silent fallbacks).

### 9. The verification pass (the step that paid for itself)

Before any owner worked a list, five read-only agents checked every item of the other 16 lists against the tree and wrote verified lists (scratchpad sweep3/lists/verified). The merged lists were leads from 15 reports; a meaningful share was wrong or dangerous as written:
- hooks: removing "unused" legacy names would have turned every hooks test red (conftest patches them in autouse fixtures); failing loud on an unset AIPASS_SESSION_TYPE would have broken every interactive session (unset IS the interactive state); refusing a malformed payload must apply to pre-tool gates only, or the Stop hook keeps an agent running.
- memory: raising in storage/lane.py would have stopped every vector feature on this host (the repo venv is the interpreter with chromadb); raising at import in repo_root.py would break a wheel install that today fails safe.
- ai_mail: treating a missing safety_config.json as an empty grant would have taken the seat's own model grant away; only unreadable or wrong-shape may fail closed. paths.py has 10 import-time callers, not 4, and ai_mail.py:131 swallows import errors into "No modules found".
- drone: a loud lint gate would refuse commits in Seed and feel_good_app (ruff is dev-only and not on PATH there); look beside sys.executable first.
- dead-cwd: in drone, flow, spawn, daemon, hooks, skills and canary, tests forbid the exact line the fix writes; they move in the same commit. Six files need a pathlib import the recipe assumed.
- prax: of 2,316 live config, data and log files only two fail the shape check, both prax's own logger files, so the json_service fix is safe; three tests in prax, api and commons pin the overwrite.
- skills: pyyaml is imported by product code and declared nowhere. The probe-skill in the owner's home was NOT made by the shipped test (the seat had said it was): it predates the test's first commit by 55 minutes.
- STATUS.local.md reaches 10 spawn template registries, prax docs, a bypass row, four tests; two real files still sit in commons and skills.
Lesson: "fail loud" needs the distinction between missing (a defined empty state) and corrupt (raise), per file, checked against the live machine first.

Also at this point: @aipass returned with the install rewritten as asked and the onboarding modules archived, but had also cut init_flow.py from 1,283 to about 370 lines (guided stages gone; init <dir>, update, agent kept) against the correction; held uncommitted for the owner's call. devpulse's own list landed in 54aba2ae.

### 10. Power loss at about 00:20 on 11-15, and what it taught

The laptop shut down (charging port) with two citizens (sentry, hooks), three builders (memory, api and ai_mail, drone and spawn) and a Docker build in flight. Lost: every running process, and the whole session scratchpad, because it lives on /tmp, which is tmpfs: all reports, verified lists and briefs. Not lost: 12 branches already committed; sentry's and hooks' uncommitted edits (55 files each, both still compiling and answering); this capture; the fallback corpus copied to sentry's dropbox. Recovery: the reports and lists were rebuilt from the sub-agent transcripts under ~/.claude/projects (the heredocs that wrote them are in the transcripts) and copied to devpulse docs.local/sweep3_2026-11-14, which survives a reboot. The three builders had edited nothing yet and were resumed from the start; the citizens were re-dispatched in continue mode; the watchdog reported the dead dispatch by itself ("monitor gone before the hard timeout: reboot, OOM or kill").
Lessons: anything another step depends on goes to a durable folder, not the scratchpad; committing each branch as it lands is what made the loss small.

By the power loss, committed on dev (79 ahead, unpushed): devpulse 54aba2ae, prax, cli and canary f73602cf, aipass plus setup.sh and root docs (end of onboarding), backup and daemon 1a10e6c8, commons and skills plus pyyaml c005a7a6, flow and trigger cfd6f9a1. Open: sentry (list done, checker task in flight), hooks, memory, api, ai_mail, drone, spawn; BAUD install.sh (--no-chat is gone; needs a consent pass-through, aipass install has no --yes); the Docker install test; the full suite once, when the machine is quiet.

### 11. After the power loss (11-15, 01:00 to 02:00)

Committed: sentry (fallback standard), hooks (332 to 196 bypass rows; promoted live .live-20261115T082829Z, 3,005 hooks tests green), drone and spawn b4968ac8, api and ai_mail. 17 of 18 branches; the memory builder is still running.
The Docker install test caught the first fallback that was load-bearing. The bootstrap install runs from the wheel in /opt/aipass, outside any AIPass home. At lock release it fires trigger file_deleted; trigger's setup_handlers imports ai_mail email_send; registry/read.py calls find_repo_root at import, finds no marker above site-packages, and now raises RepoRootNotFound. Before sweep 3 it silently took the cwd (/home/aipass, not the home /home/aipass/AIPass), so the bootstrap's ai_mail was rooted in the wrong place all along. The loud failure is the ruling working. The cure is a design choice, mailed to @aipass: the bootstrap process sets AIPASS_HOME and ai_mail honours it, or the bootstrap stops wiring trigger. Sentry's trigger standard requires trigger.fire on every unlink, so dropping the event is not a one-line fix (tried and reverted, tree clean).
The owner asked for a lighter load (battery failing): one builder at a time, memory saved more often, nothing durable left only in /tmp.

### 12. Morning of 11-15: all 18 branches in, install path under test

Memory committed (ccafa559): 18 of 18. The owner gave a green light for the night at 01:47; the machine then slept from about 02:10 to 08:46.
@aipass FPLAN-0926 (5a168484): the bootstrap fires its lock event through the home's own drone, `aipass install --yes` carries consent, a requested phone face that fails exits 1. setup.sh: no terminal and no AIPASS_YES means the machine changes are skipped and reported, never a silent yes (devpulse's call, in the owner's absence, from his "on no, a warning"). @baud FPLAN-0927 (baud 382b96d): install.sh passes --yes, lists the machine changes before its one Enter, drops the phone-face workaround. BAUD's next tag waits for an AIPass release carrying --yes.
A crossed wire: @aipass applied my overtaken correction mail hours late and restored the guided init stages; sent back, it undid the restore. Lesson: a correction mail that a later ruling overtakes must itself be corrected by mail, at once.
Docker install test 2 (image aipass-local:test3): the install completes. New finding: the bootstrap's doctor judges the directory the installer started in, not the installed home, so a healthy install (46 pass, 0 error from inside the home) is reported as 3 errors on the final screen and in install_report.json. Back to @aipass.

### 13. Both install paths green (11-15, 09:30)

AIPass alone (repo Dockerfile, image aipass-local:test4): exit 0, doctor 46 pass, 3 warnings, 0 errors, report outcome `installed`. The doctor fix: the bootstrap runs the home's own `aipass doctor` with cwd and AIPASS_HOME set to the home; a real doctor error now exits 1.
Through BAUD (its sandbox image, a bare Ubuntu; both sign-ins skipped, no credentials entered): run 1 failed on a false ERROR from hooks' wire verify (Codex hooks and OpenCode plugin "missing" on a machine with neither CLI). It predates sweep 3; it only bit once doctor errors became fatal. Cured in hooks: an absent provider CLI is a defined state, reported at INFO. Run 2: doctor 39 pass, 0 errors, phone face served (HTTP 200 on 127.0.0.1:8787), "BAUD v0.5.0 is installed". Logs: docs.local/sweep3_2026-11-14/baud_sandbox_run1.txt and run2.txt.
Three install bugs in one morning, each hidden until a failure was made loud: the bootstrap's wrong ai_mail root, the doctor judging the wrong directory, the wire verify error nobody saw because install exited 0 anyway.
Open after this: devpulse greeting from install_report.json (user_name is empty on a non-interactive install, the wake line still says "greet me by name"); the Tailscale-down warning says "Install it" when it is installed; the full suite, once; push on the owner's word.

### 14. Hand-back to the owners (the owner's ruling, 11-15 10:00)

His words: the brunt work was done with devpulse's sub-agents; from here the managers take over their own branches. Budget: 2 citizens awake, 2 sub-agents each. No more devpulse sub-agents on branch work. "We'll fix it as it breaks": the citizens using their own systems is how the cracks show. No Docker until the reds are gone. If it takes all day, it takes all day.
Full suite 11-15 09:43: 25,428 passed, 65 failed. Cured and committed: sentry 61 (contract flipped to fail loud), api 1 (+ a WebSocket gap @api found reading its own commit). Open: memory 3 (dispatched), Vera-Studio 12 (another project, the owner's call). Hooks' edit-time fallback warning committed; promote 2 running.

**The hand-back brief (one FPLAN per branch, its Goal section; dispatched two at a time, next on each wake-back):**
> Sweep 3 (FPLAN-0923, 2026-11-14/15) changed your branch, mostly through devpulse sub-agents, on the owner's rulings: AIPass is Linux only (WSL2 stays); no silent fallbacks (a missing file is a defined empty state, a corrupt or wrong-shape file raises and is left untouched, a check that cannot run never reads as passed); nothing is deleted, it moves to .archive. You may not have had a say. It is your branch: take it back.
> 1. Read what landed: drone @git log 15 on your branch path, then the diffs. Say what you agree with and what you would have done differently; cure what is wrong.
> 2. Use your own system. Run your verbs the way your callers do, the unhappy paths too. Whatever breaks loudly now is the point: cure the root, never restore a fallback.
> 3. Stragglers: any Windows or macOS residue in your code, tests, docs, prompts, scripts (win32, darwin, os.name, platform.system, msvcrt, PowerShell, cross-platform wording). Archive, do not delete.
> 4. drone @sentry audit aipass @you. The fallback standard is advisory: for each site it lists, cure it or waive that one site in .sentry/bypass.json with a reason that says who finds out when it fires. A whole-file row waives nothing. Run the prune dry-run and drop rows that cover nothing.
> 5. Tests: only the files you touch, one run at a time, output to a file, no full suite, no coverage. At most two sub-agents.
> Reply with: files changed, what you disagreed with, what broke when you used it, anything that is another branch's defect (name the branch), anything HELD.

Ruling 10:03, corrected 10:05: AIPass only for now, and BAUD is AIPass: it sits inside the repo at projects/baud, so it is in scope and in the queue. External projects live outside the AIPass tree (Vera-Studio, Seed); they follow once AIPass is in good standing, so they have something to update to.
Ruling 10:05, test suites do not overlap: AIPass's suite tests AIPass, each external project has its own. The Vera-Studio reds came from sentry's fleet json_handler contract discovering handlers in external projects registered on this seat; that reach is the defect. Mailed @sentry: bound discovery to the AIPass repo, and give external projects the contract to run in their own suites.

Queue (2 awake at a time): sentry and memory are out now (their own briefs). Then: aipass, hooks, prax, api, ai_mail, drone, spawn, flow, trigger, backup, daemon, cli, commons, skills, canary, baud. devpulse does its own. Progress 10:30: memory's 3 reds cured (tests pin the contract, not the machine). Sentry: held builds landed, suite bounded to the repo (Vera-Studio's 12 gone as out of scope), strays archived; its three own out-of-repo tests have a go. Out: @aipass FPLAN-0928, @hooks FPLAN-0929. Hand-back still owed, in order: prax, api, ai_mail (include test_admin_lane.py:64 stat of the real ~/.aipass/admin_grant.key), drone, spawn, flow, trigger (4 whole-file rows, 6 dead rows), backup, daemon, cli, commons, skills, canary, baud, memory (steps 3-4 and its whole-file row), sentry (done in passing). Ruled 10:29: the prax logger import is mandatory in every file, used or not (consistency: repeatable patterns that are tracked, like the three JSONs per module; selectiveness is how things drift). This morning's imports build relaxed that on devpulse's go, wrongly. Mailed @sentry: restore the mandatory import AND keep the new conviction of stdlib logging; also look at what special checks @cli carries. Sentry is the next dispatch when a seat frees.

Progress 10:40: @aipass hand-back done and committed (FPLAN-0928): audit 100, fallback 100 (25 cured, 35 waived per site, 1 held: scaffold_manifest.read_manifest), doctor outside a project cured, the win32 skipif gone. Out: @hooks FPLAN-0929, @sentry (prax import in every file, then prune defect, then its 3 out-of-repo tests). Next hand-backs: prax, api, ai_mail, ... as listed above.
ADD TO EVERY REMAINING HAND-BACK BRIEF: sentry's prune is unsafe until cured (@aipass found it writes nothing and convicts live rows from one lane): dry-run only, verify each row against the checklist AND the audit, remove by hand. And: add the prax logger import to every production .py file that lacks it (the owner's ruling 10:29), once sentry's advisory lane lists them.

PRAX IMPORT ON HOLD (the owner, 10:44): nothing more until the rule is laid down; he now doubts handlers need prax. @sentry told to stop the prax_import lane (its 3 files stay uncommitted). Do NOT put the prax-import line in hand-back briefs. Facts read 10:50: the written standard (imports.md 2026-03-08) says "nearly always"; handlers.md:134 says json_handler raises and "calling modules handle logging"; the old checker required the import in modules only and exempted handlers, __init__, files under 20 lines, doors, tests. Measured: 842 handler files, 552 call the logger; 242 module files, 189 call it. devpulse hand-back done (25 fallback sites waived by function). Prune defect reproduced on devpulse.

LOGGING RULING, 10:49 (the owner): no refactor of handler logging. Prax is the only logging system; any other is rejected; cli is the exception and goes in bypass. History found (sentry memory, handler_logging_standard, 2026-03-22, DPLAN-0040): handlers were once PROHIBITED from prax; that left 112 commented-out logger calls in api alone and the owner reversed it ("goes against natural flow, more logging is not a bad thing"). Measured 10:55: 3,267 logger calls in handlers, 1,919 inside except blocks (silent_catch 2026-03-22 demands a log or re-raise at the site). Stdlib logging left in the tree: aipass bootstrap.py, aipass scaffold_manifest.py, memory chroma_subprocess.py. cli uses no other logger: display.py and templates.py cannot import prax (prax imports cli, 11 files), both already bypassed. @sentry 10:50: prune defect cured (uncommitted, mixed with the held prax_import files); its dry-run now shows sentry 6 dead and prax 10, unverified. STILL OPEN: is the prax import required in every file, or as before (modules only)?

BOARDROOM (the owner, 11:11): room boardroom-one-logger, post 52; opening text kept at docs.local/sweep3_2026-11-14/boardroom_one_logger_opening.md. His idea: two prax-owned doors (the logger, and a "prax custom" path for files that cannot use it), every other logger rejected, no bypass rows for logging. Seats in order, two awake at most: trigger (out 11:20), cli, aipass, memory, sentry, prax LAST. Each posts one comment on 52 and replies by mail. Then an END REVIEW on Codex (the owner, 11:12: GPT's strongest model, does its own research of the code; dispatch flag --provider codex --model gpt-6.1-sol, --fresh). Then I close with the landing and take it to him. No building in the room. Hand-back round continues beside it: hooks FPLAN-0929 still out.

11:40 state. Boardroom thread 52: trigger posted; out now cli and aipass; then memory, hooks (added: reason D, bridges load before prax), sentry, prax last, then the Codex end review. HOOKS HAND-BACK IN and committed (FPLAN-0929, 44 files); sentry's prune cure committed; tests/e2e/test_wiring.py isolated and committed (real trust registry untouched). hooks promote running (log docs.local/sweep3_2026-11-14/hooks_promote_3.txt). FOR THE OWNER: subagent_gate has never blocked (it parses a cross mark, checklist prints [FAIL] and exits 0); hooks asks: (a) cure as is, (b) cure and judge only files the sub-agent wrote, (c) advisory. Hooks' six HELD fallback sites stand as waivers. To route: aipass-hooks-muted leftovers in sentry gateway_boundary_check.py:43 and api's tests. C4 bridge design received, waits on the boardroom. Next hand-backs after the room: prax, api, ai_mail, ...

11:55 state. Hooks PROMOTED and live (.live-20261115T182431Z, 3,040 pass) after it re-pinned alert dismiss. BOARDROOM 52: six seats posted (trigger, cli, aipass, memory, hooks, sentry); thread saved at docs.local/sweep3_2026-11-14/boardroom_thread52.txt. Out: prax (designs the door), ai_mail (dispatch_wake.log, purge.py). Still to seat: daemon (three copies of a timestamped console.print: rotation.py:94, inbox_sweep.py:88, run.py:98). Then Codex end review, then my landing to the owner.
WHERE THE ROOM STANDS (their findings, from code): (1) most "cannot import prax" bypass reasons are FALSE: cli's cycle does not exist (prax/__init__ is lazy), aipass's four files always have prax beside them, memory's subprocess runs in the same venv, trigger's config.py has no cycle. (2) All agree: a file that logs nothing owes no import; the every-file lane is redundant; sentry would archive it. (3) Real cases left: trigger's watched path (lines must land outside every watched *.log, i.e. jsonl, not DirectLogger, which writes watched files and leaks today); hooks' bridges (must answer when prax itself is broken; stdout is the protocol); records are not logs (append_jsonl is already prax's door for them); leaf scripts whose stdout is a protocol should report in the reply and let the caller log. (4) Sentry's gap: stdlib logging is convicted in modules only; 17 of 20 stdlib files are handlers and unseen. Its proposed rule: convict stdlib logging plus three home-made shapes in every production file, only prax's package exempt by a named rule, message reads door names prax publishes. 18 logging bypass rows go to zero.

12:05 state. BOARDROOM 52: all ten comments in (trigger, cli, aipass, memory, hooks, sentry, ai_mail, prax, daemon, plus mine). Thread saved (docs.local/sweep3_2026-11-14/boardroom_thread52.txt). PRAX'S DESIGN: direct.py is NOT door two; a new stdlib-only aipass.prax.floor under prax's own chain, lanes logger (.log, watched: hooks bridges, prax internals) and trail (.jsonl, unwatched: trigger), named(name) for shared files; append_jsonl stays the record door; Mission Control tails .jsonl and fires nothing; NullLogger retired (falls to the floor with a first ERROR line); three import spellings all door one, no mass conversion; prax publishes a DOORS constant sentry reads. Open: json_service loop (trigger to confirm), ai_mail's transcripts (dispatch_stdout/stderr.log in watched dirs) and its own append_jsonl (needs precheck-under-lock, no-rotate), memory to publish a modules door for purge, daemon's 38 MB unrotated ~/.aipass/daemon-tick.log (systemd redirect; cure: stdout null, stderr to journal) and prax log retention (run.log keeps about 3 days). CODEX END REVIEW OUT: @drone on --provider codex --model gpt-6.1-sol --fresh, told to verify from code and hunt what the room missed, posts one comment on 52. Then: my landing to the owner. Nothing is built until he rules.

12:20 BOARDROOM 52 LANDED. Codex end review (@drone, gpt-6.1-sol): model holds, 7 must-fix; round two: prax accepted all seven, trigger confirmed the json_service loop and owns the .log-only pin. My landing is posted on the thread and kept at docs.local/sweep3_2026-11-14/boardroom_one_logger_landing.md (rule, two doors, what stays below any logger, who changes what, build order, weak points); full thread at boardroom_thread52.txt. NOTHING BUILT: waits on the owner's ruling. No dispatches out. If he says go: FPLAN for prax first (contracts, then floor.py and pins), trigger second with json_service, hooks third, owners, sentry last. Sentry's held prax_import files then go to .archive and imports.md reverts to this morning's rule. Still open for him: subagent_gate (a/b/c), the 38 MB daemon-tick.log, small files and doors (moot if the every-file lane is retired). Hand-back queue resumes after: prax, api, ai_mail, drone, spawn, flow, trigger, backup, daemon, cli, commons, skills, canary, baud, memory.

12:35 VERIFICATION OUT (the owner, 11:53: ten sub-agents, map it all, confirm every claim is true). Brief: docs.local/sweep3_2026-11-14/verify/BRIEF.md. Ten read-only verifiers (5 opus, 5 sonnet), one report each in that verify/ directory: 01_prax_chain, 02_prax_floor, 03_rotation_retention, 04_monitor, 05_trigger, 06_hooks, 07_aipass_cli, 08_memory_ai_mail, 09_daemon_api_transcripts, 10_sentry_fleet_inventory. Each marks every claim TRUE/FALSE/PARTLY with file:line and lists what nobody mentioned. NEXT: read all ten, write one consolidated verdict (verify/00_VERDICT.md), post the corrections to thread 52, report to the owner. If a session is lost: the reports are on disk; re-run only the missing numbers.

13:20 VERIFICATION IN. All ten reported; consolidated verdict at docs.local/sweep3_2026-11-14/verify/00_VERDICT.md; corrections posted to thread 52 (comment 98). 286 claims: 218 true, 49 partly, 19 false. DIRECTION HOLDS, DESIGN AS LANDED NOT BUILDABLE YET. Eight findings change it: (1) hooks bridges record the break BEFORE refusing and catch only OSError, so a floor that raises or blocks on the shared lock opens the gate (refuse first, guard broadly, non-blocking write; conflicts with amendment 3); (2) the floor cannot be made by moving code (introspection.py:164 json-service call, config/load.py:78-93 imports door one, jsonl_writer pulls 14 modules); (3) only the short import spelling falls back, about 237 long-spelling files and 18 direct-logger importers do not; (4) the monitor does fire (monitor.py:581 to rate_tracker.py:318) and reads system_logs only; (5) the logger path can fire file_watcher_died (dormant); (6) trigger: only escalation.py and config_loader.py loop, three unlisted loops (modules/core.py:137-142, error_reporter.py:91, memory registry_scope), medic_state reads two trails; (7) the 30-day sweep is manual and would delete record files, log_watchdog truncate is unlocked, append_jsonl keeps one backup; (8) no checker convicts any stdlib logger today. My opening counts were inflated (real: 806 handler files, 487 log, 2,854 calls, 1,660 in except). Mine to cure later: watchdog _stderr helpers (26 sites), tools/dispatch_usage_v1.py reads dispatch_wake.log. NOTHING BUILT: waits on the owner. If go: step 1 (contracts) is larger and must settle those eight before prax builds. No dispatches out.

13:35 ROUND THREE CLOSED (the owner, 12:16: take the findings to the boardroom, everything verified with real code, we want to start seeing the same things). Seven seats answered from today's code, hooks, trigger, sentry, memory, ai_mail, daemon, prax last; thread saved at docs.local/sweep3_2026-11-14/boardroom_thread52_r3.txt (2,844 lines), my close is the last comment. EVERY SEAT CONFIRMED the verifiers on its own branch; room and verifiers now agree. THE DESIGN SHRANK (prax's own restatement): no floor module; door one unchanged, both spellings and get_direct_logger degrade to one landed ERROR in system_logs/prax_fallback.log then stderr, NullLogger goes; door two is from aipass.prax import trail (JSONL with levels over a standalone jsonl_writer with one lock) for real loops only (trigger escalation, config_loader, log_watcher:551, core.py:137-142, json_service, prax chain diagnostics); crash floors are named (hooks bridge.log write, daemon systemd stderr file, prax fallback line); prax is not on the hooks refusal path; log_watchdog stops truncating live files and sweeping jsonl; transcripts leave .log (ai_mail proposes .out, one published constant); sentry reads one prax list and convicts stdlib in every production file, last. DEFECTS TODAY, independent of the design: hooks gate fails open on a non-UTF-8 break message (reproduced by hooks); trigger bus disables a handler after 5 failures silently, one bad registry can deafen medic; unlocked truncate; sweep deletes records; dispatch.log exclusion hid 7 ai_mail errors (ai_mail rules it leaves the list). Daemon measured the journal: about 7 days, so its journal cure is withdrawn for a systemd stderr file. Sentry corrected my watchdog count: 23 _stderr call sites. I withdrew my opening counts on the thread. NEEDS A RUN: fallback under an induced chain break, the disable chain, escalation volume, hook latency, Codex/Seed on exit 1. FOR THE OWNER: go/no-go on the smaller design; fallback-and-keep-running versus raise at import; installed-copy branch logs under ~/.aipass; the 38 MB file; sub-agent stop gate; import lane retired. No dispatches out, no wire needed.

13:00 THE OWNER RULED, BUILD IS GO (12:43 to 12:57). (1) NO FALLBACKS, anywhere, no waivers: the system fails and we get notified; a fallback agent may come later when something is stable. So prax's fallback-and-keep-running is OUT: a broken logger RAISES at import in every spelling, NullLogger is deleted. Crash records (hooks bridge.log write, daemon systemd stderr file) stay because nothing keeps running on them. (2) The every-file prax import lane is RETIRED: only files that log import prax. (3) A destructive gate that breaks must refuse everything, loudly; only a person recovers it. (4) Sentry builds the checkers FIRST (his idea), advisory, enforcement last. OUT NOW: @hooks FPLAN-0930 (refusal first, exit in finally, record guarded with no lock, red pins first, real run for Codex and Seed on exit non-zero with no output, recovery path in docs, promote); @sentry FPLAN-0931 (archive held lane, one AST logging checker with keys K0 to K3 over every production file, drop four exclusions, before picture per branch, cost of a no-waiver fallback rule; advisory only). Wire armed. NEXT after sentry's before picture: trigger (stop the silent handler disable, cache the census failure, drop the name list incl. dispatch.log, loops to trail), then prax (delete NullLogger so breaks raise, stop the unlocked truncate and the jsonl sweep, standalone jsonl_writer with one lock, the trail door, publish backup count and the allowed list), then owners (ai_mail transcripts to .out, memory, daemon, aipass, devpulse _stderr helpers and dispatch_usage_v1), sentry enforces last incl. fallback as a hard rule. Every brief is an FPLAN in the owner's branch.

### 7. State at capture

dev is ahead of main by 72 commits, unpushed (push and merge only on the owner's word). Per-branch work lists exist for all 18 branches (110 purge items, 56 dead waivers or false greens, 120 fallbacks, 42 owner decisions). Dispatched so far: @aipass (end of onboarding), @sentry (its list), a builder on devpulse's own list. Order after that: prax, cli, ai_mail, hooks part 1, the rest; hooks removes its dead-cwd code last; sentry prunes its helper names after everyone.

(This capture is appended to until the session ends, then closed.)

## Links

- **Related plans:** FPLAN-0923
- **Commits:** AIPass dev through cce30aa7 (a624b337 wheel exclude; docker files; sweep 2 owner commits); BAUD 38795ab
- **Compass entries:** #304 (no fallbacks)
- **External:** —

## Status
- [x] Created
- [ ] Closed (same sitting — that's the design)

*Spoken summary: written only when the user asks for one, in plain sentences with no markup.*

---
*Created: 2026-11-14*
*Updated: 2026-11-14*
