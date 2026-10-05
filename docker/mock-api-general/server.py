"""api-general simulada (solo biblioteca estándar) para desarrollo local y pruebas de contenedor.

Sirve `GET <cualquier prefijo>/internal/v1/notification-targets` con paginación por offset.
Uso: python server.py --port 8080 --users 25 --delay 0 --key local.clave-de-prueba
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

RUTA = "/internal/v1/notification-targets"


def usuarios(cantidad: int) -> list[dict]:
    return [
        {
            "recommendation_id": str(uuid.UUID(int=i)),
            "user_id": i,
            "nombre": f"Usuario {i}",
            "email": f"u{i}@example.com",
            "idioma": "es",
        }
        for i in range(1, cantidad + 1)
    ]


def crear_servidor(puerto: int, cantidad: int, demora: float, clave: str) -> ThreadingHTTPServer:
    todos = usuarios(cantidad)

    class Manejador(BaseHTTPRequestHandler):
        def _responder(self, estado: int, cuerpo: dict) -> None:
            datos = json.dumps(cuerpo).encode()
            self.send_response(estado)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            if url.path == "/health":
                return self._responder(200, {"status": "ok"})
            if not url.path.endswith(RUTA):
                return self._responder(404, {"error": "ruta"})
            if self.headers.get("X-Internal-API-Key") != clave:
                return self._responder(401, {"error": "clave"})
            consulta = parse_qs(url.query)
            tamano = int(consulta.get("page_size", ["100"])[0])
            desde = int(consulta.get("page_token", ["0"])[0])
            if demora:
                time.sleep(demora)
            siguiente = desde + tamano
            self._responder(
                200,
                {
                    "items": todos[desde:siguiente],
                    "next_page_token": str(siguiente) if siguiente < len(todos) else None,
                },
            )

        def log_message(self, *_args):
            pass

    return ThreadingHTTPServer(("0.0.0.0", puerto), Manejador)  # noqa: S104


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--users", type=int, default=25)
    parser.add_argument("--delay", type=float, default=0.0, help="segundos por pedido")
    parser.add_argument("--key", default="local.clave-de-prueba")
    args = parser.parse_args()
    print(f"api-general simulada en :{args.port} con {args.users} usuarios", flush=True)
    crear_servidor(args.port, args.users, args.delay, args.key).serve_forever()
