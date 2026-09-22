# Connection errors during publish

## Symptom

`docsync publish` fails with `ConnectionError: [Errno 61] Connection refused` or hangs for 30 seconds and then reports `timeout`.

## Cause

The publish step talks to the host configured in `publish.url`. A refused connection means nothing is listening at that address; a timeout usually means a firewall drops the packets.

## Fix

1. Check the URL: `docsync config get publish.url`.
2. Test reachability from the same machine: `curl -I <url>`.
3. If `curl` also fails, fix the host or firewall first. If `curl` works, run `docsync publish --debug` and look for a proxy variable (`HTTPS_PROXY`) that docsync picks up but `curl` ignores.
