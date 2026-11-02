# Clear Text Secret Logging Standards
**Status:** v1.3 (checker 1.3.0: arm 3, a secret reader's document name in the message, CodeQL round eleven)
**Date:** 2026-10-10 · **Modified:** 2026-10-11

---

## What It Is

PR #774 round seven, head 38166f35: GitHub's CodeQL check went red while every workflow job was
green. Its one HIGH row, `py/clear-text-logging-sensitive-data`, sits on @prax
`apps/modules/logger.py:135`, `SystemLogger.warning`, the fleet's one log sink. CodeQL reports
the SINK and lists the two SOURCES it traced into it, both classified "secret". The leak is never
the sink: it is the caller that hands the sink a value named, or built from a name, that says
secret. This rule convicts the caller line.

```python
def lock_path() -> Path:
    return secrets_store.SECRETS_BASE / TOKEN_PROVIDER / f"{TOKEN_SLUG}.lock"   # tokens.py:267, the source
...
path = lock_path()
logger.warning("[host_api] breaking a stale token store lock at %s", path)      # tokens.py:370, the row
```

---

## The shape

A prax logger call, `logger.debug/info/warning/error/critical/exception` (the receiver named
`logger`, or bound by `from aipass.prax... import logger|system_logger as <name>`), is a row
when a piece of its message is one of the two below, or (arm 3) its MESSAGE writes a secret
reader's document name. The pieces read: every positional argument,
the message keywords (`exc_info`, `stack_info`, `stacklevel` and `extra` are not message), every
f-string piece, every `%` operand, every `.format()` argument, every `+` operand.

1. **Named as a secret.** A Name, Attribute or Call whose identifier holds a secret word as a
   whole segment, snake_case and camelCase both split: `secret`, `secrets`, `token`, `tokens`,
   `password`, `passwords`, `passwd`, `api_key`, `apikey`, `credential`, `credentials`, `bearer`,
   `auth_header`, `access_key`, `private_key`, `trusted`, `confidential` (`untrusted` is its own
   segment and never matches). The two-word ones match as consecutive segments.
   `credentials[0]` reads the collection; `str()`, `repr()`, `Path()`, `os.fspath()` and the
   string methods (`.strip()`, `.lower()`, `.encode()` ...) are looked through.
2. **Built in this file from a secret-named source.** File-local, settled in at most ten passes.

   It **starts** only from:
   - a secret-named **module-level binding**: an assignment at the file's top level
     (`SECRETS_BASE = Path.home() / ".secrets" / "aipass"`), read where no parameter or local of
     the same name shadows it;
   - a secret-named **attribute read**: `secrets_store.SECRETS_BASE`, `self.api_key`;
   - the **result of a call** named by CodeQL's source words (1.1.0): `secret = _get_secret(bot_id)`,
     `doc = secrets_store.get_secret(a, b)`, `load_trusted_keys()`, `read_confidential()`, assigned to
     any name, local or module. The call's secret word must be `secret`, `secrets`, `trusted` or
     `confidential` (never token or password: `secrets.token_hex`, `issue_token`); the identifier
     acquittals still apply (`secret_path()`, `redact_secret()`); a name that holds hash, md5, sha,
     random, encode, encrypt, public, user, login, logging, clear or redact anywhere is not a source
     (CodeQL's exclusions); and a setter verb segment (set, write, save, put, delete, remove, drop,
     rotate, revoke) says the call stores the secret and returns a status, so it seeds nothing.

   A token word (`token`, `tokens`) seeds neither a binding nor an attribute: measured, argparse's
   `args.tokens` in @prax `monitor.py` is a list of branch names. Arm 1 still reads it on the line.

   It never starts from a parameter, a loop or `with` target or a function-local name. From a
   source it **follows**:
   - a local assigned, looped, `with`-bound or walrus-bound from a built value (a secret-named
     local too: `secret = _get_secret(bot_id)` carries the call's taint on);
   - a comprehension or generator over a built value: its element is read with the target bound to
     what it iterates (`key for key in document` carries the document's keys); a filter acquits
     nothing, `len(key)` as the element is still a redaction;
   - the wrappers `sorted`, `list`, `tuple`, `set`, `frozenset`, `dict`, `reversed`, `str`, `repr`,
     `", ".join(...)`, `.format()`, f-strings and `%`;
   - a same-file function whose `return` hands a built value back (calls by name, or `self.`/`cls.`);
   - a parameter of a same-file function that some same-file call hands a built value (a log line
     inside that function is judged with it);
   - **the same-file hop**: a call that hands a built value to a same-file function whose `return`
     is built from that parameter has a built result (`strays = non_secret_keys(secret)`). This is
     the only place a parameter is followed back out, and it is per call: the same helper handed a
     clean argument returns clean;
   - an attribute or subscript of a built name (`target.parent`, `doc["k"]`, `doc[0]`, `doc[:10]`);
   - **a read of a built value** (1.2.0): `.get(k)`, `.pop(k)`, `.setdefault(k, d)`, `.items()`,
     `.keys()`, `.values()` carry the receiver on (`records = stored.get("tokens")`); a `.get` default
     is not followed. With the loops and unpacking above, `for k, v in built.items()` binds both;
   - **an add of a built value** (1.2.0): `seen.append(key)`, `.extend(xs)`, `.add(x)` and
     `.insert(i, x)` (judged on `x`, never `i`) bind the named list or set; a dict literal or
     `dict(...)` holding a built key or value is built. `self.items.append(x)` binds no name.

   `str()`, `repr()`, f-strings and `%r` of a built value stay rows; `len()`, `type(x).__name__` and a
   slice of four characters or fewer stay redactions.

   A subscript or attribute target (`entry["k"] = token`) binds no name. A `non_` or `not_` prefix on
   a function says what it filters, not that its return is clean: it acquits nothing.
3. **A secret reader's document name in the message** (1.3.0, CodeQL round eleven). The one
   parameter seed, as narrow as it can be held:
   - **the file** defines a secret LISTER: a def whose name holds `list` as a segment beside
     CodeQL's source words (`list_secrets`). The file's own defs say it is a secrets store;
   - **the def** is a secret READER: its name holds `get`, `read`, `load` or `fetch` as a segment
     beside secret(s)/trusted/confidential (`get_secret`, `_get_secret`, `read_secret`,
     `load_secret`, `fetch_secret`), read as the call seed reads a name: no CodeQL exclusion word,
     no setter verb (set/write/save/put/delete/remove/drop/rotate/revoke), no identifier segment
     (`get_secret_path`), and no `list` segment (a lister returns names, it reads no secret);
   - **the parameter** is a required positional one (no default, not `self`/`cls`) that no lister
     in the file takes, and the reader never rebinds. The lister's parameters are the namespace a
     caller chooses (`provider`); the reader's others are the document names the listing hands
     back (`slug`). This is how the arm tells slug from provider: by the file's own lister, not by
     a guess at position or a list of names;
   - **the position** is the MESSAGE only: the log call's first argument (or `msg=`/`message=`),
     read through its f-string pieces, both sides of a `%` or `+`, `.format()`'s receiver and
     arguments, `str()`/`repr()` and the string methods. A `%s` argument is not this arm's row (it
     is CodeQL's reach; arms 1 and 2 still judge arguments). `len()`, a redaction or a slice of four
     characters or fewer acquits; any other call in the message does too.

**Why arm 2 starts so narrowly.** A parameter or loop variable called `token` is a shell word or a
counter as often as a credential. @drone's `_resolve_mail_token(token)` hands its argument back,
and spreading from that parameter convicted `command`, `args[idx + 1]`, `message` and `unknown` on
log lines that say nothing secret. Its name is still judged by arm 1 wherever it reaches a log line
itself, and there the rename is the cure. A module-level binding and an attribute are where a file
names its secret stores, and they are CodeQL's sources too (`SensitiveVariableAssignment`,
`SensitiveAttributeAccess`). Spreading from every secret-named call was dropped for the same reason:
a function named for a token (`secrets.token_hex`, `issue_token`) returns what its name says only
sometimes. 1.1.0 re-admits calls on CodeQL's own source words only, the narrowing measured below.

Arm 2 is what reaches the CodeQL rows: no name on those log lines says secret; the source they were
built from does.

## What is not a row

| case | why |
|---|---|
| `token_id`, `token_count`, `token_store`, `secret_path`, `secret_name`, `n_tokens`, `TOKEN_SLUG` | a segment beside the word says the identifier NAMES a secret: id(s), count(s), n, num, store, path(s), name(s), slug, file, filename, dir, label, kind, type, len, length, size |
| `redact(x)`, `mask_token(x)`, `scrub(x)`, `len(x)` | a redaction: the call's name holds redact, mask or scrub, or it is `len` |
| `token[-4:]`, `token[:4]` | a slice that shows at most four characters. `token[:10]` shows the secret and stays a row |
| `logger.warning("token refused")` | the word in a string constant names a field; it does not carry one |
| `print(token)`, `log.warning(token)` with a stdlib `log` | not a prax logger receiver; `output_routing` owns `print` |
| a value that crosses into another file's function | arm 2 is file-local; the value is judged again by its name in the file that logs it |

## Why names rule

A scanner and a stranger both read the name. A name that says secret on a log line is a leak in
the reader's eyes even when the value is benign, so the cure for a false hit is the **rename**,
and the rename is a cure, not a dodge. On a public repo the name is all a reader has.

---

## Check first

Measured 2026-10-10 over 1,301 product files (`src/aipass/*/apps` and `*/lib`, tests excluded).

| | |
|---|---|
| rows | **16**, in 8 files, 4 branches |
| arm 1, named on the line | 9 |
| arm 2, built from a source | 7 |
| dropped while measuring | 17 spread from secret-named calls (`set_secret`, `token_hex`, `issue_token` ...); 6 from a subscript target's index read as a binding (`data["bots"][bot_id] = entry`); 9 spread from parameter, loop and local sources (@drone `drone.py` x6, `tracked_handler.py`, `git_module.py:880`; @memory `todo.py:123`) |

| branch | rows |
|---|---|
| api | arm 2: `auth/secrets.py` :62 :187 :216, `host/tokens.py` :324 :370 :432 :438 |
| drone | arm 1: `modules/git_module.py` :988 |
| hooks | arm 1: `security/git_gate.py` :373, `modules/bash_writes.py` :622 :626, `modules/cadence.py` :751 :828 :841 :946 |
| skills | arm 1: `lib/telegram/apps/handlers/botfather_client.py` :445 (`token[:8]`; `lib/` is outside the audit corpus) |

**The CodeQL rows.** CodeQL's "secret" class is the regex `secret|trusted|confidential`; its
sources include an attribute read and a variable assignment so named. In the fleet, the warning
calls such a source reaches are exactly six, and the rule convicts all six: @api
`host/tokens.py` :324 :370 :438, from `secrets_store.SECRETS_BASE` read at :182 (`store_path`)
and :267 (`lock_path`), two sources, which matches the alert's two; and `auth/secrets.py`
:62 :187 :216, from the `SECRETS_BASE` assignment at :29. Which pair CodeQL drew could not be
replayed here. Either way, both are convicted.

### Round nine (checker 1.1.0)

PR #774 round eight: the alert stayed after @api's cure. The live path was @skills
`lib/telegram/apps/handlers/config.py`, `load_bot_config`: `secret = _get_secret(bot_id)` (a
secret-named call into a local), `strays = non_secret_keys(secret)` (a same-file function returning
`sorted(key for key in document if key not in SECRET_FIELDS)`), and `strays` on a warning. 1.0.0
never seeded from the call. 1.1.0 convicts the pre-cure shape at the warning; the cure @skills
shipped (the count, `len(strays)`, without the names) is acquitted.

Measured over 1,302 product files, the fleet at **0 rows** before and **0 rows** after (the config
line was already cured on disk). Each narrowing below was kept because dropping it convicted a false
row:

| variant | rows | the false rows |
|---|---|---|
| call seed from every secret word | 10 | `secrets.token_hex` (@api `uploads.py` :219 :281 :300, @devpulse `registry.py` :344), `issue_token` (@api `host_api.py` :374), `context_fill_tokens` (@hooks `context_gauge.py` :106 :121), `_get_turn_token` (@hooks `cadence.py` :828 :841), `_without_credentials` (@api `git_reads.py` :1435) |
| credential(s) added to the call words | 1 | `_without_credentials` (@api `git_reads.py` :1435) |
| no setter-verb exclusion | 1 | @api `host/config.py` :150, from `secrets_store.set_secret(...)` |
| token words seed bindings and attributes | 1 | @prax `monitor.py` :274, argparse's `args.tokens` through `list()` into `args` |
| CodeQL's exclusion words dropped | 0 | (kept: they are CodeQL's model) |
| arm 1 without trusted and confidential | 0 | the two new words convict nothing new today |

So `creds = load_credentials()`, the dispatch's third example, does not seed: credential(s) is not a
CodeQL source word, and admitting it convicted a false row. It is still arm 1 on the line.

### Round ten (checker 1.2.0)

PR #774 round nine, head e23f11ca: the same one alert, two sources, constant since round seven.
Neither api's `SECRETS_BASE` cure nor skills' telegram cure moved the count, so CodeQL's live
sources here are secret-named CALL results. 1.1.0 seeded from the call and stopped one hop short:
@api `host/tokens.py` `load_tokens` reads `stored = secrets_store.get_secret(...)` (:158), then
`records = stored.get("tokens")` (:167, where the taint was lost), then the comprehension (:172);
`touch_token` loops over `load_tokens()` and calls `_is_due(record.get("last_used"))`, and
`_is_due` logs `last_used %r` (:655). 1.2.0 follows the `.get()` on both hops. The pre-cure file
(HEAD 6c3aa9aa) convicts at :655 and only there: :631 logs `token_id`, which comes from
`server.py` and is an identifier besides; a file-local arm cannot see it, and no change was asked.
@api's cure (the stamp off the line, `type(e).__name__` instead of the error's text) acquits.

