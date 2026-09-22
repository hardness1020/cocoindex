# CLI reference

All commands accept `--config PATH` to point at a different `docsync.toml`.

## `docsync run`

Scan every configured source and write the outputs.

- `--watch`: keep running and re-sync when a source file changes.
- `--release`: minify assets and skip pages marked `draft = true`.
- `--jobs N`: number of files processed in parallel. Default: number of CPUs.

## `docsync source`

- `add PATH`: register a source folder.
- `remove PATH`: unregister a source folder. Outputs from it are deleted on the next run.
- `list`: print registered sources, one per line.

## `docsync doctor`

Check the Python version, the config file, and write access to `output_dir`. Exit code is `0` when every check passes.
