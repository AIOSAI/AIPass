# `audit-tests` — MVP prototype

**Campaign:** FPLAN-0458 / DPLAN-0320 · **Spec:** `docs.local/test_quality/DESIGN_BRIEF.md`
**Status:** prototype. Runnable, calibrated on four live branches, not wired into any lane.

Grades a pytest suite. One group is scored — the filesystem-write **hygiene gate** — and three
static groups **nominate suspects without scoring anything**. Two further groups are enumerated
and reported `not_applicable`, because a group list that shrinks is a score that inflates.

Stdlib only. `ruff` is used through `subprocess` when present and its absence is reported as
`not_applicable`, never as zero.

## Run it

```
python3 audit_tests.py <target-dir> [--out artifact.json] [--keep-copy]
```

Useful flags:

| Flag | Why |
|---|---|
| `--copy-siblings` | copy sibling packages instead of symlinking them. Slower, and the only mode in which no write can reach the real repo. |
| `--baseline-passed N` | records whether the suite produced its known passing count, in the harness self-report. |
| `--no-tmpdir-allowance` | treats writes under TMPDIR outside pytest's own tmp tree as violations. |
| `--disable-hook` | leaves the audit hook off. The canary must then refuse the run — this is the seam that proves the gate can fire. |
| `--timeout N` | seconds for the suite. Real branches take 1–3 minutes; the default is 900. |

Exit codes: `0` published and clean · `1` published, gate failed · `2` refused · `3` no pytest targets.

## What it does, in order

1. **Refuse early** if the target holds no pytest files.
2. **Copy first** (Law M10). Branch → `<env>/src/aipass/<name>`, siblings symlinked or copied,
   `PYTHONPATH` ahead of the editable install's `.pth` so `aipass.<name>` resolves to the copy.
3. **Prove the copy is what runs** — import the target in a child and check `__file__` is under the
   env, before anything is measured (harness check #3).
4. **Run the suite gated**, one branch and one path argument, so pytest's rootdir lands on the
   branch's own `pytest.ini` — the configuration every agent actually uses, and the one in which the
   repo-root forgery guard is *not* loaded.
5. **Fire the canary.** The plugin writes one deliberate out-of-sandbox file and checks its own gate
   caught it. If not, the entire run refuses: `status: refused`, exit 2, no group published.
6. **Nominate statically** over the copy — ruff `PT`, self-skip, mock-drift. Suspects, never verdicts.
7. **Publish**, with the harness's verdict on itself attached.

## The sandbox, declared

Every allowance is in `plugin/audit_hygiene_plugin.py::ALLOWANCES` and copied verbatim into the
artifact. Precedence matters and is the point: **anything inside the copied tree is a violation
before any tmp allowance is consulted**, because the scratch copy usually lives under TMPDIR and
either tmp rule checked first would acquit exactly the writes the gate exists to catch.

## Layout

```
audit_tests.py                    CLI
audit_tests_lib/envcopy.py        the copy, the liveness assertion, tree fingerprints
audit_tests_lib/hygiene.py        runs the gated suite, reads the plugin's log
audit_tests_lib/discover.py       pytest discovery and the no-tests refusal
audit_tests_lib/astutil.py        string folding, subject identification, machine reads
audit_tests_lib/modmap.py         import-free dotted-name resolution
audit_tests_lib/static_skip.py    SELF-SKIP / SKIP-ON-DRIFT nominator (T7)
audit_tests_lib/static_mock.py    MOCK-DRIFT nominator (T11)
audit_tests_lib/static_ruff.py    ruff PT family
audit_tests_lib/artifact.py       artifact assembly and the S1–S5 validator
audit_tests_lib/render.py         terminal summary
plugin/audit_hygiene_plugin.py    the pytest plugin; env-var configured, no package imports
tests/                            the prototype's own suite
artifacts/                        calibration artifacts from live branches
```

## Not built here

`oracle_execution` and `ai_advisory` are enumerated and `not_applicable` with the reason
`not built in MVP`. Layer 2 (per-suite snapshot diff, for the C-extension and subprocess blind
spots), Layer 3 (Landlock) and caching are also absent — the artifact stamps
`cache: none (MVP always runs live)`.

## Declared deviations from the seedgo checklist

12 of the 15 modules pass all 34 standards. Three findings remain, each a real conflict rather
than an omission, and each stated here rather than bypassed:

| File | Standard | Why it stands |
|---|---|---|
| `audit_tests_lib/logsetup.py`, `plugin/audit_hygiene_plugin.py` | `log_visibility` | The standard requires prax's `system_logger`, which means importing aipass code. This tool is stdlib-only by mandate — it must audit directories that are not aipass packages — and the plugin is injected into a *copy* of another branch, where importing the real repo's prax would be the instrument reaching back into the tree it is measuring (Law M10). The `getLogger` call is concentrated in these two files so the deviation is countable. |
| `plugin/audit_hygiene_plugin.py` | `trigger` | Same import problem, plus firing fleet events from inside a measured suite would make the gate a participant in what it measures. The one `unlink` is the canary sentinel this plugin created seconds earlier inside the scratch copy. |
| `audit_tests_lib/static_skip.py` | `naming` | `ast.NodeVisitor` dispatches on `"visit_" + type(node).__name__`. `visit_Assign`, `visit_If` and `visit_While` are the only names the stdlib will ever call. |