Measured over 1,383 product files (`src/aipass/*/apps` and `*/lib`), the live fleet (api's cure on
disk) at **0 rows** before and **0 rows** after. Each sub-arm alone, every other widening off:

| sub-arm | rows alone | rows of the pre-cure tokens.py |
|---|---|---|
| `.get` | 0 | :655 |
| `.pop`, `.setdefault`, `.items`, `.keys`, `.values` (each) | 0 | 0 |
| `.append`, `.extend`, `.add`, `.insert` (each) | 0 | 0 |
| dict literal | 0 | 0 |
| all reads off | 0 | 0 (:655 lost) |
| all adds off | 0 | :655 |

No narrowing was needed: no sub-arm convicted a wrong row. The fixtures pin the arms: the pre-cure
tokens cut goes red with `.get` disabled, the appended-keys fixture with `.append` disabled.

### Round eleven (checker 1.3.0)

PR #774 round eleven: ground truth. @devpulse printed CodeQL's SARIF paths into the Security job
log (45ba6aa0). The one HIGH `py/clear-text-logging-sensitive-data` alert reads, every step
CodeQL's own:

| step | where | what |
|---|---|---|
| source 1 | @skills `lib/telegram/apps/handlers/config.py:412` | `_api_list_secrets("telegram")`, a secret-named call result |
| source 2 | @api `apps/modules/secrets.py:136` | `_handler.list_secrets(provider)`, the same listing one frame deeper |
| | @skills `lib/telegram/handler.py:155` | `targets = [...] or list_bot_configs()` |
| | `handler.py:160` | `for bot_id in sorted(targets)` (list element) |
| | `handler.py:161` | `migrate_bot_config(bot_id, ...)` |
| | `config.py:197` -> `:215` | `def migrate_bot_config(bot_id)` -> `_get_secret(bot_id)` |
| | `config.py:69` -> `:83` | `def _get_secret(bot_id)` -> `_api_get_secret("telegram", bot_id, as_json=True)` |
| | @api `apps/modules/secrets.py:82` -> `:97` | `def get_secret(provider, slug)` -> `_handler.get_secret(provider, slug, ...)` |
| | @api `apps/handlers/auth/secrets.py:40` | `def get_secret(provider, slug)` |
| the caller line | `auth/secrets.py:83` | `logger.warning(f"Secret not found: {provider}/{slug}")`: slug in the MESSAGE f-string |
| the sink | @prax `apps/modules/logger.py:131` -> `:135` | `message` -> `logger.warning(message, *args, **kwargs)`, columns 24-31 = `message` |

