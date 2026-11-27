"""E2E HTTP contra los ocho servicios reales ya levantados por Docker Compose."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid

SERVICES = {
    "usuarios": "USUARIOS_URL",
    "productos": "PRODUCTOS_URL",
    "envios": "ENVIOS_URL",
    "inventario": "INVENTARIO_URL",
    "carrito": "CARRITO_URL",
    "pedidos": "PEDIDOS_URL",
    "pagos": "PAGOS_URL",
    "resenas": "RESENAS_URL",
}
DEFAULTS = {
    "usuarios": "http://127.0.0.1:8001",
    "productos": "http://127.0.0.1:8002",
    "envios": "http://127.0.0.1:8003",
    "inventario": "http://127.0.0.1:8004",
    "carrito": "http://127.0.0.1:8005",
    "pedidos": "http://127.0.0.1:8006",
    "pagos": "http://127.0.0.1:8007",
    "resenas": "http://127.0.0.1:8008",
}
BASE = {name: os.getenv(SERVICES[name], DEFAULTS[name]).rstrip("/") for name in SERVICES}
DIRECCION = {"codigo_postal": os.getenv("E2E_CODIGO_POSTAL", "06600"),
             "calle": "Prueba E2E", "ciudad": "CDMX", "estado": "CDMX"}
RESULTS: list[tuple[str, bool, str]] = []


class Response:
    def __init__(self, status: int, body: bytes, headers: object):
        self.status = status
        self.headers = headers
        try:
            self.json = json.loads(body.decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.json = None

    @property
    def data(self):
        return self.json.get("data") if isinstance(self.json, dict) else None


def request(service: str, method: str, path: str, *, body=None, token=None, key=None) -> Response:
    headers = {}
    payload = None
    if body is not None:
        payload = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if key:
        headers["Idempotency-Key"] = key
    req = urllib.request.Request(BASE[service] + path, data=payload, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return Response(response.status, response.read(), response.headers)
    except urllib.error.HTTPError as error:
        return Response(error.code, error.read(), error.headers)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def scenario(name: str, action) -> None:
    try:
        detail = action()
    except Exception as error:  # mantener resumen y ejecutar escenarios independientes
        RESULTS.append((name, False, f"{type(error).__name__}: {error}"))
    else:
        RESULTS.append((name, True, detail or "aserciones satisfechas"))


def is_uuid4(value: object) -> bool:
    try:
        return uuid.UUID(str(value)).version == 4
    except (ValueError, TypeError, AttributeError):
        return False


def main() -> int:
    email = os.getenv("E2E_EMAIL")
    password = os.getenv("E2E_PASSWORD")
    product_id = os.getenv("E2E_PRODUCT_ID")
    missing = [name for name, value in (("E2E_EMAIL", email), ("E2E_PASSWORD", password),
                                         ("E2E_PRODUCT_ID", product_id)) if not value]
    if missing:
        print("FALTA CONFIGURACION: " + ", ".join(missing))
        print("No se imprimen valores de credenciales.")
        return 2

    state: dict[str, object] = {"email": email, "password": password, "product": product_id}

    def preflight():
        for name, base in BASE.items():
            r = request(name, "GET", "/ready")
            require(r.status == 200, f"{name} /ready HTTP {r.status}")
        return "8/8 endpoints /ready HTTP 200"

    def register_login():
        r = request("usuarios", "POST", "/api/usuarios/registro",
                    body={"nombre": os.getenv("E2E_NOMBRE", "Prueba E2E"),
                          "correo": email, "contrasena": password})
        require(r.status == 201 and r.data, f"registro HTTP {r.status}")
        user_id = r.data.get("id")
        require(is_uuid4(user_id), "registro no devolvió usuario UUID v4")
        login = request("usuarios", "POST", "/api/usuarios/login",
                        body={"correo": email, "contrasena": password})
        require(login.status == 200 and login.data, f"login HTTP {login.status}")
        token = login.data.get("access_token")
        require(bool(token) and login.data.get("token_type") == "Bearer", "respuesta de login sin bearer JWT")
        state.update(uid=user_id, token=token)
        return "registro 201 y login 200 con JWT del API"

    def catalog_inventory():
        catalog = request("productos", "GET", "/api/productos?limite=100")
        require(catalog.status == 200 and catalog.data, f"catálogo HTTP {catalog.status}")
        items = catalog.data.get("items", []) if isinstance(catalog.data, dict) else catalog.data
        require(any(item.get("id") == product_id for item in items), "E2E_PRODUCT_ID no aparece en catálogo")
        stock = request("inventario", "GET", f"/api/inventario/{product_id}")
        require(stock.status == 200 and isinstance(stock.data, dict), f"inventario HTTP {stock.status}")
        require(isinstance(stock.data.get("disponibles"), int), "inventario sin disponibles entero")
        state["available_before"] = stock.data["disponibles"]
        require(stock.data["disponibles"] >= 1, "el producto E2E no tiene stock para compra")
        return f"catálogo contiene producto; disponibles={stock.data['disponibles']}"

    def review():
        token = state["token"]
        body = {"producto_id": product_id, "calificacion": 5, "comentario": "Reseña de integración E2E"}
        created = request("resenas", "POST", "/api/resenas", body=body, token=token)
        require(created.status == 201 and created.data, f"crear reseña HTTP {created.status}")
        listed = request("resenas", "GET", f"/api/resenas/producto/{product_id}")
        require(listed.status == 200 and listed.data, f"listar reseñas HTTP {listed.status}")
        reviews = listed.data.get("items", [])
        require(any(item.get("id") == created.data.get("id") and item.get("usuario_id") == state["uid"]
                    for item in reviews), "la reseña creada no está en la lista")
        return "reseña 201 y aparece en listado público"

    def quote_shipping():
        token = state["token"]
        quote = request("envios", "POST", "/api/envios/cotizar",
                        body={"codigo_postal": DIRECCION["codigo_postal"], "cantidad": 1}, token=token)
        require(quote.status == 200 and quote.data and float(quote.data["costo_envio"]) >= 0,
                f"cotización HTTP {quote.status}")
        state["quote"] = quote.data
        return f"cotización HTTP 200, {quote.data['dias_estimados']} días estimados"

    def add_to_cart():
        key = str(uuid.uuid4())
        require(is_uuid4(key), "Idempotency-Key generada no es UUID v4")
        r = request("carrito", "POST", f"/api/carrito/{state['uid']}/agregar",
                    body={"producto_id": product_id, "cantidad": 1}, token=state["token"], key=key)
        require(r.status == 200 and r.data, f"agregar al carrito HTTP {r.status}")
        state["cart_key"] = key
        return "carrito actualizado con Idempotency-Key UUID v4"

    def approved_purchase():
        available = state["available_before"]
        key = str(uuid.uuid4())
        require(is_uuid4(key), "Idempotency-Key de pedido no es UUID v4")
        body = {"direccion": DIRECCION, "metodo_pago": "tarjeta_simulada"}
        first = request("pedidos", "POST", "/api/pedidos", body=body, token=state["token"], key=key)
        require(first.status == 201 and first.data, f"crear pedido HTTP {first.status}")
        order = first.data
        require(order.get("estado") == "pagado", f"pedido no pagado: {order.get('estado')}")
        require(is_uuid4(order.get("pago_id")), "pedido no incluye pago_id UUID")
        require(bool(order.get("guia")), "pedido no incluye guía")
        replay = request("pedidos", "POST", "/api/pedidos", body=body, token=state["token"], key=key)
        require(replay.status == 201 and replay.data == order, "reintento no devolvió el mismo pedido")
        payment = request("pagos", "GET", f"/api/pagos/pedido/{order['id']}", token=state["token"])
        require(payment.status == 200 and payment.data and payment.data.get("estado") == "aprobado",
                f"pago no aprobado: HTTP {payment.status}")
        stock = request("inventario", "GET", f"/api/inventario/{product_id}")
        require(stock.status == 200 and stock.data["disponibles"] == available - 1,
                "inventario no descontó exactamente una unidad")
        cart = request("carrito", "GET", f"/api/carrito/{state['uid']}", token=state["token"])
        require(cart.status == 200 and cart.data and cart.data.get("items") == [], "carrito no quedó vacío")
        tracking = request("envios", "GET", f"/api/envios/rastreo/{order['guia']}", token=state["token"])
        require(tracking.status == 200 and tracking.data, f"rastreo HTTP {tracking.status}")
        state.update(order=order, purchase_key=key)
        return "pagado, pago_id, stock -1, carrito vacío, guía rastreable, reintento idéntico"

    def prepare_stock_competitor():
        local, separator, domain = email.rpartition("@")
        require(bool(separator), "E2E_EMAIL debe tener formato de correo")
        competitor_email = f"{local}+e2e-{uuid.uuid4().hex[:10]}@{domain}"
        registered = request("usuarios", "POST", "/api/usuarios/registro",
                             body={"nombre": "Prueba E2E stock", "correo": competitor_email,
                                   "contrasena": password})
        require(registered.status == 201 and registered.data, f"registro competidor HTTP {registered.status}")
        login = request("usuarios", "POST", "/api/usuarios/login",
                        body={"correo": competitor_email, "contrasena": password})
        require(login.status == 200 and login.data, f"login competidor HTTP {login.status}")
        uid = registered.data.get("id")
        token = login.data.get("access_token")
        require(is_uuid4(uid) and bool(token), "credenciales de usuario competidor inválidas")
        quantity = state["available_before"]
        added = request("carrito", "POST", f"/api/carrito/{uid}/agregar",
                        body={"producto_id": product_id, "cantidad": quantity}, token=token,
                        key=str(uuid.uuid4()))
        require(added.status == 200, f"agregar carrito competidor HTTP {added.status}")
        state.update(competitor_uid=uid, competitor_token=token, competitor_quantity=quantity)
        return f"segundo carrito creado antes del checkout; unidades={quantity}"

    def rejected_stock():
        token = state["competitor_token"]
        uid = state["competitor_uid"]
        key = str(uuid.uuid4())
        body = {"direccion": DIRECCION, "metodo_pago": "tarjeta_simulada"}
        rejected = request("pedidos", "POST", "/api/pedidos", body=body, token=token, key=key)
        errors = rejected.json.get("errors", {}) if isinstance(rejected.json, dict) else {}
        message = rejected.json.get("message", "") if isinstance(rejected.json, dict) else ""
        require(rejected.status == 409 and
                ("stock_insuficiente" in json.dumps(errors) or "inventario" in message.lower()),
                f"esperaba 409 de inventario, obtuvo HTTP {rejected.status}")
        history = request("pedidos", "GET", f"/api/pedidos/usuario/{uid}", token=token)
        require(history.status == 200 and isinstance(history.data, list), f"historial HTTP {history.status}")
        canceled = [order for order in history.data if order.get("estado") == "cancelado"
                    and order.get("metodo_pago") == "tarjeta_simulada"]
        require(bool(canceled), "no aparece pedido cancelado por stock en el historial")
        payment = request("pagos", "GET", f"/api/pagos/pedido/{canceled[0]['id']}", token=token)
        require(payment.status == 404, f"el pedido cancelado tiene comprobante de pago: HTTP {payment.status}")
        cart = request("carrito", "GET", f"/api/carrito/{uid}", token=token)
        require(cart.status == 200 and len(cart.data.get("items", [])) == 1,
                "el carrito debe conservar el artículo rechazado")
        return f"409 inventario insuficiente; unidades solicitadas {state['competitor_quantity']}; sin pago"

    def unauthorized():
        r = request("carrito", "GET", f"/api/carrito/{state['uid']}")
        require(r.status == 401, f"carrito sin token devolvió {r.status}, esperado 401")
        return "GET de carrito sin token devuelve 401"

    scenario("Preflight Docker Compose real", preflight)
    scenario("Registro/login de usuario JWT RS256", register_login)
    scenario("Catálogo e inventario reales", catalog_inventory)
    scenario("Reseña autenticada y listado", review)
    scenario("Cotización de envío", quote_shipping)
    scenario("Carrito con clave UUID v4", add_to_cart)
    scenario("Carrito competidor previo a checkout", prepare_stock_competitor)
    scenario("Compra aprobada, efectos y reintento idempotente", approved_purchase)
    scenario("Rechazo por stock sin cobro", rejected_stock)
    scenario("Acceso sin token", unauthorized)

    print("\nResumen E2E contra servicios reales")
    for name, ok, detail in RESULTS:
        print(f"{'OK' if ok else 'FAIL'} | {name} | {detail}")
    failures = sum(not ok for _, ok, _ in RESULTS)
    print(f"Resultado: {len(RESULTS) - failures}/{len(RESULTS)} escenarios OK; {failures} FAIL")
    print("Rate limit 429 no ejecutado: opcional por costo/tiempo y depende de los límites configurados en Compose.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
