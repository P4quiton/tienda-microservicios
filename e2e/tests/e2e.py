"""Escenarios E2E "como cliente" por HTTP real contra Carrito, Pedidos, Pagos y Envios.

Se ejecuta desde run.sh con el Python del venv de Envios (necesita PyJWT + cryptography) y las variables
exportadas en e2e/.tmp/env.sh. Cada escenario afirma codigos y cuerpos REALES y imprime lo observado.
Resultado por escenario: OK (todas las comprobaciones), FALLA, o NO VERIFICADO (no se pudo comprobar).
"""
import base64
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import jwt

E2E = Path(__file__).resolve().parent.parent
TMP = E2E / ".tmp"
ENV = os.environ
PRIV = (TMP / "jwt-private.pem").read_text()
PRIV_AJENA = (TMP / "jwt-private-ajena.pem").read_text()

URL = {
    "productos": "http://127.0.0.1:8002", "envios": "http://127.0.0.1:8003", "inventario": "http://127.0.0.1:8004",
    "carrito": "http://127.0.0.1:8005", "pedidos": "http://127.0.0.1:8006", "pagos": "http://127.0.0.1:8007",
}
PROXY_PAGOS, PROXY_CARRITO = "http://127.0.0.1:8108", "http://127.0.0.1:8106"
DIR = {"cp": "06600", "calle": "Calle E2E 1", "ciudad": "CDMX", "estado": "CDMX"}
DIRECCION = {"codigo_postal": DIR["cp"], "calle": DIR["calle"], "ciudad": DIR["ciudad"], "estado": DIR["estado"]}
UUID4 = "^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"


# ------------------------------------------------------------------ HTTP / JWT / utilidades
class R:
    def __init__(self, status, text, headers, seg):
        self.status, self.text, self.headers, self.seg = status, text, headers, seg
        try:
            self.json = json.loads(text)
        except (ValueError, TypeError):
            self.json = None

    @property
    def data(self):
        return self.json.get("data") if isinstance(self.json, dict) else None

    def __repr__(self):
        t = self.text if len(self.text) < 260 else self.text[:260] + "..."
        return f"HTTP {self.status} {t}"


def http(method, url, body=None, headers=None, token=None, service=None, timeout=40, raw=None):
    h = dict(headers or {})
    if token:
        h["Authorization"] = "Bearer " + token
    if service:
        h["X-Service-Token"] = service
    data = raw
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as x:
            return R(x.status, x.read().decode(), dict(x.headers), time.time() - t0)
    except urllib.error.HTTPError as e:
        return R(e.code, e.read().decode(), dict(e.headers), time.time() - t0)
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        return R(0, f"SIN RESPUESTA: {e}", {}, time.time() - t0)


def firmar(sub, role="cliente", key=None, **cambios):
    ahora = int(time.time())
    claims = {"sub": sub, "role": role, "iss": "api-usuarios", "aud": "tienda-microservicios",
              "iat": ahora - 5, "exp": ahora + 900}
    claims.update(cambios)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key or PRIV, algorithm="RS256")


def nuevo_usuario(role="cliente"):
    u = str(uuid.uuid4())
    return u, firmar(u, role)


def idem():
    return {"Idempotency-Key": str(uuid.uuid4())}


def sql(db, user, pw_var, query):
    out = subprocess.run(
        ["docker", "exec", "-e", "PGPASSWORD=" + ENV[pw_var], "mojarra-pg-e2e", "psql", "-h", "127.0.0.1",
         "-U", user, "-d", db, "-Atc", query], capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip())
    return out.stdout.strip()


def pagos_db(where="true"):
    return sql("db_pagos", "usr_pagos", "PW_PAGOS", f"select count(*) from pagos where {where}")


def guia_de(pedido_id):
    return sql("db_envios", "usr_envios", "PW_ENVIOS", f"select guia from envios where pedido_id='{pedido_id}'")


def n_guias(pedido_id):
    return sql("db_envios", "usr_envios", "PW_ENVIOS", f"select count(*) from envios where pedido_id='{pedido_id}'")


def svc(accion, nombre):
    r = subprocess.run([str(E2E / "servicios.sh"), accion, nombre], capture_output=True, text=True, timeout=180)
    return r.returncode, (r.stdout + r.stderr).strip()


def proxy(base, **cfg):
    return http("POST", base + "/modo", cfg).json


def nuevo_producto(precio, stock):
    pid = str(uuid.uuid4())
    assert http("POST", URL["productos"] + "/__test/producto", {"id": pid, "precio": precio}).status == 201
    assert http("POST", URL["inventario"] + "/__test/stock", {"producto_id": pid, "fisico": stock}).status == 201
    return pid


def set_stock(pid, fisico):
    http("POST", URL["inventario"] + "/__test/stock", {"producto_id": pid, "fisico": fisico})


def inv():
    return http("GET", URL["inventario"] + "/__test/estado").data


def disponibles(pid):
    return http("GET", f"{URL['inventario']}/api/inventario/{pid}").data["disponibles"]


def agregar(uid, tok, pid, cant, clave=None):
    return http("POST", f"{URL['carrito']}/api/carrito/{uid}/agregar", {"producto_id": pid, "cantidad": cant},
                {"Idempotency-Key": clave or str(uuid.uuid4())}, token=tok)


def carrito(uid, tok):
    return http("GET", f"{URL['carrito']}/api/carrito/{uid}", token=tok)


