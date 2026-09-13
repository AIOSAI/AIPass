# Changelog

All notable changes to AIPass will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Entries are grouped by merge under a dated section header (`YYYY-MM-DD`). Package
releases follow [SemVer](https://semver.org/) and are tracked by the git tag and
PyPI version — not the changelog header.

---

## [Unreleased]

### Added

- **skills: `machine_vitals()` — the machine's vitals as one published in-process dict, the read behind BAUD's monitor wheel (DPLAN-0341, FPLAN-0561 row 1 of three; skills owning, devpulse landing; Patrick ruled the test-write gate open for skills 2026-09-12 23:31, flipped by hand and reverted on landing as with canary).** The probe that sized this found that @baud's planned Rust half could not serve Patrick's case — `sysinfo` 0.39.6 has no fan API at all, zero occurrences of the word in its source — while psutil, already declared and already behind the `system_status` skill, reads the applesmc fan today; @api ruled the lane under their D0 (*"this server owns the pipe and never the meaning"*): @skills publishes the read, @api proxies it, @baud renders it. `lib/system_status/handler.py` 2.0.0 → 2.1.0 (now a regular package with `__init__.py`) publishes `machine_vitals()`: `ok`, `schema: 1`, `sampled_at`, and eight sections — `cpu`, `load`, `memory`, `swap`, `temp`, `fan`, `network`, `processes` — each carrying `available`, `reason`, `sentence`, `detail` beside a stable value key set that is `None` when absent, never a zero; a reading that raises costs only its own section. Whole-function refusal is `{ok: False, reason, detail}` for exactly `psutil_missing` (detail = the install recipe) and `switched_off` (the off-switch is consulted inside the function and fails closed on an unreadable state, as the runner does). Eight reason codes, a closed set with one sentence each: `platform`, `no_sensor`, `no_allowlisted_sensor` (carries `seen`), `read_failed`, `warming`, `no_range`, `switched_off`, `psutil_missing`. CPU percent and network rate come from baselines the skill owns — held `cpu_times()` / `net_io_counters()` samples with `window_s`, `warming` on the first call — never `psutil.cpu_percent(interval=None)`, whose module-global baseline is shared per thread (measured 37.5 then 21.9 in a fresh process; a stand-in calling it between two reads is pinned not to move the number). The temperature and fan allowlist is data keyed by chip AND label: `coretemp` `Package id 0` with the sensor's own `high`/`critical` (hottest `Core N` when no package row), `applesmc` fans; every other applesmc row (five read −127, two drift around −30) and `BAT0` are off; an unlisted chip is named in `seen`, never drawn. The fan range is a guarded Linux-only sysfs read — chip found by its `name` file, never its hwmon index (on the MacBook this was built on `hwmon2/name` does not exist and the name lives at `hwmon2/device/name`), opening exactly `name`, `fanN_label`, `fanN_min`, `fanN_max` read-only and **never** `fanN_manual` or `fanN_output` (root-writable; pinned with `builtins.open`, `io.open` and `os.open` all guarded) — publishing raw `min`/`max`/`current` plus a clamped `percent_of_range`; a missing bound or `min >= max` is `no_range` with the rpm still published. Live on this box: fan `Right Side` 1291 rpm against 1299–6199 (0%, the floor — a real reading, distinguishable from no scale), coretemp package 60 °C against high/critical 100. Cost measured 19.4 ms warm; payload ~1.5 KB. Tests: `tests/test_machine_vitals.py`, 32 functions / 45 cases, every stand-in manufactured so the suite is green on a host with no chips — the section and reason-code sets, per-section absence, both refusals with two corrupt switch documents, the owned baseline against a `cpu_percent` caller, the allowlist against the real applesmc row shapes, the read-only sysfs pin, manufactured macOS and Windows worlds (`hasattr` false reads as `platform`, Windows load named not drawn as its emulated 0), `no_range` both ways; 20 mutants red. Branch suite 1438 → 1483 from both rootdirs, ruff clean, audit code rows all 100 (trinity 98 is skills' midnight freshness stamp, advisory-local). One function-scoped `unused_function` bypass names the consumer, @api's `/v1/machine` (row 2), which the per-branch scan cannot see. Text actions as renderings of the same dict, and PROC's own route, are deferred rows.

## [2026-09-12] — the portability day: seedgo's `host_portability` standard turns the Linux gate red by design and eight owners cure it, the first fully green three-OS head since the macOS job could fail, arm C plus `platform_oracle` cure 6, and canary's blind trial of the v5 test standard (FPLAN-0554 / DPLAN-0323 phase 8, merged as PR #763, v2.8.7)

### Added

- **canary: a note store, built blind as the exam for the version-5 test standard — and the entry point stops reporting every refusal as success (DPLAN-0323 phase 8, the trial Patrick ruled GO on 2026-09-12; canary owning, devpulse landing).** `drone @canary note add TEXT` appends a `{text, timestamp}` record to `docs.local/notes.jsonl` (untracked); `note list` prints them with index and timestamp; a store that will not parse is refused by file name with exit 2 and is **never** reset, truncated or rewritten — `append_note` parses every existing line before it opens the file, so a bad read costs nothing. Deliberately NOT the fleet json service: `ensure_json_exists` rebuilds an unreadable document from its in-code default and `load_json` runs it before every read, which is exactly the reset this store must never perform. The trial was blind — canary was handed the contract, told to include tests, told nothing about what to test, and not told it was being examined. **The defect it found on the way is the part worth keeping:** `canary.py` `main()` returned 0 for any command a module claimed, so a module that handled a command and REFUSED it exited 0 — a refusal the shell reads as success. Cured with the fleet's `reset_command_state` / `resolve_exit` seam (2.0.0 → 2.1.0) and pinned from four directions, two of them mutations inside `aipass.cli`. Tests: `test_note.py` 12 functions / 34 cases, the load-bearing one a 9×2 parametrize over corrupt store shapes asserting exit 2, the file named, and the store's bytes and mtime unchanged, with a valid-store control beside it so it cannot pass vacuously; canary mutation-checked its own tests unasked (10 mutants, and when one survived it added a fixture to kill it). Branch suite 47 → 83 collected, ruff clean, `audit aipass @canary` 100, hygiene 0 violations. **Known defects, not fixed here and tracked in devpulse DPLAN-0340** (a two-round adversarial audit, six sub-agents, run after the trial): a note whose text contains `-h` is discarded silently at exit 0; the subcommand-help path still returns a hardcoded 0 on a refusal, so the cure above is half-applied; the corrupt-store assertion wraps and reds below 43 console columns; `discover_modules()` has no coverage; and the branch's dead-cwd module table has not learned these three new modules. The trial verdict itself — the v5 standard does lead an agent to protective tests on its own — is written into DPLAN-0323 phase 8.

- **prax: the fleet's weekly tmp sweep is live — `prax/.daemon/schedule.json` carries `tmp-sweep-weekly`, the first daemon command job (DPLAN-0338 wave 2a, FPLAN-0546, prax owning).** Every Sunday 04:00 local (slot `2026-09-13T04:00:00`, seeded by the live tick at 13:31 so the first fire is this Sunday and never the discovering tick; a Sunday missed with the machine off fires on the first tick after) the tick runs `drone rm --stale 10d ..` from prax's directory — `..` is `src/aipass`, so one call covers every branch's json folder — with `timeout_seconds` 120 and a start and finish mail to `@devpulse`. Changing the age is editing the command string; off is `enabled: false`; the `_note` in the file carries the why (Patrick 2026-09-11: once a week, 10 days, no agent tokens, an email when it runs) and the arithmetic (measured 54 ms per deleted file, so 120 s covers about 2,100 files a week). First sweep by hand from prax at 13:32: 706 files, 35.6 MB, 39 s, `*.tmp` under `src/aipass/*/*_json` 1,170 → 466, ledger +706 rows, every one old-era `tmpXXXX.tmp`; the 466 left are the dot-prefixed temps from the prax service, all younger than 10 days, and age in. Measured on the way and NOT acted on (unruled): 87% of the new-era orphans are one record, `discovery_watcher_event action=started` at `watcher.py:234`, written on the unjoined `prax-watcher-start` daemon thread since the 09-04 bundle move — a short-lived process exits and the interpreter kills the thread between temp and rename — and 57 of today's 174 are the FPLAN-0542 data bump staging a second write per log operation. The introspection records the morning thread blamed are about 2% of it.
- **daemon: command jobs — a schedule job may carry `command` instead of `prompt`, and the daemon runs it as a subprocess with no agent wake, no seat, no tokens (DPLAN-0338 wave 1a, FPLAN-0543, daemon owning; Patrick 2026-09-11: "the cleanup can just be a drone command, a simple daemon schedule ... turned on and off easily, if it runs there's a log, if it passed or failed there's a log").** Validation in `discovery.py`: exactly one of `prompt` or `command`, the first token must be `drone`, `timeout_seconds` a positive int (default 600), `notify` a bool or a dict whose `email` is an `@address`; rotation plus command refused. The fire path (`run.py` → new `handlers/schedule/command_job.py`): `shlex.split`, no shell, cwd = the branch that vouched for the schedule file (a missing directory fails the fire by name, no fallback), stdout and stderr merged into an anonymous temp file rather than a pipe (a background grandchild holding a pipe turned exit 0 into a false timeout under mutation), its own session so a timeout stops the whole process group (TERM, 2 s, KILL; Windows kills only the direct child, documented). Outcome FIRED on exit 0, FAILED on non-zero or timeout with the output tail in `last_error`; the runstate row has exactly a wake job's keys, so catch-up, interval and slot logic is untouched. FIRE and DONE lines in both the tick log and `logs/run.log`; `notify.email` sends an ai_mail email on start and on finish through a `drone @ai_mail email` subprocess so the mail is signed by the daemon, not the project. A command job holds the tick lock for its whole run — nothing else fires fleet-wide until it finishes, so heavy commands need a short `timeout_seconds`. The static `run --help` reference moved to `handlers/schedule/job_reference.py` (run.py back under seedgo's 600-line cap; help output byte-identical). Live proof on the real systemd timer: a `once` job running `drone @daemon --help` fired at 13:03:45, DONE exit 0 in 1.5 s, both notify mails delivered, job removed, row pruned by the next tick. 616 → 698 tests, 20/20 mutants red, audit 100.
- **drone: `drone rm --stale AGE [--dry-run] DIR...` — an age-and-pattern-restricted delete of staging temps (DPLAN-0338 wave 1b, FPLAN-0544, drone owning).** A candidate is a regular file named `*.tmp` whose parent folder ends in `_json` and whose mtime is older than `AGE` (`10d`, `36h`, `90m`; zero is refused because it matches a write in flight); nothing else is touched, symlinks are skipped, carve-outs stay refused, and the sibling-branch fence is crossed in this mode only, by design — a stale staging temp is no citizen's work, and the name + folder + age restriction is the fence. `--stale` is caught in any slot and any spelling so `drone rm api_json --stale 10d` can never fall into the plain lane. Every deletion lands in `.ai_central/deletions.jsonl` with `mode` and `age`; a dry run writes no rows. Dry run over `src/aipass` on 2026-09-11: 1539 folders, 706 matches, 35.6 MB, all old-era `tmpXXXX.tmp` back to May (the 461 dot-prefixed temps from the prax service are younger than 10 days). +55 test cases, 25/25 mutants red, audit 100. Wave 2 puts it on prax's weekly Sunday schedule as the first daemon command job. Pre-existing hazard found on the way and cured the same afternoon (FPLAN-0545, rm_handler 1.4.0): a plain `drone rm ..` or `drone rm ../..` from any branch passed every fence, because the sibling fence walks UP from the target and nothing above a branch holds a `.trinity` — rmtree would have taken the fleet. The plain lane now refuses any target under the project root that CONTAINS a citizen other than the caller (`check_contained_citizens`, walks down sorted, stops at the first foreign `.trinity`, names it in the refusal, records it in the ledger; a system-temp target, a target already inside a branch, the caller's own tree, and a symlinked child are all unchanged; an unlistable folder refuses instead of being skipped). Found by the own-tree test on the way: the delete step judged the RESOLVED path but called rmtree on the path as TYPED, so `drone rm ..` from inside a tree emptied it and then logged `failed` — the delete now acts on the resolved path, which also closes the check-then-use gap on a changing symlink. +10 cases (1319 → 1329), 9/9 mutants red, audit 100. Left as a recorded choice, not a gap: `drone rm .` at a branch root still deletes the caller's own branch, `.trinity` included.
- **backup: `*.tmp` is a built-in ignore floor — snapshots, versioned, and Drive sync stop copying staging temps (DPLAN-0338 wave 2b, FPLAN-0547, backup owning; Patrick 2026-09-11: "backup needs to ignore temporary files").** One place: `BUILTIN_IGNORE_PATTERNS = ("*.tmp",)` in `handlers/ignore/patterns.py` 2.1.0, which `load_spec()` puts ahead of the project's `.backupignore` lines, so it reaches every project including every store whose ignore file was seeded before the rule existed (AIPass's own `.backupignore` never named `*.tmp`); a project can still re-include with `!*.tmp` (last match wins). `load_spec` is the only ignore source for every lane — snapshot, versioned, all, and Drive sync, which re-filters the versioned store through it before uploading — so one line covers all four. `DIFF_IGNORE_PATTERNS` was not the copy rule and is untouched. Proof on a scratch copy of prax's json folder (452 temps, 145 json): before, snapshot copied 452 temps and versioned 904; after, 0 and 0, the json byte-identical. The store under the repo root, measured: 498 snapshot copies (14.3 MB, none with a living source) pruned by `drone rm --stale 10d .backup/snapshots` (498 deleted, 0 refused, ledger rows); 996 versioned copies (28.5 MB) LEFT, because each sits in its own `<name>.tmp/` folder, not directly inside a `_json` folder, so stale mode cannot match them and the plain lane refuses them as a sibling's tree — inert, they never upload, on backup's todo for the prune lane. The rule stops new copies and removes none (no ignore-aware sweep; documented). 371 → 378 cases, 5/5 mutants red, audit 100.

### Fixed

- **seedgo: `host_portability` reads the gate a test hides behind, follows a `/proc` literal through a name, and walks `lib/` (FPLAN-0554 round three, the learning half of the CI-red rule; seedgo owning, devpulse landing).** Every macOS red after the production arms landed was a TEST behind a skip naming the wrong host - `skipif(sys.platform == "win32", reason="/proc is Linux-only")` on prax `test_current_boot_id_reads_proc_on_linux`, the same predicate on four skills `test_runner` units whose reason said "reads Linux /proc/meminfo" - and none spelled `/proc` in a filesystem call, so neither arm could see them. **Arm C** convicts a platform skip naming only Windows on a unit that declares a Linux recipe by name (`_linux`, not the `off_`/`non_`/`not_` half) or by reason ("Linux-only", or Linux beside `/proc`, `/sys/`, systemd), and acquits a unit that patches its own platform or filesystem primitive; two wider shapes were measured and rejected (a Linux-named unit with no gate: 5 fleet hits, 5 false; any `/proc` word in a reason: convicts devpulse's correct lsof-lane gate). The same rule binds **arm A**: a skip acquits a `/proc` read only when its predicate names the host that HAS the recipe (`!= "linux"`, darwin, a path probe, `shutil.which`); `os.name == "nt"` no longer launders one, and the pin that said it did was a fixture minimised past the `Path` patch that makes the real `test_doctor.py` site correct. Arm A follows a name bound only to a `/proc` literal to where it is read (skills' `meminfo_path` spelling) and judges a bound `Path()` at its read, not its constructor (telegram `base_bot.py:2721` was a false row). The existence early-out stays a guard, measured: skills' pre-cure handler refused by name with `success: False`; its red lived in the tests. **Corpus** gains `lib/` for this standard only (the per-file corpus stays `apps/` until tier-2 skill handlers have a SKILL.md-keyed architecture exemption). Fleet on host_portability: every branch 100 before; after, every branch 100 except skills 97 - 12 arm B rows (tmux x11, systemctl x1) in three telegram handler files, off since 2026-08-18, routed to skills, which cured all 12 with no bypass (its own bullet; one row was a live escape) - the two land together or the gate reads skills 97 in between. Arm C and bound-name reads convict 0 live sites - every red instance was cured by its owner first, so the pins reproduce each pre-cure shape. `platform_oracle.md` teaches cure 6 (run a module's EXISTING pins under every lane you add) and three divergences a fake cannot manufacture (a pid read after the call that ends it, `os.kill(pid, 0)` on Windows, a cwd inside a tree being deleted); `host_portability.md` records eight candidate shapes weighed and not built, each with its owner's evidence. +16 pins, 2 rewritten, 14 mutants red and the source md5-restored; a pyright finding in the new arm (a `list[Call]` passed where `List[expr]` is typed) cured before landing; 4023 passed from the branch dir, 4023 passed from the repo root; ruff check and format clean over `src/ tests/` from the root.

- **ai_mail: the registry case-sweep instrument asks the glob matcher, not the volume, and the macOS world is reproduced on Linux (FPLAN-0554 row, macOS runs 34707762639 and 34707861282, Windows run 34710099534; ai_mail owning, devpulse landing).** `test_negative_control_the_instrument_can_say_no` and `test_link_the_outcome_follows_from_the_cause_on_every_platform` predicted whether `*_REGISTRY.json` sees `wrong_registry.json` from a probe of the filesystem. On the runner (darwin, Python 3.13.15) the probe said folding and the glob returned `[]`: the volume folds case on a lookup by name, but CPython matches a wildcard with the posix flavour's case-sensitive rule on darwin too. The probe had only looked like a glob question: 3.13 answers a no-wildcard glob component with `os.path.lexists` (`Lib/glob.py` 3.13:408, `literal_selector`) while 3.12 matches every component, so the same probe asked the matcher under 3.12 and the volume under 3.13. Now two probes and two tables, VOLUME (a lookup by name; darwin row stays deliberately None) and MATCHER (a wildcard in the defect's direction; darwin row fixed False), and every glob prediction comes from the matcher. A new `folding_volume` fixture manufactures the volume half on Linux: alone it is the Mac, stacked on the existing folding-matcher emulator it is Windows, and both worlds run the same negative-control and link claims as the host. Red first: that world against the old single probe failed on Linux with the runner's own text (`host was probed as case-folding, so the raw glob must see the decoy`; `in []) is True`). A `PurePosixPath`/`PureWindowsPath` oracle pins each platform's matcher row on any host. No production change: `registries_in` already re-checks the name and refuses the decoy in every world. Same pass: the manager wake-back drop on 2026-08-21 was three logged cases, not two, corrected in `dispatch.py`, `dispatch_monitor.py`, the README (now with the fleet `skipped_manager` figure and its method) and `test_dispatch_module.py` (@verify, Vera Studio); `purge.py`'s "about four months" reads "from March 2026 until the fix on 2026-08-24" (Vera Studio feedback 048682fe); three pre-existing type findings in the case-sweep file cleared. Tests plus wording, +6 cases, 7/7 mutants red, 1492 green from the branch dir and the repo root, ruff check and format clean from the root, audit 100 with Host_Portability 100. **The Windows half (run 34710099534, head c69720c2, 2 failures):** the Mac world manufactured only the volume, so on a Windows host it inherited `WindowsPath.glob`'s folding matcher, and `test_the_mac_row_is_driven_here_so_it_cannot_rot` and `test_the_two_probes_ask_different_questions` read True where they claimed a case-sensitive matcher — a cure for macOS proven on Linux that had never run under Windows. A new `posix_matcher` fixture installs the posix rule on any host (`fnmatch.fnmatchcase` per component over the real listing, `**` refused by name), and `mac_world` stacks it under `folding_volume`, so both pins are about the probes on every host rather than a posix host fact. Proved with a plugin that manufactures a whole host for the module (volume, matcher and the module's `sys.platform`): the landed file read 2 failed / 28 passed in the Windows world with the runner's text, and the cured file reads 30 passed (Windows world), 29 passed + 1 skipped (Mac world, the configurable volume row) and 30 passed natively; 3 more mutants red where they should be (dropping the matcher from `mac_world` and returning the two-probes pin to the volume alone are red only in the Windows world, a folding stand-in is red in all three). `paths.py`'s `registries_in` docstring stops saying the glob folds on default macOS (ruled yes, no behaviour). Still 1492 green both rootdirs, ruff clean from the root, Host_Portability 100.
- **prax: `test_current_boot_id_reads_proc_on_linux` skips wherever there is no procfs, not only on Windows (FPLAN-0554 row, FPLAN-0559, macOS runs 34707762639, 34707861282 and 34708132945; prax owning, devpulse landing).** The guard read `skipif(sys.platform == "win32")` over a test that reads `/proc/sys/kernel/random/boot_id`; macOS has no procfs either, so `_current_boot_id()` correctly answered None and `assert boot_id` (line 177) went red on every macOS run. Now `skipif(sys.platform != "linux")`, the reason naming the recipe that is unavailable rather than the state. Reproduced on Linux before the cure against an untouched snapshot, with a plugin that sets `sys.platform` to darwin before collection and refuses every `/proc` read: 1 failed and 8 passed in TestBootIdentity, same line and `assert None` as the runner; the cured file under the same world reads 8 passed and 1 skipped, and natively on Linux the test still runs (28 passed in the file). The portable half of the contract, no procfs means None and never an exception, is the sibling `test_current_boot_id_returns_none_when_unreadable`, which patches the read and ran green in the manufactured world too. Swept every platform guard in prax's suite for the same species and found no second one: the two Windows symlink and mode-bit skips in the json handler tests and the three deleted-cwd and emulation skips in the repo_root tests all name Windows correctly, since macOS has symlinks, mode bits and a deletable cwd; the pid_cache tests force `sys.platform` to linux and patch the `/proc` check, so they are host-independent. Tests only, one file, 1541 green from the branch dir and from the repo root, ruff check and format clean from the root, audit 100 with Host_Portability 100.
- **trigger: the log watcher's systemd door answers by name on a host with no systemd, and the `daemon-reload` that had never run once now runs (FPLAN-0554 row, Linux audit gate runs 34703057231 and 34705263028 read trigger 99 under seedgo's new `host_portability` standard; trigger owning).** `service_control.py:82` ran `systemctl --user enable` with no probe, no platform test and no handler; `systemctl` exists only where systemd does, so on macOS, on Windows and in a bare Linux container that call raises `FileNotFoundError` out of `exec`. Both doors now probe with `shutil.which("systemctl")` and refuse by name — `NO_SYSTEMD_REASON`, said in one place so the log, the CLI and the tests quote the same fact — instead of returning a bare `False` that reads as a broken unit: `_run_systemctl` refuses before `exec` and still catches a `FileNotFoundError` from a PATH that changed under it, and `_ensure_service_installed` probes **before** the `_SERVICE_UNIT_PATH.exists()` short-circuit, because a unit file copied in from another host is not a ready service and answering `True` for one is the assumed-running the standard refuses. Carried up to the surface a caller can read: `medic status` says `unavailable — no systemd on this host` rather than `stopped — run medic on to start`, advice that cannot work there, and `medic on` says `unavailable` rather than `failed to start`, which sends a reader after a unit that can never exist. **A second defect found on the way and cured with it:** `_systemctl(action)` spelled every call `systemctl --user <action> <unit>`, and `daemon-reload` takes no unit — `systemctl --user daemon-reload trigger-log-watcher.service` exits 1 with `Too many arguments.` (measured 2026-09-12), so the reload between installing the unit file and enabling it had never happened in the life of the handler and a fresh install depended on systemd noticing the unit some other way. `_run_systemctl(*args)` now takes the argv tail whole, `_systemctl(action)` is the unit-scoped one-liner over it, and the argv of both install calls is pinned. The tests state the host fact instead of reading it: `systemd_present` / `systemd_absent` fixtures replace `shutil.which`, so the pre-existing success cases no longer passed only because the author's box runs systemd — on the macOS runner they would have executed nothing at all. +11 cases (`TestNoSystemdHost`, `TestInstallArgv`, and two medic surface pins), 9 mutants red, including one that moves the probe back behind the `exists()` check and one that restores the unit name on `daemon-reload`. `drone @seedgo audit aipass @trigger` reads Overall 100 with Host_Portability 100; 1079 green from both rootdirs.
- **hooks: the three `tmux kill-session` calls in `session_boot.py` answer honestly on a host with no tmux (FPLAN-0554 row, Linux audit gate run 34703057231 read hooks 99 under seedgo's new `host_portability` standard; hooks owning).** `session_boot.py:248`, `:313` and `:1078` ran `subprocess.run(["tmux", "kill-session", ...], check=False)` with no probe and no handler, and `check=False` is not a guard: a missing binary raises `FileNotFoundError` out of `exec` before there is any exit code to ignore. One `_tmux_kill_session(name)` seam now owns all three, catches `(OSError, subprocess.SubprocessError)`, names what was missing in the log, and returns whether the kill was actually delivered — so `_stop_session` no longer reports `killed tmux session 'x'` for a kill that never happened and falls through to its own SIGTERM instead, while the two launch doors (`_exec_in_tmux`, `_start_fresh`) treat a stale session they cannot kill as a stale session they don't need to kill. The exec failure is the probe deliberately rather than a `shutil.which` at the seam: a `which` there reads the real PATH in every unit that mocks `subprocess.run` and nothing else, which is the host-coupled test this standard exists to prevent. The three `os.execvp("tmux", ...)` launches are left alone and stay acquitted by `boot()`'s own `_find_tmux()` early-out at `:428`, which every path to them passes through. 6 new cases under `TestTmuxLookupsSurviveAMachineWithoutTmux` (tmux absent, tmux hung, and each of the three call sites), 3 mutants red including a helper that swallows the failure and returns `True`.
- **hooks: `git_gate` reads a git or gh spelled as a path — `/usr/bin/git commit` was never matched at all (static finding from an external reader of a public drone post, relayed by @devpulse 2026-09-11; hooks owning).** `RAW_GIT_RE` is `(?<![@\w/.])git\s`, and the `/` and `.` in that lookbehind — there to keep `drone @git`, `.git/hooks` and `some/path/git.py` quiet — meant `/usr/bin/git commit -m x`, `./git commit` and `~/bin/git commit` all passed the one mechanical layer holding git writes behind drone. A path is now read as an invocation only at a **command position**: `_command_words` steps past leading `VAR=value` assignments and wrapper executables (`env`, `command`, `sudo`, `xargs`, …, plus their flags once a wrapper has been seen), `_path_exec_tail` claims the clause only when that word is a path whose last component is exactly `git`, and the argv tail joins the existing read-verb ruling — so `/usr/bin/git status` stays allowed exactly like the bare form while `cd /tmp && /usr/bin/git reset --hard` is refused. The same hole existed one function over for `gh` (`/usr/bin/gh pr create` was never read as gh) and is cured with the same seam, `gh api` still allowed. The rule deliberately stops at the basename: `ls /usr/bin/git`, `rm -rf /path/to/git` and `cat /srv/proj/.git/config` name a file and are nobody's git write. The suite had **pinned the defect** — `test_path_git_not_matched` asserted `/usr/bin/git push` was allowed and passed for its whole life — and that unit is replaced by the inverted claim under its own name; +13 cases, 6 mutants red, and the mutant that dropped the path-separator test survived until a unit pinned what it is actually for (a bare `git` with no arguments prints usage and stays allowed).
- **hooks: `.codex/hooks/prompt_inject.py` drops an unused binding and the three Codex hook scripts are ruff-formatted (they sit outside CI's `src/ tests/` lane, which is why nothing caught them).** The stdin read stays — a provider hook that never drains the event pipe can hand the provider a broken one — but the parse result was bound to a name nobody read (`F841`), so it is now drained without the binding and the narrowed `except (OSError, ValueError)` says why an unreadable event changes nothing this hook prints. `ruff check` and `ruff format --check` are clean over `.codex/`.
- **hooks: the post-compact re-ground's step 2 is honest outside the fleet (measured by @verify from an external project, relayed by @devpulse 2026-09-11).** Step 2 told every agent to run `drone @prax dashboard refresh @<self>`; in a project carrying its own registry that answers `Branch VERIFY not found in registry`, so the step failed on every external branch and the `DASHBOARD.local.json` it then pointed at was four months stale and read `new_mail 0` while the inbox held three. The step is kept rather than skipped — prax owns the resolver half — but it now names that answer and aims the agent at the file's own `last_updated` over its contents, because a stale dashboard read as current is worse than no dashboard. +1 case, 2 mutants red. Also in the same test file: the release-notice version units handed `tuple[int, ...] | None` straight to `_is_behind`, which takes neither optional (10 type findings); a `_parsed_version` helper asserts the parse instead, which turns "must parse" into a claim the units were quietly assuming, and the budget unit's `in` against `__doc__` now checks the docstring exists first.
- **hooks: a cadence unit stops letting a real clock decide a question about token identity.** `test_clear_then_all_loaders_fire` called `should_fire` three times with no `hook_data`, so the per-turn token was `0`, the token guard in `_should_increment` was disabled, and the only thing keeping the three sibling loaders on one turn was the 2.0 s `_DEBOUNCE_S` mtime window — green when the unit ran alone, red twice in a 207 s full-suite run when more than two seconds passed between the first call and the third. The siblings are now handed the same `transcript_path`, which is what holds them together in production; proved by forcing `_DEBOUNCE_S` to 0, where the old text goes red and the new text stays green. Found while verifying an unrelated dispatch, not caused by it.
- **api: the attach lane's real-PTY tests measure the pump instead of the runner's package list, and the descriptor census stops reading `/proc` (macOS CI run 34704362515, 15 failed + 8 errors; Linux audit gate run 34703057231 under seedgo's new `host_portability` standard — FPLAN-0554 rows, api owning).** Every one of the 23 reds in `src/aipass/api/tests/test_host_attach.py` said `AttachUnavailable: tmux is not installed on this host`, and not one of those cases runs tmux: they replace the argv with `cat`, `echo` or `pwd`, or patch `Popen` outright, so `open_attach`'s preflight was their only tmux dependency and what they measured on a green Linux box was the runner's package list. A `tmux_preflight` fixture now satisfies that preflight — one shared rule, `_forced_tmux_which`, which answers a stand-in path for tmux ONLY and delegates every other lookup to the real `shutil.which`, because a blanket yes would report the monitor lane opening a watch on a host with no drone installed. 15 cases and the `cat_session` fixture hold it; the argv-composition pins in `TestOneRoomHonoursAnOutsideSeat` had already set the precedent. One of the 23 was worse than red: `test_a_failed_spawn_leaks_no_descriptors` asserts `AttachUnavailable` from a spawn that raises, and on a tmux-less host the preflight raises that exact class three lines earlier — the case would have passed while measuring nothing. Its census is the Linux-audit row: `/proc/self/fd` at :912 and :919 is absent on macOS, so an `_open_descriptors()` helper reads `/dev/fd` (a symlink to `/proc/self/fd` on Linux, fdescfs on macOS) and a host exposing neither skips by name rather than counting wrongly. Three cases added, each manufacturing the macOS half on this Linux box: the lane opens with `shutil.which` answering None for every binary, the forced preflight answers for tmux and nothing else, and the census still counts this process's own descriptors with every `/proc` read raising `FileNotFoundError`. Proof of both directions from this seat — the pre-cure file under a manufactured macOS host (no tmux, no `/proc`) reproduces exactly 15 failed and 8 errors, the cured file is 115 green under the same host, and 5 mutants (`/dev/fd` back to the Linux literal, a constant census, a blanket preflight, a preflight that stops special-casing tmux, one that answers None for it) all go red. Product code untouched; `git_reads.py` carried a separate docstring correction in the same pass (#737 closed as designed: reading a foreign project does not provoke drone's caller-verification refusal, since drone runs from this server's own citizen directory with the project as an argument). FOLLOW-UP, the one red left on the real host after that (macOS CI run 34707099650 on 3ef3d571: 22 of the 23 cured there, all 8 errors gone). `test_a_real_child_ends_up_owning_the_terminal` read the child's pgid AFTER the `finally` block had hung up and reaped it — macOS answers ESRCH for a pid that is gone while Linux keeps a zombie's pgid readable until its parent reaps it, so the read-after-death was green here for a reason with nothing to do with the property under test. Both reads now happen while the child is alive and the assertion compares the held value; the case carries the macOS rule as a stand-in (`getpgid` refuses once the session is closed), so moving either read back below the hangup goes red on this box too. Reproduced exactly before curing: HEAD's copy of the file, under a plugin that refuses `getpgid` for a zombie or absent pid, raises `ProcessLookupError [Errno 3]` at the line the runner named and passes on a plain Linux host — and the cured file is 115 green on Linux, under that plugin, and under the full manufactured runner (no tmux, no `/proc`, ESRCH on a reaped pid).

- **devpulse: the watchdog cure's own reds on the two hosts it was written for (macOS CI run 34704362515, 1 new failure; Windows CI run 34704362507, 25 failures, all devpulse; FPLAN-0554 follow-up, tests only).** The macOS one: `test_wire_never_spawns_anything` monkeypatched `subprocess.Popen` to explode on ANY spawn while its claim was Rule 2, "idle is zero running processes", so the new portable `lsof` probe (waited, reaped before the arm returns) tripped a pin that read wider than its claim. Replaced by `test_the_wire_leaves_no_process_running[host|darwin]`: a recording `Popen` subclass refuses a detached spawn by name and asserts every recorded process is reaped when the arm returns, the darwin lane runs for real on Linux and asserts it reached the probes; two mutants (a process left running, a detached daemon) go red on both lanes. The Windows 23: lsof does not exist there, so the continuous arm's new honest refusal (`BASELINE DEAD: stdout target unresolvable`) fired in every world-building test that had never been taught the host has no resolver. An autouse fixture now asks `wire._stdout_target()` and, only when the host cannot name a target, hands the arm a regular file under `tmp_path` (not under a `tasks` dir, so the run_in_background tripwire stays quiet); eight probe-level and refusal-pinning tests opt out via `raw_stdout_probe` so they keep testing the code. A manufactured win32 world on Linux reproduced 29 failed before and reads 0 after. The other two: `test_a_zombie_watch_is_pruned_off_linux` forced darwin on a real Windows host and the registry file lock then imported `fcntl` (win32 skip naming the recipe); `test_the_zombie_rule_is_not_duplicated_in_this_module` split so the no-second-copy half runs everywhere and the call-through skips on win32, where `_pid_alive` answers from OpenProcess and correctly never asks the registry. `os.kill(pid, 0)` is safe on Windows (`CTRL_C_EVENT` is 0, TerminateProcess is unreachable below signal 2), so the four forced-darwin liveness tests stay running there. The lesson, recorded with seedgo: a cure for host B proven on host A by monkeypatching the platform was never run on host C, and the old pins were never run under the new lanes anywhere.

- **drone: the broker's non-Linux path resolver stops reading `/proc`, so path resolution works off Linux at all (CI run 34686193857, seedgo's `host_portability` ruling — row 1, product defect; FPLAN-0557, drone owning).** `apps/handlers/broker/path_resolver.py:135` lived in `_resolve_via_walk`, the fallback taken exactly when the platform is NOT Linux x86-64, and answered *which path did I just verify?* with `os.readlink("/proc/self/fd/<fd>")` — Linux furniture. The lane that exists for other hosts therefore raised `FileNotFoundError` on every broker path resolution on macOS; the identical spelling at `:101` is reached only under `_openat2_available()` and is untouched, which is the one-hop caller acquittal the new standard was built to make. The cure keeps the property the fd walk exists for — the verified path cannot be swapped under you: the leaf is now `lstat`ed relative to its verified parent's fd, with an explicit symlink refusal standing in for the `O_NOFOLLOW` the open used to carry, and the assembled path is returned only if it `lstat`s to the same `(device, inode)` the walk verified, so a component swapped mid-walk yields an error instead of a path nobody checked. Flags now come from `os` rather than written-down Linux numbers: `0o0400000` is `O_NOFOLLOW` on Linux and `O_NOCTTY` on macOS, so the literal would have quietly traversed the symlinks it was there to block — a worse bug than the crash it sat behind. A host with neither `O_NOFOLLOW` nor `dir_fd` support is refused rather than served unverified. +8 cases drive the walk with `/proc` poisoned and both lanes compared; 6 mutants red, 0 survivors; `path_resolver.py` 1.0.0 → 1.1.0.

- **drone: `test_a_folder_holding_only_the_callers_own_tree_is_allowed` carries the `deletable_cwd` marker, and the verdict it claims is now pinned on every OS (Windows CI run 34686193857, 1 failed of 20925 on head bd3b104e — row 2, ruled TEST DEFECT; FPLAN-0557, drone owning).** The unit builds its world by deleting the directory the process stands in: it chdirs into `spawn` and deletes `..`, because standing inside your own tree is what makes you its owner. Windows holds the current directory open without delete sharing, so the `rmtree` raises `[WinError 32]`. What failed there is the removal, not the claim — every drone guard passed, and the fence's verdict (a folder holding only the caller's own tree, template skeleton included, is no stranger's) is host-independent. drone has had a named convention for exactly this since the deletion-record work — `deletable_cwd`, registered in src/aipass/drone/tests/conftest.py, skipped on Windows with the whole reason written out and portable siblings beside each skipped unit — and this unit simply never got it. Cured to that convention: the marker on the end-to-end case (11 units carry it now), the fence verdict asked of `check_carveouts` directly so Windows keeps the claim, and the Windows half manufactured at the seam — an injected `rmtree` that refuses to remove a live cwd — proving the refusal is the host's and not ours. One message-only product change beside it: when a delete fails and the caller's cwd is inside the target, the result and the ledger `reason` now name where the process is standing and say to run `drone rm` from outside it; no outcome changes, and POSIX never reaches it because the delete succeeds there. Unchanged for a Linux caller: `drone rm ..` from inside a branch still completes, leaving their shell in a directory that no longer exists, which drone already answers for. @prax's weekly `drone rm --stale 10d ..` sweep is unaffected on every host — stale mode unlinks regular `*.tmp` files inside `*_json` folders and never removes a directory, so nothing it deletes can be anyone's cwd. 4 mutants red, 0 survivors; 1339 green both rootdirs.

- **devpulse: watchdog is honest off Linux — three `/proc` reads that quietly answered "" or None on macOS now have a portable half (macOS CI run 34682737363, seedgo's `host_portability` ruling FPLAN-0554, devpulse owning).** `/proc` is absent on macOS and every one of the three degraded into a lie the caller could not see. **Row 1**, `watchdog/wire.py:_cmdline` — the `/proc/<pid>/cmdline` read answered "" for every pid, so `_looks_like_ours` was False for every pid, every live wire read as a recycled pid and was left alone instead of taken over, and dispatch completions were never delivered; the /proc read is now the `sys.platform == "linux"` fast path and `ps -p <pid> -o command=` answers everywhere else. **Row 2**, `wire.py:_stdout_target` — `os.readlink("/proc/<pid>/fd/1")` answered None, so a continuous wire armed, said `armed` on stderr, recorded wrapper `foreground` / stdout `null` in the registry, and woke nobody ever; the probe now falls back to `lsof -p <pid> -a -d 1 -Fn`, and because "cannot tell" is still a possible answer a CONTINUOUS arm whose stdout target is unresolvable now refuses by name (`BASELINE DEAD: stdout target unresolvable`, exit 1) instead of reporting armed — `--once` is untouched, it exits on delivery so any wrapper hears it. **Row 3**, `watchdog/registry.py:is_pid_alive` and `watchdog/agent.py:_pid_alive` — both gated zombie detection on `sys.platform == "linux"`, and `os.kill(pid, 0)` SUCCEEDS for a zombie, so an exited-but-unreaped pid read alive: `kill_watch` reported `killed=False` "still alive after 2.0s" for a process it had just killed, and `list_active(prune_stale=True)` kept a dead watch listed. One portable `registry.is_zombie(pid)` (/proc/<pid>/status on Linux, `ps -o state=` elsewhere, a state beginning `Z` is a corpse) is now called ungated at both sites; agent.py imports it rather than keeping a second copy — registry.py imports nothing from agent.py, so there is no cycle and no rule to drift. 18 new tests run the macOS paths on the Linux box (monkeypatched `sys.platform` plus `ps`/`lsof`-shaped `subprocess.run`) and 8 of them go red against the old code; 594 green, ruff clean, seedgo audit 100% with Host_Portability 100%.

- **prax: the discovery watcher's own two events reach the trigger bus for the first time (DPLAN-0339 follow-up 2, FPLAN-0556, prax owning).** `handlers/discovery/watcher.py` held a module-level `from aipass.trigger.apps.modules.core import trigger` that could never succeed and never had: the module is still executing its own import when it reaches that line, trigger's `core.py:20` imports prax's logger, prax's logger imports `is_file_watcher_active` back out of the partially initialised watcher, and the import dies with `ImportError`. Python discarded `core` and kept the three `aipass.trigger` parent packages it had already created, so every process that logged carried three package shells it never used — and, far worse, the fallback pinned a module-level `_HAS_TRIGGER = False` that nothing could set back to True, leaving both fires in the file permanently unreachable: `module_discovered` and `file_watcher_died` had never once fired. `file_watcher_died` is the escalation path for DPLAN-0305, and the step-4 decision in DPLAN-0339 to keep it was made about a fire that was already dead; a gate that is always closed and a bus with no listener look identical from outside. Cured with `_get_trigger()`, which imports at the fire site guarded `(ImportError, OSError)` to a warning and returns None when the host cannot supply a bus; `_HAS_TRIGGER` dropped, since a flag with one reachable value told nobody anything. Proved: a throwaway under `AIPASS_TEST_LOG_DIR` driving `on_created` and `_report_watcher_death` sees both events on a listener double attached to the real bus; a fresh interpreter that imports the logger and logs one line now holds **no** `aipass.trigger` module at all, not even a shell, with the first `.info()` at 0.010 s (was 0.012 s with the shells); a denied trigger import still lets the watcher import, the discovery scan complete and the death report go out. `test_watcher.py`'s pins on the old placement were rewritten rather than deleted — the 2026-08-31 Windows CI lesson (the guard must be as wide as `OSError`, because trigger's own import guard raises `FileNotFoundError` without a readable cwd) is kept in full; only the placement they encoded was dropped, and the placement was the defect. +7 cases, 1541 green both rootdirs, ruff clean, audit 100.
- **prax: the two explicit logging lifecycle doors fire lifecycle events again, and the audit gate is green (DPLAN-0339 follow-up, FPLAN-0555, prax owning).** Removing the hot-path `startup` fire in step 3 left `apps/modules/logger.py` with no `trigger.fire` at all, and seedgo's Trigger standard gates its Pattern 9 check on a file-level flag — so `initialize_logging_system` and `shutdown_logging_system` had been passing only because the hot-path fire happened to live in the same file. The audit dropped to 99% and the Linux CI audit job failed on run 34682737344. Cured the way the standard asks: `initialize_logging_system()` fires `logging_system_initialized` (carrying `modules_count`) after `run_initialize` returns, and `shutdown_logging_system()` fires `logging_system_shutdown` after `run_shutdown`, last, so the event reports the system *is* down. seedgo's event table names no system-lifecycle event, so those two names are prax's, following the convention it does state (lowercase, underscore-separated, past tense). Both imports are INSIDE their function: `from aipass.prax import logger` and every log line the fleet writes must stay clear of the `aipass.trigger` import graph, which was 0.339 s of a 0.361 s first log line before step 3; each fire is guarded `(ImportError, OSError)` exactly as the removed one was, so a host where trigger cannot import still gets a working door and a warning. Proved: `drone @seedgo audit aipass @prax` 100% with zero violations, both events fire exactly once against a listener double, a fresh interpreter that logs one line loads nothing under `aipass.trigger.apps.modules` and still pays about 0.011 s for its first `.info()`. Found while proving it and REPORTED, not fixed here: `handlers/discovery/watcher.py:57` attempts a module-level trigger import that always raises `ImportError` (circular import back into the partially initialised watcher), so `_HAS_TRIGGER` is False in every live process and `module_discovered` and `file_watcher_died` have never actually reached the bus. +6 cases in `test_logger_module.py`, 1534 green both rootdirs, ruff check and format clean from the repo root.
- **prax: discovery is a scheduled scan — the first log line of a process no longer starts a filesystem watcher, and the registry is a truthful snapshot for the first time (DPLAN-0339 step 4, FPLAN-0553, prax owning; Patrick 2026-09-12: "ok proceed").** `SystemLogger._ensure_watcher` started `start_file_watcher_in_background()` on the first log line of **every process in the fleet**: a daemon thread that walked 1,589 directories, installed one inotify watch per directory and died with the process. Short-lived processes never finished it; long-lived processes that merely logged carried a whole-tree watch by accident (6,356 of this machine's 6,634 watches were four such processes). It was also not doing its job — measured 2026-09-11, the registry held **250 of the 1,442 modules a scan finds (17%)**, because a module was registered only if it happened to be created while some process was both alive and still walking, and it never pruned: the first real scan removed **55** entries, including probe files deleted in August. **New: `drone @prax discover run`** (the verb archived 2026-03-18, restored; bare `discover` shows introspection, per the fleet's module standard — a bare word must not rewrite the registry) walks once through the existing scanner and writes the registry as a snapshot — added, removed, `discovered_time` carried over for known entries — printing added/removed/unchanged/total. **New: `module-scan-daily`** in prax's `.daemon/schedule.json`, 04:30 daily, `timeout_seconds` 60, `notify: false` deliberately (a daily "0 added, 0 removed" mail is noise and daemon's notify.email costs 5-7 s of tick time on start *and* finish with no failure-only option; the record is the FIRE/DONE lines, the runstate row, and the `last_scan` block the status line reads). Proofs, throwaway processes under `AIPASS_TEST_LOG_DIR` with the live tree untouched except the registry and schedule prax owns: first scan **+1,245 / -55 / 197 unchanged**, second run **0 and 0** (5.5 s wall, walk 0.18 s); a long-lived process that logs once now holds **0 inotify watches** and has **no `prax-watcher-start` thread** (`MainThread` only) where the old path in the same process shape gives **1,589 watches and three watchdog threads**; first `.info()` **0.011 s** (0.420 s before step 3, 0.016 s after it) and steady state **improved** from 0.402 to **0.232 ms/line**, which was not the plan — step 3's figure still carried the background walk contending for the GIL, and with the walk gone the contention DPLAN-0339 measured in both directions is simply absent. `drone @prax status` loses the `File Watcher` line, which reported the *calling* process and so read "Inactive" on every run while discovery was healthy, and gains `Last Scan: <timestamp> (+added / -removed)`. **Kept deliberately:** `initialize_logging_system()` → `start_file_watcher()` is an explicit synchronous door that keeps a watcher for the life of its process, so the liveness check, the `died` record and the `file_watcher_died` fire all stay for it (DPLAN-0305). Logging never depended on discovery: a module gets its log file when it logs. Found and fixed during the build: a new prax module must guard `if command != "<name>": return False` or it claims every command — `discover` sorted first and answered `drone @prax status` once before the guard went in. logger.py 1.3.0, status.py 1.2.0, registry save.py 1.1.0 / load.py 1.1.0, new `handlers/discovery/scan.py` and `modules/discover.py`; +18 cases in three existing test files (no new test file), 1528 green both rootdirs, ruff check and format clean from the repo root, audit 99% with only the known step-3 lifecycle violation outstanding.
- **prax: the first log line no longer fires a `startup` event — `trigger.fire("startup")` is gone from `SystemLogger._ensure_watcher` (DPLAN-0339 step 3, FPLAN-0552, prax owning).** Every process in the fleet fired a startup event on its first log line, and that fire *was* the first log line: **0.339 s of its 0.361 s, 94%**, nearly all of it importing the `aipass.trigger` graph so one event could reach one handler. What it bought was an error catch-up scan in trigger's `handle_startup`; at 5.1 fires a minute, 100 of 100 of those runs found 0 errors, and because every process shared one throttle a hook or a drone command routinely consumed the recovery window seconds before the scan that needed it. Recovery now has an owner of its own (trigger's step 2, above): `log_watcher_service` calls `run_error_catchup()` at service start, live since the `Startup error catch-up complete` line at 00:28:08. Medic's digest lane never rode the fire — it calls `run_startup_catchup()` directly, deliberately. Measured 12 throwaway processes each side under an `AIPASS_TEST_LOG_DIR` redirect with the live tree untouched: first `.info()` **0.420 s -> 0.016 s median** (ranges 0.336-0.826 and 0.012-0.021), about **26x**, while steady state did not move (0.390 -> 0.402 ms/line, same spread). Proof the per-process fire is gone: trigger's `startup_log.json` ring gained **40 records from a batch of 40 short processes before the change and 0 after** — counted by timestamp, because the ring is capped at 100 rows and a raw count is saturated at 100 either way. The event still exists, still has exactly one listener (trigger `registry.py:87` `handle_startup`), and `drone @trigger fire startup` still works; nothing fires it per-process any more, by design. The double-checked-locking flag stays and its comment now states what it actually guards, since the recursion it named is gone. logger.py 1.1.0 -> 1.2.0, 1510 green both rootdirs, ruff check and format clean from the repo root, audit 100. Not in this step: the `died` record and the background watcher start.
- **trigger: the log-watcher service runs its own error catch-up at start, and `last_scan_timestamp` advances only after a scan that read every file (DPLAN-0339 step 2, FPLAN-0551, trigger owning; Patrick 2026-09-12: "ok proceed").** Until now the catch-up ran only through `handle_startup`, the sole listener on the `startup` event, and the only production firer of that event is prax's `logger.py:132` on the first log line of every process; the service itself never ran one, so its recovery window was whatever the last drone command left behind. `log_watcher_service.main()` now calls `medic.run_error_catchup(trigger.fire)` once after its watchers are up (after, so nothing lands between the scan and the first watch; overlap is safe because the registry dedupes on fingerprint), guarded so a failed scan never costs the watching, and as a direct call rather than a self-fired event, because a fire into zero listeners returns `handlers:0` and reads as success. Row 12 cured: `_scan_system_logs_for_errors` returns `ScanOutcome(errors, completed, reason)`, `completed` meaning every candidate `system_logs/*.log` read to its end; the time budget between or inside files, `MAX_ERRORS_PER_SCAN`, and a file skipped for `MAX_FILE_SIZE_BYTES` all hold the cursor so the next run re-covers the window, bounded by `MAX_LOOKBACK_HOURS` (measured 181 ms cold against 161 ms warm over 363 files). Processed hashes persist on both paths, so a held cursor cannot re-dispatch what was already handled. The `startup_catchup` record now carries `completed` and `reason` beside `errors_found`, and a held cursor writes its reason to `medic_suppressed.jsonl`. Tests: an autouse `isolate_catchup_state` fixture redirects the catch-up state, its legacy path, the suppression log and the trail logger into `tmp_path`; +16 cases across three existing files, 1068 green both rootdirs, 12/12 mutants red, ruff clean, audit 100. Live: the service restarted clean at 00:28:07 with `Startup error catch-up complete` on its first second. Listener pin for step 3: `registry.py:87` is the only listener on `startup` fleet-wide, so prax can drop the per-process fire.
- **prax: `start_file_watcher()` no longer writes a `discovery_watcher_event` `started` record — the write raced its own process's exit and was 87% of the ecosystem's orphaned staging temps (DPLAN-0339 step 1, FPLAN-0550, prax owning; Patrick 2026-09-12: "ok proceed").** Since the 09-04 move to the unjoined `prax-watcher-start` daemon thread, the record was written at the end of the inotify walk — measured on HEAD `d6deeb42` at **0.431–0.440 s** wall (CPU 0.133 s, so 70% of it is GIL waiting) — while a short-lived process such as a hook or a drone command logs once and exits at **0.394–0.433 s**. Interpreter exit kills a daemon thread wherever it stands, temp-and-rename included, so the record was written inside its own destruction window on every process, every time; the FPLAN-0542 data-leg bump rides on the same `log_operation`, so each dying process staged two writes, not one. Removing the single call removes both. Nothing was traded away: `watcher_log.json` has no reader in production, in the tests, or anywhere in the fleet (re-grepped; the only other `discovery_watcher_event` writer is the `died` record, left alone and decided separately). Proof, 240 throwaway processes each side under an `AIPASS_TEST_LOG_DIR` redirect with the live tree untouched: **6 orphans before, 0 after**, and `watcher_log.json` came through all 240 with its mtime unchanged — the record is not merely unobserved, it is never written. The after-run carried higher load than the before-run (7.71 vs 3.71), so the race had more chance to fire, not less. First-log-line cost unchanged, as expected: this step is litter, not speed. Worth recording for whoever re-runs it: the orphan rate is load-dependent — the same 40-process reproduction that gave 3 of 40 on 09-11 gave **0 of 40** on 09-12 before any change, because a slower first line pushes exit past the 0.43 s write, which is why the baseline here is 240 processes and not 40. watcher.py 1.3.0, 1510 green both rootdirs, ruff clean, audit 100. Explicitly not in this step and separately ruled: the `died` record, `trigger.fire("startup")` on the first log line (94% of that line's 0.361 s), and the background watcher start itself.
- **CI: the macOS test job could not fail on test failures (@verify c89af1b3, found fact-checking Vera's Update #21; devpulse, 2026-09-11).** `pytest ... | tee pytest-output.txt` returned tee's status, and the `EXIT_CODE` the step wrote to `GITHUB_ENV` was read by nothing, so the v2.8.6 merge a526fec0 ended `32 failed, 20805 passed, 8 errors`, `EXIT_CODE: 1`, job green, and PR #763's head did the same (`32 failed, 20861 passed, 8 errors`). `set -o pipefail` in the step now makes pytest's status the step's status; `macos-test.yml` and `windows-test.yml` read the same (Windows already carried `shell: bash`, which implies pipefail on GitHub runners, so it failed honestly before and is unchanged in behaviour). The 32 macOS failures are one class — Linux-host assumptions (`/proc`, tmux on the runner, a case-folding filesystem, `/proc/meminfo`) in api, devpulse, skills, seedgo, ai_mail and prax — and go to seedgo as a red-to-rule row; until they are cured the macOS check on dev reads red, which is the truth.
- **prax: `drone @prax dashboard refresh @branch` resolves external-project branches, and the bare `refresh` follows the caller instead of prax (Vera Studio 77f3335d; FPLAN-0548, prax owning).** `resolve_branch_path` read `AIPASS_REGISTRY.json` only, so a branch of a project outside the AIPass tree got `Branch VERIFY not found in registry`, exit 2. It now tries the core registry first, unchanged, then the nearest `*_REGISTRY.json` at or above the caller's directory (the exact-case filter reused from `branch_detector`), with a relative path resolved against that registry's own directory; a name in both goes to core and a WARNING names both rows; a total miss says which two registries were tried. Found and cured on the way: drone runs every branch with its cwd set to the branch, so inside prax `Path.cwd()` was always prax and a bare `refresh` from any other branch refreshed PRAX; `_caller_dir()` in `modules/dashboard.py` now reads `AIPASS_CALLER_CWD` first, falls back to the process cwd for a direct run, and refuses by name with neither (it lives in the module because `test_repo_root.py` allows exactly one cwd read in prax). Prax's own measurement corrected on the way: the dashboard's `new_mail` never came from the mail central (it counts the branch's `.ai_mail.local/inbox.json` directly), so a resolved external branch stamps its true count, not 0; the central-built ai_mail section is built, read by nothing and popped before save, and the comment that said otherwise is fixed. Pinned by test: central lists only FLOW, branch inbox has 3 new, `new_mail` is 3. +7 functions / +8 cases in `test_operations.py`, 10/10 mutants red in an overlay copy, 1510 green from both rootdirs, audit 100. Live: from a throwaway project with its own registry, `refresh @zeta` exits 0 with the true count and `@nosuch` exits 2; from `src/aipass/flow`, bare `refresh` refreshes FLOW; and from Vera Studio's verify directory, `refresh @verify` now writes `5 new emails`, the truth, where it refused before. `--all` still covers core only.
- **skills: `system_status` answers off Linux, and `summary` stops calling a partial report a good one (FPLAN-0554 rows A/B/C, macOS runs 34704362515 and 34707099650; skills owning, devpulse landing).** `lib/system_status/handler.py` read `/proc/meminfo`, `/proc/uptime` and the `/proc` process table, so on the macOS runner `memory`, `uptime` and `processes` each returned `success: False` every run and `summary` returned `success: True` over a disk line plus an `Errors:` trailer — a caller that checks `success` read a disk measurement as a system report. All three now ask psutil (`virtual_memory` / `boot_time` / `pids`), a declared dependency at `psutil>=5.9`; `disk` was always portable (`shutil.disk_usage`) and is untouched; a host that cannot import psutil is refused by name with the install recipe rather than served a partial; and `summary` is now `success: False` with `error` naming each missing section, while still handing back the sections that answered. `buffers`/`cached` print only where the platform has them (macOS has neither) instead of a zero that reads like a measurement. The four skills cases that were red every run carried `skipif(sys.platform == "win32")` — a guard naming the one platform that was never the problem — and are now unguarded; +16 cases manufacture the macOS half on this Linux box: `sys.platform` darwin, every `/proc` read refused, and a psutil stand-in shaped like macOS's `virtual_memory`. The stand-in is part of the world, not a shortcut around it — psutil's *Linux* backend reads `/proc` through plain `open()`, so denying `/proc` with the real psutil in place would have manufactured a failure no Mac can have. Three controls hold the world (the denial is live, it can still say yes, the process table is gone too); 11 cases go red on behaviour against the pre-cure handler and 8 mutants were killed. Reported, not cured: the audit corpus is `apps/` (plus `tests/` for the branch-level arms) and never enters `lib/`, where all seven built-in skills live — which is why `Host_Portability` read 100 on this branch while the skill was red on every macOS run. 1425 green from both rootdirs (1409 before), ruff check and format clean from the repo root, seedgo audit 100 with Host_Portability 100.
- **skills: the telegram skill answers a host without tmux or systemd instead of raising (FPLAN-0554 round three; seedgo's host_portability now reads `lib/` and scored skills 97; skills owning, devpulse landing).** 12 calls ran `tmux` or `systemctl` with no probe and no `FileNotFoundError` handler (`base_bot.py` 7, `bot_factory.py` 3, `tmux_manager.py` 2), and a missing binary raises out of exec before any return code exists. One was a real escape: `tmux_manager.session_exists` is called above the `try` in `send_message`, `kill_session` and `get_session_pane`, so on a tmux-less host all three raised past their own `except Exception`. Every call site now catches the exec failure where it sits and returns a verdict: `session_exists` False (so `kill_session` has nothing to kill, `get_session_pane` is None, `send_message` is False), `_send_rename` logs, `inject_message` and `_kill_tmux_session` return False, `/start` and `/kill` reply `tmux not found on this machine.` as their has-session probe already did, `launch_mirror_session` returns False when tmux is gone at new-session or at either send-keys (a session nobody typed into is not a mirror session, and the old code returned True over it), and `/suspend` on a host with no `systemctl` disarms the alarm and says `systemctl is not installed on this host.` instead of polkit advice that cannot work there; a suspend systemd refused keeps the polkit text byte-identical. No `shutil.which` probe: every unit here mocks `subprocess.run`, and a probe would make them measure the runner's package list (api 3ef3d571). +13 cases in five existing telegram test files, all 13 red against the pre-cure handlers; 11 mutants red, sources md5-restored. The skill stays switched OFF since 2026-08-18, so nothing live changed. 1438 green from both rootdirs (1425 before), ruff check and format clean from the repo root, seedgo audit @skills 100 with Host_Portability 100.

### Changed

- **prax: the module data json is wired — every log write bumps the module's lifetime `operations_total` and stamps `last_operation` (DPLAN-0325 After, DPLAN-0337 R6, FPLAN-0542).** The three legs finally each mean something: log is the rolling per-module operation trail, data is lifetime state, config is the rotation cap. The bump is read-modify-write after the log entry lands, every other key preserved (rate_tracker's `files`, the old-era `operations_successful`/`operations_failed` left as they are; no success signal exists to count them by), a failed log never counts and a failed bump never changes the log's answer; under racing writers the total is a lower bound. A data document that parses as a dict but lacks a base key is now healed in place instead of replaced (the old replace-on-invalid would have wiped state other writers keep there). rate_tracker saves by updating its own key, so `created` and the counters survive. Measured before the wire: 585 data files fleet-wide, none ever updated after creation in tracked history. Cost: about +5 ms per log call (a second staged write). json_service 1.2.0, rate_tracker 1.3.0, 15 new pins in the existing test file, 17 mutants red, the 18 shims unchanged by hash.
- **devpulse: the release mail's update ritual carries the stamp-only exception (DPLAN-0337 R1).** Step 3 now says a plan that reads stamp only needs no go, run the apply and read the receipt, and step 4 says the apply prints a receipt of what it did. The hooks `release_notice` sentence ("Apply ONLY with Patrick's or devpulse's go") is @hooks' and goes in their window.
- **daemon: the nightly rounds are ON — one citizen a night, 05:00, opus, fresh, alphabetical roster, budget rules in the prompt; the inbox-sweep job that woke up to five agents at 09:00 is deleted (Patrick, 2026-09-10 20:52–21:06, DPLAN-0337 R2; DPLAN-0287's design, built in August and shipped disabled).** Patrick's frame: nightly maintenance is one agent in rotation getting time to keep its own lane — inbox to zero, todos against reality, dashboard, logs, self-audit, the work others asked of it inside its own domain — never a fan-out, and always inside a budget: never dispatch or wake another citizen, at most two sub-agents (sonnet or lower), never edit another branch, no fleet-wide investigations, write down what is outside your lane for devpulse and stop. The night's one artefact is a mail to @devpulse (health verdict, what you did, what you noticed, what you need), so the morning reads "memory did its rounds, all fine, noticed X" and Patrick decides whether it becomes an issue. Usage limits are his to watch, not the agents'. `fleet-steward` is renamed `rounds` (never fired, no runstate to migrate); the roster is sorted by email; `rotation.py` and `inbox_sweep.py` pass ai_mail's new `wake_back=False` so @daemon is never woken back; the APLAN step and the "reply to this dispatch" line are gone (a rounds wake is a session prompt, not a mail — there is nothing to reply to). The `inbox-sweep` command stays as a hand tool, nothing schedules it. Proved on a copy of the live runstate with the clock at tomorrow 05:01, wake caught at ai_mail's seam: fired once, woke @ai_mail with `fresh, auto, sender @daemon, model opus, wake_back False`, pointer advanced, night two serves the next name, nothing fires at 21:15. Pins: the shipped stanza read-only (id, on, 05:00, opus, fresh, no managers, budget text in stanza and fallback), the real tick, a signature pin that goes red if `wake_branch` loses keyword-only `wake_back`, the roster-order pin red under registry order, the sweep-row pin inverted. 10 mutants red, 611 green both rootdirs, ruff clean, audit 100 `--full`. First real night 2026-09-11 ~04:45 (a daily window fires on its first tick): @ai_mail. **Scope, ruled the same evening (Patrick 21:47, "very important"): AIPass maintains its OWN agents — the roster is the framework fleet under `src/aipass/` only, never `projects/*` residents or external roots; Vera has her own schedule and the other projects are nowhere near a trust stage.** The first build read the whole fleet map and served 21 names (Vera-Studio's three, DEMO's one); `ROSTER_SCOPE` in `handlers/schedule/rotation.py` 1.2.0 now enforces it by PATH before any passport is read (a citizen_class can never bring an outsider in, `include_managers` cannot widen it), the status surface prints `Scope: framework fleet only`, and a discovery-level pin builds a temp install with one branch of each tier and proves only the framework one is served — its fixtures moved to their real tiers, because every earlier fixture sat under `src/aipass/`, "projects/baud" included, and would have pinned nothing. Roster: 17, @canary in. `run.py` 1.5.0 also passes `wake_back=False` on every clock-fired wake (@seedgo's weekly shadow-cycle, @vera's release-watch): all nine discovered job prompts were read, none asks the daemon for a reply. 6 named mutants red, 616 green both rootdirs, ruff clean, audit 100 `--full`.
- **ai_mail: `wake_branch(..., wake_back=False)` — a scheduled wake that wants no answer no longer wakes the scheduler back (DPLAN-0337 R2, FPLAN-0541).** Measured in the monitor log: @daemon was woken back four times on 09-10 and twice on 09-09 (four more blocked by its own lock) after branches its inbox-sweep had woken finished, each a fresh session to read an empty inbox; Patrick: nuisance token waste. The keyword-only flag rides the monitor argv as `--no-wake-back` (an argv flag, not env, because the spawn env becomes the agent's own and would leak the choice into every dispatch it makes); when declined the monitor neither wakes nor mails the sender and logs one INFO line, the register row carries `wake_back: false`, and the default path is byte-identical (default rows carry no key). No CLI flag: the dispatch verbs always arm the wake-back, that is the team-mission contract; library callers such as @daemon's rotation pass it. 14 pins in the existing monitor, wake and register tests (the declined path red on the old monitor: sender wake 1x, manager mail 1x); 11 mutants killed, 0 survivors; 1486 green both rootdirs, ruff clean, audit 100 `--full`. Left named in @ai_mail's todos: the legacy `handlers/dispatch/daemon.py` builds its own monitor argv and will never carry the flag.
- **aipass: a stamp-only `aipass init update` — a plan where no file would change and only the manifest's record of the version is pending — now applies without Patrick's or devpulse's go (Patrick, 2026-09-10 20:26, DPLAN-0337 R1; DPLAN-0335's open question, FPLAN-0540).** Every release that changes no template leaves every project in exactly this state, and the door asked for a go on each one — spending the go on the one plan that touches nothing, which teaches people to approve without reading. Patrick's frame: no silent processes; the dry run prints what would happen, every apply prints a receipt of what did, and the receipt is the contract, not the go. The plan gains `stamp_only`, derived from the same write queues as `pending` so the two can never disagree about what apply would do (`stamp_pending and not file_writes`); `--json` carries it so a manager's agent reads a key rather than parsing prose. The dry run keeps exit 2 — the stamp IS a write, and 2 keeps meaning "there is a plan to read" — while its last line changes from asking for a go to naming the apply as the next move. Any plan that would write a file keeps today's sentence. A kept-local file whose `.aipass-new` is already current writes nothing and so stays stamp-only (the Vera-Studio shape R1 was ruled on); one still needing its sidecar does not. Also cured in the receipt: after an apply the stamp row read `pending` — a lie in the one block Patrick has made the contract — and now reads `written`. Verified against live Vera-Studio by dry run only (`stamp 2.8.4 → 2.8.6 pending`, `0 of 8 file(s) would change`, the stamp-only sentence, exit 2, `"stamp_only": true`, a 28,283-entry tree sweep byte-identical across two runs); the apply receipt shown on a `/tmp` copy of her scaffold, every file but the manifest byte-identical after. Nine pins in the existing `test_bootstrap.py` and `test_init_flow.py`, end to end through the real handler on `tmp_path`. Six mutants of the predicate; five red at first, and the survivor — dropping the stamp half — was a real gap: every pin had aged the stamp, so none covered a fully current project, where that mutant would tell a manager "no go is needed, run the apply" for a plan with nothing in it. Pinned, re-run, red.

## [2026-09-10] — the open-issue campaign: the post-compact re-ground packed into parts and every hook fan-out merged into ONE answer (#752), the shell reader reading a multi-line command line by line and Git Bash's `/c/` drive spelling (a Windows `edit_gate` hole cured on the way), the ai_mail external-tier boundary failing CLOSED (#754), and a skills test host-state fix; #755 cured out of tree (private integration), #760 and #737 closed by ruling (DPLAN-0336 / FPLAN-0533–0537, merged as PR #762, v2.8.6)

### Fixed

- **skills: `test_validator.py` set `os.environ` outside the `try` and hacked `sys.path` (FPLAN-0525 host_state v5, ENV_MUTATION; DPLAN-0336 sweep).** `monkeypatch.setenv` replaces the bare assignment so a failing assertion no longer leaks the variable into the next test, and the `sys.path` insert is gone because the package import already resolves. 11 green.

- **hooks: the post-compact re-ground backstop sent one ~21,500-char `additionalContext`, and the agent saw the first 2,000 of it (issue #752, FPLAN-0533, devpulse dispatch).** Claude Code persists any hook `additionalContext` longer than 10,000 UTF-16 units to a file and shows the agent a 2,000-char preview, so after a compaction the agent got the header and a sliver of the kernel, and the branch prompt — the seat's own rules, the one section nothing else repeats mid-turn — never landed. The limit was measured, not assumed: read from the installed binary (Claude Code 2.1.267: the hook-output persister compares a JS string length against `sgr = 1e4`, preview `EBe = 2000`), and corroborated from 1,609 hook attachments across every transcript on the machine (largest PostToolUse context shown inline 2,424 chars, smallest persisted 12,148). `post_compact_regrounding.py` 2.0.0 packs the re-ground into parts of at most `REGROUP_FIRE_BUDGET = 9000` (10% under the limit, counted in UTF-16 units, headers and continuation markers included) and hands out one part per PostToolUse, most important first: branch prompt, identity, kernel, navmap. A section stays whole wherever it fits a part and is otherwise split between lines, so nothing is dropped; the header says `k/N` and the count it prints is the count it produced. The manager release notice (DPLAN-0335 leg 2) moved from the tail to the head of the branch section, so it lands in part 1 on every seat. Dropping navmap alone could not fit: a manager seat's header, branch prompt and notice come to 10,103 on their own. The parts ride the cadence regroup token (`cadence.py` 2.3.0, `queue_regroup_parts` / `pop_regroup_part`, both under the state file's flock): the first fire consumes the token and queues the rest, each index is handed out exactly once and the keys go with the last, a real UserPromptSubmit cancels what is left because the turn-0 path then delivers every loader anyway, a new compaction starts over, and a debounced duplicate reset on the same boundary keeps the queue rather than cancelling it. Every fire writes one `hooks_cadence.log` line, `[HOOKS] regroup fired loader=<sections> part=k/N bytes=<utf-8> chars=<utf-16> budget=9000`, as a warning marked `OVER-BUDGET` if one ever exceeds it. Today's seats: hooks 3 parts (8,941 / 5,232 / 7,939), devpulse 3, memory 2, vera 3 (largest 8,961), baud 2 — and proved live when the hooks session compacted mid-build: three inline parts, three sized log lines. Idle cost per PostToolUse 0.11 ms (the pop adds 0.05). 25 pins across the existing `test_post_compact_regrounding.py` and `test_cadence.py` (one notice pin re-pointed to the new order), 15 mutations red — cap, budget, order, notice at the tail, UTF-16 counting, line split, hard cut, re-pack, queue, log, pop advance, key removal, debounce carry-over, prompt cancel, log units — sources restored md5-identical. hooks + daemon 2,498 green from both rootdirs, ruff clean, audit 100 `--full`. No provider wire needed: no handler added, PostToolUse is fan-out.

- **hooks: the shell reader both gates share read a multi-line Bash command as ONE line, and let an interpreter claim every path in the command (devpulse 213c64fd, FPLAN-0534; @aipass hit the second twice curing PR #761).** `bash_writes` 1.4.0. The reported defect: a python step standing before `cd ../../..` took the later pytest argument, resolved it from the seat and named `src/aipass/aipass/src/aipass/aipass/tests/…`, a path that does not exist, so `testwrite_gate` refused an edit of an existing test as a creation and the whole call — edit included — was lost. The resolution rule was not the fault. `_interpreter_targets` was handed the whole command although its docstring already said "the segment"; it now reads its own command plus the heredoc it opened (openers and bodies paired in order, and a pairing that cannot be made keeps the old whole-command read). Measuring it found a worse, unpublished hole in the same reader: a newline never separated. `"\n"` sat in `_SEPARATORS`, but shlex counts it as blank space, so line two of any multi-line command was glued onto line one — `true` then `touch <new test>` reported zero targets, and `cd <foreign>` then `sed -i … f.json` escaped `edit_gate`'s cross-project fence. Newlines now end commands. A backslash-newline still joins lines. A `#` opens a comment only where a word starts outside quotes (shlex cut the line at ANY `#`, so `echo host/#frag && touch f` hid the write, and its comment reader swallowed the newline too). A `cd` inside `( … )` ends with the subshell, and glued operator runs such as `);` are split. This tightens `edit_gate` (writes on line two and later are now seen) and narrows one thing, published in `NOT_CAUGHT`: a path an interpreter receives from ANOTHER command (a pipe, a file) is no longer read as held. 17 pins in the existing `test_edit_gate_bash.py` and `test_testwrite_gate.py` (the 213c64fd repro among them), 11 mutations red — one survived the first round and strengthened its pin — source restored md5-identical. hooks + daemon 2,515 green from both rootdirs, ruff clean, audit 100 `--full`. No provider wire needed.

- **hooks: the engine answered a fan-out event with every handler's stdout joined by a newline, so two JSON answers reached Claude Code as two documents and NEITHER was applied (devpulse bc1bcc45, FPLAN-0535; the residue of issue #752).** The parser was read from the installed binary (Claude Code 2.1.267). It trims stdout and sends anything that starts with `{` to `JSON.parse`. Two valid objects on two lines fail that parse, and because each one passes the schema, the "several JSON documents" plain-text escape does not apply either. The result is the validation error "looks like a JSON object but is not valid JSON", reported as a non-blocking hook error, with neither object applied. Measured in the transcripts: four post-compact re-grounds lost exactly that way on PostToolUse:Edit (devpulse ×3, trigger ×1, 2026-09-02 to 09-08). Each paired `auto_fix`'s `{"systemMessage": "[diagnostics] ok"}` with a re-ground part, because `auto_fix` emits on every clean edit, not only on errors. New `handlers/config/output_merge.py` (the engine was at its size limit) makes the answer ONE document. A single output passes through byte-identical, and plain-only outputs are newline-joined as before. Once any handler answers in JSON, `hookSpecificOutput.additionalContext` strings are joined in handler order by a blank line, `systemMessage` strings by a newline, and other keys are first-handler-wins, with a conflict logged. A plain output beside JSON keeps its audience: context on UserPromptSubmit/SessionStart, `systemMessage` elsewhere. The merged context respects the same 10,000-UTF-16-unit persister limit: the post-compact re-ground (budgeted to 9,000 alone) is placed first, and any context that would carry the total past the limit is dropped with a WARNING naming the handler and its size, never silently. A total of exactly 10,000 lands whole. `engine.py` 1.4.0 calls it in place of the join. Nine pins in the existing `test_engine.py`, including the two-handler merge (the old join is asserted to fail `json.loads`) and the over-limit case. 10 mutations red — old join, re-serialised single output, no priority, priority by entry name only, silent drop, exclusive limit, code-point units, single-newline separator, swapped audience, last-handler-wins — source restored md5-identical. hooks + daemon 2,524 green from both rootdirs, ruff clean, audit 100 `--full` (one `json_structure` bypass: the module parses and serialises in memory and opens no file). No provider wire needed: no handler added or moved.

- **hooks: PR #762 windows-setup red, `test_a_subshell_cd_resolves_its_own_edit` — a pin spelling, and behind it a reader branch that let a foreign write through on Windows (devpulse 401ee814, FPLAN-0537).** The pin spelled its `cd` target with `str()`, so windows-setup got an unquoted `C:\Users\...\AIPass`. Bash eats those backslashes. The reader reads each command two ways and unions the results, and its bash-faithful reading `cd`'d into a directory named `C:Users...AIPass` under the seat, where the existing test did not exist, so `testwrite_gate` refused it as a creation. Reproduced on Linux by back-slashing the real path (exit 2; `as_posix()` exit 0). The pin now spells its path with `as_posix()`, the `C:/...` form bash takes, as do the seven other 1.4.0 pins that put a project path into a command string (one in `test_testwrite_gate.py`, six in `test_edit_gate_bash.py`). The older pins are left alone: they aim the raw path at the write target itself, where the separator reading carries it and windows-setup was green. Checking the reader for the `/c/` form devpulse offered found the branch: Git Bash's own drive spelling, the one its `pwd` prints, resolved on Windows to `C:\c\Users\...`. That directory has no registry, so `edit_gate` ALLOWED a foreign write spelled `/c/Users/<me>/Vera-Studio/f.json`, and `testwrite_gate` called an edit of an existing test a creation. `bash_writes` 1.4.1 reads `/x` or `/x/...` as drive `X:` whenever the path it resolves against is a Windows path; on POSIX `/c` stays a directory. Pinned the platform-oracle way: the reader is made to build `PureWindowsPath` or `PurePosixPath`, so Linux reads like Windows without asserting the host. There are 8 cases (4 drive spellings incl. `cd` and newline forms, the bare drive, `/cache` is not a drive, the respelled CI pin landing on the real file, `/c` on POSIX). 5 mutations red — no drive reading, reading on every flavour, guard on the host instead of the path, bare drive left drive-relative, no boundary after the letter — source restored md5-identical. hooks + daemon 2,532 green from both rootdirs, ruff clean, audit 100 `--full`. No provider wire needed.

- **ai_mail: the cross-project boundary check failed OPEN for external-tier recipients when the sender had no caller cwd (issue #754, FPLAN-0536, DPLAN-0336 campaign).** Since 0748d1b9 the delivery address map's last lookup is the declared-roots external tier, so an address like `@vera` (Vera-Studio) resolves; the only remaining wall, `_check_cross_project_boundary`, returned allow the moment `AIPASS_CALLER_CWD` was empty or sat in no project, before any tier was considered. Measured on 09-02 and again today: caller cwd set to a fleet branch, refused; caller cwd unset, allowed. `delivery.py` 3.4.0: the resolver now tells the check when the external tier answered and no earlier one (`external_tier=`), and an unverifiable sender fails CLOSED there (`_refuse_unverified_external`) with the wall named, not the address ("Out of scope: @vera is a citizen of external root Vera-Studio ... Unverified mail never crosses into an external root (#754) — only @devpulse's verified-admin lane may initiate there. From your own seat you may reply to an existing message from @vera."). The verified-admin grant stays the bridge and still runs last. No reply exemption on the unverifiable path: with no sender project a stamped `reply_path` could name any mailbox on disk, so a crafted reply could launder through any inbox holding a message from `@vera`. Fleet-internal delivery with no caller cwd is byte-identical, so @trigger's in-process sends to owner branches still land. 6 pins, 9 cases, in the existing `test_delivery.py` and `test_dispatch_module.py` through the real @memory gateway: unverified sender to `@vera` refused in both shapes (no cwd, cwd in no project) plus the reply-stamp case, all three red on the old code; same sender to a fleet branch lands; verified admin to `@vera` lands; and the second pin owed in the issue, both dispatch verbs returning the same manager-gate verdict from the admin seat through the real `wake_branch` gate. 9 mutants, 0 survivors. Live probe from the real tree with every caller variable unset: `@vera` refused with the reason above, self-send delivered, the wrapped wall never fired a wrong allow. ai_mail 1,472 green from both rootdirs, ruff clean, audit 100 `--full`.

## [2026-09-10] — release awareness for project managers: a release mail and a manager-only session-start notice, a safe `aipass init update` (manifest, plan-then-apply, keep local edits, backup, retire, doctor scaffold check), `.updateignore` at project and branch roots, the identity injector rendering every passport facet, and the first Windows-only red cured with a Linux oracle (DPLAN-0335 / FPLAN-0530–0532, RPLAN-0005 row 1, merged as PR #761, v2.8.5)

### Added

- **devpulse: `drone @devpulse release-notify v<version> [--dry-run] [--force]` — the release mail to project managers (DPLAN-0335 leg 1; Patrick's July proposal DPLAN-0264 step 1, revived 2026-09-09).** Between 2026-07-28 and v2.8.4 every release shipped with zero fan-out to the projects that run on this install; Vera-Studio carried a 07-27 `hooks.json` through all of them. The command enumerates managers the way the install already declares them — active roots in `AIPASS_ROOTS.json` plus `projects/*`, passports with `citizen_class: manager`, dot-prefixed entries such as `projects/.archive` skipped and named (the first run would have mailed the retired @marketstand) — and sends each one an ai_mail email (no wake; read on their next wake) with the GitHub release link, the CHANGELOG headline of the version-named section (not `[Unreleased]`, which is what has not shipped), and the update ritual: `aipass doctor`, `aipass init update <root> --dry-run`, ask Patrick or devpulse, apply on a go, `aipass doctor` again. One thread in r/announcements. Idempotent per version through `.devpulse/release_notify.json`; a failed recipient is named and does not stop the others; exit 2 on any failure (the branch's `resolve_exit` contract). Measured on this machine: 8 roots, 11 passports, 6 managers (@vera, @wren, @aipass_site, @baud, @earmark, @finch). The merge playbook (`flow/templates/playbook_plans/merge.md` section 7) gains the step after the PyPI verify, so the first live send is the next merge train.
- **hooks: `.aipass/project_hooks.json` was described as a mirror of AIPass's own `.aipass/hooks.json` and had drifted 13 handlers behind it, while still shipping a `auto_watchdog` entry whose handler file had already been renamed to `auto_watchdog(disabled).py` — a dotted path resolving to nothing, in every project stamped since (DPLAN-0335 leg 2, @hooks ruling, devpulse dispatch 2026-09-09).** Each of the 13 was ruled individually rather than bulk-copied, with the per-handler reason recorded in `src/aipass/hooks/README.md` section 'The template ruling' and pointed at from the template's own `_comment`, so the next reader does not re-derive the divergence as a bug. Project-appropriate and now shipped: `temporal`, `context_gauge`, `persistent_alert`, `pre_compact_prep`, `post_compact_regrounding`, `registry_gate` (measured 2026-09-09: all four projects under `projects/` and Vera-Studio carry a `*_REGISTRY.json`, so without it a project's sealed registry is an ordinary editable file), and `feedback_pulse` shipped `enabled: false` because its own docstring scopes it to external user projects. Framework-only and deliberately absent: `presence_gate` and `presence_release` (the fleet seat rule; `presence_gate.handle_stop` is additionally a documented no-op and is flagged as a retire candidate in the framework file too), `auto_process` (@memory and its optional `numpy`/`chromadb`/`fastembed` extra), `compass_recall` (@devpulse's compass FTS, which a project has no copy of), `user_message_relay` and `telegram_response` (the Telegram extra and per-branch chat registration). `auto_watchdog` dropped. Template 18 → 25 handler entries. The generic cure for the class of bug is pinned: a live-config test imports every handler the template names and asserts the function exists, which no fixture-reading test could have caught.
- **hooks: a project manager had no way to learn that the installed AIPass had moved past the AIPass that wrote their scaffold (DPLAN-0335 leg 2, `release_notice`).** `apps/modules/release_notice.py` (the deciding) under `apps/handlers/lifecycle/release_notice.py` (SessionStart wiring) reads two files and writes none: the nearest `.trinity/passport.json` and the project root's `.aipass/scaffold_manifest.json` (@aipass's leg-3 contract — `aipass_version`, `stamped_at`, `files` — verified end to end against their actual writer, not a fixture). When the scaffold is behind it prints installed version, stamped version and date, the `aipass init update <root> --dry-run` preview, and the rule that applying needs Patrick's or devpulse's go; it never runs the update. Silent for a non-manager passport, no passport, a cwd outside any `*_REGISTRY.json` root, the AIPass source repo itself (@devpulse's passport says `manager` and `init update` refuses its own repo, so the notice there could never be cleared), and a current scaffold. An absent or unparseable manifest counts as behind; an unparseable *installed* version stays quiet, because an AIPass defect must not become every manager's every-wake nag. Versions compare as zero-padded integer tuples rather than through `packaging.version`, which is not in the declared dependencies — without the padding a scaffold stamped `2.8` would read as behind `2.8.0` forever. Two doors, one code path: SessionStart (`startup`/`clear`; `resume` and `compact` skipped) and the post-compact regroup, where the block is appended after the grounding sections and is not even built when there is nothing to reground. Measured 1.18 ms for a manager on the full path, 0.29 ms for a non-manager. Proven by hand through the engine's own door from four seats; eleven mutations red; Vera-Studio verified untouched by an mtime sweep. NOTE: SessionStart is wired per handler in provider settings, so the live SessionStart door needs one `claude.py SessionStart:release_notice` entry from a trusted editor; the post-compact door rides the PostToolUse fan-out and needs none.
- **aipass: `aipass init update` overwrote every managed file whose content differed from the template, which cannot tell "the template moved on" from "the project edited this file" — and `--dry-run` previewed only the git-auth half, so there was no way to find out first (DPLAN-0335 leg 3, FPLAN-0530).** The live case: Vera replaced Vera-Studio's `tier1_navmap.md` with the studio's own map on 09-09 (DPLAN-0334), and an update that morning would have silently put AIPass's roster map back. Every project now carries `.aipass/scaffold_manifest.json` — `aipass_version`, `stamped_at`, `files` as rel path → sha256 of the bytes written — stamped by `init run`, `adopt` and `init update`; it is the contract @hooks' `release_notice` reads, and the schema was fixed before either side built. The conffile rule, named after dpkg's: a managed file is overwritten only when its current hash still equals the recorded one (nobody has touched it since AIPass wrote it) or it is absent; otherwise your copy stands, the plan says `kept-local`, and the template is written beside it as `<name>.aipass-new` to diff. Root `CLAUDE.md` and `AGENTS.md` became seeds — created once, never rewritten, because they exist to be filled in — while `tier0_kernel.md`, `tier1_navmap.md` and `prep.md` stay managed. `update_project(target, apply=False)` computes the whole plan with zero filesystem writes (no `mkdir`, no stamp, no trust enrolment: every decision is a read, and the single write loop sits below one `if apply`), so `--dry-run` is a real preview — exit 0 current, exit 2 pending, `--json` for machines, and the same plan block prints on apply so what a manager pasted for a go and what actually ran read as the same thing. Applying backs up every overwritten file into `.aipass/.backup/scaffold_<stamp>/` mirroring the project tree, and retires `_STALE_MANAGED_FILES` by renaming them `<name>(disabled)` instead of `unlink` (Patrick, DPLAN-0264: visibility beats tidiness). `RETIRED_HOOK_HANDLERS` prunes `auto_watchdog` out of a project's `hooks.json` and reports it — the union merge could only ever grow a project, so a handler dropped from the template had never once been dropped from a project. `aipass doctor` gains a **Scaffold** group: manifest present or absent, stamped vs installed version, tier0 hash against `AIPASS_HOME`, handler keys missing vs the template, retired handlers present, and the one command to run next; it is read-only including under `--fix`, because applying a scaffold update can replace files a manager wrote and that is a decision, not a repair. One design change against the DPLAN, and it matters: the plan says a backfilled manifest "records what is on disk", which would have made a `kept (unknown provenance)` file read as `unmodified since AIPass wrote it` on the NEXT run and overwrite it — the exact loss the rule exists to prevent — so the manifest records what AIPass wrote, never what a kept file currently holds, and a kept file with no prior record gets no entry at all. Measured against Vera-Studio: the plan reports both tier files `kept`, `hooks.json` +9 handlers −`auto_watchdog`, stamp `unstamped → 2.8.4`, exit 2, with an mtime+size sweep of all 28,186 entries in the tree byte-identical before and after (md5 `88abfda6…` both times). Nothing was applied to any project — apply is Patrick's go. Also corrected in passing: `init --help` had described `update --dry-run` as previewing "the auth repairs only", which is no longer true.
- **aipass: a project had no way to tell an update "this file is mine" before the fact (Patrick, 2026-09-09 00:41, DPLAN-0335 leg 3 addendum).** `.updateignore` at the project root, same fashion as `.gitignore` and `.backupignore`: one pattern per line, `#` comments, blank lines ignored, `fnmatch` against the path relative to the project root, a trailing slash meaning a directory and everything under it, and a pattern with no slash also matching a bare filename at any depth so the documented `tier1_navmap.md` actually reaches `.aipass/tier1_navmap.md`. Negation is not in v1. A matched file is never written, never backed up, never given a `.aipass-new`; the plan reports `skipped (.updateignore)` and doctor counts it as owner-protected instead of as drift. It outranks the seed rule and the hash rule both. The file is owner-owned — `init` and `update` never create or modify it. One deviation from the dispatch, for the same reason as the manifest change above: the brief said the manifest should still record an ignored file's on-disk hash "so a later un-ignore behaves like backfill", but recording it produces the opposite — on the next run the file would read as unmodified since AIPass wrote it and be overwritten. Nothing is recorded for a protected file, which is what actually gives un-ignore the backfill path. Proven on a copy of Vera-Studio's scaffold under `/tmp` (never the live tree): `.aipass/tier1_navmap.md` moves from `kept (local edits)` to `skipped (.updateignore)`, and doctor's Scaffold group reports `1 file(s) owner-protected`.
- **spawn: `drone @spawn update` had no way for a citizen to say "this file is mine", so a preview that proposed merging template boilerplate into a live passport could only be answered by not applying the update at all (Patrick, 2026-09-09 00:41; DPLAN-0335 follow-up, FPLAN-0531).** `.updateignore` at a BRANCH root, beside `.trinity/` — the second door on the contract `aipass init update` landed at project roots in 6ecd5acb, deliberately one name so an owner learns the syntax once: one pattern per line, `#` comments, blank lines ignored, `fnmatch` against the path relative to the branch root, a trailing slash meaning a directory and everything under it, and a pattern with no slash also matching a bare filename at any depth. No negation in v1. A matched path is checked FIRST in both template walks — before the create-only set and before the passport heal — because an owner-protected file is a decision already made and nothing downstream is entitled to reconsider it; it is never written, never merged and never backed up, and the preview reports it as `skipped (.updateignore)` on its own line rather than as a warning. Spawn never creates or modifies the file, and its absence protects nothing, so every branch on this machine is unchanged until its owner writes one. The parser is spawn's own copy rather than an import: branches never import each other's handlers, the contract is small and frozen, and both copies are pinned. Measured on a real branch scaffold copied to `/tmp` (never a live branch, proved by an mtime+size sweep of all 39,360 paths under `src/aipass/` and Vera-Studio — the only entries that moved were operation logs, zero Vera-Studio paths): a passport missing an allowlisted field moves from `updates=2` with the passport proposed for merge, to `owner_protected=1` with the passport skipped and the rest of the update proceeding unchanged; on `--apply` the file is byte-identical afterwards and no `.recovery` copy exists, where the same apply without the ignore file rewrites it and leaves a backup. A directory pattern protects everything beneath it at any depth. Twelve pins; eleven mutations red, and two of them found real holes before landing — the comments pin passed for the wrong reason (a `#` is a literal to `fnmatch`, so a comment kept as a pattern can never match a filename and the defect was invisible one layer down; it now asserts the parsed pattern list), and the bare-filename-at-any-depth clause had no pin at all. One mutation is declared EQUIVALENT with the measurement rather than chased: removing the `"/" not in pattern` guard changes nothing over a 117-pair matrix, because a basename never contains a slash — the guard is a documented short-circuit, not a behavioural gate, and the same line stands in @aipass's copy.
- **hooks: the identity injector dropped `identity.personality` and `identity.anti_traits`, so a passport that carried them was rendering an incomplete citizen every turn (RPLAN-0005 row 1, devpulse S430).** `_format_identity` read name, path, email, role, traits, purpose, the first 4 `what_i_do`, the first 3 `what_i_dont_do` and principles, and never looked at either key. Now a dict `personality` emits one `Facet: text` line per facet in the passport's insertion order (placed after Purpose, before Do/Don't — the facets are written as a progression and sorting them would rewrite the author's argument), and a non-empty list `anti_traits` emits a `Never: a | b | c` line straight after the `Don't` line, because `Don't` names tasks that belong to another citizen while `Never` names ways of being the citizen rejects. Absent keys emit nothing, so the fleet renders byte-identically: measured across 173 passports on this machine, 12 carry either key and exactly ONE is a live citizen (Vera) — devpulse's brief said only Vera's, which is right for live citizens; the other 11 are archives and backups under Vera-Studio, and one of them carries `anti_traits` with a null `personality`, which is why both keys are guarded independently rather than as a pair. Vera's render 1817 → 3366 chars, 9 → 16 lines, against a 4,000-char budget: not a platform limit but a per-turn tax, since this block is injected on every turn. A facet over `FACET_CHAR_BUDGET` is cut at the last sentence boundary rather than dropped, so every facet stays present and every kept word stays true. Six mutations red; two of them found real defects in this change before it landed — the hard-cut path appended its ellipsis on top of the limit instead of out of it (321 chars against a 320 budget), and the wrong-shape test could not tell a correctly-skipped string `personality` from one that CRASHED the renderer to empty, since a `str` has no `.items()` and the handler swallows the error. Both cured, then re-killed.

### Fixed
- **aipass: every managed file AIPass writes now lands with LF bytes on every OS, because the scaffold manifest hashes bytes on disk while the plan hashes the template string, and the two can only ever agree if what lands on disk IS the string (PR #761 windows-setup red on 6ecd5acb, FPLAN-0532).** `Path.write_text` defaults to `newline=None`, which translates every `\n` to `\r\n` on Windows, so a project AIPass had just written reported `.claude/commands/prep.md` as needing an update on the first `init update` and — worse than CI showed — as `kept-local` with a spurious `.aipass-new` sidecar on the second, for a file nobody had touched. Why prep.md and not the tier files, which devpulse left to me: prep.md is GENERATED from a string and written, while `tier0_kernel.md`/`tier1_navmap.md` were `shutil.copy2`'d byte-for-byte from an AIPASS_HOME the Windows runner checks out with LF, and `settings.json`/`hooks.json` are merge files compared as parsed JSON, which no newline can touch. So it is a rule, not a site: one writer, `scaffold_manifest.write_text_lf`, at all 29 scaffold write sites across `bootstrap.py` (14), `new_project/__init__.py` (12) and `adopt.py` (3), and the three `copy2` calls for text templates became read-then-write so a CRLF checkout of AIPASS_HOME cannot hand a project bytes no comparison can match either. It also makes the `.aipass-new` sidecar and the backup copy byte-comparable across a team that is not all on one platform, and it reaches doctor's Scaffold group, which compares tier0 against AIPASS_HOME the same way. Same shape as the cp1252 class RPLAN-0004 gated with PLW1514 — the platform default silently changes bytes and str-vs-bytes reasoning diverges from there — but there is no ruff rule for the newline sibling, so devpulse has taken the class to @seedgo as a standard. Pinned the platform_oracle way (FPLAN-0529): a fixture makes this Linux process translate newlines the way Windows does, faithful in the one way that matters — it translates only when the caller left `newline` unset, which is exactly the condition the cure removes. Both pins red before the cure (naming `prep.md` as CI did, plus the two tier files CI could not show), green after, `scaffold_manifest.py` restored byte-for-byte by md5 between the two runs. Also stamped: `aipass new` was the fourth project-minting door and the only one not writing a manifest, so a project born there would have met its first update as unknown provenance and collected sidecars for files nobody edited.
- **aipass: a kept-local file forced `exit 2` on every later preview forever, even once its `.aipass-new` sidecar already matched the template and nothing would be written (found by devpulse in the live Vera-Studio apply, 17:36).** The plan labelled the file `kept-local` and queued the sidecar write unconditionally, so Vera-Studio previewed "2 of 8 would change, exit 2" permanently — a signal that can only be cleared by resolving files the owner may intend to keep indefinitely, which teaches people to stop reading it. Each plan entry now carries `writes`, the honest answer to "would this run touch the file?", which the verdict alone cannot give; the counts, the summary line and the exit code all read that one key, so they can never disagree. Vera-Studio now previews `0 of 8 file(s) would change`, exit 0, with both files still reported kept. The dead `PENDING_ACTIONS` constant went with it — it encoded the wrong rule (that `kept-local` is always pending) and was never read.
- **aipass: `aipass doctor` reported a kept file as a bare `tier0_kernel.md differs from AIPASS_HOME`, which reads as a fault the manager cannot clear (devpulse, same run).** It now distinguishes `kept (local edits)` from `kept (unknown provenance)` using the manifest, and names both resolutions instead of neither: delete your copy to take the template, or add it to `.updateignore` to keep it for good. `template moved on` is reserved for the case where the hash still matches what AIPass wrote.

- **hooks: two `host_state` rows mutated the process environment and did not put it back (@seedgo FPLAN-0525, 2 of the fleet's 3 rows).** `test_edit_gate_bash.py::test_the_stamp_does_not_outlive_the_check` used `os.environ.pop` and `test_hook_test.py::test_unset_stays_unset` assigned into `os.environ` directly; the interpreter environment is process-wide, so both outlived their test and neither was restored on the failing path — the run where you least want the environment silently rearranged. Both now arrange through `monkeypatch`, which restores on every path. Proved with a subprocess probe reading both names before and after the two files: NO LEAK, 87 green.

## [2026-09-08] — no stragglers: every v5 pytest_quality row to 100 fleet-wide, then red-to-rule: the first fully green three-OS matrix (FPLAN-0508 / FPLAN-0529, DPLAN-0323 phase 7.5, merged as PR #759, v2.8.4)

Fleet re-audit 2026-09-08 03:52, uncached, one branch at a time: 17 branches read 100 on every score-bearing v5 rule; api reads 99 on one `unentered_assert` row ruled a judged false positive and forwarded to seedgo. Ten owner waves, every landing verified from devpulse's seat and committed path-scoped; nothing deleted, removals archived with reason headers; six pack notes to seedgo. The canary trial (DPLAN-0323 phase 8) is unblocked and waits on Patrick's go.

### Fixed

- **daemon: `run.py` was 690 lines against the 650 cap and did its own `mkdir`, the one row that kept PR #759's seedgo-audit job red after every test leg went green (row 13, daemon owning, dispatched 2026-09-08 20:35).** Two handlers left the module, each written and run standalone before a single import in `run.py` changed, because the systemd timer runs that file live every two minutes: `handlers/schedule/catch_up_lane.py` (detect_and_queue, drain_one and the OUTCOME vocabulary; fires nothing itself, `fire` and `log` arrive as callables so the dependency arrow keeps pointing one way) and `handlers/schedule/tick_lock.py` (the lock directory, the lock file and fcntl, the only thing in the tick lane that touches the filesystem; line 640's `mkdir` is `tick_lock.prepare()` now). Deliberately not moved: `LOCK_FILE` stays owned by `run.py` and is passed in, and the OUTCOME constants are re-exported, not redefined, so the seam `test_run_blocked_contract.py` patches is still the path that gets opened. `run.py` 690 → 585 lines, zero direct file operations, audit 100 uncached. Verified from both seats: 598 green from the repo root and the branch directory, ruff check and format clean, the timer ticked four times on the split code (20:38 through 20:44, all Finished, `schedule.lock` touched by the new acquire path), run.log silent, Vera's runstate byte-identical across all eight fields.
- **Fleet: the eleven test rows that went red on PR #759's first completed matrix, cured against the rules that now name them (devpulse landing a sonnet sub-agent's cures on Patrick's go, 2026-09-08 15:58; rules first under FPLAN-0529, then this).** Every cure is test-only, in an existing file, and the forbidden shapes were named in the brief: no skip, no xfail, no platform branch, no both-worlds `exists()` branch, no widened assertion. By class: ai_mail row 1 and daemon row 2 (machine as oracle) now build their world under `tmp_path` (a four-resident fleet through the file's own `_project()` helper; a fully populated branch through `_setup_full_branch`) instead of reading the real `projects/` tree and the real `.trinity/`, both renamed to say so and both proven in a tracked-only `git archive` checkout where the old tests failed; prax row 5 compares `Path` to `Path`; trigger row 6 and its twin in `test_log_watcher.py` (same shape, never reported by CI because seedgo's REPR-HAYSTACK arm found it, not the runner) assert on `call_args` values instead of searching a rendered mock call whose repr doubles the separator; skills row 7 compares a set of names, since `sorted()` over Paths case-folds on Windows; hooks row 8 injects the write failure at the seam the function calls (`append_jsonl` raising `OSError`) instead of a POSIX device path Windows opens happily; drone row 9 asserts the wrapper's own message, not `.filename`, which Windows leaves `None`; spawn row 10 resolves both sides once (the 8.3 `RUNNER~1` short name) and replaces the `files_copied == 49` magic integer with a count measured from the template through the copier's own `SKIP_NAMES` rule (still 49, now derived); prax rows 11 and 12 plant `DASHBOARD.local.json` in `tmp_path` so `_handle_refresh`'s ancestor walk stops in the sandbox instead of climbing into the runner's profile where a home `.aipass` lives (class G, named by seedgo from the code; the marker the runner actually held is still a Windows probe). Verified from the devpulse seat before landing: each cure checked against seedgo's new arms with the flagged unit gone, `Platform_Oracle` 100 on all eight branches, the eight branch suites and the full suite green from the repo root, ruff check and format clean on all ten files. Not cured here by design: daemon's `run.py` split (row 13, the audit gate, daemon's live module), and seedgo's four other true findings from the fleet measurement (daemon's vacuous absence pin, memory's `.archive` half, prax's redirect guard, spawn's published false positive), which go to owners in the RPLAN-0004 round. Windows rows are reasoned cures verified by the checker and the Linux run; the CI Windows job is the verdict.

- **daemon: the test suite uninstalled the live scheduler timer and reported green (FPLAN-0524 / FPLAN-0526, daemon owning; Patrick's ruling 2026-09-08).** The unknown-argument pins in `test_cli_routing.py` drive the real router over every gated verb, two of which are `install-timer` and `uninstall-timer`; whenever the gate was absent (the red-first runs and the mutation runs that disable it) `_install()` and `_uninstall()` executed against the user's systemd. The journal shows seven Started/Stopped pairs across four runs on 2026-09-07 11:28–11:46, the last event a Stop; nothing ticked for twenty-three hours, `@vera/release-watch` and `@daemon/inbox-sweep` missed their 09-08 windows, and no MISSED line could be written because writing one needs a tick. The ruling, his words: tests can't disable processes, they restore to the exact same state before the test; the test is fine and good that it can enter something. Cure: a session-wide autouse seal in `tests/conftest.py` on `timer_install`'s three seams (`_run_systemctl`, `_UNIT_DIR`, `_STATE_DIR`), so no daemon test can reach systemd whether the gate is present, absent or mutated away; a session sentinel that snapshots the live timer at start and fails the run that changed it (deliberately non-restoring, so the defect is reported, not hidden); an opt-in `timer_host_state` snapshot/restore fixture, idempotent, asserting the restore matched, for the next test that must touch the real verb; and the two timer rows proved sealed in the exact gate-absent world that did the damage. Timer reinstalled 10:46, ticking again. Four mutations red; 596 green from both rootdirs with the timer enabled and active before and after and zero journal lines. The standard follows as seedgo's `host_state` pack rule (FPLAN-0525).
- **devpulse: `compass query "opt-in"` died in FTS5's parser and the router called it an unknown command.** `query_decisions` handed the raw text to MATCH, so a hyphen became column-filter syntax (`sqlite3.OperationalError: no such column: in`); `route_command` caught the exception, logged it, and fell through to `Unknown command: compass / Did you mean: compass?`, exit 1. The query is now defused the way recall and `find_conflicts` already were (word tokens as quoted literals), joined by FTS5's implicit AND so every word still has to match; a query with no word token is refused by name, exit 2. A module that raises is now reported as that module's failure, named with the exception, handled, exit 2. Two mutations red (raw MATCH restored; the fall-through restored), 571 green from the repo root.
- **api: seven refusals exited 0 — `caller-usage`, `track`, `get-key`, `validate`, `get-secret`, `models` with nothing configured, and `host-api revoke-token <unknown id>` (FPLAN-0492, the fleet refusal sweep; the item stood since 08-13 and was re-measured six-for-six on 08-28).** `main()` clears cli's process-level failure flag before routing and returns `resolve_exit(handled)`: 1 unrecognised, 2 recognised-and-refused, 0 only when nothing printed an error. All 63 `error()` sites were read first for one that prints a failure on a still-successful path; there were none. `revoke-token` on an unknown id was the branch's one warning-channel refusal and names the id through `error()` now. Measured from the shell before and after; five mutations red; seven pins added to `test_host_attach.py` (1589 cases).
- **backup: `settings` printed "not implemented" as a yellow warning and exited 0, indistinguishable from a settings UI that opened and closed, and every routed command returned a bare 0 whatever it printed (FPLAN-0492, the fleet refusal sweep, row settings.py 63).** `settings` raises `NotImplementedError` carrying the reason and the workaround; `route_command`'s existing handler names the module and `main()` exits 1, measured from the shell before and after by driving the real `main()`. The fleet seam landed beside it: `reset_command_state()` on entry and `resolve_exit(True)` on both routed-success paths, so a handled command that called `error()` exits 2. The standalone entry catches the raise and exits 1 rather than tracebacking.
- **prax: `dashboard refresh` on a partial failure printed a warning and exited 0, and every routed command returned a bare 0 whatever it printed (FPLAN-0492, the fleet refusal sweep, row dashboard.py 240).** `main()` clears cli's failure flag before routing and returns `resolve_exit(True)` on a routed command; the partial-refresh headline goes through `error()`. `dashboard refresh @nosuchbranch` exits 2 now, `status` stays 0, an unknown flag stays 1, measured from the shell. The test that pinned the row (`test_refresh_all_partial`) asserted nothing and now pins the `error()` call and that `warning()` was not called. The `profile_write_failed` colour key trigger asked for is added to `unified_stream.COLORS` with a caveat beside it: nothing reads that table today, so the key is inert and could not be mutation-checked; wiring or deleting `COLORS` is routed to prax as its own piece of work.
- **spawn: `migrate-passports` against a root with no discoverable passports exited 0, so "I searched the wrong root" was indistinguishable from "your fleet is already 2.0" to anything reading the exit code, and a routed command that called `error()` and returned 0 still exited 0 (FPLAN-0518, the fleet refusal sweep).** The zero-scan notice goes through `error()` with a suggestion and exits 1 (measured from the shell before and after; the healthy live dry-run still exits 0). `main()` clears cli's failure flag on entry and every one of the nine routed commands returns through `_resolved()`, which passes a non-zero code untouched and re-asks `resolve_exit` on a 0, so a command that reported a failure exits 2. README carries the code table. The test that pinned the 0 was rewritten in place with the reason in its body.
- **spawn template: every newborn was stamped with a permanent self-skip** (`templates/citizen/tests/test_scaffold.py`, `test_conftest_fixtures_available` — a bare `pytest.skip` in an `except FixtureLookupError` arm), so a branch that grew its own conftest ran the stamp as a silent pass. Judged on a throwaway minted outside the repo: `self_skip` 1 row before, 0 after, every other score-bearing rule 0 both times, the repo `AIPASS_REGISTRY.json` md5 unchanged by both mints. The stamp now asserts both worlds: fixtures present hand back the values the template conftest declares; fixtures absent means the replacement is total, because a conftest offering one half of the pair is a half-edited scaffold. Proved present GREEN, half-scaffold RED, total-replacement GREEN, conftest-deleted RED. No live branch carries a copy of the file (measured: zero `test_scaffold.py` under `src/aipass/*/tests/`), so the cure needs no fleet write.
- **trigger: `log_events start` declined by design and exited 0, so `log_events start && <next>` ran `<next>` with nothing watching (canary's fleet sweep 2026-09-07; FPLAN-0522).** The refusal goes through cli's `error()` and names the reason (withdrawn by ruling, not failed: `system_logs` has one owner, with the `branch_log_events status` suggestion); `main()` clears the failure flag on entry and returns `resolve_exit(True)` on a routed command. Exit 0 before, 2 after, measured from the shell; a clean routed command stays 0, an unknown command stays 1. The two tests that pinned the old channel (one asserted `error` was NOT called) were rewritten in place. Ruled by devpulse over trigger's own 2026-08-14 reading, following daemon's identical call.
- **memory: seven more refusals exited 0 — `fleet`, `governance`, `health` and `roots` with an unknown subcommand, `roots add` on a not-ok report, `templates push-templates` / `diff-templates` (the retired verbs), and `lint` on an empty registry (FPLAN-0521, the fleet refusal sweep).** Each goes through cli's `error()` now and exits 2 through the seam memory wired on 2026-09-07; measured from the shell through the real drone binary before and after, with the bare `governance` and `health` introspections as the control that stays 0. The `roots` advisory on a successful restore ("declarations NOT restored, re-add them yourself") was checked and correctly stays a warning. Six mutations (each swap reverted by line number) red, the `test_lint` patch target corrected to the name the module actually binds (`_read_registry`, imported from the monitor detector, not `_load_branches`).
- **cli: the branch that owns the exit seam never called it, and a Ctrl-C exited 0 (FPLAN-0523, the fleet refusal sweep; canary's row cli.py 318).** `main()` now runs the three-line shape every other branch wired tonight: `reset_command_state()` on entry, refuse through `error()` when not routed, `return resolve_exit(handled)`. Codes measured from the shell: routed clean 0, routed with a refusal 2, unknown verb 1 (unchanged: `resolve_exit` checks handled before the flag, so a caller's own 1 is never upgraded), cancellation 0 → 130. The `KeyboardInterrupt` handler moved out of the `if __name__` block into `run_cli()`, which returns the code, because where it sat nothing could test it, which is exactly why it exited 0 for months. Six seam mutations, each isolating its unit; the documented codes are pinned in `test_cli_routing` under a header naming them the fleet contract.

### Added

- **seedgo: CI red becomes standard first, two new `pytest_quality` rules and three `posix_literal` arms from PR #759's first completed matrix (FPLAN-0529, seedgo owning; Patrick's ruling 2026-09-08 13:47: red is never just fixed, the class becomes a rule, then owners cure against it).** The 13 reds (2 Linux, 11 Windows, 1 audit gate) were pinned to six classes in a dossier before anyone touched a row; every class is now caught on the author's machine. `fresh_clone` (fourteenth rule, scoring) asks whether the expected value comes from content the machine has and a clone does not: IGNORED_PATH (a read of a root-gitignored segment outside a sandbox), BOTH_WORLDS (a runtime `is_dir`/`exists` branch with assertions in both arms, two oracles proving neither), DERIVED_EXPECTED (the expected value computed by the production under test off a bare machine root); 41 rows on the first run narrowed to 6 through four measured acquittals. `platform_oracle` (scoring) asks whether the pass is a fact about the code or about the host: LISTING_ORDER (an ordered equality over `iterdir`/`glob`/`listdir` output, `sorted()` over Paths case-folds on Windows) and MODE_INJECTOR (`chmod`, `0o444`, a POSIX device path used to provoke the OSError the test asserts; Windows ignores every mode bit) score, while OSERROR_ATTRIBUTE (`filename`/`errno`/`winerror` of a host-raised exception), UNRESOLVED_TMP_PATH (one side resolved, one not, the 8.3 short-name class) and SHALLOW_SANDBOX (cwd sealed, its ancestors not) nominate only because the same shapes are written correctly across the fleet; 2,832 first-run nominations narrowed to 83 by requiring positive evidence, at a cost of zero true rows. `posix_literal` gains RENDERED-PATH (the test renders a Path and compares it to a slash literal, scoring), REPR-HAYSTACK (a path searched inside a rendered mock call where repr doubles the separator, scoring) and RETURNED-PATH (nominate only, since whether the producer normalised is off-screen for a static reader). `self_skip.md` gains the cure paragraph both Linux rows needed: build the world, never assert both of them. Class G was named from the code with its unproven half stated: the `Path.cwd` patch took, the production ancestor walk left the sandbox, and only on Windows does the temp dir sit under the user profile where a home `.aipass` exists; which marker the runner held is a Windows probe for RPLAN-0004. All twelve test rows flagged by nodeid at 15:55 before any cure. Seedgo's own two rows cured at the producer (`architecture_check.py` rendered a template entry with `str()`, now `as_posix`, pinned through `PureWindowsPath` so the pin never asks the platform). One defect in the new checker caught by its own pins (a shared name walker collapsed `stat.S_IREAD` to `stat`, so the dotted spelling the rule text prints scored clean). Runnable templates for both rules. 326 pins in the pack file (83 new, 83 mutations red one at a time, checkers sha-verified restored), 3979 green both rootdirs, `audit aipass` and `audit pytest_quality` seedgo 100 with fourteen rules listed. Fleet at 16:09: `fresh_clone` 4 scored rows (daemon, memory, prax, spawn), `platform_oracle` 0 scored and 85 nominations, `posix_literal` 1 scored (trigger) and 70 nominations, 34 of them seedgo's own corpus-rendering family. Also in seedgo's dropbox: the dossier `ci_red_2026-09-08_defect_classes.md`, and RPLAN-0004 in the branch root, where seedgo takes over cross-OS and CI health as its standing lane. **Its own landing's Windows red, cured the same evening:** the first completed Windows run carrying the landing showed seedgo's two rows gone and one new red, the suite pin that runs every teaching template, because `templates/platform_oracle_test.py` proved its WRONG shapes by asking the host for one half of the divergence, inside the file that teaches the species for that mistake (the device-path injector proof assumed `/dev/null/impossible` is ENOTDIR, which Windows creates happily; the sealed-cwd proof assumed a `/tmp`-shaped host; the two-spellings fixture symlinked `RUNNER~1` to a long directory and got `WinError 183`, because Windows had already minted `RUNNER~1` as that directory's 8.3 name). Now both halves are manufactured (a strict writer that refuses a null segment by spelling, a forgiving no-op writer; a `WALK_CEILING` the proof sets to `tmp_path`; a dot-dot route for the second spelling, no symlink, no privilege, nothing the 8.3 generator can collide with), reproduced on Linux against a Windows-shaped world by a throwaway probe in `tools/`. Measured on the way: auditing the templates with the pack would not have caught it (six rules at 100 over the copied templates, the defect lived in helpers and a fixture the rules say they do not follow); the suite pin that runs every template is what the Windows leg used, and that order of proof is written into `platform_oracle.md`. The template runs 18 green, 3979 green both rootdirs, both audits 100.

- **seedgo: `host_state`, the twelfth `pytest_quality` rule, scoring from the first run (FPLAN-0525, seedgo owning; Patrick's ruling 2026-09-08).** A test may touch the real thing, but a test that reaches live host state and does not put it back is a finding: five ordinary arms (service control through `subprocess` argv beginning `systemctl`/`launchctl`/`sc`/`service`/`crontab`/`pkill` and kin, process signals, writes under `Path.home()`, `os.environ` mutation, `os.chdir`) plus a sixth derived from production, not from a list: a module under `apps/` that publishes a command set and reaches host control makes its verbs host-effectful, and a test that puts one of those verbs into an argv and calls the entry point with nothing patched is flagged, which is how `install-timer` / `uninstall-timer` were named by the module that made them dangerous. Acquittals: the seam patched anywhere in the unit's with-stack (a patch target held in a module constant resolves one hop), `monkeypatch.setenv`/`chdir`, `tmp_path`-rooted names, a yield-and-restore fixture. Stated limits in the rule text: a helper or a fixture in another file is not followed, a runtime-built argv is not read, a SIGKILL skips every teardown, so the template writes the snapshot under `tmp_path` and restores idempotently. `templates/host_state_test.py` teaches the pattern on a subject modelled on `systemctl disable`, where the restoring start is a silent no-op unless the fixture reads the state back; the fleet conftest template gains an opt-in `host_state_snapshot`. Measured against daemon at HEAD before its cure: 4 rows, 99; fleet after: 3 rows (hooks 2, skills 1), mailed to their owners; 38 rows on the first run narrowed to 3 through four measured false positives. Three defects in the checker itself caught by its own pins before landing (the finally acquittal convicted the cure it teaches; fixture rows divided by a unit count scored a clean file −100; a dead splice). 31 pins, 31 mutations, 3895 green from both rootdirs.

- **daemon: temporal-aware schedule recovery, built and gated OFF (DPLAN-0332 / FPLAN-0527, daemon owning; Patrick's design 2026-09-08 after Vera's missed 08:00).** `RECOVERY_LANE_LIVE = False` in `apps/handlers/schedule/runstate.py`: every piece below is inert until the controlled live proof Patrick watches, and the flip is his and devpulse's, not the owner's. What is built: gap detection (`last_tick` stamped in a `finally`; a gap is more than 30 min of no ticks; the cause is read from the host, psutil then `/proc/stat` btime then refused by name as `BootTimeUnavailable`, never guessed; three values: `scheduler_stopped` when the boot precedes the gap, `scheduler_stopped_then_rebooted` when it falls inside, `unknown`; an absent `last_tick` is not a gap and no substitute timestamp may stand in); missed-window enumeration for daily, rotation and hourly with both edges inside the gap (a window still open at gap end fires normally; hourly spells its target as an int minute, and reading it as HH:MM is how hourly silently owed no catch-up); one queue entry per owner/job merged idempotently, superseded by the on-time wake, which then carries the missed list; a drain with one in flight fleet-wide, released by completion through ai_mail's `outstanding_dispatches` door with 60 min as the ceiling, an unreadable register answering AWAKE, three refusals parking at the tail; SCHEDULED and CATCH-UP wake headers with a "do not replay each one" instruction, prepended to the prompt and filed atomically to the target's `.daemon/last_wake_prompt.txt` and to daemon_json; `catch_up` default ON for daily/rotation/hourly with `catch_up: false` to opt out and `catch_up_max_age_hours` unlimited by default; `queue` gains a Catch-up Queue table and an additive JSON key. MANUAL header parked. Also fixed on the way: a suite run had wiped the live runstate (a test patched load but not save), now sealed, and the runstate sentinel compares job keys against discovery instead of bytes, because a real timer tick lands inside the 30 s suite. The lane fired Vera twice out of window while half-built in the working tree (11:31, 12:04), the second with a false last-run sentence; the working tree is production while the timer is installed, and that is now a compass entry. 64 pins with 25 mutants red wait at `docs.local/pending/test_recovery.py.pending` for the test-write door, held rather than folded into an existing file. 598 green both rootdirs, verified from the devpulse seat with the timer and Vera's runstate row snapshotted before and after. `**/.daemon/last_wake_prompt.txt` gitignored.

### Changed

- **Lint: `PLW1514` unspecified-encoding is now a gate, the first ruff family adopted under RPLAN-0004 (seedgo's decision D1, measured; devpulse landing a sonnet sub-agent's fix, 2026-09-08).** Every text-mode `open`, `Path.open`, `read_text`, `write_text` and `NamedTemporaryFile(mode="w")` now passes `encoding="utf-8"`: 39 sites in 16 files across ai_mail, aipass, drone, hooks, memory, prax, skills and spawn, before 39, after 0, each hunk reviewed as exactly that one argument. This is the cp1252 class (FPLAN-0239's Windows red) caught at the desk instead of on the runner. Seedgo's measurement that shaped it: the runtime form (`-X warn_default_encoding -W error::EncodingWarning`) was rejected, since it names 1022 sites fleet-wide and would fail all eighteen suites on day one, so the static rule lands and the runtime count becomes a reported baseline gated on no new site. The rule is preview-gated in ruff 0.16, so `[tool.ruff.lint]` gains `preview = true` and `extend-select = ["PLW1514"]` beside the pinned default families; preview mode surfaced two findings the stable gate had missed, both settled: memory's `tests/test_auto_process.py` imported `importlib` twice (removed), and ai_mail's package `__all__` names `FEED_PATH`, which ruff's preview F822 flags in `__init__.py` files even though the name resolves through the module's PEP 562 `__getattr__` (the star import works, the lazy door is pinned by `test_public_surface.py`, and ruff's own rule text documents this blind spot), so that line carries a `noqa` with the reason rather than an eager import that would pull the logging stack in. `ruff check --statistics src/ tests/` reports zero violations of any rule fleet-wide with preview on; every touched branch's suite green. Next family, one per landing: the three path rules that map to PR #759's classes B, C and D (`PTH101`, `PTH206`, `PTH208`, 15 sites).

- **CI: a running matrix run is never cancelled by the next push (devpulse; RPLAN-0004 finding 2.5, 2026-09-08).** `ci.yml`, `windows-test.yml` and `macos-test.yml` had `concurrency.cancel-in-progress: true` keyed on the ref. Eight landings pushed within hours on 2026-09-07/08 cancelled every in-flight run, so no wave got a Windows or fresh-clone verdict; the first run that completed showed 13 reds with no wave to attribute them to (all now pinned to six defect classes in seedgo's dropbox and being turned into `pytest_quality` rules under FPLAN-0529 before any row is fixed). Now `cancel-in-progress: false`: one run per ref at a time, a new push queues behind the running one, GitHub keeps at most one pending run per group, and a verdict that starts always finishes. Runner minutes are free on a public repo; an erased verdict is not.

- **ai_mail: Fable is granted by name, and the only name is @devpulse (FPLAN-0528, ai_mail owning; Patrick's ruling 2026-09-08, supersedes his 08-30 "managers are fable").** He saw Vera wake on Fable at 11:31 through the daemon's timer lane: `resolve_wake_model` gave every `citizen_class: manager` Fable, and a project owner is a manager. Now `FABLE_GRANT_DEFAULT = {"@devpulse"}`, overridable by a `fable_allowed` list in the untracked `.ai_mail.local/safety_config.json` (the config pointer moved there too: it had resolved to the branch root and never read a file). Absent, unparseable, missing-key or not-a-list all fall back to the devpulse-only default, never to empty; an explicit empty list is honoured as revocation. `resolve_wake_model(target_email, requested)` returns `ModelDecision(model, refusal)`; a refused Fable request is rendered as a warn step on the model label in the dispatch output, names the seat, the requested model and the ruling date, and the wake proceeds on opus. Nothing requested still means opus, for granted seats too. `MANAGER_MODEL` retired; the manager gate (who is woken at all) untouched. Three sites name a model and all take the resolved value (tmux lane, headless lane, the dormant daemon.py). Nine 08-30 pins rewritten in place with the supersession named, a tenth found by the suite (it pinned the literal `--model fable` and had become a third copy of the rule), eleven added, 26 mutants dead; README's 08-30 block kept marked SUPERSEDED. 1463 green both rootdirs, audit 100, verified from the devpulse seat: real resolver against the real grant (@vera fable → opus with the refusal, @devpulse fable → fable), and a live round trip `dispatch wake @daemon --model fable` printed the refusal by name and launched nothing.

- **devpulse tests** — the branch's own v5 rows closed: eleven either/or assertions (`"usage" in out or cmd in out` and kin) now pin the one string the code prints, measured by running each command; six isinstance-only units pin values, three of them archived to `tests/.archive/` as subsumed by the neighbour that already pinned the exact value; two vacuous loops assert before iterating; five feedback-inbox tests and the wire's never-spawns test read what they print or count what they forbid. `assertion_shape`, `no_oracle`, `unentered_assert` 100; 569 passed from both rootdirs; five mutations red. `capture_never_read` (26 units reading `capsys` through a same-file helper) closed when seedgo taught the rule to follow the helper; the one real row left, `test_router_timer_wake_in` asking for `capsys` it never read, drops the parameter. devpulse reads 100 on every v5 rule.
- **commons tests** (FPLAN-0510, commons owning) — 94 → 100 on the v5 pack. `pin`, `react`, `unpin`, `unreact` are now named by contract tests entered through `reaction.handle_command` (a misroute is caught, not just a fall-through; one of commons' own first pins survived its mutant and was strengthened before landing); five either/or assertions pin the exact refusal text; the mood-styles loop asserts its floor before iterating; all 113 patches of the fleet json shim carry `autospec=True` — measured against a shim with `log_operation` deleted, 19 tests that were green only because a MagicMock invented the missing function now go red. 497 green, shim byte-identical.
- **seedgo tests and the v5 pack** (FPLAN-0509, seedgo owning) — 93 → 100 on all twelve rules. `capture_never_read` now follows a same-file helper that takes `capsys` and reads it (`_output(capsys)` and kin) to its fixed point, the delegated-oracle shape `no_oracle` already knew: fleet rows 132 → 9 without a test touched (devpulse 94 → 99, memory 93 → 99). `coverage_slot` no longer convicts its own detector tests; `posix_literal` tightened in both packs. 31 test files re-pinned: the four unnamed verbs get contract tests through the real door (`entry_point_diff` 33 → 100), every patch carries `autospec=True`, either/or assertions pin the printed string, loops assert their floor, and the three mutation survivors from FPLAN-0496 are killed on path (a mutant installed by swapping `sys.modules` after import reached nothing, because prax caches the resolved service). 3864 green from the repo root.
- **flow tests** (FPLAN-0511, flow owning) — 98 → 100 on all rules. The `mock_drift` measurement, both directions: production reaches exactly one thing through the patched `json_handler` module, `log_operation` at 59 call sites; with that function renamed in the shim, zero of the 54 module-patching units went red before the cure and 41 after (the other 13 never reach it on their path). `autospec=True` was refused by the autouse conftest patch on the same attribute (`InvalidSpecError`), so the 54 carry `spec=True`, which the rule acquits in the same sentence; the 4 `load_registry` patches carry `autospec=True`. Six `HOSTS` parametrize rows are pinned by a second derivation read from the class body (a constant named `_HOST` whose source imports a path dialect), so an emulated host defined and never registered goes red, which nothing pinned before. Fifteen no-oracle units read what they print or assert the verdict a does-not-raise path returns; `release_lock` on OSError now asserts the warning it took a logger for. Three either/or assertions pin the printed string; two loops assert a measured floor, one of which exposed a pin satisfied by the description column while the module name was blank. Ride-alongs: nine POSIX literals and three type errors in tests. 1023 green from both rootdirs; README file and function counts re-measured (two were stale).
- **hooks tests and the parked census** (FPLAN-0513, hooks owning) — 99 → 100 on all rules, and `tests/parked/` no longer exists. Its two files (47 units: the retired `auto_watchdog` handler's 9 and the retired `presence` module's 38) are archived under `tests/.archive/` with a reason header each; every surface that moved to `cc_sessions` rather than dying was checked and is already pinned there, so nothing was un-parked. The measurement that set the order: `tests/.archive` is outside the pack's corpus walk and `tests/parked` inside it (a conftest stops pytest, not a static reader), so one assertion-shape row lived in a file that had never executed. Four either/or assertions in the CLI contract file pin the string the real binary prints (`-p, --print` as a pair; a bare `-p` matched `--permission-mode`); three units that asserted properties of a conftest dict literal are archived as tautologies; `test_paths_return_path` pins `BRANCH_ROOT`'s name and a landmark instead of a type, because the branch's known gotcha is an import-time resolve that reads the cwd. Nine vacuous loops got floors or were restructured into one assertion over the whole run; six introspection smoke tests assert the line they print (to stderr, through the cli's err console); five does-not-crash units assert the failure was reported, one of which was green-blind because it patched `engine.logger` while the report goes through `diagnostics.logger`. 21 mutations red, 11 mutated files restored byte-for-byte; 1836 passed, 2 skipped by design, from both rootdirs; README and branch-prompt counts re-measured (51 files, 1756 functions, 1838 cases).
- **ai_mail tests** (FPLAN-0514, ai_mail owning) — 99 → 100 on all rules, 26 rows, 25 units changed in place and one archived. Every either/or assertion was resolved by running the unit and printing the value first: the sandbox-bounce test's `'sandbox' in reason` clause had never once held (the reason a sender actually receives is a bare `exit code -4`, a product gap now on ai_mail's next wave), and the interactive-input test's TTY claim had never been asserted because the fixture's EOFError made the first clause true. Six type-only units pin values (the two public-surface door tests pin `is_absolute`, because devpulse's wire reads both doors from another cwd); the one unit with no claim left (`get_footer` returns a constant two siblings already pin) is archived with that reasoning. The one `self_skip` row was removed rather than rewritten: both worlds are asserted now, the resident-projects tree present and absent. Four vacuous loops got measured floors. 25 mutations red, every source restored. 1452 green from both rootdirs; README counts re-measured and the counting method written beside the number, because the old figure agreed with no method (an archived file was still listed in the tests tree).
- **drone tests** (FPLAN-0516, drone owning) — 99 → 100 on all rules, 36 rows over 33 units in nine files. Two defects the rows did not name, found by the required measurement: three `test_module_registry` units carried a patch that never applied (a `patch` of `importlib.import_module` earlier in the same `with` made the next `patch` target resolve through the mock, so those tests wrote real log records for months), and `test_includes_slash_tmp` could not fail because `$TMPDIR` on the host is `/tmp` and was quietly supplying the root the carve-out was credited for. `mock_drift` measured both ways: 18 of 21 cases green on a renamed `log_operation` before autospec, 21 of 21 red after; the autouse fixture that already patched the attribute now carries autospec and yields the mock. Two `/tmp` units are POSIX-only by `skipif` with the root spelled from `os.sep`; `/etc/passwd` standing in for "outside the fence" is a `tmp_path` sibling. Five vacuous loops floored (one floor measured at 2, because an unfiltered `list_branches` drops archived rows). 20 mutations red; 1264 green from both rootdirs; README counts re-measured (three stale claims corrected).
- **aipass tests** (FPLAN-0515, aipass owning) — 98 → 100 on all rules, 71 rows, no production change. `mock_drift`: 30 of 34 units green on a renamed `log_operation` before autospec, 30 of 34 red after (the four survivors return before the call by construction); eleven identical fixture patches cured in the same pass. One either/or refusal assertion across three parametrize cases was two different refusals (`.` and `./` as a project root, the empty path for recording nothing) and now rides the parametrize one phrase per case. Two of aipass's own new pins were caught too weak by its harness, and the harness itself lied once: a same-length mutation restored within the same second kept the mutated `.pyc`, so it purges `__pycache__` before every run now. 37 mutations red, files restored and md5-verified; 1081 green from both rootdirs.
- **backup tests** (FPLAN-0517, backup owning) — 94 → 100 on `assertion_shape` (17 findings over 16 units, one more than the rows file showed), `no_oracle` and `empty_parametrize` to 100, nothing archived. The five ceiling-guard either/or assertions (`not dest.exists() or not any(dest.rglob(...))`) were run on a fresh tree instead of guessed: `snapshot` scaffolds the store and then refuses, `versioned` refuses before it scaffolds, two behaviours the `or` had blurred into a sentence that could not fail; both are pinned by name now. `HELP_ARGV` is the one live site of the documented `empty_parametrize` false positive (a class-body literal that cannot vanish at collection) and is closed the way the rule asks, with an independent count pin that goes red when a row is deleted while the sweep silently runs four cases. 14 mutations red with `__pycache__` purged before each, sources md5-verified; one new pin was caught too weak by its own mutation (a bare word that survived in the examples block) and strengthened before landing; 371 cases green from both rootdirs, README counts re-measured.
- **api tests and the api exit seam** (api owning) — 97 → 99 on the pack, six of seven rows to 100, the seventh ruled a judged false positive (`unentered_assert` VACUOUS-GUARD on a loop whose preceding assert already pins the directory present; forwarded to seedgo as a rule note). Five routes and verbs are named by contract tests through the real door (`entry_point_diff` 83 → 100); fifteen files carry `autospec=True` (a renamed `is_ssl_error` is red now, it was green before). `apps/api.py` clears cli's process-level failure flag before routing and resolves the exit from it, so a refused `validate` or `revoke-token` no longer exits 0 (`host_api.py` promotes the unknown-token warning to an error). 1582 green from both rootdirs, six mutations red, README counts re-measured.
- **spawn tests** (FPLAN-0518, spawn owning) — 96 → 100 on all rules, 30 rows over 14 files, nothing archived, no new test files. The five either/or assertions were resolved by running the lane: three registry "one of the two ids moved" tolerances described a world the code never produces (both ids are always re-minted) and now pin the shared id gone and both replacements 36 chars; `ensure_project_has_owner` pins the key ABSENT on the untouched entry; the live baseline verdict pins the rule (measures exactly when a resident tier is present) instead of `None or str`; the host parsing fact is a closed set via `partition`, which also convicts a bare `demands:`. Four type-only assertions now pin values (exit 0 plus one `print_introspection` call, True for its own verb and False for a foreign one, a call recorded through the consumer binding, the values of a real mint). Fourteen vacuous loops floored with measured counts (`SYNTHETIC_FLEET_SIZE = 8` beside the fixture with its reasoning: ten planted, two decoys). Six `empty_parametrize` rows acquitted the way the rule asks, the count re-derived from the raw source as an AST. Eighteen mutations red, every one re-taken under a real `__pycache__` purge after the first ten were found to be no-ops (`drone rm` refuses `__pycache__` silently with exit 0). 960 green from both rootdirs; README re-measured (809 test functions by AST, the method written beside the number).
- **daemon tests** (FPLAN-0519, daemon owning) — 98 → 100 on all rules, 8 rows over 7 files, no production change, nothing archived. The `--help` either/or (`USAGE in out or daemon in out.lower()`, both clauses true on the real banner) pins the literal `USAGE:` line and the heading; the headless-lane probe that asserted membership in `(True, False)` now pins True and the `scheduled` parameter of ai_mail's `wake_branch` that makes it so, so the day ai_mail drops the lane both halves go red together. Two `test_help_flag` units that requested capsys and never read it now pin the heading their own verb prints. Four vacuous loops floored with measured counts (twelve gated verbs, five schedule types, eleven queue fields) and one with names (`structure_checks` is exactly `.trinity/local.json` and `.trinity/observations.json`, so a health check that quietly dropped a file cannot shrink past the pin). One seedgo finding forwarded: `unentered_assert` reads a literal floor only in the loop header, so a literal bound one assignment above is convicted. Eight mutations red under a python `__pycache__` purge, 594 green from both rootdirs and with the roster forced empty, README re-measured (531 test functions, 594 cases).
- **skills tests** (FPLAN-0520, skills owning) — 97 → 100 on all rules, 12 rows over 5 files, no production change, nothing archived. `mock_drift` measured both ways and it did not say what the rule expects: with `log_operation` renamed in the shim, one of the two module-patching units in `test_creator` survived, and the other went red for the wrong reason (a second, unpatched reach into the same shim at `template.py` 106 raised inside production); after `autospec=True` both go red at the patch itself. The version banner either/or (`"SKILLS" in out or "1.0.0" in out`) pins the banner, so a half-broken one is red now. Two things the rows did not name: a VACUOUS-GUARD in `test_template` sat on a dead `except UnicodeDecodeError` (the template lays down exactly two utf-8 files; the handler had never fired and would have swallowed a real read failure as a skipped binary), removed, the floor is the exact filename list; a first cure that pinned `body.count("##") == 14` on a markdown document was replaced before landing with the real contract, the frontmatter split. Eleven mutations red under a python `__pycache__` purge, three of them redone after the harness caught a quoting bug that had silently skipped them; 286 green from both rootdirs; README count (281 functions, 13 files) re-measured and already exact.
- **trigger tests** (FPLAN-0522, trigger owning) — 98 → 100 on all rules, 18 rows over 13 files, nothing archived: every one of the eighteen had a real contract underneath that was never asserted. The `self_skip` row read `config.sys.platform` (a machine probe reached through the subject module, so the pack convicts it correctly) and now reads `sys.platform` directly. The fifteen `no_oracle` units (the "handles gracefully" and stub units in `test_error_detected`, `test_pr_status_sync`, `test_watchers_log_watcher`) each pin what the swallowed failure leaves behind. 22 mutations under a python `__pycache__` purge, two survivors reported rather than hidden: a belt-and-braces guard duplicated at a module boundary (docstring now says so, the unit pins what it actually owns), and trigger's own exit-seam instrument, which had left `mark_command_failed` auto-mocked so deleting the reset it pinned stayed green (fixed, then red). Two hardcoded-path hook findings left deliberately: the fake paths are the input to the path-stripping normalizer under test. 1051 green from both rootdirs; README re-measured (1017 functions, 28 files, 1051 cases: the two added functions are the exit-seam contract tests in `test_trigger_entry`).
- **memory tests and the never-run census** (FPLAN-0521, memory owning) — 98 → 100 on all rules, 33 rows over 32 units (the rows file said 32 and "mostly parked"; re-measured, three sit in `tests/parked/`, thirty are live), nothing archived, nothing moved. Two defects the rows did not name: `test_the_six_published_keys_are_still_ints` built its entry with a field named `observation` (the schema says `note`), so it measured a MISSING-FIELD hit and never the over-cap hit its docstring claims (now 500/300/+200 pinned); `test_no_registry_glob_in_this_tree_is_left_unfiltered` required the literal `_REGISTRY.json` on the glob line, so `registry_scope`, which globs through two constants, had both sites invisible (the matcher reads the constant names, sites floored per module). The parks stay in the tracked `tests/parked/` under Patrick's 2026-08-18 ruling (`.archive` is the disposal zone; live tests pin the park on disk): each directory now carries its dated revival condition or its reason in `tests/parked/README.md` — `symbolic_20260814` (revives when the AUDN deduplicator records what a Delete verdict removed), `unwired_handlers_20260813` (revives when a caller appears for learnings / manager-vectorize / storage), `dead_template_lane_20260827` kept as marker-7 retirement evidence with the live refusal that names it. README states the census the counts were hiding: 1437 test functions, 91 of them the dormant symbolic suite skipped at module level (`test_symbolic_extras` 76, `test_vector` 15), 172 more under `tests/parked/` where `collect_ignore_glob` keeps pytest out. 27 mutations red under a python `__pycache__` purge; five text-only cures on files that cannot run are named as such, not claimed as checked. `config reset --json` publishes `verb: config` where every other config verb publishes its own name — pinned as measured, a wire string @api parses, not changed inside a test wave. 1578 green from both rootdirs.
- **cli tests** (FPLAN-0523, cli owning, the last seat) — 98 → 100 on all rules, 5 rows over 3 files. The three `no_oracle` units in `test_handler_guard` were bare calls under a patched caller lookup whose whole claim was "did not raise"; each now names the refusal through `pytest.fail` and, where no sibling pins it, asserts the debug trace (the backslash spelling reaching the branch check; `caller_file = None` proving the fail-open arm). The import-time guard cannot be mutation-isolated (any allow-arm mutation stops the branch importing itself, so the whole suite errors at collection); the oracle was proved live the other way, by handing the unit a foreign caller and watching `pytest.fail` fire. The two `assertion_shape` type-only units were archived to `tests/.archive/deleted_2026-09-08_type_only_return_contracts.py` after measuring that their siblings carry the value by identity (`return False → return 0` reds the sibling; `any(...) → sum(...)` reds 17 sibling cases), with both mutation results in the header. 176 green from both rootdirs (172 baseline, two archived, six seam contracts added to the existing `test_cli_routing`); README re-measured (164 functions, 9 files, 176 cases; importer census 368 statements in 255 files).

## [2026-09-07] — the blanket-ruling day: eight owner waves on the contested MERGE rows, the watchdog dead-monitor backstop, the fleet refusal sweep (FPLAN-0492 / FPLAN-0499, merged as PR #758, v2.8.3)

### Fixed
- **aipass: six refusals exited 0 — `feedback` with drone missing or hooks timing out (the rc from @hooks was computed and discarded), `handoff --cli <bad>`, and `profile clear` on a piped EOF or a wrong confirmation, which reported success while clearing nothing (FPLAN-0492 wave 6 / FPLAN-0506, canary's sweep rows).** All exit 1 through `raise SystemExit`, aipass's own idiom (it never consults cli's `resolve_exit`); the three green tests that asserted `result is True` were rewritten in place, `handoff.py:152` had no test at all and gained one in the existing platform file, and counterfactual pins keep the success paths at 0. A seventh row (`feedback` unknown option, `~97`) exits 0 still and is aipass's next wave.
- **aipass: `--no-chat` and a non-TTY install skipped the doctor preflight silently; `--non-interactive` ignored the cwd and always targeted the default home; a second concurrent install died without a word (FPLAN-0492 wave 6, todos 193/206).** The skip is now announced with `aipass doctor --fix` named; a headless install standing in an AIPass tree targets that tree; an install lock is claimed before the first mutating step and released before the welcome chat (which replaces the process), a second install refuses naming the lock path and holding pid, a stale lock from a dead pid is taken over once and announced. Two existing tests had an unstated dependency on the runner's cwd and now pin it. Caught in passing: the first `_pid_alive` used `os.kill(pid, 0)`, which terminates the target on Windows — rewritten to `tasklist` there, unknown counts as alive so a live lock is never stolen.
- **aipass: `init_flow._write_local_json` was the last hand-rolled atomic writer in the tree (mkstemp + dump + replace) and rode a size bypass row.** It goes through prax's `write_json` now, a `False` raised back into `OSError` so a lost init stage cannot look like a saved one. The bypass row stays, and its premise was wrong: it is a file-size bypass on a 1210-line module, measured by control-running both lanes with the row removed (audit 95 %, checklist FAIL); the split is a scoped refactor on aipass's list, not a wave smuggle. `--help` now names `feedback` and `handoff` (handoff was missing from the bare listing too) and `init`'s positional scaffold.
- **hooks: five refusals exited 0 — `dismiss <nosuchalertid>`, both `feedback` sentinel arms, `hookstatus` with no config, and an output-capture status (FPLAN-0492 wave 7 / FPLAN-0507, canary's sweep rows plus one the suite found).** Cure is `sys.exit(1)`, the idiom already in `wire_verify.py` — hooks refuses through yellow Rich prints, never cli's `warning()`, so the fleet seam carries nothing there. Five tests rewritten in place (one had patched `_dismiss_alert` with a bare truthy MagicMock and could not fail in either direction); three mutations, each red. Measured and named, not fixed: from a neutral cwd `drone @hooks status` renders AIPass's config while a direct `find_project_config()` returns None, so under drone the cwd-walking surfaces resolve the AIPass project and the no-config branch is unreachable — a drone finding. The heredoc-body false positive in the test-write gate is NOT fixed (only the runner half was); it is git_gate's defect wearing a second gate, hooks' todo 25, next wave.
- **commons: every refusal exited 0 — `thread bogus`, `thread 999999`, `post`, `comment`, `room join` and a `whoami` with no detectable identity all printed the red cross and returned success (FPLAN-0492 wave 7 / FPLAN-0505, canary's sweep row).** The cure is cli's existing seam, not a commons one: `reset_command_state()` at the top of `main()`, `error()` marking the command failed as it already did, `resolve_exit(handled)` producing the verdict — a refusal now exits 2 (cli's handled-but-failed code), an unknown command exits 1 and names the whole invocation. A first draft built a parallel `exit_status` module across 21 routers; withdrawn on the steer, both files parked in `.archive/`. Four pins in the existing `test_cli_and_contracts.py` (deleting the seam kills two; the first draft's flag-poking pin killed none and was rewritten); an autouse conftest fixture clears the process-level flag per test because the suite is one process where a real run is one per invocation.
- **ai_mail: `monitor_alive` answered `None` on Windows, so the watchdog there could never see a dead monitor — the Windows matrix went red on 6d764980 on the two liveness pins.** `os.kill(pid, 0)` is TerminateProcess on win32, not a probe, so the Windows leg asks `OpenProcess` + `GetExitCodeProcess` (the probe prax's `instance_lock` already uses; kept separate because that one is private and folds "exists but not ours" into dead). `ERROR_INVALID_PARAMETER` → gone, `ERROR_ACCESS_DENIED` → alive, anything else → `None`. Five mapping pins through a fake kernel32 run on every platform, plus a routing pin that `os.kill` is never reached on win32. Same run: api's two ONE ROOM wiring tests drive `open_attach`, which refuses on a host with no PTY — marked `@pty_required` like the file's other attach tests.
- **api: a refused bind exited 0, so `Restart=on-failure` never fired and the host-api face stayed dark after roughly one boot in three (FPLAN-0492 wave 4, api's incident 3023446f).** The tailscaled boot race (six seconds, measured in the journal on two of the last six boots) now exits 1 at all three `host_serve.py` sites and the unit's sixty-attempt window arms. Carved out of APLAN-0013 as a bug against documented intent; pinned at the foreground and detach seams.
- **api: the phone's git-changes cards each spawned their own `drone @git status --json` — 31 concurrent reached 60 % of the 30 s budget on an idle box and timed out under boot load (incident a6a71c2d).** `git_reads.py` now coalesces: single-flight plus a 1.5 s TTL keyed on (branch, project, grain), the mechanism in a new `apps/handlers/host/read_cache.py` (the 1500-line cap forced the split). Four mutations red, including the copy-on-read pin that needed three readers to bite.
- **flow: a Windows-absolute or UNC recorded plan location was restored under `FLOW_ROOT` silently (FPLAN-0492 wave 4, todo 180).** `restore_ops.py` tested absoluteness with `startswith('/')`, so `C:\plans` and `\\srv\share\plans` read as relative. Now `PurePosixPath` OR `PureWindowsPath` `is_absolute`, and an absolute recorded directory that has vanished is an error naming the path, never a silent re-home. Five pins, mutation-checked.
- **flow: `team_dev_plans` derived `TPLAN` on a fresh install and `TDPLAN` only where the registry already held the row (FPLAN-0492 wave 4, todo 179).** The prefix rule is now deterministic: initials of the underscore words minus a trailing `plans`, plus `PLAN`; collision widening unchanged. Every shipped directory derives its registered prefix (pinned against the live template tree); the one hypothetical that moves is `security_audit_plans`, `SPLAN` → `SAPLAN`. The README says where a prefix comes from.
- **flow: nine doors accepted an unknown argument and exited 0 — `aggregate <bogus>` ran the cross-branch write, `post <bogus>` ran the archival pass (FPLAN-0492 wave 4, the unknown-argument ruling).** One gate, `apps/handlers/cli/arg_gate.py`, decides and raises `UnknownArgument` with a did-you-mean; each module renders it and exits 1 before any write. `registry <bogus>` no longer prints a contradictory second refusal plus the help screen. The undocumented `aggregate run` / `scan run` sub-verbs are refused. Reported, not changed: `register`/`unregister` with a missing argument still exit 0 (arity, not an unknown argument).
- **skills telegram: the secret store held a ten-key bot document of which one key was a secret (FPLAN-0492 wave 6, todo 205; the root of CodeQL #111, a false positive on prax's audit-log side).** `config.SECRET_FIELDS` is now the rule — `bot_token` plus the Telegram app credential `api_id`/`api_hash` — and `create_bot` hands the secret store `{bot_token}` only; the other nine keys live in `~/.aipass/telegram_bots/<bot_id>.json`, promoted from "staging artifact" to runtime config, with `load_bot_config` merging the halves so callers keep the dict they had. The config write is fatal where it was a logged non-fatal (a bot whose branch and work_dir never landed cannot start). Legacy ten-key documents still load and warn on every load, naming the stray keys and the split command. A dry run against the live store caught the first draft proposing to move the app credential into a plain file — pinned by `test_the_telethon_app_credential_is_left_alone`. Migration is an operator door, `drone @skills run telegram migrate-config` (dry by default; `--apply` is Patrick's call: 30 keys across 5 bots, token kept in every one). Seven pins in `test_multibot_config.py`.
- **skills telegram tests wrote `sync_test.json` into the live `~/.aipass/telegram_bots/` on every run.** A conftest autouse fixture redirects `config.BOT_CONFIG_DIR` per test; the eight `_BOT_CONFIG_DIR` patch sites moved to the one owner, and a hardcoded `/tmp/test_bots` is gone.
- **memory: every refusal exited 0 — unknown verb, unknown flag, `rollover <bogus>` all printed the right cross and returned success (FPLAN-0492 wave 6, the only branch failing all three probes of the 2026-09-07 sweep).** One seam: every door in `main()` returned None and `__main__` never called `sys.exit`. Cured with the fleet idiom (`reset_command_state()` at the top, `resolve_exit(True)` on the routed path): unknown verb 0 → 1, unknown flag 0 → 1, bogus sub-argument 0 → 2 (handle_command's True means "handled", not "worked"); `--help`, `--version`, bare and working verbs still 0. Four pins in `test_contracts.py`; the README documents the exit-code contract with the before/after table.
- **memory: the templates bump ledger could never be stamped — `push` reported 54 stray `.trinity/` files across 22 of 22 branches as "NOT push scope", and three readers (spawn, memory, devpulse) took the line as a verdict on the branch.** It named the files. The line now says so, and `_trinity_strays()` no longer counts `*.pre_v2_backup` / `*.pre_v3_backup` — accounted-for artifacts of named migrations (exclude by name, not an archive sweep: moving 54 files out of 22 citizens' `.trinity/` is a cross-branch write, and a pin keeps the backups surviving a push). First real push: 22 branches, 44 files, 22 receipts, 5 entries archived and pruned, 854 carried, 0 strays; ledger stamped local 3.0.0 / observations 3.0.0; a dry run straight after reports nothing pending. The per-machine ledger `templates/.template_version.json` is gitignored.
- **memory: `_completion_status` returns `"unknown"` for an absent or empty section** (hooks' 09-05 finding, trigger's fourth status value), pinned inside the existing crash test. Twelve checklist flags in `test_trinity_push`, `test_lint`, `test_rollover_pipeline` cured (`/tmp` strings → `tempfile.gettempdir()`, two test names lowercased); the two symbolic-tier flags are moot, those files were archived with the parked tier. Leaf-module bare pops: measured three, all guarded — nothing to cure. README 1437 functions / 42 files / 1573 collected.
- **ai_mail: a dispatch row stayed outstanding until the two-hour hard timeout after its target had already replied, so the devpulse watchdog announced `DEAD @api` for a landed wave (FPLAN-0492 wave 5 / FPLAN-0499 phase 2).** Close-on-reply now lands in the reply path and matches by THREAD (replier is the row's target, recipient is the row's sender, `thread_subject()` equality after stripping stacked `RE:` markers), not by dispatch stamp: api's stamp sat on its report-first plan mail while the real completion carried a different id after a resume, so stamp matching would have closed early on the plan and still missed the completion. Four overdue rows (flow, api, drone, prax) were closed through the rule by append, never by hand; three older rows with no surviving reply evidence and one bare-wake row with no thread stay open by design (a sender-side close door and a 24 h expiry rule are ai_mail's next wave).
- **ai_mail: the admin bridge's discovery half walked `projects/.archive/`.** `get_project_tree_branches` globbed `projects/*/*_REGISTRY.json` with no dot filter (the resident half had one), so an archived project surfaced as `@archive`. The rule is now one reader, `_has_dot_component()`, shared by both halves; pinned in `TestProjectTreeBranches` — the first fixture was planted one level too deep and the depth rule, not the dot rule, refused it, which the mutant exposed.
- **trigger: two doors refused an unknown sub-argument and exited 0 (FPLAN-0492 wave 5, row 51 of the 2026-09-07 sweep).** `errors <bogus>` printed the token and returned True; `escalation <bogus>` printed its HELP screen and returned True, never naming the token. Both now refuse through the one gate at `trigger.py:246-256` (`Unknown command: errors bogus_xyz`, exit 1). Two green tests had pinned the old behaviour — the suite was agreeing, not silent — and were rewritten, plus an end-to-end pin over both modules in `test_trigger_entry.py`.
- **trigger: the catch-up scan counted one occurrence per distinct error, so a 37-line burst arrived as `count=1` and gate 3 (`count >= 2`) held it as "first occurrence — waiting for pattern" (FPLAN-0492 wave 5, the count-vs-occurrences gap @api's incident exposed).** The dedup key is unchanged (one event per distinct error, never 37 dispatches); `_scan_single_log_file` now counts every matching line and stamps `first_seen` / `last_seen`; the live watcher path is untouched; severity stays a documented constant, never derived from the count; `MAX_ERRORS_PER_SCAN` still measures distinct entries so counting repeats cannot widen the storm guard. Five pins, three mutations red.
- **drone: `rm`'s deletion ledger named the caller from the directory it stood in (FPLAN-0492 wave 3, S2).** A devpulse deletion run from the repo root was recorded as `caller: aipass` — the project, not a citizen. `deletion_log` now resolves the caller through `resolve_caller_identity_signal` and accepts only the `assigned` or `passport` sources; the `project` source is refused because it answers "where", not "who". The repo root with no passport now records `unknown`; standing in drone records `drone`. Mutation-checked. The 211 earlier records stay untouched, with one record-shaped annotation appended after them (S1, Patrick's option 2).
- **drone: `drone @git log not_a_real_count` honoured the default and exited 0 (FPLAN-0492 wave 3, S5).** Output was byte-identical to a plain `log`, stderr empty — a caller reading `$?` was told its count had been honoured. Now refuses by name on stderr, exit 1, and an `ok: false` document under `--json`; the three idioms (`log 20`, `log -n 20`, `log -3`) still parse. Three pins.
- **prax: six doors accepted an unknown argument and exited 0 (FPLAN-0492 wave 3, the unknown-argument ruling).** `drone @prax --definitely-not-a-flag` printed the self-map, `log-audit`/`monitor`/`log-health` printed a refusal and still exited 0, `dashboard` printed help, and `status bogus` printed the normal status block with no complaint at all. All six now refuse by name on stderr with exit 1 through one shared gate (`apps/handlers/cli/arg_gate.py`), pinned.
- **seedgo `audit`: every refusal now exits non-zero (FPLAN-0496, row from the 2026-09-07 fleet sweep).** Unknown argument, `--artifact` with no path, a branch without `@`, unknown pack, private branch, branch not found — each printed the cross and returned 0. `_print_refusal` raises `CommandRefused` (in `apps/modules/__init__.py`), `seedgo.py` passes it through `route_command` and returns its code. Pinned in `test_standards_audit.py`. The argv grammar moved to `apps/handlers/audit/argv.py` when `standards_audit.py` crossed 600 lines (609 → 573).
- **seedgo: a `SyntaxWarning` from a compiled template during the fleet walk.** `corpus._walk` now prunes dot-directories as pytest's `norecursedirs` does; the source was an `.archive/` file `ast.parse` could not attribute.
- **seedgo README said "11 core agents" three times; the fleet is 18.** `json_handler_content.py` no longer prints the retired `aipass.aipass.shared.json_handler` example; `json_handler.md` no longer says "retiring".
- **hooks: `drone @hooks <bogus>` refused on stderr, and the version drift its own tests were pinning (FPLAN-0495, hooks todo 16).** The refusal printed to stdout with exit 1, so redirecting stdout swallowed it; moved to `err_console`, exit unchanged, both tests now pin stderr and assert absence from stdout. `hooks.py` header said 1.2.0 while the banner and `--version` said 1.1.0, and both tests asserted the literal stale string; now 1.2.1 everywhere and the tests read the `# Version:` header (mutation-checked: header bumped with the strings left behind → 2 failed).
- **hooks test-write gate: `-m pytest` / `-m unittest` paths no longer read as test-file creation (testwrite_gate 1.1.0, bash_writes 1.3.0).** `write_targets_by_segment()` split out so there is still one shell reader; the exemption is per-segment (`pytest x && touch tests/test_new.py` still refuses; 56 → 67 cases). Known residual, hooks todo 25: `_interpreter_targets` scans the whole command, so a heredoc plus a pytest path in one call still refuses.
- **daemon: twelve verbs refuse an unknown argument by name (FPLAN-0497).** `update`, `queue`, `rotation`, `inbox-sweep`, `run`, `install-timer`, `uninstall-timer`, `schedule`, `actions`, `activity`, `activity-report`, `activity_report` accepted and silently ignored a trailing argument (daemon's own finding after FPLAN-0494). One shared gate, `apps/handlers/cli/arg_gate.py`, knows boolean flags from value flags (`--hours 48` is not a stray positional), lets a help request outrank it, and raises `UnknownArgument`; every verb refuses on stderr with the usage line and exit 1. Two swallowed refusals surfaced and cured: `update.py`'s broad `except` turned the refusal into exit 0 (the gate now runs outside the try in every module), and `route_command`'s broad catch fell through to "unknown command" (the refusal is caught first, pinned). Mutation-checked one per verb, all twelve red. Every test that resolves a branch or job name now patches the roster; 594 passed with the registry forced empty.
- **daemon tests: the five branch-health tests resolved the branch name against the machine's registry**, which a CI checkout does not have (PR #758 red on b681c085). The roster is now pinned in the tests; the refusal tests keep the real function.
- **spawn: `add_to_registry` and `sync_registry --fix` refuse an unreadable registry (FPLAN-0493, todo 188.2).** Red-first over a registry truncated mid-file: `add_to_registry` returned True and left the file holding one branch with `metadata.id` None; `sync_registry(fix=True)` rewrote it with freshly minted uppercase entries and new registry ids, orphaning every passport that carried the real credential. `registry_is_writable_document()` now guards both (missing → creatable, unparseable or not-an-object → refuse by name, file byte-identical); `metadata` via `setdefault` so a registry without it cannot KeyError mid-write. Five pins in `test_registry_credential.py` (30 → 35).
- **spawn `update`: the passport heal reported "updated" on every run for externally written passports.** The "did anything change" test compared serialised text against on-disk text across an `ensure_ascii` boundary, so a 1.0.0 passport with escapes came back changed with a backup and zero changed fields, forever (@vera). It now compares parsed documents. The "half-migration" premise from the 09-06 vera research was measured false: passports never reach `deep_merge`, the heal allowlist is three fields that exist in every schema, and `migrate_document` completes or refuses (pinned). Template-owned lists (`.registry_ignore.json` ignore_files / ignore_patterns / patterns) now grow additively; permissions deliberately excluded (a union would have re-denied devpulse's publishing lane).
- **daemon `branch-health <unknown>` refused by name, exit 1.** It printed two contradictory "not found" blocks and exited 0 (row 21 of the 2026-09-07 sweep). The name is now resolved once, up front, against the roster the report uses; unknown or missing → one refusal naming the token plus the known-branch list. Resolution is case-insensitive, which closes daemon's standing "expects uppercase" known issue. Pinned in `test_activity_report.py` (36 → 38).
- **daemon `inbox_sweep` docstring and introspection panel** claimed it discovers from `AIPASS_REGISTRY.json`; the sweep has read the whole fleet through @memory's `fleet_branches()` (28 citizens, projects/* included) since FPLAN-0460. Text corrected, scope pinned by `TestSweepScopeIsTheWholeFleet`. Dead `apps/json_templates/` (zero readers) archived out of the tree.
- **devpulse `admin_grant`: `verify`, `keygen` and `mint` refused in a yellow print and exited 0 once the owner guard had passed, so `admin_grant verify && <next>` ran the next step on an unverified grant (canary's fleet refusal sweep, 2026-09-07, the three rows directly beneath the 08-28 cure).** All three refuse through `error()`, which marks the command failed; four pins in `test_owner_guard_refusals.py` (a refused verify marks, a verified one does not, keygen and mint past the guard mark), mutation-checked. The sweep itself, report only: 141 `warning()`/yellow-print refusal sites across 18 branches, 35 exit 0, 17 of those with a green test pinning the exit-0 outcome; and the structural finding that only ai_mail, devpulse and memory consult `resolve_exit()`, so in 15 branches `error()` changes the colour and nothing else. Each owner has its rows and the seam rule for its next wave.
- **devpulse: an unknown command or flag is refused by name.** `drone @devpulse <bogus>` used to exit 1 with empty stdout and stderr (the 2026-09-07 fleet sweep's REFUSES-SILENT). `route_command` now prints `Unknown command: <token>`, a did-you-mean from the discovered module names, the known list, and a `--help` pointer; exit code unchanged. Pinned in `tests/test_devpulse.py` (FPLAN-0492, Patrick's standing unknown-argument ruling: fail non-zero and name the token, never default).

### Added
- **aipass: `init` stamps `.aipass/test_write_policy.json` at stage 1 — gate off, empty allow, create-only, never clobbered (FPLAN-0492 wave 6, the shape confirmed by @hooks by mail, never guessed).** Hooks corrected the premise: a fresh install was not permissive, the gate fails closed when the file is absent, so this replaces a fail-closed refusal with a readable, flippable state and closes no hole. Stamped from the live bytes at git HEAD (hooks' mailed copy was abridged). Incident in the same wave, reported by aipass itself: a pin called the cwd-resolving path helper unpatched and overwrote the live fleet policy with a 49-byte fixture (gate on, canary allowed) for under two minutes; restored byte-exact from HEAD, no commit carried it, both tests now patch the path.
- **ai_mail: `monitor_pid` and a tri-state `monitor_alive` on the dispatch register (FPLAN-0499 phase 2).** The pid is recorded as a second append-only outstanding record after the spawn (the original promise is never rewritten); `monitor_alive` is derived at read time from `/proc`, never stored — `True` alive, `False` gone, `None` cannot be told (every row written before this change and the systemd-scope path, which never learns a pid; folding those into `False` would have announced the whole historic backlog dead). Exposed in `outstanding()` and therefore in `outstanding_dispatches()` for the devpulse wire, and in `dispatch register`'s human output per row. Readers treat `None` as "fall back to overdue".
- **devpulse watchdog: dead-monitor backstop (FPLAN-0499, the hole DPLAN-0314 named "outcome M").** A dispatch whose monitor died (host reboot, OOM, kill) can never report; the wire now reads the dispatch register at sign-in and every 5 minutes and pushes one `DEAD @branch ...` line per dispatch of this seat's that is past `expected_by`, announced once ever via `devpulse_json/wire_dead_cursor.json`. No agent is polled and no token is spent until it fires. Found the hard way: the 2026-09-07 12:17 reboot killed two wave-3 agents mid-work and nothing said so for 2.5 h. Phase 2 (wire 2.2.0, same day): once ai_mail served `monitor_alive`, the wire announces a gone monitor within one cadence ("its monitor (pid N) is gone before the hard timeout") instead of at the two-hour `expected_by`; `None` (a row that never learned a pid) keeps the overdue rule, so the historic backlog is not announced dead. Three pins.
- **seedgo json-handler contract: resident citizens are discovered (FPLAN-0496 item 7).** Discovery is a roster — the installed 18 as the floor, unioned with @memory's `fleet_branches()` — measured 18 → 22 on the dev machine; residents load from file with the module cached in `sys.modules` exactly as `import_module` does, and `test_one_branch_is_one_module_however_many_times_it_is_asked_for` pins that identity (an uncached first draft wrote 92 fixture documents into four Vera-Studio trees before it was caught; the files were moved out, nothing pre-existing was touched). The four pre-migration Vera handlers (no shim, `open(path, "w")`) are skipped BY NAME with the finding in the skip line.
- **seedgo json-handler contract: three pins from the advisory mutation run (ruling 5 of FPLAN-0492).** A rewrite keeps the file's permission bits (probe mode 0o640, chosen because 0o664 is what a new document is born with under the default umask and proved nothing); NaN and Infinity are refused with the previous document byte-identical after; log rotation keeps the newest window asserted by content over a seeded 105-entry log. Each pin was run against its mutant on a copy of `json_service.py`; two first drafts were blind and were rebuilt. Run: 391 mutants, 255 killed, behavioural score 77 % once logger-text survivors are set aside; report in devpulse `docs.local/`.
- **seedgo audit banner is pack-aware.** `pack.json` declares `corpus {noun, detail, measured_by}`; `discovery.pack_corpus` resolves it like a checker; the banner no longer says "apps/ only, tests/ not in the corpus" under a pack whose every rule walks test units.
- **daemon: opt-in `catch_up`, interval `slot`, and a MISSED line (FPLAN-0494, ruling 6 of FPLAN-0492).** A daily or rotation job with `schedule.catch_up: true` whose window closed unrun fires late on the next tick, bounded by the already-ran-today guard so it cannot double-fire, stamped `caught_up: <iso>` in its runstate and cleared on the next ordinary run. Interval jobs take `schedule.slot`, an ISO instant naming one occurrence of the rhythm; a freshly enabled job with no `last_run` is seeded so its first fire lands on the slot instead of the next tick (the failure that fired seedgo's weekly audit on a Monday). One `MISSED:` line per daily job per day, same predicate as the catch-up, so the line and the fire never disagree. Root cause: the vera feedback of 2026-09-06 (a host down across the 30-minute window lost the job day silently).
- **devpulse `tools/statusline.sh`** — the watchdog statusline for Claude Code, previously only at `~/.claude/statusline.sh` and tracked nowhere. Byte-identical copy is now the versioned source; the green `watchdog:in` additionally requires the registered wire's `metadata.wrapper == "monitor"`, so a foreground wire with no listener paints `watchdog:OUT`.

### Changed
- **aipass: the profile-write failure event is `profile_write_failed`, not `file_deleted` (FPLAN-0492 wave 6; trigger's alias landed in 41ebc9fe).** Five fire sites renamed (`profile.py` fire at 84 / call at 110, `init_flow.py` 120/125/142), payloads kept, pinned and mutation-checked. 3 MERGE rows: two `print_help` does-not-raise pairs merged (a raising `print_help` killed both members identically); one KEPT — `TestPrintIntrospection::test_does_not_raise` is the only pin that renders through real Rich, its proposed sibling patches the console, and a broken close tag reddens only the candidate. README re-measured: 1052 test functions across 28 files (the old "29" was never right), 1067 → 1081 cases.
- **commons: `apps/json_templates/default/{config,data,log}.json` archived (FPLAN-0492 wave 7).** Measured first: zero references from `apps/`, `tests/` and `tools/`, one from the README's layout row. Moved to `apps/.archive/json_templates/default/`, never deleted; `.archive/` is gitignored, so the tree records three deletions. README re-measured the same night: every line naming v4 `test_quality` as a live standard is gone, 477 `def test_` across 21 files expanding to 491 cases, 74 bypass rows, and a correction to the FPLAN-0490 figure — 53 live prax import sites, not 75 (that count had swept `.archive/`).
- **skills: 2 MERGE rows from the 2026-09-05 contested band, second pass (FPLAN-0492 wave 6).** `test_single_line_sent_as_single_message` deleted (`_send_batched` has no single-line branch; the three-line sibling pins one call and the exact joined payload — mutation `"\n".join` → `" ".join` red on the survivor). `test_declared_unreadable_sends_nothing` deleted: `SwitchStateUnreadable` subclasses `RuntimeError`, so the declared test could never go red while its bare sibling was green; the declared path is exercised for real by `test_corrupt_state_file_sends_nothing`. Sources verified byte-identical to HEAD after each revert.
- **ai_mail: 6 MERGE rows from the 2026-09-05 contested band, second pass (FPLAN-0492 wave 5).** Five merged (two `kill_process` copies and a `cleanup_own_lock` copy 640 lines apart in `test_dispatch_monitor.py`, the error-dispatch suppression duplicate, the header pair as a two-value parametrize); one KEPT with the proof in the test — `test_batch_close_post_ops_partial_fns` is the sole pin that a `None` purge function does not stop the central update, which the walk had credited to its siblings. The `session_pointer` `Path.home()` guard from the brief was already landed and pinned (`_claude_home()`, three tests on a raising `Path.home`); reported with citations, nothing added. 18 mutants planted, 18 killed; 1419 → 1447 collected.
- **trigger: the profile write-failure event is `profile_write_failed`; `file_deleted` is a deprecated alias for one release (FPLAN-0492 wave 5, trigger todo 192).** The event fires on a failed profile write, not a deletion. `DEPRECATED_EVENT_ALIASES` in `core.py` resolves the old name in `fire()`, `on()` and `off()` (off too, or a handler registered under the old name could never be detached), logging the deprecation once per name per process. Measured fleet-wide: zero registered handlers on either name; three firers — aipass `profile.py`, aipass `init_flow.py` (both queued for aipass's wave), daemon `timer_install.py:157` (a different event, queued for daemon to name honestly) — and prax's `unified_stream.py:59` colour map keyed on the literal, queued for prax. Six pins, five mutations red.
- **trigger: 7 MERGE rows from the 2026-09-05 contested band, second pass (FPLAN-0492 wave 5).** Six merged (1049 → 1043 mid-wave); one KEPT with the reason written into the test — `test_suppressed_fingerprint_does_not_dispatch` is the only pin between compass #219 and a suppressed error going out the door. The walk's reasoning on three delegation rows was corrected: the named failure sibling proved the handler was called, not called once; a different sibling caught the double call. Two pins for 3.10 module identity live inside the existing `test_core.py` (a CI canary; the box is 3.12). Dead `apps/json_templates/` (zero readers) moved to `apps/.archive/`, which is gitignored by the 2026-08-18 ruling, so it lands in git as the deletion of four tracked files; the archive copy is local recovery only.
- **api: ONE ROOM step 1 — a branch seated in a room BAUD did not create is attached to, never given a second room underneath it (DPLAN-0327 / DPLAN-0310 P3, FPLAN-0492 wave 4).** `_room_for` honours the snapshot's `outside_room` when `has_room` is false and uses a new attach-only door (`attach.py attach_only_command`, `tmux attach-session`, no `new-session -A`), so the create path is structurally absent rather than guarded. An own room still wins when it exists. Step 2 (an empty room must not outrank a live seat) waits on a per-row liveness field from BAUD.
- **api: 8 MERGE rows from the contested band landed, mutation-checked (FPLAN-0492 wave 4).** Three in `test_api_key.py`, five in `test_openrouter_client.py`; every twin carried exactly one oracle its sibling lacked, the survivor keeps the union. README re-measured (1470 functions / 1569 cases). Left unfolded on purpose: `fleet.py` still carries its own copy of the single-flight+TTL shape that `read_cache.py` now names.
- **flow: 4 MERGE rows from the contested band landed, mutation-checked (FPLAN-0492 wave 4).** One pair merged (parametrised over one and two modules), one kept as a parametrised pair because the inputs straddle a live branch in `print_help`, one kept and now asserting where it asserted nothing. All four read the real Rich output instead of an empty capsys. `test_flow.py` 39 → 40 collected; suite 1023. The dead `json_templates` handler directory (zero readers fleet-wide, 23 mentions all skip-list entries) leaves the tree; a copy sits in the branch's local `.archive/`.
- **drone: 3 MERGE rows from the contested band landed, mutation-checked (FPLAN-0492 wave 3, S4).** `test_path_calls_get_registry_path` folded into `test_path_prints_registry_location`; the four one-line `log_operation` twins in `test_module_registry.py` are one parametrised test over list/info/check/bogus — two mutants prove the verb has to stay parametrised. 1265 → 1264 collected. S6 (rm refusal exit 0) could not be reproduced from any door drone can reach; two pins lock the mapping (an outside-roots refusal is `False`, the CLI maps it to exit 1). S3 (owner/admin rm in siblings) NOT built: the sibling fence is one identity-blind `if`, and the only real authority in the tree is a plugin welded to the git verb table — lifting it is a change to the git credential path, held for a ruling.
- **prax: 18 MERGE rows from the contested band landed, mutation-checked (FPLAN-0492 wave 3).** Seven test files, 1491 → 1487 collected cases (18 test functions gone, 10 cases — a parametrised survivor keeps both inputs where dropping one would change a branch). Every survivor keeps the union of both oracles and eight pin claims nothing pinned before (emit_command_separator's caller/command, SystemLogger level routing, the TTY aliases, doRollover's warning, the template-status truncation). 40 mutations, all red, all reverted. README re-measured: 1404 functions / 1487 cases / 36 files, the per-file table re-collected, 11 handler directories; the branch prompt's "901 tests across 19 files" claim corrected.
- **seedgo: 44 MERGE rows from the 2026-09-05 contested band landed (FPLAN-0491 + FPLAN-0496).** 37 pairs in `test_content_functions.py`, one retired by subject gone (`get_test_quality_standards` left with the v4 standard), six in `test_coverage_audit.py` (collection 124 → 118) each mutation-checked with one mutant per moved input, killed by exactly the survivor that inherited it. v4 test_quality residue: two live-voice references cured, `.archive/` untouched. README re-measured: 62 files, 3028 test functions, 3897 collected cases.
- **hooks: `auto_watchdog` retired and the presence fossil parked (FPLAN-0495, devpulse todos 181 and 171).** `auto_watchdog(disabled).py`, `enabled: false` in both `.aipass/hooks.json` and `project_hooks.json` (30 of 32 entries enabled); the hooks.json edit broke the enrolled trust hash by design and Patrick re-enrolled at 11:13. `presence.py` → `presence(disabled).py`, `presence_gate` stays live; archive waits for a session cycle proving nothing was connected. Both suites moved to `tests/parked/` behind a `conftest.py` with `collect_ignore_glob = ["*"]` — a `(disabled)` suffix does not stop pytest, and a branch-level ini is never read when CI runs from the repo root. hooks README re-measured (1838 cases / 51 files, 59 live apps files).
- **`.aipass/tier1_navmap.md`: the four directory roles in Terminology, and the file trimmed back under its ~8,000-char cap** (it was 9,035 before hooks' bullet; now under the cap with the same signal, bold removed per PROMPT_STYLE).
- **spawn citizen template: `tests/test_json_handler.py` retired (ruling 2 of FPLAN-0492).** Newborns no longer ship the six shim stamps; seedgo's contract suite discovers a newborn's shim by path and passes it by hash (proved on a throwaway citizen, sha256 = `CANONICAL_SHIM_SHA256`). Archived at spawn's `tests/.archive/`, not inside the template (a template `.archive/` ships to every newborn). Manifest 50 → 49 files, `.registry_ignore.json` 1.2.0 → 1.3.0, absence pinned in `test_template_hygiene.py`. Known gap, queued to seedgo: the contract's discovery glob is the installed package, so resident citizens in other project trees get no coverage.
- **spawn citizen template: the four directory-role README stubs** (`docs/` tracked public reference · `docs.local/` own untracked scratch and research, `sub_agent_drops/` inside · `dropbox/` inbound-only, consumed once · `artifacts/` identity and provenance only) from the 2026-09-07 fleet inventory (devpulse todo 194). Newborns only; existing branches refresh their own by hand under their FPLAN-0492 wave.
- **`tests/docker_checklist.md`** (repo root) gains "The one flow": one image (`aipass-test:latest` from `Dockerfile.test`), `--rm` containers only, post-mortem naming `aipass-verify-<date>`, the two runner scripts, never `docker cp`/`exec` a fix into a container (Patrick's 2026-08-28 ruling: no invented flow per test).

---

## [2026-09-07] — the clampdown: test-write gate, one json service for the fleet, v4 test_quality retired, every README verified (DPLAN-0323 / DPLAN-0325, merged as PR #751, v2.8.2)

Section opened 2026-09-01 as "the clampdown begins"; retitled on the merge date per the convention above. Everything from the test-write gate (FPLAN-0468/0469) through the DPLAN-0323 seal (FPLAN-0491) shipped in one PR.

### Fixed
- **CI 3.10 red on `5b4d9cca`: memory's two completion-fire tests patched a bus object the code never called** (devpulse, DPLAN-0323 tie-up, 2026-09-06): `TestCompletionIsAnnounced` used `patch("aipass.trigger.apps.modules.core.trigger.fire")` while `_fire_completion` does `from aipass.trigger.apps.modules.core import trigger` at call time. Those are two routes to what should be one object: the production import resolves through `sys.modules`; Python 3.11+'s `mock` resolves the dotted target the same way, but 3.10's walks the attribute chain from the top package. Something earlier on that xdist worker left the attribute route and the `sys.modules` route naming two different objects, so on 3.10 alone the patch landed on a `Trigger` the code never reaches: run 34088947108, "expected exactly one completion fire, got 0", green on 3.11/3.12/3.13 and green locally in every order tried. drone's `test_git_module.py` already defends against exactly this ("pin module identity … so both paths agree even if an earlier test on this worker disturbed trigger's module state"). Fix in the test, not the code: a `_bus()` helper resolves `importlib.import_module("aipass.trigger.apps.modules.core").trigger` at patch time and the four sites use `patch.object(_bus(), "fire")` — the same route the code takes, on every interpreter. Verified: the file 18 passed; ruff, format clean. What splits the two routes is not named. The known shape — `monkeypatch.delitem(sys.modules, …)` followed by a fresh import restores `sys.modules` but not the parent-package attribute — is the candidate, not the finding: the worker's file order up to the failing test was replayed on 3.12 in one process (352 files, 15,765 passed, 27 min) with an identity probe at that test, and both routes named one object, no split. So the splitter is 3.10-only or xdist-only. The CI run on this commit is green on every interpreter. @trigger emailed the species, no wake.
- **`drone @hooks test` no longer writes the branch it probes — and fixing that found two side effects worse than the one reported** (hooks owning, DPLAN-0323 tie-up, 2026-09-06): the probe fired the real PreCompact handlers against hooks' own `.trinity/` and had stamped a false auto-compact session into its live `local.json` (found in the README round). Three inputs decide which branch a handler acts on — `hook_data["cwd"]`, the process cwd, and `AIPASS_HOME` — measured per handler rather than assumed; `run_test()` now builds a throwaway branch skeleton in a tempdir with copies of the three `.trinity` files and overrides all three for the duration, restoring each in a `finally`. A tempdir is never under `src/aipass`, so a handler that walks upward finds nothing rather than the fleet. **Worse, found while fixing:** `rollover` shells out to `drone @memory rollover run`, a FLEET-WIDE memory trim that ignores `hook_data` entirely and stayed quiet only because nothing was overdue on the nights anyone ran the probe; and `auto_process` spawns @memory's real background worker, whose session guard keys on session id, so the first probe run of a mock id spawns for real (guard file dated to the previous night's probe). Neither is reachable by an env seam — `AIPASS_HOME` appears nowhere in @memory's `apps/` — so both handlers now refuse at the MUTATION under `AIPASS_HOOK_PROBE`, never at the entry: rollover still resolves the repo root and runs its read-only check, auto_process still runs its guard path, and a suppressed kick does not mark the session guard (or a probe would silence the real auto_process for that session). Proof: `local.json` hash changed under the old path (`d46eae42… → 24c3d231…`), identical under the new, all three files; the handler's own log reads `stamped=True … at=/tmp/aipass_hook_probe_*/hooks`, so the run is real and aimed, not quiet. The false session 188 entry removed (the probe's own, 22:52); the genuine 09-05 auto-compact stamp kept. Mutation-checked both ways: both seams removed → 2 of 5 isolation tests red; probe flag off → the fleet rollover really runs and the spawn really happens. hooks' first full run went RED on its own new test (`test_real_run_still_spawns`) — it had not redirected `_GUARD_DIR`, so a guard file from an earlier isolated run suppressed the spawn it asserted; fixed in all three. Nine hooks files, no new test files, `test_auto_process.py:204`'s hardcoded `/tmp` replaced with `tempfile.gettempdir()`. Verified by hooks and again by devpulse: 1899 passed / 1 skipped from the repo root; audit 100 every category; ruff, format clean. **Not changed, for Patrick:** bare `drone @hooks test` prints the introspection and fires nothing (`hook_test.py:221`) — the documented command needs `--verbose` or any argument, which is why the defect survived; making bare `test` run is a ruling against the fleet's bare-verb convention.
- **seedgo's `--help` names the whole command surface** (devpulse, small fix in seedgo's entry point, Patrick 2026-09-06: "do both, they are all related"): the README round had recorded, truthfully, that `--help` stopped at 13 verbs while the branch answers more — `audit-tests`, `test-inventory`, `shadow-cycle`, `permissions`, `inbox_audit` and the `audit pytest_quality` pack all ran and none was named. Docs-only rules kept it a record; those rules ended with the round. The help text now carries the pack under Audit (shadow: scores, gates nothing), a Test Quality section (audit-tests, test-inventory with `--twins`, shadow-cycle run), a Housekeeping section (permissions, inbox_audit), `standards_audit` as the long form, `diagnostics_audit`, and a README section for `readme update/check`; the `Commands:` line lists all 18. Proven by walking every verb the modules claim against the printed help — 17 of 17 present. The two README lines that recorded the gap now record its closing. ruff and format clean.
- **The 211 forged records in the live deletion store were a production bug, not a test bug: the store's location followed the process's cwd, not the deletion's project** (drone owning, DPLAN-0323 tie-up, 2026-09-06): the dispatch said a drone test was writing into `.ai_central/deletions.jsonl`; drone measured and corrected the premise — no drone test ever did (its autouse `_isolate_deletion_log` fixture always held; the three delete-lane files alone leave the store untouched). The forger is ai_mail's `test_dispatch_monitor.py::test_child_inherits_broker_fd` (186 rows carry its tmp_path, the other 25 are xdist workers of the same suite), which starts a real `BrokerDaemon` against a synthetic repo under `tmp_path` and deletes inside it — correctly. The defect is drone's: `record_deletion()` already took a `caller` because the broker authenticates its requester over HMAC and knows the identity better than cwd, but `deletion_log_path()` still resolved the STORE by walking up from cwd, so a daemon constructed with an explicit `repo_root` filed its record against whichever project the process stood in. A broker serving an external repository in production writes into the standing project's ledger the same way. Fix: `deletion_log_path(project_root=None)`, `record_deletion(..., project_root=)`, all five broker call sites pass `self._repo_root`; `AIPASS_DELETION_LOG` still outranks both so a lane naming its own root cannot defeat the test and container seam; `rm` passes nothing and keeps the cwd walk (the operator IS standing in the project). Four tests added inside existing files, three mutants run and killed one clause each. Verified by drone and again by devpulse: drone 1272 + ai_mail's dispatch-monitor suite in one process from the repo root 1448 passed, the live store byte-identical before and after (920 records, sha256 `22411f4e…`); audit 100 on every CI-scored category, ruff, format, pyright clean. drone corrected its own memory (last night's "subprocess does not inherit the env var" was wrong). **The 211 records still stand** — cleanup is Patrick's ruling; drone's recommendation, and devpulse's, is to annotate the incident in the ledger and delete nothing. The store had grown 916 → 920 since last night on four real @backup rm-lane records, not tests.
- **The skills CI 3.10 hang: the suspend tests patched the stdlib clock for the whole process** (skills owning, DPLAN-0323 tie-up, 2026-09-06): `patch("...base_bot.time.time")` cannot fake a clock safely because `base_bot.time` IS the stdlib module — with the suspend tests' fake epoch of 1000.0, any deadline another thread had already captured read ~56 years away and that thread waited forever; measured as the 22-minute hang on the Linux 3.10 leg (run 33941446687, 2026-09-04). Cure is a seam, not an anchored fake: `from time import time as _now` in `base_bot.py` (an import alias, not a module constant, so seedgo's naming check has nothing to say), all 32 wall-clock reads moved to `_now()`, 22 patch sites in `test_suspend.py` and one in `test_network_backoff.py` repointed; zero `base_bot.time.time` patches remain. Proof measured both ways with one pre-captured deadline: through the seam, stdlib `time.time()` is untouched and the deadline is still 30 s away; through the old global patch, the same deadline is 56.7 years away. Verified: skills 1419 passed in the CI shape (`-n auto --dist loadscope`) and serial by skills, 1419 passed again from the repo root by devpulse; audit 100 on every CI-scored category; ruff and format clean. **Deliberately not done, queued for skills:** `time.sleep` is still patched process-globally by three test files (~35 sites) — same class, milder (a busy loop, not a hang), not what hung CI; a `_sleep` seam beside `_now` closes it the same way.
- **devpulse's last refusal that exited 0, its hardcoded `--version`, and canary's dead bypass row** (devpulse, FPLAN-0490 tie-up, 2026-09-06): `watchdog cancel <unknown>` printed `FAILED … handle not found` and returned success — the one refusal left in the branch that did not go through `error()`; it now does and exits 2. `--version` printed `devpulse 1.0.0` against a `1.0.1` file header with no constant between them; one `VERSION` (1.0.2) now, header in step. canary's `.seedgo/bypass.json` still excused `tests/test_scaffold.py` for the architecture standard — that file has lived in `tests/.archive/` since the sweep, so the row excused nothing; removed, list empty. Verified: devpulse 569 passed / 3 skipped, devpulse and canary audits 100 on every category, both refusals proven by exit code.
- **canary and aipass conftests set the `AIPASS_TEST_LOG_DIR` seam at import, not only per test** (devpulse, DPLAN-0323 tie-up, `3f603fc8`, 2026-09-06): canary's README pass measured it — from the repo root under `-c pyproject.toml --rootdir=.` the repo-root conftest guard refuses to import a branch's json shim while the seam is unset, so canary gave 61 errors and aipass 1081, and both passed in CI only because a sibling branch's conftest had already set the variable in the single-process fleet run. Sixteen branches already set it at module import; these two set it inside the autouse fixture only. Same four-line block added to both, per-test redirect fixtures untouched. Verified: canary + aipass together from the repo root under the pyproject rootdir, 1142 passed / 0 errors (was 1142 errors).
- **`memory_pool_auto_processed` fires again, from the detached child's completion point** (memory 1.1.0 + a trigger docstring, `755711b5`, 2026-09-06): trigger's README pass found the event had a registered handler and zero firers fleet-wide — DPLAN-0294 phase 1b detached auto-process into a child process and the fire went with the inline call it replaced, so a vectorise or rollover failure inside the child was visible only as counters nothing reads. hooks refused to fire it at the spawn site (a PID is not a completion) and routed it to memory, who put `_fire_completion` in `run_once()` — the only process present when the work ends — firing on both outcomes so the handler can turn `success: False` into `error_detected` (the medic path); a declined run does not fire, the lock holder announces its own. trigger's `memory_pool.py` gains a docstring publishing the status vocabulary and the registered-citizen rule, no code path touched. Existing test extended, no new file (gate off). Verified: memory 1582 passed / 5 skipped, trigger 1057 passed. Built off-plan on the docs-only night (recorded in FPLAN-0490) and landed on Patrick's "tie up all loose ends".
- **`aipass/shared/json_handler.py` retires — the last file of the old json lineage leaves the tree** (aipass, FPLAN-0489 / DPLAN-0325 phase 5, devpulse landing, 2026-09-04): moved to `shared/.archive/` after measuring zero production importers fleet-wide; the other four shared modules stay (22 production imports, bootstrap's constraint). `tests/test_json_durability.py` archived with its subject — its one remaining test pinned `_replace_with_retry` routing on the retiring module and was the ONLY live `monkeypatch.setattr` on a json internal in aipass's tree (finding m clean after). Sole-carriership measured before archiving (finding l): the file carried three checker items, every one also carried by the conftest and three or more other files — nothing dropped, Test_Quality 100 before and after. `test_shared_bootstrap_safety.py` keeps the four-module version with no json leg (prax owns the json stdlib scan since FPLAN-0485). Bypass 25 → 24 (the shared file's `.unlink()` trigger row goes with the file). canary's dead-cwd probe drops its preload of the shared handler (devpulse; 29 pass, checklist clean). Fleet grep for a live import of the shared module outside `.archive/`: **0** — seedgo's `json_handler_content.py:41` still shows it in a dim example string and `json_handler.md:23` still calls it "retiring"; both seedgo's lines, queued for its next session. Verified by devpulse: aipass + canary + contract in one process from the repo root 1750 passed; aipass audit 100; ruff, format, pyright clean. **Flagged by aipass, pre-existing and not a regression:** from the `src/aipass` rootdir the local `aipass/` directory shadows the installed package and four subprocess-based tests (two dead-cwd probes, bootstrap safety, the setup.sh trust enroll) cannot resolve `aipass.aipass`/`aipass.hooks` — proven by restoring the archived files and getting the identical four; that rootdir was never green for those four. With this, DPLAN-0325's sweep is complete: eighteen branches on one byte-identical shim over prax's service, the shared module gone, every divergence table empty, the checkers judging the shim by hash.
- **api moves to the one json shim — 18 of 18, the fleet is on one json implementation; every divergence table empty; the checkers judge the shim by hash** (seedgo owning DPLAN-0325 pair 6 + FPLAN-0486 B sections 2 and 4, devpulse landing, 2026-09-04): shim byte-identical (sha256 `3456b766…`, mode 664), placed before archiving with drone proven alive (h); three test files to `tests/.archive/` — all three carried a discovery block that hunts the handler for `API_JSON_DIR`/`JSON_DIR` and skips ITSELF at module level when it finds none, so on the shim they would have gone dormant and read as coverage. Dead surface measured fleet-wide and retired with the handler (i): `atomic_create_json` zero production callers, `API_ROOT` zero importers, four privates only in api's own archived tests. Token scan 28/28 before and after, one carrier moved (l). api's autouse fixture (conftest 63-74/121) hunted the same `JSON_DIR` names — on the shim it would have done NOTHING, silently, letting 1561 tests write into the real `api_json/`; replaced with the `AIPASS_TEST_LOG_DIR` seam. Five `monkeypatch.setattr` sites on shim internals cured (m); the dead-cwd caller probe now measures THROUGH `log_operation`, reading the answer off the written `*_log.json` name. **Unpredicted:** `test_host_perf.py`'s caller-detection section compared a `sys._getframe(2)` fetch against an `inspect.stack()` walk the one service never had — no subject — but two of its five tests were the FLEET'S ONLY carriers of "an underscore-private caller is unknown" and "an unfetchable frame is unknown, not a crash"; both moved INTO seedgo's contract (`TestTheAuditTrailNamesWhoItCan`, mutation-checked red both ways), the section archived as a commented verbatim copy with a record left in place. **B2:** `SAVE_JSON_MISSING_PARENT[api]` XPASSed strictly, row retired, live xfails 1 → 0, all eight divergence tables empty; `increment_counter`/`update_data_metrics` contract tests retired by subject gone (18 skipped / 0 measurements, zero definitions fleet-wide). Contract 614 passed / 0 skipped / 0 xfailed. `EXHAUSTED_WRITE` 18/0, every branch raising the service's `WriteFailed`; `RETRY_IMPLEMENTATIONS` 6 → 5 with no branch handler left on it. **B4 applied:** `_has_service_import`/`_has_shared_import`/`_has_triplet_surface` and their three token tables deleted — the shim is accepted by hash only; `json_structure_check:651` shares the same `_is_canonical_shim` test (finding (a): with the marker removed and no hash substituted, all eighteen AND the template drop 100 → 75; measured before applying, 18/18 accepted by hash, zero drops, identity pinned so the two standards cannot drift apart). Four of seedgo's checker tests now use the REAL canonical bytes read from the citizen template and hash-verified rather than hand-written lookalikes. **Encapsulation derivation cured** (the pair-5 CI red, species (o)): the old `_infrastructure_handlers` returned the EMPTY SET for all eighteen branches after the sweep — blind, not wrong; daemon was only the first to show it. New basis reads what a module PUBLISHES: a top-level `apps/handlers/*.py` defining `module_file`/`find_repo_root`/`source_root`/`resolved_file` IS the branch's resolution shim (fifteen found; spawn's `passport_migration.py` correctly not). A leaf test ("imports nothing from its own apps/") was measured and rejected — it blessed nine unrelated handlers. daemon's `daemon_wakeup.py` passes with no bypass row, so the row landed in `a6956b0f` came back out (23 → 22). Seven tests pin the new derivation including a red-first pin on the exact swept-branch shape. Evidence: api 1561 both rootdirs, composed with the contract in one process 2175 / 0 / 0 (devpulse re-ran: 2175); host suite 1005, the running 8787 server untouched; seedgo 3732 / 5 pre-existing skips (devpulse re-ran: same); fleet audit full re-scan by devpulse 18/18 on every CI-scored category, six branches at Overall 99 on their own `.trinity` hygiene only; ruff + format + pyright clean. Attributed to no one: `api/tests/.archive/test_scaffold.py` is named `test_*.py` inside `.archive/` — the shape the write gate refuses; not collected, a naming inconsistency.
- **commons and daemon move to the one json shim — 17 of 18, and the composed CI shape caught a leak a single suite would have shipped** (seedgo owning DPLAN-0325 pair 5 / FPLAN-0488, devpulse landing, 2026-09-04): Patrick's "ok proceed" first landed the three dead-cwd probe-hardening test files that had blocked this pair (`c9e8e92e`: commons docstring, daemon's `ARM_PATHLIB_ACCESSOR` so `PROBE_VACUOUS` is a failure on every interpreter, api's `ELSEWHERE` absolute under the temp dir). Then the sweep: shim byte-identical to prax's in both trees (sha256 `3456b766…`, mode 664), placed BEFORE anything was archived and drone proven alive after each step (finding h). Seven test files moved to `tests/.archive/deleted_2026-09-04_*.py`, two old handlers to `apps/handlers/json/.archive/`. `increment_counter`/`update_data_metrics` measured at ZERO production callers in either branch and retired with the old handler (i); commons's bypass row for exactly those two removed (75 → 74). **The token scan was measured before archiving and it mattered on daemon (l):** archiving its five stamp files cost `init_provisioning/no_overwrite` and `return_type_contracts/command_returns_bool` (Test_Quality 100 → 93) — cured with real claims in tests that run, not tokens: `handle_command` genuinely returns bool (its old pin lived in a file that had stopped running behind a module-level skip), and daemon's actual no-clobber contract is in `runstate` — a load that returned the empty default for an EXISTING file would let the next whole-structure save erase every other job's `last_run` and re-fire the scheduler; pinned as a read-modify-write that leaves unrelated history intact. A checker change that would have cured daemon by excusing thirteen branches was measured and rejected. **Patch-under-patch (m) caught a real one, seedgo's own:** commons's reimport test kept a save/restore around `importlib.reload` on a shim name — the reload rebinds all nine names to a fresh handle, so restoring one left the module holding two handles; both suites green alone, `binds_one_handle[commons]` red only in the composed run. Restore dropped, invariant pinned. Finding 4g (bespoke-conftest prax stub) did NOT apply to either branch and is reported as such. Contract: commons's `SAVE_JSON_MISSING_PARENT` and `GET_JSON_PATH_TYPE` rows XPASSed strictly and retired (3 → 1 live xfail, api alone; `GET_JSON_PATH_TYPE` table gone); commons's own `test_json_path_returns_path_like` had asserted `.endswith(".json")` — the divergence written from the inside — and now asserts the Path. `UNKNOWN_TYPE_NOT_REFUSED` test retired: 18 skipped, 0 measurements, the concept lives in the public `VALIDATION_MATRIX`. Counts: `EXHAUSTED_WRITE` composition all seventeen raise `WriteFailed`, api alone returns False; `RETRY_IMPLEMENTATIONS` 8 → 6. Evidence: commons 487 / daemon 495 both rootdirs; composed CI shape 1101 and 1109 passed / 1 xfailed; seedgo 3730 / 1 xfailed; fleet Test_Quality 18/18 at 100; ruff + format + pyright clean on all nine touched files. daemon audits Overall 99 on trinity hygiene only (its own `local.json` session order; not CI-scored). B section 4 still staged: api alone would red, and finding (a) grew — deleting `SERVICE_IMPORT_MARKER` without the hash test costs seventeen branches 25 points each. **CI then reddened on the audit alone (`a6956b0f` fixes it), a new species for the last pair:** seedgo's `encapsulation_check` derives the handlers a branch may import anywhere from what the branch's OWN `json_handler` imports (their 2026-08-31 rule that made `module_root` importable by construction) — the one fleet shim imports nothing under `handlers/`, so that derivation is empty in every swept branch, and daemon, the only branch whose entry-point script imports `module_root` directly, scored 66% on `daemon_wakeup.py:40` the moment its old handler left. Documented bypass row on daemon until seedgo re-bases the derivation on the property rather than on the shim's imports; daemon's README test count corrected 559 → 473 (five stamp files archived).
- **`room create --help` no longer creates a room named `--help`** (commons, 2026-09-04): the room router now checks the sub-arguments for `--help`/`-h` before dispatching to ANY verb and prints that verb's usage instead, so the same class of bug cannot recur on `list`/`join`/`leave`; pinned by a router-level test that asserts usage is printed and nothing is created. The stray `--help` room and its auto-subscription row were removed from `commons.db` (`room list` is clean; `boardroom-json-service` intact). A real `room delete`/`archive` verb (creator-only, empty-room check) is backlogged as its own design surface. Verified by devpulse before commit: 15/15 room tests, ruff + format clean, audit 100.
- **The fleet json service stops narrowing every document to 0600, refuses NaN, and prax's watcher no longer stalls the first log line of a process** (prax, DPLAN-0325 post-sweep bundle, 2026-09-04): (1) `json_service._stage` staged through `NamedTemporaryFile` (hardcoded 0600) and `os.replace` carried the STAGED mode onto the target, so every service write narrowed a 664 document to 600, fleet-wide (skills found it on pair 2). Now the staged file is created with `os.open(..., O_CREAT|O_EXCL, 0o666)` so the KERNEL applies the umask — byte-for-byte what `open(path, "w")` gives a new document, with no `os.umask()` round-trip that would briefly widen the umask for prax's watchdog and display threads — and an EXISTING document keeps its own mode via `fchmod` on the fresh fd (`_current_mode()` stats the target; Windows guarded by `hasattr(os, "fchmod")`). Pinned: 664/644/600/640 all come back exactly; a fresh document is compared against a reference file made by a plain `open()` in the same directory in the same breath, never against the number 0664. (2) `allow_nan=False` on the service's `json.dump`: nan/inf/-inf now raise json's own `ValueError` (deliberately not wrapped — the message already names the fault and nothing needs to tell it from the circular-reference case), pinned red-first, plus pins that a refused write leaves the live document byte-identical with no staged temp behind, and that `log_operation` still answers False rather than raising on the monitor's threads. Red-first proof: the pre-change service under the new pins fails 10 of 11; the eleventh is the 600 control. (3) The banked `watcher.py:159` TOCTOU named no code that exists in any version on disk; the real exists-then-open was `monitoring/file_watcher_integration.py:94` (spawn rewrites `AIPASS_REGISTRY.json` atomically, so the checked inode can be gone by the open) — now an open with `FileNotFoundError` handled at the open itself, and the test re-pointed at the open asserting the ABSENCE warning (it had stubbed `exists()` and would have passed a loader with no guard). ~20 more sites of the same shape in prax (pid_cache, agent_status_writer, dashboard, template_pusher, registry/load) are a sweep decision, not done here. (4) **Measured, 1605 directories: `start_file_watcher()` alone 0.119 s; with ONE busy thread 13.949 s (117×)** — watchdog installs one inotify watch per directory, each syscall drops the GIL and must win it back from a thread that never blocks, up to a full switch interval per directory; the caller paying was `SystemLogger._ensure_watcher` on the FIRST log line of the process. Neither banked cure works ("yield between files" adds handoffs; "bound the scan" is what the live monitor already does, but for discovery it stops seeing the 112 of 195 registered modules outside `apps/`). Cure: `start_file_watcher_in_background()` — same walk on a thread nobody joins; caller blocked 5.72 ms under the same contention, the walk finishes 4.5 s later; the synchronous door stays for `lifecycle.run_initialization` and both are serialised on one lock so overlapping starts install exactly one observer (pinned, including the inotify-limit `OSError` logged rather than raised on an unjoined thread). Caught by the contract mid-build: a first cut named staged files with `time.time_ns()` and seedgo's suite stubs `time` for the bounded retry — 45 reds across 15 branches — staged names are pid + `itertools.count()` now. Evidence: 1503 passed both rootdirs (was 1488), contract 623 passed / 3 xfailed unchanged, ruff + format clean, audit 100 on every category (Silent_Catch 98 → 100 by returning `_current_mode()`'s not-found branch as a value). Flagged, attributed to no one: `prax_registry.json` still lists five long-deleted `api/_prove_*`/`_mutate`/`_win_*` probe files from 2026-08-18 — discovery adds and never prunes.
- **skills's `SAVE_JSON_MISSING_PARENT` divergence row retired the moment its strict xfail turned red on CI** (devpulse landing the pair-2 sweep, DPLAN-0325 / FPLAN-0488, 2026-09-03): the sweep gave skills the service's staged write, which creates the missing parent, so seedgo's `test_save_json_persists_into_a_document_directory_that_does_not_exist_yet[skills]` XPASSed(strict) and reddened the board (1 failed / 20887 passed). Removed skills from `SAVE_JSON_MISSING_PARENT` per seedgo's own standing rule — delete a divergence row only when it turns red, never pre-emptively — leaving five rows. Confirms the divergence tables must be emptied per pair as each sweep lands, not deferred to the last pair.
- **CI's 3.10 and 3.11 legs stopped counting setuptools' startup import as a service import** (devpulse for prax, DPLAN-0325, 2026-09-03 04:30, 94ab45e4): prax's cold-footprint probe found `_distutils_hack` on the 3.10/3.11 runners - setuptools' `distutils-precedence.pth` imports it at interpreter startup wherever setuptools is installed, and 3.12+ venvs ship without it. Added to `_INTERPRETER_NOISE` beside `__main__` and `sitecustomize`; the service still imports six aipass modules and nothing third-party.
- **The repo-root test guard no longer wraps a one-source shim's `log_operation`** (devpulse, DPLAN-0325, 2026-09-03 03:20): the first repo-root CI run after prax landed showed 2 failures in 20857 on every leg. One was `conftest.py` at the repo root — the autouse guard that wraps every `aipass.*json_handler` module's `log_operation` during each test so xdist workers never race on live `<branch>_json` files. A DPLAN-0325 shim binds the service's bound method and must never be wrapped (frame-2 caller attribution; prax's own bind-not-wrap pin went red on the wrapper). The guard now leaves a module alone when its `log_operation` is a bound method of `json_service.JsonHandle` — the service redirects per call through `AIPASS_TEST_LOG_DIR` — and raises if that seam is unset in such a run, rather than silently skipping writes. Verified: prax's 72 pass from the repo-root rootdir. The other failure is seedgo's contract redirect test not yet knowing the shim (FPLAN-0486 part A, in flight).
- **ai_mail's mail store no longer truncates the live document on write** (ai_mail, from FPLAN-0481's finding, 2026-09-02): `save_json` in `ai_mail/apps/handlers/json_utils/json_handler.py` wrote with `open(path, "w")` + `json.dump` — the truncation happens when the file is OPENED, so any failure during the dump destroyed the live document while `save_json` answered False (the caller heard "did not save"; the truth was "your previous document is gone too"). Reproduced on the real handler before the cure: a 101-byte inbox holding one message became 83 bytes of unparseable text. Cure: `_atomic_write_json` (mkstemp in the target's own directory, `os.fdopen`, dump, flush + fsync, then `_replace_with_retry` copied verbatim with the fleet's constants — 40 × 0.005 s — so seedgo's helper contract holds for a sixteenth implementation; temp removed on any failure, `BaseException` so an interrupt cannot strand it). Disposition on an exhausted retry: the helper raises like the fleet's, `save_json` catches and still answers False. The one deviation from drone's reference, stated: the fsync, because `os.replace` orders the rename, not the data. Beyond the brief: the source guard convicted a SECOND truncating write in `ensure_json_exists` — the self-healing path, which fires exactly when the document is already suspect — cured in the same change. Two pins in the EXISTING `tests/test_json_handler.py` (an AST source guard with negative and positive controls — the regex version went red on the docstring explaining the defect; and save_json reaches the helper, counted on the helper not the syscall) plus 4/4 mutants killed. Evidence: 1449 passed both rootdirs, seedgo contract `-k ai_mail` 30 passed / 8 skipped with the six helper behaviours running for ai_mail for the first time, checklist 34/34 + 23/23, ruff + pyright clean, audit 100. Seedgo removed ai_mail's six xfail rows from its tables while both were awake. Flagged for @hooks, not chased: the test-write gate read a compound `cd <root> && pytest src/...` as a NEW test file because it resolved the pytest argument against the branch cwd (path doubled).
- **Twins container derived from the source tree, not the registry** (seedgo, FPLAN-0474, 2026-09-02): PR #751 was red on every board since the phase 4 commit — one test, all four Python legs plus coverage. `inventory._branch_container` took the common parent of the registry's branch paths, and `AIPASS_REGISTRY.json` is machine-local and gitignored, so on any fresh checkout discovery answered nothing and the container fell back to the repo root, publishing "0 twins over 0 branches" as a success — the exact defect the pin was written for. Green on developer machines only because the registry exists there. Cure: the container is read off the imported `aipass` package's own directory (a fallback no broader than the happy path), and it raises rather than guessing the repo root. The existing pin stays; a second pin in the same class asserts the registry-less world and was mutation-verified against the restored pre-fix code (the old pin passes on it locally, the new one fails). Banked for the pack: a resolver whose fallback path is broader than its happy path is statically detectable.
- **The audit artifact and the incremental cache are scoped by pack** (seedgo, FPLAN-0478, 2026-09-02): the two defects reported above are cured in one change set. `default_artifact_path` gains a `pack` argument on the same rule bypass mode already used - `audit pytest_quality` now writes `last_audit_pack_pytest_quality.json` and `.seedgo/last_audit.json` keeps the 47-standard aipass record (proven by re-running the exact clobbering command: fleet-record mtime unchanged before and after). The inline cache key became `branch_audit.cache_key_for(branch, pack_path, no_bypass)` and folds the pack in the way the stamp already did, so alternating `audit aipass` and `audit pytest_quality` no longer evicts each other into a cold fleet scan. Counter-arms pinned on purpose: the `aipass` pack keeps the bare artifact name and the bare cache key, because renaming the compliance record or suffixing every key would have fixed the collision by breaking what it endangered. Six pins, red first, all in the two existing test files; the full suite also caught one stale expectation (`test_delete_file_drops_from_cache_and_output` read the cache by a hardcoded bare name) which now derives the key through the helper. Owner evidence: 3353 passed / 35 skipped / 10 xfailed both rootdirs, checklist 34/34 and 23/23, ruff and pyright clean. Devpulse re-ran the two touched files: 89 passed, ruff and format clean, pyright 0.

### Removed
- **DPLAN-0323 sealed — v4 `test_quality` leaves the gate, the judged rows go, the shim-pin twins fold into the contract, and the fleet still audits 100 on 46** (devpulse orchestrating FPLAN-0491, seedgo owning the pack and the contract, three opus subs on the walk, night of 2026-09-07, Patrick 01:16: "seal the deal here. and old test not needed now can all be archived. so we can actually run the new tests setup"): (1) the v4 checker, its content module and its `.md` moved to `seedgo/apps/handlers/aipass_standards/.archive/`; the aipass pack is 45 standards, the audit consults 46 (45 + diagnostics), and CI's `EXPECTED_STANDARDS` tripwire moves 47 → 46 in the same commit, as its own comment demands. No checker declares `APPLIES_TO = tests` any more — the substring scan that made the json sweep add four `test_cli_routing.py` files just to keep its items covered is gone, and its own tests (`test_aipass_standards.py` −8, `test_checkers_batch4.py` −3, `test_applicability.py` 1 rewritten) went with it. (2) The 42 rows the 2026-09-05 contested band judged DELETE are out: memory 18 (the three parked symbolic files whole — `test_symbolic.py`, `test_symbolic_cli.py`, `test_symbolic_module.py` — plus one in `test_rollover_pipeline.py`), prax 10 across six files, trigger 4, hooks 2, spawn 2, devpulse 1, flow 1, skills 1, seedgo 3; functions removed in place (git is their archive), whole files to `tests/.archive/deleted_2026-09-07_*`, every file's collection count checked before and after so the difference equals the rows and nothing else. (3) The 89 shim-pin twins (six identities stamped per branch) are carried once: two new parametrised tests in `seedgo/tests/test_json_handler_contract.py` — every shipped shim is byte-identical to the pinned canonical, and a migrated shim's exceptions are the service's own — take the contract file 608 → 644 collected; thirteen `tests/test_json_handler.py` files moved whole to `.archive/` (ai_mail, aipass, backup, canary, cli, devpulse, drone, flow, hooks, memory, seedgo, skills, trigger), prax's thinned 61 → 59 and spawn's 15 → 12 because those two carry tests of their own beside the stamp. Spawn's citizen template still ships the six-test file to every newborn — held as a ruling, not touched. (4) seedgo's `test_content_functions.py` merged 37 twin pairs into 37 tests, mutation-checked at the merge; `test_readme_update.py` 16 → 14, `test_standards_audit.py` 44 → 43. Measured after: seedgo 3087 → 3030 test functions (3695 passed, 5 skipped from the repo root), memory 1580 → 1431 across 42 files (1567 passed, 2 skipped — the two `allow_module_level` skips are what is left of the parked tier), canary 33 → 27 (47 passed); seedgo's composed 14-branch run 14,864 passed / 5 skipped / 0 failed; fleet audit prints 46 consulted for all 18 with every CI-scored category at 100 (memory dipped to 99 on README count drift the walk caused and is back at 100 with the counts re-measured). The v5 pack (`pytest_quality`, 11 AST rules) still runs on demand and scores the fleet; it gates nothing, by Patrick's 09-01 cadence ruling. Not in this landing: the 118 MERGE rows (second pass, per owner), v5 as a per-commit gate, the mutation run — each its own ruling.
- **Phase 7 deletion walk, slice 4 — the json_handler template stamp gone from five branches: 183 tests removed, 12 kept as v4 carriers, every branch still at 100** (devpulse, DPLAN-0323 / FPLAN-0483, Patrick's standing go 2026-09-02): the 195 copies seedgo judged SUBSUMED by the contract suite (994465a5) removed from `tests/test_json_handler.py` in api, drone, seedgo and spawn and from devpulse's `tests/test_json_handler_template.py`, each block moved verbatim to the branch's `tests/.archive/`; dead helpers (`_get_default_for_type`, `_has_default_factory`, `_default_factory_raises_on_unknown`), spawn's orphaned skip markers and unused imports dropped with them. The re-audit then showed what the dossier's sole-carrier measure never covered: in devpulse and spawn the stamp copies were the last text in `tests/` carrying the v4 json_handler substrings (devpulse 100 → 80: default factory, validate, get_path, ensure_exists, load, ensure_module, plus the config-key, data-key and dict-return items; spawn 100 → 90: validate, get_path, ensure_exists, load, ensure_module), while api, drone and seedgo carry them in other files. Seven copies went back into devpulse (JH-001 and JH-002 re-pointed at devpulse's own `_default_config` / `_default_data`, the cross-branch resolver having gone with the stamp) and five into spawn, each in a labelled "v4 sole carriers — SUBSUMED, kept for the gate" block that goes the day v5 replaces v4 — the same standing as the dossier's 24. Net: 183 removed (api 38, drone 40, seedgo 38, spawn 34, devpulse 33); remainders api 1 / drone 13 / seedgo 14 / spawn 7 / devpulse 8 — 226 test functions in the five files before, 43 after (the commit message of e95ec835 says 184: an arithmetic slip, the file counts are the truth). Ground truth: seedgo audit `test_quality` 100 on all five after the restore; 43 tests pass across the five files; all five branches collect clean; ruff + format clean. Phase 7 totals: 282 tests removed over four slices (38 + 37 + 24 + 183).
- **Phase 7 deletion walk, slice 3 — the last 24 durability twins gone, four files with them, every branch still at 100** (devpulse, DPLAN-0323, Patrick's standing "keep powering on" 2026-09-02): the four write-site identities seedgo's FPLAN-0481 contracts subsume — `test_atomic_write_routes_through_the_replace_helper` (5 copies), `test_exhausted_retry_leaves_the_original_intact_and_cleans_the_temp` (6), `test_save_survives_a_transient_sharing_violation` (6), `test_concurrent_writers_never_expose_a_torn_document` (7) — removed from `tests/test_json_durability.py` in aipass, backup, commons, devpulse, drone, flow and prax. In backup, devpulse, drone and flow nothing but fixtures remained after slices 2 and 3, so those four files went whole (moved to `tests/.archive/` under the archive ruling). aipass keeps its `write_json` routing pin (a sole carrier by name, not in the 24), commons keeps its exhaustion and source-guard tests, prax keeps the `AIPASS_TEST_LOG_DIR` seam class — each with a docstring pointing at the contract, dead helpers and imports dropped. Ground truth: seedgo audit re-run on all seven, `test_quality` 100 → 100 everywhere; 24 tests pass across the three edited files; all seven branches collect clean; ruff + format clean. Phase 7 totals so far: 99 tests removed (38 + 37 + 24), every one archived verbatim in its branch's `tests/.archive/`.
- **Phase 7 deletion walk, slice 2 — the 37 durability twins gone, every branch still at 100** (devpulse, DPLAN-0323, Patrick's "keep powering on" 2026-09-02 16:57): the six `_replace_with_retry` tests stamped into `tests/test_json_durability.py` in aipass, backup, devpulse, drone, flow and prax (36) plus commons's `test_retry_waits_between_attempts` (1) — every one now pinned by the durability contract in seedgo's contract suite (above), against all 14 implementations rather than one each. The three rows the dossier counted that seedgo showed are real tests stay: commons's bounded-retry test drives `save_json` to exhaustion, and spawn's two exercise `atomic_write_text` with assertions the twins never made. Same ruling as slice 1: each removed block moved verbatim to the branch's `tests/.archive/` (gitignored disposal), `errno` import dropped where nothing else used it. Verified: 7 files ruff + format clean, the seven suites pass, all seven branches collect clean, v4 audit 100 on each. The write-site durability tests in those files stay — they are slice 3's subject (FPLAN-0481, seedgo, in flight).
- **Phase 7 deletion walk, slice 1 — 38 tests gone, every branch still at 100** (devpulse, DPLAN-0323, Patrick's go 2026-09-02 10:38). The first deletions of the campaign, all from the deletion dossier's recommended tier: (1) `tests/test_scaffold.py` in all 17 branches that carried it — one byte-identical smoke test stamped at birth, which in 8 of the 17 had done nothing but skip itself since the branch wrote its own conftest; spawn's update path never re-adds a deleted scaffold test, and only newborns get one from the citizen template (which now carries canary's inspect.stack pin, so the template stays). (2) `test_validate_valid_config` / `test_validate_valid_data` in api, devpulse, drone, seedgo, skills and spawn — 12 template stamps of one happy-path case, subsumed by seedgo's contract suite, which runs a ten-case matrix against every branch's implementation. (3) the two zero-assertion `test_reimport_after_mock` copies in drone and seedgo, the campaign's smoking gun: their only effect was placing the substring `importlib.reload` in a v4-scanned file. (4) devpulse's 7 hook-engine POC functions, gitignored return-value tests pytest silently discarded. Per Patrick's ruling every removed text was moved to the branch's `tests/.archive/` (gitignored disposal, local only; git history is the durable record) — measured before the move that pytest never descends into dot-dirs (612 collected before and after a probe copy) and v4 scans only files directly inside `tests/`. Re-measured this morning on fresh copies of all 17 branches with the whole slice applied: `test_quality` 100 → 100 everywhere; the real fleet audit after the move reads 100 on every branch for every standard CI scores (the four 99s are `trinity`, machine-local memory files CI never sees). 249 tests pass in the six edited files; all 17 branches collect clean. Not in this slice: the 38 `test_json_durability` copies wait for their parametrized replacement (phase 4), and the one parked row stays.

### Added
- **v4 test_quality stops charging a branch for not testing what it does not have** (seedgo, DPLAN-0325 pair 3 / FPLAN-0486, 2026-09-03 23:30): @canary's swept tree audited `Test_Quality` **87**, missing `error_resilience/corrupt_json`, `error_resilience/empty_file`, `return_type_contracts/paths_return_path` and `init_provisioning/no_overwrite` — all four carried only by its archived DPLAN-0059 stamp, so the obvious move was to extend the part B retirement by four. **The measurement refused it:** 16 of 18 branches earn each of these four from tests with nothing to do with the json handler (ai_mail's `test_notify.py`, aipass's `test_structure_scan.py`, api's `test_secrets.py`; `empty_file` is earned that way by 17 of 18). Retiring them fleet-wide would have deleted four live, earned items from sixteen branches to cure one — scoring the fleet down to its thinnest member, the exact inverse of part B where the stamps genuinely were the only carriers anywhere. What canary actually is, is a branch with **no subject**: its whole production surface is `apps/canary.py` plus a handlers `__init__` (9 files, three of them empty), and it parses no JSON, returns no `Path` and writes no file. Neither does **@cli**, whose only file-touching code is the handler it has not swept yet — cli scores these four today from its json tests and would hit the identical wall on its own sweep. The defect was never the tokens; it was asking every branch for coverage of something two of them do not do. **Cure: item applicability (5.1.0).** `ITEM_SUBJECT_PROBES` maps an item to the subject it measures, looked for in the branch's own `apps/` code; an item the branch ships no subject for leaves the numerator AND the denominator for that branch, so it neither convicts nor flatters. The branch's `json_handler.py` is excluded from the probe on purpose — it is the fleet's file, byte-identical everywhere, and counting it would hand every branch every subject and make the gate meaningless. The exclusion is printed in the audit line (`4 of 31 not applicable to this branch (…)`), because a denominator that changes per branch has to be readable from the outside. **Result: canary 87 → 100, cli 100 → 100 and immunised before its own sweep, the other sixteen unchanged with nothing excluded, none down. `TOTAL_ITEMS` stays 31 — nothing retired, nothing re-scoped, 0 of the 4.** Known and accepted: a branch could shed an item by deleting production code, which is a visible act with its own reviewers, where charging a branch for not testing what it does not have is the failure actually happening. For pairs 4–7 this likely removes the need to extend per pair: a missing token now gets one of two honest answers — the stamp was its only carrier fleet-wide (retire, as in part B) or the branch ships no subject (exclude, as here) — and only a branch that ships the subject and never tested it stays red, which is the one case that should. Evidence: 3790 passed / 70 skipped / 8 xfailed identically from both rootdirs, 4 new pins (60 → 64) including the red-first negative that a branch which DOES parse JSON is still charged, ruff + format + pyright clean, checklist 34/34. `test_json_handler_contract.py` deliberately untouched — devpulse holds an uncommitted pair-3 edit there.
- **The v4 test_quality token union retires with the handler it was grepping for, and json_structure learns to recognise a branch-owned logging seam** (seedgo, DPLAN-0325 / FPLAN-0486 part B sections 1 + 3, 2026-09-03 16:30): four sweeps (devpulse, backup, hooks, aipass) were done in-tree but HELD, because archiving the DPLAN-0059 stamp files drops items CI gates at 100 — devpulse 88, aipass 88, backup 94, hooks 96. The part A blast table had counted the `json_handler` category only; measured here, the stamps were the sole carrier for items in FIVE categories, so retiring one leaves devpulse at 38/43 = 88 and still red. **20 items retired by subject, 2 re-scoped, `TOTAL_ITEMS` 51 → 31, and all 18 branches land at 100 with four moving up and none down.** Retired: the whole `json_handler` (8), `exception_contracts` (3) and `data_structure_contracts` (3) categories, plus `conftest_fixtures/mock_json_handler` (the fixture conftest v3.0.0 deletes), `return_type_contracts/load_correct_type` and `ensure_returns_bool`, `init_provisioning/returns_dict`, and `infrastructure_mocking/sys_modules_mock` + `reimport_after_mock` — the stamp's own technique of stubbing `sys.modules` and reloading the handler, when there is no shim to reload. The principle: v4 is a per-branch TEXT scan and DPLAN-0325 moved the behaviour and its tests into one service plus seedgo's contract suite, which a per-branch scan cannot see; retiring costs nobody because numerator and denominator move together. Re-scoped rather than retired, because both were measuring a spelling instead of a concept: `error_resilience/empty_file` += `test_empty` (@aipass has `test_empty_project`, `test_empty_branch_name_ignored`, `test_empty_path_flagged` and lost only the stamp) and `return_type_contracts/command_returns_bool` += `", bool)"` (@aipass asserts `isinstance(result["ok"], bool)`, which the literal token missed for being subscripted) — each measured alone (93 → 96 → 96 → 100), and a third candidate `empty_string` was measured to catch nothing and dropped. **json_structure 3.3.0 rules on backup's seam**: the spec took backup's 67 audit calls off the shim to `apps/handlers/audit/trail.py` on `from aipass.prax import append_jsonl`, and the check's two literal tests (`import json_handler`, the substring `json_handler.log_operation`) convicted 41 of backup's 43 files for obeying it. Recognised, not bypassed — a seam is a file that BOTH defines `log_operation` AND builds it on a prax primitive; both conditions, or any module naming a local object `trail` would claim it. Three consequences, all needed: a module importing its branch's seam satisfies both checks together, the seam itself is exempt (the substrate does not log through itself), and seams seed the bootstrap chain so a stdlib-only helper reachable only through the seam (`backup/apps/handlers/path/module_paths.py`) is not left red for an import it must not carry. Measured with the rule on and off over all 1,878 fleet `.py` files: **41 files move, every one upward, none down, all in backup — 41 convicted files to zero, with no bypass**; `trail.py` is the fleet's only seam today. Section 3 counts, each re-measured: exhausted-write split 11/6 → **12/5** (aipass crossed on migration), `RETRY_IMPLEMENTATIONS` 16 → 14 (it did not fall when prax migrated — the helper MOVED into `json_service`), `validate_json_structure` sixteen → **seventeen of eighteen, only ai_mail lacks it**, and the `save_json` convention split is **GONE** — backup's path-addressed form left with its old handler, so all 18 write the three-argument form. Two more divergence rows emptied on the standing rule (only when the strict xfail turns RED): `SAVE_JSON_MISSING_PARENT[hooks]` and `DECLARED_LOG_CAP_IGNORED[aipass]`, leaving 6 and 2. Evidence: 3779 passed / 85 skipped / 12 xfailed identically from both rootdirs, 7 new standards pins (60), ruff + format + pyright clean, checklist 34/34 on both changed standard files. Sections 2 and 4 (the remaining divergence tables, the checker's retirement to hash-only) stay staged for the last sweep pair.
- **seedgo accepts the one shim — four standards had priced the old handler shape into four places, and none of them knew it** (seedgo, DPLAN-0325 / FPLAN-0486 part A, 2026-09-03 03:30): the `json_handler` capability check (1.2.0) gains four accept paths strongest first — the canonical shim by sha256 (`CANONICAL_SHIM_SHA256 = 3456b766…cf0b7`, derived from the pinned spec's section 3 before reading prax's file, then compared: identical), the transitional service-import marker with no branch tokens, the shared-import path and the triplet surface — and the citizen template becomes an audit subject, judged unrendered with `{{BRANCH}}` as its token. The naming check reads a module-level dotted alias (`read_json = _h.read_json`) as an alias, not a lowercase constant. `test_quality`'s `default_factory` markers learn `_default_document` (prax back to 100, 8/8). `json_structure` (3.2.0) stops demanding `Path(__file__).resolve()` of a file that must resolve nothing — it accepts on the same service-import line the capability check reads, one public constant, so the two standards cannot define "the shim" twice; measured over all 1873 fleet `.py` files before and after each rule: 7 files move for naming and 3 for json_structure, every one upward, none down. The contract suite gains the IDENTITY axis (three tests per migrated branch: the bound function is the service's, the handle root is `parents[3]` of the shim, the env var set after import redirects the next call; skips cleanly with the branch named on the 16 not yet migrated) and `redirect_documents` learns the shim — it sets `AIPASS_TEST_LOG_DIR` and leaves `branch_root` real, and `prepared()` asks the implementation's own `get_json_path` where documents land — which cured the one contract failure CI showed on the first repo-root run and six more prax cases. Two divergence rows emptied on the rule "only when the strict xfail turns red": `SAVE_JSON_MISSING_PARENT[prax]`, `DECLARED_LOG_CAP_IGNORED[spawn]`; the exhausted-write split re-measured 11/6. Part B (staged, report-only in `artifacts/reports/DPLAN-0325_part_B_staged.md`): retire the v4 `json_handler` category (51 → 43; it greps `tests/` for eight substrings and would turn 13 of 18 branches red if the sweep lands with it live — same commit as the sweep), empty the remaining tables as their xfails turn red, correct the retry counts and floor, narrow both checks to hash-only. Evidence: 3750 passed / 117 skipped / 14 xfailed both rootdirs, contract file from the repo-root rootdir 622 passed with the safety test green, 14 new standards pins (53), ruff + pyright clean, checklist 34/34 on every changed file and on the shim itself, fleet audit unchanged for anything seedgo changed. The two bypasses the check had been hiding behind (prax's stale "load_template() and json_templates/" entry, spawn's shim entry) are removed in this commit. Banked for @hooks: the test-write gate false-fired on read-only commands four times tonight.
- **The citizen template mints the one shim, and spawn is the first swept branch** (spawn, DPLAN-0325 / FPLAN-0487, 2026-09-03 03:19): template f047 (`templates/citizen/apps/handlers/json/json_handler.py`) is the canonical shim verbatim — no placeholders, rendered equals raw — and spawn verified the hash by extracting section 3 from the pinned spec rather than trusting a number; the template, spawn's own handler and prax's are now the same 1724 bytes. Template tests follow: the conftest (v3.0.0) redirects through `AIPASS_TEST_LOG_DIR` alone and MEASURES its sandbox off the shim's own `get_json_path` instead of spelling the path, the `mock_json_handler` fixture and the shared `JsonHandler` import retire, the template test file (v2.0.0) keeps wiring only — a newborn ships wiring, seedgo's contract pins behaviour once for the fleet. `.spawn/.template_registry.json` regenerated by `drone @spawn regenerate-registry` (f047 `699a7c16…` → `3456b766…`, f050 with it). spawn's own sweep: the old handler and the dead `apps/json_templates/` package archived, the shim ADDED by the real lane (`handle_update(["@spawn", "--apply"])`: Additions 1, Updates 1, Skipped py 11), `_isolate_spawn_json` cured to the env seam, the naming bypass dropped (seedgo's alias rule works), three internals pins archived, `tests/test_json_handler.py` replaced — the DPLAN-0059 universal stamp had skipped itself module-wide the moment `_JSON_DIR` disappeared, taking the five v4 sole carriers with it — and `test_invalid_write_caught` re-pinned against a real unwritable target (its `os.write` patch never reached a `NamedTemporaryFile`). Newborn check: a throwaway citizen minted into a temp registry carries the template bytes, torn down, the real registry untouched. Evidence: 956 passed both rootdirs (was 931 / 1 skipped / 3 failed on the shim), ruff + format clean, checklist 34/34 on the shim, audit 100. Three findings for the sweep: spawn cannot run its own lane against itself (its update code imports its handler at module level) so its leg preloaded the archived copy — the other 17 run in spawn's process and are unaffected; the lane stages through mkstemp so an added shim lands mode 0600 (owners `chmod 664`; the lane learns to widen the mode in a follow-up); a preload out of `.archive/` resolved `parents[3]` one directory too deep and wrote an `apps/spawn_json/` tree — never import from an archive. Also: seedgo's `json_structure` check flags the shim for not calling `resolve()`, which the spec forbids — spawn carries a bypass naming the spec, prax scores 100 on the same bytes only through a stale bypass; seedgo's part A exempts the canonical shim by hash and both bypasses go.
- **The fleet's one json handler service — prax owns it, every branch will bind to it through `from aipass.prax import json_handler`** (prax, DPLAN-0325 / FPLAN-0485, night shift 2026-09-03 on Patrick's "finish ur planning then execute"): the boardroom (r/boardroom-json-service post 8: prax, spawn, seedgo, aipass, devpulse) chose prax over spawn on survivability and direction; Patrick then ruled the fleet's handler drift no longer matters — one source, every agent follows the one file. Phase 0: `aipass/prax/__init__.py` exposes `logger`, `append_jsonl` and `json_handler` lazily (PEP 562 `__getattr__` via `importlib.import_module`, cached in `globals()`, `TYPE_CHECKING` re-exports so pyright still sees SystemLogger); the NullLogger fallback moves from import time to first attribute access and its three pins were ported, not weakened (exec-the-source split into `_exec_prax_init` + `_load_lazily`), four added. Cold footprint of `from aipass.prax import json_handler`, measured in a subprocess and pinned by four tests that go red on an eager-import mutant: 6 aipass modules, zero third-party — was 30 plus watchdog, and `aipass.trigger` never enters `sys.modules`. Phase 1: `apps/handlers/json/json_service.py`, stdlib-only, `for_module(file)` derives `parents[3]` without `resolve()`, the branch's `<branch>_json` directory is computed PER CALL with `AIPASS_TEST_LOG_DIR` honoured in trigger's form, `InvalidDocument(ValueError)` and `WriteFailed(OSError)` named, the three-name contract (`write_json` the bool primitive with the bounded 40 × 5 ms retry; `save_json` raises; `log_operation` best-effort, catches `(OSError, TypeError, ValueError)` by name, never bare `Exception`), the log cap read from the module's config document with 100 as the fallback, the default document in code (`json_templates/` retired to `.archive/`), frame-2 caller resolution with the pseudo-frame guard. prax's own `apps/handlers/json/json_handler.py` is the canonical zero-token shim — sha256 `3456b766…cf0b7`, 1724 bytes, equal to the pinned spec block — binding nine bound methods and never wrapping (a `def` wrapper would rename every operation in every log). `rate_tracker._save_state` now catches `WriteFailed` on the monitor's threads. Evidence: 1488 passed both rootdirs (was 1433; `test_json_handler.py` 18 → 72 — the 18 v4 stamps re-simulated the handler inline and passed after the handler was deleted, archived verbatim), ruff + format clean, pyright 0, checklist 34/34, audit 99 (the one item: seedgo's `default_factory` marker does not know `_default_document`; seedgo adds it in FPLAN-0486). Same commit: nine bare `import aipass.prax` dead-cwd preloads in daemon, devpulse (2), drone, flow, hooks, seedgo and skills (2) become `from aipass.prax import logger`, since a bare package import now loads nothing (the three in commons wait for canary's live WIP on that file). Two findings by prax, amended into the spec: `log_operation` cannot reach `InvalidDocument` by construction (guard, not a pinned behaviour) and `json.dumps` writes NaN as a bare token unless `allow_nan=False` (now spelled out, prax's follow-up).
- **Phase 7 slice 4 — the json_handler template stamp judged copy by copy against the contract suite** (seedgo, FPLAN-0483, 2026-09-02): 201 copies (the dossier said 193; the AST count over the five files is 201) in `tests/test_json_handler.py` of api, drone, seedgo, spawn and `tests/test_json_handler_template.py` of devpulse — **195 SUBSUMED, 5 NOT A TWIN, 1 STAYS**. Fifteen contracts folded into the EXISTING `seedgo/tests/test_json_handler_contract.py`, each parametrized over all 18 branches (the default document a missing read materialises passes the validator; the default factory refuses an unknown json_type; ensure_json_exists creates / reports True / preserves a valid document / regenerates an unreadable one / regenerates a structurally invalid one; ensure_module_jsons creates all three / reports True; log_operation appends a timestamped entry and reports True / attaches the data it was given / accumulates in call order / rotates to the module's declared cap; save_json reports True on a write that landed / writes a document that parses from disk), plus five VALIDATION_MATRIX tuples the copies asserted and the matrix did not carry. Divergence tables, measured not read: `ENSURE_RETURNS_NOTHING` and `ENSURE_ALL_RETURNS_NOTHING` (seedgo returns None by documented decision, seventeen return an unconditional True — recorded as a divergence, not a fault), `UNKNOWN_TYPE_NOT_REFUSED` (skills' default factory answers None for a typo'd json_type, so `ensure_json_exists(name, "confgi")` writes the literal `null`), `DECLARED_LOG_CAP_IGNORED` (aipass/shared writes `max_log_entries` into every config document and rotates on its own class constant — aipass, canary, memory, spawn publish a knob that does nothing). The 5 NOT A TWIN are one fingerprint with two OPPOSITE claims: `test_save_rejects_invalid_structure` asserts `save_json` returns False in api and raises ValueError in the other four — folding it means ruling which refusal the fleet owes, so it stays until someone rules. The 1 STAYS: spawn's `test_log_operation_fifo_rotation` is the only live pin on spawn's rotation while spawn sits in the cap-divergence table. Findings: two of the four fifo_rotation copies (drone, devpulse) NEVER RAN — they set the cap by patching a module attribute no branch defines, green their whole life by never executing; seedgo nearly shipped the same bug and removed the fallback before it landed. The tree moved under seedgo mid-verification: ai_mail's cure landed at 19:31 and six strict xfails went XPASS as designed; seedgo dropped ai_mail from three tables (`WRITER_HAS_NO_BOUNDED_RETRY` and `TORN_DOCUMENT_OBSERVED` are now EMPTY and kept with their record — no branch in the fleet is currently known to tear). Owner evidence: contract file 597 passed / 65 skipped / 16 xfailed; full suite 3767 passed / 69 skipped / 16 xfailed / 0 failed, identical from both rootdirs; checklist 23/23, ruff + pyright clean, audit 100. Devpulse: 597 / 65 / 16 from both rootdirs, ruff + format + pyright clean. Committed together with ai_mail's cure on purpose — either alone is six reds. Post-removal remainders: api 1, drone 13, seedgo 14, spawn 2, devpulse 1 — no file goes to zero.
- **Phase 7 slice 3 — the public writer's durability, one contract over all 18 branches, and the concurrency race written once** (seedgo, FPLAN-0481, 2026-09-02): 96 parametrized cases added to the EXISTING `seedgo/tests/test_json_handler_contract.py`, no new file. Four public-writer contracts × 18 branches — the write routes through the bounded helper (counted on the HELPER, not on `os.replace`: a syscall counter passed the exact inlining refactor the test forbids, so seedgo rewrote it mid-build); an exhausted retry leaves the original intact and cleans the staged temp; the writer survives a transient sharing violation end to end; a write that cannot land never answers True (the fourth was not in the brief — three twins pin the return value and the fleet splits 9 raise / 8 return False, so the claim both camps satisfy is pinned instead of a coin-toss majority) — plus the concurrent-writers race written ONCE with skip-vs-fail discrimination (a race that did not race SKIPS with its counters; a torn or empty document is RED regardless), bounded join so a deadlocked writer fails instead of hanging the suite. Owner resolution walks out from wherever `save_json` is defined, because six branches do not perform their own rename (aipass, canary, memory, spawn via `aipass/shared`; trigger via `trigger/apps/config.py`). Two findings: (1) a FIFTEENTH bounded helper — `trigger/apps/config.py` exports it PUBLICLY as `replace_with_retry`, invisible to a scan keyed on the private spelling; discovery now matches both spellings, +6 cases, slice 2's count corrected 14 → 15. (2) **ai_mail's `save_json` is not atomic**: `open(path, "w")` + `json.dump`, no staging, no rename, no retry reachable — the contract REPRODUCED a reader seeing an empty mailbox document six times in one four-writer run, and the `except Exception` reports the loss as a soft False. Recorded as four strict xfails naming the branch; @ai_mail dispatched for the cure in their own tree. Red first on seedgo's own handler: helper inlined to a bare `os.replace` → 2 failed; truncating in-place write (ai_mail's shape) → all 4 failed; staged temp left behind → 1 failed. Stability: 30 runs of the race across both rootdirs, zero variation, plus 5 consecutive full-suite runs. Owner evidence: 3526 passed / 35 skipped / 15 xfailed both rootdirs, checklist 23/23, ruff + pyright clean, seedgo audit 100. Devpulse: 356 passed / 31 skipped (all pre-existing: missing entry points, backup's path family) / 15 xfailed on the file from both rootdirs, ruff + format + pyright clean, ai_mail's write shape confirmed by reading the source. Subsumes all 24 remaining durability twins across 7 branches — deleted in the next commit.
- **Phase 7 slice 2 in phase 4's shape — one durability contract over every `_replace_with_retry` in the fleet** (seedgo, FPLAN-0479, 2026-09-02): 86 parametrized cases added to the EXISTING `seedgo/tests/test_json_handler_contract.py` — six behaviours (helper exists and is declared bounded; moves the staged file over the target; retries through a transient PermissionError; bounded retry raises when exhausted; waits between attempts; a non-PermissionError propagates with no retry) × 14 implementations, plus two guards against the failure mode a consolidation creates (discovery that matches nothing would collect zero cases and stay green; a canonical handler that calls `os.replace` without the bounded helper is reported, not merely absent). Discovery is an rglob for the helper, not a glob of the known handler paths, and that found a FOURTEENTH implementation nobody had listed: `spawn/apps/handlers/atomic_write.py`. Red first on all six by mutating seedgo's own handler (attempts=1, backoff=0, sleep deleted, catching OSError, bound removed, replace as a no-op — every one caught). The surprising finding: **no divergence in the helper** — all 14 are assertion-identical (one docstring-normalised AST hash, same 40 attempts × 0.005 s), the opposite of `save_json` with its 10 xfails over 4 divergence classes, so no divergence table was added on purpose. Windows: pure monkeypatch, no platform branch, the Windows leg runs the same 14 cases. Subsumes **37 of the dossier's 38** durability twins; the 3 not subsumed are real tests, not copies (commons drives `save_json` to exhaustion; spawn's two exercise `atomic_write_text` with stray-temp and survival assertions). Slice 3 scoped, report only: the four other durability identities are 24 copies but fragment by public-writer calling convention (largest family 3, not 7); three fit the contract, the concurrent-writers test should not be folded (needs real threads and skip-vs-fail discrimination, better written once). Owner evidence: 3435 passed / 35 skipped / 10 xfailed both rootdirs, checklist 23/23, ruff + pyright clean, seedgo audit 100. Devpulse: 265 passed on the file, 86 retry nodes collected, ruff + format + pyright clean. Flagged by seedgo, not chased: `import aipass` binds the aipass BRANCH when run from `src/aipass/` (same species as the FPLAN-0474 defect); the test-write gate refused two read-only scripts whose strings looked like new test paths.

### Changed
- **The weekly v5 cadence is on — and the order of switching it on was measured the hard way** (seedgo enabling, daemon seeding, FPLAN-0491, 2026-09-07 01:39–01:48): seedgo's `.daemon/schedule.json` job `shadow-cycle-weekly` (interval 10080 min, `shadow-cycle run`, mails @devpulse) went `enabled: true` at 01:39, and @daemon seeded `daemon_runstate.json` with `last_run 2026-09-06T03:00` at 01:48 so the week counts from Sunday 03:00 — next run **Sun 2026-09-13 03:00**, verified against `is_job_due()` at six instants. In the nine minutes between, the job tried to fire twice (daemon `run.log` 01:34:52 and 01:40:20), and the only reason the rhythm did not lock to 01:34 Monday for good is that seedgo happened to be awake holding its own branch lock: `record_job_blocked` leaves `last_run` alone, so an enabled interval job with no runstate row is due on every tick. The schedule file's note now says it as a consequence, not advice: **seed first, then enable.** Patrick's 09-01 ruling stands — v5 runs weekly + on demand and scores; it is not a per-commit gate, and making it one needs its own ruling.
- **All 18 branch READMEs verified claim by claim by their own citizens, round 2 after the json sweep** (devpulse orchestrating, FPLAN-0490, night of 2026-09-05/06, Patrick: "tokens to burn"): two citizens at a time in continue mode, docs-only (README + own `.trinity`), every number measured that night, unverified claims marked in the README rather than left green, re-audit to 100 on every CI-scored category, code defects reported to owners and never fixed in the pass. 178 wrong claims corrected across the 18 files (seedgo 27, trigger 14, flow 13, prax 11, spawn 11, hooks 11, backup 10, commons 10, drone 9, daemon 9, devpulse 9, memory 8, ai_mail 7, api 7, skills 6, aipass 5, cli 5, canary 4). The shapes that repeated: test counts stated one way and stale everywhere (now `N def test_ across F files; pytest expands to M cases`, both measured), `json_handler.py` still described as a local handler where it is the byte-identical fleet shim (sha256 `3456b766…`, verified in all 19 copies incl. spawn's template), per-file test tables scoring archived files, "Last Updated" a week or more behind the tree, and dependency tables omitting @prax and @cli though every module imports both. Facts overturned, not just stale: aipass's "no .py elsewhere imports this branch" (spawn imports three of its four shared modules); ai_mail's "wake-back wakes the sender" (a manager is mailed, never woken, and the code returned True for it); daemon's "22 citizens, Vera-Studio out of scope until multi-root discovery" (28 across three tiers, discovery exists); api's "backup credential migration pending, `~/.aipass` legacy" (`~/.aipass` holds live fleet state and no credential); backup's `restore @p list src/main.py` in two places (never worked — `restore.py:56` joins the whole path); seedgo's own passport identity "11 core agents / 44 standards" injected into every seedgo prompt (18 / 46); trigger's 10 events / 10 handlers (7 / 7, and three registered events with no firer anywhere in the fleet). Code defects found and left for their owners, the sharp ones: `drone @hooks test` fires the real PreCompact handlers and stamped a false auto-compact session into hooks' live `local.json`; the live deletion store `.ai_central/deletions.jsonl` carries 211 test-forged `/tmp/pytest-of-*` records of 916; canary's and aipass's `conftest.py` set `AIPASS_TEST_LOG_DIR` inside a fixture instead of at import, so their suites error from the repo root with `-c pyproject.toml` (61 and 1081) and pass in CI only because a sibling conftest sets it first; hooks' git gate read-allowlist is a closed set of 21 (tag, branch -a, remote -v, config --get, stash list, reflog, worktree list, notes list are all refused raw) and its false-fire #8 reproduced on hooks' own report mail; the skills CI 3.10 hang traced to suspend tests patching the stdlib clock process-wide; api's `openai` provider entry has a base URL nothing reads; four `--version` strings hardcoded against their headers (flow 2.6.0 vs `v2.2.1`, devpulse 1.0.1 vs `1.0.0`, drone header 1.2.1 vs `VERSION = "1.1.0"`) plus nine `--help` rosters missing live verbs across aipass, api, backup, hooks, memory, seedgo. Two things happened off-plan and are recorded, not hidden: trigger's report of the unfired `memory_pool_auto_processed` chained into hooks → memory → trigger wakes (four citizens awake against a cap of two; steered by email, all three confirmed no further wakes), and memory built the one-call completion fire in `auto_process.py` (+79/−3, with its existing test) while trigger added a docstring to `memory_pool.py` — both left in the tree as owner WIP for Patrick's read, outside this docs entry. Not committed with this entry: the three code files.
- **Root README verified claim by claim against the tree, second pass** (devpulse, 2026-09-05, Patrick: "full truth only, verify all pieces"): four read-only verifiers covered 84 claims — 62 true, 19 partial, 3 false. The three false: "you don't need any of these" (every spawned agent imports cli and prax at startup, is created by spawn and reached through drone — now said so), "optional add-on agents (OpenRouter/OpenAI)" (no OpenAI provider exists; the OpenAI SDK is OpenRouter's transport), and the outside-the-project layer in Uninstall, which named four writes where the installer makes ten (user-level Claude deny/ask rules and env, the `claude()` boot shim in the shell rc, `pull.rebase`, Codex config, memo.md, the optional systemd timer, uv on the no-sudo path). Partials tightened: doctor runs only on the interactive chat path and the concierge receives hook-wiring failures, not a full verdict; "three prompts" is up to three plus a possible sudo password; git-identity skip lives at the email prompt; "pipes" is stdin-not-a-tty; `aipass new` asks one question and leaves the project on `dev`; an outside-tree project needs `drone @memory roots add` before the fleet can dispatch to it; access tiers gate git only; flow hands vectorisation to memory; daemon is interval/daily/hourly/once/rotation, not cron; Windows is Git Bash in CI, WSL untested; per-project uninstall dropped a root `.ai_mail.local/` that init never creates and gained init's package stub; `.backupignore` is generated, not shipped. Owners mailed, no wake: @aipass (`--help` omits `feedback`, `init .` and `init agent`; bootstrap.py:22 docstring), @backup (`restore` absent from the COMMANDS block), @api (`host-api` absent from help), @spawn (registry name casing). Not decided: `assets/demo.gif` (4 MB, unreferenced) versus the three commented GIF slots that point at files that do not exist.
- **test_quality stops crediting a file that cannot run, and a lone stray token in a big category** (seedgo, DPLAN-0325 session L / FPLAN-0486, 2026-09-04): the branch-wide token scan could earn an item from a file with nothing to do with the category (flow, pair 7) or from a file that executes nothing at all (drone, pair 6a: the DPLAN-0059 trio skipped module-wide on a missing `JSON_DIR` while still the sole carrier of `command_returns_bool`). Two static gates, each on a named dial set where NO branch loses a point today, each carrying its measured next notch: a **live-file gate** (an unconditional module-level skip, a `pytestmark` skip, a test file with no test function, or an unparseable file cannot carry an item; `conftest.py` exempt from the no-tests rule; discounts printed in the audit as a `Carriers` line, never silent — dial `DISCOUNT_CONDITIONAL_MODULE_SKIPS=False`), and a **subject gate** (in a category with ≥ 5 scored items, a file must carry ≥ 2 of that category's items for any of them to count — dials `SUBJECT_SCOPED_CATEGORY_SIZE=5`, `SUBJECT_MIN_ITEMS_PER_FILE=2`). **Fleet measured before and after on the live checker: all 18 at 100, none moved**; the live gate now discounts six memory files (one with no test functions, five module-skipped) and memory loses nothing by them. Two designs refuted by measurement and reported: a subject gate on every category cost all 18 branches (up to −23, cli) because a one-item category can never satisfy a two-item rule; and the shipped threshold of 2 does NOT convict the case that produced the finding — flow's archived handler test carried two incidental `cli_routing` tokens (`StringIO` and `is True`), so the docstring says plainly that 2 is a partial narrowing and 3 is the notch that catches it. Next notches, measured: `SUBJECT_MIN_ITEMS_PER_FILE` 2 → 3 costs exactly one branch (prax −4, `conftest_fixtures/sample_data` earned by its `test_json_handler.py`; cure is the template's `sample_test_data` fixture in prax's conftest — the identical restore flow needed); 4 breaks prax −20, commons −4, daemon −4, do not go past 3. `DISCOUNT_CONDITIONAL_MODULE_SKIPS` → True costs exactly daemon −7 (its own DPLAN-0059 stamps, freed by its sweep). **Part B section 4 staged, not applied** (`seedgo/docs.local/DPLAN-0325_partB_section4_staged.md`): forcing hash-only today reds exactly api, commons, daemon (`Json_Handler` 100 → 66) and nothing else; the citizen template already passes by hash; all fifteen migrated branches are accepted by hash and none relies on the transitional service-import marker. **Finding (a), measured by running the narrowing the wrong way first: `json_structure_check:651` borrows `SERVICE_IMPORT_MARKER` to excuse a shim from "resolves its own path" — delete the marker without moving that exemption to `_is_canonical_shim(content)` and all fifteen migrated branches drop 25 on their handler file.** Section 2: with `--runxfail` all three live xfails still genuinely fail; `UNKNOWN_TYPE_NOT_REFUSED[skills]` went DORMANT (the probe now skips — skills has no private default factory to probe), so that row retires by the subject being gone, not by an XPASS. Records corrected, none asserting: `EXHAUSTED_WRITE_RAISES` 12 → 17 / `RETURNS_FALSE` 5 → 1 (ai_mail counted for the first time; ends 18/0 when api sweeps), `RETRY_IMPLEMENTATIONS` 14 → 8 (three unswept handlers, aipass's retiring file, and the floor of four). seedgo's own `isolated_replace` stub REVERTED to `sleep`-only with the reason recorded: the committed service names staged files by pid + counter and its comment promises never to depend on the clock, so a delegating stub would have silently accepted a dependency the contract never agreed to — strict is the detector. seedgo's dead-cwd `PRELOAD` drops its bare import of `aipass.aipass.shared.json_handler` (nothing in seedgo imports it; 83 passed / 3 skipped before and after), clearing one of the three references FPLAN-0489 waits on. Evidence: 3739 passed / 63 skipped / 3 xfailed both rootdirs, contract 623 / 3 xfailed from the repo root, audit every category 100, ruff + format + pyright clean; the checker's own `Unused_Function` caught the first cut orphaning `_find_covering_file` and it was restored as the one scanning primitive. Same commit (devpulse for prax, on seedgo's ask): the template's `sample_test_data` fixture added to `prax/tests/conftest.py` (1503 passed), so `SUBJECT_MIN_ITEMS_PER_FILE` 2 → 3 is now free fleet-wide — seedgo flips it next session.
- **test_quality subject gate notched to the threshold that convicts the original finding** (seedgo, DPLAN-0325 session M / FPLAN-0486, 2026-09-04): `SUBJECT_MIN_ITEMS_PER_FILE` 2 → 3, measured over all 18 branches BEFORE flipping against the 10:41 baseline — test_quality 18/18 at 100, no branch dropped, 0 code violations, every non-100 average is trinity hygiene. The gate's work is visible in the carriers, not the scores: 19 items across six branches (commons 4, hooks 2, prax 5, spawn 2, trigger 2, +4) moved from a file with an incidental token to a file carrying three or more of the category (e.g. commons's `cli_routing` now earned by `test_cli_and_contracts.py`, not `test_artifacts.py`). The dial comment records the whole arc and the ceiling: do not go past 3 (at 4: prax −20, commons −4, daemon −4). `DISCOUNT_CONDITIONAL_MODULE_SKIPS` stays False (daemon −7 until it sweeps). **Part B section 2:** `UNKNOWN_TYPE_NOT_REFUSED[skills]` retired BY SUBJECT GONE — verified by probing all eighteen handlers for a `DEFAULT_FACTORY_NAMES` factory: seventeen expose none (skills included, its shim has no private factory), the one that does (commons) raises `ValueError` and is conformant; the row was a skip, not a pending XPASS, so waiting for a red that cannot fire would have kept a dead row forever. Recorded in place: the test under it now measures exactly one branch (commons, unswept) and skips seventeen — a retirement decision for the session that closes commons. The three live xfails (`SAVE_JSON_MISSING_PARENT` api/commons, `GET_JSON_PATH_TYPE` commons) untouched; section 4 still staged with finding (a) written verbatim. Evidence: 3739 passed / 63 skipped / 3 xfailed one process from the repo root (the xfail count did not move because the retired row was never among the live three), ruff + format + pyright clean, seedgo audit 100.
- **drone swept to the one shim — pair 6a, the router itself, and it never went down** (seedgo owning the pair, devpulse attending, DPLAN-0325 / FPLAN-0488, 2026-09-04): drone is every command's path including `drone @git`, so spec §6 (h) was run as procedure, not advice — prax's canonical shim copied in by hand FIRST (sha256 `3456b766…`, 1724 bytes, mode 664; the old handler `37a0899e…` kept in `.archive/`), then `drone systems` / `drone @drone --help` / `drone @git status` proven alive, and re-proven after the lane, after the archive moves, and at the end; the restore was never needed. 15 of 18 migrated; api, commons, daemon remain (all three wait on one uncommitted WIP file each). Evidence: 1268 passed branch rootdir; the CI shape (drone suite + seedgo's contract in ONE repo-root process) 1891 passed / 58 skipped / 3 xfailed, three consecutive runs; audit every CI-scored category 100 (Overall 99 is drone's own stale Trinity stamp); ruff + format + pyright clean; contract xfails 3 unchanged — drone carried no divergence row, it was already conformant. (i) measured: drone's `apps/` reaches only `log_operation` (72 sites), `increment_counter`/`update_data_metrics` had zero callers and went with their pins. **(l), the sharpest instance yet:** drone's DPLAN-0059 stamp trio (`test_contracts`, `test_init_provisioning`, `test_json_dir_seam`) had STOPPED RUNNING — a module-level skip on a missing `JSON_DIR` — while still reading as covered to the branch-wide token scan; `test_contracts.py` was drone's sole carrier of `command_returns_bool` while executing nothing. All three archived, the type assertion moved into `test_router.py`, a test that runs. A dead file scoring a live item is worse than flow's case, where at least the wrong file ran. (m) clean: drone's `mock_json_handler` is a plain non-autouse MagicMock. seedgo also saw, once, 45 failures across all 15 migrated branches — `SimpleNamespace has no attribute time_ns` at `json_service.py:138` — that it could not reproduce or explain: it was prax editing the service live in the parallel dispatch (prax's first cut named staged files with `time.time_ns()`; removed before `08359ec2` landed). Two hooks findings banked for @hooks: the test-write gate stayed quiet (policy `on`, tracked), but `git_gate` refused seedgo's first attempt to SEND its reply — `RAW_GIT_RE` scans the command text after stripping quoted strings, a heredoc mail body is not quoted, and the prose "no git — version control is yours" read as a raw invocation; a text-scanning gate cannot tell an argument from a command, same family as the cd-compound false fire. **Windows Test then reddened on `804ab5d9` alone** (CI, coverage, macOS green): two teardown errors in `test_router.py`, `WinError 32` on the sandbox — the sweep's autouse `mock_infrastructure(tmp_path, monkeypatch)` takes the shared `monkeypatch` first, so it is torn down AFTER `temp_test_dir`, and both tests had `monkeypatch.chdir`'d into that sandbox; Linux deletes a cwd, Windows holds it open. Cured in the fixture: teardown steps out of the sandbox before `rmtree` (monkeypatch's own undo restores the real cwd after). Same root as (m), second arm — a sweep is green when all five workflows are, not when CI is. The fixture's pre-existing `/tmp/mock.json` went to `tempfile.gettempdir()` on the standards hook's flag in the same commit.
- **flow and trigger swept to the one shim — pair 7, and the sweep found an item earned by a file with nothing to do with its category** (seedgo owning the pair, DPLAN-0325 / FPLAN-0488, night shift 2026-09-04): both `apps/handlers/json/json_handler.py` are the canonical 1724-byte shim (sha256 `3456b766…`, verified identical to prax's), placed by hand and hash-verified BEFORE the old handlers were archived — spec §6 (h), and drone never went down. flow Overall 100, trigger every CI-scored category 100 (Overall 99 is trigger's own stale Trinity stamp, not the sweep's); flow 1018 passed, trigger 1057 passed, both rootdirs; seedgo 3744 passed / 64 skipped / **3 xfailed** — `SAVE_JSON_MISSING_PARENT[flow]` retired on its first strict XPASS, leaving api + commons rows and `GET_JSON_PATH_TYPE[commons]`, all on unreached branches. 14 of 18 migrated; the IDENTITY axis still skips api, commons, daemon, drone. Dead entry points measured before retiring — flow used exactly one handler name (`log_operation`, 57 call sites), trigger the same (32); `increment_counter` / `update_data_metrics` had zero callers on either, so flow's five pins for them went with the measurement written in their place. trigger's `replace_with_retry` KEPT: it is `apps/config.py`'s, not the handler's, with three live consumers plus `config_loader.py`; config.py cannot import prax (the cycle its bypass documents), so moving trigger's durability layer onto the service is a judgment call reported, not taken. **The finding:** archiving flow's lane routing test as a duplicate of its 40 entry-point tests dropped Test_Quality to 93 — `cli_routing/output_capture` and `conftest_fixtures/sample_data` had been earned by a `StringIO` and a fixture name sitting in the archived json handler test, nothing to do with either category; flow's routing tests patch `print_introspection` and never read what the CLI prints. 17 of 18 branches carry both honestly, so neither retirement nor applicability applies — spec (e) says ADAPT first, so flow's routing test was restored and adapted to what flow writes (module-list-taking `print_introspection`, flow's `USAGE:`/`EXAMPLES:` casing, no version constant, unknown-command-plus-help falls through to module help and exits 0) and the template's `sample_test_data` fixture restored to flow's conftest. Trigger's lane test stayed archived (100 before and after). Banked for a supervised seedgo session, not changed tonight: the checker's token scan is branch-wide, so a file can earn an item for a category it has nothing to do with — a different defect from pair 3's applicability. Also: flow's dead-cwd audit-line probe now measures THROUGH `log_operation` (a direct call to caller detection is one frame short of what the service reads) and pins both arms — a named frame attributed, a `<string>` frame answered "unknown" by design (that literal became a directory once, 2026-08-31); flow's autouse `mock_json_handler` opts out for the shim's wiring test so the fleet's canonical wiring file stays byte-identical. No gate refusals, no prompts (the policy was `on` for the night shift — see devpulse's tracked-switch ledger; reverted after CI). B sections 2 and 4 still held: api, commons, daemon, drone remain. **CI's coverage leg then reddened six contract tests for `[flow]`** while all four xdist legs passed: flow's `test_push_central.py` monkeypatched `log_operation` on the shim while the autouse spy held a `patch()` on the same attribute, and since `monkeypatch` is one shared instance already taken by `mock_logger`, it tore down AFTER the spy's patch exited and put the spy's MagicMock back onto the shim for good — a pre-existing leak, invisible while flow ran alone (its own wiring test sorts before `test_push_central`) and exposed the moment the contract's IDENTITY axis ran against a migrated flow in the same process. Cured by telling the spy to raise (`mock_json_handler.side_effect`) instead of a second patch; reproduced and verified locally in the CI shape (devpulse, follow-up commit).
- **seedgo (own) and cli swept to the one shim — pair 4, and archiving cli's handler crashed drone mid-sweep** (seedgo owning the pair end to end, DPLAN-0325 / FPLAN-0486, 2026-09-04): both `apps/handlers/json/json_handler.py` are the canonical 1724-byte shim (sha256 `3456b766…`, verified identical to prax's), old handlers and internals suites archived, conftests on the `AIPASS_TEST_LOG_DIR` seam. seedgo Overall 100 (212 production files, Trinity included), cli Overall 100; suites green from both rootdirs (seedgo 3747 passed / 66 skipped / 4 xfailed, cli 186 passed). **The contract dropped 8 → 4 xfails, each retired only on the XPASS the sweep produced:** `SAVE_JSON_MISSING_PARENT` for cli and seedgo, and both one-row `ENSURE_RETURNS_NOTHING` / `ENSURE_ALL_RETURNS_NOTHING` tables — seedgo's own documented decision to return None (an unconditional True is a success signal that never arrives) settled by the service, the reasoning kept in a comment over each emptied table so the fleet's uninformative True does not read as unquestioned. The remaining 4 are all on unreached branches (`SAVE_JSON_MISSING_PARENT` for api/flow/commons, `GET_JSON_PATH_TYPE` for commons). **test_quality: both 100, nothing dropped — pair 3's applicability cure had already immunised cli before its own sweep, exactly its purpose, so no checker change this pair.** Three findings, all handled: (1) **archiving cli's handler took drone itself down** — drone → resolver → `cli.apps.modules.display` → cli's json handler → ImportError, the whole CLI dead mid-sweep; recovered by placing prax's shim into cli by hand (the lane only adds a missing file, and drone must run to run the lane), hash-verified. That crash is proof cli's two bypasses (both reading *json_handler cannot import prax, circular*) were obsolete: the cycle is real and the shim imports prax anyway, broken by prax's lazy PEP 562 `__init__` — both rows retired (silent_catch, error_handling; bypass 9 → 7). Relayed to the six unmigrated branches: any carrying a circular-import bypass on its handler must NOT archive the old handler before the shim is in place. (2) the sweep retired two dead seedgo entry points (`increment_counter`, `update_data_metrics`) — the one service never bound them and the fleet has no caller outside the five still-unmigrated handlers (flow, daemon, commons, drone, trigger), so it retired dead surface with the four tests that pinned it, the measurement written where they used to be; those five will meet the same two names on their sweep. (3) the test-write gate false-fired a seventh time in a new shape — a read-only pytest inside a cd-compound, the gate resolving the path argument against the first cd's cwd into a phantom doubled path it read as a new test file and refusing the whole compound (banked for @hooks: the gate reads path-shaped arguments of read-only commands, not writes). Also fixed in seedgo's tree: the dead-cwd sweep now skips dot-dirs and pycache (it had walked the archive and raised SyntaxError, six tests reporting nothing instead of failing); the audit's incremental `CACHE_FILE` re-pointed at the service; the lane's routing suite adapted to what both entry points actually write (general help, exit 0 — a help request answered with help is not a refusal); cli's README corrected 201 → 166 tests. B sections 2 and 4 stay staged for pair 7.
- **canary and memory swept to the one shim — pair 3** (devpulse landing canary + memory, DPLAN-0325 / FPLAN-0488, 2026-09-03): both `apps/handlers/json/json_handler.py` are now the canonical 1724-byte shim (sha256 `3456b766…`, mode 664), old handlers archived, conftests moved to the `AIPASS_TEST_LOG_DIR` seam with the sandbox measured off the shim's own `get_json_path`, the DPLAN-0059 stamp and the json-handler naming bypass dropped. **memory's wall — the reusable finding for the bespoke-conftest branches:** memory's autouse `mock_infrastructure` stubs `aipass.prax` with a bare `ModuleType`, which satisfied the old `from aipass.aipass.shared.json_handler` import but not the shim's `from aipass.prax import json_handler` — 187 failed / 255 errored on the first pass; cured faithfully by binding the real stdlib-only prax service onto the stand-in (`prax_mod.json_handler = _prax_json_service`), the same shape cli, commons, daemon and api will each need. **canary's cascade:** archiving the handler orphaned `apps/handlers/paths.py` (its sole importer), which the audit then flagged three ways (dead_code, unused_function, json_structure 0%) — paths.py is stdlib-only by design and its cwd-safety role is now prax's cwd-free service, so it was archived and its two now-dead dead-cwd pins retired; the lane's `test_cli_routing.py` was a strict subset of canary's curated `test_canary_cli.py` (zero unique tests), archived as a duplicate. canary's swept tree first audited Test_Quality 87 — cured to 100 not by retiring tokens but by seedgo's per-branch item applicability (see Added, checker 5.1.0), since canary parses no JSON and ships no subject for those four items. Evidence: canary 61 passed both rootdirs, memory 1578 passed both rootdirs (5 pre-existing skips), every CI-scored standard 100 on both (Overall 99 is Trinity, machine-local, never gated); ruff + format clean, pyright 0/0/0 on the changed files.
- **devpulse swept to the one shim, and the sweep's first measurement changed the landing order** (devpulse, DPLAN-0325 / FPLAN-0488, 2026-09-03 04:35): `apps/handlers/json/json_handler.py` is now the canonical 1724-byte shim (sha256 `3456b766…`, mode 664), the old handler archived beside it; the DPLAN-0059 template stamp `tests/test_json_handler_template.py` (monkeypatched `_JSON_DIR`, called `_default_config`, stubbed `sys.modules`) moved verbatim to `tests/.archive/` - seedgo's contract pins every claim it made; `tests/conftest.py` v1.2.0 arms `AIPASS_TEST_LOG_DIR` at the top and carries the template's autouse `mock_infrastructure` (sandbox measured off the shim), nothing patches handler attributes any more. Two findings for the fleet, both in the spec: the spawn lane adds EVERY template .py a tree lacks, not only the shim - `tests/test_json_handler.py` (the shim's wiring test, kept) and `tests/test_cli_routing.py` (pins the template's CLI shape, 13 red against devpulse's entry, archived, not adapted); and CI's `seedgo_audit.py` gates every branch at 100 while the v4 `test_quality` checker greps for the stamp's substrings across five categories (devpulse: Test_Quality 88, Overall 99), so seedgo's part B category retirement lands BEFORE the first stamp-dropping sweep, not with the last pair. Suite 569 passed both rootdirs (the two `test_import_dead_cwd` reds from `src/aipass` are the pre-existing FPLAN-0474 species); ruff + format clean; every other standard 100.
- **skills and ai_mail swept to the one shim — pair 2** (devpulse landing skills + ai_mail, DPLAN-0325 / FPLAN-0488, 2026-09-03): both `apps/handlers/json/json_handler.py` are now the canonical 1724-byte shim (sha256 `3456b766…`), old handlers and `apps/json_templates/` archived/removed, conftests armed on `AIPASS_TEST_LOG_DIR` alone, the v4 stamp and durability twin test files gone. skills migrated its call sites off the dropped `SKILLS_JSON_DIR` constant to the service (`switch_handler.get_state_path` via `get_json_path`, the telegram relay/switch-gate tests to the env seam). ai_mail also retired its FPLAN-0481 `apps/handlers/json_utils/` atomic-write handler — the service carries the same staged-write cure, so one source now, not two. Evidence: skills 1419 passed from the repo rootdir plus 156 sweep-affected from the branch rootdir, ai_mail 1433 passed both rootdirs; every CI-scored standard 100 on both (skills Overall 99 is Trinity 93, machine-local, never gated); ruff clean both, pyright introduced no new errors. Banked for @prax: `json_service._stage` stages through `NamedTemporaryFile` (0600) and `os.replace` carries that mode onto the target, so every service write narrows a 664 document to 600 — fleet-wide, fires on every write; cure is a chmod after replace or staging with the target's mode.
- **Phase 6 wiring, three small commits** (devpulse, DPLAN-0323, 2026-09-02): (1) the CI audit script gains a pack-count tripwire — `EXPECTED_STANDARDS = 47` (46 `*_check.py` in the aipass pack + the diagnostics checker), so a standard can never leave the gate silently: retire a checker or break its import and the job fails naming the count, instead of quietly averaging one fewer standard at 100. The number moves only by hand, in the commit that adds or retires a standard. Measured before pinning: every branch scores exactly 47 today. **First board, first catch:** CI consulted 47 but scored 46 — the `trinity` standard reports `not_applicable` on a clean checkout because `.trinity/` is machine-local and gitignored, so it has never gated CI, and a local trinity fail (ai_mail's `local.json` numbering, seen the same night) can never red a board. The tripwire now counts every standard the audit CONSULTED (scored + not-applicable) and prints the stood-down ones per branch; proven at 47 on all 18 branches in a tracked-only extract (46 scored + trinity) and locally (47 scored). (2) `codecov.yml`: project and patch statuses off, PR comment off — Patrick's ruling, no coverage percentage targets; the coverage job keeps uploading so the dashboard stays an instrument. The patch status had been painting a red X on PRs that passed. (3) `mutmut>=3.7` declared in the dev extras and installed — mutation sampling is the pyramid's ground truth; mutmut 3 needs a `[tool.mutmut]` block or a `src/` layout in cwd, so it runs from the repo root and the sampling instrument that drives it is seedgo's. Deliberately NOT wired: the v5 pack stays inert at CI and the checklist until the shadow cycle ends.
- **Phase 6, the seedgo half — `drone @seedgo shadow-cycle run`** (seedgo, FPLAN-0476, 2026-09-02): one verb runs the three measurement passes (v5 shadow score over 18 branches, the ranked inventory, the twins report) and mails @devpulse a one-screen summary with artifact paths — the console prints the same block, so terminal and inbox cannot disagree. `--no-mail` for Patrick's own runs. It reuses `inventory._fleet_container()` so the registry is never read. Weekly entry in seedgo's `.daemon/schedule.json` as a 10080-minute interval (the daemon has no native weekly type), **landed `enabled: false` on purpose**: an interval job with no runstate entry fires on the next tick and locks its weekly rhythm to that hour, and the slot can only be set by seeding `last_run` in @daemon's runstate — a cross-branch write seedgo refused to make. Switch-on procedure is in the job's `_note` (seed first, enable second). New artifact family `.seedgo/shadow_cycle*` gitignored in the same change. First live cycle: fleet average 98 on the v5 pack, 19,709 test functions, 9 consolidation candidates.
- **Shadow diff #1, v5 vs the haiku triage** (`seedgo/docs/v5_vs_haiku_shadow_diff.md`): population-level, because the haiku per-row verdicts were never written to disk (independently confirmed by the deletion dossier). On the one overlapping rule v5 does not convict what haiku cleared (haiku 305 of 526, v5 308, by the same two mechanisms). False-conviction pressure sits entirely in `docstring_pin` (264 of 308 healthy rows), the rule already shipped unscored; the other ten rules land zero on the healthy population. On the record against gating yet: v5's `TEST_DIRS` is top-level only, so `devpulse/tools/hook_engine_poc` and the nested telegram tests are invisible — and that blind spot holds 5 of haiku's 7 NO_ORACLE rows; 66 of the 263 delegating clears delegate to a production symbol, not a checking helper; and 995 of v5's 1,198 non-docstring flags have never been judged by anything.
- **mutmut config: nothing at the repo root, by seedgo's reading of the installed tool.** mutmut 3.7 has no CLI flags for source paths or the runner; it reads `pyproject.toml` from the CURRENT WORKING DIRECTORY, so a root block would make a bare `mutmut run` look valid while mutating all 18 branches against a 19,700-test suite. The sampling instrument will materialise a scratch copy per branch with a disposable `[tool.mutmut]` block and sample by MUTANT_NAMES; verified on a throwaway package (1/1 mutant killed).
- **Two seedgo defects found tonight, reported not fixed:** `drone @seedgo audit pytest_quality` overwrites `.seedgo/last_audit.json` (the fleet compliance record) with a shadow score, because `default_artifact_path` scopes by branch and bypass mode but not by pack; and the incremental cache key omits the pack, so alternating packs evict each other into cold full scans. Pins named, fix queued.

### Added
- **Test-write gate** (hooks): agents can no longer create new test files — a PreToolUse gate (`testwrite_gate.py`, 29th handler) behind a JSON policy switch (`.aipass/test_write_policy.json`: off now, `allow[]` for canary trials, one field flip to re-enable). Fail-closed on missing/corrupt policy, with both safety properties pinned: non-test writes never read the policy, and writing the policy file is itself always allowed. Admin seat checked before the policy read. 54 pins, 13/13 designed mutants killed, proven live through `engine.dispatch`. Not yet wired into `hooks.json` — the wire is a deliberate human checkpoint (trust re-enrollment).
- **Admin seat rail extracted** (hooks): the 5-leg grant moved from `edit_gate` into `modules/admin_seat.py` — one home, both gates delegate. The extraction itself surfaced (and fixed) a real defect: an unimportable `admin_seat` would have fail-open exempted every seat; both gates now refuse instead.
- **Test inventory** (seedgo, FPLAN-0468 phase A): `drone @seedgo test-inventory` — static ranking pass over all ~19k fleet tests in seconds; artifacts gitignored by family rule (`.seedgo/test_inventory*`).

- **pytest_quality_standards — test_quality v5** (seedgo): a generic, stdlib-only standards pack (liftable onto any Python project) with eleven AST rules that judge what a test *proves*: no_oracle, assertion_shape, unentered_assert, capture_never_read, empty_parametrize, mock_drift, self_skip, posix_literal, entry_point_diff, coverage_slot, docstring_pin (structural — the docstring must name a symbol the test actually calls; unscored until the fleet's 89.8% miss rate comes down). Scores the whole fleet in 70s, runs in shadow mode: 1,369 flags across 18,780 units (docstring_pin excluded). v4 remains the CI gate untouched until v5 is proven over a weekly cycle. Porting the old nominators surfaced four real corpus-reader bugs (two inherited by the production audit-tests lane) — all fixed with red-first pins.

- **Teaching templates** (seedgo): three worked examples in the pack's `templates/` — seam, failure-path, and contract tests — each showing the wrong version first with the reasoning inline and a DO-NOT-STAMP block citing the stamped-family measurement. Wrong versions are executed by proof tests (not dead code, not collectable); the templates pass the pack they ship with, including docstring_pin's measured score.
- **json_handler contract suite** (seedgo): 216 (implementation, contract) pairs glob-discovered over all 18 branches — 179 pass, every skip/xfail naming its branch and divergence. Nine real fleet divergences published (none silently fixed): `save_json` into an absent directory splits three ways across the fleet (9 create it / 5 return False / 4 raise), two of which lose the document on a fresh checkout; `validate_json_structure` pinned as the one genuinely shared contract. The twins report says the campaign's own quiet part out loud: a filename-keyed merge of the five stamped families would destroy 1,363 of 1,411 tests — consolidation walks a 48-candidate list, never a family list.

### Context
Part of the test-standards campaign (DPLAN-0323): seedgo's `test_quality` v4 standard graded tests by substring pattern coverage and CI gated the average at 100, which manufactured tests-for-the-checker fleet-wide. v5 above replaces the design; deletions and gating wait until the shadow cycle proves it.

## [2026-09-01] — one test universe: the night CI-red stopped being a norm (FPLAN-0460/0461) · v2.8.1

### Fixed

- **Round 13 is a skip list, not a round** (FPLAN-0461, the ruling applied as
  written). The round-12 board's real cures all held — the coverage report
  step survived, the direction table went green on every POSIX leg — and every
  remaining red was round-11/12 test instrumentation meeting a real host: six
  tests in two files. Per the one-fix ruling they were skipped by name with
  the reason in the mark, not cured with another instrument: seedgo's three
  instrument self-checks (red on a different interpreter each board, green
  only on the 3.12 box that wrote them; the worlds they self-check remain
  exercised by every test that uses them) skip unconditionally, owner to
  rewrite as measurement after the PR; backup's three coverage pins skip on
  Windows only, because they are the live POSIX regression net for the real
  report-step landmine and that stays armed. One commit for the whole board.

- **Round 12: the hybrid row, the wrong attribute, and the coverage landmine —
  under the one-fix-at-a-time ruling** (FPLAN-0461 continued). Patrick's ruling
  landed mid-round and governs everything after: fix one thing at a time, no new
  test instrumentation on this PR — future reds get the minimal cure or a named
  skip; never add a test without a defect it pins (the audit-tests lane is the
  instrument for test bloat, not more tests). This train is the last pre-ruling
  pair, both cures of round-11-authored test code, zero production changes.
  Seedgo: the 3.11 hybrid row measured instead of predicted (accessor removed,
  flavour still an object — the route is a call-time module read), and the
  stand-down guard read `PurePath._flavour` where 3.10/3.11 define it on the
  CONCRETE class — a guard reading the wrong attribute is indistinguishable
  from no guard and looks more careful in review; now reads the concrete class
  with three measured arms. The Windows no-op break cured by breaking the
  routing identity TOWARD the dialect the host is not — and their sweep then
  caught the cure itself asserting this box's dialect as a literal, so what
  ships is all measurement: the child announces where it started, a two-row
  direction table decides where it must go, the both-sides pin asserts
  movement rather than a destination, and hosts where the reading cannot move
  report instead of convicting. Per the ruling, two extra pins were taken
  back out; three surviving mutants are named on the record instead of
  pinned — all one species, an arm that only fires on a host this box is
  not. Backup: the coverage
  report landmine reproduced to the line — a test compiled code under a fake
  filename inside the source tree, so coverage recorded a measured file absent
  from disk and the REPORT step failed with zero test failures; the two sites
  called likely-inert were NOT (drive-lettered PureWindowsPath literals are
  RELATIVE on POSIX, resolved against cwd at trace time — they fire from the
  branch cwd). Cure: one guarded mint point every future site inherits by
  construction, fabrications moved under tmp_path, both cwds pinned. Rule
  banked: whether a fabricated filename mints depends on the cwd, because
  abspath does. Also this round: the test-quality audit lane ran for the first
  time in the campaign (harness 12/13; its one fail correctly named real
  unattributed tree writes) and joins the standing verification bar alongside
  the standards audit; @aipass dispatched on round-2 research — a ranked
  per-test inventory for a 20k-test fleet, culling precedent, and AI test
  bloat as a named industry problem.

- **Round 11: the fixture's first catch, the captured accessor, and the end of
  arms** (FPLAN-0461 continued). Round 10's board (c5b6e173): six red legs and
  every red ONE FILE — while spawn's import guard went green on every leg for
  the first time in six boards and seedgo's alias cures held everywhere. Three
  tests. The first was seedgo's day-old left-nothing-behind fixture CONVICTING
  A REAL FLEET DEFECT on its first live catch — and the defect was devpulse's
  own: the watchdog storage resolver walked up from Path.cwd() looking for
  AIPASS_REGISTRY.json (machine-local, absent on every fresh checkout) and
  fell back to Path.cwd()/.watchdog, so a parallel devpulse test planted
  .watchdog/ at the repo root on CI — invisible on every dev machine because
  the marker exists there, and the timer copy carried a comment defending the
  fallback as production-only, refuted by CI within a day. Cured by devpulse:
  root derived from __file__, both walks and both fallbacks deleted, red-first
  pins reproducing the exact fallback answer before the fix, agent tests
  hermetic via module-local autouse. The other two were seedgo's own round-10
  pins carrying the species one level up — the assumption in the assertion of
  the very pin that documents the assumption. ROUTES_THROUGH pinned "Path's
  routing module IS os.path" — the 3.12 spelling; the fact that DECIDES the
  route is the pre-3.11 CAPTURED ACCESSOR (pathlib holds a private copy of
  realpath a module patch can never reach), measured by a spy and pinned as a
  four-row literal table falsifiable from 3.12 twice over. DISARMS_world_a's
  negative control asserted a 3.11+ fact on every interpreter — and devpulse's
  machine-shaped diagnosis was REFUTED WITH RECEIPTS (child run from a
  marker-less cwd: still survives), while devpulse's OWN overclaim (red on
  all six including 3.12) was corrected on seedgo's challenge: the 3.12 leg
  carried only the watchdog conviction, and the correction relocated the one
  unexplained leg to 3.13 — where a targeted addendum found THE THIRD
  MECHANISM: 3.13's resolve reads os.path at call time, so the chimera does
  not sever the route, it MOVES it — world A's own patch rides along on
  ntpath and the defect dies. The cure is the end of arms: after three rounds
  of predict-from-version-and-platform tables each refuted by a real host,
  the control now ASKS THE CHILD which routes survive the chimera — right on
  3.13, nt, pre-3.11, and interpreters nobody has shipped yet, without naming
  any of them. The sweep pre-killed three more 3.13 reds and caught seedgo's
  own hour-old pin carrying the species it was written to cure. Fleet lines
  banked: an arm that only fires on a host you do not have needs a table,
  not a branch (the mutant that deletes it is invisible on the only machine
  you can run); a new world needs its stand-down and its host-already-has-one
  pin on day one. Devpulse 607x2, seedgo 2916x2 across the two passes, audits
  100.

- **Round 10: the assumption moves into the assertion next** (FPLAN-0461
  continued). Round 9's board (84175b82): production clean a FOURTH consecutive
  board, red owners down to two, five unique failing tests — and spawn's
  windows-leg skip-by-name cure HELD on the real Windows runner. Every red was
  one species, seen twice in one round: round 9 made the verdicts honest
  three-state, and the reds were the ASSERTIONS over those verdicts, still
  spelling the answer of the host they were written on. Devpulse diagnosed all
  four mechanisms from the CI evidence before dispatching; two survived contact,
  two were corrected with receipts and the conclusions stood. Spawn: the posix
  control now measures a control (untouched-host run first, forcing posix must
  LEAVE the row, forcing nt must MOVE it — no literal anywhere, and the row
  runs again against an object-flavour host so the restored-literal mutant dies
  on the exact CI red reproduced locally); the parse_parts dialect mismatch is
  gated by a MEASUREMENT, not a version table — a probe asks the host's own
  pathlib what it reaches for, rows carrying a module-shaped flavour skip by
  name with the host's own answer, and the probe carries a negative control
  that grows 3.10's consumer to prove it can fire (a silent child reads as
  unknown and CLOSES the rows). Seedgo: the alias judgement keys on measured
  module identity with both arms asserted and an nt-identity world reachable
  from Linux forever — the world's two halves pinned alone, because identity
  without the cwd-reading realpath is the Linux answer wearing an nt label;
  and the refuted mechanism's cure was one dialect-neutral literal — the probe
  had built its input as abspath(os.sep), which is rooted-driveless on posix
  but DRIVE-rooted on nt: the input changed shape underneath the row. Seedgo's
  property sweep then caught THREE literals true only where ntpath carries the
  3.12 legacy clause — next board's 3.13 reds, killed tonight — and grew a
  fourth verdict for a foreign ntpath that reads the cwd anyway (an emulation
  reported as a platform). The night's found-object: backslash-named files
  minting at the repo root, spawn measured them without naming an author,
  devpulse attributed them to seedgo's window, and seedgo corrected the
  attribution with receipts — their throwaway sweep instrument, not shipped
  code — while writing down the harness property that made it a commit risk at
  all: the composed runner hands every child cwd = repo root, so any relative
  write anywhere lands in the tree. Pinned one level stronger than asked: a
  fixture that fails the module if children leave ANYTHING behind, deliberately
  non-deleting, acquitting removed entries, its watched directory pinned to the
  real child cwd. Fleet lessons banked: a mutant that deletes a COUPLING is
  invisible to a single-mutant run (the pair is the mutant); an assertion that
  holds cannot be killed by deleting it (mutate the source); and the naming
  checker learned PYTEST_CONTRACT_GLOBALS from devpulse's refused auto-fix —
  2074 files, 7 verdicts change, all FAIL to no-verdict. Spawn 977x2 with 12/13
  mutants named, seedgo 2901x2 with 8/8 named, both audits 100.

- **Round 9: the instruments learned to say where they cannot speak — cross
  terms, one-dimension litmuses, and the wrong question** (FPLAN-0461
  continued). Round 8's board (9bd2618b) was five red legs, zero production
  defects for the third consecutive board — and every red was a cross term:
  a shape simulated on a real host where neither side is 3.12. Three owners,
  one evening. **Spawn** (965×2, 147 pins in the file, 14/15 mutants each named
  with the assertion that fired) decomposed the cross into four mechanisms and
  found the deepest one under it: the old symptom table pinned whether a
  rebinding reaches the route *afterwards* — an answer that moves with the host
  for reasons unrelated to the emulation. Three reds, one wrong question. The
  cures are the terminal shapes: symptoms as judgements over measured values,
  simulations that declare which real hosts they can speak from and skip with
  the child's own reason elsewhere, and the platform asymmetry stated plainly —
  the nt getcwd row is measurable from posix (it rests on the cwd read sitting
  above the isabs check), the posix row is not measurable from nt (it rests on
  what counts as absolute), so on the windows leg those rows now skip by name.
  Two findings that travel: *an emulation friendlier than the thing it emulates
  hides the defect* (their flavour stand-in forwarded to posixpath, which has a
  realpath the real `_PosixFlavour` lacks — delegate to the thing you stand in
  FOR, not a convenient neighbour), and rebinding `pathlib.Path` moves pathlib's
  own `cls is Path` identity test — the tidier rewrite is the broken one.
  **Seedgo** (2882×2, 8/8 mutants named) found round 8's defect committed again
  one file over — the *reproduction partner* of the cure installed a three-method
  accessor stand-in that decapitated a real 3.10: "a cure and its reproduction
  are two instruments, and I applied the rule to one of them." Their synthetic
  accessor now delegates every unnamed attribute ("a stand-in for a namespace
  that answers three questions is a trap for the fourth") and prints whether it
  synthesised or stood down. The alias-catchability red confirmed the dispatch
  hypothesis against CPython source: 3.13 removed ntpath's LEGACY BUG clause
  (3.12 ntpath.py:99–102) keeping rooted-driveless paths absolute — a platform
  fact that was a version fact, their own checker-pack sentence landing in their
  own file; the verdict is now three-state, because a verdict that cannot tell
  two different losses apart hides the more interesting one. **Flow** (1041×2 +
  bare-checkout, 15/15 valid mutants dead, 2 invalid published as invalid) found
  worse than their reported red: *a one-dimension litmus is blind on the host
  that already is that dimension* — on Windows their runner fake installed
  Windows-shaped values over Windows-shaped values and the litmus measured
  nothing while reporting green. The cure is a runner **set**: both platform
  fakes run every direction and the verdict must not move, so on any host at
  least one row is a real measurement. Trigger's round-9 line — a mutant report
  says *which assertion fired*, not only how many — was taken by all three
  owners the same evening it was proposed. Devpulse fixed the unowned repo-root
  `conftest.py` docstring and refused the auto-fix rename of
  `collect_ignore_glob` (the lowercase name is pytest's API contract; the tidier
  spelling silently disables the mechanism), reported to seedgo as a live
  checker counterexample. The seedgo-audit leg and test 3.12 went green this
  board; expected next: the campaign's first fully green board, with the
  windows-leg posix-only rows skipping by name rather than asserting what the
  runner can contradict.

- **Round 8: the assumption moves up a level every time it is cured — round 7's
  instruments were sound, and the machinery that installs them was not**
  (FPLAN-0461 continued). Round 7's board (commit 68ab5132) came back 20/20
  checks with six non-green and **zero production defects** — the first board
  where Windows ran the fleet's own litmus for real: an nt host, and every
  expectation still keyed on "here = posix host" moved. Six owners, every red an
  instrument, every cure red-first on Linux. **Spawn** (930×2, 14/16 mutants + 2
  named equivalents) owned the largest share and the round's sentence: *the
  version-shaped assumption moves up a level every time it is cured* — round 6
  the world, round 7 the emulation, round 8 the installer. Their shape preludes
  reached `PurePath._parse_path` (3.12+; older interpreters spell it
  `_parse_args`), so the child died before printing and all 37 failures on
  3.10/3.11 wore the arming probe's message — *a harness crash wears the message
  of the instrument it never reached*. Their 3.13 red was the probe building its
  own input **inside** the world it measures, meeting 3.13's ntpath dropping the
  legacy clause that kept rooted-driveless paths absolute; the cure vocabulary —
  halves with three verdicts (NATIVE / INSTALLED / UNAVAILABLE-with-the-child's-
  own-reason), decisions by measurement not `hasattr`, the probe literal built
  once and its VALUE reused — is the round's export. They also corrected the
  dispatcher's brief by measurement: the coverage leg runs **3.13, not 3.12**
  (ci.yml:101), so the "dies under the coverage tracer" hypothesis is refuted —
  one mechanism had been counted twice. **Flow** (1029×2 + bare-checkout, 13/13)
  extended the verdict: *an instrument's inputs are behaviour too* — round 7
  cured the captured function and left the probe path built from `os.sep` and
  `pathlib.__file__`, the runner's spelling, which posixpath rightly reads as
  relative; and they named the litmus's missing dimension — it varied the
  emulated host, but what convicted CI was the platform the **process** runs on,
  so WINDOWS_RUNNER now fakes exactly what a probe can read to build a path and
  is deliberately *not* a world. Their confession pair: a structural check that
  reddened on its own documentation, and an nt literal mangled by its enclosing
  triple-quote (`\not` became a newline — the instrument's input corrupted by
  the language it is written in). **Trigger** (1092×2, 0 skips) refuted the
  dispatcher's mechanism while confirming the conclusion — the probe path was
  `sys.executable`, drive-lettered on the runner, and the fix a one-line
  dialect-neutral literal; their addendum deleted a control clause a mutant
  proved could never fire ("it looked more careful than what replaced it") and
  found their own round-7 two-sentinel discriminator gone dark one round later
  by the mechanism it guarded against. Their round-9 line rides ahead: *a mutant
  report should say which assertion fired, not only how many — false kills are
  worse than false survivors, because nobody re-examines a kill.* **Seedgo**
  (2869×2, 8/8) named the verdict's mirror — *an instrument must not REMOVE
  behaviour it is not testing* — after their 3.10 emulation stubbed the accessor
  a real 3.10 routes its whole API through, decapitating the interpreter before
  the measured defect was reached; and their windows red was their own round-7
  sentence ("absolute never reads the cwd is a posixpath fact") shipped as a
  constant one file over — the nt alias row is now *reported* as unfalsifiable
  there rather than asserted away. Their stacking find (host == emulated is one
  layer) was acted on by spawn the same hour: applied each emulation twice,
  pinned no-recursion, and killed the mutant that proves the property is
  measured, with seedgo's name on the pin. **Skills** cured **six** docstring
  files, not the three CI flagged nor the five seedgo's mail named — the sixth
  was invisible to both lists because its verdict never *moved*, and seedgo's
  list was correctly a diff of moved verdicts: *a handed list is a lower bound
  whenever the thing that produced it is a diff — re-measure until the number
  stops moving.* They also caught spawn's `ntpath.py:678` citation reading `:673`
  on 3.12.3 — the ordering travels, the line number doesn't. **Ai_mail** (1446×2)
  reproduced their discarded string-after-import before fixing it (`__doc__` was
  None on the live module), worked the tree not the list, and named an unarmed
  species for seedgo to confirm: an f-string opening a module body reads as a
  docstring to a human and is refused by `ast.get_docstring`. The seedgo-audit
  leg itself was the dispatcher's own train collision — `--all` swept the new
  ast-based checker onto CI before the flagged owners had fixed their files.
  Composed verify before this commit: full universe from the repo root under
  exact CI mode, plus per-branch both-rootdirs by every owner; the train
  deliberately carries seedgo's held work (the posix-literal checker pack, the
  docstring rule, the settle-recheck, and the round-7 litmus pins).

- **Round 7: an instrument must not import behaviour it is not testing — the
  round-6 instruments met the interpreters and platforms they were built to
  emulate, and lost everywhere except home** (FPLAN-0461 continued). Round 6's
  board was 12 green with test 3.12 passing — the exact interpreter the fleet
  builds on — and red on 3.10/3.11/3.13 and windows-setup (13 failed /
  19,697 passed on *Python 3.12.10*, isolating pure nt semantics). Every red
  was round 6's own new accessor instruments; zero production defects, all
  prior cures held. Memory measured the mechanism in 553 seconds and named the
  fleet verdict: the probes were built out of the **live** `os.path` and
  `os.getcwd`, so their verdicts carried platform behaviour they weren't
  testing — on nt `os.path` *is* `ntpath`, whose `realpath` reads the cwd
  unconditionally (round 4's own headline turned back on its finders) and
  makes a POSIX-absolute literal drive-relative (`/tmp` → `D:\tmp`). Three
  rules, each paid for: emulate *both* platforms or neither; build emulations
  from `posixpath`/`ntpath` **by name**, never `os.path` (which *is* the
  host — flow's first try recursed into itself 997 frames deep); and probes
  asking "did my patch reach X" capture a **sentinel** that returns its
  argument, so the original's platform behaviour can't answer for it. Plus the
  litmus that finds all three: run every probe under the *opposite* platform's
  emulation and require the verdict not to move — it caught spawn's next CI
  red before it shipped. Spawn's cluster decomposed differently by reading
  CPython per version: 3.10/3.11 reds were their emulation *crashing while
  parsing* (a wrapped `_flavour` lost `parse_parts`), 3.13's patch was a write
  nothing reads, Windows instantiates `WindowsPath` outside the patched
  hierarchy — the new emulation replaces exactly one method and proves it
  armed (`ROUTE_ARMED`/`ROUTE_DARK`) before anything downstream claims.
  Refinements traveled mid-round: skills corrected flow's alias trap by source
  read (off-Windows `ntpath.realpath` is a *wrapper*, not an alias — an `is`
  test proves nothing) and kept `getcwd` a live capture deliberately (a
  sentinel can never arm, so sentinelling it takes the eagerness pin dark);
  trigger closed that hole with two distinguishable sentinels (eager answers
  CAPTURED, lazy answers MOVED — no platform behaviour in the discriminator);
  drone generalized: a pin that reads a *value* back can be measuring the
  host, so the litmus lives beside every return-value pin as a test. On the
  record: trigger's mis-aimed mutant that would have logged a false survivor
  ("looks exactly like a real hole"), seedgo's refuted round-6 mechanism
  rewritten in place with attribution rather than deleted, drone's stale
  held-tree list corrected from git rather than memory, and skills' recurrence
  of the poisoned-baseline species caught by ai_mail's guard — the guard is
  the cure, not the `finally`. Seven branches: memory 1596×2, seedgo 2808×2,
  spawn 902×2 (14/14 mutants), flow 1022×2 + bare-checkout, drone 1349×2,
  skills 355×2 + 1119 lib, trigger 1087×2 with 0 skips.

- **Round 6: the interpreter is part of the platform — the 3.10 leg convicted
  the instruments, and the fleet cured the capture** (FPLAN-0461 continued).
  Round 5's CI left two named clusters and both are dead. The Python 3.10 reds
  were all *arming probes refusing honestly*: on ≤3.10, `pathlib` reads
  `os.path.realpath` (and `os.getcwd` — skills) through a `_NormalAccessor`
  that **captured its copy when pathlib was first imported**, so rebinding the
  module attribute rebinds a name nothing reads again and the injected worlds
  never armed. My first diagnosis ("3.10 doesn't delegate") was wrong — memory
  read the CPython source and refuted it, seedgo reproduced the capture by
  construction, and the correction propagated mid-flight; the cure is four
  hasattr-guarded lines (patch the captured accessor too) and the same world
  arms on every interpreter — no version tables, no skipif. Eight branches
  cured, each making the 3.10 row *falsifiable locally* by rebuilding the
  capture on 3.12 rather than asserting from the CI red. The round's traps,
  each measured: patch as `staticmethod` or a plain function eats the path
  into `self` and raise-shaped pins stay green for the wrong reason
  (return-value pins cure); exercise through an instance; probe with absolute
  paths (a relative path convicts for the path's *shape* — skills had this
  live); emulations must capture eagerly (flow shipped the trap inside the
  instrument built to avoid it and their ninth mutant caught it); `cwd` and
  `resolve` ride *different* captured attributes (skills' M16). Structural
  finds beyond the cure: spawn's gate was reporting one red while several
  sibling pins *silently skipped* under an unrelated platform message (gates
  now fail, not skip, where no platform reason exists); trigger's version
  escape hatch cited the retracted diagnosis and was green only by
  import-order luck on the one leg where order decides — deleted, and made
  falsifiable on a host that cannot produce the condition it excused;
  memory's windows-setup pins (the last two on the board) got the six-row
  os.name table with both nt rows measured twice. Seedgo's sentence carries
  the round: *a careful falsifiable table on a wrong mechanism is more durable
  than a guess — read the source before keying an instrument to it.*

- **Round 5: the round-4 pins met the real Windows platform, and every red
  taught a structural rule** (FPLAN-0461 continued). CI on the round-4 commit
  came back red where the new pins *measured the platform for the first time* —
  POSIX facts asserted as universal. Eight branches cured by their owners:
  per-platform expectation tables replace universal assertions, each stating
  which rows are measured live here vs derived from the CI red (a CI red is a
  *negative* measurement — it proves not-unconditionally-X, never which value;
  recording a guess is inventing a measurement, so unfalsifiable rows are
  pinned as `None` *decisions*). The round's converged rules, each named to its
  finder: **emulate the platform, not just the denial** (prax — getcwd-denied
  Linux is a genuinely different world from Windows-with-no-cwd, because
  `ntpath.abspath` never touches getcwd); **split cause / outcome / link into
  separate pins** (canary — a future red names its own mechanism, and the link
  pin makes derived rows falsifiable locally); **key the table on the variable
  that actually decides** (ai_mail — `os.name` answers which path module,
  `sys.platform` answers does-the-filesystem-fold: darwin folds on posixpath);
  **a table row no local platform can falsify enters silently** (ai_mail's
  darwin mutant — the original defect's shape, one platform along); **separate
  the judgement from the world** (commons — their first rebuild shipped the
  unreachable-branch species one level up in the instrument: four survivors all
  mutated branches Linux never executes; judgements became plain functions fed
  synthetic values, every platform case reachable on any host); **a line-scoped
  waiver whose number moves fails open and silent** (trigger — one round-4
  edit shifted four bypass.json waivers, resurfacing as "new" violations;
  re-derive, never hand-adjust); **mutate the source, never the test** (daemon
  — deleting a currently-true assertion proves nothing). Real defects found
  under the noise: prax's log-dir resolver mkdir'd the literal `<stdin>` (21
  such dirs in /tmp; reserved-character crash on Windows — cured, bracketed
  names → "unknown"); backup's fence compared one normalised operand against
  one raw (refused its *own kin* on Windows — cured both sides); trigger's
  `_systemctl` had never been executed by its suite (extraction exposed it;
  `return True` left all 40 tests green — 9 pins now). Exactly-once log pins
  on Linux cured at conftest altitude (flow/memory — the bare-checkout world
  logs a fallback diagnostic *inside* the test window on CI only). Daemon
  caught their own CI-red-in-waiting pre-commit (a pin asserting the
  gitignored `tools/` exists — verified in the absent world). Composed
  universe green before commit; per-branch by owners, both rootdirs, audits
  100 across every touched branch.

- **Round 4: the import-time dead-cwd defect cured in all 16 branches (~150
  sites), and the instrument that watches the cure** (FPLAN-0461 continued).
  `ntpath.realpath` reads `os.getcwd()` unconditionally and `Path.resolve()`
  routes through it, so every module-level resolve *reached at import* is an
  import-time crash on Windows — and every branch's `handlers/__init__.py`
  guard called `inspect.stack()` first, masking its whole tree (the mask ran
  two layers deep in daemon/api/backup via a json_handler root constant, three
  in skills with two *parallel* second layers — counts only become true as
  cures land; re-measure until the number stops moving). Each branch cured by
  its owner, red-first in two subprocess worlds, mutants run not assumed:
  guard walks on `sys._getframe` over `co_filename`, module-level resolves
  routed through one guarded `module_file()` helper per branch (diagnostics
  inside their own protection — daemon's rule, stderr deduped last resort),
  the hot-path `_get_caller_module_name` stack walks cured to
  `sys._getframe(2)` with pins asserting the audit trail still *answers*
  (aipass's shared fix reaches five shims including spawn's citizen template —
  newborns born cured AND born pinned). The deleted second stack walk proved
  unreachable from import-shaped pins in nine independent reproductions
  (restoring the defect left 1118/1120 green in aipass), so every tree carries
  an AST ban — and spawn's capstone correction landed the behavioural sibling:
  the branch IS reachable by calling the guard directly from a `-c` child,
  adopted fleet-wide within 90 minutes of the relay. Five harness species now
  named in the record: a mutant with no pytest output is invalid, never
  survived (canary); the lookup frame must be the compiled one (aipass); a
  world can be too hostile to convict — denying getcwd *hides* the stack
  defect inside `getabsfile`'s own except (prax); a world spelled too
  realistically is silently inert — script-run probes make every frame a real
  file (commons); a negative control that can fail for the ban's own reason is
  a second ban, not a control (spawn, confirmed retroactively by prax).
  Report-only for Patrick's ruling, all measured: the handlers fence is
  decorative in fact (backup/skills proved a foreign import ALLOWED, causally
  — door closed = blocked), and one-word branch kinship tests admit any
  same-named directory as kin (api: drone's own `api/` subdir admitted; skills:
  14 same-named dirs on this machine). Rode along: daemon's `_calc_next_run`
  read the wall clock instead of the timestamp it was handed — `next_run` had
  advertised impossible fires on the human status surface daily (13 pins, 3
  live records repaired); skills' `get_search_paths` raised on dead cwd taking
  every list/info/run down — cured by asymmetry (discovery skips, creators
  refuse); the medic warning-storm species (a WARNING logged at module import
  escalates on volume alone) moved to first-use, deduped.

- **The two-test-universes defect class, closed at root cause across 7 branches**
  (FPLAN-0461, night shift on Patrick's brief "every change we make it turns
  red — is it a norm?"; answer: no). The commit gate runs each branch's suite
  with rootdir pinned to the branch by its own `pytest.ini`, so the repo-root
  `conftest.py` never loads there — while CI composes every conftest in one
  process under xdist. All 30 CI reds classified with zero speculation, each
  fixed by its owner, every fix independently verified by devpulse:
  - repo-root conftest guard (devpulse): consult the handler's own
    `_current_json_dir()` seam instead of re-deriving from constants — the
    substring scan read seam-adopted modules as unpatched and skipped writes
    their tests asserted on (12 reds).
  - prax json_handler 1.4.0: the import-time anchor was seeded WITH
    `AIPASS_TEST_LOG_DIR`, violating the env-independence its own adopters
    pinned as load-bearing; an env-derived anchor is sufficient for the defect
    alone, no reload needed — and prax's own suite was green only by
    import-order luck (2 reds). Subprocess import pins now bite in both
    universes.
  - drone registry tests: a stand-in installation that passes the credential
    gate on merit, not unverifiability; the memory-gateway import moved inside
    the never-take-routing-down guard (5 CI-only reds, one a real bare-world
    import crash).
  - memory: marker7 guarded on `live_all_tiers` — existence is not sufficiency,
    a registry with no rows or no external tier is a half-present world that
    skips with a named reason (2 reds); plus registry_scope's module-level
    `Path.cwd()` fallback replaced with a `__file__`-derived source root
    (the import-time crash behind drone's).
  - **the CI polluter, fingerprinted and killed**: `tests/e2e` `routing_root`
    wrote a 3-branch synthetic `AIPASS_REGISTRY.json` at the repo root for a
    whole module — true sequentially, poison under xdist (40/60 parallel reads
    saw the synthetic in @aipass's repro), and on a live machine it overwrote
    the real fleet registry with the backup held only in process memory
    (kill -9 repro: the 22 rows existing nowhere). The fixture now builds a
    throwaway root under tmp — no repo write exists, no teardown left to fail.
    Only macOS/Windows CI run e2e, which is why only those jobs saw `{'core'}`.
  - aipass `find_registry`: absence is `None`, never `Path.cwd()/…` — the old
    code answered a question about one directory with a file from wherever the
    caller stood; paired with spawn's `load_registry` minting a fresh
    `metadata.id` for missing paths, two lines conjured a registry with a new
    trust credential out of nothing (loaded gun, unfired, disarmed). Spawn moved
    the mint to `resolve_project_credential`, called by name from the two
    create sites — the create path knows it is creating; the load path knows
    nothing — and hardened all fifteen resolver call sites to refuse in their
    own vocabulary (four were live `None.exists()` crashes, one an
    AttributeError escaping a narrow except inside the delete-protection
    check). Their live-fleet baseline test now guards on what the WORLD
    contains, not where the process runs (`GITHUB_ACTIONS` was protecting one
    CI provider and nobody else).
  - spawn: the read-torn race harness reports weather as weather (warmup until
    both sides prove live, skip-with-counted-reasons backstop, tear-check-first
    pinned so a skip can never mask a real tear; proved under load 5.29 with
    races exercised) — it was the one intermittent red in prax's 1380-file
    fleet batch.

- **Round two, caught by the first round's own pins on CI** (same night):
  - memory: nine private repo-root walks with `Path.cwd()` fallbacks became ONE
    implementation (`handlers/repo_root.py`) behind the existing names, with a
    parse-tree pin — no lane may define a walk that is not a delegation, no
    `return Path.cwd()` anywhere in apps/ — that named all ten offenders
    red-first and carries a positive control (a mutant that blinded the filter
    left the suite green; skip-reads-green, caught twice in one night). One
    reversed test told the whole story: `test_find_repo_root_falls_back_to_cwd`
    had pinned the defect as the contract — a green test standing guard over
    the bug.
  - prax `config/load.py`: the same cwd fallback under `get_system_logger()` —
    called at module level by nearly every handler in the fleet — fixed within
    the hour of memory's cross-branch report (memory verified 11/11 bare-world
    imports clean, then removed their own xfail hatch the moment the blocker
    died).
  - **hooks bash_writes 1.2.0 — the Windows fence was open**: `shlex`'s POSIX
    lexer eats backslashes as escapes, so a drive-absolute foreign path arrived
    as one relative token and resolved LOCAL — every scripted-lane category
    allowed with exit 0 on Windows CI. Fixed by dual-dialect lexing with
    unioned write targets (reading `\` as a separator can only ADD components,
    so local can never become foreign by it — the reverse is exactly what
    happened); unwalkable foreign roots published as NOT_CAUGHT entry 8, never
    a silent allow. Reproduced and pinned on Linux — the bug needed a
    backslash, not a Windows box.
  - seedgo: three "deliberate violations" ruled — all three were checkers
    overclaiming, all three taught instead of waived (pure-declaration modules
    `not_applicable` for json_structure; relaying a captured subprocess stream
    is an authorship class, and crossed streams are now caught under the same
    rule; unused_function says "no caller in this branch" and warns about
    cross-branch/dynamic callers it cannot see — the dead-code checker had
    nominated the fleet's most load-bearing function, memory's
    `changed_entries`, called by hooks' write gate via importlib). Adopted
    rule: a structurally detectable exemption goes in the checker; a waiver is
    only for what cannot be measured.
  - drone: the no-cwd sweep's own new test asserted a fact about the machine
    (registry presence) instead of the function — rebuilt against stand-ins,
    claim strengthened to "carries a project marker" (the weak claim was
    satisfied by the function's own last-resort return); two POSIX separator
    pins converted to `Path.parts`.

- **Windows joins the one universe: the case-fold registry defect, closed at
  every site in the fleet** (FPLAN-0461 round 3, dawn shift). ef029782's
  windows-setup leg — the last red gate, 20/21 green — failed only in the
  night's own new tests, and the diagnosis found a real cross-platform defect
  under the noise: pathlib's glob is case-insensitive on Windows (and default
  macOS), so `*_REGISTRY.json` also matches `*_registry.json` — and the bait is
  everywhere (ten `flow_json/*_registry.json` plan counters, spawn's dotfile
  `.template_registry.json` in every branch; pathlib's `*` matches dotfiles).
  CI's proof: `find_registry()` served `drone_command_registry.json` as a
  trust-anchor candidate. **44 exposed walk sites cured across 9 branches**
  (drone 13 → one `registries_in` reader; aipass 7 incl. the shared
  `registry_discovery` everyone imports; ai_mail 6 — two more than any list
  named, one hidden behind a CONSTANT pattern a literal grep cannot see, and
  the live harm measured rather than assumed: a walk that ENDS at the decoy
  resolved an external caller to None, and `find_project_root` handed the
  fence a wrong root; seedgo 9 → one reader + the measured two-clause checker
  discriminator, build queued; memory 4 — detector PERSISTED the folded match
  into fleet state forever and a nearer decoy `break`-ended the walk above the
  real registry; spawn 2; prax 1; commons 1 — whose
  `name != "AIPASS_REGISTRY.json"` filter was the instructive near-miss; and
  devpulse 2). Fix shape everywhere: glob, then re-check the name with
  case-sensitive `endswith("_REGISTRY.json")` — suffix only, never the stem,
  so externally-named registries survive. Memory's follow-through went one
  door further: a cased LITERAL folds too, so `find_repo_root`'s
  `(parent / "AIPASS_REGISTRY.json").exists()` could accept a lowercase file
  as THE repo root — `exists_exactly` now guards it and three sibling lanes.
  All pins red-first on Linux by emulating the widened listing, with positive
  AND negative instrument controls (aipass's first control re-implemented the
  matcher's logic and proved nothing while the walk visited zero files;
  commons measured that without the control, breaking the emulator turns every
  pin green). Precedent noted for the record: prax's branch_detector and eight
  aipass sites already carried the exact cure — it never traveled to the sites
  that globbed.

- **The dead-cwd test world, made honest on Windows** (same round). The night's
  deleted-cwd pins died at SETUP on Windows — `WinError 32`, the OS locks a
  process's cwd, the world is unbuildable by chdir+rmdir. Two rulings, both
  pinned, each owner choosing per claim: memory's — pin the CONDITION
  (`os.getcwd()` raises), not the CAUSE (a deleted directory): inject a raising
  `getcwd` in the child, licensed by `TestBothConstructionsAgree` (both worlds
  must agree on POSIX or the stand-in expires); drone's — Windows removes the
  RECIPE, not the STATE (a disconnected share is a live dead cwd), so the
  deletion tests keep running where they can under a registered
  `deletable_cwd` marker whose skip is itself pinned observable from Linux,
  with portable siblings supplying the state and the one genuinely lost claim
  named out loud. Spawn measured which ruling their defect needed instead of
  picking by taste, and added the round's best control: a negative control for
  the positive control, after a mutant showed a lying `CONTROL_LIVE` probe
  turning every portable pin vacuously green. Prax's entry found the deeper
  vacancy: their dead-cwd pins passed on dev machines because the marker walk
  succeeds there and the cwd fallback never runs — the probes now hide the
  marker so every machine runs CI's world. Hooks' two remaining Windows reds
  were separator spellings in the tests (`Path.parts` tail comparison now) —
  and the fence-fix measurement arrived: TestScriptedLaneCatches is GREEN on
  the real Windows runner; the dual-dialect gate holds on every OS.

### Added

- **daemon+ai_mail+hooks+memory: Vera woke** (FPLAN-0460 closed, c9d0327e —
  entry owed from that commit). The first external citizen fired by the real
  clock; scheduled manager wakes are headless dispatches under Patrick's
  rulings (always bypass permissions, managers-are-Fable-only-managers, marked
  sessions, blocked-is-not-ran three-state runstate); hooks edit_gate 1.7.0
  verifies the admin seat through ai_mail's 5-leg grant and bash_writes.py
  closes the scripted lane for everyone else; memory's entry_limits 1.6.0
  refuses what a write AUTHORS, never what it CARRIES.

## [2026-08-30] — the audit-tests lane: testing the tests (DPLAN-0320 campaign) · v2.8.0

### Added

- **seedgo: the audit-tests lane — the fleet's first real test-quality measurement**
  (`drone @seedgo audit-tests <target>`, FPLAN-0459 phases 1–5, DPLAN-0320/0321
  campaign). One day from directive to running product: 2,453 fleet tests read
  by eyes (taxonomy of 41 defect species, three laws), a signed 2,053-line
  design (three adversarial review rounds, 21 findings, both sides caught wrong
  once on the record), and a working lane. What it does: copies the target's
  tree (M10 — measured by before/after fingerprint, not asserted), runs the
  suite under a `sys.addaudithook` write gate with a mandatory canary
  (refuse-if-not-caught), attributes every live-state write to its exact test
  nodeid, runs nine static nominators (OR-ESCAPE, NO-ORACLE, MOCK-DRIFT…
  nominate-only — static never convicts), and publishes a lawful artifact:
  refuse-never-zero, unbuilt probes say `not_applicable` with a reason, the
  gate prints its own blind spots (child processes, sqlite3 handles) beside any
  100 so a clean score can never be read as proof. Advisory only — SCORED is
  not GATING; exit codes demoted to hints. First live results: backup hygiene
  0/100 (807 attributed write events from 64 tests, including 4 records touching
  `~/.secrets/aipass/`), canary 100 clean. Old Test_Quality standard measured as
  a constant (100% on all 18 citizens by construction) — retirement by recorded
  ruling rides the fleet announcement.
- **aipass: OSS test-quality tooling research** (`docs/test_quality_tooling_research.md`,
  1,721 lines) — five research agents, licenses verified from LICENSE files,
  tools run against this fleet. Verdict: the category is empty in every language
  (§0.1 checks the commercial field too — CodeRabbit resells OSS linters under
  an LLM and never runs your suite; the one product selling our criterion is
  JVM-only). Two published ideas adopted: the AssertionError kill-split (Law S9)
  and per-function extreme mutation (banked).

### Fixed

- **prax: the commons live feed prints full agent messages** — `_snippet()`
  capped every post/comment at 100 chars, which made boardroom debates
  unreadable from the phone; long bodies now render whole (multi-line, no
  ellipsis) and agent text is markup-escaped so brackets survive Rich verbatim.

- **devpulse watchdog: cancel no longer reports KILLED for a process that survived
  SIGTERM** — `registry.kill_watch` returned `"killed": killed or True` (always
  True), so a runaway pid that ignored the signal was announced as killed while
  still running; the log line beside it already told the truth. Now returns the
  measured value; the presenter's existing `FAILED` path renders it. Red-first
  pin: a child that installs `SIG_IGN` before the kill, asserts `killed: False`
  + the handle still deregistered (FPLAN-0455, todo 172 — found by the dead-code
  map on 2026-08-22, all prior tests only covered pids that die).

- **seedgo: CLI parsers refuse unknown tokens** — `audit -tests @backup` used to
  silently drop the unknown token and run the standards audit on cached data (a
  typo executing a different real command); now every unrecognised argument
  refuses loudly with a did-you-mean (`ARGV`, exit code 7). `audit tests` is the
  canonical spelling of the new lane (parallel to `audit aipass`), `audit-tests`
  a permanent alias, and the word `tests` refuses ambiguity if a standards pack
  ever claims it.

- **devpulse: owner-guard refusal-exit pins** (`test_owner_guard_refusals.py`) —
  the 2026-08-22 exit-0 refusal fixes (feedback + admin_grant guards rendered
  with `warning()`, which skips `mark_command_failed()`) had scar docstrings but
  no tests defending them. Five pins now assert the failure MARK, not wording;
  both mutations (error→warning) bite with exactly one failing test each. The
  one remaining `warning()` in devpulse (feedback compose, anonymous-sender
  advisory) judged legitimate — the command succeeds, degraded — and the verdict
  pinned in a comment so future sweeps don't re-flag it.

---

## [2026-08-28] — residency convergence: the fleet definition becomes a rule (DPLAN-0319 wave 3) · v2.7.22

**Residency convergence — the fleet definition becomes a rule, not a list
(DPLAN-0319 wave 3, FPLAN-0454)** — four consumer lanes and one gateway, each
built by its own branch, each independently re-verified before commit:

- **@memory `registry_scope` 2.0.0** — discovery is registry-led and shallow
  (`projects/<name>/*_REGISTRY.json`, one level, explicit dot filter);
  classification reads the passport's `citizenship.residency`; trust asymmetry
  pinned: a passport can never ADD scope (no passport walk exists — baud's
  `.backup/` copies carry real resident-declaring passports, so a walk counts it
  three times) and never REMOVE a core citizen. `trinity_push` and `detector`
  converged in the same pass. Then the micro-pass deleted `RESIDENT_REGISTRIES`
  outright: no list of residents exists anywhere in @memory now — a rule the
  passports answer. One legacy test was found green while defending the exact
  design wave 3 overturned, and was inverted with the reason written in.
- **@ai_mail** — the deliberate mirror and its AST drift pin died together,
  replaced by 12 behavioural pins of ai_mail's own resolution; live answer
  unchanged (same four residents). Banked: the verified-admin bridge
  (`get_project_tree_branches`) lacks the dot filter — ghost registries in
  `projects/.archive` leak in, masked today only by depth.
- **@daemon discovery 2.0.0** — the blind projects/* walk is gone; two-key rule
  (registry active AND passport resident) replaces the de-facto on_hold
  inclusion (all three consumer lanes checked before flipping — load-bearing for
  nothing). Real hole proven: `SKIP_DIRS` never covered `.archive`; a planted
  ghost registry WAS discoverable. A sixth named refusal added: a registry row
  whose directory is missing no longer vanishes silently.
- **@spawn modules gateway** — `get_template_dir` + `refuse_legacy_class`
  re-exported with an identity pin (the export IS the handler's callable), so
  **@seedgo retired its drift-pinned class-registry mirror** for the import.
  Fixing the door meant fixing the rule that barred it: `check_no_orchestration`
  contradicted `check_handler_independence`; orchestration is now an own-branch
  rule, and the widening admitted zero hidden violations fleet-wide.

Fleet receipt unchanged throughout: 18 core + 4 resident = 22. Adding a resident
is now a deliberate write in a tracked passport plus a registry entry — no
central file edit (stated trade, Patrick can overturn). Banked for later:
spawn's cross-branch handler guard is pre-empted at import time by an eager
package import (pinned both directions, not fixed); resident repos still need
their retro dev branches (no git door into nested project repos — refusal
recorded, no workaround taken).

---

## [2026-08-28] — passport 2.0: the identity file gets the trinity treatment (DPLAN-0319) · v2.7.21

**Telegram stripped from the concierge (2026-08-28)** — Patrick's ruling from
the docker live test: BAUD is the phone face now, so @aipass's Telegram-bot-host
identity (passport purpose/what_i_do/principle/tag), `telegram_readiness.py`
(retired as a tracked `.disabled` rename — `.archive` is the disposal zone, so
moving tracked source there would be a delete), the doctor telethon row, and all
README/help mentions are gone; the @skills telegram skill and @api stay — the
capability retired from the concierge's identity, not from the system. Riding
with it: doctor's drone row root-caused and reconciled (`18 citizens + 1 routed
service (@git)` — the mystery 19th was @git, routed but passportless; fixing it
exposed and killed a substring-count bug in the same line), a split-brain
AIPASS_HOME doctor check (terminal vs Claude Code trees compared, silent on
agreement), the wizard now prints which branch it clones, and @aipass's seed
re-exported clean. Merge-train CI fix: spawn's R3 archive pin asserted
`templates/.archive/` on clean checkouts that can never carry it (gitignored) —
the archive half now skips loudly as an environment fact.

**Docker dev-container round (2026-08-28)** — the dev image (`aipass-test`)
proved the whole cold-clone story and caught what CI structurally cannot:
`./aipass install` was DEAD on dev — setup.sh still passed the retired
`aipass_framework` class and spawn's refusal (correct, by design) killed the
installer before settings.json existed; one root cause, eight cascading FAILs,
zero suites red. Fixed to `specialist` as the refusal instructs. Then the
banked mint-all-core follow-up landed: the installer bootstrap now asks
`find_seed()` first — every branch shipping a tracked seed births its live
passport through spawn's own `mint_and_write` (fresh uuid4 citizen_id,
registry_id from the fresh registry's metadata.id); template render fills only
local/observations (seeds carry identity, never memories); a bad seed kills
the install loudly. `tests/docker_checklist.md` (new) is the contract;
docker_dev_verify.sh grew phases 7–9 (seed-minted passports incl. stamp
sha256 vs seed bytes and verbatim identity diff, memory-file hygiene, doctor
read in full). Final run 30/30; an INDEPENDENT sub-agent audit then confirmed
7/8 claims with stronger checks (full-document diff on all 18, double-install
byte-identity, two clean containers = 36 unique citizen_ids), split the 8th
honestly (`./aipass install` re-run exits 1 only when `$AIPASS_HOME` is absent
from a non-login shell — the wizard prompts and cancels on EOF; file state
untouched), and banked the warts: `aipass install --non-interactive` targets
~/AIPass ignoring the clone you stand in (@aipass lane), drone counts 19
citizens vs registry 18, concurrent installs on one host can die silently.
Cold-machine doctor: 35 pass / 2 warnings (both container-env, inert) /
0 errors, admin lane dark-and-valid per the fail-closed design.

**The rulings (Patrick live, 2026-08-27 night)** — devpulse's passport becomes
the 2.0 schema: machine facts on top (document_metadata → branch_info →
citizenship), agent-written soul below (identity, with principles moved
inside); classes become `manager | specialist` (aipass_framework renames —
"every branch is an expert in its domain"); new `citizenship.residency`
(core / resident / external) splits the job from the posting; ONE template
replaces the aipass_framework/project_agent fork — the first agent minted in
a project gets manager, every later one specialist; new projects get main +
dev at creation and every agent defaults to `git_branch: dev`.

**spawn — the epicenter build**: new `templates/citizen/` (both classes mint
from it; old template dirs archived, never deleted); class_registry reworked
with loud refusal of legacy names; the first-agent rule wired from the
already-computed `citizen_number == 1` signal — and a CLI default that was
silently defeating it fixed and pinned both directions; a dedicated one-shot
migration tool (`migrate-passports`, dry-run default, per-file
`.pre_v2_backup`, idempotent across a date roll, 20/20 mutations bite) built
but NOT run — the fleet flip is its own GO. Dry-run receipt over the live
fleet: 22/22 would change, 0 errors, 0 unrecognised fields. Beyond the brief:
resident passports' hardcoded absolute paths cured by a general relative-path
rule, and `sync-registry --fix` (a second fleet-write path) now takes the
same backups first. 668 tests passed / 1 skipped, re-run identically from
branch dir and repo root by devpulse.

**hooks — the silent-vanish fix, landed first**: identity injection read
top-level `principles` only; post-migration the Principles line would have
silently vanished from every agent's injected prompt. Now reads
identity-first with top-level fallback — both layouts render byte-identical,
proven against real passports. 1709 passed / 2 skipped, re-run exactly by
devpulse; 4/4 mutations bite.

**seedgo — the auditor refuses to import the audited**: architecture_check
stopped raw-joining citizen_class onto the templates path (broken for
manager branches for months per seedgo's own stored audits). The brief's
suggested spawn-import failed seedgo's own checklist twice, so the fix is a
drift-pinned mirror of spawn's class registry (the RESIDENT_REGISTRIES
precedent) with three refusal doors kept apart: legacy (migrate), forbidden
(admin, never a class), unknown (never existed). Un-migrated passports now
score a truthful named violation quoting the cure. 1954 passed / 1 skipped,
exact re-run; 5/5 mutations bite. Side finding banked: the audit cache was
serving 12/18 branches pre-archive results (99 shown, 97 true).

**aipass — `aipass new` revived on the new mint path**: it was dead at the
door since the spawn commit (named refusal of the retired class — the
planned seam, captured live before any edit). Now: no class passed (spawn's
first-agent rule mints manager), `git init` cuts dev AFTER the birth commit
with HEAD left on dev (ordering pinned — dev from an empty repo would never
merge back), and git_auth's passport-owner fallback retired with a refusal
that names the rule change. Live CLI receipt in a throwaway host: main+dev,
HEAD dev, 2.0.0 manager passport, no owner key, live registry md5-identical.
1061 passed / 0 skipped, exact re-run.

**THE MIGRATION RAN (2026-08-28, Patrick's GO)**: 22/22 migrated, 0 errors,
per-file `.pre_v2_backup`, idempotent re-run changed 0; drift canary flipped
to 2.0-only (schema-1 lane removed). Full fleet audit: Architecture 100
fleet-wide — the 15 legacy passport violations cured.

**gitignore — the rename had silently untracked the template's payload**: the
spawn-template negations still named the retired `aipass_framework` /
`project_agent` dirs, so after the `citizen` rename 17 payload files
(birth-certificate template, inbox scaffold, `{{BRANCH}}_json/`, logs/,
DASHBOARD, dropbox/, tools/, docs.local/, `.archive/`, `.spawn/`) left the
public repo — the exact ship-incomplete bug the 2026-08-17 CI red documented,
reintroduced by rename. All template negations consolidated into one
wildcarded `templates/*/` block (name-specific lines are how this breaks) and
the payload restored. Verified: template files are pure placeholders — no real
mail, signatures, names, or machine paths; live-branch ignores unaffected.

**aipass — the admin ceremony becomes findable (Patrick's ruling: admin stays
bolted to devpulse, single-seat, no transfer)**: new `docs/admin_setup.md`
(the ceremony as the live surfaces state it: keygen → mint → @spawn registry
flag → verify; keygen --force = revocation), README "Admin setup" section
placed above the help-lane truncation threshold so `aipass help` actually
surfaces it, and a doctor row that reports lane state (lit / dark / partial —
partial never rounds up) as PASS-glyph info, never a nag: it observes four
presence facts and refuses to reimplement the HMAC verdict (pinned — no
hmac/hashlib, no devpulse import, key file content never read; the
authoritative check stays `admin_grant verify`). A dark lane is a valid
end-state, and on dark/partial the row names the doc, never a ceremony
command. 1080 tests / 0 skipped (+19 pins), 2/2 mutations bite, seedgo 100%
overall — re-verified independently by devpulse from both rootdirs.

**PASSPORT SEEDS (TDPLAN-0017, Patrick's GO)** — the tracking ruling landed as
**tracked soul, untracked live**: each core branch now ships
`.aipass/passport.seed.json` (its live passport minus the four machine-local
facts: registered, registry_id, citizen_id, and the stamp), so identities ship
with the repo while `.trinity/` stays permanently out of git's reach — the
ignore IS the pull protection, and seeds are new paths so existing installs
can't collide on pull. Ruled from a 12-pattern prior-art survey (dpkg
conffiles, RPM %config(noreplace), ucf, .env.example drift, chezmoi, Copier,
kubectl last-applied; git-native tricks disqualified by git's own docs — four
independent systems prove you need a record of what-was-last-shipped beside
the live copy). Built as three parallel lanes: **spawn** grew `export-seeds`
(dry-run default, idempotent, generated-never-hand-edited) plus a seed door in
the create path — target-exists-without-passport (the fresh-clone shape) now
births from the seed through closed-schema validation, minting fresh local
ids plus a `citizenship.seed = {version, sha256}` stamp (dpkg's three-way
fingerprint, making future update machinery retrofit-free; that machinery is
deliberately deferred until real users exist). The validator REFUSES unknown
keys at the two publish gates (a retired field must not ride into every
clone) while the transform preserve-and-reports. **seedgo** measured that
trinity judges passport EXISTENCE only, so the stamp was structurally free —
proved with pins instead of edits, plus a new seed suite whose leak-guard
walks whole documents for machine-local fields (live-proved red on a real
passport planted as a seed). The 18 seeds exported and verified: idempotent
re-run 0 changed, round-trip identity byte-equal, zero leaks. core.py crossed
the 600-line standard in the build; the target-exists lane (adopt +
birth-from-seed) split honestly into `handlers/adoption_ops.py`, spawn audit
100 overall after. Bars: spawn 666→728/1 (20/20 mutations), seedgo
1954→2040/1 (9/9 mutations, 54 seed-pin instances live), both re-run
independently by devpulse.

**Still gated on Patrick**: `sync-registry --fix` stays hot?, and wave 3
(residency consumers converge; resident repos get dev branches; registry_path
field retirement — zero code consumers, canonical value names a file that
doesn't exist).

## [2026-08-27] — v2.7.20: the trinity pattern lands — fleet 22/22 at trinity 100

**CI round 2, four fixes in one evening (PR #743 merge prep)** — the full
matrix run surfaced 5 failures across 3 jobs; every one root-caused, none
patched over. **memory**: the 3.10-only red was a MagicMock with no
`__path__` (3.12 short-circuits imports on sys.modules; 3.10 walks the
parents, and the optional-bus ImportError swallow turned that into an empty
event list) — real ModuleType stand-ins now, plus a reachability assertion
so bus-unreachable can never masquerade as bus-not-fired; and the resident
guard gained a second discriminator, `live_residents`, which reads the four
registry files with pathlib rather than asking the resolver about its own
inputs — a guard that consults the code under test deletes the failure it
exists to expose (proven: `if False` mutation gives FAILED, not skipped).
**api**: the Windows mock wasn't wrong, it was unreachable — is_supported()
returns before subprocess is touched; one red was five, plus six vacuous
greens asserting exactly what the untouched gate returns. New
SupervisorUnreachable: a probe that FAILS on a capable machine refuses
instead of answering no-unit — on this host the old path printed "No server
is running" about a server serving requests. **aipass**: the mkdir flag hid
a json.dump behind it (checker reports first hit only); the writer moved to
json_handler and came out stronger (fsync + Windows retry the hand-rolled
version never had), with the write_json returns-False-never-raises trap
re-raised, and all five forbidden tokens source-scan pinned. **seedgo**:
trinity_check.py split 1557 → 429 engine + 1231 groups at the I/O seam,
proven by running pre-split and post-split over all 18 live branches in one
process — full result dicts byte-identical; `all_groups(ctx)` pins the
roster because a dropped group scores HIGHER (the weighted mean divides by
less); save_cache's real hole was BaseException, not a hard kill; the
orphan-tmp flake now claims only what it can support (this session left no
new orphan, pre-existing ones warned by name). Fleet 22/22 trinity 100
held through all four.

**fix(aipass)** — the last drifted citizen reaches trinity 100, and the
stray `user` section turns out to be aipass's own profile.py writing on
read since June (PR #743 merge prep): the fleet push pruned the section,
get_user_profile() recreated it minutes later, and init_flow's
`existing.get("first_seen") or now()` silently reset a 2026-06-10 date to
today — so a 2.5-month-old artifact presented as same-day drift by an
unknown author. Fix relocates the profile to aipass_json/user_profile.json
(profile.py never writes .trinity again; legacy section read once as
fallback, never written back; true June first_seen restored). Two live
defects caught while verifying: the test suite was mutating the REAL user
profile (a sys.modules MagicMock silently bypassed by from-import binding —
only two test files TOGETHER corrupt it), and the first filename chosen
collided with json_handler's managed triplet, which regenerated — erased —
the store through the very call that logged the save. 1041 passed (+7),
trinity 100 all nine groups. **FLEET: 22 of 22 at trinity 100.**

**fix(memory)** — CI guard for live-fleet tests, 8 guarded not 5 because
three greens were vacuous (PR #743 merge prep): a `live_fleet` fixture in
tests/conftest.py skips with @seedgo's exact wording when no
AIPASS_REGISTRY.json exists — a fixture not a helper import, because dotted
sibling imports break on CI's repo-root rootdir (a trap this branch was
caught by once already). Checks BOTH repo roots (registry_scope +
trinity_push resolve independently). Red reproduced first by masking both
_REPO_ROOTs at an empty dir — exact CI failure list remade locally. The
deviation on the record: 3 tests that PASS on clean CI were guarded anyway,
because an empty fleet satisfies every subset assertion — a green reporting
a measurement that never happened. Whole suite swept under the mask from
both rootdirs: zero other live-state dependents. 1227 passed / 5 skipped.

**feat(spawn)** — newborns arrive with a receipt, retirees leave a named
archive (DPLAN-0318 marker 7, spawn's leg): measured first — a minted
citizen scored trinity 77, and only half of that was the missing receipt;
spawn's own seeds carried a status block the standard deletes, wrong-case
managed_by, and _usage/meta drift nobody had ever measured. receipt_ops
stamps at birth AFTER mint-verify and BEFORE registration (ordering pinned),
reading versions from @memory's GOLD templates, not its own seeds — a
drifted seed must not mint a receipt claiming a version the fleet never
issued. Shape copied not imported (ast test pins the constant; another
asserts no aipass.memory import). Seeds rebuilt from gold with
byte-identical pins that go red on the next template bump. Adoption stamps
only-if-absent — restamping a push-stamped branch would replace a true
record with a false one. Retire now SAYS what it carried (archive path +
trinity files in the operation log — the fact a later reader can't
re-derive). Newborn trinity 100 both classes, live-minted and scored with
seedgo's real checker. 531 spawn tests, full repo 17589 passed, 12/12
mutations bite.

**fix(seedgo)** — the audit learns what a clean checkout is, and the cache
learns to see directories (CI unblock for PR #743): trinity on a tree with no
AIPASS_REGISTRY.json AND no citizen `.trinity/` anywhere now returns
not_applicable with score None — left OUT of scores entirely, because a 0
blames the branch for an environment fact and a 100 claims a measurement that
never happened (the old path actually CRASHED on None; red-first surfaced
it). Both signals must be absent — a live installation missing one branch's
.trinity still scores 0, pinned. The one `.trinity` that DOES ship (spawn's
un-ignored template, two levels down) is a named test, not a lucky accident.
The skip announces itself in the report. Defect 2, @daemon's find: the
incremental cache excluded directories (`is_file()`), blinding it to the
exact stray shape the File set rule scores — directories now watched by
presence, the morning's opposite-asserting test reversed with a banner.
1931 passed, 7/7 mutations bite. Flagged honestly: trinity_check.py now
1550 lines vs its own 1500 limit (seedgo 99 architecture — split queued,
not smuggled into a CI fix), and 2 branches drifted to 99 since the push.

**feat(hooks)** — edit_gate grandfather narrowed to todos only (1.6.0,
DPLAN-0318 circle close): the migration-era blanket exemption is retired —
exempt containers are now read off @memory's RESHAPE_ONLY_SECTIONS at call
time from the module the gate already imports (one list, no drift; a
hardcoded-copy mutation bites), with a loud-warning fallback for an old
entry_limits because exempting nothing would brick every branch carrying one
drifted todo. Pinned both directions: a drifted todo on disk blocks nothing
elsewhere, a NEW drifted todo is refused, editing a drifted todo forfeits
its exemption. Four migration-era tests REVERSED with banners saying what
expired ("the critical no-false-reject test" was right while the fleet was
mid-migration; that state ended). Verified its half was dead weight on the
blanket path before — not riding @memory's measurement now. Rider:
auto_fix's open_no_encoding matched the open( inside Popen( as a substring
— word-boundary fix after @drone hit 6 false demands on a file with no
open() at all. Hooks' own trinity 68→100; its restore mistake (top-down
numbering) was caught by the live checker, not the builder — the gate
gating its own consumer.

**feat(drone)** — timeouts stop killing legitimate work (Patrick's ruling,
DPLAN-0318 circle close): the seam is a HANG GUARD, not a per-verb budget —
default 60s→600s, and a child still producing output at its deadline buys
repeated 120s extensions up to an absolute 1800s ceiling, so a chattering
hang can't live forever while a long silent job never gets *shortened*.
Explicit `--drone-timeout N` means exactly N (extension off). On timeout the
error now replays both streams tail-first ("partial stdout (N bytes)"
banners) instead of discarding the evidence. TIMEOUT_OVERRIDES emptied: its
three raise-entries (memory 120/100, flow 90) would have inverted into CAPS
under the new base — the known-slow commands getting the least time.
Beyond the brief: `--drone-timeout` was silently INERT on interactive and
in-process lanes (found by live-proving, not tests) — both now warn; and a
checklist catch turned a restructured KeyboardInterrupt handler from
compliant to silent — seven silent catches now log. 1238 passed, 22/22
mutations bite (two equivalent mutants removed rather than tested around).
Honest edge on record: output-extension is test-proven with scaled
constants, not yet end-to-end past 600s live.

**feat(ai_mail)** — verified-admin `@all` reaches the residents + the
ambiguity warning goes quiet on proven-good cases (DPLAN-0318 circle close):
behind the DPLAN-0288 five-leg admin verification only, `@all` now adds the
four resident projects — via a named RESIDENT_REGISTRIES constant mirroring
@memory's registry_scope (copy not import; an ast-parsing test fails on
drift), NOT the existing projects glob, which would have silently broadcast
into two on-hold projects on the strength of a stale ACTIVE flag. Ordinary
citizens' @all unchanged; a verifier that raises fails toward fleet-only.
The 104× captured_branch_detection warning was a fleet sweep from ai_mail's
own process (premise corrected by reading all 104), and the quiet-gate is
PROVENANCE not success — identity source in {assigned, passport} resolved
against a catalog; a directory-name identity that resolves "successfully"
keeps warning, because that is the misattribution the warning exists for.
1340 passed, 6/6 mutations bite. New ruling banked: should resolution (not
broadcast) also stop at held projects.

**feat(memory)** — marker 7 memory lane (DPLAN-0318 circle close): the
self-healing triggers, trigger-driven never a daemon. `templates bump` fires
the trinity push (dry-run default, only a push that actually succeeded stamps
the fleet ledger); rollover normalizes the rolled branch's machine frame on
touch (entries byte-identical, sibling branches untouched); the dead
pre-trinity pusher/differ lane retired to the archive with its 67 tests;
ruling 5 confirmed (schema_version IS the receipt field, both sides already
agree); sync-lines renamed report-lines and made genuinely read-only; the
grandfather clauses narrowed to todos only (one RESHAPE_ONLY list shared by
gate and push); the fleet defined once in registry_scope.py — residents now
visible to monitor/report (44 files seen, was 38). The wifi outage's one red
test led to the find of the build: `_announce_bump` hit a NameError (json
never imported) that a broad catch logged as "Event bus unavailable" — the
bump had never announced anything; catch split so environment facts and bugs
stop wearing the same clothes. Push reports now always state todos ("N seen,
M to reshape") so silence can't hide open work again. 1225 passed from repo
root, seedgo --full 100% including trinity, mutations bite ×4.

**feat(seedgo)** — marker 7 seedgo lane (DPLAN-0318 circle close): trinity was
measured to ALREADY be a gate (non-ADVISORY, passes only at 100, failures land
in failed_checks) — so instead of performing a flip, 6 regression pins now
hold each gate property individually, including "ADVISORY still means
non-gating" and "the gate is satisfiable." The ruling-6 audit-cache defect is
dead declaratively: branch_level checkers declare their inputs as globs
(trinity: `.trinity/*`), split into content-matters vs presence-only channels
after the live tree caught the first cut always-dirty (json_handler's own
`*_log.json` outputs are written during the audit — the audit disturbed what
it measured). document_metadata extras now flagged by name (closed set,
ruling 4), guidelines content byte-compared against the gold template —
both calibrated against the pre-push `.pre_v3_backup` corpus since the push
cured the live population first (preventive, not curative — said plainly).
Fleet re-measured: 17/18 at 100, only daemon 98 (.recovery queued). 1911
passed, trinity suite 166→189, 12/12 mutations bite, first all-standards-100
audit of seedgo itself.

**feat(api)** — host-api survives reboots (Patrick's ruling after the morning
baud outage): a systemd user unit, deliberately NOT a home-grown supervisor —
the 14 death-and-restart cycles of 08-19 came from one. `autostart.py`
supervises nothing: renders the unit, reports whether systemd holds the
server, asks it to stop. `status` stops lying by construction (asks the
supervisor first — a unit-managed server previously reported "no server
running"); `stop` routes supervised stops through systemctl (a SIGTERM is a
stop the restart policy may undo) and re-checks the pid rather than trusting
the accept. Unit details each an avoided trap: `append:` logs (file:
truncates the outage evidence), `Restart=on-failure` never always,
StartLimit* under [Unit] (systemd silently ignores the [Service] spelling),
a 10-min retry window wide enough for tailscaled to assign the bind address
at boot. Installed live: pid 227641 under `aipass-host-api.service`, tailnet
200, enabled at boot with linger. 1611 tests green (re-run independently),
46/46 standards, 10/10 mutations bite.

**fix(devpulse)** — the watchdog pair moves out of `.trinity/` (File set
ruling, DPLAN-0318 circle close): `watchdog_active.json` + lock and
`watchdog_timers.json` now resolve to a dedicated `.watchdog/` dot-dir
(gitignored) — `.trinity/` holds identity and memory only. registry.py +
timer.py resolvers changed, statusline reader repointed, live wire re-armed on
the new path, 99 watchdog tests green, devpulse trinity 100 on a fresh --full
audit. 21 of 22 branches now at trinity 100; the last stray (`daemon/.recovery`)
is queued with its owner.

**fix(memory)** — todos are never archived (memory 1.1.0): spawn caught the
push's one real defect — non-canonical todos were pruned to vectors like any
entry, but a todo in a vector is silently forgotten open work ("never rolls"
must outrank the shape rule). Mechanical reshape was considered and refused on
the module's own law: a machine that invents someone's `priority` has
rewritten their open work, not rescued it. Non-canonical todos now stay
byte-identical in the file and are REPORTED per entry (uncapped — the report
is the only place left-behind work is named); `carried[]` deliberately doesn't
count them, because calling a debt clean is how it goes unseen. Blast-radius
sweep measured from the vector stamps, not the reports (catching the 46
entries the first timeout-killed fire had already cured): 388 total archived,
67 todos across 8 branches (baud 41), every affected branch mailed its own
todos verbatim with the recovery command — three via devpulse's admin lane,
since fleet-to-project mail is replies-only by ruling. The best mutation
survived the unit pins and only an end-to-end test caught it: without the cap,
the note enumeration busts 300 chars, the canonical-note guard refuses it, and
the branch is told nothing — that test now exists and bites.

**feat(fleet)** — THE FLEET PUSH EXECUTED: five months of memory-file drift
cured in one gated run. 22/22 branches pushed, ~366 non-canonical entries
vectorized-verified-pruned (every one recallable via `drone @memory search`),
563 carried, 0 refusals, receipts stamped everywhere, a canonical session note
written into every pruned branch's own chronicle. The first fire hit drone's
60s default timeout mid-run; the fleet parsed clean and the re-run pruned 0 on
already-cured branches — the idempotency canary proved, proven again in anger.
Seedgo's live acceptance guard now skips itself with the best sentence of the
night: "no drifted citizens on disk". Full fresh audit: trinity 100 on 20/22,
the two below are the deliberately-flagged operational strays (daemon
.recovery/, devpulse watchdog pair) whose relocation is owned work; every
other standard 100 fleet-wide. The README species closed the same hour — all
22 .trinity/README.md files byte-identical (spawn's md5-before-writing caught
that a template edit reaches newborns only; living branches took an explicit
copy). _CANONICAL_OBSERVATION_BRANCHES flipped from the six to all eighteen.

**feat(seedgo)+feat(spawn)** — the File set ruling executed on both sides.
Seedgo: versioned old files are legal residents of .trinity/ — the rule
matches the shape `<canonical>.pre<sep><token>` (dotless token, canonical base
required) rather than a suffix list, so the next migration needs no code
change; deliberately narrow because an allow-rule fails toward blindness — a
rule loose enough to admit `local.json.tmp` would hide torn writes in the one
directory whose job is durable memory. Fleet strays 38→4 with zero collateral
(the 4 = the deliberately-flagged operational files); seedgo relocated its own
stale STATUS.local.md while it was there. 10 red-first tests + 23 over-refusal
guards written first, 6/6 mutations bite, trinity suite 125→166. Spawn: one
generic .trinity/README.md (no numbers, no branch names — points at meta lines
and the standard instead of restating them), added to BOTH scaffold classes and
backfilled to the 6 missing branches, 8 files byte-identical; passports
surveyed first so the new template file red-boards nobody (the August lesson,
applied). The 4 outlier core READMEs (one literally says "README.md
placeholder", one hardcodes a cap) get the same file in a follow-up copy.

**feat(memory)** — the trinity PUSH is built and live-proven on canary
(@memory's build): one lane per branch — re-render the machine frame, prune
every non-canonical entry (vectorize verbatim → read back BY ID and compare
byte-for-byte → only then prune; verification failure means nothing is pruned),
and write one canonical session entry telling the agent where its memories
went. Canary live: 15 pruned, 25 carried, trinity 77→100, idempotent on
re-run, and the note's promise was tested not assumed — search returns a
pruned entry verbatim. Fleet dry-run: 366 to archive / 560 carry over across
22 branches (the push resolves residents from a named constant — the registry
lane reaches only 19), measured post-push projection 70.1→97.2 with only
stray-file/README rulings blocking 100. Over-cap entries prune like any other
(size and shape are different scan groups — the grandfathered 315-char summary
would otherwise hold branches at 96). refresh_all_tabs now scopes to the
rolled branch, closing the any-PreCompact-rewrites-the-fleet hazard; the bare
`push` alias that once fired a fleet-wide config reset is gone, and the fleet
lane refuses without --confirm. 69 new tests, 10/10 mutations bite, the
strongest pin runs seedgo's real checker over pushed output and requires all
nine groups at 100.

**fix(memory)+fix(hooks)+docs(seedgo)** — the morning-after round, all three
verified independently before commit. @memory entry_limits 1.4.0 closes the
half of B1 that @hooks proved still open: a MISSING canonical field now
returns None like any other unreadable payload (present-and-empty still
answers "") with its own reason=missing_field naming the field — 42 previously
invisible violations surfaced fleet-wide (hooks/ai_mail/api, 14 each, all
learning-shape key_learnings; grandfathered until the fleet push, like B1).
This retires 8d31a646's "memory_files.py:116 still dodges" note — true when
written, closed within the hour. @memory also fixed tab_renderer's per_branch
override blindness (one resolver shared with the write gate), so @seedgo's
known xfail flipped to a plain passing test and the marker is removed.
@hooks edit_gate 1.5.1 dedupes the double-report that appeared once both
missing-field checks ran (union of checks kept deliberately — a gate that
outsources all measurement inherits its supplier's blind spots). And Patrick's
session-shape ruling landed in the contract + graduated trinity.md verbatim:
the shape stays closed — summary is the headline, lessons go to
key_learnings, depth lives in @memory vectors (rollover + search), tags are
the findability hook. Suites re-run together pre-commit: memory + hooks +
trinity checker all green.

**feat(seedgo)** — the trinity standard is LIVE: trinity_check.py joins the
standards family (no bypass by design) and the fleet has its first honest
memory-file scores — red-first bar hit exactly (clean set = the MASTER_LIST
six, all 12 deviants flagged, pinned as a live test), fleet avg 72% with
memory the only 100. The checker's own first draft broke the one law it
enforces (zero denominator read as clean → silent pass of an unmeasurable) —
caught by its test agent as strict xfail, fixed in the engine, kept as a named
regression guard. Five contract ambiguities and two possibly-wrong rules
flagged for Patrick rather than silently resolved; audit-cache engine defect
(hashes only apps/*.py — stale scores for checkers reading outside) queued.
1836 green + 1 known xfail, 25 rule-matched mutations.

**fix(hooks)** — B3, the last of the four measurement bugs: edit_gate refuses
a NEW/EDITED entry whose canonical field is missing — by name, with the rename
instruction, never measured as zero. Exemption keys on raw-entry identity so
one legacy entry cannot license ten more (mutation-pinned). Live-proven on
hooks' own drifted file. Second defect fixed en route: @memory's unmeasurable
refusals were rendering as "0/300 chars" through the over-cap formatter.
Flagged honestly: the dodge originates in @memory's _extract_text (missing
field still returns ""), so their own write path still dodges — repro
dispatched to them. 7 red-first tests, 1688 green.

**fix(memory)+feat(memory)** — the measurement bugs that let memory-file drift
pass silently are dead, and the standard's text machinery is live (@memory's
build). The law: a field the gate cannot measure is REFUSED loudly, never
measured as zero. B1: non-string entries refused (new/edited only — legacy
shapes grandfathered until the reset, deliberately); B2: lint's len-on-a-list
path gone; B4 was TWO files — detector fired at >= while the extractor floored
at 1, both moved together or the fix would have traded settle-at-14 for a
drain-nothing loop. Renderer reads the gold-source templates (hardcoded text
constants retired, refresh preserves the semantics prose); every health writer
deleted per the ruling; new per-branch .template_version.json receipt writer
(three sanctioned lanes, push lane awaits the pusher rebuild — flagged). 42
red-first tests, 1115 green re-run independently.

**feat(memory)** — trinity gold-source templates carry the agreed standard
(DPLAN-0318, Patrick's line-by-line review): unique `_usage` per file (working
draft vs memory-of-the-USER), meta lines become `{{PLACEHOLDER}} + one-sentence
semantics` so every section shows its live caps AND its meaning where the agent
writes, and the dead `status.health` block is deleted rather than revived — it
had no consumer, stored a derivable fact, and always read healthy; health is
now computed by the checker at run time, never stamped into the file. The
standard itself (trinity_pattern.md, seedgo-format) governs; @memory machinery
fixes and the @seedgo checker build ride separate dispatches.

**docs(fleet)** — README truth campaign, the 08-25 night shift (Patrick's GO):
every citizen verified its OWN README against the code as it exists, waves of
two, each pass re-audited to 100% after editing — 18 branch READMEs corrected
in this repo (~120 claim families), plus the four resident projects in their
own repos. The rule was measured-or-marked: every number rewritten tonight was
counted tonight, and what couldn't be verified is now labeled unverified in the
README itself instead of standing green. Headlines: commons documented a
Reward-Drops feature that never existed in any code; baud's command-registry
safety claim was false (26 listed, 29 registered — three write-capable commands
invisible to an audit); aipass's own Quick Start pointed new users at bare
`init`, which prints help; two project front doors misrepresented finished
products as empty templates. Fleet pattern, both directions: dead features
documented live AND real features/fixed debt undocumented — either would
poison a post-reset agent, which is why this campaign was the precondition for
the DPLAN-0318 fleet memory reset. Code defects found were flagged to owners,
never smuggled into docs-only edits; the queue rides in devpulse's campaign
log (dropbox/readme_night_shift.md) for the morning read.

**fix(ai_mail)** — registry rows leave the reader ABSOLUTE, rooted against the
registry that answered (`_rooted()` in both lanes of `_lookup_branch_by_name`
and `get_branch_info_from_registry`). The defect: a projects/* citizen's
relative registry row was joined to the AIPass repo root, so BAUD's mailbox
resolved to a phantom dir inside our tree — inbox read empty against a full
store, reply refused an id sitting in the file under his feet, and the lane
FABRICATED the phantom on write: his answer to Patrick's continuity probe was
silently swallowed into `src/baud/` (recovered, then removed via drone rm once
re-sent on the live lane). Reply is the only sanctioned cross-project return
path, so the failure forced the exact silent completion the house forbids.
Three red-first tests including a guard for the six relative AIPass rows;
verified live from BAUD's seat — inbox lists all messages, the id resolves,
and his reply arrived through ai_mail itself. 1326 green. Rider: purge.py's
gap comment updated — @memory shipped `vectorize_and_store` (1.4.0), the seam
is verified live, and the four-month mail-loss loop is closed in practice.

**feat(spawn)** — a brand-new external project's registry is born WITH its
credential: `load_registry` mints `metadata.id` for a missing file (a registry
that does not exist is a new project) and deliberately does NOT mint for an
unreadable one (a live project whose credential failed to read must never be
re-credentialled — four tests hold the asymmetry). Mint-once ordering moved
into `_spawn_agent`: the passport writes at step 1, the registry at step 4, so
the credential resolves at step 1 and `add_to_registry` adopts it only for a
registry it is CREATING, keyed off file-existed-before-load rather than
id-already-set. Live probe: fresh project mints its own credential, passport
and registry agree, zero AIPass leak. 11 red-first tests, 506 green. Known and
flagged, not fixed here: `add_to_registry` against an unreadable registry
would write the empty schema over the real file — guard awaits its own GO.

**fix(drone)** — owner-tier git refusals carry their species: authority (not
this repo's owner) stays ERROR and warn-mode lifts it; capability (proven
owner, verb untranslated for external repos) logs WARNING and warn-mode does
NOT lift it — `AIPASS_GIT_AUTH_MODE=warn`, the AUTHORITY-migration rollback,
was proven live re-arming `pr` inside BAUD's repo, a half-run of our flow in
someone else's tree. Message honesty: a proven owner reads "cannot run pr in
this repo", not "is not authorized". 6 tests, 1200 green, auth.py 1.1.0.

**fix(devpulse)** — feedback's cross-store writes speak the host's dialect:
`compose.py` 1.3.1 stamps ai_mail's canonical local format into recipients'
inbox.json instead of UTC ISO-T (two timestamp shapes in one store, BAUD's
report — measured NOT the cause of his dead inbox, but real pollution).
Red-first test pins format and wall-clock, 70 feedback tests green.

**docs(changelog)** — the v2.7.17 section header is restored at its splice
point (VERA's find: the v2.7.18 merge glued the header's title onto a README
paragraph mid-line, leaving tag v2.7.17 with no matching section). Kept the
deliberate retitle over the 08-19 original; all released tags have sections
again.

## [2026-08-23] — v2.7.19: the merge playbook grows teeth

**docs(flow)** — README truth check and site parity become hard checkboxes in
the merge playbook template (Patrick's ruling during the v2.7.18 train, edit
by @flow). The soft "flag site drift" note let aipass.ai sit three claims
stale since May; now a train that changes anything user-facing must run the
claim-by-claim README fan-out BEFORE merge (parallel read-only reviewers, one
per section, ACCURATE/STALE/WRONG with file-and-line evidence, fixes riding
the same PR), and every merge closes with a five-field site parity diff
(agent count, platform line, install commands, structure snippet, FAQ). The
site repo's missing write door is written in as stop-and-record, never
work-around. @flow re-measured the brief before carving it in and fixed it
twice: `drone systems` lists @drone and @canary but omits them only from its
printed count (which also counts @git, a branchless module), and "count the
directories" answers 19 because `__pycache__` is one — the checklist carries
two literal commands that both return 18, with the load-bearing `grep -v`
named as such.

## [2026-08-22] — v2.7.18: the watchdog stops polling, identity stops being a directory name, a test citizen is born

**feat(watchdog)** — three releases land as one arc, and each one killed a
defect the previous one had left standing. r2 gave detection and delivery
separate lifetimes: the 12:34 miss convicted `run_in_background`, which
notifies on process exit only, so a continuous watcher armed that way wakes
nobody, ever. r3 cut the daemon's idle cost from 7.72% of a core to 0.017% —
1640 CPU-seconds burned across 5.9 hours in which zero dispatches occurred.
r4 deletes the daemon outright, because gating the polling was the wrong fix:
`feed.py`'s own header already said detection by inference is replaced by
detection by report, and the code had taken one step toward it. Completion is
now REPORTED by the completing agent. The defect that hid inside the old
design: every completed dispatch produced TWO wakes for months — @ai_mail's
report, then the daemon's lock inference one to two seconds later, drained
from both sources with no dedupe. It survived because a duplicate wake looks
exactly like a working wake, and every test that could have caught it asserted
that something *arrived*, which stayed true throughout. Only a COUNT catches
it; the replacing test counts. The wire also answers "was this mine" for the
first time — the feed names the branch that finished, never the branch that
sent, so this seat was woken for every citizen's completion fleet-wide. Sender
is now stamped on the completion line and attribution is one comparison;
an unattributable record fails CLOSED, because failing open is not a smaller
version of the fleet-wide wake, it *is* the fleet-wide wake. Crash coverage
stopped being a job for a process and became a fact about a file: a register
entry past `expected_by` means the monitor died, true whether or not anyone is
looking. Named rather than buried: that trades 10 minutes of detection latency
for 2 hours, a 12x regression, and buying it back is a deliberate second
timeout with its own justification, never a quiet edit to this one.

**fix(ai_mail)** — identity stops being something a directory can spell. A
dispatch run from the repo root sent as @aipass, and its wake-back then woke
@aipass instead of the sender: 11 turns, $1.41, a phantom badge on a phone
that could not be cleared, and a lock renamed by hand at midnight. Nothing
warned, and the root cause was not a missing policy — `get_current_user()`
already documented "no fallbacks, fails hard" and every route already reached
it. It SUCCEEDED and returned the wrong citizen, because the identity was
derived from the project *directory name* and the contact lookup then found
the real citizen of that name. The raise had to be made reachable, not added.
`AIPASS_CALLER_CWD` is now treated as evidence of where the caller stood while
the claimed branch is only a claim, and the evidence outvotes the claim; the
fence sits at the CLI entry above routing so every verb obeys it. Once @drone
stamped provenance, the fence learned to ask what KIND of evidence names a
caller: assigned and passport are credentials and pass from anywhere, a
directory name is refused permanently, and absent or unrecognised is refused
too — so the lift is opt-in and fails closed against an older drone. Three
more silent substitutions in the same lane went with it, all of which had
never fired because the claim path masked them. The manager wake-back was two
lies, not one: the drop (managers were promised a wake the gate always
blocked) and the promise (senders were told "you will be woken" regardless of
class). Managers are now mailed, and told so. Earlier in the train, dispatch
began recording the session it lands in — resume by pointer, not by transcript
mtime, which is what every resume door in the system had been ranking by.

**fix(drone)** — a fallback that fired on the happy path was also swallowing a
security refusal. The router's fast path excluded interactive commands, but
`status` is one, so `@git status` skipped it, looked for a *branch* named git,
raised `BranchNotFoundError` on every single call by design, got caught, and
was handed to the identical call the fast path would have made. The detour
achieved nothing — and removing all three fallback sites rather than only the
noisy one exposed that `resolve_branch()` refuses a registry path escaping the
project root by raising that same exception. That refusal was reaching the
except arm and being answered by running the module: a blocked branch served
through another door. Nobody was hunting for it. Side effect of the fix:
drone's own log stops being 1277 of 1279 lines of one INFO message.

**feat(canary)** — @canary is born, a permanent test citizen, so dispatch — the
riskiest lane in the system — is exercised on something disposable instead of
on a real branch doing real work. It earned its keep immediately. Dispatched
to probe owner-gates from a NON-OWNER seat, which is the one thing an owner
can never verify from their own chair, it found that refusals EXITED 0:
`warning()` does not call `mark_command_failed()` and `error()` does, so
`<refused command> && <next step>` ran the next step, and nothing in the exit
status said otherwise. Eight sites fixed across watchdog, feedback, compass
and `admin_grant` — the birth-certificate privilege ceremony, reporting
success to the shell while granting nothing. All now exit 2. It also found the
gate outranking `--help`, so a stranger could not read the text naming whose
module it is. Its birth also turned a months-old latent pytest defect into a
hard failure: two branches missing a package-marker `__init__.py` resolve to
the same bare `tests.conftest`, and that aborts collection for the WHOLE
suite at the first clash. Fixed in both colliding branches, then fixed at the
source — the spawn scaffold now mints the marker at birth, so the next citizen
is born with it instead of re-redding the board.

**feat(flow)** — a project is its register. A directory is a project root if
and only if it holds a `<NAME>_REGISTRY.json` carrying a top-level `branches`
key — not its repository marker, not the presence of citizens, not nesting
depth. That distinguishes the 15 real projects on this machine, including
zero-citizen ones and one with no repository marker at all; the `branches` key
is load-bearing, because three files match the name glob and are not registers,
and a name-only test would have minted them into projects and silently pulled
rows out of their real project's scope. The new `project_scope` handler never
consults `__file__` — seven files in flow answer "where am I" that way, which
is right for flow's own registries and wrong for "whose plan is this".
`close --all` gains three fences: `--exclude-type` validated against the
registered templates, any unknown argument refuses the whole run instead of
being ignored, and rows are scoped to the caller's project. Held rows are
counted by WHY, and "foreign" is kept distinct from "unattributable", because
a row no register claims is a data-quality defect and collapsing the two is
how the second kind stays invisible. And the one that matters: RESTORE WAS
DEAD FOR 719/719 CLOSED PLANS — it checked the `file_path` that close had
archived away, while the archive sat intact. It had been proven on a test plan
whose file still existed: proof on a neighbour is not proof on the row. It now
reads the archive; 412/719 recoverable, 307 pre-May closes have no artifact.

**feat(spawn)** — a newborn citizen is no longer born failing. @canary's birth
proved the framework template minted citizens at 79% against a 100% CI gate —
day-one red through no fault of their own. The template now ships a compliant
entry point (META block, `--version`/`-V`, non-zero refusals on stderr), a
json-handler shim, and 47 genuine starter tests; a probe citizen minted from
the fixed template audits 100% on the real gate and was retired through the
lifecycle, not deleted. The catch that mattered: a template file is a
FLEET-WIDE MANDATE — seedgo's architecture baseline requires every template
file in every branch of that class, so two new starter-test files red-boarded
nine green branches that hadn't changed a line. Fixed via the template's
registry ignore (files still ship at create, just aren't retroactive
structural law). The template's prompt also stops teaching newborns a
watchdog reflex that was owner-only since DPLAN-0239 and retired by r4 —
an instruction whose only possible outcome was a refusal. project_agent got
the same-species half (84% → 92%); its structural gaps are named, not
papered over.

**feat(hooks)** — the terminal boot menu learns what a dispatched branch is
(session_boot 4.4.0). Two doors were broken in the same place: every human
entry door resumed with `-c`, and interactive `-c` refuses headless
transcripts. The dispatched card's door became a resume-INTERCEPT — reclaim
stops the agent and the seat inherits the chat — and the first successful live
intercept of a dispatched agent followed.

**refactor(api)** — the room socket moves out of the route into a handler that
owns the wire for as long as both ends are alive. The split it enforces is the
load-bearing part: binary frames are keystrokes, text frames are control,
which is what lets a resize or a liveness probe ride the same socket as the
operator's typing without either being mistaken for the other. Bytes are
forwarded undecoded in both directions, because the room emits escape
sequences and partial UTF-8 across chunk boundaries and decoding at either end
corrupts both. Riders from the same nights: room-lane liveness after the phone
corpse-frame incident, an advisory throttle, and bearer-token receipts rehomed
out of the home root.

**fix(backup)** — a run ceiling, because no ignore list catches the build
system nobody has met yet. One `backup all` run wrote 50GB over 7.5 hours
through a generated ignore file that predated its target's build tooling.

**fix(skills)** — a fall-through is not a warning. `_parse_simple_value` tries
float, then int, and uses the ValueError as its *route* to the string branch,
so the non-numeric case is the design, not a fault, and stops logging itself
as one.

**docs(prompts)** — every injected prompt file now opens with a pointer to
`PROMPT_STYLE.md`: the four root tiers, every branch's local prompt, and both
spawn templates, so a citizen born tomorrow carries it too. The reason it is a
pointer at the top of the file rather than trust is measured, not theoretical
— while shrinking one prompt its author re-added bold and caps, the two things
the style guide bans, in the same pass. The writer cannot feel urgency
creeping back into their own text; only the checks catch it. Devpulse's README
is rewritten for the watchdog's login model, and its branch prompt dieted from
2400 to 1032 words.

**fix(ci)** — the release's first fresh-checkout run failed 37 tests across
three branches, and every one was a single species: tests green against live
machine state, red on a machine without history. CI has no
`AIPASS_REGISTRY.json` — it is runtime state — and the watchdog re-root walk,
@ai_mail's register transplant, and @flow's plan-type assertions all
implicitly required it. No local gate could have caught this; every local run
is on a machine with history. The reusable artifact is the mimic: copy the
tree to a marker-less directory, force imports there via PYTHONPATH, run
pytest from the copy root — red on the old code, green on the fix, both
directions proven. Behind the test fixes, three production defects fell out.
@flow's `load_registry` seeded a missing registry and returned early, skipping
type discovery — every fresh install answered "which plan types exist" two
different ways depending on call order, and CI was the only machine that could
ever see call one. @ai_mail's `find_repo_root` fell back to `Path.cwd()` on a
fresh checkout, so the dispatch register would be created in whatever
directory the caller stood in; it now walks for the untracked registry and
then for tracked `pyproject.toml`, which sat on the ancestor chain the whole
time, unasked. And the transplants (theirs and devpulse's feed) re-derived a
repo root they already held, with a marker only historied machines have —
fixed by carrying the root in hand and by the two-marker walk. In passing,
@ai_mail caught and fixed a LIVE cross-citizen mailbox leak: a poisoned row in
their learned contacts cache outranked the authoritative registry and served
@flow's mailbox to @ai_mail's own CLI, stamped "verified" — right name, right
email, wrong path. Registry now outranks cache for every citizen it knows;
contradicting rows are refused and logged; a fleet-wide scan of all 18
branches' caches found no other poisoned row.

The Linux gate going green exposed the second stratum: `windows-setup` is a
fresh-INSTALL machine (setup.sh runs first, so the registry exists), and it
failed 14 tests across five owners. The house standard that emerged: build the
foreign platform's semantics locally and reproduce before fixing — @flow
patched one `Path` name to `PureWindowsPath` and got CI's three assertions
verbatim (their fence was fully working; three tests compared stringified
paths against forward-slash literals, an idiom also wrong on Linux for
`/aipass-old` under `/aipass`); @hooks replaced `os.path.expanduser` with
ntpath semantics and reproduced their exact four-vs-three split
(`patch.dict(clear=True)` strips USERPROFILE, which Windows home resolution
needs and POSIX doesn't — fixed portably at all 12 sites, no skips, and the
sim surfaced two latent import-time crashes from module-scope `Path.home()`,
invisible in CI only by import order); @ai_mail refused the comparison-side
fix because their failing test was REPORTING a production defect — the
mismatch message rendered paths with repr, showing Windows humans
double-escaped paths that match nothing — and fixed the message instead,
keeping repr's quiet gift (an empty pointer renders as quotes, not a vanished
word). Devpulse's wire tests were the honest exception: argv[0] renaming and
/proc inspection are POSIX mechanisms Windows does not have, so those five
carry skipifs naming the mechanism. And @spawn's passport-drift test caught a
real gap on the runner: setup.sh's hand-written bootstrap list predates
@canary's birth, so fresh installs minted every passport except theirs — one
line added, and the hazard (a list every birth must remember by hand) written
beside it.

**docs(readme)** — the root README verified claim-by-claim against the tree by
four parallel reviewers before this release ships it. Fleet count corrected 17
→ 18 in four places and @canary added to the diagram and tables (a reader
running `ls src/aipass/` finds 18; a public README must not lose a count to
its own registry). Descriptions refreshed from each agent's own words: api is
an external API gateway (keys, secrets, Google OAuth, host server — OpenRouter
is one module of thirteen now), trigger's medic fingerprints and wakes, never
"self-heals", spawn creates, updates, AND deletes. The honesty fixes: "delete
the directory and it's gone" was false — the installer writes hooks in
`~/.claude/`, PATH entries, and cross-project state in `~/.aipass/`, so the
claim now names both halves and Uninstall covers removing them. The uninstall
recipe itself was defused: it said `rm -rf src/` in a section that exists for
brought-your-own projects, where `src/` is plausibly the user's entire source
tree, and it deleted a `hooks/` directory nothing ever creates. `aipass init`
corrected to `aipass init .` (bare init prints help and scaffolds nothing),
`--no-chat` now admits it skips the doctor preflight too, the structure
diagram gained the three standard dirs it omitted, and "Linux or WSL" widened
to Linux/macOS/Windows (Git Bash or WSL) — both extra platforms run the full
suite in CI on every PR. Verified clean and left alone: every badge and link
(zero dead, LICENSE genuinely MIT, codecov live at 78%), and the whole
Subscriptions & Compliance section — the subprocess claim is backed by code,
zero credential handling in the tree.

## [2026-08-19] — v2.7.17: one-brain enforced, CI green campaign, fleet perf night, phone file explorer

**fix(ci)** — the PR #734 green campaign: six owner rounds took the PR's own
board from red to 21/21. Main was never red — the merge gate forbids it; these
failures lived only on the PR, where the new Windows/macOS lanes' first
complete runs unmasked platform
assumptions suite by suite (a bare `os.geteuid()` in a decorator killing a whole
file at collection, POSIX-mode skips made honest, the parent-is-a-file corpus
divergence, @trigger's reader-clobber where a refused read became a destructive
write over the whole log). The last two reds were each one test and neither was
the code lying: @prax's size pin compared `len('y = 2\n')` to the 7 bytes
Windows actually holds after CRLF translation (production recorded the truth;
the pin now asserts the file's own `stat().st_size`, plus an explicit-CRLF pin
run by name from the Linux lane), and @trigger's Linux 3.12 flake was a third
door — `ensure_json_exists` created missing files as a REPLACING write outside
every lock, so two racers could bury a lock-holder's entry (the fcntl lock was
measured innocent). Cure: `atomic_create_json` — stage to temp, `os.link` into
place, create-or-fail; 0 losses in 1500 stress runs, and the zero is evidence
because restoring the old write makes the same loop lose again. Also declared:
httpx in the dev extra; `.claude/settings.local.json` files ship tracked
(tested settings are shared; only memories and local work files stay home).

**fix(fleet)** — DPLAN-0310: one brain, enforced. Never two live interactive
sessions on one branch again. The presence gate flips from observe to enforce,
sourcing truth from CC-native session files (resume-aware, exit-aware): one
INTERACTIVE brain per branch, background jobs never gate (a job is not a seat),
and the incumbent-by-start-time tiebreak refuses exactly one of two competing
seats — without it both refuse each other and the branch bricks. The boot
picker now lists conversations (transcripts, with your actual last message)
instead of anonymous PIDs, so Ctrl+C recovery returns to the chat you were in.
The CLI auto-updater that self-ran mid-session (2.1.234→235, the drift that
started the night) is pinned: tracked `provider_manifest.json` version, symlink
install, boot-time drift warning. Live-verified across laptop and phone: second
seat refused with the occupant named, held-chat pick attaches, cross-device
one-brain-two-windows, Ctrl+C round-trip clean.

**perf(fleet)** — DPLAN-0305: the lag named and cured. One unguarded stat —
prax's logger lazy-started an ecosystem-wide recursive filesystem observer
(~1413 inotify watches) in EVERY process that logged, watchdog's dispatcher
thread died on any handler exception, and the unbounded event queue then grew
forever in processes that thought they were healthy: six of them held 13.7GB,
12.8GB came back the moment they stopped. The watcher now guards the whole
handler body, the observer never self-starts in importing processes, and the
monitor runs on request only. @api unblocks its event loop in the same train:
18 no-await route handlers made sync, snapshot TTL + per-key single-flight,
and the attach lane's silent ninth-terminal hang fixed with a named thread
pool behind a bounded semaphore.

**feat(api)** — FPLAN-0443: the fence gains ROOTS and the phone leaves
agent-land. File explorer + copy-path, accepted on the S24 the same afternoon.
Four root kinds (branch/home/project/aipass) under the same containment;
`GET /v1/roots` publishes the roster from the census, answers carry `floor` so
copy-path yields a real pasteable location. The home arm's openness is on the
record with its cheap reversal written down.

**feat(fleet)** — DPLAN-0303 server side + DPLAN-0302 day 3: the one-terminal
arc goes live on the phone — server lanes for the phone face, spawn birth-cert
repair round, devpulse watchdog refit riding the same trains.

**chore(git)** — APLAN-*.md joins the gitignore: living audit records are
working papers; they stay home with the branch that keeps them.

**feat(host)** — DPLAN-0300: the phone becomes a terminal — attach lane, photo
lane, verb doors (@api server-side; @baud's client lands in the BAUD repo).
`WS /v1/room/attach` spawns a PTY running the desktop's exact attach-or-create
tmux command (SIGHUP = detach, rooms survive close); the bearer rides
`Sec-WebSocket-Protocol` and the server echoes only the sentinel, never the
token; binary frames are keystrokes/output forwarded unchanged, text frames are
control (resize — refused-not-clamped, never fatal). The pump waits
FIRST_COMPLETED with hangup-first (gather-both deadlocked on quiet rooms,
leaking a thread + an undetached tmux client per closed sheet). The fix that
mattered most: the PTY child now ACQUIRES its controlling terminal (login_tty,
setsid+TIOCSCTTY fallback for 3.10) and the PTY is born at a real 80x24 —
before this, TIOCSWINSZ's SIGWINCH had no recipient, so the tmux client read
0x0 at startup, fell back to 80x24, and stayed deaf to every resize any client
would ever send. That deafness painted 80 columns into a ~46-column phone:
mangled lines and the stacking status bar, root-caused live by reading stty and
tmux list-clients link by link until they disagreed. Rooms are stamped `mouse
on` + `window-size smallest` on EVERY attach, each chained tmux command with
its own `-t`. `POST /v1/files/upload` (operate, multipart field `image`): the
server names the file — the client filename is never read; magic-byte sniffing
with an offset table (WebP/HEIC put size before brand), 25MB refused not
truncated and checked twice, 0600 via os.open, lands in ~/Pictures/BAUD beside
the desktop's screenshots. Kill/wake/lock verb doors, phone face serving, and
FastAPI validation errors normalized into the documented error envelope
("image: Field required" in words, not a naked 422 shape). pyproject grows
python-multipart in `[host]`; `tests/.archive/` whitelisted so the superseded
capture-lane tests ship revivable (`--capture-room` stays parked as the future
look-don't-touch lane for read-scope room viewing). ~1002 api tests green
incl. mutation-checked resize guards that caught the genuinely-untested 3.10
fallback. Riding along: @skills screen_lock v1.0.0 (loginctl password-lock,
every agent keeps running — the walking-away-from-the-desk piece) and
devpulse's dispatch-protocol prompt lines (S248: mail reaches an awake agent
only at hook boundaries — long briefs now carry re-check-inbox-before-done).
Live-accepted by Patrick from his S24 through the real stack — attach, type
directly into the TUI, photo, finger-scroll: "this is usable rn."

**feat(fleet)** — DPLAN-0291 audit wave, morning completions. @spawn S118
closes all 4 open items: `create <unknown-class>` refused red-first (the repro
created WIZARD on disk before the fix), `.ai_mail.local/` never-update
exclusion, `sync-templates` retired outright (template_owners.json empty twice
running) — 434 green, seedgo 100%, APLAN-0007 signed GREEN. @daemon hardens
memory_health per APLAN-0015 (3 fixes, not 1). @skills telegram base_bot +
suspend tests. @aipass APLAN-0018 stamped.

**feat(host)** — DPLAN-0300 Stage 0: the host API lands (@api, FPLAN-0411).
The fleet's first phone-ready surface: loopback-only FastAPI behind
sha256-hashed bearer tokens (compare_digest, read|operate scopes, file-edit
revocation effective next request). `/v1/feed` reads notifications.jsonl
through a ts cursor clamped both ends with an explicit gap flag and
at-least-once boundary delivery; `/v1/files` + `/v1/diff` take branch NAMES
never paths (512KB cap refuses rather than trims, diff goes through drone
@git); `/v1/fleet` + `/v1/rooms` consume `baud --snapshot` so "which agents
are alive" has exactly one implementation — binary resolution prefers the
deployed release build over any PATH copy, and SNAPSHOT_READY survives as an
operational kill switch (closed = 503 with a reason, never a synthesized
fleet). 713 tests, live-verified on a running server including post-revoke
401 and the exit-1 envelope path. pyproject grows the `[host]` extra
(fastapi, uvicorn). Riding along: @ai_mail's fleet→project refusal now tells
the truth (replies-only by ruling DPLAN-0288 — the outer wall said "Unknown
branch" and sent @api hunting a phantom; wall stays shut, test pins it shut,
1083 green), the morning riders (hooks TG relay cursor clamp, @memory vector
embedder parked to .archive, skills TG start/kill control-verb fixes), and
README/APLAN truth-ups. Patrick live-verified the whole chain same day:
dev-window click-through, release rebuild, his own --snapshot run, /v1/fleet
200 on real data. CI hardening rider: the bind-refusal test inherited fastapi
from the local venv (green at home, red on every runner); both
availability-dependent tests now pin `is_available` explicitly, a new guard
asserts a valid port actually reaches serve (its neighbor test had been
passing on CI for the wrong reason), and ci.yml + setup.sh now install the
`[host]` extra — before this, CI had never made a single HTTP request against
AIPass's first network-listening service; the auth/scope/traversal tests ran
only on developer machines.

**feat(fleet)** — night shift DPLAN-0295: the prompt-lane sweep (Patrick's
ruling, compass #272 — the agent never waits for the system) plus four ruled
queue items, all 10 roster items landed. auto_process relocated off the first
prompt: @memory built a fire-and-forget detached child (single-flight lock in
the child, live-proven on real rollover work), @hooks swapped the shell —
handler returns in 0.7s where the lane used to block 78–120s. Full UPS sweep:
11 injectors legitimate, user_message_relay flagged relocation candidate #1
(blocking Telegram POST per prompt, zero stdout in 18/18). @prax measured the
same species in its own hottest path: the FIRST log call in any process costs
0.60s (watcher start + fleet event that imports ai_mail) on every drone
command — relocation proposals filed for ruling. Severity reclass per compass
#273: the 17/15 over-budget class (16% of all escalation mail ever sent)
reclassed WARNING→INFO at the emitter with a guard pinning the genuinely-loud
advisory. system_logs double-watching ended — root cause was ONE reader and
TWO FILES (prax dual-writes; watcher globbed both trees), fixed with twin
detection + live-tree branch names, UNKNOWN-attribution mystery solved
(hardcoded 11-name list vs 17 branches). seedgo's log_structure check proven
NEVER to have run in any commit (signature mismatch swallowed by a bare
except; mocks accept any kwarg so the suite stayed green) — crashed checkers
now surface attributably, observe-mode shipped with an honest negative
verdict. drone subprocess default 30s→60s referenced from one constant across
all three layers; --drone-timeout placement tested and documented. prax
Mission Control now resolves projects/* citizens from registries and
passports (BAUD scopes; misattribution-as-AIPASS and CWD-relative registry
bugs found and fixed beneath it). Four branches corrected their own published
diagnoses when evidence arrived — amendment-before-hardening held fleet-wide
with nobody watching (compass #276). Suites: memory 1011/823, hooks 1469/1483,
trigger 1029, seedgo 1662, drone 1118, prax 1322 — all green, all audits 100%.

**feat(fleet)** — morning round 2026-08-14: deletion record + fragments park
(Patrick's rulings). Every deletion now leaves a record: drone rm logs every
outcome — deletes, refusals, failures, not-found attempts — to
.ai_central/deletions.jsonl plus a prax INFO line (passport-resolved caller,
2MB rotation, env override deliberately cannot silence the audit trail;
first-run-green tests distrusted and proven by mutation), and hooks' rm gate
records every raw rm it allows or blocks (command as-typed, ~10ms only on the
rm lane, measured). Bonus fix: the sibling-branch guard resolved ownership by
INNERMOST .trinity, so template skeletons masqueraded as citizens — @spawn
could never delete inside its own templates/; outermost-citizen-wins now,
matching e934099f. The symbolic fragments tier is PARKED, revivable
(.archive/parked_symbolic_20260814 + numbered revival README): the Agent
Memory Atlas external review (first code-grounded outside review of AIPass —
praised surfacing governance as the standout mechanism of its corpus) flagged
the AUDN Delete verdict as unauditable, and the tier was unused — Compass is
the active curated-truth piece, and every disable point says so. @memory's
verification caught that "unwired ≠ unloaded": handlers/__init__ imported the
whole symbolic package on every live call. Loud stubs answer the entire old
API with the ruling; 4 legacy suites skip-annotated, live lane proven
untouched by a real detached rollover run. Surfacing governance confirmed
LIVE meanwhile — it gates compass recall on every prompt (engine.log entries
match the injected lessons), with one actionable found: the five governance
constants are unoverridable without a code change (queued). New CPLAN plan
type registered in flow (capture_plans): records wearing the plan lifecycle,
born to close, vectorized on close — CPLAN-0001 captures the Atlas review
whole. Captured in DPLAN-0295's run log end to end.

**fix(hooks)** — UserPromptSubmit timeout seatbelt, DPLAN-0285 items 1+2
(Patrick present, live-verified same evening). A timed-out UserPromptSubmit
hook is cancelled and its context silently discarded — the model quietly loses
its operating instructions and carries on. The real regression: auto_process
carried timeout 120 only in deployed settings, never in the manifest; a
reconcile ~08-02 silently wiped it, and its legitimate 78–120s first-prompt
run (@memory vectorize + rollover) started dying at the 30s default. Timeouts
predate BAUD by weeks — the transcripts (205k lines back to 07-09) acquit it.
Fix: timeout 90 (auto_process 120) stamped in ALL layers the same breath —
.aipass/hooks.json (inner), provider manifest (source of truth), init template
(the aipass init update union-merge would silently wipe live-only values) —
plus 3 config-pinning tests and an engine test proving values >30 reach
worker.join uncapped. Trust re-enrolled with the edit (an @hooks probe showed
editing hooks.json breaks its trust hash and takes every gate dark). Stale
README single-dispatch claims fixed (3 sentences, wrong for 73+ days). Suite
1454 green. Follow-up queued: DPLAN-0294 relocates auto_process off the
prompt lane entirely (Patrick's ruling, compass #272 — system housekeeping
never blocks the prompt).

**feat(fleet)** — the fleet audit round: every citizen audits itself
(DPLAN-0291, Patrick's directive, waves of 2). All 17 branches created living
APLANs — standing per-branch health records that future audits UPDATE, never
recreate — and ran full self-audits: live command probes, full suites, seedgo,
README truth pass, bypass-registry measurement (control-first: pull the rule,
audit, restore — cli 21→8, drone 48→29, flow 74→58, ai_mail 51→17 accumulated
fiction cleared). Six branches had tests PINNING broken behaviour, found only
by running the real path. Round closed with the full-fleet proof: 17/17
branches at 100%, all 45 standards at 100%, 0 type errors.

**fix(fleet)** — a help flag anywhere must explain, never execute (DPLAN-0291
rule E, all 17 branches). Fleet-wide idiom gated help at args[0] only, so
`verb sub --help` EXECUTED the verb: live detonations included @memory's
rollover push running a 17-branch reset, @backup running a real snapshot, and
@drone's `rm notes.md --help` deleting the file. Every branch fixed red-first
with a whole-sequence wants_help predicate inside its own handle_command
(after the ownership check — routers try modules in turn), bare word `help`
position-0 only, opt-outs pinned for genuine help verbs. @seedgo encoded it
the same day as the help_flag_safety standard (AST-based), recalibrated three
times on fleet evidence: router exemption removed (standalone `__main__`
paths), value-slot-only trigger widened (flow/hooks false negatives), and
log_structure DE-SCORED after it proved to read live runtime state — a score
that moves on its own is worse than a wrong one.

**feat(drone)** — the tag verb learns external repos (by @drone, FPLAN-0403,
DPLAN-0290 night shift). Two lanes chosen by the repo the command runs in:
external seats (projects/*) tag their own repo's current HEAD and push to
their own origin — names validated by `git check-ref-format`, duplicate guard
kept both sides, and a new `ls-remote` exit-code guard so an unreachable
remote can't read as "no such tag" and stamp over a live release. The AIPass
lane is untouched and argv-pinned by regression test. New
`handlers/git/repo_context.py` owns "is this AIPass's repo". 17 tests
red-first, 1019 green, live-proven from the real baud seat.

**feat(trigger)** — reload sentinel: the watcher notices its own code change
(by @trigger, FPLAN-0404, DPLAN-0290). Every 30s the service compares handler
and module mtimes against its startup snapshot; on change it exits 75 and
systemd restarts it onto the new code. Settle guard (15s) refuses mid-save
restarts; an unsupervised process logs loudly instead of exiting (a stale
watcher beats no watcher). Live-fired three times the same night unprompted.
Also: `Trigger.on()` is now idempotent — double-registration had been pinned
as a feature by two tests asserting `call_count == 2`, delivering every event
twice and walking medic gate 3 on single occurrences. 957 green, audit 100%.

**fix(memory)** — auto-compact snapshots drain past the date valve (by
@memory, DPLAN-0283/0290). The v2 extractor's snapshot rule existed; the
skip-loop was DPLAN-0278's safety valve refusing any tail entry "dated
today" — and snapshots are machine-written same-day by nature, so every
candidate was refused forever. New `date_guard` param: the auto-compact lane
trusts ordering over dates; the conservative rule stays everywhere it still
discriminates (above-head and numberless entries refused in both lanes).
Skip loop proven to terminate on a sandbox copy; 6 tests (3 red-first,
3 protection), 1063 green. No live rollover run — the rule is dark until one.

**fix(flow, prax)** — quick_status stops clobbering itself (by @flow
FPLAN-0405 + @prax off @flow's dispatch, DPLAN-0290; the bug behind
Patrick's "zero todos" BAUD card). Two writers replaced the whole
`quick_status` block with different schemas — every plan close wiped
`todo_count` off the cards, every prax refresh wiped `commons_mentions`, and
flow's push also flipped mail counts from a stale mirror. Flow now merges by
ownership class (OWNED recomputed / MIRROR preserved / DERIVED recomputed
over all counters including foreign / foreign verbatim); prax fixed the
mirror in BOTH copies of its calculator — the second one, on the live
refresh path, was the one outside code-reading's reach. Live-proven from
both directions: `todo_count` and `commons_mentions` now coexist through
either writer. 787 + 1240 green, both audits 100%.

**fix(devpulse)** — watchdog resolves projects/* citizens (todo #132,
DPLAN-0290 night shift item 0). `watchdog agent @baud` reported
agent-not-found minutes after the admin lane's first dispatch reached that
seat: the resolver checked the main registry and external `~/Projects` roots
but never descended into `<repo>/projects/*/` where project citizens live.
New sweep of `projects/*/*_REGISTRY.json` mirrors ai_mail's admin-lane scan
and runs AFTER the main registry so a local branch always wins a name
collision (tested both ways, red-first, world pinned to tmp_path). Suite 488
green; live-proven against the exact failing command.

## [2026-08-12] — v2.7.16: admin grant lane live, cross-project bridge, BAUD product night, telegram blip fix

**fix(trigger tests)** — signature-fragmentation tests pin their own registry
(by @devpulse in-train, PPLAN-0034). Two collapse tests read the live
`AIPASS_REGISTRY.json` through `_find_repo_root()` — green on any dev machine,
red on CI's bare checkout where the untracked registry doesn't exist and name
collapse silently skips. Went unseen for 8 pushes because nobody watched the
PR checks between trains. Fix: an autouse fixture registry carrying the corpus
names, the same pattern the file's registry-lifecycle tests already used.
Escalation lane code untouched. Proven red→green in a tracked-only
`git archive` checkout; trigger suite 932 green.

**fix(skills)** — telegram send path stops escalating network blips (by
@skills, base_bot v1.6.1, FPLAN-0402, error 9353d1ae). `send_message`
exhaustion is now classified with the same `_is_network_error()` the poll
path already used: unreachable host logs WARNING ("sendMessage abandoned...
Telegram unreachable") instead of a flat ERROR; API rejections and unknown
faults still log ERROR. Retry budget, backoff timing, and the
`messages_failed` health counter unchanged, so real outages stay visible.
Bonus in the same function: HTTPError caught separately with the description
pulled from the response body — a 400 now names its cause. 7 new tests plus
a real-stack proof (broken `socket.getaddrinfo` through genuine urllib);
telegram suite 1090 green, audit 100%, all 5 bots restarted.

**fix(ai_mail)** — cross-project replies deliver back (by @ai_mail, FPLAN-0401
phase 5b — the gap the live proof caught: the first-ever admin dispatch
reached @baud, but @baud's reply was refused at the boundary; test suites
modeled mail going in, nobody modeled the answer coming out). New
`_is_sanctioned_reply`: a reply crosses the boundary iff it carries an
`in_reply_to` present in the SENDER'S OWN inbox and is addressed to that
mail's sender (or its `reply_to` — fields only the original sender could have
written). Forged ids, redirected recipients, and non-reply outbound all
refuse with today's wording character for character. Patrick's same-evening
ruling pinned the model: REPLIES ONLY — projects citizens answer
conversations the admin opened, never initiate (his own live test from the
baud seat is the negative proof, caught in the log at 17:54). Ceremony
happened mid-build; the suite's lane-dark tests were rebuilt to simulate a
failing grant instead of asserting a dark world, with a stat-only key guard
(never content). 9 tests red-first + 2 mutation checks, suite 1048 green,
audit 100%.

**feat(ai_mail)** — cross-project bridge, built dark (by @ai_mail, FPLAN-0401
phase 5, DPLAN-0288). Verified-admin dispatches can now resolve and deliver
into `projects/*` trees (@baud et al.): branch resolution gains an admin-only
sweep of `projects/*/*_REGISTRY.json` that runs LAST (a local branch always
wins), and `_check_cross_project_boundary` gains a verified-admin exemption
placed after every existing early-return — same-project mail never touches
the grant (tested), everyone else's refusal wording unchanged character for
character. Privilege verdict deliberately NOT cached per process (a cache
keeps a torn-up grant alive = failing open). Gates mutation-proven (`if
True:` substitution sent 4 tests red incl. both lane-dark end-to-ends). 18
tests red-first, suite 1039 green, audit 100%, no new bypasses. One
pre-existing env-sensitive test fixed and flagged. Vera-Studio (separate
repo) stays phase 2.

**feat(ai_mail)** — admin dispatch lane, built dark (by @ai_mail, FPLAN-0401
phase 4, DPLAN-0288). `wake_branch()` gains keyword-only `admin=False`: a
VERIFIED devpulse dispatch to a manager-class target now routes headless
through the dispatch-monitor pipeline (350k pin) instead of being mail-only.
Verification lazy-imports devpulse's `verify_admin_grant` 5-leg reference —
one implementation, no drift; ImportError or missing key = lane dark = today's
behavior byte-identical. WAKE_BLOCKLIST now fences BOTH privileged lanes: an
admin dispatch targeting @devpulse is still refused (tested) — the seat
asymmetry stands. Scheduled-wins ordering pinned (a 5am rotation never logs as
admin). The `wake.py __main__ --sender` door closed on the same rail
(live-proven refusal). Verifier only runs for the grant holder (noise
control); a raising verifier degrades to non-admin and mail still sends. 25
tests (lane red-first; wiring mutation-tested and said so), suite 1021 green,
audit 100% with two documented bypass entries (no compliant cross-branch
import shape exists — reasoning in bypass.json).

**security(ai_mail)** — sender-spoof holes closed on both doors (by @ai_mail,
FPLAN-0401 phase 1, DPLAN-0288). The `--from` flag (dispatch-send) and the
`--sender` flag (wake path — second door self-found by @ai_mail, not in the
scout report) were unauthenticated strings fed straight into `wake_branch`'s
privileged `sender` param: any caller could claim `@daemon` and unlock the
interactive manager wake. New `verified_caller.py` rail resolves the real
caller from `AIPASS_CALLER_BRANCH` / passport-walk (never bare cwd); a
privilege-bearing claim the rail can't prove is refused loudly BEFORE the
send; ordinary `--from` mail identity untouched; the wake sender (and
wake-back) now always attribute to whoever actually ran the command. 27 tests
red-first incl. a structural canary that fails if a future sender literal in
wake.py skips the privileged set. Live-proven refusals (exit 2). Suite 996
green, audit 100%.

**feat(spawn)** — admin-grant ceremony support + admin never mintable (by
@spawn, FPLAN-0401 phase 2, DPLAN-0288). `ensure_admin()` mirrors the
sealed-owner writer: sets `admin:true` on the devpulse registry ENTRY only —
the seat is a constant, any other name is a named refusal with zero writes;
CLI `drone @spawn grant-admin` takes no branch argument by design (Patrick's
one-time ceremony). Success output states the honesty leg: the flag is one of
five legs, alone it grants nothing. `FORBIDDEN_CLASSES={'admin'}` fenced at
five doors incl. PRE-parse (create's grammar would otherwise swallow "admin"
as a target path and never reach a class check — self-found). 28 tests
red-first, suite 409 green, audit 100%.

**feat(devpulse)** — birth-certificate admin grant tooling (by devpulse,
FPLAN-0401 phase 3, DPLAN-0288). Patrick's design: the admin privilege rides
on devpulse's EXISTING birth certificate (SYSTEM-minted 2026-03-07, in
spawn's never-update list, untracked by git). New `admin_grant` module —
keygen (`~/.aipass/admin_grant.key`, 0600, outside every repo), mint (signed
`privileges` block, HMAC-SHA256 over canonical cert), verify (the 5-leg
contract: verified caller → registry-resolved cert path → content →
signature → registry flag; every refusal named, missing key = lane dark).
Ceremony verbs owner-gated. 17 tests incl. the tamper canary (any
post-signing edit kills the signature), suite 486 green, checklist clean.

**feat(daemon)** — nightly steward rotation shipped dark (by @daemon,
DPLAN-0287 daemon-to-production). New `rotation` schedule type: one
fleet-steward job (05:00, sonnet, ships `enabled:false` — flip to go live)
walks the citizen roster one branch per night with a templated steward prompt
(inbox → todos → logs → self-audit → APLAN → report); busy target = logged
miss, pointer advances, no starvation logic. @devpulse never on the roster;
managers excluded behind `include_managers:false` with a live signature probe
on wake_branch's `scheduled` param (lane detected: manager wakes go headless +
pinned the moment the knob flips). Discovery widened to `projects/*` sealed
registries (five manager seats found and swept — roster unchanged until the
knob, by design). Runstate prune now persists on no-fire ticks (stale June
entries finally cleared). 62 new tests (40 rotation), suite 406 green, audit
100%. First live steward night still unproven — flip is the ceremony.

**feat(ai_mail)** — scheduled-manager headless lane (by @ai_mail, DPLAN-0287
daemon-to-production). `wake_branch()` gains keyword-only `scheduled=False`:
daemon-scheduled wakes of manager-class citizens now route headless through
the dispatch-monitor pipeline (350k pin applies) instead of an unattended,
unpinned interactive tmux session; WAKE_BLOCKLIST targets are refused in the
scheduled lane with a named reason (lane-gated, fail-closed). Defaults keep
every existing path byte-identical — manual manager self-wakes stay
interactive. 8 tests red-first, suite green, audit 100%. Groundwork for the
5am steward rotation (@daemon building the rotation primitive in parallel).

**fix(prax)** — live-monitor display crash no longer kills the Telegram relay
(by @prax, morning trigger-triage dispatch). One tailed log line carrying a
bracketed path (`[/usr/bin]`) raised an uncaught Rich MarkupError inside
`_display_worker`, killing the queue's only consumer — the relay hangs off the
same thread, so Patrick's TG monitor feed went silently dark 2026-08-11 11:29
while event_queue warned "queue full" every 30s (1144 warnings across rotated
logs; the flood was the alarm, not the fire). unified_stream 0.2.0 escapes
every dynamic value before markup (bracketed paths crashed; `[event_queue]`
prefixes were silently eaten); monitor 0.4.0 guards each render (one undrawable
line costs one line, failures counted + rate-limited) and relays BEFORE
rendering so a console failure can never take the feed again. Separate defect
self-found while proving: the service's `run` argv token was parsed as a branch
scope once scoping became real (08-11 fix), so a naive restart would have come
up scoped to nonexistent branch RUN — leading `run` now recognized as the
subcommand (monitor.py `_standalone_run_args`). Red-first A/B on the real
stack + headless live injection; 25 new tests through a REAL Rich console
(shared conftest MagicMock cannot fail this class); suite 1221 green, audit
100%. The queue-full WARNING stays loud by design — it was the only instrument
still reporting the outage.

**night-shift 2026-08-12** — @baud's first-day field notes turned into three
same-night fixes (FPLAN-0400, each owner-dispatched, red-first, live-verified
from the reporting seat): **fix(hooks)** cross-project file fence shipped
(GH #733: edit_gate 1.3.0 gains a project layer — a projects/* seat could
write src/aipass/* unchallenged because both path sides resolved to empty
branch; upward+sideways now blocked, downward allowed, proven through the
real bridge from @baud's seat). **fix(ai_mail)** refused sends no longer
recorded as delivered (sent record was stamped before delivery; refusals now
restamped with reason, kept as evidence) + the scrambled refusal output was
a real routing bug (send handler answered for commands it didn't own, so the
router re-ran failed sends — doubled records included; hard command gate,
refusals exit 2, outcomes announced instead of intent). **fix(memory)**
GH #728 normalize guardrail fails-open fixed for real (per-entry number
validation — crash mode structurally gone; unreadable rows hold their index
and warn on three channels; numeric-string numbers self-heal on next touch).
Plus: fleet-wide `autoCompactWindow` 350k stamped (17/17 branches + dispatch
pin via @ai_mail, m11 phase 4), the fleet rich-markup sweep (29 sites) rides
this train, and BAUD m11 settings arc closed out (baud repo 5d340b7).
Issues #733/#728 commented and left open pending independent verify.

**fix(trigger)** — escalation signatures no longer fragment on counts and
citizen names (by @trigger off a devpulse dispatch; the 2026-08-11 storm
put 18 digests for ONE logical event in the manager inbox — the state
table held 148 signatures for it, 30% of the cap). The collapse is local
to the escalation signature path (registry fingerprints keep their finer
grain for `errors list`/medic): standalone numbers with optional short
unit suffix → `<id>` (the suffix rule caught "1237ms" durations — and with
them a second, unreported 72-signature hooks-gate storm), registered
citizen names + any `@handle` → `<branch>`. The placeholder deliberately
matches the registry's `<id>` token — a different token measurably
re-fragments at the 100 boundary. Measured on live state: prax event
148→6, hooks storm 72→6, corpus 500→250; the residual 6 are genuine
source-kind variance (file/log/agent/hook), meaning not values, left
untouched. Also a test-integrity catch: a MagicMock'd normalizer had one
test green without ever running the code it named, and two more vacuous
via numeric distinguishers — all five repaired against the real
normalizer. 12 new tests incl. the pinned storm pair, canary red-first
(9/12 red on revert, 3 anti-over-collapse guards correctly green both
ways), suite 929 green, audit 100%.

**fix(skills/telegram)** — log streamer 400s root-caused and killed (by
@skills off a devpulse escalation dispatch; 80 lifetime failures since
08-08). One log line over Telegram's ~4096 cap slipped the batch guard —
`if batch_len + line_len > MAX and batch:` never flushes an EMPTY batch, so
an oversized line went out whole; 5/5 correlation between >4000-char router
lines and 400s within 2-6s, burst window = @seedgo's audit window. The API
named the offense once asked: probed sendMessage with real credentials —
"message is too long" confirmed; MarkdownV2 escaping empirically RULED OUT
(4000 chars of brackets/underscores/stars accepted; no parse_mode on this
path). log_streamer.py 1.2.0: oversized lines chunk with lossless [i/n]
markers before batching, empty/whitespace payloads refused pre-network,
blank lines dropped by stated rule, and the 400 response body is now
LOGGED with payload size instead of discarded. Live-proven: the actual
5,167-char offender now delivers as 2 messages; post-restart canary (5,300
chars + blank + whitespace) produced zero 400s. 10 new tests, telegram
suite 1083 green, audit 100%.

**feat(seedgo)** — rich_markup, the 44th standard: unescaped `[tokens]` in
console.print are silently eaten by Rich at render time — correct source,
100% audits, mangled output (by @seedgo off @prax's dispatch; the rule
class devpulse swept locally the night before, now fleet-enforced).
Measured before shipping: 29 real losses across 14 branches, fleet average
93% but nobody under the 75% threshold, so it registered live without
turning anyone red. The losses concentrate in apps/<branch>.py --help
surfaces — the text read by the person with the least context. One
self-caught false positive fixed pre-fleet (`markup=False` pass-through is
the correct move, not a violation; both directions pinned). Also ships the
audit exit artifact @prax asked for (`.seedgo/last_audit.json`, complete
untruncated violation set, `--artifact/--no-artifact`) and retires the
"NEVER use logger.debug()" doctrine line — which the grep found was
contradicting debug_print_content's own advice. 77 new tests (suite 1494
green), self-audit 100% across all 44.

**chore(prax)** — bypass debt paid with measurements, not guesses (by
@prax, riding @seedgo's new audit artifact): ran the branch un-bypassed,
attributed all 76 rules, re-ran with survivors — 45 deleted, 31 remain,
audit 100%, suite 1132 green. All 45 were waivers that outlived their
violation; the method is handed to @seedgo in case it becomes a command.

**fix(drone/auth)** — passport-gate denial now names the caller's cwd (by
@devpulse in @drone's tree — small-fix lane; answers @trigger's x10 repeat
escalations on captured_auth/captured_git_module). The "cannot verify
caller" warning carried no CWD or PID, so identifying who kept tripping
the gate took a cross-log timestamp correlation instead of one grep
(culprits turned out to be sessions running `drone @git status` from
passport-less dirs like repo root). Message now embeds `caller cwd:`;
@trigger's normalizer collapses paths to `<path>` (verified), so repeat
signatures stay unified across callers and the digest upsert counter keeps
climbing in place. Live-verified from a passport-less dir; drone suite 985
green.

**feat(prax)** — SystemLogger.debug(), and the gate that makes it real (by
@prax, promised follow-through ex-todo #116, morning-wave dispatch).
debug() alone would have shipped dead: DEFAULT_LOG_LEVEL="INFO" was
hardcoded at four setLevel sites, and Python's logger-level gate runs
before any handler's — DirectLogger has carried a debug() since 2026-02-27
that never emitted a line. The dormant `log_level` config key (declared
since 2025, loaded, read by nothing) is now read per tier, plus an
AIPASS_LOG_LEVEL env override; precedence env → tier → INFO, unrecognised
values warn once and fall through. Logger sits at min() of the two tiers
so "quiet central, verbose branch-local" actually works (asserted by
test). Default behaviour unchanged — no config, no env, nothing new in any
log. Canary-verified both directions + live-probed on the production path;
every gating test carries an INFO control line (an absent debug marker
alone proves nothing). 26 new tests, suite 1132 green, audit 100%. Known
caveat (documented): levels bind at logger creation — long-running
processes pick up changes on restart. Two fleet rules now contradict
shipped code ("logger.debug not supported" in @hooks auto_fix +
@seedgo standards text); @prax dispatched both owners to retire them.

**feat(daemon)** — fleet inbox sweep: unread mail can no longer rot silently
(by @daemon, FPLAN-0394, morning-wave dispatch; design from devpulse backlog
ex-todo #119). Daily 09:00 job (own `.daemon/schedule.json`, wake-only →
haiku wake runs `drone @daemon inbox-sweep`): scans every active branch's
inbox for `status=='new'` older than 24h and wakes the owners, oldest-first.
`inbox_scanner.py` is pure detection (no cross-branch imports);
`inbox_sweep.py` owns wake policy — one wake per branch per sweep, 2s
stagger, managers skipped and reported (self-enforced: `@daemon`-sender
wakes bypass ai_mail's manager gate by design, so the sweep checks
citizen_class + is_wake_blocked itself), capped at 5 wakes/pass with
deferred branches named, never dropped (`--limit` overrides; also
`--dry-run`, `--hours N`). First live dry-run found the disease it was
built for: 8 stale unread across @backup/@drone/@spawn/@seedgo, oldest 62h.
44 new tests (suite 344 green), audit 100%, 5 dead bypass rules pruned
same-touch.

**feat(ai_mail)** — culture fence line in dispatch headers (by @ai_mail,
DPLAN-0276 leftover, morning-wave dispatch). Both header constants
(DISPATCH_HEADER and NO_MEMORY_SAVE_HEADER) now carry the attribution
fence after the sync-subagents warning: "Found work in the tree you cannot
explain? REPORT it — never invent an author." Unexplained changes are
evidence, stated and attributed to no one — the rule that closed the
DPLAN-0276 invented-author incident now rides every dispatch a recipient
reads. header.py 1.2.0; 3 canary-verified tests (fence stripped → red,
restored → green), including one asserting the fence survives
prepend_dispatch_header. Suite 924 green, audit 100%. The second DPLAN-0276
leftover (stale TRUST-BREAK banner commands) turned out to live in @hooks'
config loader, not @ai_mail — @ai_mail measured it (`drone @hooks trust
enroll` is not a real verb; the working path is `aipass trust <path>`) and
emailed @hooks so the one-line fix rides their next touch.

**perf(devpulse)** — watchdog poll loop 142× cheaper (by @devpulse; todo
#126, night shift FPLAN-0393). Each 5s tick cost 152ms of CPU (~3% of a
core per armed watchdog, compounding across concurrent watches): two
pathlib rglobs over the branch's 300-file transcript dir plus a 1MB tail
re-read even when nothing changed. agent.py 1.3.0 introduces
TranscriptScanner — full re-walk only every 60s (os.walk), per-tick is one
os.stat pass over the cached list (1.07ms), and the in-flight tail parse is
cached on (size, mtime) since an unchanged file cannot change its last
entry. Also closes a remaining stall false-positive: a parent blocked on a
sub-agent that is silently composing (newest transcript idle-looking, no
growth) now counts the parent's own in-flight Agent tool_use — both the
newest and newest-top-level transcripts are candidates — and the tracker
forces a fresh re-walk before ever declaring STALLED so a transcript born
between refreshes suppresses the false alarm. Live-verified: pidstat
steady-state 1.73% → 0.27% per handler; synthetic-lock watch woke next tick
on lock removal. 6 new scanner tests; watchdog suite 27, devpulse suite 469
green. Follow-up after CI's fleet audit caught the rewrite honestly
(unused_function 98%): the four pre-scanner helpers the loop no longer
calls were deleted rather than bypassed, their tests ported to the scanner
and the pure `_inflight_from_lines` (the actual production path), restoring
the audit to 100%; four dead encapsulation bypass rules pruned in the same
touch.

**fix(drone/git)** — `drone @git status` and `diff` no longer false-green
on git failure (by @devpulse in @drone's tree — small-fix lane; backlog
flag from old todo #102). Both exited 0 unconditionally, and `status --all`
even overwrote the handler's error message with "0 file(s) changed in repo"
— a failed git read was indistinguishable from a clean tree to scripts and
CI. Handlers now stamp `ok` on every return; the module surfaces failures
as exit 1 with the git error verbatim on stderr, and the `--all` reword
only applies to success. 4 regression tests (module + handler level); drone
suite 985 green.

**chore(prep-skill)** — /prep now pins the interrupted thread as step 0 and
ends every run with a mandatory `Resuming:` line naming what was in flight
and the next concrete action (Patrick, todo #127: auto-triggered preps were
flushing the live task — the session wrapped up tidily and then lost the
thread). Pit stop, not a finish line: if something was in flight, the same
turn picks it back up; before a /compact the line carries enough for the
post-compact self to continue without re-asking.

**fix(devpulse)** — the bracket sweep @prax requested, run on devpulse's own
surfaces (night shift FPLAN-0393): `drone @devpulse --help` was silently
losing its `[args...]` usage placeholder and `watchdog --help` its optional
`[command]` — same Rich markup-eating class as the prax fix below. Both
escaped; devpulse gains its own rendered-output canary suite
(test_help_markup.py, 7 tests through a REAL Rich console) covering the
help surfaces plus the watchdog status/cancel `[handle]` prefixes, with a
control test documenting why `[--timeout SECONDS]` never needed escaping
(dash-leading tags are not valid Rich markup). Compass/feedback surfaces
audited clean.

**fix(prax)** — Rich markup no longer eats literal `[bracketed]` text on
prax's console surfaces (by @prax). Unescaped `[word]` is silently consumed
as a style tag — `monitor run [branches]` rendered as `monitor run` with no
error. Escaped in monitor/prax help, logger lifecycle prints, and every
log-health row's `[branch]` attribution tag. New rendered-output canary
suite (test_help_markup.py, 9 tests) renders through a REAL Rich console —
the shared conftest's MagicMock records calls but never renders, so it
cannot catch this class. README truthed: commons feed mode documented
(filter <room>/filter clear, --relay), Known Issues now states exactly
which interactive commands Mission Control dispatches. 14 stale bypass.json
entries pruned (test-directory false-positives whose checker causes were
fixed). Suite 1106 green.

**feat(ai_mail/trigger)** — repeat-warning digests collapse into ONE inbox
message with a climbing counter (by @ai_mail, @trigger; FPLAN-0389, Patrick
ruling 2026-08-10). ai_mail's delivery layer gains an opt-in `upsert_key`:
same sender + same key + not-closed updates the existing message in place —
subject/body refreshed, `updates` counter climbs (inbox row `x4`, view
header `Updates:`), id and read-state preserved, desktop toast suppressed on
updates, `auto_execute` forced off in delivery, broadcast+key refused
loudly. CLI `--upsert-key`. trigger's escalation lane passes
`escalation:<signature>` threaded explicitly past its `**kwargs` adapter
(mutation-tested guard); medic/runaway paths byte-identical; upsert outcome
audited in escalation.jsonl. 56 new tests (ai_mail suite 921, trigger 917),
seedgo 100% on all touched files, live-proven end to end: created → viewed →
updated in place, same id, still opened.

**chore(memory/seedgo/prax)** — bypass-hygiene train (by @memory, @seedgo,
@prax; FPLAN-0382 follow-through). Stale bypass.json entries pruned in
memory and prax after their underlying causes were fixed; @memory's
symbolic extractor drops the caller-less `analyze_conversation_llm` v2
twin its bypass had flagged pending-deletion, with test_symbolic_extras
reshaped to the surviving surface; @seedgo's inert/audit_display refined
with new test_bypass and test_coverage_audit coverage. 237 touched-file
tests green at commit time.

---

## [2026-08-09] — v2.7.15: scope-aware standards, streamer loop kill, Windows tie data-loss fix, aipass read train

**feat(aipass)** — `aipass read` + version truth + Telegram readiness at
doctor time (by @aipass). New `read` command renders any branch README in
the terminal straight from the live file (the depth step behind `aipass
help`; list mode when no branch given, @-prefix tolerated). `--version` now
resolves from the repo's own pyproject.toml with a tomli fallback on 3.10.
doctor gains a telegram_readiness check that surfaces BotFather automation
gaps only on machines that actually host bots — convenience warning, never
an error, silent on plain installs. help_chat and readme_map sharpened;
README updated. Test suite grows to 977 passing.

**fix(ai_mail)** — sender identity resolution is now forensically loggable
(by @ai_mail). A COMMONS-authored dispatch once filed under @aipass left
only "from_branch: null" in the logs — no record of who the sender became
or which resolution path decided, costing hours of cross-mailbox forensics.
Every resolution now records strategy + input + resolved identity + mailbox
path at the moment of decision, and branch_detection hardens the walk-up
(env-var caller first, passport walk second, explicit precedence). New
test_send_identity.py pins all resolution strategies; 881 passing.

**docs(commons)** — branch prompt truthed to the standard layout (by
@commons): src/aipass/commons/ paths corrected, registry lookup now
documents the external-citizen fallback via the caller's own registry.

**fix(trigger)** — Windows escalation flake was data loss, not display (by
@trigger). datetime.now() ties on the 15.6ms Windows clock made the
last_seen sort non-deterministic — and _prune sorts by the same key to pick
evictions, so a tied clock dropped the signature just written and kept the
stale one. Fix: the state document carries a write_seq counter and both call
sites sort on one shared (last_seen, last_seen_seq) key — deliberately NOT
time.monotonic(), whose per-process epoch is meaningless after a restart.
No migration; missing keys default to 0. Three regression tests with a
frozen clock reproduce the Windows tie on any platform, red-green probed
(two initial tests passed for the wrong reason via insertion order and were
rewritten to make creation and touch order diverge). Post-0384 settlement,
measured NOW = OLD = NONE: the deleted tests/ bypass rules are formally
moot — nothing left to restore. Bypass file 25 → 24 (one leave-one-out-dead
rule dropped, two reasons re-derived to match present code); liveness sweep
says all 24 earn their keep. Caveat for the audit info channel:
functions-scoped rules read DEAD under record-field attribution because
unused_function records bury names in issue strings — auto-pruning on that
signal would delete working rules fleet-wide.
source (by @skills). The streamer logged "Found N new log lines, sending to
Telegram" every cycle; with system_wide=True that INFO landed in its own
capture file inside its own watch glob, so each cycle manufactured the fuel
for the next — 1,495 loop lines and a ping every ~6s on Patrick's phone. The
announcement is deleted (forwarded lines are their own evidence) and a
structural guard now drops the streamer's own log family first in
_filter_lines, unconditionally — no level anyone adds later can reopen the
loop, and a WARNING from a failing send would have looped hardest of all.
Boot line now prints the real glob instead of claiming branch scope while
watching everything. Trade-off, ruled delete-over-tune: bot-level errors no
longer reach Telegram (still on disk + journalctl + medic scope); phone-side
bot health needs its own de-duped heartbeat path if ever wanted. 9 new
self-exclusion canaries (one behavioural: a _run cycle emits no "Found");
telegram suite 1073 green. Deploy verified live: 5 bots restarted, 210s+
quiet where it fired every 6s, forwarding canary still delivered.
both lanes (by @seedgo). The audit lane walked apps/ regardless of what a
checker declared and run_checklist filtered nothing, so the same standard was
production-only in one lane and everywhere in the other — structural checks
failed on 96% of the fleet's test files and branches papered over it with
suppression. New aipass_standards/applicability.py declares APPLIES_TO
(production / tests / everywhere, default everywhere so a new bug-finding
checker is never silently muted) and BOTH collectors consult it. Deliberately
NOT folded into AUDIT_SCOPE: that constant says where a result is REPORTED,
and conflating the two axes is what created the disagreement. Retired code
(.archive/, deprecated/) is now excluded from both lanes — the checklist lane
used to flag archived files nobody can fix without un-retiring them — and the
exclusion is part-based, closing a latent Windows bug where the audit's
"/.archive/" substring pattern never matched and CI audited archived code the
local run skipped. Measured, bypass disabled: fleet test files 1185 failing
(standard, file) pairs → 205; architecture 439 → 0, encapsulation 247 → 0,
documentation 163 → 0, meta 112 → 0, trigger 19 → 0, while every bug-finding
standard is untouched (windows_compat 63, silent_catch 41, hardcoded_path 32
— scoping, not muting). 0 production files misclassified; 42 archived files
excluded fleet-wide. trigger_check's private copy of the bypass matcher —
the third implementation in the tree, and the only one that never received the
FPLAN-0382 scope fix — is gone; it still fall-through-matched, so a 'lines'
rule muted the whole file for that standard. utils.matching_rule() now backs
is_bypassed() and hands the rule back for the category/reason annotations that
copy existed for. The audit cache now fingerprints the bypass/ and audit/
packages, so a checker-semantics change busts it instead of serving green-stale
results (that gap is why the wave-2 fleet verification read 17/17 from cache
while CI was red). Branches keep their now-dead rules until their own next
touch; each one is named on the audit's non-scored info channel with a count,
not a wall of identical lines. **Correction to the entry below:** windows_compat
is NOT line-blind. Canaried through all three paths — checker, audit lane
_run_all_files, checklist lane — a lines rule suppresses in every one, and a
non-matching line number suppresses in none. devpulse's registry.py rule said
lines [138,149] while `import fcntl` sat on 139 and 150 in the same commit that
introduced the rule (57285740): off by one from birth, harmless only because
the pre-0382 fall-through was muting the whole file anyway. The honours map was
right; the rule was wrong.

**fix(devpulse)** — watchdog _FileLock fcntl imports restructured into
checker-recognized platform guards; windows_compat bypass rule DELETED
(FPLAN-0382 residue, own branch). CI's fresh seedgo-audit caught what
the local fleet run could not: devpulse's own trued-up lines[139,150]
rule went inert under wave 2 (windows_compat is line-blind — trigger's
honours-map was wrong on this one standard, seedgo's AST scan right),
and the local 17/17 verification was all "(cached)" because the audit
cache doesn't fingerprint bypass/utils.py — the checker-semantics
change never busted it. Fix at source instead of file-wide: the
checker only sees imports INSIDE an if-sys.platform block (the
early-return guard shape is invisible to it), so __enter__ moved to a
positive platform guard and __exit__'s guard gained the explicit
platform check. Rule deleted outright — the honest end-state a
file-wide bypass would have papered over. 456 devpulse tests green;
audit --full (uncached) Windows_Compat 100%, Overall 100%. Cache-gap
finding queued for seedgo's board.

**fix(seedgo)** — FPLAN-0382 wave 2: bypass scoping is real now (by
@seedgo). is_bypassed rewritten around _scope_matches(): every scope
the caller can evaluate must match AND at least one declared scope
must be evaluable — a rule declaring scope nobody supplies is INERT,
not file-wide (stricter than briefed; a pre-existing test proved the
naive version wrong and the design was refined, not the test). The
deeper truth, AST-derived: only 4 of 42 standards evaluate scope at
all (cli/encapsulation/stderr_routing pass line, unused_function
passes name) — so new machinery ships with the ruling: bypass/inert.py
reports every inert rule on the audit's non-scored info channel, with
the scope-support map derived from checker sources by AST so it
cannot drift. pattern field documented ANNOTATION-ONLY (the notes
example was teaching the fiction — removed). Trigger's in_except bug:
THREE defects (never cleared inside class bodies; reported 0-based
indexes as line numbers; reported only the first silent except) —
rewritten on AST, trigger's repro files now score honestly. Drone's
spurious 0%: root-caused — IndentationError is not a TokenError, a
mid-save file escaped check_branch and scored the branch a flat mute
0; fixed to degrade like _extract_functions, and crashed checkers now
carry their error into checks[] so a 0 always arrives with its reason.
Own rules: 52 → 34, zero lines rules left — after restoring ONE
over-pruned rule (dead_code reports as prose, invisible to
violation-key scans; caught in self-verification at 95%). Old-vs-new
fleet measurement, cache off: 1 newly-red — exactly the pre-declared
drone pr_handler rule (inert lines key on a line-blind standard);
devpulse dropped the key per the rule's own documented intent. Two
method blind spots flagged for the morning report: the checklist/hook
lane audits tests/ WITH bypass rules (trigger deleted 18 tests/ rules
on audit-only evidence — live for the hook lane, will trip on next
test edit); branch-level standards report as prose. 1372 tests (+12,
all canaried), fleet 17/17 at 100%, average 100%. WS-B doc moves ride
along (legacy json_structure.md → .archive, handlers.md pointers
fixed). Re-verified by devpulse: suite + fleet audit.

**fix(fleet)** — FPLAN-0382 wave 1: all 77 line/function-scoped bypass
rules trued up across 8 branches in parallel (by @skills @commons
@aipass @memory @spawn @drone @prax @trigger, orchestrated by
devpulse; Patrick night directive, max 2 waves). Context: @seedgo
proved is_bypassed()'s line=None fall-through makes every scoped rule
a silent WHOLE-FILE bypass — so before the 3-line fix can land (wave
2), every rule had to face the raw checker. The fleet independently
converged on the same honest method: pull the rule and re-audit;
prose is not evidence. What the sweep found: nearly every line number
had drifted (drone: all 9, in four separate edit-eras; devpulse's own
was off by one); reasons had rotted into fiction (memory: a rule
excusing a function called twice in-file; aipass: a documented caller
that hasn't existed since their own refactor; spawn: two rationales
SWAPPED between files); rules outlived their violations (prax: all 6
lines now compliant console.print; commons: deleted by fixing the
odd-one-out label instead). Trigger, the deepest cut: 84 rules → 25,
4 violations fixed at source instead of excused (incl. two invisible
wake_branch failures now logged WARNING), the CI readme red fixed and
PROVEN on a self-built clean checkout (tree fence describes checkouts,
prose describes runtime). Wave-2 rulings surfaced for @seedgo: 7
standards never pass a line to is_bypassed (scoped rules on them can
NEVER match post-fix — skills proved correct-line RED / file-wide
GREEN by simulation; trigger mapped the full honours/ignores split);
the pattern field is DECORATIVE (prax: is_bypassed never reads it);
error_handling's in_except flag never clears inside class bodies
(trigger); one spurious Unused_Function 0% (drone). Also: prax
shipped the INVERTED-direction resync fixture (mocks raw-written INTO
sys.modules — cascading eviction, xdist-proven at 3 worker counts),
closing the Windows CI red. Every branch: audit 100%, suites green,
re-verified by devpulse before commit.

**fix(seedgo)** — handlers checker compared packages, not branches (by
@seedgo, on @trigger's reproduction; the last CI seedgo-gate blocker).
Ruling: the published text was the intent — the standard says twice
that same-branch handler imports are ALLOWED across packages, and
check_handler_independence() rejected its own shipped ALLOWED example;
root-level handler files could never pass at all (own_package resolved
to the filename, exempting an impossible string). Rewritten
branch-level: cross-BRANCH handler imports forbidden, same-branch
free; unrecognizable layout returns an explicit "rule not evaluated"
pass instead of flagging everything. The old json_handler exemption
removed as a real hole (any branch could import any other's
json_handler past the DPLAN-0246 encapsulation ruling; fleet-grepped —
all 4 occurrences comments/strings, AST-invisible). No-regression
MEASURED, not asserted: all 623 handler files scored under old and new
logic — 0 newly failing, 142 newly passing across 12 branches (trigger
reported it but carried only 6; the false positive was quietly taxing
the whole fleet). Bonus from trigger's third report: cli_check's
duplicate-display scan was substring-based and read TrailLogger's
.error() METHOD as a duplicate of cli.display — AST rewrite,
module-level defs only, canaried 8 cases both directions; trigger can
drop its cli_flags bypass. Held deliberately: the is_bypassed
line=None fall-through fix (3 lines, written and MEASURED: 37 files
across 6 branches would go red from 60 stale line-scoped rules that
have been silently whole-file bypasses — every checker's top-of-file
gate matches them, making all 21 per-line call sites dead code) — a
correct fix with a wrong rollout is still red CI; staged options
queued for Patrick. 1359 passed (+6), fleet 17/17 Handlers 100%,
trigger confirmed 100%. Re-verified by devpulse: suite + trigger and
seedgo audits both 100%.

**fix(trigger)** — escalation-lane audit flags: four resolved at the
root, the fifth raised as a checker bug instead of routed around (by
@trigger). silent_catch + error_handling were one finding in two hats:
seedgo only recognizes literal `logger.<level>()` calls, so the
`_log_warning()` helper — which really wrote every exception to the
JSONL sidecar — read as 16 silent catches. Rather than a 13th
file-wide "cannot log a failure to log" bypass, TrailLogger moved into
apps/config.py (the one module that can't import prax's logger —
circular) and both files bind a module-level logger from it: all 16
sites are now recognized log calls, ZERO bypasses on the two newest
files, and nothing self-feeds (still never touches prax). The one
genuinely unreportable site — the sidecar's own write failure — went
from `pass` to a `.dropped` counter surfaced in `escalation status` as
"Trail lines lost". unused_function: reset_config_cache() deleted (six
test callers, zero production; a CLI call would be dead code — fresh
process per invocation means the cache is always cold there).
custom_config readme finding: already resolved by seedgo's FPLAN-0380
work — verified, not claimed. Self-caught: moving the sink orphaned
conftest's ESCALATION_LOG constant patch — 898 tests would have
silently written the LIVE escalation.jsonl; all six sites now swap the
logger object. +8 tests (build_digest was the branch's one untested
public function), canary 3-red-then-green. Deliberately NOT fixed:
cross-handler imports — trigger holds at 99% because
check_handler_independence() rejects seedgo's own documented ALLOWED
example and computes own_package as the FILENAME for root-level
handler files (exemption tests "handlers.escalation.py", impossible in
any import); reproduction mailed to @seedgo, restructure only on their
ruling. Also reported: bypass rules carrying "lines" are actually
file-wide (silent_catch never passes line to is_bypassed). 898 passed,
ruff clean, coverage 100/100. Re-verified by devpulse: suite + audit
(99%, sole flag is the checker bug).

**fix(prax)** — Windows CI red root-caused to the assertion, not the
isolation (test_telegram_relay.py 1.2.0, by @prax — correcting
devpulse's brief). `assert Path.home() not in CONTROL_FILE.parents` is
a POSIX-only proxy: on Windows pytest's tmp_path lives INSIDE the user
profile, so the check is False whether isolation works or not — and
the sibling exact-equality test passing on the same CI job proves
isolation was holding. Assertions now state path IDENTITY (== isolated
path, != operator path). The HOME+USERPROFILE redirect went in anyway
as belt to the re-point's braces, scoped to the reload; platform
honesty pinned by Linux-runnable tests calling posixpath/ntpath
expanduser BY NAME (ntpath never reads HOME — drop USERPROFILE and the
Linux runners go red, not Windows six weeks later). Canary: Windows-
shaped layout on Linux (tmp nested under home) reproduced the verbatim
CI error with the old assertion, 62/62 green with the new. Process
honesty: their first simulation (swapping os.path.expanduser) was a
no-op harness — caught, discarded, replaced. Fleet lesson: assert
isolation by identity, never ancestry. 1098 passed / 1 skipped, audit
100%. Re-verified by devpulse: suite + audit.

**fix(drone)** — seedgo unused_function flag resolved by deletion, not
bypass (by @drone). `reset_identity_log_dedupe()` was a public
production function whose only callers were tests — exactly what the
standard exists to catch. @drone verified a per-function bypass was
genuinely available (unused_function honors named bypasses) and
declined it: the standard wasn't wrong, the README's "long-lived host"
justification was a hypothetical, and no natural production caller
exists. Tests now clear the private dedupe set directly (documented
autouse conftest fixture — the established shape, seedgo skips
tests/). Honest extra: their canary showed the fixture is defensive,
not load-bearing (per-test temp dirs mean signatures never collide),
proven both ways with a throwaway shared-cwd pair. Audit 100%, 981
passed / 5 skipped. Re-verified by devpulse: suite + audit.

**fix(ci)** — two small CI reds cleared by devpulse on its own turf.
Devpulse: watchdog transcript reader (agent.py 1.2.1) logged nothing
when it skipped an unparseable transcript line — seedgo silent_catch
flag, now an info log naming the file and the parse error, audit back
at 100%. Flow tests: CodeQL read `assert "https://aipass.ai" in result`
as hostname sanitization (py/incomplete-url-substring-sanitization);
assertion now pins the full template sentence, which is also the
stronger test. Both suites green (devpulse 456, flow 774).

**fix(tests)** — CI-only xdist failures in backup and trigger rooted in
one class: tests that evict a module from `sys.modules` and re-import it
under mocks leave the parent package's *attribute* pointing at the
throwaway twin after teardown (monkeypatch/patch.dict restore the dict,
never the attribute). The next test on the same worker then resolves two
different objects for one dotted name — patches land on one, code runs
the other. Trigger: escalation's medic gates read an unpatched
medic_state twin whenever test_medic_state ran first (deterministically
reproduced: 4 red). Backup: mock.patch on 3.10/3.11 walks parent
attributes and dies with `AttributeError: ...drive has no attribute
'client'` (3.12+ resolves via pkgutil.resolve_name, which is why it
never reproduced locally). Fix: autouse conftest fixture in both suites
resyncs parent attributes with `sys.modules` after every test and drops
attributes whose module was evicted. Trigger repro 4 red → 151 green;
+2 regression tests pinning the desync shape; both suites + full-repo
xdist green. By devpulse (test-only, CI unblock).

**fix(hooks)** — edit_gate's entry-count warning stopped making false
promises (edit_gate 1.2.0, by @hooks; the @memory entry-count bug's
twin, caught by three escalation digests). Same class: the guard
counted the combined sessions array (regular + auto-compact snapshots)
against the regular-only cap, so every healthy branch read "16/15 —
rollover will trim at next PreCompact" on every gate pass — a trim that
could never come, since rollover budgets snapshots separately and had
nothing to archive. Guard now mirrors the extractor's predicate exactly
(sessions split, key_learnings deliberately not — the extractor doesn't
split it either, test-pinned). Second false promise found in the same
function: todos "will trim" — todos never roll, they're hand-pruned;
dormant today but one re-added config key from returning. Warning lines
now name the branch (previously every branch's over-count was
attributed to @hooks, and digest signatures blurred) and state what
actually happens, every clause verified in code. Warn-only confirmed —
nothing was ever blocked, "they were lied to ~10x/hr." +10 tests
(1370), two canaries red with the false lines verbatim, live-verified
against the real 14+2 file: zero warnings. Seedgo 100%. Suite + lint
re-verified by devpulse.

**fix(memory)** — the fleet-wide false ENTRY COUNT warning is gone:
entry-count guard now budgets auto-compact snapshots separately, exactly
as rollover always did (memory_files 1.2.0, built by @memory, parked by
Patrick's ruling, applied as phase 2 of the digest live-test). The guard
counted the combined sessions array against the regular-only cap, so
every healthy branch (14 regular + 2 snapshots) read "16/15" on every
.trinity write, forever — a warning rollover could never satisfy because
there was nothing to trim. Deliberately left LIVE as the escalation
digest's designated first prey; the digest caught it (signature
d3aeeee9ae26, 10-in-60min, emailed @devpulse 21:41), and only then was
the parked, canary-proven patch applied — completing the full lifecycle
test: detection proven by the digest arriving, resolution proven by the
signature going structurally quiet. Guard now shares the extractor's
exact predicate (junk entries count as regular in both). +5 tests
(1046), live-verified against the digest's named file: 0 warnings.
Same-class twin found in @hooks' edit_gate by two more digests — fixed
separately. Applied + re-verified by devpulse.

**fix(drone)** — caller-identity warnings were a category error reported
twice per call, fixed at source (router_handler 1.1.0, by @drone). The
new escalation digest lane's first two catches named this module; the
real bug was deeper than the digest saw. Identity resolution ran twice
per route, doubling every log line — and the "identity conflict" warning
cited a passport at the repo root that has never existed ('aipass' was
the registry-fallback *project name* arriving indistinguishable from a
passport identity; 103 of 105 logged conflicts were that shape).
Detection now returns provenance (passport vs project), messages say
what is actually true, and severity follows meaning: a real
two-citizens conflict stays a loud WARNING, an assigned identity
running at a project root is INFO, an anonymous caller is INFO (a
correct outcome, not a fault). Repeated explanations dedupe once per
process — per-process only, so real conflicts recurring across
invocations still reach the digest, test-pinned. +10 tests (981),
canary red on all three reverts, live-proven: the exact shapes that
tripped both digests now produce zero warnings in 10 calls while the
real-conflict case still warns. First full digest-lane loop closed:
digest → owner fix → signature quiet. Suite + lint re-verified by
devpulse.

**fix(prax)** — every operator-facing monitor line rewritten in plain
language that names its subsystem (40 sites across 10 monitoring files,
by @prax; Patrick ruling). The line that triggered it — `Dropping
events (102...): Full()` — now reads "The live monitor display queue is
full — 102 events were skipped from the terminal monitor view since the
last report. Nothing is lost: the on-disk logs are complete." Split in
two on the way: the old line reported every enqueue failure as
overflow, so an unexpected TypeError would have worn the comforting
"queue is full" wording — expected pressure is now a WARNING saying
nothing is lost, unexpected failure an ERROR saying "this one is a
bug." Subsystem vocabulary standardized in the operator's words (live
monitor display, file watcher, log watcher, Telegram relay, commons
live feed, branch labelling) — including the instance_lock line that
sat unremarked for 1h51m on 07-31 while the relay was stranded
viewer-only. Every reassurance was verified in code before shipping
("plain language can lie faster than a repr can"). Exception reprs
gone except two network lines where the errno text IS the actionable
content. +5 wording-pin tests (1093), canary red on old-line restore,
live-proven overflow in system_logs. The 30s rate limiter untouched.
Ruff + seedgo 100%. Suite + lint re-verified by devpulse.

**fix(backup)** — user-supplied relative paths resolve where the user
actually is, and a live tree changing mid-snapshot no longer aborts the
cycle (by @backup). Two fixes riding together. CALLER_CWD: backup runs
as an installed entry point, so `Path.cwd()` is backup's own branch dir
— `backup share notes.txt` from another project resolved into the wrong
tree and failed with a misleading not-found. New
`handlers/path/caller.py` resolves relative paths against
`AIPASS_CALLER_CWD` (drone exports it; falls back to `Path.cwd()` for
direct invocation), absolute paths byte-identical to before. Sweep found
the same class failing SILENTLY in register/status (registering the
backup branch dir under another project's name and happily backing it
up) — all four sites fixed, registry.py's registry-file path deliberately
untouched (not user input). TOCTOU: the post-snapshot timestamp save
indexed `os.path.getmtime` over files scanned moments earlier — an
editor temp file vanishing mid-run threw FileNotFoundError, aborted the
whole cycle, and surfaced as a bogus "Unknown command" through the
route_command catch-all. Vanished files now skip with a log line
(absent-from-both compares equal; a returning file mismatches and
triggers the full snapshot it needs). +11 tests (263), canary red 6
ways with the exact live failure shapes, absolute-path tests green
under revert. Seedgo 100%. Suite + lint re-verified by devpulse.

**fix(flow)** — template stamping hardened against partial placeholder
values + VERA's weekly_update v2.1 landed (get_template 1.3.1). VERA's
createIfEmpty KeyError report turned out already fixed 08-07 (her field
report predated the fix — flow live-stamped to prove it before touching
anything). The one real remaining hole: `_substitute_placeholders` used
a raw dict index, safe today only because every known placeholder
happens to be supplied — now `.get` with literal-token passthrough, so
a template that loaded when registered always loads when stamped,
structurally. v2.1 landed byte-identical from the dropbox (full
clickable https://aipass.ai URLs per Patrick's directive, Bluesky step
fires from the caller's own branch dir post-v2.7.14). +2 tests (774,
one pinning the REAL shipped template through a live stamp), canary red
with the exact KeyError shape VERA hit. README truth-up: PPLAN/
playbook_plans was entirely undocumented. Live-stamped PPLAN-0032 as
proof, both test artifacts closed through the pipeline. Seedgo 100%.
By @flow; suite + lint re-verified by devpulse.

**fix(prax)** — telegram relay tests no longer read the operator's live
control file (test_telegram_relay.py 1.1.0, tests only). Five tests went
red on the dev machine the moment Patrick paused the prax monitor bot
from Telegram — `_flush_buffer` honors the real
`~/.aipass/telegram_bots/` control file, and the tests inherited his
`paused: true`, discarding every buffered line before assertion (green
on CI where no control file exists). Fix: autouse fixture isolates
CONTROL_FILE per test, applied AFTER the module reload — reload
re-executes the module body and recomputes the path from Path.home(),
so isolation applied before the reload silently lapses; a pin guards
exactly that. Helper now refuses (RuntimeError) outside the fixture
instead of quietly falling back to the operator file. Insight kept from
the fix: module reload already resets literal globals — the only leak
was the one global computed from the environment. +4 isolation pins
(57), canary 8-red/57-green proven in BOTH environments (real paused
file present, and HOME redirected). Patrick's pause untouched. By
@prax; suite + lint re-verified by devpulse.

**feat(trigger)** — the escalation digest lane: repeat warnings/errors
now email the operator (DPLAN-0283 WS-A, the build the whole doctrine
train served). Signature = level|branch|module|normalized-message,
aligned with the error-registry fingerprints; rolling window per
signature; threshold crossed → ONE email to @devpulse (email, never a
wake), then per-signature cooldown. The ruling encoded structurally:
`record_error()` is the FIRST statement above every gate — a mute stops
the dispatch but cannot reach the counting; only SENDING is gated, so
every signature stays auditable in escalation_state.json. Two tiers:
warnings (which never had any escalation path) including branch-log
WARNING parsing, and errors still recurring after a medic dispatch,
under a mute, with medic off, or with no owner to dispatch to.
Suppressed fingerprints stay silent (a human already said benign) unless
`escalate_suppressed` is flipped. All knobs operator-owned in
`trigger.config.json` under custom_config, loaded by trigger's own
S193-doctrine config loader — first adopter of the standard shipped
earlier tonight. Live-proven with 4 real digests through ai_mail
end-to-end, including the muted-branch case: dispatch suppressed,
counting continued, digest sent. State file deliberately off the trio
naming path; audit trail in .jsonl so the lane cannot feed itself.
+167 tests (890), seedgo 99%, README truth-up. By @trigger; suite +
lint + live CLI + audit re-verified by devpulse.

**fix(memory)** — unreadable config can no longer crash past the
fail-loud path (config_loader 1.3.0). Seedgo's WS-B rider find, fixed at
both occurrences: `load()` had `read_text()` outside the try, so bad
bytes (UnicodeDecodeError) or bad permissions (OSError) escaped raw
instead of serving defaults — and `push_defaults_to_per_branch` had the
identical hole, its try catching only JSONDecodeError. Now: read guarded
with its own except → ERROR naming the exception type + distinct
`config_load_unreadable` operation + defaults in memory, file never
touched; push refuses on all three conditions. Corrupt handling NOT
flipped — still fail-loud-never-clobber per the June ruling; the
quarantine upgrade stays queued behind the escalation digest. +5 tests
(1041), canary-verified red on both reverted halves, live-proven on a
bad-bytes file (defaults served, push refused, bytes byte-identical).
Operator's live config untouched throughout. By @memory; suite + lint +
code read re-verified by devpulse.

**fix(devpulse)** — watchdog stall detector no longer blind to sub-agent
work (agent.py 1.2.0). Two compounding causes, both caught live when the
watchdog cried STALLED on @trigger's healthy digest build: (1) JSONL
scanning was top-level only, but sub-agent transcripts live under
`<session>/subagents/` — a parent waiting on a synchronous sub-agent
writes nothing itself while the nested file grows, so real work read as
idle; now recursive, keyed by relative path so equal basenames across
sessions can't collide. (2) The in-flight-tool check read the literal
last JSONL line, which can be a bookkeeping entry (`last-prompt`)
written after the assistant's `tool_use` — now walks backwards past
roleless lines to the last real message entry. +4 tests (21),
canary-verified red on the reverted glob, then live-proven against the
very trigger session that false-fired: 11 nested files tracked,
in-flight True, activity caught in 10s. By devpulse.

**docs(seedgo)** — json_structure standard rewritten to the S193
self-heal doctrine (v3.0.0, DPLAN-0283 WS-B). The house-pattern block is
now 6 rules written from the verbatim ruling + memory's config_loader
1.2.0 as reference implementation: configs live in the JSON; the file on
disk is the runtime authority; DEFAULT_CONFIG is the regeneration seed
kept at operating values; missing → full atomic regen; malformed or
unreadable → fail loud, never clobber, defaults in memory only;
deep-merge file-over-seed. Retired: never-snapshot, "config holds only
overrides", "missing = defaults". The 6-key drift case reframed — a
stale seed regenerates stale truth, not "files can't hold full configs".
"Never create JSON files manually" warning scoped to the auto-generated
trio (custom_config is the operator's to hand-edit). +8 tests (1347):
six pin the doctrine, two pin what must never return — canary-verified
red three ways, which itself caught a vacuous-pass defect in the test
helper. Rider finding for @memory: config_loader read_text() outside
the try — UnicodeDecodeError/PermissionError escape raw (queued). By
@seedgo; suite + lint + live render re-verified by devpulse.

**docs(spawn)** — custom_config README template rewritten to the S193
self-heal doctrine + fleet re-render 17/17 (DPLAN-0283 WS-C). The guide
now teaches: the file is the runtime authority (configs live in JSONs,
not code); code holds `DEFAULT_CONFIG` only as the regeneration seed,
kept aligned with operating values; missing file → regenerated in full;
malformed file → fail loud, never clobbered; code writes to
custom_config only on that self-heal path, partial files deep-merge from
the seed. Thursday's never-snapshot wording retired everywhere —
verified by grep across all 17 rendered READMEs. Tests were part of the
defect (they asserted the reversed doctrine): rewritten + a new
absence-canary test that goes red if the retired rule ever reappears,
all three canary-verified red/green. Reference-loader pointer added
(memory's config_loader 1.2.0). Registry hash updated; only README.md
written per branch — operator files untouched. 381 tests, seedgo 100%.
By @spawn; suite + lint + rendered README + fleet grep re-verified by
devpulse.

**fix(memory)** — the config file is the authority again: self-heal
restored (config_loader 1.2.0, Patrick ruling S193 reversing the
doctrine half of Thursday's ws4). The never-snapshot change had archived
the operator's `memory.config.json` and made the loader write nothing on
a missing file — inverting the June-shipped design (DPLAN-0206 /
FPLAN-0271): configs live in JSONs; code's `DEFAULT_CONFIG` exists only
as the regeneration seed. Restored to that spec: genuinely-missing file
→ full config written to disk (atomic write); malformed or wrong-shape
JSON → ERROR + defaults served in memory, the operator's file never
touched; `push_defaults_to_per_branch` now refuses over an unreadable
file instead of silently rebuilding it. `enforce: true` in the seed per
ruling — regenerate what we operate. Kept from ws4 because correct
regardless: the extractor defaults-fallback (the regen path is only safe
because it stayed) and the aligned seed values. Live-proven twice:
delete the file, run any memory command, watch the full config reborn —
second run carries `enforce: true`. 1036 tests, seedgo 100%. Queued: the
never-snapshot text in the seedgo standard + spawn README guide now
contradicts the ruling; correction pass to follow. By @memory;
suite + lint + live regen ×2 re-verified by devpulse.

## [2026-08-07] — post-v2.7.14 train (in progress)

**feat(seedgo)** — the audit can now SAY things without scoring them, and
the trio standard closed its blind spot (FPLAN-0380 workstream 1 of 4,
Patrick-ruled: seedgo never audits custom_config content — signpost only).
A new non-scored info channel: checkers may expose `check_branch_info()`,
collected into `info_lines` (structurally impossible to affect a score)
and rendered dim ALWAYS — including at 100%, where the old
violations-only display would have hidden an info line on exactly the
healthy branches it describes. First consumer lists custom_config
operator files + a guide pointer; audit cache now fingerprints
custom_config names/mtimes so the line can't go stale on a cache hit.
Standard text gains the house-pattern section (5 rules + the
never-snapshot rule with memory's 6-key drift named). Trio completeness
is now bidirectional — any `{stem}_{config|data|log}.json` implies the
other two; live-proved both directions on @trigger in real time (19:45
red 66% on the genuine gap, 19:50 green 100% after their parallel fix —
neither branch touching the other). Plus, born from devpulse's typo'd
pointer in the brief: `drone @seedgo standard <name>` now exists as a
pack-resolving alias (refuses to guess on ambiguity), and a canary test
parses the embedded pointer constant and resolves it for real — an
embedded command string is untested code, which is how the typo could
exist at all. Their attempt-1 process died after replying (exit 1);
attempt 2 honestly flagged the tree-state mismatch before commit. 1339
tests (+36 across both passes), fleet 16/17 at 100%. Found-not-fixed,
queued: log_structure's branch post-check has been dead fleet-wide
(bypass_rules TypeError swallowed by a bare except) — reviving it can
move scores, held for a ruling. By @seedgo; suite + alias + live @hooks
info line re-verified by devpulse.

**fix(memory)** — archived entries recover by identity, not by guesswork
(extractor 0.6.0, search display; @commons' finding fixed at the source).
Archived vectors carried branch/type/source but never the entry's own
number or date — a recovered entry matched on text alone, ambiguous the
moment two entries share wording. extract_with_metadata now lifts
entry_number + entry_date into vector metadata (scalars only; missing or
mistyped values skipped, never written as None — a None fails the whole
Chroma store). Chased to the surface: search had been printing a bare
"Time:" for every archived .trinity entry since forever (rollover writes
empty timestamp; entries carry `date`) — now renders "Entry: #14 | Dated:
…". Canary-verified both ways; live unmocked run archived 3 entries
printing numbered+dated. Honest caveats kept: ~8437 existing vectors have
no backfill (only possible from versioned backups — on @memory's board),
and their earlier "restore on request" offer is withdrawn as unactionable
(the index-0-only write hook would misorder restored entries — correct
guardrail, wrong offer). 1029 tests (+5). By @memory; suite + lint
re-verified by devpulse.

**fix(memory)** — the stale-snapshot trap closed at its source, and the
reframe that came with it (FPLAN-0380 workstream 4 of 4). config_loader
1.1.0 no longer writes anything on a missing file (the self_heal parameter
removed entirely — a flag that never heals is a lie in the signature);
code DEFAULT_CONFIG aligned to the operating values (enforce=True, todos
150, observations 300, rollover keep 15/15/15). The reframe: that config
file was NEVER in git — `**/*_json/` ignored — so the divergence was
never disk-vs-code, it was THIS MACHINE vs EVERY FRESH INSTALL, which had
been running the old lax defaults all along. The alignment is the entire
shipped fix. And archiving the local file exposed a masked fleet bug:
extractor _extract_items_v2 had no defaults fallback, so without
per_branch entries (i.e., on every clone that ever ran rollover) it
archived nothing while returning success — a silent no-op wearing a green
badge. Fixed (extractor 0.5.0, canary-verified: revert reproduces the
exact skipped:True dict). Live proof fileless: *_meta cap lines
byte-identical across 21 branches before/after, end-to-end archive run
kept 15 newest/archived 6 oldest (first attempt correctly refused —
same-day entries hit the DPLAN-0278 safety valve, working as designed).
1024 tests, seedgo 100%. By @memory; suite + fileless live rollover +
rendered caps re-verified by devpulse.

**fix(trigger)** — latent data-loss defused, and the defect had a twin
(FPLAN-0380 workstream 3 of 4). Two hand-written live-state files squatted
on json_handler's trio paths for module `trigger`: `trigger_config.json`
(12 branch mutes + circuit breaker) and — found by @trigger, not in the
brief — `trigger_data.json` (the error catch-up hash set, whose loss would
re-dispatch every already-handled error). Neither carried the trio's
required keys, so any `ensure_json_exists('trigger', ...)` call judged
them corrupt and template-blanked them. Moved to `medic_state.json` /
`error_catchup.json` (config.py 1.1.0, medic_state.py 1.2.0,
error_detected.py 2.4.0, startup.py/runaway_handler.py 1.1.0/1.2.0);
one-shot migration, legacy archived never deleted, unreadable legacy left
in place with a warning. Proof by attempted destruction: fired
`ensure_module_jsons('trigger')` live — it recreated blank templates while
all 12 mutes, TTLs, breaker state, and 32/32 catch-up hashes survived
(pre-fix, that single call destroys everything). Two self-caught traps:
a nested-flock deadlock the mocked test lock could never expose (lock made
real in the fixture), and the first-cut migration fighting @seedgo's new
bidirectional trio check in an infinite create/archive loop (now one-shot,
placeholders left to their owner — trigger audit 100%). A dead
TRIGGER_CONFIG_FILE constant removed rather than repointed; one test that
passed for the wrong reason fixed. 723 tests (+13). By @trigger; suite +
live medic read-back re-verified by devpulse.

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
