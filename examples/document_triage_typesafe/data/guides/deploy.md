# Deploying to production

This guide covers publishing the generated site to a production host.

1. Build the site with `docsync run --release`. Release mode minifies assets and strips draft pages.
2. Upload the `site/` folder to your host.

TODO: document the CDN cache invalidation step and the rollback procedure.
