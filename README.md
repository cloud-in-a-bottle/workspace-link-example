# workspace-link-example

A tiny openhost app that demonstrates how an error page can hand the user a
link straight into a working environment at the failing commit.

The request handler intentionally raises a `KeyError`. The 500 page renders an
HTML traceback plus an **"Open a workspace at this commit"** button. The button
URL is **not hard-coded** — it's resolved at runtime against the openhost zone
the app is deployed in:

1. The app asks the openhost router which apps provide the
   `open-workspace` service:

   ```
   GET {OPENHOST_ROUTER_URL}/api/services/v2/providers
       ?service=github.com/imbue-openhost/claude-code-container/services/open-workspace
   Authorization: Bearer {OPENHOST_APP_TOKEN}
   ```

2. The router replies with the providers registered in this zone (their
   `app_name`, `endpoint`, version, status, and which one is the default).

3. The app picks the default (or first running) provider and builds the
   user-facing URL as
   `https://{app_name}.{OPENHOST_ZONE_DOMAIN}{endpoint}?repo=…&ref=…`,
   which is how openhost routes traffic to any app in the zone.

4. `ref` is `git rev-parse HEAD` of the running checkout, so the link points
   at the exact commit that produced the 500.

If no provider is installed in the zone (or the app is running outside
openhost), the error page renders without the button instead of guessing a
URL.

## Manifest

[`openhost.toml`](./openhost.toml) declares:

- a container image (built from [`Dockerfile`](./Dockerfile)) on port 8000
- a `/health` route for the router
- consumption of the `open-workspace` service (no grants — the call is from
  the user's browser, not server-to-server)

## Run locally (outside openhost)

```
pip install httpx
python3 server.py
```

Then visit <http://localhost:8000/>. Without `OPENHOST_ROUTER_URL` /
`OPENHOST_APP_TOKEN` / `OPENHOST_ZONE_DOMAIN` set, you'll see the 500 page
without the button — the app refuses to guess a URL.

## Env vars

Injected by openhost when deployed:

- `OPENHOST_ROUTER_URL` — base URL of the router (for service discovery)
- `OPENHOST_APP_TOKEN` — bearer token authenticating this app to the router
- `OPENHOST_ZONE_DOMAIN` — zone domain used to build provider hostnames

App-specific:

- `WORKSPACE_REPO_URL` — clone URL passed to the provider (default the
  GitHub mirror of this repo)
- `PORT` — listen port (default `8000`)
