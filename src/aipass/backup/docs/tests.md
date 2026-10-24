[<- Back to BACKUP](../README.md)

# Running the tests

How to run the backup suite, and what it needs from the host.

```bash
python -m pytest src/aipass/backup/tests -q
```

Run it from the **repo root**. From the branch directory the local `aipass/`
tree shadows the installed package, and the suite then tests something other
than what ships.

The count belongs to the run, not to this page: whatever pytest prints is the
truth of the moment. The same goes for how the cases divide across files —
`test_drive_pipeline.py` and `test_dead_cwd_imports.py` are heavily
parametrised, so case counts run well ahead of function counts there.

## What the suite is careful about

- **Live files.** `tests/conftest.py` sets `AIPASS_TEST_LOG_DIR` to a temp
  directory, and the audit trail (`handlers/audit/trail.py`) honours it, so a
  test run writes into a sandbox rather than the branch's own
  `logs/operations.jsonl`.
- **Real credentials.** No test may reach live OAuth: a help-gate test that
  patches only one lane lets `all` fall through to the machine's real Google
  credentials file. `TestNoWriteEscapesToRealSecrets` in
  `tests/test_cli_routing.py` pins that the `all` cycle never writes there.
- **The fence runs in fresh interpreters.** `tests/test_handlers_fence.py`
  copies `tests/support_fence.py` to foreign seats under `tmp_path` and runs it
  in a child process per case, because the fence only fires on a package's
  first import. See [the handlers fence](module_fence.md).
- **New test files.** They need permission by fleet policy. Editing an existing
  test file is normal work; adding one is a conversation with @devpulse first.

---

[<- Back to BACKUP](../README.md)
