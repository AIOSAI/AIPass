# =================== AIPass ====================
# Name: test_pattern_scan.py
# Description: Pattern audit — scan home dir, report what passes ignore patterns
# Version: 1.0.0
# Created: 2026-03-14
# Modified: 2026-03-14
# =============================================

"""
Pattern Audit Scan

Diagnostic tool — uses the same ignore patterns and scanner as the real backup
to show what would be backed up. Reports file counts and sizes per top-level
directory, flags large files and long paths.

Usage:
    python3 tests/test_pattern_scan.py
"""

from collections import defaultdict
from pathlib import Path

from rich.console import Console

from aipass.backup.apps.handlers.config.config_handler import (
    GLOBAL_IGNORE_PATTERNS,
    IGNORE_EXCEPTIONS,
    should_ignore,
    SOURCE_WHITELIST,
    MAX_FILE_SIZE_MB,
)
from aipass.backup.apps.handlers.operations.file_scanner import scan_files

console = Console()


def fmt_size(b: int) -> str:
    if b >= 1024 * 1024 * 1024:
        return f"{b / (1024**3):.1f} GB"
    if b >= 1024 * 1024:
        return f"{b / (1024**2):.1f} MB"
    if b >= 1024:
        return f"{b / 1024:.1f} KB"
    return f"{b} B"


def run_scan() -> None:
    source_dir = Path.home()
    large_file_threshold = 1 * 1024 * 1024  # 1MB

    console.print()
    console.print("[bold cyan]Pattern Audit Scan[/bold cyan]")
    console.print(f"  Source: {source_dir}")
    console.print(f"  Whitelist: {SOURCE_WHITELIST if SOURCE_WHITELIST else '(all directories)'}")
    console.print(f"  Max file size: {MAX_FILE_SIZE_MB} MB")
    console.print(f"  Large file threshold: {fmt_size(large_file_threshold)}")
    console.print()
    console.print("[dim]Scanning with current ignore patterns...[/dim]")

    ignore_patterns = GLOBAL_IGNORE_PATTERNS

    def check_ignore(path: Path) -> bool:
        return should_ignore(path, ignore_patterns, IGNORE_EXCEPTIONS)

    files, skipped = scan_files(source_dir, check_ignore,
                                whitelist=SOURCE_WHITELIST,
                                max_file_size_mb=MAX_FILE_SIZE_MB)

    # Aggregate by top-level directory
    dir_stats: dict[str, dict] = defaultdict(lambda: {"count": 0, "size": 0})
    large_files: list = []
    total_size = 0
    path_too_long: list = []

    for f in files:
        try:
            rel = f.relative_to(source_dir)
            top_dir = rel.parts[0] if len(rel.parts) > 1 else "(root files)"
            size = f.stat().st_size
            dir_stats[top_dir]["count"] += 1
            dir_stats[top_dir]["size"] += size
            total_size += size

            if size >= large_file_threshold:
                large_files.append((f, size))

            # Estimate backup path length
            estimated_path = len(str(f)) + 80
            if estimated_path > 260:
                path_too_long.append((f, estimated_path))
        except (OSError, ValueError):
            pass

    sorted_dirs = sorted(dir_stats.items(), key=lambda x: x[1]["size"], reverse=True)

    # Report: directories
    console.print()
    console.print(f"[bold cyan]Files passing ignore patterns: {len(files)}[/bold cyan]")
    console.print(f"[bold cyan]Total size: {fmt_size(total_size)}[/bold cyan]")
    console.print(
        f"[dim]Directories ignored: {len(skipped.get('directories', set()))} "
        f"| Files ignored: {len(skipped.get('files', set()))}[/dim]"
    )
    console.print()

    console.print("[yellow]Top directories by size:[/yellow]")
    for dir_name, stats in sorted_dirs[:25]:
        pct = (stats["size"] / total_size * 100) if total_size > 0 else 0
        size_str = fmt_size(stats["size"])
        color = "red" if pct > 20 else "yellow" if pct > 5 else "dim"
        console.print(
            f"  [{color}]{dir_name:<40} {stats['count']:>6} files  "
            f"{size_str:>10}  ({pct:.1f}%)[/{color}]"
        )

    if len(sorted_dirs) > 25:
        console.print(f"  [dim]... and {len(sorted_dirs) - 25} more directories[/dim]")

    # Report: large files
    if large_files:
        large_files.sort(key=lambda x: x[1], reverse=True)
        console.print()
        console.print(
            f"[yellow]Large files (>{fmt_size(large_file_threshold)}):[/yellow] "
            f"{len(large_files)} found"
        )
        for f, size in large_files[:20]:
            rel = f.relative_to(source_dir)
            console.print(f"  [red]{fmt_size(size):>10}[/red]  {rel}")
        if len(large_files) > 20:
            console.print(f"  [dim]... and {len(large_files) - 20} more[/dim]")

    # Report: path too long
    if path_too_long:
        console.print()
        console.print(
            f"[yellow]Path too long (>260 chars estimated):[/yellow] "
            f"{len(path_too_long)} found"
        )
        for f, length in path_too_long[:10]:
            rel = f.relative_to(source_dir)
            console.print(f"  [red]{length} chars[/red]  {rel}")
        if len(path_too_long) > 10:
            console.print(f"  [dim]... and {len(path_too_long) - 10} more[/dim]")

    # Report: files skipped by size cap
    too_large = skipped.get("too_large", set())
    if too_large:
        sorted_large = sorted(too_large, key=lambda x: x[1], reverse=True)
        console.print()
        console.print(
            f"[yellow]Skipped by size cap (>{MAX_FILE_SIZE_MB} MB):[/yellow] "
            f"{len(sorted_large)} files"
        )
        for rel_path, size in sorted_large[:20]:
            console.print(f"  [red]{fmt_size(size):>10}[/red]  {rel_path}")
        if len(sorted_large) > 20:
            console.print(f"  [dim]... and {len(sorted_large) - 20} more[/dim]")

    if not large_files and not path_too_long and not too_large:
        console.print()
        console.print("[green]No large files or long paths detected[/green]")

    console.print()


if __name__ == "__main__":
    run_scan()