def comprar(tok, clave, metodo="tarjeta_simulada", direccion=None, timeout=60):
    return http("POST", URL["pedidos"] + "/api/pedidos", {"direccion": direccion or DIRECCION, "metodo_pago": metodo},
                {"Idempotency-Key": clave}, token=tok, timeout=timeout)


def pedido(pid, tok=None, service=None):
    return http("GET", f"{URL['pedidos']}/api/pedidos/{pid}", token=tok, service=service)


def compra_pagada(cant=1, precio="10.00"):
    """Crea usuario+producto, agrega al carrito y compra con tarjeta aprobada. Devuelve dict de contexto."""
    uid, tok = nuevo_usuario()
    p = nuevo_producto(precio, 20)
    assert agregar(uid, tok, p, cant).status == 200
    clave = str(uuid.uuid4())
    r = comprar(tok, clave)
    assert r.status == 201 and r.data["estado"] == "pagado", r
    return {"uid": uid, "tok": tok, "producto": p, "clave": clave, "pedido": r.data, "id": r.data["id"],
            "guia": guia_de(r.data["id"])}


# ------------------------------------------------------------------ registro de resultados
RESULTADOS = []
CTX = {}


class Escenario:
    def __init__(self, num, titulo):
        self.num, self.titulo, self.fallos, self.nv = num, titulo, 0, []

    def check(self, desc, cond, observado=""):
        marca = "ok   " if cond else "FALLA"
        if not cond:
            self.fallos += 1
        obs = observado if isinstance(observado, str) else repr(observado)
        print(f"   [{marca}] {desc}" + (f"  <- {obs}" if obs != "" else ""))
        return cond

    def no_verificado(self, motivo):
        self.nv.append(motivo)
        print(f"   [NO VERIFICADO] {motivo}")

    def nota(self, texto):
        print(f"   [nota ] {texto}")


def escenario(num, titulo):
    def deco(fn):
        def run():
            print(f"\n=== Escenario {num}: {titulo}")
            s = Escenario(num, titulo)
            try:
                fn(s)
            except Exception:  # un fallo del propio escenario es FALLA, no aborta la corrida
                s.fallos += 1
                print("   [FALLA] excepcion en el escenario:\n" + "".join("     " + l for l in traceback.format_exc().splitlines(True)))
            estado = "FALLA" if s.fallos else ("NO VERIFICADO" if s.nv else "OK")
            RESULTADOS.append((num, titulo, estado, s.fallos, s.nv))
            print(f"   => {estado}")
        run.num = num
        return run
    return deco


# ------------------------------------------------------------------ escenarios
@escenario(1, "Carrito: vacio v0, agregar con Idempotency-Key, repetir no duplica")
def esc1(s):
    uid, tok = nuevo_usuario()
    p = nuevo_producto("100.00", 10)
    r = carrito(uid, tok)
    s.check("GET carrito vacio => 200, items [] y version 0",
            r.status == 200 and r.data == {"usuario_id": uid, "items": [], "version": 0}, r)
    k = str(uuid.uuid4())
    r1 = agregar(uid, tok, p, 2, k)
    s.check("agregar 2 con clave K => 200, cantidad 2, version 1",
            r1.status == 200 and r1.data["version"] == 1 and r1.data["items"][0]["cantidad"] == 2, r1)
    linea = r1.data["items"][0]["linea_id"] if r1.status == 200 else None
    r2 = agregar(uid, tok, p, 2, k)
    s.check("repetir la MISMA clave => 200 sin duplicar (cantidad 2, version 1, misma linea_id)",
            r2.status == 200 and r2.data["version"] == 1 and r2.data["items"] == r1.data["items"], r2)
    r3 = agregar(uid, tok, p, 5, k)
    s.check("misma clave con OTRO cuerpo => 409", r3.status == 409, r3)
    r4 = agregar(uid, tok, p, 1)
    s.check("otra clave suma 1 => cantidad 3, version 2, linea_id conservada",
            r4.status == 200 and r4.data["items"][0]["cantidad"] == 3 and r4.data["version"] == 2
            and r4.data["items"][0]["linea_id"] == linea, r4)
    r5 = http("POST", f"{URL['carrito']}/api/carrito/{uid}/agregar", {"producto_id": p, "cantidad": 1}, token=tok)
    s.check("agregar SIN Idempotency-Key => 422", r5.status == 422, r5)
    r6 = agregar(uid, tok, str(uuid.uuid4()), 1)
    s.check("producto inexistente => 404", r6.status == 404, r6)
    r7 = agregar(uid, tok, p, 0)
    s.check("cantidad 0 => 422", r7.status == 422, r7)
    r8 = agregar(uid, tok, p, 11)
    s.check("cantidad mayor al stock => 409", r8.status == 409, r8)


@escenario(2, "Envios: cotizar envio")
def esc2(s):
    uid, tok = nuevo_usuario()
    r = http("POST", URL["envios"] + "/api/envios/cotizar", {"codigo_postal": "06600", "cantidad": 2}, token=tok)
    s.check("CP 06600 x2 => 200 costo 114.00 (89 + 10*0 + 25), 2 dias",
            r.status == 200 and r.data == {"costo_envio": "114.00", "dias_estimados": 2}, r)
    r = http("POST", URL["envios"] + "/api/envios/cotizar", {"codigo_postal": "91000", "cantidad": 1}, token=tok)
    s.check("CP 91000 x1 => 179.00, 5 dias", r.status == 200 and r.data == {"costo_envio": "179.00", "dias_estimados": 5}, r)
    r = http("POST", URL["envios"] + "/api/envios/cotizar", {"codigo_postal": "06600", "cantidad": 1},
             service=ENV["T_PEDIDOS_ENVIOS"])
    s.check("con X-Service-Token de Pedidos => 200", r.status == 200, r)
    r = http("POST", URL["envios"] + "/api/envios/cotizar", {"codigo_postal": "0660", "cantidad": 1}, token=tok)
    s.check("CP invalido => 422", r.status == 422, r)
    r = http("POST", URL["envios"] + "/api/envios/cotizar", {"codigo_postal": "06600", "cantidad": 1})
    s.check("sin credenciales => 401", r.status == 401, r)


