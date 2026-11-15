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
