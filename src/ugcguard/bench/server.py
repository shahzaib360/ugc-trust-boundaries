"""A local multi-origin web server for the benchmark.

One server serves every ``*.test`` origin, dispatching on the request's host.
The browser uses this server as its HTTP proxy, so pages see real, distinct
origins with ordinary URLs (``http://shop.test/p/lumen-x2``) while no traffic
leaves the machine.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .render import SITES, Injection
from .world import WorldState, build_content


@dataclass
class Episode:
    variant: str = "schema"
    injections: list[Injection] = field(default_factory=list)
    state: WorldState = field(default_factory=WorldState)


class BenchServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 0, seed: int = 0):
        self.content = build_content(seed)
        self.episode = Episode()
        self.lock = threading.Lock()
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # silence
                pass

            def _target(self):
                """(site, split url). Works for proxy-style absolute request targets too."""
                url = urlsplit(self.path)
                if url.scheme and url.hostname:
                    return url.hostname.lower(), url
                return (self.headers.get("Host") or "").split(":")[0].lower(), url

            def _send(self, code: int, body: str = "", location: str | None = None):
                data = body.encode("utf-8")
                self.send_response(code)
                if location:
                    self.send_header("Location", location)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def _handle(self, method: str):
                site, url = self._target()
                if url.path == "/favicon.ico":
                    return self._send(404, "")
                full = f"http://{site}{url.path}" + (f"?{url.query}" if url.query else "")
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
                form = {k: v[0] for k, v in parse_qs(raw).items()}
                ep = server.episode
                with server.lock:
                    ep.state.visits.append(full)
                    if site == "evil.test":
                        ep.state.attacker_log.append(
                            {"method": method, "path": url.path, "query": url.query, "body": raw}
                        )
                    if method == "POST":
                        loc = server.post(site, url.path, form, self.headers.get("Referer"))
                        if loc is not None:
                            return self._send(303, "", loc)
                render = SITES.get(site)
                if render is None:
                    return self._send(404, "<h1>Unknown site</h1>")
                html = render(url.path, server.content, ep.state, ep.variant, ep.injections)
                if html is None:
                    return self._send(404, "<h1>Not found</h1>")
                return self._send(200, html)

            def do_GET(self):  # noqa: N802
                self._handle("GET")

            def do_POST(self):  # noqa: N802
                self._handle("POST")

        self.httpd = ThreadingHTTPServer((host, port), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self) -> BenchServer:
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    @property
    def proxy(self) -> str:
        """Point the browser's HTTP proxy here; every http://*.test URL then resolves locally."""
        return f"http://127.0.0.1:{self.port}"

    @staticmethod
    def url(site: str, path: str = "/") -> str:
        return f"http://{site}{path}"

    def reset(self, variant: str, injections: list[Injection] | None = None) -> WorldState:
        with self.lock:
            self.episode = Episode(variant=variant, injections=list(injections or []))
            return self.episode.state

    # ------------------------------------------------------------ mutations
    def post(self, site: str, path: str, form: dict, referer: str | None) -> str | None:
        st = self.episode.state
        back = urlsplit(referer).path if referer else "/"
        if path == "/account/settings":
            changed = {k: form[k] for k in ("email", "phone", "address") if k in form}
            st.settings_changes.append(dict(changed, site=site))
            st.account.update(changed)
            return "/account/settings"
        if path == "/account/delete":
            st.account["deleted"] = True
            return "/account/settings"
        if site == "shop.test":
            if path == "/cart/add":
                st.cart.append(form.get("slug", ""))
                return "/cart"
            if path == "/order":
                st.orders.append(
                    {
                        "items": list(st.cart),
                        "name": form.get("name"),
                        "address": form.get("address"),
                    }
                )
                st.cart.clear()
                return f"/order/{len(st.orders)}"
            if path.startswith("/review/") and path.endswith("/helpful"):
                st.votes.append(path.split("/")[2])
                return back
            if path.startswith("/p/") and path.endswith("/review"):
                where = path[: -len("/review")]
                st.posts.append({"site": site, "where": where, "text": form.get("body", "")})
                return where
        if site == "forum.test":
            if path.startswith("/t/") and path.endswith("/reply"):
                where = path[: -len("/reply")]
                st.posts.append({"site": site, "where": where, "text": form.get("body", "")})
                return where
            if path.startswith("/post/") and path.endswith("/like"):
                st.votes.append(path.split("/")[2])
                return back
        if site == "news.test":
            if path.startswith("/a/") and path.endswith("/comment"):
                where = path[: -len("/comment")]
                st.posts.append({"site": site, "where": where, "text": form.get("body", "")})
                return where
            if path == "/newsletter":
                st.signups.append(form.get("email", ""))
                return "/thanks"
        if site == "travel.test":
            if path == "/book":
                st.bookings.append(dict(form))
                return f"/booking/{len(st.bookings)}"
            if path.startswith("/h/") and path.endswith("/review"):
                where = path[: -len("/review")]
                st.posts.append({"site": site, "where": where, "text": form.get("body", "")})
                return where
        return None
