# Retiring a citizen — delete, archive, deregister

**Branch** spawn · **Code** `apps/handlers/delete_ops.py`, `apps/handlers/repair_ops.py`
(`ARCHIVE_EXCLUDE`), `apps/modules/delete.py`
**Moved out of README.md** (DPLAN-0347, the layer contract).

Usage is in `drone @spawn delete --help`; preview is the default and confirmation is
explicit. Everything below is what retirement means once it runs.

---

## The lane

Resolve the branch from the registry, archive the whole tree into `.archive/`, remove the
live directory, then deregister the entry. The order matters: the archive is the only copy
once the tree is gone, so anything left behind at archive time is lost. The whole
`.trinity/` travels with it — passport, memories and the birth receipt — because a retired
citizen's identity is the part worth keeping, and `tests/test_birth_receipt.py` pins that it
arrives.

The archive copy skips build and VCS noise — `ARCHIVE_EXCLUDE` is `.venv`, `.git`,
`__pycache__`, `.chroma`, `node_modules`, `.pytest_cache`. The same set guards the
relocation lane in [registry_and_repair.md](registry_and_repair.md), so neither carries a
virtualenv into an archive.

---

## Delete refuses protected branches, and every live citizen is protected

`is_protected()` guards three layers, any one sufficient:

1. The hardcoded floor — the branch factory, the orchestration branch and the router.
2. A registry entry carrying `owner: true`.
3. A passport with `citizenship.registered: true`.

Since `create` writes `registered: true`, a branch is protected from the moment it exists.
There is no force flag: retiring a citizen means clearing that passport flag first, which
is a deliberate, visible act rather than an argument on a command line.

Verified live (APLAN-0007): the infrastructure and active-citizen refusals both fire and
exit non-zero. The registry-owner layer is **unreachable in the live fleet** — the only
entry carrying `owner: true` short-circuits at layer 1, so no branch reaches layer 2. It is
covered by unit tests against a synthetic registry, not by live behaviour, and that is
stated rather than papered over.

---

## What retirement does not do

It does not touch another project's registry, it does not delete an archive, and it does not
clean up mail or plans that named the branch. Those live with the branches that own them.

---

**Last Updated:** 2026-09-15
