# Setting up a workspace

Follow these steps once per machine to prepare a docsync workspace.

1. Install Python 3.11 or newer and confirm it with `python --version`.
2. Create a virtual environment: `python -m venv .venv` and activate it.
3. Install docsync inside the environment: `pip install docsync`.
4. Copy `docsync.example.toml` to `docsync.toml` and set `output_dir` to the folder you want to publish.
5. Run `docsync doctor`. It checks the Python version, the config file, and write access to `output_dir`.

When `doctor` prints `all checks passed`, the workspace is ready. Continue with the getting-started guide to run your first sync.