@escenario(3, "Compra aprobada: pedido pagado, 1 pago, guia, stock descontado 1 vez, carrito sin lo comprado")
def esc3(s):
    uid, tok = nuevo_usuario()
    p = nuevo_producto("100.00", 10)
    agregar(uid, tok, p, 2)
    clave = str(uuid.uuid4())
    r = comprar(tok, clave)
    d = r.data or {}
    s.check("POST /api/pedidos => 201 estado pagado", r.status == 201 and d.get("estado") == "pagado", r)
    s.check("importes: costo_envio 114.00, total 314.00, item 2 x 100.00",
            d.get("costo_envio") == "114.00" and d.get("total") == "314.00"
            and d.get("items") == [{"producto_id": p, "cantidad": 2, "precio_unitario": "100.00"}], d)
    pid = d.get("id", "")
    s.check("GET pedido (titular) => 200 pagado", pedido(pid, tok).status == 200 and pedido(pid, tok).data["estado"] == "pagado")
    g = http("GET", f"{URL['pagos']}/api/pagos/pedido/{pid}", token=tok)
    s.check("Pagos: comprobante aprobado por 314.00 tarjeta_simulada",
            g.status == 200 and g.data["estado"] == "aprobado" and g.data["monto"] == "314.00"
            and g.data["metodo_pago"] == "tarjeta_simulada", g)
    s.check("BD Pagos: exactamente 1 pago del pedido", pagos_db(f"pedido_id='{pid}'") == "1", pagos_db(f"pedido_id='{pid}'"))
    guia = guia_de(pid)
    s.check("BD Envios: exactamente 1 guia para el pedido", n_guias(pid) == "1" and guia != "", guia)
    ra = http("GET", f"{URL['envios']}/api/envios/rastreo/{guia}", token=tok)
    s.check("Rastreo del titular => 200 preparando (generar guia no marca enviado)",
            ra.status == 200 and ra.data["estado"] == "preparando" and ra.data["pedido_id"] == pid, ra)
    est = inv()
    s.check("Inventario: fisico 10 -> 8, reservado 0 (descontado una sola vez)",
            est["stock"][p] == {"fisico": 8, "reservado": 0}, est["stock"][p])
    s.check("Inventario: reserva confirmada, 1 reservar + 1 confirmar",
            est["reservas"][pid]["estado"] == "confirmada"
            and [l[0] for l in est["llamadas"] if l[1] == pid].count("reservar") == 1
            and [l[0] for l in est["llamadas"] if l[1] == pid].count("confirmar") == 1,
            [l[0] for l in est["llamadas"] if l[1] == pid])
    c = carrito(uid, tok)
    s.check("Carrito sin las unidades compradas (items [], version > 1)",
            c.status == 200 and c.data["items"] == [] and c.data["version"] > 1, c)
    CTX["s3"] = {"uid": uid, "tok": tok, "clave": clave, "id": pid, "guia": guia, "p": p, "pedido": d}


@escenario(4, "Agregar 1 articulo DURANTE el pago: 2 comprados + 1 agregado => queda 1")
def esc4(s):
    uid, tok = nuevo_usuario()
    p = nuevo_producto("50.00", 20)
    r0 = agregar(uid, tok, p, 2)
    linea = r0.data["items"][0]["linea_id"]
    proxy(PROXY_PAGOS, modo="delay", ruta="/api/pagos/procesar", segundos=3, coincidencias=0)
    res = {}
    t = threading.Thread(target=lambda: res.update(r=comprar(tok, str(uuid.uuid4()))))
    t.start()
    visto = False
    for _ in range(100):
        if http("GET", PROXY_PAGOS + "/c").json["coincidencias"] >= 1:
            visto = True
            break
        time.sleep(0.1)
    s.check("el checkout llego a Pagos y esta en vuelo (retenido 3 s por el proxy)", visto)
    vaciar = http("DELETE", f"{URL['carrito']}/api/carrito/{uid}/vaciar", headers=idem(), service=ENV["T_PEDIDOS_CARRITO"])
    s.check("vaciar con checkout activo => 409", vaciar.status == 409, vaciar)
    ra = agregar(uid, tok, p, 1)
    s.check("agregar 1 durante el pago => 200 (cantidad 3)",
            ra.status == 200 and ra.data["items"][0]["cantidad"] == 3, ra)
    t.join()
    proxy(PROXY_PAGOS, modo="pass", ruta="", coincidencias=0)
    r = res["r"]
    s.check("la compra termina 201 pagado, items comprados = 2", r.status == 201 and r.data["estado"] == "pagado"
            and r.data["items"][0]["cantidad"] == 2, r)
    c = carrito(uid, tok)
    s.check("carrito conserva la adicion: queda 1 unidad, misma linea_id",
            c.status == 200 and len(c.data["items"]) == 1 and c.data["items"][0]["cantidad"] == 1
            and c.data["items"][0]["linea_id"] == linea, c)


