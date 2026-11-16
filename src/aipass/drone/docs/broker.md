[<- Back to the README](../README.md)

# The broker — a removal lane with a server-side path check

**Branch** drone · **Code** `apps/modules/broker.py`, `apps/handlers/broker/` (daemon, client,
path_resolver, protocol)

The broker removes on behalf of an HMAC-authenticated requester over a unix socket, with a typed
JSON-line protocol and an inherited-fd transport. Its live caller is @ai_mail's dispatch monitor,
which connects one per dispatch when `AIPASS_SANDBOX_ENABLED` is on and hands the fd to the
sandboxed child; `drone rm` under `AIPASS_BROKER_FD` routes through it. It records every outcome
like the plain verb does (see [rm_and_the_record.md](rm_and_the_record.md)), lane `broker`, and
passes the requester's identity in rather than reading its own cwd.

## One decision, the plain verb's

After its own containment (the identity's bases: the temp dir, the caller's branch, the whole repo
for the identity granted it, and never a base itself), the broker asks `rm_handler.judge()` — the
function `drone rm` asks — with the requester's seat: its own branch, and as admin the identity the
policy grants the whole repo. So the rule is the same in both lanes: in the tree a target moves into
the `.archive` beside it through `rm_handler.move_into_archive()`, never over a taken name; a dot
name, a carve-out, a `.archive`, a branch root and a folder holding a citizen are refused; only the
temp dir's files and bytecode are truly deleted. The protocol has no `--dot`, so the dot guard is
never lifted here. Every act runs relative to the parent fd the resolver held, so a parent swapped
after the check cannot redirect it.

Each start writes a fresh 32-byte HMAC secret to `.ai_central/broker_secret` under the project root
(the host temp directory when there is none), which the launcher reads to sign its identify step.
The file is staged 0600 with an exclusive create and swapped in whole with `os.replace`, so no other
user and no handle on the previous file ever reads it, and the value never reaches a log or the
audit line. Pinned in `TestIdentity` in `tests/test_broker.py`.

---

## Two lanes, one contract

`resolve_beneath()` re-resolves an agent-supplied path server-side, so the broker never trusts the
string it was handed.

- **x86-64** gets `openat2(2)` with `RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS`, where the kernel
  enforces containment.
- **Every other machine** walks the path one component at a time, opening each relative to its
  parent's fd with `O_NOFOLLOW` — the only fd-based way to say "and no symlinks" without that
  syscall.

Both lanes must answer the same question: *which path did I just verify?* The openat2 lane reads
`/proc/self/fd/<fd>`. The walk never reads `/proc`:

- **The leaf is measured, not opened** — `lstat` relative to its verified parent's fd. A symlink
  there is refused exactly as `O_NOFOLLOW` refuses one above it, and a fifo cannot block an open
  that never happens.
- **The path is proved before it is returned.** It is assembled from the real base plus the
  verified components and handed back only if it `lstat`s to the same `(device, inode)` the walk
  verified. Swap a component under the walk and the caller gets an error instead of a path nobody
  checked: the anti-swap property, without `/proc`.
- **The flags come from `os`, never from a written-down number.**

---

## Related

- [rm_and_the_record.md](rm_and_the_record.md) — the record both delete lanes write
