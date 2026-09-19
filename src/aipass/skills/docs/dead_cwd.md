[← Back to the skills README](../README.md)

# Running Where The Working Directory Is Gone

Every skills module imports without a readable current directory. Why that is not theoretical here, and what holds it.

Every skills module imports without a readable current directory.

`ntpath.realpath` calls `os.getcwd()` on its first lines **unconditionally** —
before it checks whether the path is even relative. `posixpath.realpath` reads
the cwd only for relative paths, which is why this stayed invisible on Linux.
`Path.resolve()` routes through realpath, so on Windows any
`Path(__file__).resolve()` *reached at import* is an import-time crash for a
process whose directory was deleted or whose network share dropped. Not
"degrades" — cannot import.

This matters more here than in most branches: skill units run in host processes
nobody in this branch chose — the telegram relay, cron-fired lanes, hook
subprocesses — and those are exactly the processes likely to hold a dead or
foreign working directory.

Every module-level location goes through one helper:

```python
from aipass.skills.apps.handlers.module_paths import module_file

_BRANCH_ROOT = module_file(__file__).parents[3]
```

`module_file()` is **stdlib-only on purpose**: importing prax would put the
logger's own construction — which reads the cwd — onto the very path the helper
protects. When resolve fails it reports once per path on stderr and returns the
unresolved absolute spelling, which loses symlink normalisation and nothing
else.

Two sites guard themselves inline instead, because they run where the helper
cannot be imported: `apps/skills.py` (the block runs *before* any aipass import
by design, removing the shadowing path that would resolve `aipass`) and
`tools/verify_branch.py` (ships inside spawn's agent template, where `aipass`
is not importable at all).

The handlers guard walks frames with `sys._getframe` rather than
`inspect.stack()`. inspect materialises a FrameInfo per frame, and
`getmodule()` calls `os.path.realpath` at `inspect.py:1009` outside any try —
so the guard needed a readable cwd before a single line of its own code ran,
and every module in this branch imports through it.

The worlds themselves are defined once, in `tests/dead_cwd_world.py`. They
patch pathlib's pre-3.11 `_NormalAccessor` as well as the module name: that
accessor **captured** its copies of `os.getcwd` and `os.path.realpath` when
pathlib was first imported, so on Python 3.10 a bare module rebind patches a
name nothing reads again and the world never arms. Two of these pins were
vacuously green on the 3.10 CI leg for exactly that reason. There is no 3.10 on
this machine, so the capture is rebuilt locally on whatever interpreter is
running and the discrimination is falsifiable here rather than derived.

That rebuilt accessor captures a **sentinel** for realpath, not the host's.
An instrument must not import behaviour it is not testing: the question it
asks is "did the patch reach the captured attribute", and a live capture makes
the answer depend on the dialect — on nt the accessor reads the cwd on its own
account, so a world that reached nothing still answers *raised* and the probe
convicts the host. The same file carries `posixpath`- and `ntpath`-shaped
realpaths written **by name and by behaviour**, never by aliasing the dialect's
own `realpath` (off Windows `ntpath.realpath` is a wrapper around `abspath` and
leaves an absolute path alone, so an nt world built by aliasing never arms).
Every accessor pin runs under both dialects and must return the same verdict;
one shape that is *supposed* to differ is held alongside them, so a litmus that
reached nothing cannot pass quietly. Where a claim really is per-platform — a
relative arming path raises in both dialects, an absolute one only on nt — it
is written as a two-row table with both rows measured here and a pin requiring
the live host to agree with its own row.

Pinned by `tests/test_dead_cwd_imports.py`, which imports every skills module
in a child process under two denial worlds (deny `getcwd`; deny `realpath`),
plus a healthy baseline. Both worlds carry a control proving the world is live,
and a control proving that control can say no.

Two runtime paths are covered there too, because skill units resolve them in
those same host processes: skill **discovery** drops the project search path
when there is no current directory and keeps serving global and builtin skills,
while skill **creation** refuses outright — it writes, and a target that cannot
be computed must not be guessed at.

---

*Owned by the skills branch. The face is [../README.md](../README.md).*
