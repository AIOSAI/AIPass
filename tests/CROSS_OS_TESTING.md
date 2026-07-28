# AIPass Cross-OS Acceptance Checklist

**Purpose:** the definition of *"AIPass works on this OS."* Follow this top-to-bottom on any
fresh machine or VM (Windows / macOS / Linux) to verify a real end-to-end install — the things
automated CI structurally cannot reach (full install, interactive flows, background daemons,
audible hooks). Copy a **Run Record** (bottom of this file) per machine and fill it in.

> Code is truth. A green checkbox here means *you watched it work on that OS*, not that it should.

---

## The 3 layers of cross-OS confidence

| Layer | What | Where it runs | Catches |
|-------|------|---------------|---------|
| 1 — **Static** | `drone @seedgo` Windows-compat scan | any OS, no execution | POSIX-only patterns (`os.kill`, `start_new_session`, `/tmp`, `fcntl`…) before you run |
| 2 — **Automated** | `pytest tests/e2e` (the `e2e-wheel.yml` 4-tier gate) | CI on ubuntu+windows+macos, and locally | the wiring contract: clean-wheel install → `aipass init` scaffold → hook fires → `drone` routes |
| 3 — **Manual** | **this checklist** | a real box / VM, by hand | full install, interactive `init run`, daemons, sound, per-branch smoke |

Layers 1–2 are free and run on every push. **This file is layer 3** — the human acceptance pass
you do when you get hardware (a VM, a borrowed Mac, a new laptop).

> **Machine pre-flight (augments, never replaces layer 3).** `aipass init` now runs a layer-3-lite
> pre-flight: stage 2 prints OS-relevant heads-ups for tracked gaps before scaffolding. For a fuller
> machine sweep, `aipass doctor --cross-os` reports the known-gap surface, `--e2e` runs the real
> layer-2 suite, and `--record [PATH]` emits a machine-filled Run Record. These front-run the obvious
> breakage — but the human acceptance pass below is still the real layer 3.

---

## How to use

1. **Capture output.** Run your shell session into a log so any crash traceback is saved:
   - Linux/macOS: `script -q aipass-crossos-$(uname -s).log` (then run the checks, `exit` when done)
   - Windows PowerShell: `Start-Transcript -Path aipass-crossos-win.log` … `Stop-Transcript`
2. Work through **Phase 0 → 7**, then the **Per-branch matrix**.
3. For every check: run the command, compare to **Expected**, tick ⬜ → ✅ / ❌.
4. On ❌: note the exact error in the Run Record, check the **Known gap registry** (it may be a
   tracked one), and if new, file it / email the owning branch.
5. Paste the completed Run Record into the PR / DPLAN-0194 thread.

**Legend:** ✅ pass · ❌ fail · ⏭️ skipped (state why) · ⚠️ known-gap watch item

---

## Phase 0 — Environment capture (record before anything)

| # | Capture | Command |
|---|---------|---------|
| 0.1 | OS + version | `uname -a` / Win: `cmd /c ver` + `systeminfo \| findstr /B /C:"OS"` |
| 0.2 | Arch | `uname -m` / Win: `echo %PROCESSOR_ARCHITECTURE%` |
| 0.3 | Python | `python3 --version` (Win: `python --version`) — **must be 3.10+** |
| 0.4 | Shell + terminal | which shell; is it Windows Terminal / cmd / PowerShell / iTerm? |
| 0.5 | `AIPASS_HOME` | `echo $AIPASS_HOME` (Win: `echo %AIPASS_HOME%`) — note set/unset |
| 0.6 | Git | `git --version` |

> **Why terminal matters:** the cp1252 stdout class of bug (fixed S190) only bites when stdout is
> a *legacy/captured* stream. Record whether you're on UTF-8-capable Windows Terminal vs legacy
> conhost — reds can differ.

---

## Phase 1 — Clean install ⬜

| # | Step | Expected | Watch |
|---|------|----------|-------|
| 1.1 | Fresh clone or wheel copy onto the box | files present | — |
| 1.2 | Run `setup.sh` (or `pip install -e ".[dev]"`) | exits 0; `.venv` created with pip | ⚠️ **Windows `.venv` symlink WinError 1314** — needs `os.symlink` guarded w/ copy/junction fallback (DPLAN-0194 gap) |
| 1.3 | `drone --version` and `aipass --version` | both print a version, exit 0 | ⚠️ `.venv/bin` vs `Scripts` path resolution |

---

## Phase 2 — Automated wiring (run the e2e suite on the real box) ⬜

| # | Step | Expected |
|---|------|----------|
| 2.1 | `pip install build pytest` | installed |
| 2.2 | `python -m pytest tests/e2e -v` | **14 passed** (T0 install / T1 init scaffold / T2a hook fire / T3 drone routing) |

> This re-runs the CI gate on *real* hardware. If CI is green but this is red, the difference is
> the machine (real console, real paths) — exactly what we're hunting.

