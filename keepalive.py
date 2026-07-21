"""Petit serveur HTTP pour satisfaire le health-check de Render.

Isolé dans son propre module : ce n'est pas une responsabilité du bot Discord
en tant que telle, donc ça ne doit pas polluer le fichier principal.
"""
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


class _KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Gestion en ligne !")

    def log_message(self, format, *args):
        pass  # on tait les logs HTTP, comme dans l'original


def _run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), _KeepAliveHandler)
    server.serve_forever()


def start_keepalive_server() -> None:
    threading.Thread(target=_run_web_server, daemon=True).start()
