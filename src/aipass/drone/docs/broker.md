[<- Back to the README](../README.md)

# The broker — a delete lane with a server-side path check

**Branch** drone · **Code** `apps/modules/broker.py`, `apps/handlers/broker/` (daemon, client,
path_resolver, protocol)

The broker deletes on behalf of an HMAC-authenticated requester over a unix socket, with a typed
JSON-line protocol and an inherited-fd transport. It records deletions like the plain verb does
(see [rm_and_the_record.md](rm_and_the_record.md)) and passes the requester's identity in rather
than reading its own cwd.

Each start writes a fresh 32-byte HMAC secret to `.ai_central/broker_secret` under the project root
(the host temp directory when there is none), which the launcher reads to sign its identify step.
The file is staged 0600 with an exclusive create and swapped in whole with `os.replace`, so no other
user and no handle on the previous file ever reads it, and the value never reaches a log or the
audit line. Pinned in `TestIdentity` in `tests/test_broker.py`.

---

## Two lanes, one contract

`resolve_beneath()` re-resolves an agent-supplied path server-side, so the broker never trusts the
string it was handed.

- **Linux x86-64** gets `openat2(2)` with `RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS`, where the kernel
  enforces containment.
- **Every other host** walks the path one component at a time, opening each relative to its
  parent's fd with `O_NOFOLLOW` — the only fd-based way to say "and no symlinks" without that
  syscall.

Both lanes must answer the same question: *which path did I just verify?* The openat2 lane reads
`/proc/self/fd/<fd>`, which is correct there: nothing off Linux reaches it. The walk exists for the
hosts that have no `/proc`, so it answers portably:

- **The leaf is measured, not opened** — `lstat` relative to its verified parent's fd. A symlink
  there is refused exactly as `O_NOFOLLOW` refuses one above it, and a fifo cannot block an open
  that never happens.
- **The path is proved before it is returned.** It is assembled from the real base plus the
  verified components and handed back only if it `lstat`s to the same `(device, inode)` the walk
  verified. Swap a component under the walk and the caller gets an error instead of a path nobody
  checked: the anti-swap property, without `/proc`.
- **The flags come from `os`, never from a written-down number.** `0o0400000` is `O_NOFOLLOW` on
  Linux and `O_NOCTTY` on macOS: the literal would have quietly traversed the symlinks it was there
  to block, which is a worse bug than the crash it sat behind.
- **A host with neither `O_NOFOLLOW` nor `dir_fd` support is refused**, not served unverified.

---

## Related

- [rm_and_the_record.md](rm_and_the_record.md) — the record both delete lanes write
