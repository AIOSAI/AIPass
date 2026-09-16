# Known issues

**Branch** drone
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

Each entry carries the measurement behind it. Where a number would rot, the command that produces
it is given instead.

---

## Open

- **`pr_handler.py` is orphaned.** `create_pr()` has no production caller — `dev_pr_handler.create_branch_pr()`
  superseded it — and every caller is in `tests/test_git_module.py`. It is still maintained (the
  commit subject cap landed in it), because the workflow it implements is the one a future
  `pr` rebuild would start from.
- **`update_command()` and `command_exists()` in `apps/handlers/command_registry/ops.py`** are
  tested CRUD API with no production caller.
- **Piping drone output into a truncating reader** (`| head`) yields inconsistent exit codes — no
  BrokenPipe handling anywhere in the tree. Cosmetic, but it blocks that shape inside a `set -e`
  script.
- **Line-scoped bypass rules drift.** Several rules in `.seedgo/bypass.json` name line numbers and
  go stale whenever code above them moves: adding a function to `apps/drone.py` once pushed four
  write sites down and dropped the audit below the CI gate until the rule was refreshed. The drift
  is a feature in one respect — it proves the rule is still load-bearing.
- **`apps/drone.py`'s file header disagrees with its own runtime constant.** The header's version
  is ahead of `VERSION`, and the constant is the one every other source of truth agrees with
  (`__init__.py`, `drone --version`). The header has moved twice while the constant stood still.
  Cosmetic, and a code fix rather than a documentation one: changing `VERSION` changes what
  `drone --version` prints, which is behaviour.
- **Pyright's `json` package-shadowing warning could not be reproduced**, twice, on dates months
  apart — and the subject has changed underneath it since: that file is now the fleet json shim,
  not drone's own handler. It may still surface from an editor opening this directory standalone,
  without the root config. Left listed rather than deleted, marked unreproduced twice — there is no
  evidence it was never real.
- **The live deletion store holds records forged by another branch's sandbox suite.** The *writer*
  was fixed on 2026-09-06; the *records* stand by the owner's ruling of 2026-09-07: annotate, do not
  delete. They are all `broker` lane, caller `testbranch`, with paths under a pytest temp root. The
  source was never drone's own suite (the autouse isolation fixture has always held): it was a real
  `BrokerDaemon` started by @ai_mail's dispatch-monitor test against a synthetic repo, where
  `deletion_log_path()` resolved the *store* by walking up from the cwd and filed the record
  against whichever project the process stood in. Both lanes now name their project. One
  record-shaped annotation row was appended after them — same keys, `lane` and `outcome` both
  `annotation` — so a reader who reaches the store finds the correction in the store's own
  language. That row has no writer and no test pinning it: it was appended by hand, once, with
  @devpulse's sanction, and nothing in the code path can produce another. A ledger someone edits to
  look right is worth less than one with a documented wrong patch in it.
- **Recurring sync errors when the working tree is dirty** — operational, not a code bug.

---

## Closed, kept for the lesson

- **2026-09-11 — the plain verb now fences above the branches.** `drone rm ..` and `drone rm ../..`
  from a branch passed containment and the sibling fence (which walks UP and finds no `.trinity/`
  above `src/aipass/`), and rmtree would have taken every branch. Found by calling the guards
  directly; no delete was run. Cured in its follow-up: a project folder that contains another
  citizen is refused, naming the first one. See
  [rm_and_the_record.md](rm_and_the_record.md).
- **2026-09-15 — `repo_door` is back in the import block.** It sat on its own line in
  `apps/modules/git_module.py` because seedgo's `dead_code` rule matched imports with a single-line
  pattern and could not see a name inside a parenthesised multi-line import, so `repo_door.py`
  scored unreferenced and dropped the audit below the CI gate. Reported to @seedgo on 2026-09-13;
  their checker learned to read the block, and the import rejoined it here.

---

## How to re-measure

| Question | Command |
|---|---|
| Does the branch pass its standards? | `drone @seedgo audit aipass @drone` |
| What does a greeting cost? | `drone @seedgo audit context @drone` |
| Is the suite green from both rootdirs? | see [testing.md](testing.md) |
| What is registered, and where does it resolve? | `drone systems` |
| What has this branch deleted? | `.ai_central/deletions.jsonl` |
| What has gone through the external-repo door? | `.ai_central/git_repo_door.jsonl` |
