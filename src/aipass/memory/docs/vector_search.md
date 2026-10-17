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

`chroma_subprocess.py` has a **text-in** operation so another
branch can archive its own content without ever choosing an embedding model:

```
vectorize_and_store(branch, memory_type, texts, metadatas, db_path=None)
    → embeds via embed_subprocess.py, stores through the existing _store_vectors path
    → content-hash IDs, upsert, dedup — same guarantees as rollover
    → validates: branch and memory_type required, len(metadatas) == len(texts)
    → timeout max(30, len(texts) * 3)s; always returns an explicit success flag
```

Callers: `@ai_mail`'s `handlers/email/purge.py`, which sends sent/deleted mail as text before
deleting the originals (`ai_mail_email_sent`, `ai_mail_email_deleted`), and this branch's own trinity
push (`handlers/templates/push_store.vectorize_and_store_subprocess`). The model choice stays here
because consistency across a collection is this branch's job, not the caller's: two callers encoding
with two models would put unsearchable vectors in one collection.

**Read the payload, not the exit code.** An operation the handler does not know answers
`{"success": false, "error": "Unknown operation: <name>"}` on stdout and exits 0; only an exception
inside an operation exits 1. A caller that checks only the return code reads a refusal as a store.

---

## Anchored plan-ID matching

`_source_matches()` backs `drone @memory verify`. A plain substring test has no boundary check, so
`DPLAN-0012` would match inside `TDPLAN-0012`. A hit counts only at the string start or after a
non-alphanumeric boundary, and scanning continues past a rejected hit so a real match later in the
same string (`TDPLAN-0012_supersedes_DPLAN-0012`) is still found. The same predicate is shared by
`_delete_by_source`, which **deletes**, which is why the boundary lives in the shared predicate.

---

## Related

- [rollover_pipeline.md](rollover_pipeline.md) — the lane that feeds this one
- [trinity_push.md](trinity_push.md) — vectorize → VERIFY → prune, the law over this lane
- [cli_surface.md](cli_surface.md) — how `search` and `verify` are routed