@escenario(5, "Pago rechazado: 201 cancelado, reserva liberada, carrito intacto (3)")
def esc5(s):
    uid, tok = nuevo_usuario()
    p = nuevo_producto("20.00", 10)
    agregar(uid, tok, p, 3)
    r = comprar(tok, str(uuid.uuid4()), metodo="transferencia_simulada")
    pid = (r.data or {}).get("id", "")
    s.check("POST => 201 estado cancelado", r.status == 201 and r.data["estado"] == "cancelado", r)
    g = http("GET", f"{URL['pagos']}/api/pagos/pedido/{pid}", token=tok)
    s.check("Pagos: 1 comprobante rechazado (transferencia_simulada)",
            g.status == 200 and g.data["estado"] == "rechazado" and pagos_db(f"pedido_id='{pid}'") == "1", g)
    est = inv()
    s.check("Inventario: reserva liberada y stock intacto (10 fisicos, 0 reservados, 10 disponibles)",
            est["reservas"][pid]["estado"] == "liberada" and est["stock"][p] == {"fisico": 10, "reservado": 0}
            and disponibles(p) == 10, est["reservas"].get(pid))
    s.check("sin guia generada", n_guias(pid) == "0")
    c = carrito(uid, tok)
    s.check("carrito intacto: 3 unidades", c.status == 200 and c.data["items"][0]["cantidad"] == 3, c)
    r2 = comprar(tok, str(uuid.uuid4()))
    s.check("checkout liberado: nueva compra con tarjeta => 201 pagado", r2.status == 201 and r2.data["estado"] == "pagado", r2)
    CTX["s5_cancelado"] = pid


@escenario(6, "Stock insuficiente: 409 / cancelado sin cobro")
def esc6(s):
    uid, tok = nuevo_usuario()
    p = nuevo_producto("30.00", 10)
    agregar(uid, tok, p, 5)
    set_stock(p, 3)
    antes = pagos_db()
    r = comprar(tok, str(uuid.uuid4()))
    s.check("POST => 409", r.status == 409, r)
    s.check("sin cobro: la tabla pagos no crece", pagos_db() == antes, f"{antes} -> {pagos_db()}")
    h = http("GET", f"{URL['pedidos']}/api/pedidos/usuario/{uid}", token=tok)
    s.check("pedido persistido como cancelado", h.status == 200 and len(h.data) == 1 and h.data[0]["estado"] == "cancelado", h)
    s.check("stock sin cambios (3 disponibles, 0 reservados)", inv()["stock"][p] == {"fisico": 3, "reservado": 0})
    c = carrito(uid, tok)
    s.check("carrito intacto (5) y checkout liberado (se puede vaciar)", c.data["items"][0]["cantidad"] == 5
            and http("DELETE", f"{URL['carrito']}/api/carrito/{uid}/vaciar", headers=idem(), service=ENV["T_PEDIDOS_CARRITO"]).status == 200, c)


@escenario(7, "Repetir POST con la misma Idempotency-Key: mismo pedido, sin duplicados")
def esc7(s):
    c3 = CTX.get("s3")
    if not c3:
        return s.no_verificado("depende del escenario 3, que no produjo contexto")
    r = comprar(c3["tok"], c3["clave"])
    s.check("misma clave y cuerpo => 201 con el MISMO pedido (id, estado, total)",
            r.status == 201 and r.data == c3["pedido"], r)
    s.check("sigue 1 solo pago y 1 sola guia", pagos_db(f"pedido_id='{c3['id']}'") == "1" and n_guias(c3["id"]) == "1")
    s.check("stock no vuelve a descontarse (fisico 8)", inv()["stock"][c3["p"]]["fisico"] == 8)
    r2 = comprar(c3["tok"], c3["clave"], metodo="transferencia_simulada")
    s.check("misma clave con OTRO cuerpo => 409", r2.status == 409, r2)
    r3 = comprar(c3["tok"], str(uuid.uuid4()))
    s.check("otra clave con carrito ya vacio => 409", r3.status == 409, r3)
    h = http("GET", f"{URL['pedidos']}/api/pedidos/usuario/{c3['uid']}", token=c3["tok"])
    s.check("historial: 1 pedido", h.status == 200 and len(h.data) == 1, h)
    r4 = http("POST", URL["pedidos"] + "/api/pedidos", {"direccion": DIRECCION, "metodo_pago": "tarjeta_simulada"},
              token=c3["tok"])
    s.check("sin Idempotency-Key => 422", r4.status == 422, r4)


