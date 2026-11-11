[<- Back to the README](../README.md)

# Moving a citizen into another project — adopt-citizen

`drone @spawn adopt-citizen @name <target_root>` moves an existing citizen whole, with its identity, `.trinity/` memory, mailbox, plans and registry row (ids kept), into another project root. The preview is the default and writes nothing; `--apply` executes. The code is `apps/handlers/adopt_citizen_ops.py` (`plan_adoption`, `apply_adoption`) and `apps/modules/adopt_citizen.py` (parsing and printing). Flags are in `drone @spawn adopt-citizen --help`.

## The plan

The plan is a pure read. It finds the citizen among those @memory's door answers (core, resident, and external at a declared root), reads its row from the registry that lists it, and refuses a core citizen: a row in `AIPASS_REGISTRY.json` never leaves AIPass. The passport's `citizen_id` must equal the row's `registry_id`, and an open dispatch in the citizen's inbox (`auto_execute` true, status not `closed`) refuses by message id.

The target root must exist, and must neither sit inside the source project nor contain it. The destination is `<target_root>/<name>`; an existing destination is a clash. The target registry is the one `*_REGISTRY.json` at the root, or a new `<DIRNAME>_REGISTRY.json` with a freshly minted `metadata.id` when there is none; two or more refuse. When the target registry has no `owner: true` row, the moved row takes the seat and the passport's class becomes `manager`.

When the target is a git work tree, its tracked files are read with `git ls-files`. A tracked registry, lock or destination path is a clash. Tracked `.aipass/` entries are one clash row, the AIPass leftover a client repo must untrack first. A tracked `AGENTS.md` is a skip row: the client's file, never touched.

### The preview

Every write is a row: `create`, `move`, `append`, `edit`, `skip` or `clash`, with its path relative to the target root (the source registry, outside it, is printed absolute) and a reason. Any clash or refusal goes into `blocked`, and the result reads `ready` only when that list is empty. The text shape is stable, so @aipass embeds it verbatim; `--json` carries the same fields.

### Follow-ups

Records spawn does not write are listed by owner: @flow re-points each plan row whose `file_path` sits under the old directory, @memory declares the target root when it is outside the AIPass home and not among the roots @memory's `declared_roots()` answers (an inactive row is not declared), @hooks enrols an untrusted target and revokes the old root once it holds no citizens, and @devpulse archives that emptied root.

## Apply

The order is: create the target registry if new, `os.rename` the directory (a cross-filesystem move refuses, with no copy fallback), edit the passport (`branch_info.path`, `citizenship.registry_path`, `registry_id`, `residency`, the class), append the row to the target registry under its lock, remove it from the source registry under its lock, and append the exclude lines (`/<REG>.json`, `/.<REG>.lock`, `/<name>/`, only those not already present). A failure after the move puts the directory back and restores the passport, both registries and the exclude file.

The proof re-reads what was written: the passport's `citizen_id` equals the new row's `registry_id`, and the target registry resolves the name to the destination. Drone resolves the name only once @memory declares the root, so the output says so rather than claiming it.

## Exit codes

0 is a ready preview or a finished apply; 1 is a refusal or a block, with nothing written; 2 is a usage error. The command passes through the exit seam in `apps/spawn.py`.

## What is not verified

The restore after a failed apply has no test of its own, and neither does a target that is a subdirectory of a larger git work tree (the exclude lines take git's `--show-prefix`).

## Related

[registry_and_repair.md](registry_and_repair.md) covers relocation inside one project; [cli_contract.md](cli_contract.md) the exit seam.
