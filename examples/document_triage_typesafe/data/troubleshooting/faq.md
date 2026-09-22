# Frequently asked questions

**Why does the output folder contain files I deleted from the source?**
Run `docsync run` again. Deleted sources are cleaned up on the next sync, not immediately.

**Can I use a different config file?**
Yes. Every command accepts `--config PATH`.

**What does `--jobs` control?**
The number of files processed in parallel. The default is the number of CPUs.

**Why is `draft = true` ignored?**
Drafts are only skipped in release mode. Pass `--release`.