@escenario(8, "Caidas: kill de Carrito / de Pagos (cobro sin respuesta) / Carrito en finalizar + recuperar")
def esc8(s):
    # (a) Carrito caido antes de comprar
    uid, tok = nuevo_usuario()
    p = nuevo_producto("40.00", 20)
    agregar(uid, tok, p, 1)
    clave = str(uuid.uuid4())
    svc("kill", "carrito")
    antes = pagos_db()
    r = comprar(tok, clave)
    s.check("(a) Carrito apagado (kill -9) => POST 503", r.status == 503, r)
    s.check("(a) sin cobro mientras tanto", pagos_db() == antes)
    rc, out = svc("start", "carrito")
    s.check("(a) Carrito reiniciado y /ready 200", rc == 0, out[-80:])
    r = comprar(tok, clave)
    s.check("(a) misma clave tras reiniciar => 201 pagado", r.status == 201 and r.data["estado"] == "pagado", r)
    s.check("(a) 1 pago del pedido", pagos_db(f"pedido_id='{(r.data or {}).get('id')}'") == "1")

    # (b0) Pagos cobra y se pierde SOLO la respuesta del POST: Pedidos lo resuelve consultando GET /pagos/pedido/{id}
    uid, tok = nuevo_usuario()
    p = nuevo_producto("40.00", 20)
    agregar(uid, tok, p, 1)
    proxy(PROXY_PAGOS, modo="drop_response", ruta="/api/pagos/procesar", coincidencias=0)
    r = comprar(tok, str(uuid.uuid4()))
    descartadas = http("GET", PROXY_PAGOS + "/c").json["descartadas"]
    proxy(PROXY_PAGOS, modo="pass", ruta="", coincidencias=0)
    s.check("(b0) respuesta de POST /procesar perdida (descartada por el proxy) pero Pedidos concilia con GET => 201 pagado, 1 pago",
            descartadas >= 1 and r.status == 201 and r.data["estado"] == "pagado" and pagos_db(f"pedido_id='{r.data['id']}'") == "1",
            f"descartadas={descartadas} {r}")

    # (b) Pagos cobra pero se pierde la respuesta del POST Y la consulta; luego Pagos muere (kill -9) y reinicia
    uid, tok = nuevo_usuario()
    p = nuevo_producto("40.00", 20)
    agregar(uid, tok, p, 2)
    clave = str(uuid.uuid4())
    proxy(PROXY_PAGOS, modo="drop_response", ruta="/api/pagos/", coincidencias=0)
    r = comprar(tok, clave)
    s.check("(b) cobro efectuado, respuesta del POST y de la consulta perdidas => POST 503", r.status == 503, r)
    h = http("GET", f"{URL['pedidos']}/api/pedidos/usuario/{uid}", token=tok)
    pid = h.data[0]["id"] if h.status == 200 and h.data else ""
    s.check("(b) el pedido persiste como pendiente (NO se cancela por resultado incierto)",
            h.status == 200 and len(h.data) == 1 and h.data[0]["estado"] == "pendiente", h)
    s.check("(b) Pagos SI registro 1 pago aprobado", pagos_db(f"pedido_id='{pid}' and estado='aprobado'") == "1")
    est = inv()
    s.check("(b) reserva NO liberada por timeout (sigue 'reservada')", est["reservas"][pid]["estado"] == "reservada", est["reservas"].get(pid))
    svc("kill", "pagos")
    proxy(PROXY_PAGOS, modo="pass", ruta="", coincidencias=0)
    r = comprar(tok, clave)
    s.check("(b) con Pagos caido (kill -9), misma clave => 503 y pedido sigue pendiente",
            r.status == 503 and pedido(pid, tok).data["estado"] == "pendiente", r)
    rc, out = svc("start", "pagos")
    s.check("(b) Pagos reiniciado y /ready 200", rc == 0, out[-80:])
    r = comprar(tok, clave)
    s.check("(b) misma clave => 201 pagado, MISMO pedido", r.status == 201 and r.data["estado"] == "pagado" and r.data["id"] == pid, r)
    s.check("(b) sigue exactamente 1 pago (sin doble cobro)", pagos_db(f"pedido_id='{pid}'") == "1", pagos_db(f"pedido_id='{pid}'"))
    est = inv()
    s.check("(b) reserva confirmada y stock 20 -> 18 una sola vez", est["reservas"][pid]["estado"] == "confirmada"
            and est["stock"][p]["fisico"] == 18, est["stock"][p])
    s.check("(b) 1 guia; carrito vacio", n_guias(pid) == "1" and carrito(uid, tok).data["items"] == [])

    # (c) Carrito falla en finalizar; recuperacion SIN cliente con pedidos:recuperar
    uid, tok = nuevo_usuario()
    p = nuevo_producto("40.00", 20)
    agregar(uid, tok, p, 2)
    clave = str(uuid.uuid4())
    proxy(PROXY_CARRITO, modo="refuse", ruta="/finalizar", coincidencias=0)
    r = comprar(tok, clave)
    s.check("(c) finalizar del carrito falla => POST 503", r.status == 503, r)
    h = http("GET", f"{URL['pedidos']}/api/pedidos/usuario/{uid}", token=tok)
    pid = h.data[0]["id"]
    s.check("(c) el pedido ya cobrado queda 'pagado' (nunca se cancela)", h.data[0]["estado"] == "pagado", h.data[0]["estado"])
    s.check("(c) carrito aun con items (finalizar pendiente)", carrito(uid, tok).data["items"][0]["cantidad"] == 2)
    proxy(PROXY_CARRITO, modo="pass", ruta="", coincidencias=0)
    time.sleep(6)  # backoff inicial de 5 s
    rc, out = svc("start", "pedidos-recuperar")
    s.nota("pedidos:recuperar => " + out.replace("\n", " | ")[-300:])
    c = carrito(uid, tok)
    s.check("(c) tras pedidos:recuperar el carrito queda sin lo comprado", rc == 0 and c.data["items"] == [], c)
    s.check("(c) sin doble cobro (1 pago) y 1 guia", pagos_db(f"pedido_id='{pid}'") == "1" and n_guias(pid) == "1")
    r = comprar(tok, clave)
    s.check("(c) repetir la clave devuelve el mismo pedido pagado", r.status == 201 and r.data["id"] == pid and r.data["estado"] == "pagado", r)


