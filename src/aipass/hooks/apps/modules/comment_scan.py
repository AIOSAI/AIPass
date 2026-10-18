# =================== AIPass ====================
# Name: comment_scan.py
# Version: 1.2.0
# Description: Comment budget counter: full-line comment share of a source file
# Branch: hooks
# Layer: apps/modules
# Created: 2026-10-16
# Modified: 2026-10-17
# =============================================

"""Counts a source file's full-line comment lines against the comment budget (docs/comments.md)."""

import io
import textwrap
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console
BUDGET_PERCENT = 10
MIN_BODY_LINES = 20

KINDS = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "c",
    ".tsx": "c",
    ".js": "c",
    ".jsx": "c",
    ".mjs": "c",
    ".cjs": "c",
    ".css": "c",
    ".scss": "c",
    ".sh": "shell",
    ".bash": "shell",
}

HASH_DIRECTIVES = ("!", "-*-", "noqa", "type:", "pyright:", "pragma", "fmt:", "ruff:", "pylint:", "seedgo:")
# The fleet json shim is a byte-identical copy checked by hash in every branch: no branch can trim it.
EXEMPT_PATHS = ("apps/handlers/json/json_handler.py",)
SLASH_DIRECTIVES = ("eslint-", "@ts-", "prettier-ignore")
_STATEMENT_START = {tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING}
_NOISE = {tokenize.NL, tokenize.COMMENT}


@dataclass
class Scan:
    """One file's count: body lines, comment lines, and the comment runs."""

    body: int
    comments: int
    runs: list[tuple[int, int]] = field(default_factory=list)

    @property
    def share(self) -> float:
        """Comment lines over body lines, 0.0 for an empty body."""
        return self.comments / self.body if self.body else 0.0

    @property
    def judged(self) -> bool:
        """False under MIN_BODY_LINES: a percentage has no meaning on a file that small."""
        return self.body >= MIN_BODY_LINES

    def over(self, budget: int = BUDGET_PERCENT) -> int:
        """Comment lines past the budget; zero or less is within it, and an unjudged file is never over."""
        return self.comments - self.body * budget // 100 if self.judged else 0

    def heaviest(self, count: int = 3) -> list[tuple[int, int]]:
        """The longest runs, longest first, earliest first among equals."""
        return sorted(self.runs, key=lambda run: (run[0] - run[1], run[0]))[:count]


def print_introspection() -> None:
    """Print module structure for drone routing."""
    CONSOLE.print("[bold cyan]comment_scan[/bold cyan] — full-line comment share against the comment budget")
    CONSOLE.print("[dim]Consumed by handlers/lifecycle/comment_budget.py and the comments verb.[/dim]")


def kind_of(path: str | Path) -> str | None:
    """The counter kind for *path*'s suffix, None when the budget does not judge it."""
    if Path(path).as_posix().endswith(EXEMPT_PATHS):
        return None
    return KINDS.get(Path(path).suffix.lower())


def _is_hash_directive(stripped: str) -> bool:
    """A `#` line that tells a tool something."""
    return stripped[1:].lstrip().startswith(HASH_DIRECTIVES)


def _header_lines(lines: list[str]) -> set[int]:
    """The AIPass header block's line numbers, empty when the file has none; a shebang or coding line may precede it."""
    start = 0
    while start < len(lines) and lines[start].startswith(("#!", "# -*-")):
        start += 1
    if start == len(lines) or not lines[start].startswith("# ===="):
        return set()
    header = set()
    for number, line in enumerate(lines[start:], start + 1):
        if not line.startswith("#"):
            break
        header.add(number)
    return header


def _python_by_lines(lines: list[str]) -> set[int]:
    """`#` lines, for text the tokenizer refuses (an edit's fragment)."""
    marked = set()
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#") and not _is_hash_directive(stripped):
            marked.add(number)
    return marked


def _python_comments(text: str, lines: list[str]) -> set[int]:
    """Comment lines and docstring lines past each docstring's first."""
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(textwrap.dedent(text)).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        logger.info("[HOOKS] comment_scan: tokenizer refused the text, counting # lines: %s", exc)
        return _python_by_lines(lines)
    marked = set()
    previous = tokenize.ENCODING
    for index, token in enumerate(tokens):
        row, col = token.start
        if token.type == tokenize.COMMENT:
            if not token.line[:col].strip() and not _is_hash_directive(token.string):
                marked.add(row)
        elif token.type == tokenize.STRING and previous in _STATEMENT_START:
            following = next((t.type for t in tokens[index + 1 :] if t.type not in _NOISE), tokenize.ENDMARKER)
            if following in (tokenize.NEWLINE, tokenize.ENDMARKER):
                marked.update(range(row + 1, token.end[0] + 1))
        if token.type not in _NOISE:
            previous = token.type
    return marked


def _c_line(stripped: str, in_block: bool) -> tuple[bool, bool]:
    """Whether one line is a comment, and whether a block comment is open after it."""
    if in_block:
        return True, "*/" not in stripped
    if stripped.startswith("//"):
        return not stripped[2:].lstrip().startswith(SLASH_DIRECTIVES), False
    if stripped.startswith(("/*", "{/*")):
        opened = stripped[stripped.index("/*") + 2 :]
        return not opened.lstrip().startswith("eslint"), "*/" not in opened
    return False, False


def _c_comments(lines: list[str]) -> set[int]:
    """`//` lines and every line of a block comment opened at a line's start."""
    marked = set()
    in_block = False
    for number, line in enumerate(lines, 1):
        is_comment, in_block = _c_line(line.strip(), in_block)
        if is_comment:
            marked.add(number)
    return marked


def scan(source: str | Path, kind: str) -> Scan:
    """Count *source* (a path to read, or the text itself) as *kind*."""
    text = source.read_text(encoding="utf-8", errors="replace") if isinstance(source, Path) else source
    lines = text.splitlines()
    header = _header_lines(lines) if kind in ("python", "shell") else set()
    if kind == "python":
        marked = _python_comments(text, lines)
    elif kind == "c":
        marked = _c_comments(lines)
    else:
        marked = _python_by_lines(lines)
    body = {n for n, line in enumerate(lines, 1) if line.strip()} - header
    comment_lines = sorted(marked & body)
    runs: list[tuple[int, int]] = []
    for number in comment_lines:
        if runs and runs[-1][1] == number - 1:
            runs[-1] = (runs[-1][0], number)
        else:
            runs.append((number, number))
    return Scan(body=len(body), comments=len(comment_lines), runs=runs)
