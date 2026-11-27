# =================== AIPass ====================
# Name: header_version.py
# Description: Read an entry point's version from the # Version line of its file header
# Version: 1.0.0
# Created: 2026-11-25
# Modified: 2026-11-25
# =============================================

"""The one version an agent has: the # Version line of its file header, read as text."""

import itertools
import re
from pathlib import Path


def header_version(path: str | Path) -> str:
    """Return X.Y.Z from the first `# Version:` line of the file's leading comment block.

    Raises ValueError naming the file when the line is absent or not three integers.
    """
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    block = itertools.takewhile(lambda line: line.startswith("#"), lines)
    value = next((line.removeprefix("# Version:").strip() for line in block if line.startswith("# Version:")), None)
    if value is None or not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError(f"{path}: header has no '# Version: X.Y.Z' line (found {value!r})")
    return value