@escenario(9, "Seguridad: JWT, titularidad, tokens internos, PATCH como cliente")
def esc9(s):
    c3 = CTX.get("s3")
    if not c3:
        return s.no_verificado("depende del escenario 3")
    A, tokA, pid, guia = c3["uid"], c3["tok"], c3["id"], c3["guia"]
    B, tokB = nuevo_usuario()
    _, tokAdmin = nuevo_usuario("admin")
    body = {"direccion": DIRECCION, "metodo_pago": "tarjeta_simulada"}
    s.check("POST /api/pedidos sin JWT => 401", http("POST", URL["pedidos"] + "/api/pedidos", body, idem()).status == 401)
    s.check("GET carrito sin JWT => 401", carrito(A, None).status == 401)
    partes = tokA.split(".")
    otro = base64.urlsafe_b64encode(json.dumps({**json.loads(base64.urlsafe_b64decode(partes[1] + "==")), "sub": B}).encode()).rstrip(b"=").decode()
    manip = ".".join([partes[0], otro, partes[2]])
    for nombre, url in [("pedidos", f"{URL['pedidos']}/api/pedidos/{pid}"), ("carrito", f"{URL['carrito']}/api/carrito/{B}"),
                        ("envios", f"{URL['envios']}/api/envios/rastreo/{guia}"), ("pagos", f"{URL['pagos']}/api/pagos/pedido/{pid}")]:
        r = http("GET", url, token=manip)
        s.check(f"JWT manipulado (payload alterado, firma vieja) en {nombre} => 401", r.status == 401, r)
    ajena = firmar(A, key=PRIV_AJENA)
    s.check("JWT firmado con otra clave RSA => 401 (pedidos/carrito)",
            pedido(pid, ajena).status == 401 and carrito(A, ajena).status == 401)
    none_tok = jwt.encode({"sub": A, "role": "cliente", "iss": "api-usuarios", "aud": "tienda-microservicios",
                           "iat": int(time.time()) - 5, "exp": int(time.time()) + 900}, key=None, algorithm="none")
    s.check("JWT alg=none => 401", pedido(pid, none_tok).status == 401 and carrito(A, none_tok).status == 401)
    s.check("JWT expirado => 401", pedido(pid, firmar(A, iat=int(time.time()) - 7200, exp=int(time.time()) - 3600)).status == 401)
    s.check("JWT con audiencia equivocada => 401", pedido(pid, firmar(A, aud="otra")).status == 401)
    s.check("JWT con sub no UUID v4 => 401", pedido(pid, firmar("no-es-uuid")).status == 401)
    # titularidad
    r = pedido(pid, tokB)
    s.check("cliente B lee pedido de A => 403/404", r.status in (403, 404), r)
    r = carrito(A, tokB)
    s.check("cliente B lee carrito de A => 403/404", r.status in (403, 404), r)
    r = http("POST", f"{URL['carrito']}/api/carrito/{A}/agregar", {"producto_id": c3["p"], "cantidad": 1}, idem(), token=tokB)
    s.check("cliente B agrega al carrito de A => 403/404", r.status in (403, 404), r)
    r = http("GET", f"{URL['pedidos']}/api/pedidos/usuario/{A}", token=tokB)
    s.check("cliente B lee historial de A => 403/404", r.status in (403, 404), r)
    r = http("GET", f"{URL['envios']}/api/envios/rastreo/{guia}", token=tokB)
    s.check("cliente B rastrea guia de A => 403/404", r.status in (403, 404), r)
    r = http("GET", f"{URL['pagos']}/api/pagos/pedido/{pid}", token=tokB)
    s.check("cliente B lee pago de A => 403/404", r.status in (403, 404), r)
    s.check("admin lee pedido y carrito de A => 200",
            pedido(pid, tokAdmin).status == 200 and carrito(A, tokAdmin).status == 200)
    s.check("titular A si => 200 pedido y rastreo",
            pedido(pid, tokA).status == 200 and http("GET", f"{URL['envios']}/api/envios/rastreo/{guia}", token=tokA).status == 200)
    # rutas internas Carrito
    tok_ok, tok_mal = ENV["T_PEDIDOS_CARRITO"], ENV["T_PEDIDOS_PAGOS"]
    for ruta, cuerpo in [("iniciar", {"pedido_id": str(uuid.uuid4()), "version_original": 0}),
                         ("finalizar", {"pedido_id": str(uuid.uuid4()), "version_original": 0, "items": []}),
                         ("liberar", {"pedido_id": str(uuid.uuid4())})]:
        u = f"{URL['carrito']}/api/carrito/{B}/{ruta}"
        a = http("POST", u, cuerpo, idem())
        b = http("POST", u, cuerpo, idem(), service=tok_mal)
        c = http("POST", u, cuerpo, idem(), token=tokB)
        s.check(f"Carrito /{ruta}: sin token {a.status}, token de otro par {b.status}, JWT de cliente {c.status} => todos 401",
                (a.status, b.status, c.status) == (401, 401, 401))
    u = f"{URL['carrito']}/api/carrito/{B}/vaciar"
    s.check("Carrito DELETE /vaciar: sin token, token ajeno y JWT => 401",
            [http("DELETE", u, headers=idem()).status, http("DELETE", u, headers=idem(), service=tok_mal).status,
             http("DELETE", u, headers=idem(), token=tokB).status] == [401, 401, 401])
    # Pagos
    cuerpo = {"pedido_id": str(uuid.uuid4()), "monto": "1.00", "metodo_pago": "tarjeta_simulada"}
    u = URL["pagos"] + "/api/pagos/procesar"
    r = [http("POST", u, cuerpo, idem()).status, http("POST", u, cuerpo, idem(), service=ENV["T_PAGOS_PEDIDOS"]).status,
         http("POST", u, cuerpo, idem(), token=tokB).status]
    s.check(f"Pagos /procesar: sin token, token de otro par y JWT cliente => 401/403 ({r})", all(x in (401, 403) for x in r))
    r = [http("GET", f"{URL['pagos']}/api/pagos/pedido/{pid}").status,
         http("GET", f"{URL['pagos']}/api/pagos/pedido/{pid}", service="x" * 40).status]
    s.check(f"Pagos GET: sin credencial y token desconocido => 401 ({r})", r == [401, 401])
    # Envios
    cuerpo = {"pedido_id": str(uuid.uuid4()), "direccion": DIRECCION}
    u = URL["envios"] + "/api/envios/generar"
    r = [http("POST", u, cuerpo, idem()).status, http("POST", u, cuerpo, idem(), service=ENV["T_ENVIOS_PEDIDOS"]).status,
         http("POST", u, cuerpo, idem(), token=tokB).status]
    s.check(f"Envios /generar: sin token {r[0]}, token de otro par {r[1]} => 401; JWT cliente {r[2]} => 401/403",
            r[0] == 401 and r[1] == 401 and r[2] in (401, 403))
    r = http("GET", f"{URL['envios']}/api/envios/rastreo/{guia}", service=ENV["T_PEDIDOS_PAGOS"])
    s.check("Envios rastreo con token interno de otro par => 401", r.status == 401, r)
    # Pedidos: PATCH y GET interno
    u = f"{URL['pedidos']}/api/pedidos/{pid}/estado"
    cu = {"estado": "enviado"}
    r = {"cliente_titular": http("PATCH", u, cu, idem(), token=tokA).status,
         "admin": http("PATCH", u, cu, idem(), token=tokAdmin).status,
         "sin_credencial": http("PATCH", u, cu, idem()).status,
         "token_desconocido": http("PATCH", u, cu, idem(), service="x" * 40).status,
         "token_de_Pagos": http("PATCH", u, cu, idem(), service=ENV["T_PAGOS_PEDIDOS"]).status,
         "token_de_Pedidos_saliente": http("PATCH", u, cu, idem(), service=ENV["T_PEDIDOS_ENVIOS"]).status}
    s.check(f"PATCH /estado con JWT cliente/admin o sin credencial => 401 ({r})",
            r["cliente_titular"] == 401 and r["admin"] == 401 and r["sin_credencial"] == 401 and r["token_desconocido"] == 401)
    s.check(f"PATCH /estado con token interno de otro par => 401/403 ({r['token_de_Pagos']}, {r['token_de_Pedidos_saliente']})",
            r["token_de_Pagos"] in (401, 403) and r["token_de_Pedidos_saliente"] in (401, 403))
    s.check("el pedido sigue 'pagado' tras todos los PATCH rechazados", pedido(pid, tokA).data["estado"] == "pagado")
    s.check("GET pedido con token interno de Pagos (lectura interna) => 200", pedido(pid, service=ENV["T_PAGOS_PEDIDOS"]).status == 200)
    s.check("GET pedido con token interno desconocido => 401", pedido(pid, service="x" * 40).status == 401)


