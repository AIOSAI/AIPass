"""
Memory JSON Handler Package

Provides two sub-modules:
    json_handler  -- Standard three-JSON logging (read_json, write_json, log_operation)
    memory_files  -- Memory file safe I/O (read_memory_file, write_memory_file, etc.)
"""

from .json_handler import (
    log_operation,
    read_json,
    write_json,
)

from .memory_files import (
    read_memory_file,
    write_memory_file,
    update_metadata,
    read_memory_file_data,
    write_memory_file_simple,
    validate_memory_file_structure,
)

__all__ = [
    # json_handler (three-JSON standard)
    "log_operation",
    "read_json",
    "write_json",
    # memory_files (memory file I/O)
    "read_memory_file",
    "write_memory_file",
    "update_metadata",
    "read_memory_file_data",
    "write_memory_file_simple",
    "validate_memory_file_structure",
]
