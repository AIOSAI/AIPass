# Clear Text Secret Logging Standards
**Status:** v1
**Date:** 2026-10-10

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
when a piece of its message is one of the two below. The pieces read: every positional argument,
the message keywords (`exc_info`, `stack_info`, `stacklevel` and `extra` are not message), every
f-string piece, every `%` operand, every `.format()` argument, every `+` operand.

1. **Named as a secret.** A Name, Attribute or Call whose identifier holds a secret word as a
   whole segment, snake_case and camelCase both split: `secret`, `secrets`, `token`, `tokens`,
   `password`, `passwords`, `passwd`, `api_key`, `apikey`, `credential`, `credentials`, `bearer`,
   `auth_header`, `access_key`, `private_key`. The two-word ones match as consecutive segments.
   `credentials[0]` reads the collection; `str()`, `repr()`, `Path()`, `os.fspath()` and the
   string methods (`.strip()`, `.lower()`, `.encode()` ...) are looked through.
2. **Built in this file from a secret-named source.** File-local, settled in at most ten passes.

   It **starts** only from:
   - a secret-named **module-level binding**: an assignment at the file's top level
     (`SECRETS_BASE = Path.home() / ".secrets" / "aipass"`), read where no parameter or local of
     the same name shadows it;
   - a secret-named **attribute read**: `secrets_store.SECRETS_BASE`, `self.api_key`.

   It never starts from a parameter, a loop or `with` target, a function-local name, a function's
   return or a secret-named call. From a source it **follows**:
   - a local assigned, looped, `with`-bound or walrus-bound from a built value;
   - a same-file function whose `return` hands a built value back (calls by name, or `self.`/`cls.`);
   - a parameter of a same-file function that some same-file call hands a built value;
   - an attribute or subscript of a built name (`target.parent`).

   A subscript or attribute target (`entry["k"] = token`) binds no name.

**Why arm 2 starts so narrowly.** A parameter or loop variable called `token` is a shell word or a
counter as often as a credential. @drone's `_resolve_mail_token(token)` hands its argument back,
and spreading from that parameter convicted `command`, `args[idx + 1]`, `message` and `unknown` on
log lines that say nothing secret. Its name is still judged by arm 1 wherever it reaches a log line
itself, and there the rename is the cure. A module-level binding and an attribute are where a file
names its secret stores, and they are CodeQL's sources too (`SensitiveVariableAssignment`,
`SensitiveAttributeAccess`). Spreading from secret-named calls was dropped for the same reason: a
function named for a token (`secrets.token_hex`, `issue_token`) returns what its name says only
sometimes.

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
