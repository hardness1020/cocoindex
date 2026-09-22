# `docsync setup` command reference

`docsync setup [OPTIONS]` creates or repairs the local workspace files without running a sync.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--config PATH` | path | `./docsync.toml` | Config file to create or validate. |
| `--output-dir PATH` | path | `./site` | Folder written into `output_dir` in the config. |
| `--force` | flag | off | Overwrite an existing config file. |
| `--quiet` | flag | off | Suppress the summary line. |

Exit codes: `0` on success, `2` when the config exists and `--force` was not given, `3` when `output_dir` is not writable.