**CodeQL's reach is the MESSAGE only.** The sink's columns are the message parameter; a value in
the `%s` arguments never reached it through prax's two wrappers. That is why rounds eight, nine and
ten (the `SECRETS_BASE` paths, the telegram strays, the token store: all `%s` arguments) never
moved the count. This is recorded as CodeQL's reach, **not** as this standard's rule: arms 1 and 2
stay stricter (an argument is a row too), because the log line carries the value either way.

**The new arm.** The file-local arms could not see the path: the slug is a parameter of
`get_secret`, and the names come out of the store's own listing in another file. Arm 3 (above)
convicts where the listing's names land: a secret reader's document parameter in its message.
What it does with each line of the pre-cure file (HEAD 6c3aa9aa):

| line | text | verdict |
|---|---|---|
| :64 | `f"Provider directory not found under the secrets base: {provider}"` | acquitted: `provider` is `list_secrets(provider)`'s own parameter, the namespace the caller chose |
| :83 | `f"Secret not found: {provider}/{slug}"` | **convicted** on `slug`, the document name; `provider` in the same f-string is acquitted on its own and is not what the row names |
| :191, :220 | `f"Error reading a ... secret file: {e}"` | acquitted: `e` is no parameter |

@api's cure (83f812c9), `"Secret not found under provider %s: no JSON or raw document for the
requested slug", provider`, acquits: the slug is gone and provider is a `%s` argument, which this
arm does not read. The telegram `handler.py` loop crosses files and stays out of file-local reach;
no change is asked there.