---

## Phase 3 — `aipass init` (real scaffold + interactive) ⬜

| # | Command | Expected | Watch |
|---|---------|----------|-------|
| 3.1 | `aipass init /tmp/demo demo` (Win: a temp path) | creates `DEMO_REGISTRY.json`, `.aipass/`, `.claude/settings.json`, `src/demo/` + prints `✓ Project initialized` | ⚠️ cp1252 banner crash (fixed S190 — verify it stays fixed) |
| 3.2 | `aipass init run --dry-run` | shows the 10-stage plan (`init_flow.TOTAL_STAGES`), no writes | — |
| 3.3 | `aipass init run --non-interactive` (in a throwaway dir) | completes all stages headless | ⚠️ symlink/daemon steps |
| 3.4 | `aipass init run` (interactive, manual) | prompts render + accept input; completes | ⚠️ **interactive PTY** — never machine-tested; pexpect territory |
| 3.5 | `aipass doctor` | health report renders, exit 0 | — |

> **@aipass is its own process — the user-facing concierge / onboarding CLI** (`init`, `doctor`,
> scanner). It's the front door you run to *bootstrap* a project, so it's invoked directly as
> `aipass …` and is **by design not routed through `drone @aipass`** (unlike the other 12 branches).

---

## Phase 4 — `drone` routing ⬜

| # | Command | Expected |
|---|---------|----------|
| 4.1 | `drone systems` | lists all registered branches + modules |
| 4.2 | `drone @ai_mail --help` | help text, **exit 0** (real registry-branch subprocess — the T3 path) |
| 4.3 | `drone @seedgo --help` | help text, exit 0 (in-process module path) |
| 4.4 | `drone @ai_mail inbox` | inbox renders (empty is fine) |

---

## Phase 5 — Daemons / background processes ⬜

| # | Command | Expected | Watch |
|---|---------|----------|-------|
| 5.1 | `drone @ai_mail dispatch @devpulse "x-os test" "ping"` then `drone @ai_mail inbox` | mail sent; target woken | ⚠️ **`start_new_session=` POSIX kwarg** in ai_mail/flow daemon spawn |
| 5.2 | `drone @devpulse watchdog --help` then arm a watchdog | polls lock, exits clean | ⚠️ **`os.kill` POSIX-only**; inotify vs Win file-watch |
| 5.3 | `drone @prax monitor` (then quit) | live dashboard renders | ⚠️ interactive / curses-style on Win |

---

## Phase 6 — Hooks + sound ⬜

| # | Step | Expected | Watch |
|---|------|----------|-------|
| 6.1 | Trigger `rm_gate` (attempt a raw `rm -rf` via the agent / fire the bridge) | blocked; `src/aipass/hooks/logs/engine.jsonl` gains a record | — |
| 6.2 | A hook with sound fires | audible cue plays | ⚠️ **`aplay` is Linux-only** — needs `afplay` (macOS) / `winsound` (Windows) |
| 6.3 | `drone @hooks status` | per-project hook config renders | ⚠️ hardcoded `/tmp` paths |
| 6.4 | `drone @hooks hooksound` (mute/unmute) | toggles without error | — |

---

## Phase 7 — Interactive layer (manual, hardest to automate) ⬜

| # | Step | Expected | Watch |
|---|------|----------|-------|
| 7.1 | Launch an agent session in a terminal | starts, prompt usable | ⚠️ tmux (Linux/mac) vs Windows terminal multiplexer |
| 7.2 | `aipass init run` full interactive (if not done in 3.4) | all 10 stages accept input | ⚠️ PTY/pexpect |
| 7.3 | Any prompt-driven flow (`--bypass`/flags where available) | bypassable for headless | — |

---

## Per-branch smoke matrix (all 13 branches)

Run each branch's `drone @<branch> --help` first (the universal *resolve → subprocess → execute →
print* proof), then the listed **read-only** commands. ⚠️ = mutates state / side-effect — run only
deliberately. Every command should **exit 0** and render readable (non-mojibake) output on the OS
under test.

> **† aipass is the exception** — it's the standalone user-facing concierge CLI, invoked directly
> (`aipass …`), **not** routed through `drone`. So it has no `drone @aipass --help` row; smoke it
> with the `aipass` command itself. The other 12 branches all route through `drone`.

