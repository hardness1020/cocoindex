# Configuration options

`docsync.toml` has two sections. Start by setting `output_dir`; everything else has a default.

```toml
[project]
name = "my-docs"
output_dir = "./site"

[sync]
jobs = 4
ignore = ["**/drafts/**"]
```

`project.name` is used in the generated page titles. `project.output_dir` is where outputs are written; docsync deletes files there that no longer have a source. `sync.jobs` limits parallelism, and `sync.ignore` is a list of glob patterns to skip.

If you are unsure which values to use, copy the block above, run `docsync run`, and adjust from there.
