from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import logging
from threading import Thread


class HealthRequestHandler(BaseHTTPRequestHandler):
    server_version = "RiskUAHealth/1.0"

    def do_GET(self) -> None:
        if self.path not in {"/", "/healthz"}:
            self.send_response(404)
            self.end_headers()
            return

        body = b"ok\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        logging.debug("Health check: " + format, *args)


@dataclass(frozen=True)
class HealthServer:
    server: ThreadingHTTPServer
    thread: Thread

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def shutdown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def start_health_server(port: int, host: str = "0.0.0.0") -> HealthServer:
    server = ThreadingHTTPServer((host, port), HealthRequestHandler)
    thread = Thread(
        target=server.serve_forever,
        name="riskua-health-server",
        daemon=True,
    )
    thread.start()
    return HealthServer(server=server, thread=thread)
