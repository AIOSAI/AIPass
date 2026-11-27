[<- Back to the README](../README.md)

# The vector lane

**Branch** memory · **Code** `apps/modules/search.py`, `apps/handlers/vector/`, `apps/handlers/storage/`

Everything below is the machinery *behind* `drone @memory search "query"` and
`drone @memory verify FPLAN-XXXX` — how text becomes vectors, where the model choice lives, and
what counts as a match. The verbs themselves are in `drone @memory --help`.

---

## Two stores, and who reads which

Every rollover writes twice: into the branch's own **local store** (`<branch>/.chroma`) and into the
**global store** (`memory/.chroma`), which holds every citizen's memories. Plans do the same:
`process-plans` stores each plan in the global `flow_plans` and in its owner's local `flow_plans`
(the plan's `**Branch**:` line, resolved inside its project). `rollover backfill-local` copies what
the global store already holds into each local store, once. See
[rollover_pipeline.md](rollover_pipeline.md#plans-land-in-both-stores).

| Form | Store | Who may run it | Filters |
|---|---|---|---|
| `drone @memory search <query>` | the caller's own `<branch>/.chroma`, every collection in it (@memory: its own rows only) | any seat, the admin included | `--type`, `--n` |
| `drone @memory search global <query>` | `memory/.chroma`, every collection | `@memory`'s seat and the verified admin only | `--branch`, `--type`, `--n` |

**Whose store the local form reads.** `query_executor.caller_local_store()` asks the verified-caller
rail (`caller_gate.verified_caller()`) first. When it proves no one, the branch directory the caller's
cwd sits in answers (`todo_roll.resolve_target(None)`, which reads `AIPASS_CALLER_CWD`, the directory
drone stamps for the original caller). When neither resolves, the search is refused in one sentence.
A rail that raises is a refusal too, never read as "no caller". The path comes from
`orchestrator.local_store_lookup(name, create=False)`, the lookup rollover writes through, with the
same write scope; `create=False` means a search never makes a store.

**No store yet is a state.** A branch whose `.chroma` does not exist answers
`@<branch>: no local store at <path> - nothing has rolled yet` and exits 0; the store is not created.

**`--branch` is refused on the local form**, before the model loads: the local store holds one
citizen. The global form keeps it, with the same collection-owner boundary as before.

**The global gate** is `caller_gate.other_branch_refusal("search global", None, ..., act="reads")`,
the rail `rollover run --branch` and `push` use. Any other seat, or an unverified caller, is refused
with `... not @<seat> - mail @devpulse, the verified admin` and exits 2, before the model loads.

**The first-argument rule.** The global form is chosen only when the first argument is exactly
`global` (`search.GLOBAL_FORM`). `search "global warming"` (one quoted argument) and
`search warming global` are local queries; `search global global` searches the global store for
"global".

**The plan-ID pin reads the same store.** A query that names a plan (`FPLAN-1202`) pins its exact
chunks from `flow_plans` in the store being searched, so a local search never pulls a global chunk.
A store with no `flow_plans` yet answers `exists: false` from `get_by_source`: no pin and an INFO
line, never a warning. A store that fails is still a WARNING.

**The @memory seat's local store is the global store.** `memory/.chroma` is both, so a local search
from `@memory`'s own seat searches as owner: its `memory_*` collections and only the `flow_plans`
chunks tagged `branch: memory`, never another branch's row. `search global` reads the whole store.
Untagged older plan chunks whose owner is @memory are reached through `search global`.

---

## Subprocess isolation

All ML operations (fastembed, chromadb) run via subprocess. The main process never imports these
libraries. `handlers/storage/lane.py` owns the lane: `memory_python()` resolves the interpreter (env var
`AIPASS_MEMORY_PYTHON` → `memory/.venv/bin/python` → `sys.executable`) and `run_json()` sends the
JSON request on stdin and reads the JSON reply on stdout. `CHROMA_SUBPROCESS_SCRIPT` sits beside it in
the same file. The package door does not carry the lane or the script path.

**Who says what when it fails.** The child (`chroma_subprocess.py`) logs nothing: every failure it
sees coming is named in its JSON reply, including an embed run that left no JSON
(`embedder_reason()` names the missing reply, its parse error and the embedder's stderr). The
child's stderr is the crash record for a death before it could reply. `run_json()` logs that
case through prax at WARNING — the label, the exit code and the stderr tail (last 20 lines, at most
2000 characters) — and logs a reply that is not a JSON object. A non-zero exit that carries a JSON
refusal is returned unlogged; the caller logs it.

**Options are checked before the lane starts.** `search` refuses a `--branch`, `--type` or `--n` with
no value, a `--branch`/`--type` that is not a name (a letter or digit, then letters, digits, `_` or
`-`; a leading `@` on `--branch` is dropped) and an `--n` below 1, before the embedding subprocess
runs. Whether a branch or type has vectors is the store's answer, after the model loads.

**A result names its owner from the collection.** Every hit from `search_vectors` and `get_by_source`
carries `branch` (lowercased) and `type` from the metadata the collection was created with, because a
collection name cannot be split back: `ai_mail_email_sent` is branch `ai_mail`, type `email_sent`.
The result screen heads each hit `branch (type)`; a collection created without that metadata is
headed by its own name. A local store's `flow_plans` carries the global collection's metadata
(`FLOW`, `plans`), so a local search heads its plan hits with the store's branch: `devpulse (plans)`.

**The model is downloaded once, with network.** `embed_subprocess.py` loads
`sentence-transformers/all-MiniLM-L6-v2` through fastembed, which reads it from its cache
(`$FASTEMBED_CACHE_PATH`, default `<tempdir>/fastembed_cache`) or downloads it there from Hugging Face
(`qdrant/all-MiniLM-L6-v2-onnx`) or fastembed's storage.googleapis.com mirror. Offline with an empty
cache, fastembed retries and then refuses with "Could not load model ... from any source."; the
refusal names the cache directory and says to run one search while online. There is no fallback.

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

## Folding a renamed branch's collections

`merge_collection(source, target, db_path)` moves every row of `source` into `target` as stored (ids,
embeddings, documents, row metadata) through `add_missing`, so an id already in `target` is left alone.
`target` keeps its own collection metadata, or takes `source`'s when it is new. `source` is dropped only
after every one of its ids reads back from `target`; a copy that raises or loses a row leaves it whole.
A renamed branch needs this because a collection is named `<branch>_<type>`: the next rollover writes the new
name and the old collection is no longer searched as that branch's own. There is no CLI verb; the operation
is sent to `chroma_subprocess.py` as JSON on stdin, `{"operation": "merge_collection", "source": ...,
"target": ..., "db_path": ...}`. Cosine collections store normalised float32 vectors, so a copied
embedding can differ from the one read in the last float32 digit (about 1e-8).

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
- [cli_surface.md](cli_surface.md) — how `search`, `search global` and `verify` are routed
