"""Demo openhost app: a 500 page that links into an open-workspace provider.

A request handler intentionally raises a KeyError. The error page renders a
"Open a workspace at this commit" button whose href points at a deployed
provider of the `open-workspace` service — resolved at runtime via the
openhost router's service-discovery API — with the failing commit as `ref`.

Service discovery: GET {OPENHOST_ROUTER_URL}/api/services/v2/providers?service=...
returns the providers registered in this zone for the requested service. We
pick the default (or first) and construct a public URL as
`https://{provider_app_name}.{OPENHOST_ZONE_DOMAIN}{endpoint}?repo=…&ref=…`,
which is how openhost exposes every app's HTTP routes to the outside.

Contract: github.com/imbue-openhost/claude-code-container/services/open-workspace
"""

from __future__ import annotations

import html
import os
import subprocess
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import quote

import httpx

REPO_DIR = os.path.dirname(os.path.abspath(__file__))

ROUTER_URL = os.environ.get("OPENHOST_ROUTER_URL", "").rstrip("/")
APP_TOKEN = os.environ.get("OPENHOST_APP_TOKEN", "")
ZONE_DOMAIN = os.environ.get("OPENHOST_ZONE_DOMAIN", "").strip()

OPEN_WORKSPACE_SERVICE = (
    "github.com/imbue-openhost/claude-code-container/services/open-workspace"
)

# The clone URL passed to the provider. In a real app this would be the repo
# whose code produced the 500; for the demo, override via WORKSPACE_REPO_URL.
WORKSPACE_REPO_URL = os.environ.get(
    "WORKSPACE_REPO_URL",
    "https://github.com/imbue-openhost/workspace-link-example.git",
)


def _current_ref() -> str:
    """Pin the link to the exact commit running right now."""
    try:
        out = subprocess.check_output(
            ["git", "-C", REPO_DIR, "rev-parse", "HEAD"], text=True
        )
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "main"


CURRENT_REF = _current_ref()


def _resolve_provider() -> tuple[str, str] | None:
    """Ask the router which app provides open-workspace in this zone.

    Returns (app_name, endpoint) for the default provider (or the first listed
    if none is marked default), or None if discovery isn't available — e.g.
    when running outside an openhost zone, or no provider is installed.
    """
    if not ROUTER_URL or not APP_TOKEN:
        return None
    url = f"{ROUTER_URL}/api/services/v2/providers"
    try:
        resp = httpx.get(
            url,
            params={"service": OPEN_WORKSPACE_SERVICE},
            headers={"Authorization": f"Bearer {APP_TOKEN}"},
            timeout=5,
        )
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    providers = (resp.json() or {}).get("providers") or []
    if not providers:
        return None
    chosen = next((p for p in providers if p.get("is_default")), providers[0])
    if chosen.get("status") != "running":
        return None
    return chosen["app_name"], chosen["endpoint"]


def _build_link(provider: tuple[str, str] | None, repo: str, ref: str) -> str | None:
    """Public URL the user's browser will hit.

    Openhost exposes each app at `{app_name}.{zone_domain}`, so the provider's
    declared endpoint becomes `https://{app_name}.{zone}{endpoint}`. The
    open-workspace contract accepts `repo` + `ref` as query params on GET, so
    a plain <a href> suffices.
    """
    if provider is None or not ZONE_DOMAIN:
        return None
    app_name, endpoint = provider
    host = f"{app_name}.{ZONE_DOMAIN}"
    qs = f"repo={quote(repo, safe='')}&ref={quote(ref, safe='')}"
    return f"https://{host}{endpoint}?{qs}"


def buggy_handler() -> str:
    data = {"user": "alice"}
    # Bug: typo'd key — raises KeyError at request time.
    return f"hello, {data['username']}"


ERROR_PAGE = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>500 — Internal Server Error</title>
  <style>
    body {{ font-family: -apple-system, system-ui, sans-serif;
            max-width: 760px; margin: 3rem auto; padding: 0 1rem;
            color: #222; }}
    h1 {{ color: #b00020; margin-bottom: 0.25rem; }}
    .sub {{ color: #666; margin-bottom: 1.5rem; }}
    pre {{ background: #f5f5f5; padding: 1rem; border-radius: 6px;
           overflow-x: auto; font-size: 0.85rem; line-height: 1.4; }}
    a.debug {{ display: inline-block; margin-top: 1rem;
               background: #4f46e5; color: #fff; padding: 0.6rem 1rem;
               border-radius: 6px; text-decoration: none; font-weight: 600; }}
    a.debug:hover {{ background: #4338ca; }}
    .nolink {{ margin-top: 1rem; color: #888; font-style: italic; }}
  </style>
</head>
<body>
  <h1>500 — Internal Server Error</h1>
  <div class="sub">Something blew up handling <code>{path}</code>.</div>
  <pre>{traceback}</pre>
  {action}
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"ok")
            return

        try:
            body = buggy_handler()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))
        except Exception:
            tb = traceback.format_exc()
            link = _build_link(_resolve_provider(), WORKSPACE_REPO_URL, CURRENT_REF)
            if link is None:
                action = (
                    '<div class="nolink">No open-workspace provider is '
                    "available in this zone — install one to get a debug "
                    "link here.</div>"
                )
            else:
                action = (
                    f'<a class="debug" href="{html.escape(link, quote=True)}">'
                    "🛠  Open a workspace at this commit</a>"
                )
            page = ERROR_PAGE.format(
                path=html.escape(self.path),
                traceback=html.escape(tb),
                action=action,
            )
            self.send_response(500)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))

    def log_message(self, fmt: str, *args: object) -> None:
        print("[server]", fmt % args)


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(
        f"Serving on :{port}  ref={CURRENT_REF}  "
        f"zone={ZONE_DOMAIN or '<unset>'}  router={ROUTER_URL or '<unset>'}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
