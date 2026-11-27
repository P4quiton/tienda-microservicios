"""Stubs minimos de Productos e Inventario (servicios aun inexistentes) para la prueba E2E.

Respetan docs/api/productos.yaml y docs/api/inventario.yaml solo en lo que consumen
Carrito y Pedidos. Estado en memoria; se arrancan nuevos en cada corrida.

Uso: python stub_server.py productos|inventario PUERTO
Las rutas /__test/* NO forman parte del contrato: solo siembran datos para la prueba.
"""
import hashlib
import json
import os
import re
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
PRECIO = re.compile(r"^\d{1,10}\.\d{2}$")
LOCK = threading.RLock()


def ok(data, status=200):
    return status, {"success": True, "message": "OK", "data": data}


def err(status, msg, errors=None):
    return status, {"success": False, "message": msg, "errors": errors or {}}


class Base(BaseHTTPRequestHandler):
    servicio = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # silencio; run.sh guarda stdout/stderr
        pass

    def _send(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw or b"{}")
        except ValueError:
            return None

    def _dispatch(self, method):
        path = self.path.split("?")[0]
        if path == "/health":
            return self._send(200, {"status": "ok", "service": self.servicio})
        if path == "/ready":
            return self._send(200, {"status": "ok", "service": self.servicio})
        body = self._body() if method in ("POST", "PUT", "PATCH") else None
        with LOCK:
            status, out = self.handle_api(method, path, body)
        self._send(status, out)

    def do_GET(self): self._dispatch("GET")
    def do_POST(self): self._dispatch("POST")
    def do_PUT(self): self._dispatch("PUT")


class Productos(Base):
    servicio = "api-productos"
    catalogo = {}

    def handle_api(self, method, path, body):
        if method == "POST" and path == "/__test/producto":
            pid = body.get("id") or str(uuid.uuid4())
            assert PRECIO.match(body["precio"])
            self.catalogo[pid] = {
                "id": pid, "nombre": body.get("nombre", "Producto"), "descripcion": "stub",
                "precio": body["precio"], "categoria": "e2e", "imagen_url": "http://localhost/img.png"}
            return ok(self.catalogo[pid], 201)
        if method == "GET" and path == "/api/productos":
            items = list(self.catalogo.values())
            return ok({"items": items, "total": len(items), "pagina": 1, "limite": 20})
        m = re.fullmatch(r"/api/productos/([^/]+)", path)
        if method == "GET" and m:
            p = self.catalogo.get(m.group(1))
            return ok(p) if p else err(404, "No encontrado")
        return err(404, "No encontrado")


class Inventario(Base):
    servicio = "api-inventario"
    stock = {}      # producto_id -> {"fisico": int, "reservado": int}
    reservas = {}   # pedido_id -> {"items": [...], "estado": str}
    idem = {}       # (operacion, clave) -> (huella, status, body)
    llamadas = []   # bitacora (operacion, pedido_id, clave) para las aserciones

    @classmethod
    def disponibles(cls, pid):
        s = cls.stock.get(pid)
        return max(0, s["fisico"] - s["reservado"]) if s else 0

    def _auth(self):
        esperado = os.environ["SERVICE_TOKEN_PEDIDOS_INVENTARIO"]
        recibido = self.headers.get("X-Service-Token")
        if not recibido or recibido != esperado:
            return err(401, "Credencial interna invalida")
        return None

    def handle_api(self, method, path, body):
        if method == "POST" and path == "/__test/stock":
            self.stock[body["producto_id"]] = {"fisico": int(body["fisico"]), "reservado": 0}
            return ok({"producto_id": body["producto_id"], "disponibles": self.disponibles(body["producto_id"])}, 201)
        if method == "GET" and path == "/__test/estado":
            return ok({"stock": self.stock, "reservas": self.reservas, "llamadas": self.llamadas})
        m = re.fullmatch(r"/api/inventario/([^/]+)", path)
        if method == "GET" and m and m.group(1) not in ("reservar", "confirmar", "liberar"):
            pid = m.group(1)
            return ok({"producto_id": pid, "disponibles": self.disponibles(pid)})
        if method == "POST" and path in ("/api/inventario/reservar", "/api/inventario/confirmar", "/api/inventario/liberar"):
            fallo = self._auth()
            if fallo:
                return fallo
            clave = self.headers.get("Idempotency-Key", "")
            if not UUID4.match(clave):
                return err(422, "Idempotency-Key UUID v4 obligatoria")
            return self._operar(path.rsplit("/", 1)[1], clave, body)
        return err(404, "No encontrado")

    def _operar(self, op, clave, body):
        if not isinstance(body, dict) or not UUID4.match(str(body.get("pedido_id", ""))):
            return err(422, "pedido_id invalido")
        extra = set(body) - ({"pedido_id", "items"} if op == "reservar" else {"pedido_id"})
        if extra:
            return err(422, "campos no declarados")
        pedido = body["pedido_id"]
        items = []
        if op == "reservar":
            raw = body.get("items")
            if not isinstance(raw, list) or not raw:
                return err(422, "items obligatorio")
            agg = {}
            for it in raw:
                if (not isinstance(it, dict) or set(it) != {"producto_id", "cantidad"}
                        or not UUID4.match(str(it["producto_id"]))
                        or not isinstance(it["cantidad"], int) or isinstance(it["cantidad"], bool) or it["cantidad"] < 1):
                    return err(422, "item invalido")
                agg[it["producto_id"]] = agg.get(it["producto_id"], 0) + it["cantidad"]
            items = [{"producto_id": k, "cantidad": v} for k, v in sorted(agg.items())]
        huella = hashlib.sha256(json.dumps([op, pedido, items], sort_keys=True).encode()).hexdigest()
        self.llamadas.append([op, pedido, clave])
        previo = self.idem.get((op, clave))
        if previo:
            return (previo[1], previo[2]) if previo[0] == huella else err(409, "Clave usada con otra solicitud")
        res = self._efecto(op, pedido, items)
        self.idem[(op, clave)] = (huella, res[0], res[1])
        return res

    def _efecto(self, op, pedido, items):
        r = self.reservas.get(pedido)
        if op == "reservar":
            if r:
                return ok(self._vista(pedido)) if r["items"] == items else err(409, "Reserva existente con otro contenido")
            for it in items:
                if self.disponibles(it["producto_id"]) < it["cantidad"]:
                    return err(409, "Stock insuficiente", {"producto_id": it["producto_id"]})
            for it in items:
                self.stock[it["producto_id"]]["reservado"] += it["cantidad"]
            self.reservas[pedido] = {"items": items, "estado": "reservada"}
            return ok(self._vista(pedido))
        if not r:
            return err(404, "Reserva inexistente")
        destino = "confirmada" if op == "confirmar" else "liberada"
        if r["estado"] == destino:
            return ok(self._vista(pedido))
        if r["estado"] != "reservada":
            return err(409, "Transicion incompatible")
        for it in r["items"]:
            s = self.stock[it["producto_id"]]
            s["reservado"] -= it["cantidad"]
            if destino == "confirmada":
                s["fisico"] -= it["cantidad"]
        r["estado"] = destino
        return ok(self._vista(pedido))

    def _vista(self, pedido):
        r = self.reservas[pedido]
        return {"pedido_id": pedido, "items": r["items"], "estado": r["estado"]}


if __name__ == "__main__":
    clase = {"productos": Productos, "inventario": Inventario}[sys.argv[1]]
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[2])), clase).serve_forever()
