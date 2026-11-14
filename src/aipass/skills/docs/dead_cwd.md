[← Back to the skills README](../README.md)

# Running Where The Working Directory Is Gone

Every skills module imports without a readable current directory. Why that is not theoretical here, and what holds it.

Every skills module imports without a readable current directory.

This matters more here than in most branches: skill units run in host processes
nobody in this branch chose — @api's host routes, cron-fired lanes, hook
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
name nothing reads again and the world never arms. The capture is rebuilt on
whatever interpreter is running, so the discrimination is falsifiable on any
machine rather than derived.

That rebuilt accessor captures a **sentinel** for realpath, not the host's.
An instrument must not import behaviour it is not testing: the question it
asks is "did the patch reach the captured attribute". The same file carries a
`posixpath`-shaped realpath written **by name and by behaviour**, never by
aliasing `posixpath.realpath`. A relative arming path raises whether or not the
world armed and an absolute one does not; that is written as a table row with
a pin requiring the live host to agree with it.

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