Measured over 1,383 product files (`src/aipass/*/apps` and `*/lib`), the live fleet (api's cure on
disk) at **0 rows** before and **0 rows** after. The variants, each against the fleet and the pre-cure
file:

| variant | fleet rows | pre-cure `auth/secrets.py` |
|---|---|---|
| shipped: lister-gated, the lister's parameters as namespace | 0 | :83 (`slug`) only |
| every required parameter of every reader, no gate | 1 (@api `auth/secrets.py:64`, `provider`: false) | :64 and :83, both on `provider` |
| lister gate, every required parameter | 1 (the same false `provider` row) | :64 and :83 on `provider` |
| no gate, the last required parameter only | 0 | :83 (`slug`) only |

The namespace from the lister is what acquits `provider`; the last-parameter variant matches today
but guesses at position (a one-parameter reader such as @api `auth/keys.py`
`_read_key_from_secrets(provider)` would be read as handed a document name), so the file's own
lister rules. The reader defs in the fleet today: @api `auth/secrets.py` `get_secret`,
`_read_json_secret`, `_read_raw_secret` and `modules/secrets.py` `get_secret` (both files define
`list_secrets`), @api `auth/keys.py` `_read_key_from_secrets`, @skills telegram `config.py`
`_get_secret` and `telethon_auth.py` `_get_secret` (no lister: out). The fixtures pin both shapes:
the pre-cure cut convicts :83 and only it, the cured line acquits; disabling the arm turns
`test_the_pre_cure_not_found_line_is_convicted_and_only_it` red.

## Scoring

Scored per file: 0 on any row, else 100. Every row goes on ONE check, as
`<file>:<line> logs <what> in clear text - <cure>`, where `<what>` names the piece and, for arm 2,
the secret name it was built from.

## The cure

A real secret: log the field's name, its `len()` or its last four characters, or `redact()`/
`mask()` it, or leave it out of the line. A value that is no secret: rename it so the line no
longer says it is: a parse token is an `arg` or a `word`, and a lock path built from a secrets
root is cured where the root is named.

---

[← Back to README](../../../README.md)
