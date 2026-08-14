# Help-Flag Safety Standard

## Purpose

**A help flag ANYWHERE in the arguments means EXPLAIN, never EXECUTE.**

On 2026-08-13 every one of eight branches probed carried the same defect: a trailing `--help` executed the verb instead of describing it. The gate read one fixed position — almost always `args[0]` — so a flag any later on the line was discarded and the subcommand ran.

```
drone @memory rollover push --help
  -> args = ["push", "--help"], args[0] == "push"
  -> the gate misses, push() runs
  -> PERFORMED the fleet-wide per_branch reset it was being asked to describe
```

Real damage in one morning: a 17-branch config reset, a real backup run, a real data cleanup, an enrollment write. Near-misses: an external dev.to publish, and an agent literally named `--help`.

## The Five Shapes

| Shape | Description | Status in this checker |
|-------|-------------|------------------------|
| (a) | Module gate reading `args[0]` only | **Detected and scored** |
| (b) | Router intercepting `remaining[0]` only | **Detected as a precondition**, not scored on its own |
| (c) | `--help` consumed as an ACTION or BRANCH value | **Reported only where it co-occurs with (a)** |
| (d) | Subcommand word occupies the gated slot, and a work call runs below it | **Detected and scored** (arm 3b) |
| (e) | `handle_command` dispatches on `command` and never reads `args` at all | **Detected and scored** (no gate exists) |

### Why (b) is a precondition, not its own violation

In AIPass a router is allowed to delegate help handling downstream. That is exactly how @memory was fixed: `memory.py` still reads `remaining_args[0]`, and the modules below it scan the whole list — and the branch is safe. A positional-only router is therefore a defect **only when the module below it is positional-only too**, and in that case the module is what gets named. Scoring the router independently would fail @memory, which is a correct reference implementation.

### Why (c) is not detected on its own

Detecting "a help flag lands in a value slot" with no gate present would mean flagging every function that reads a positional argument. "This function has no help gate" is indistinguishable from "this function is not a CLI surface" without heuristics that flood the fleet with false positives. Where shape (a) is already present, the failure message names the value slot the flag lands in — that is the honest limit of what static analysis buys here.

Shape (e) is the one exception, and it does not soften that limit. It fires only inside `handle_command`, which in AIPass is a CLI surface **by definition** — the router calls it by that name — so the surface is not being guessed at from argument shapes. Outside that one function the limit stands unchanged: a bare "no help gate" check is still not attempted, and shape (e) requires three further conditions on top of the name (below).

### Why (e) exists — a gate arm cannot fire when there is no gate

Arms (a)/(d) both require a fixed-position help gate to **exist** before anything fires. @cli reported the shape where there is none at all:

```python
def handle_command(command, args):
    if command == "demo":
        run_demo()
        return True
    return False
```

`drone @cli demo --help` arrives as `command="demo"`, `args=["--help"]`. The verb is in the **command** slot, so there is nothing left for a positional gate to read — and `args` is not read at the wrong index, it is never read at all. The router did its job here: it rewrote `remaining` to `["--help"]` and delegated. The module threw the flag away and ran the demo, and the file scored 100.

Fleet population of this exact shape, measured by @cli on 2026-08-13 across all branches: **0 of 152 modules**, because @cli fixed theirs before reporting it. Re-measured after the arm shipped: still 0 of 152. It flags nobody today and catches the shape the next time it appears — the same calibration discipline @flow, @hooks and @backup applied to arm (3b).

**The router exemption does not apply to (e).** A normalising router protects a module by *rewriting* its arguments to `["--help"]`; a module that never reads its arguments cannot benefit from a rewrite, so the flag is discarded exactly as it was before. This is the one arm a correct router cannot cover.

## What Is Checked

Scored on `apps/modules/*.py` only. A module **fails** when all four hold:

