# Getting started

This guide takes you from an empty folder to a running sync in about five minutes.

1. Install the CLI: `pip install docsync`.
2. Create a project: `docsync init my-docs`. This writes a `docsync.toml` with sensible defaults.
3. Add a source folder: `docsync source add ./content`.
4. Run the first sync: `docsync run`. The command scans `./content`, writes the outputs to `./site`, and prints a summary.
5. Open `./site/index.html` in a browser to check the result.

To keep the output fresh while you edit, run `docsync run --watch` instead of step 4.
