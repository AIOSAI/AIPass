"""Pytest configuration for backup branch.

Excludes backup data directories from test collection to prevent
pytest from recursing into system_snapshot and versioned_backup
which contain full copies of the AIPass repo tree.
"""

collect_ignore_glob = [
    "backups/*",
]
