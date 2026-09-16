# The handlers fence

[<- Back to BACKUP](../README.md)

The access guard on `apps/handlers/__init__.py`: how kinship is decided, and the rules its own tests must obey.

### Fabricated filenames never name the real tree (round 12)

The fence pins drive the guard by compiling `check()` under a made-up caller
filename. coverage.py records every executed code object BY FILENAME, existing
file or not -- so a fabrication that looks like a real tree file makes the
coverage *report* step exit 1 with `No source for code` while every test passes.
That is what reddened the coverage CI leg on `5bfd5b63`.

Two rules, both pinned:

- Every fabricated filename lives under `tmp_path`, outside coverage's `source`
  filter. Real-tree adjacency (is `src/aipass/memory` foreign? is a real backup
  file kin?) is asserted on `_is_kin`, which is pure and compiles nothing.
- There is exactly ONE `compile()` in the test file, and it refuses a filename
  that `abspath`s inside the source tree. `abspath`, not the literal: coverage
  resolves a relative name against the cwd at trace time, so a Windows-spelled
  literal is inert from the repo root and a minter from the branch directory.

### Kinship is spelled, not compared raw (round 5)

The handlers fence asks one question -- is this caller inside my branch? -- and
until 2026-08-31 it asked it with a raw substring test that normalised only ONE
side. On Windows `_BRANCH_ROOT` arrives from `Path` with backslashes while the
caller had just had its backslashes replaced with forward slashes, so the test
could never match: every file in this branch read as FOREIGN and the whole tree
died at the door with backup's own ACCESS DENIED message.

Both sides now go through `_spell_for_kinship()`. Case is folded only when
`os.name == "nt"` -- folding everywhere would ADMIT a foreign `/tmp/BACKUP` on a
case-sensitive filesystem, which is a wider fence, not a safer one. The guard's
own-frame skip uses the same rule for a sharper reason: if that skip misses,
`__init__.py` becomes the reported caller, is trivially kin, and the real
foreign frame beneath it is never examined.


---

[<- Back to BACKUP](../README.md)
