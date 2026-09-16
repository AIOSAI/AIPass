# Known issues

*Open items in this branch, each one verified against live code before it was
written down. No command here is broken — these are places where a help page,
a docstring or a line of code disagrees with the truth.*

Re-verified 2026-09-15, when the README diet moved this list here. Three claims
this page used to carry were **false by then and are gone rather than moved**:
`aipass --help` no longer omits `feedback` and `handoff`, bare `aipass` no
longer omits `handoff`, and the `doctor --json` line that advertised "JSON
output for structure scan" is now `doctor --fix --json`, which is where JSON
actually comes from. `aipass init --help` does now document the
`init [target] [name]` scaffold form.

## Help text vs behaviour — the code is right, the help is wrong

- `aipass handoff --help` claims bare `aipass handoff` shows status; it prints
  the usage block instead. Status is `aipass handoff --info`.
- `aipass feedback --help` claims bare `aipass feedback` shows the current
  state; it prints module introspection instead. The real state lives with
  @hooks.
- `aipass init --help` documents neither `init agent <name>` nor the bare
  template form `init <template>`, and omits the `--style` flag that
  `init run` accepts — all three route in `init_flow.py`.

The `aipass --help` surface itself was diffed against bare `aipass` and against
the dispatcher on 2026-09-15 and now agrees with both.

## Stale docstring

- The module docstring of
  [`apps/handlers/init/bootstrap.py`](../apps/handlers/init/bootstrap.py) lists
  `.ai_mail.local/inbox.json` as scaffold step 9. No code in the file creates
  it — mailboxes are per-agent, inside `src/PKG/AGENT/`.

## Behaviour

- Running the entry point as a file (`python apps/aipass.py`) fails on package
  imports (`ModuleNotFoundError: No module named 'aipass.cli'`). Use the
  installed `aipass` entry point, which works from any directory.
- `aipass install --no-chat` returns from `_end_in_chat` before the doctor
  pre-flight runs, so the pre-flight is skipped along with the chat. It is
  announced rather than silent — the skip prints the command that runs it
  (`aipass doctor --fix`), by the FPLAN-0492 wave 6 ruling — and the same is
  true of the `--dry-run` and no-TTY paths.
- The concierge prompt `install` builds carries the resolved binary paths plus
  only the hooks / wire-verify doctor failures — not the full doctor verdict.
  Intended, and recorded here so the narrower scope is not mistaken for a bug.

## The test suite's one sharp edge

Run the suite from the branch directory or the repo root. From `src/aipass`
four tests fail: that cwd puts a local `aipass/` directory ahead of the
installed package, so the subprocess-based tests cannot resolve `aipass.aipass`
or `aipass.hooks`. Pre-existing and not a regression, proven by
restore-and-rerun on 2026-09-04; it is on the fix list, not a property of the
suite.

`pytest tests/` from here, or `pytest src/aipass/aipass/tests/` from the repo
root, prints the current count — which is why no count is written down here.

---

[← Back to the AIPASS README](../README.md)
