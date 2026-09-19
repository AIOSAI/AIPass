[<- Back to the README](../README.md)

# S84: Multi-line Reply Body Truncation — Root Cause & Fix

Why a multi-line reply or send body arrives whole: the S84 truncation, its root cause, and the argument handling that fixed it.

## Bug

Reply and send commands silently truncate multi-line message bodies to the first argument.

**Reported:** @devpulse dispatch 7b6a70b9 (2026-06-08)
**Evidence:** @hooks sent two replies with full multi-line bodies; both arrived in devpulse inbox as first line only (60 chars / 48 chars). @memory's reply arrived intact (951 chars).

## Root Cause

Two code paths only captured the second positional CLI argument as the message body, dropping everything after it:

1. **`email.py:handle_reply`** (line 280):
   ```python
   send_reply(branch_path, original, args[1])  # args[2:] silently dropped
   ```

2. **`send_args.py:parse_send_args`** (line 106):
   ```python
   message = rest[1]  # rest[2:] silently dropped
   ```

When an agent's bash command produces multiple args from a message body (shell word-splitting on unquoted text, or subprocess argument handling), only the first segment survives. The rest is discarded with no warning.

The entire Python delivery pipeline (reply.py, delivery.py, create.py) handles multi-line strings correctly — the truncation happens at the CLI argument boundary.

## Why @memory Worked

@memory's reply body was a single properly-quoted argument that arrived as one `args[1]` entry. @hooks' body was split into multiple args (likely unquoted or shell-expanded), so only the first piece reached `send_reply()`.

## Fix

Both locations now join all remaining args:

1. **`email.py:handle_reply`**: `reply_message = " ".join(args[1:])`
2. **`send_args.py:parse_send_args`**: `message = " ".join(rest[1:])`

Backwards-compatible: single-arg messages pass through unchanged. Multi-arg messages are reconstructed.

## Tests Added (6)

- `test_reply.py`: `test_send_reply_multiline_body_preserved` — multi-line body stored intact in delivery and sent copy
- `test_email_module.py`: `TestHandleReplyMultiArg` — handle_reply joins split args; single arg unchanged
- `test_send_helpers.py`: 3 tests — parse_send_args joins split message; single arg unchanged; embedded newlines preserved

718 tests pass (712 + 6 new).
