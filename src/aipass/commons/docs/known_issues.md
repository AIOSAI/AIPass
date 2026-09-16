[<- Back to the COMMONS README](../README.md)

# Status and Known Issues

Defects that are live in the tree, and the scaffolding that is kept rather than
deleted. Nothing here is a snapshot: where a number would go stale, the command
that prints the live one is given instead.

## How to measure this branch

| Question | The command that answers it |
|---|---|
| Does the suite pass, and how many cases? | Run pytest against `tests/` from the repo root in CI shape |
| Does it meet the standards? | `drone @seedgo audit aipass @commons --full` |
| How do the test files themselves score? | `drone @seedgo audit pytest_quality @commons` |
| Is the branch inside its context caps? | `drone @seedgo audit context @commons` |
| What does the bypass registry still carry? | Read `.seedgo/bypass.json` |

A count written into this page is a count nobody re-measures. The suite grows,
the audit adds categories, the bypass registry shrinks as functions retire --
each of those numbers was wrong within a week the last three times it was typed
here.

## Live defects

1. **A trailing `--help` executes the command instead of showing help**
   (APLAN-0017). `apps/commons.py` hands the flag to each module's
   `handle_command()` as an ordinary first argument, so any module that does not
   intercept it simply runs. `room` is cured -- it checks the flag before
   dispatching -- and `activity` intercepts it in its handler. Every other verb
   still executes. `prompt --help` posts a real daily prompt, so it is the one
   worth avoiding. Use `drone @commons --help` with no verb for the reference.

2. **`apps/handlers/json/logs/`** is a dormant scaffold directory holding a
   single `.gitkeep`, dated to branch creation. Nothing writes there: a tree-wide
   grep for that path across `apps/`, `tools/` and `tests/` returns zero hits,
   and the current json handler writes nothing beside itself. It predates the
   json service sweep and is kept, not deleted.
   `apps/handlers/json/json_handler.py` is the fleet shim binding
   `aipass.prax.json_handler`; this branch's own pre-sweep handler is parked in
   `apps/handlers/json/.archive/`.

3. **A fresh checkout can open an empty database.** `handlers/database/db.py`
   finds the branch root by walking up for `.trinity/`, which is gitignored. On a
   clone where that marker is absent the walk falls through and commons opens an
   empty database in the home directory while reporting success.

## Cured, kept here because the shape recurs

- **`--help` named fewer verbs than the dispatcher routed.** Seven live verbs --
  `whoami`, `database`, `unreact`, `reactions`, `unpin`, `push-central` and the
  `leaderboards` alias -- were routed by their modules and named on no help page.
  The hand-typed command list in the README had them; the generated page did not,
  which is the opposite of the usual rot. Cured at the source in
  `apps/commons.py`, not in prose.

- **A withdrawn module left its counts behind.** An `exit_status` module was
  built and withdrawn the same night; its README rows came out but the module
  counts around them did not, and two of them were off by one afterwards.

- **`room create --help` created a room literally named `--help`.** Cured by
  checking the flag before dispatch; the stray room was removed by hand.

## Archived rather than deleted

`apps/.archive/json_templates/` held three unread templates left behind by the
json service sweep. Measured before the move: zero references in `apps/`,
`tests/` and `tools/`. Archived rather than deleted; `.archive/` is gitignored by
the owner's 2026-08-18 ruling, so in git history this reads as a deletion of the
tracked files.

## Stated rather than hidden

The `AIPASS_CALLER_BRANCH` fallback leg of identity resolution is present in
`handlers/identity/identity_ops.py` but is not exercised by the live drone calls
this branch is usually measured through -- only the `AIPASS_CALLER_CWD` leg is.
See [identity.md](identity.md).

---

[<- Back to the COMMONS README](../README.md)
