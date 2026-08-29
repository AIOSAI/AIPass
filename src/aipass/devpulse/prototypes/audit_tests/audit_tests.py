# =================== AIPass ====================
# Name: audit_tests.py - audit-tests lane CLI (MVP prototype)
# Description: CLI entry point - one scored hygiene gate, three nominate-only groups
# Version: 0.1.0
# Created: 2026-08-29
# =============================================

"""``audit-tests`` MVP prototype.

Usage is printed by ``--help``; the target directory is the one positional
argument and every flag below changes what gets measured.

Scores one group -- the filesystem-write hygiene gate -- and nominates suspects
in three static groups without scoring any of them.  Runs the target's suite
inside a scratch copy so measuring a branch never writes to it.

Exit codes:
    0  published, hygiene gate passed
    1  published, hygiene gate failed (out-of-sandbox writes convicted)
    2  refused - the harness could not prove it was entitled to publish
    3  refused - the target holds no pytest targets
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# A standalone script, deliberately: it must audit directories that are not
# aipass packages, so it never imports itself as ``aipass.*``.  Running it puts
# its own directory on sys.path, which is what resolves ``audit_tests_lib``.
from audit_tests_lib import discover, runner  # type: ignore[import-not-found]

EXIT_PASS, EXIT_GATE_FAILED, EXIT_REFUSED, EXIT_NO_TESTS = 0, 1, 2, 3


def emit(text: str, stream=None) -> None:
    """Write one block to the terminal.

    The report *is* this tool's output, not a debugging aside, so it goes to the
    stream explicitly rather than through anything that could be reconfigured
    into silence.
    """
    (stream or sys.stdout).write(text + "\n")


def build_parser() -> argparse.ArgumentParser:
    """The command line, with every flag that changes what gets measured."""
    parser = argparse.ArgumentParser(
        prog="audit_tests.py",
        description="Audit a pytest suite's hygiene, and nominate static suspects.",
    )
    parser.add_argument("target", type=Path, help="directory containing pytest targets")
    parser.add_argument("--out", type=Path, default=None, help="write the JSON artifact here")
    parser.add_argument("--keep-copy", action="store_true", help="keep the scratch copy for inspection")
    parser.add_argument("--env-root", type=Path, default=None, help="build the scratch copy here")
    parser.add_argument("--python", default=None, help="interpreter that owns the target's dependencies")
    parser.add_argument("--ruff", default=None, help="path to a ruff binary")
    parser.add_argument("--timeout", type=int, default=900, help="seconds allowed for the suite (default 900)")
    parser.add_argument(
        "--no-tmpdir-allowance",
        action="store_true",
        help="treat writes under TMPDIR outside pytest's basetemp as violations",
    )
    parser.add_argument(
        "--disable-hook",
        action="store_true",
        help="leave the audit hook off; the canary must then refuse the run (Law T10 seam)",
    )
    parser.add_argument("--baseline-passed", type=int, default=None, help="expected passing count, for the self-report")
    parser.add_argument("--no-static", action="store_true", help="skip the static nominators")
    parser.add_argument(
        "--copy-siblings",
        action="store_true",
        help="copy sibling packages instead of symlinking them, so no write can reach the real repo",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one audit and return the exit code the docstring above documents."""
    args = build_parser().parse_args(argv)
    options = runner.Options(
        target=args.target,
        out=args.out,
        keep_copy=args.keep_copy,
        env_root=args.env_root,
        python=args.python,
        ruff=args.ruff,
        timeout=args.timeout,
        tmpdir_allowed=not args.no_tmpdir_allowance,
        disable_hook=args.disable_hook,
        baseline_passed=args.baseline_passed,
        skip_static=args.no_static,
        copy_siblings=args.copy_siblings,
    )
    try:
        document, text = runner.execute(options)
    except discover.NoTestsError as exc:
        emit(f"audit-tests REFUSES: {exc}", sys.stderr)
        raise SystemExit(EXIT_NO_TESTS) from exc

    emit(text)
    if args.out:
        emit(f"\nartifact: {args.out}")
    if document["status"] == "refused":
        return EXIT_REFUSED
    return EXIT_PASS if document["groups"]["hygiene"]["passed"] else EXIT_GATE_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
