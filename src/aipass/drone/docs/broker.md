# The broker — a delete lane with a server-side path check

**Branch** drone · **Code** `apps/modules/broker.py`, `apps/handlers/broker/` (daemon, client,
path_resolver, protocol)
**Moved out of README.md** 2026-09-15 (DPLAN-0347, the layer contract).

The broker deletes on behalf of an HMAC-authenticated requester over a unix socket, with a typed
JSON-line protocol and an inherited-fd transport. It records deletions like the plain verb does
(see [rm_and_the_record.md](rm_and_the_record.md)) and passes the requester's identity in rather
than reading its own cwd.

---

## Two lanes, one contract

`resolve_beneath()` re-resolves an agent-supplied path server-side, so the broker never trusts the
string it was handed.

- **Linux x86-64** gets `openat2(2)` with `RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS`, where the kernel
  enforces containment.
- **Every other host** walks the path one component at a time, opening each relative to its
  parent's fd with `O_NOFOLLOW` — the only fd-based way to say "and no symlinks" without that
  syscall.

Both lanes must answer the same question: *which path did I just verify?* Until 2026-09-12 the walk
answered it by reading `/proc/self/fd/<fd>`. `/proc` is Linux furniture, so the fallback raised
`FileNotFoundError` on exactly the hosts it exists for — every broker path resolution on macOS
(seedgo's `host_portability` standard caught it in CI). The same spelling in the openat2 lane is
correct and stays: nothing off Linux ever reaches it.

The walk now answers portably, and keeps the property that made it worth having:

- **The leaf is measured, not opened** — `lstat` relative to its verified parent's fd. A symlink
  there is refused exactly as `O_NOFOLLOW` refuses one above it, and a fifo cannot block an open
  that never happens.
- **The path is proved before it is returned.** It is assembled from the real base plus the
  verified components and handed back only if it `lstat`s to the same `(device, inode)` the walk
  verified. Swap a component under the walk and the caller gets an error instead of a path nobody
  checked — the anti-swap property the `/proc` readlink bought, bought another way.
- **The flags come from `os`, never from a written-down number.** `0o0400000` is `O_NOFOLLOW` on
  Linux and `O_NOCTTY` on macOS: the literal would have quietly traversed the symlinks it was there
  to block, which is a worse bug than the crash it sat behind.
- **A host with neither `O_NOFOLLOW` nor `dir_fd` support is refused**, not served unverified.

---

## Related

- [rm_and_the_record.md](rm_and_the_record.md) — the record both delete lanes write