1. **Fixed-position gate** — `args[0] in ("--help", "-h", "help")` or `args[0] == "--help"`, on any sequence name (`args`, `remaining`, `sub_args`, …), found by AST `Compare` inspection.
2. **No whole-sequence scan** anywhere in the module's routing closure.
3. **The flag reaches something that runs** — either arm is enough:
   - **(3a) Argument consumption** — the function uses the sequence as data: binds `args[k]` to a name, reads index ≥ 1, slices, iterates, probes for another flag, checks `len()`, or forwards the list to a non-logging call.
   - **(3b) Positional dispatch past the gate** — the gated slot is matched against a literal subcommand word (directly, or through a name bound from it including via an `IfExp`), and a work call — any call that is not a display sink — is reachable below the gate. The flag needs no value slot to do harm here: it is simply pushed to `args[1:]`, where nothing looks, while the command runs.
4. **No router protection** — the branch's entry point does not scan the remaining arguments either, *or* the module is reachable without the router (see below).

A module **also fails**, with no gate present anywhere, when all four of these hold (shape (e)):

1. **The function is `handle_command`** — the name the router calls, and therefore a CLI surface by definition. Nothing else is examined for this arm.
2. **It dispatches on the `command` parameter** against a literal word (`command == "demo"`, `command not in ("display", "show")`), taken as the earliest such comparison.
3. **The `args` parameter is never READ** anywhere in the routing closure — no subscript, membership test, iteration, `len()`, forward to another call, or bare truthiness test. Every one of those is a `Name` load, so one predicate covers the lot. **One touch of `args` and this arm stops**: the module is then judged by the gate arms above, which is where the rest of this standard lives.
4. **A work call is reachable below the dispatch** — the same non-display-sink test arm (3b) uses.

There is no whole-sequence scan in this shape by construction (a scan that reads `args` is a read), so criterion 2 of the gate arms is satisfied automatically; a scan of some *other* sequence (`sys.argv`) still short-circuits the whole checker before any arm is consulted.

### Why arm (3b) exists — consumption-only was missing the majority

Consumption was the only trigger until 2026-08-13, and three branches measured it against a whole-branch grep the same evening: @flow's checker named 5 of 8, @hooks' named 2 of 9, @backup found a defect in a module the checker had cleared. The misses outnumbered the hits.

