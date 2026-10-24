[<- Back to BACKUP](../README.md)

# Restore — finding and recovering a version

`restore` reads the versioned store. It never writes into it, and it never
touches the source tree except at the output path you name.

## Naming the file

`restore` takes a bare filename or a path from the project root. A path names
exactly one file; a bare filename takes the first match the store walk meets, so
use the path when two files share a basename. The path form is pinned by
`test_a_relative_path_restores_the_right_one_of_two_same_named_files` in
`tests/test_versioned_engine.py`.

## Why the store layout decides the lookup

The versioned store wraps each file in a folder of its own name
(`handlers/path/builder.py`):

```
<store>/root/<name>/<name>             # a file at the project root
<store>/<parent>/<name>/<name>         # a nested file
<store>/root/root/<parent>/<name>/<name> # a file under the project's own root/ folder
```

so the folder and the file inside it share a name, and a lookup has to match the
folder by the path and the file by its basename.

A project folder named `root/` is nested one level under the store's `root/`, so
`x.py` and `root/x.py` never share a folder. A store written by an earlier
release can still hold versions of a `root/` file one level up, at
`<store>/root/<rest of the path>/<name>/`, where `root/x.py` shared a folder with
`x.py`. Once the nested folder holds a current copy, lookup by path answers with
it, so those older versions stay in the store and are reached by browsing it,
not through `restore`.

A name longer than 50
characters is shortened for the folder only (`<name[:30]>_<md5[:8]>`). The
lookup (`_find_file_folder()` in `modules/restore.py`) asks the builder where a
name would be written rather than re-deriving the layout, so a long name is
found under its hashed folder, by path or by bare name.

## Subcommands

`list <file>` prints every version the file-folder holds: the baseline, the
current copy (marked `*`), and one row per dated diff in `<name>_diffs/`.
`file <file> <output>` copies the current version to the output path you give,
creating parent directories as needed; diffs are listed, not replayed. A file
the store does not hold, or a folder with no readable current copy, is named on
stderr, nothing is written, and the verb exits non-zero.

---

[<- Back to BACKUP](../README.md)
