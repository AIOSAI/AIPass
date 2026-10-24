# =================== AIPass ====================
# Name: parser.py
# Description: Parses drone command output (ANSI, line endings, module names)
# Version: 1.0.1
# Created: 2026-03-07
# Modified: 2026-10-24
# =============================================

"""
Parser handler for drone command output.
"""

import re


def parse_output(raw_output):
    """Clean up raw drone command output (ANSI codes, line endings, blank runs)."""
    if not raw_output:
        return ""

    ansi_pattern = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
    cleaned = ansi_pattern.sub("", raw_output)

    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")

    lines = cleaned.split("\n")
    lines = [line.rstrip() for line in lines]

    result_lines = []
    prev_blank = False
    for line in lines:
        is_blank = len(line.strip()) == 0
        if is_blank and prev_blank:
            continue
        result_lines.append(line)
        prev_blank = is_blank

    result = "\n".join(result_lines).strip()

    return result


def extract_modules(systems_output):
    """Parse `drone systems` output into a list of module names."""
    if not systems_output:
        return []

    cleaned = parse_output(systems_output)
    lines = cleaned.split("\n")

    modules = []
    for line in lines:
        line = line.strip()

        if not line:
            continue

        if line.startswith("---") or line.startswith("==="):
            continue
        if line.lower().startswith("registered") or line.lower().startswith("available"):
            continue

        # Accepted shapes: "name", "[OK] name", "* name", "@name".
        cleaned_line = line
        cleaned_line = re.sub(r"^\[.*?\]\s*", "", cleaned_line)  # [OK], [ERR], etc.
        cleaned_line = re.sub(r"^[*\-+]\s*", "", cleaned_line)  # bullet points
        cleaned_line = cleaned_line.lstrip("@")  # @ prefix

        parts = cleaned_line.split()
        if parts:
            module_name = parts[0].strip()
            if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", module_name):
                modules.append(module_name)

    return modules