The reason is that a work call needs no arguments to do damage. `registry_monitor.py` (@flow) matched `args[0] == "scan"` and called `scan_plan_files()`, which writes the registry. `cc_sessions.py` (@hooks) matched `"reclaim"` and stopped live sessions. `inbox_audit.py` (seedgo's own) matched `"inbox-ids"` and ran a repo-root-wide `rglob`. In all three the help token sat unread at `args[1]` while the verb executed, and in all three the sequence was never used as data — so consumption-only scored them 100.

Both halves of (3b) are load-bearing, measured on a 142-file fleet snapshot: dispatch alone would flag modules whose only path past the gate is `console.print` and a `return False` (`diagnostics_audit.py`, `permissions.py` — correct passes); work-call alone would flag modules that dispatch on `command` rather than on `args`, where the positional gate genuinely does catch `<command> --help`.

Known limit: only *literal* subcommand words are recognised. `if args[0] in HANDLED_SUBCOMMANDS:` (module constant) or `_ROUTES[args[0]]` (dict dispatch) behind a positional gate would still be missed. No fleet file used that shape when this was written.

### The router exemption only covers modules the router is the only way into

Nearly every module also carries a standalone door:

```python
if __name__ == "__main__":
    handle_command(PRIMARY_COMMAND, sys.argv[1:])
```

That hands raw argv straight to the gate and never touches the router. @api proved it live: `python apps/modules/api_key.py get-key openrouter --help` still reached the retrieval path with their router already normalised. So when a module's `__main__` block reaches `handle_command` with `sys.argv`-derived arguments, the router exemption is withdrawn and the module is scored on its own gate.

The exemption **survives** when the standalone path cannot deliver a stray flag:

- `if __name__ == "__main__": main()` where `main()` never calls `handle_command` (it is its own program).
- A `__main__` (or `main()`) that screens **both** `--help` and `-h` across the whole command line before delegating.
- A `__main__` that only ever calls `handle_command(CMD, ["--help"])` — a normalised list, not raw argv.

Both dashed spellings are required, because a screen for `--help` alone still hands `-h` to a positional gate — the same hole one layer up. Detection follows `__main__` into module-level delegates (depth 3) and tracks argv through renames, slices, comprehensions and a bare `parse_known_args()`; `handle_command` itself is never followed, so a module cannot vouch for its own gate.

The **routing closure** is `handle_command()` plus the module-level private helpers it delegates to (depth 3). Several branches keep `handle_command` as a one-line forwarder and put the gate in `_handle_x(args)`; following delegates finds gates that hide one call deep and credits scans that hide there too.

Detection is **pure AST**. No regex, no substring scanning — this pack has repeatedly been burned by substring scanners flagging code inside docstrings, `# BAD` counter-examples and test fixture strings.

## What Passes

Any **one** of these is enough:

| Form | Example | Used by |
|------|---------|---------|
| Membership scan | `if "--help" in args:` | @skills, @spawn |
| Comprehension scan | `if any(a in ("--help", "-h") for a in args):` | @api (partly) |
| Loop scan | `for token in args: if token in ("--help", "-h"):` | — |
| Shared helper | `if wants_help(args, allow_bare_word=True):` | @memory |
| argparse | `parse_known_args()` absorbs the flag anywhere | @prax |
| Router normalisation | entry point scans `remaining`, rewrites to `["--help"]` — *and the module has no standalone `__main__` door* | @backup, @aipass, @daemon |

## What Is Deliberately Not Flagged

- **Closed-vocabulary commands.** A `handle_command` that only compares `args[0]` against literal subcommand names and takes no operands has nowhere for a stray flag to hide. A positional gate is sufficient for it.
- **Arguments that only reach a logger or an error message.** Reporting an argument is not executing it.
- **Entry points.** Read for the router check, never blamed.
- **Routing functions with no help gate at all** — *outside* `handle_command`. Not detectable without flooding; `subcommand_help` covers the entry-point half of that gap. Inside `handle_command`, shape (e) covers the one case where the missing gate is provable: the function ignores its argument list entirely and still works.
- **A `handle_command` that reads `args` but never gates on it.** One read is enough to leave shape (e), and with no help gate present the gate arms have nothing to fire on either. This is the remaining hole in the standard, and it is deliberate — closing it means guessing which reads were meant to be a gate.

## Scope

- `AUDIT_SCOPE = "all_files"` — every `.py` under `apps/` is offered; only `apps/modules/*.py` is scored, everything else returns 100 as not applicable.
- `APPLIES_TO = "production"` — CLI routing conventions are a production concern; test files build argument lists as fixtures, not as a surface a user types into.

## Scoring

| Score | Meaning |
|-------|---------|
| 100 | Passes, bypassed, or not applicable |
| 0 | Unprotected fixed-position gate on argument-consuming or executing code, **or** a `handle_command` that dispatches on `command`, never reads `args`, and works anyway |

Branch score is the mean across all scanned files (`all_files` scope).

## Fix

**Option 1 — fix the module** (protects it however it is reached):

```python
def handle_command(command: str, args: list) -> bool:
    # A help flag ANYWHERE wins — asking about `push` must never push.
    if any(arg in ("--help", "-h") for arg in args):
        print_help()
        return True
    ...
```

**Option 2 — fix the router** (protects every module behind it in one edit, *except* against shape (e): a module that never reads `args` discards the rewritten list too):

```python
command = args[0]
remaining = args[1:]

# Checking only remaining[0] let '<cmd> <operand> --help' fall through and execute.
if any(arg in ("--help", "-h") for arg in remaining):
    for module in modules:
        if module.handle_command(command, ["--help"]):
            return 0
    print_help()
    return 0
```

**Option 3 — a shared helper**, when a branch has many modules. See `src/aipass/memory/apps/handlers/cli/help_flags.py`: `wants_help(args, allow_bare_word=False)`. The bare word `help` counts only in the first slot unless the caller opts in, because modules that take free text (search queries, transcripts) legitimately receive it as content.

## Bypass

```json
{
  "file": "apps/modules/example.py",
  "standard": "help_flag_safety",
  "reason": "why this module genuinely cannot be reached with a stray flag"
}
```

A bypass here suppresses a command that runs when it was asked to explain itself. Prefer the three-line fix.

## Related Standards

- **`subcommand_help`** — does the entry point intercept `<cmd> --help` *at all*? This standard asks the next question: does it intercept it *everywhere*.
- **`introspection`** — no-args means describe structure; `--help` means describe usage. Different functions, different purposes.
- **`cli_flags`** — which flags an entry point must support.
