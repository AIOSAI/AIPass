[<- Back to BACKUP](../README.md)

# Restore — finding and recovering a version

`restore` reads the versioned store. It never writes into it, and it never
touches the source tree except at the output path you name.

## Naming the file

`restore` takes a bare filename or a path from the project root. A path names
exactly one file; a bare filename takes the first match the store walk meets, so
use the path when two files share a basename.

Until 2026-09-14 only the bare form worked: the lookup joined the whole argument
onto the matched folder and looked for `<store>/src/main.py/src/main.py`, which
never exists. Both the `--help` examples and this branch's own documentation
spelled the failing form. It is pinned now by
`test_find_file_folder_path_shaped` in `tests/test_versioned_engine.py`.

## Why the store layout decides the lookup

The versioned store wraps each file in a folder of its own name
(`handlers/path/builder.py`):

```
<store>/root/<name>/<name>        # a file at the project root
<store>/<parent>/<name>/<name>    # a nested file
```

so the folder and the file inside it share a name, and a lookup has to match the
folder by the path and the file by its basename. A name longer than 50
characters is shortened for the folder only (`<name[:30]>_<md5[:8]>`), which the
lookup does not reproduce.

## Subcommands

`list <file>` prints every version it holds: the current copy and the dated
baseline beside it, newest marked. `file <file> <output>` writes the current
version to the output path you give, creating parent directories as needed. A
failed restore says so and exits non-zero rather than leaving you with a
half-written file.

---

[<- Back to BACKUP](../README.md)