@escenario(10, "PATCH /estado pagado->enviado con token de Envios: 200, idempotente, otra transicion 409")
def esc10(s):
    c = compra_pagada()
    pid, svc_tok = c["id"], ENV["T_ENVIOS_PEDIDOS"]
    u = f"{URL['pedidos']}/api/pedidos/{pid}/estado"
    k = str(uuid.uuid4())
    r = http("PATCH", u, {"estado": "enviado"}, {"Idempotency-Key": k}, service=svc_tok)
    s.check("pagado -> enviado => 200 estado enviado", r.status == 200 and r.data["estado"] == "enviado", r)
    r2 = http("PATCH", u, {"estado": "enviado"}, {"Idempotency-Key": k}, service=svc_tok)
    s.check("repetir misma clave => 200 idempotente, mismo cuerpo", r2.status == 200 and r2.data == r.data, r2)
    r3 = http("PATCH", u, {"estado": "enviado"}, idem(), service=svc_tok)
    s.check("repetir 'enviado' con otra clave => 200 sin cambios", r3.status == 200 and r3.data["estado"] == "enviado", r3)
    r4 = http("PATCH", u, {"estado": "pagado"}, idem(), service=svc_tok)
    s.check("enviado -> pagado => 409", r4.status == 409, r4)
    r5 = http("PATCH", u, {"estado": "cancelado"}, idem(), service=svc_tok)
    s.check("enviado -> cancelado => 409", r5.status == 409, r5)
    r6 = http("PATCH", u, {"estado": "enviado"}, {"Idempotency-Key": k}, service=svc_tok)
    s.check("misma clave original sigue devolviendo 200", r6.status == 200)
    r7 = http("PATCH", u, {"estado": "pagado"}, {"Idempotency-Key": k}, service=svc_tok)
    s.check("misma clave con OTRO estado => 409", r7.status == 409, r7)
    s.check("GET pedido (titular) => enviado", pedido(pid, c["tok"]).data["estado"] == "enviado")
    cancelado = CTX.get("s5_cancelado")
    if cancelado:
        r8 = http("PATCH", f"{URL['pedidos']}/api/pedidos/{cancelado}/estado", {"estado": "enviado"}, idem(), service=svc_tok)
        s.check("cancelado -> enviado => 409", r8.status == 409, r8)
    else:
        s.no_verificado("no hay pedido cancelado del escenario 5")
    r9 = http("PATCH", f"{URL['pedidos']}/api/pedidos/{uuid.uuid4()}/estado", {"estado": "enviado"}, idem(), service=svc_tok)
    s.check("pedido inexistente => 404", r9.status == 404, r9)


