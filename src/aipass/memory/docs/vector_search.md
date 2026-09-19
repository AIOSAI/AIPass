[<- Back to the README](../README.md)

# The vector lane

**Branch** memory · **Code** `apps/modules/search.py`, `apps/handlers/vector/`, `apps/handlers/storage/`

Everything below is the machinery *behind* `drone @memory search "query"` and
`drone @memory verify FPLAN-XXXX` — how text becomes vectors, where the model choice lives, and
what counts as a match. The verbs themselves are in `drone @memory --help`.

---

## Subprocess isolation

All ML operations (fastembed, chromadb) run via subprocess. The main process never imports these
libraries. Python interpreter resolved via `_get_memory_python()` (env var `AIPASS_MEMORY_PYTHON` →
`memory/.venv/bin/python` → `sys.executable`).

---

## `vectorize_and_store` — text in, this branch owns the model

Shipped in 1.4.0 on 2026-08-23. `chroma_subprocess.py` gained a **text-in** operation so another
branch can archive its own content without ever choosing an embedding model:

```
vectorize_and_store(branch, memory_type, texts, metadatas, db_path=None)
    → embeds via embed_subprocess.py, stores through the existing _store_vectors path
    → content-hash IDs, upsert, dedup — same guarantees as rollover
    → validates: branch and memory_type required, len(metadatas) == len(texts)
    → timeout max(30, len(texts) * 3)s; always returns an explicit success flag
```

Caller today: `@ai_mail`'s `handlers/email/purge.py` — it sends sent/deleted mail as text before
deleting the originals (`ai_mail_email_sent`, `ai_mail_email_deleted`). The model choice stays here
because consistency across a collection is this branch's job, not the caller's.

**Why it exists.** From its creation in March 2026 until the fix on 2026-08-24 — more than five
months — `purge.py` called an operation that did not exist. The handler
answered `success: false` on stdout and **exited 0**; the caller checked only the return code, so
purge reported mail vectorized and deleted it. 55 purges across 11 branches into a collection that
had never been created. An unknown operation that exits 0 is a lie — the operation now exists, and
the caller reads the payload.

---

## Anchored plan-ID matching

From 1.3.0. `_source_matches()` backs `drone @memory verify`. A plain `label in source_file` had no
boundary check, so `DPLAN-0012` matched inside `TDPLAN-0012` — `verify DPLAN-0012` reported 27 chunks
live that all belonged to a different plan. A hit now counts only at the string start or after a
non-alphanumeric boundary, and scanning continues past a rejected hit so a real match later in the
same string (`TDPLAN-0012_supersedes_DPLAN-0012`) is still found. The same predicate is shared by
`_delete_by_source`, which **deletes** — that call site was the reason to fix it at the source.

---

## Related

- [rollover_pipeline.md](rollover_pipeline.md) — the lane that feeds this one
- [trinity_push.md](trinity_push.md) — vectorize → VERIFY → prune, the law over this lane
- [cli_surface.md](cli_surface.md) — how `search` and `verify` are routed
