"""Serve synthetic OAuth hosts over real loopback HTTPS, including redirect chains."""
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from inboxstride_auth.ca import create_ca, issue
from mailhelp.web.http import Request, Response


class HttpsBrowser:
    def __init__(self, runtime, directory, width, wrap):
        self.dispatch = lambda request: Response.text(404, "Synthetic route missing")
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.respond()

            def do_POST(self):
                self.respond()

            def respond(self):
                path, _, query = self.path.partition("?")
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                answer = owner.dispatch(Request(self.command, path,
                    {key.lower(): value for key, value in self.headers.items()}, query, body))
                self.send_response(answer.status)
                self.send_header("Content-Type", answer.content_type)
                self.send_header("Content-Length", str(len(answer.body)))
                for key, value in answer.headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(answer.body)

            def log_message(self, *_args):
                pass

        create_ca(directory / "ca")
        issue(directory / "ca", directory / "certs", "localhost", server=True)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(directory / "certs/localhost.pem", directory / "certs/localhost.key")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.socket = tls.wrap_socket(self.server.socket, server_side=True)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        port = self.server.server_port
        self.browser = runtime.chromium.launch(channel="chrome", args=["--no-proxy-server",
            f"--host-resolver-rules=MAP * 127.0.0.1:{port}", "--js-flags=--no-compilation-cache"])
        # 8.7.11: German like every other UI context; on Ubuntu CI the host language was English.
        self.context = self.browser.new_context(ignore_https_errors=True, service_workers="block",
            locale="de-DE", timezone_id="Europe/Berlin",
            viewport={"width": width, "height": 900}, is_mobile=width < 1000, has_touch=width < 1000)
        self.page = wrap(self.context.new_page(), "desktop" if width > 1000 else "mobile")

    def close(self):
        self.page.collect()
        self.browser.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