@escenario(11, "Envios: generar guia, rastreo y EnviosRepo.despachar -> outbox -> Pedidos pasa a enviado")
def esc11(s):
    c = compra_pagada()
    pid, guia = c["id"], c["guia"]
    ra = http("GET", f"{URL['envios']}/api/envios/rastreo/{guia}", token=c["tok"])
    s.check("guia generada por la compra, rastreo 'preparando'", ra.status == 200 and ra.data["estado"] == "preparando", ra)
    gen = http("POST", URL["envios"] + "/api/envios/generar", {"pedido_id": pid, "direccion": DIRECCION}, idem(),
               service=ENV["T_PEDIDOS_ENVIOS"])
    s.check("POST /generar directo (otra clave, mismo pedido y direccion) => 201 la MISMA guia",
            gen.status == 201 and gen.data["guia"] == guia and gen.data["estado"] == "preparando", gen)
    time.sleep(5)  # > intervalo del Notificador (3 s): generar la guia NO debe notificar
    s.check("tras >1 ciclo del Notificador el pedido sigue 'pagado' (guia != enviado)", pedido(pid, c["tok"]).data["estado"] == "pagado")
    env = dict(ENV, API_ENVIOS_DIR=str(E2E.parent / "api-envios"), DB_HOST="127.0.0.1", DB_PORT=ENV["PG_PORT"],
               DB_DATABASE="db_envios", DB_USERNAME="usr_envios", DB_PASSWORD=ENV["PW_ENVIOS"])
    out = subprocess.run([sys.executable, "-B", str(E2E / "tests" / "despachar.py"), pid], capture_output=True, text=True,
                         env=env, cwd=str(E2E.parent / "api-envios"), timeout=60)
    s.check("script despachar.py (EnviosRepo.despachar) termino sin error", out.returncode == 0, (out.stdout + out.stderr)[-400:])
    try:
        info = json.loads(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        info = {}
    s.nota(f"despachar => {json.dumps(info, default=str)[:500]}")
    ok = False
    for _ in range(40):
        if pedido(pid, c["tok"]).data["estado"] == "enviado":
            ok = True
            break
        time.sleep(1)
    s.check("el Notificador (outbox) llega a Pedidos real y el pedido pasa a 'enviado'", ok, pedido(pid, c["tok"]).data["estado"])
    ra = http("GET", f"{URL['envios']}/api/envios/rastreo/{guia}", token=c["tok"])
    s.check("rastreo => en_transito", ra.status == 200 and ra.data["estado"] == "en_transito", ra)
    fila = sql("db_envios", "usr_envios", "PW_ENVIOS", f"select * from notificaciones_pedido where pedido_id='{pid}'")
    s.nota(f"outbox: {fila}")
    s.check("outbox: una sola fila por pedido", sql("db_envios", "usr_envios", "PW_ENVIOS",
            f"select count(*) from notificaciones_pedido where pedido_id='{pid}'") == "1")


@escenario(12, "/health y /ready de cada servicio; /ready 503 con la BD detenida (docker pause del PG e2e)")
def esc12(s):
    nombres = {"carrito": "api-carrito", "pedidos": "api-pedidos", "pagos": "api-pagos", "envios": "api-envios"}
    for n, nombre in nombres.items():
        h = http("GET", URL[n] + "/health")
        r = http("GET", URL[n] + "/ready")
        s.check(f"{n}: /health {h.status} y /ready {r.status} => 200", h.status == 200 and r.status == 200, f"{h.text} | {r.text}")
    pausado = False
    try:
        out = subprocess.run(["docker", "pause", "mojarra-pg-e2e"], capture_output=True, text=True)
        pausado = out.returncode == 0
        s.check("docker pause mojarra-pg-e2e", pausado, out.stdout.strip() + out.stderr.strip())
        for n in nombres:
            r = http("GET", URL[n] + "/ready", timeout=60)
            h = http("GET", URL[n] + "/health", timeout=20)
            s.check(f"{n}: BD detenida => /ready 503 ({r.seg:.1f} s) y /health {h.status}", r.status == 503 and h.status == 200, r)
    finally:
        if pausado:
            subprocess.run(["docker", "unpause", "mojarra-pg-e2e"], capture_output=True, text=True)
    for n in nombres:
        r = None
        for _ in range(60):
            r = http("GET", URL[n] + "/ready", timeout=10)
            if r.status == 200:
                break
            time.sleep(1)
        s.check(f"{n}: BD reanudada => /ready vuelve a 200", r.status == 200, r)


def main():
    t0 = time.time()
    for fn in [esc1, esc2, esc3, esc4, esc5, esc6, esc7, esc8, esc9, esc10, esc11, esc12]:
        fn()
    print("\n================ RESUMEN ================")
    for num, titulo, estado, fallos, nv in RESULTADOS:
        print(f"{num:>2}  {estado:<14} {titulo}" + (f"  ({fallos} comprobaciones fallidas)" if fallos else ""))
    print(f"duracion: {time.time() - t0:.0f} s")
    sys.exit(1 if any(r[2] == "FALLA" for r in RESULTADOS) else 0)


if __name__ == "__main__":
    main()