| Branch | `--help` ⬜ | Read-only smoke | Side-effect (run deliberately) |
|--------|:---------:|-----------------|--------------------------------|
| **drone** | ⬜ | `drone systems` · `drone list` · `drone --version` | `drone scan @<b>` · `drone activate @<b>` |
| **seedgo** | ⬜ | `drone @seedgo audit` · `drone @seedgo standards_query` · `drone @seedgo diagnostics` | `drone @seedgo audit aipass` (full scan) |
| **prax** | ⬜ | `drone @prax status` · `drone @prax dashboard` · `drone @prax log-audit` | `drone @prax monitor` (interactive) |
| **cli** | ⬜ | `drone @cli` · `drone @cli display` · `drone @cli templates` | `drone @cli display demo` |
| **ai_mail** | ⬜ | `drone @ai_mail inbox` · `drone @ai_mail sent` · `drone @ai_mail contacts` | ⚠️ `dispatch` / `email` / `reply` / `close` |
| **api** | ⬜ | `drone @api status` · `drone @api stats` · `drone @api models` · `drone @api list-providers` | ⚠️ `get-key` / `validate` / `call` (touch keys/network) |
| **flow** | ⬜ | `drone @flow list` · `drone @flow list open` | ⚠️ `create` / `close` / `restore` / `aggregate` |
| **spawn** | ⬜ | `drone @spawn --help` · `drone @spawn sync-registry` | ⚠️ `create` / `update` / `delete` (use `--dry-run`) |
| **trigger** | ⬜ | `drone @trigger errors` · `drone @trigger core` | ⚠️ `medic` toggle |
| **memory** | ⬜ | `drone @memory search "test"` · `drone @memory verify` | ⚠️ `rollover` · `watch` (daemon) |
| **aipass** † | (n/a) | `aipass --version` · `aipass --help` · `aipass init --help` · `aipass doctor` | ⚠️ `aipass init …` (scaffolds) |
| **hooks** | ⬜ | `drone @hooks status` · `drone @hooks engine` | ⚠️ `hooksound` (mute) · `claude` (bridge) |
| **devpulse** | ⬜ | `drone @devpulse feedback` · `drone @devpulse watchdog --help` | ⚠️ `watchdog agent @<b>` (arms wake) |

---

## Known cross-OS gap registry (living — update as fixed)

Tracks every confirmed/suspected portability gap so a red here is "expected, tracked" not a mystery.
Source of truth: **DPLAN-0194**. Status: ✅ fixed · 🔧 owner assigned · ❓ suspected/untested.

| # | Gap | OS | Symptom | Owner | Status |
|---|-----|----|---------| ------|--------|
| 1 | cp1252 stdout + Rich in CLI entry points | Win | `UnicodeEncodeError('charmap')` on `aipass init` banner & `drone @branch` print | aipass/drone | ✅ S190 (`reconfigure(utf-8)` at entry) |
| 2 | `.venv` symlink | Win | `setup.sh`/`init` → WinError 1314 (no symlink priv) | aipass | ❓ untested (CI left `AIPASS_HOME` unset) |
| 3 | `start_new_session=` kwarg | Win | daemon spawn throws (POSIX-only) | ai_mail / flow | ❓ |
| 4 | `os.kill` | Win | watchdog / daemon stop throws | flow + others | ❓ |
| 5 | `.venv/bin` vs `Scripts` | Win | path resolution misses console scripts | memory / drone / ai_mail | ❓ |
| 6 | hardcoded `/tmp` | Win | scratch-dir writes fail | hooks / seedgo | ❓ |
| 7 | `aplay`-only audio | Win/mac | hook sound silent / errors | hooks (+ template hooks) | ❓ (mac needs `afplay`, Win `winsound`) |
| 8 | `shell=True` usage | Win | quoting/semantics differ | hooks | ❓ |
| 9 | `route_command` masks errors | all | real exceptions printed as "Unknown command" | aipass | 🔧 recommended (not fixed — hid gap #1 for hours) |

> @seedgo's `windows_compat_check.py` already scans for several of these statically — extending it
> to flag the cp1252/entry-point pattern (#1) and the `aplay`/`/tmp`/`os.kill` patterns is **P2**.

---

## Run Record (copy one block per machine/run)

```
─────────────────────────────────────────────
AIPass Cross-OS Run Record
Machine/VM   :
OS + version :
Arch         :
Python       :
Shell / term :
AIPASS_HOME  :
Commit (drone @git log -1) :
Tester       :            Date :
─────────────────────────────────────────────
Phase 0 env capture .......... ✅ / ❌
Phase 1 clean install ........ ✅ / ❌   notes:
Phase 2 e2e suite (14/14) .... ✅ / ❌   notes:
Phase 3 aipass init .......... ✅ / ❌   notes:
Phase 4 drone routing ........ ✅ / ❌   notes:
Phase 5 daemons .............. ✅ / ❌   notes:
Phase 6 hooks + sound ........ ✅ / ❌   notes:
Phase 7 interactive .......... ✅ / ❌   notes:
Per-branch matrix (13) ....... ✅ / ❌   reds:
─────────────────────────────────────────────
New gaps found (file + assign):

Overall verdict: PASS / PARTIAL / FAIL
─────────────────────────────────────────────
```

---

*Layer 3 of cross-OS confidence. Pairs with `tests/e2e/` (layer 2) and `drone @seedgo` Windows-compat scan (layer 1). See DPLAN-0194 for the full strategy.*
