"""Escenarios E2E "como cliente" por HTTP real contra Carrito, Pedidos, Pagos y Envios.

Se ejecuta desde run.sh con el Python del venv de Envios (necesita PyJWT + cryptography) y las variables
exportadas en e2e/.tmp/env.sh. Cada escenario afirma codigos y cuerpos REALES y imprime lo observado.
Resultado por escenario: OK (todas las comprobaciones), FALLA, o NO VERIFICADO (no se pudo comprobar).
"""
import base64
import json
import os
import re
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
    "productos": "http://127.0.0.1:8002", "envios": "http://127.0.0.1:8003", "envios2": "http://127.0.0.1:8013", "inventario": "http://127.0.0.1:8004",
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


def svc(accion, nombre, env=None):
    """servicios.sh; `env` anade variables solo a esa llamada (p. ej. E2E_SCHEDULER, ENVIOS_DESPACHO_SEGUNDOS)."""
    r = subprocess.run([str(E2E / "servicios.sh"), accion, nombre], capture_output=True, text=True, timeout=180,
                       env=dict(os.environ, **(env or {})))
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


def n_outbox(pid, estado=None):
    cond = f" and estado='{estado}'" if estado else ""
    return sql("db_envios", "usr_envios", "PW_ENVIOS", f"select count(*) from notificaciones_pedido where pedido_id='{pid}'{cond}")


def esperar(cond, segundos, paso=1.0):
    """Sondea `cond()` hasta `segundos`; devuelve (ok, segundos_transcurridos). Sin intervencion del test."""
    t0 = time.time()
    while time.time() - t0 < segundos:
        if cond():
            return True, time.time() - t0
        time.sleep(paso)
    return bool(cond()), time.time() - t0


@escenario(11, "Envios: guia, rastreo, generar idempotente; la notificacion pendiente sobrevive a reinicios (Pedidos y Envios caidos)")
def esc11(s):
    # Parte 1: con despacho lento (3600 s) generar la guia NO notifica ni despacha.
    c = compra_pagada()
    pid, guia = c["id"], c["guia"]
    ra = http("GET", f"{URL['envios']}/api/envios/rastreo/{guia}", token=c["tok"])
    s.check("guia generada por la compra, rastreo 'preparando'", ra.status == 200 and ra.data["estado"] == "preparando", ra)
    gen = http("POST", URL["envios"] + "/api/envios/generar", {"pedido_id": pid, "direccion": DIRECCION}, idem(),
               service=ENV["T_PEDIDOS_ENVIOS"])
    s.check("POST /generar directo (otra clave, mismo pedido y direccion) => 201 la MISMA guia",
            gen.status == 201 and gen.data["guia"] == guia and gen.data["estado"] == "preparando", gen)
    time.sleep(5)  # > intervalo del Notificador (3 s): generar la guia NO debe notificar
    s.check("tras >1 ciclo del Notificador el pedido sigue 'pagado' (guia != enviado) y no hay outbox",
            pedido(pid, c["tok"]).data["estado"] == "pagado" and n_outbox(pid) == "0")

    # Parte 2: despacho a 8 s; se apaga Pedidos ANTES del despacho. Nadie invoca despachar a mano.
    rc, out = svc("restart", "envios", {"ENVIOS_DESPACHO_SEGUNDOS": "8", "ENVIOS_DESPACHO_INTERVALO_SEGUNDOS": "1", "NOTIF_INTERVALO": "1"})
    s.check("Envios reiniciado con despacho a 8 s", rc == 0, out[-80:])
    c2 = compra_pagada()
    pid2, guia2 = c2["id"], c2["guia"]
    svc("kill", "pedidos")
    # Con Pedidos caido el rastreo HTTP no sirve (Envios consulta a Pedidos para la titularidad): se lee la BD de Envios.
    estado_envio = lambda: sql("db_envios", "usr_envios", "PW_ENVIOS", f"select estado from envios where guia='{guia2}'")
    ok, t = esperar(lambda: estado_envio() == "en_transito", 40)
    s.check(f"con Pedidos caido, Envios despacha solo (envio en_transito en BD en {t:.0f} s)", ok, estado_envio())
    time.sleep(4)  # varios ciclos del Notificador contra un Pedidos caido
    s.check("la notificacion queda 'pendiente' (1 fila, no entregada)", n_outbox(pid2, "pendiente") == "1", n_outbox(pid2))
    fila = sql("db_envios", "usr_envios", "PW_ENVIOS", f"select * from notificaciones_pedido where pedido_id='{pid2}'")
    s.nota(f"outbox con Pedidos caido: {fila}")
    svc("kill", "envios")
    rc, out = svc("start", "envios", {"ENVIOS_DESPACHO_SEGUNDOS": "8", "ENVIOS_DESPACHO_INTERVALO_SEGUNDOS": "1", "NOTIF_INTERVALO": "1"})
    s.check("Envios muere (kill -9) y reinicia: /ready 200", rc == 0, out[-80:])
    s.check("tras reiniciar Envios la notificacion sigue 'pendiente' (persistida en BD)", n_outbox(pid2, "pendiente") == "1", n_outbox(pid2))
    rc, out = svc("start", "pedidos")
    s.check("Pedidos reiniciado: /ready 200", rc == 0, out[-80:])
    ok, t = esperar(lambda: pedido(pid2, c2["tok"]).data["estado"] == "enviado", 40)
    s.check(f"la notificacion pendiente se entrega y el pedido pasa a 'enviado' ({t:.0f} s)", ok, pedido(pid2, c2["tok"]).data)
    s.check("outbox: 1 fila 'enviada'", n_outbox(pid2, "enviada") == "1" and n_outbox(pid2) == "1", n_outbox(pid2))
    # Restaurar la fase de escenarios 1-13 (despacho lento, ciclo de 3 s).
    svc("restart", "envios", {"NOTIF_INTERVALO": "3"})


@escenario(13, "Scheduler de Pedidos (schedule:work como el CMD del Dockerfile): recuperacion SIN intervencion")
def esc13(s):
    rc, out = svc("restart", "pedidos", {"E2E_SCHEDULER": "1"})
    s.check("Pedidos reiniciado con el CMD del Dockerfile (recuperar + schedule:work + servidor)", rc == 0, out[-80:])
    log = (TMP / "logs" / "pedidos.log").read_text(errors="replace")
    s.nota("log de arranque: " + " | ".join(l for l in log.splitlines() if "CMD del Dockerfile" in l or "Running" in l)[:300])
    uid, tok = nuevo_usuario()
    p = nuevo_producto("40.00", 20)
    agregar(uid, tok, p, 2)
    clave = str(uuid.uuid4())
    pagos0 = pagos_db()
    proxy(PROXY_CARRITO, modo="refuse", ruta="/finalizar", coincidencias=0)
    r = comprar(tok, clave)
    s.check("finalizar del Carrito falla a mitad de la compra => POST 503", r.status == 503, r)
    h = http("GET", f"{URL['pedidos']}/api/pedidos/usuario/{uid}", token=tok)
    pid = h.data[0]["id"]
    s.check("el pedido cobrado queda 'pagado' y el carrito aun tiene items",
            h.data[0]["estado"] == "pagado" and carrito(uid, tok).data["items"][0]["cantidad"] == 2, h.data[0]["estado"])
    # Se reinicia Carrito (kill -9 + start) y se restablece el proxy; a partir de aqui NADIE toca Pedidos.
    svc("kill", "carrito")
    rc, out = svc("start", "carrito")
    proxy(PROXY_CARRITO, modo="pass", ruta="", coincidencias=0)
    s.check("Carrito reiniciado (kill -9 + start) y proxy en modo normal", rc == 0, out[-80:])
    ok, t = esperar(lambda: carrito(uid, tok).data["items"] == [], 110, 2)
    s.check(f"SIN intervencion el scheduler completa el pedido: carrito vaciado en {t:.0f} s (limite 110 s)", ok, carrito(uid, tok).data)
    log = (TMP / "logs" / "pedidos.log").read_text(errors="replace")
    ejecuciones = [l.strip() for l in log.splitlines() if "pedidos:recuperar" in l]
    s.nota("log del contenedor (pedidos:recuperar): " + " | ".join(ejecuciones)[-400:])
    s.check("el log del contenedor muestra la ejecucion programada de pedidos:recuperar", any("Running" in l for l in ejecuciones), ejecuciones[-3:])
    s.check("sin doble cobro: 1 pago aprobado del pedido y el total de pagos subio 1", pagos_db(f"pedido_id='{pid}'") == "1"
            and pagos_db(f"pedido_id='{pid}' and estado='aprobado'") == "1" and int(pagos_db()) == int(pagos0) + 1)
    est = inv()
    s.check("sin doble efecto: 1 guia, reserva confirmada, stock 20 -> 18 una vez",
            n_guias(pid) == "1" and est["reservas"][pid]["estado"] == "confirmada" and est["stock"][p]["fisico"] == 18, est["stock"][p])
    r = comprar(tok, clave)
    d = r.data or {}
    s.check("repetir la clave devuelve el MISMO pedido pagado (sin crear otro)", r.status == 201 and d.get("id") == pid and d.get("estado") == "pagado",
            f"HTTP {r.status} id={d.get('id')} esperado={pid} estado={d.get('estado')}")
    s.check("tras repetir: sigue 1 pago, 1 guia, carrito vacio", pagos_db(f"pedido_id='{pid}'") == "1" and n_guias(pid) == "1"
            and carrito(uid, tok).data["items"] == [])
    # Volver a Pedidos sin scheduler para que los escenarios siguientes sean deterministas.
    svc("restart", "pedidos")


@escenario(14, "Despacho automatico de Envios (3 s / barrido 1 s): en_transito, outbox entregado, pedido 'enviado', sin duplicar")
def esc14(s):
    cfg = {"ENVIOS_DESPACHO_SEGUNDOS": "3", "ENVIOS_DESPACHO_INTERVALO_SEGUNDOS": "1", "NOTIF_INTERVALO": "1"}
    rc, out = svc("restart", "envios", cfg)
    s.check("Envios reiniciado con ENVIOS_DESPACHO_SEGUNDOS=3 y ENVIOS_DESPACHO_INTERVALO_SEGUNDOS=1 (notificador 1 s)", rc == 0, out[-80:])
    c = compra_pagada()
    pid, guia = c["id"], c["guia"]
    ra = http("GET", f"{URL['envios']}/api/envios/rastreo/{guia}", token=c["tok"])
    s.nota(f"rastreo justo tras la compra: {ra.status} {ra.data}")
    ok, t = esperar(lambda: http("GET", f"{URL['envios']}/api/envios/rastreo/{guia}", token=c["tok"]).data["estado"] == "en_transito", 30, 0.5)
    s.check(f"sin tocar nada, el rastreo pasa a en_transito ({t:.1f} s tras la compra)", ok)
    ok, t = esperar(lambda: pedido(pid, c["tok"]).data["estado"] == "enviado", 30, 0.5)
    s.check(f"el pedido real pasa a 'enviado' ({t:.1f} s mas)", ok, pedido(pid, c["tok"]).data["estado"])
    ok, t = esperar(lambda: n_outbox(pid, "enviada") == "1", 15, 0.5)
    fila = sql("db_envios", "usr_envios", "PW_ENVIOS", f"select * from notificaciones_pedido where pedido_id='{pid}'")
    s.nota(f"outbox: {fila}")
    s.check("outbox: 1 fila 'enviada' (entregada)", ok and n_outbox(pid) == "1", n_outbox(pid))
    # Repetir: ni /generar ni esperar mas ciclos duplican guia, notificacion ni cambian el estado.
    gen = http("POST", URL["envios"] + "/api/envios/generar", {"pedido_id": pid, "direccion": DIRECCION}, idem(),
               service=ENV["T_PEDIDOS_ENVIOS"])
    s.nota(f"POST /generar tras el despacho => {gen.status} {gen.data}")
    time.sleep(6)
    ra = http("GET", f"{URL['envios']}/api/envios/rastreo/{guia}", token=c["tok"])
    s.check("repetir no duplica: 1 guia, 1 fila de outbox, rastreo sigue en_transito, pedido sigue 'enviado'",
            n_guias(pid) == "1" and n_outbox(pid) == "1" and ra.data["estado"] == "en_transito"
            and pedido(pid, c["tok"]).data["estado"] == "enviado", f"guias={n_guias(pid)} outbox={n_outbox(pid)} {ra.data}")
    s.check("repetir /generar despues del despacho no deshace el estado (200/201 con la misma guia o 409, nunca otra guia)",
            gen.status in (200, 201, 409) and (gen.status == 409 or gen.data["guia"] == guia), gen)
    # Otro envio: dos pedidos a la vez se despachan una vez cada uno.
    c2, c3 = compra_pagada(), compra_pagada()
    ok, t = esperar(lambda: all(pedido(x["id"], x["tok"]).data["estado"] == "enviado" for x in (c2, c3)), 40, 0.5)
    s.check(f"dos compras simultaneas se despachan solas ({t:.1f} s) con 1 fila de outbox cada una",
            ok and n_outbox(c2["id"]) == "1" and n_outbox(c3["id"]) == "1")
    # Restaurar la fase 'altos' (despacho lento): los escenarios 16 y 17 no deben despachar a destiempo.
    svc("restart", "envios", {"NOTIF_INTERVALO": "3"})


def pedidos_db(pid, cols="pago_id, guia, metodo_pago, estado"):
    """Fila del pedido en la BD de Pedidos (rol usr_pedidos), columnas separadas por '|'."""
    return sql("db_pedidos", "usr_pedidos", "PW_PEDIDOS", f"select {cols} from pedidos where id='{pid}'")


def campos_pedido(d):
    return {k: (d or {}).get(k, "<AUSENTE>") for k in ("guia", "pago_id", "metodo_pago")}


@escenario(16, "Campos del pedido (guia, pago_id, metodo_pago) por HTTP: creacion, detalle, historial, rechazo, 409, idempotencia, titularidad, PATCH, recuperacion")
def esc16(s):
    # (i) compra aprobada con tarjeta
    uid, tok = nuevo_usuario()
    p = nuevo_producto("25.00", 20)
    agregar(uid, tok, p, 2)
    clave = str(uuid.uuid4())
    r = comprar(tok, clave)
    d = r.data or {}
    pid = d.get("id", "")
    s.check("(i) POST => 201 estado pagado", r.status == 201 and d.get("estado") == "pagado", r)
    comp = http("GET", f"{URL['pagos']}/api/pagos/pedido/{pid}", token=tok)
    s.check("(i) Pagos: comprobante aprobado", comp.status == 200 and comp.data["estado"] == "aprobado", comp)
    pago_id = (comp.data or {}).get("id")
    guia_bd = guia_de(pid)
    det = pedido(pid, tok)
    hist = http("GET", f"{URL['pedidos']}/api/pedidos/usuario/{uid}", token=tok)
    h = next((x for x in (hist.data or []) if x["id"] == pid), {})
    for nombre, x in (("201", d), ("GET detalle", det.data), ("GET historial", h)):
        s.check(f"(i) {nombre}: guia string no nulo, pago_id uuid v4 = id del comprobante de Pagos, metodo_pago tarjeta_simulada, estado pagado",
                isinstance(x.get("guia"), str) and x["guia"] != "" and isinstance(x.get("pago_id"), str)
                and re.match(UUID4, x["pago_id"]) is not None and x["pago_id"] == pago_id
                and x.get("metodo_pago") == "tarjeta_simulada" and x.get("estado") == "pagado", campos_pedido(x))
    s.check("(i) la guia del pedido coincide con la guia real de la BD de Envios", d.get("guia") == guia_bd, f"{d.get('guia')} vs {guia_bd}")
    ra = http("GET", f"{URL['envios']}/api/envios/rastreo/{d.get('guia')}", token=tok)
    s.check("(i) el cliente rastrea con la guia que le da el pedido (descubrible por HTTP) => 200 preparando",
            ra.status == 200 and ra.data["estado"] == "preparando" and ra.data["pedido_id"] == pid, ra)
    fila = pedidos_db(pid)
    s.check("(i) BD de Pedidos: pago_id/guia/metodo/estado coinciden", fila == f"{pago_id}|{guia_bd}|tarjeta_simulada|pagado", fila)

    # (iv) misma Idempotency-Key => mismo pedido y mismos campos
    r2 = comprar(tok, clave)
    s.check("(iv) repetir la misma clave => 201 con el MISMO pedido y los mismos guia/pago_id/metodo_pago",
            r2.status == 201 and r2.data == d and campos_pedido(r2.data) == campos_pedido(d), campos_pedido(r2.data))
    s.check("(iv) sigue 1 pago y 1 guia", pagos_db(f"pedido_id='{pid}'") == "1" and n_guias(pid) == "1")

    # (v) titularidad
    uidB, tokB = nuevo_usuario()
    _, tokAdmin = nuevo_usuario("admin")
    rb = pedido(pid, tokB)
    s.check("(v) otro cliente no ve el pedido (403/404) y no recibe guia/pago_id en el cuerpo",
            rb.status in (403, 404) and "pago_id" not in rb.text and d["guia"] not in rb.text, rb)
    hb = http("GET", f"{URL['pedidos']}/api/pedidos/usuario/{uid}", token=tokB)
    s.check("(v) otro cliente no ve el historial de A (403/404)", hb.status in (403, 404) and pago_id not in hb.text, hb)
    ra_ = pedido(pid, tokAdmin)
    s.check("(v) admin SI ve el pedido con los tres campos", ra_.status == 200 and campos_pedido(ra_.data) == campos_pedido(d), ra_)

    # (vi) PATCH pagado -> enviado con el token de Envios devuelve los tres campos
    pr = http("PATCH", f"{URL['pedidos']}/api/pedidos/{pid}/estado", {"estado": "enviado"}, idem(), service=ENV["T_ENVIOS_PEDIDOS"])
    s.check("(vi) PATCH /estado pagado->enviado => 200 enviado con guia/pago_id/metodo_pago intactos",
            pr.status == 200 and pr.data["estado"] == "enviado" and campos_pedido(pr.data) == campos_pedido(d), pr)

    # (ii) pago rechazado con transferencia_simulada
    uid2, tok2 = nuevo_usuario()
    p2 = nuevo_producto("25.00", 20)
    agregar(uid2, tok2, p2, 1)
    r = comprar(tok2, str(uuid.uuid4()), metodo="transferencia_simulada")
    d2 = r.data or {}
    pid2 = d2.get("id", "")
    comp2 = http("GET", f"{URL['pagos']}/api/pagos/pedido/{pid2}", token=tok2)
    s.check("(ii) POST => 201 cancelado; Pagos: comprobante rechazado", r.status == 201 and d2.get("estado") == "cancelado"
            and comp2.status == 200 and comp2.data["estado"] == "rechazado", f"{r} | {comp2}")
    hist2 = http("GET", f"{URL['pedidos']}/api/pedidos/usuario/{uid2}", token=tok2)
    for nombre, x in (("201", d2), ("GET detalle", pedido(pid2, tok2).data), ("GET historial", (hist2.data or [{}])[0])):
        s.check(f"(ii) {nombre}: pago_id = comprobante rechazado (uuid v4), guia null, metodo transferencia_simulada, estado cancelado",
                x.get("pago_id") == (comp2.data or {}).get("id") and re.match(UUID4, x.get("pago_id") or "") is not None
                and x.get("guia") is None and x.get("metodo_pago") == "transferencia_simulada" and x.get("estado") == "cancelado",
                campos_pedido(x))
    s.check("(ii) BD de Pedidos: pago_id = comprobante, guia NULL", pedidos_db(pid2) == f"{comp2.data['id']}||transferencia_simulada|cancelado", pedidos_db(pid2))

    # (iii) stock insuficiente
    uid3, tok3 = nuevo_usuario()
    p3 = nuevo_producto("25.00", 10)
    agregar(uid3, tok3, p3, 5)
    set_stock(p3, 3)
    r = comprar(tok3, str(uuid.uuid4()))
    s.check("(iii) POST => 409", r.status == 409, r)
    hist3 = http("GET", f"{URL['pedidos']}/api/pedidos/usuario/{uid3}", token=tok3)
    h3 = (hist3.data or [{}])[0]
    s.check("(iii) historial: 1 pedido cancelado con pago_id null y guia null", hist3.status == 200 and len(hist3.data) == 1
            and h3.get("estado") == "cancelado" and h3.get("pago_id") is None and h3.get("guia") is None, h3)
    det3 = pedido(h3.get("id", ""), tok3)
    s.check("(iii) detalle: cancelado, pago_id null, guia null, metodo_pago presente (tarjeta_simulada)",
            det3.status == 200 and det3.data["estado"] == "cancelado" and det3.data["pago_id"] is None and det3.data["guia"] is None
            and det3.data["metodo_pago"] == "tarjeta_simulada", det3)
    s.check("(iii) BD de Pedidos: pago_id y guia NULL", pedidos_db(h3.get("id", "")) == "||tarjeta_simulada|cancelado", pedidos_db(h3.get("id", "")))

    # (vii) recuperacion de un pago incierto: Pagos cobra, se pierden respuesta y consulta, Pagos muere
    uid4, tok4 = nuevo_usuario()
    p4 = nuevo_producto("25.00", 20)
    agregar(uid4, tok4, p4, 1)
    clave4 = str(uuid.uuid4())
    proxy(PROXY_PAGOS, modo="drop_response", ruta="/api/pagos/", coincidencias=0)
    r = comprar(tok4, clave4)
    h4 = http("GET", f"{URL['pedidos']}/api/pedidos/usuario/{uid4}", token=tok4)
    pid4 = (h4.data or [{}])[0].get("id", "")
    s.check("(vii) cobro hecho, respuesta y consulta perdidas => POST 503, pedido pendiente", r.status == 503
            and h4.data[0]["estado"] == "pendiente", f"{r} | {h4.data}")
    s.check("(vii) mientras es incierto: pago_id aun null (HTTP y BD) y guia null", h4.data[0]["pago_id"] is None
            and h4.data[0]["guia"] is None and pedidos_db(pid4, "pago_id is null") == "t")
    svc("kill", "pagos")
    proxy(PROXY_PAGOS, modo="pass", ruta="", coincidencias=0)
    rc, out = svc("start", "pagos")
    s.check("(vii) Pagos reiniciado (kill -9 + start): /ready 200", rc == 0, out[-80:])
    time.sleep(6)  # backoff inicial de 5 s
    for _ in range(6):  # sin cliente: pedidos:recuperar con las mismas claves
        rc, out = svc("start", "pedidos-recuperar")
        if pedido(pid4, tok4).data["estado"] == "pagado":
            break
        time.sleep(8)
    s.nota("pedidos:recuperar => " + out.replace("\n", " | ")[-200:])
    comp4 = http("GET", f"{URL['pagos']}/api/pagos/pedido/{pid4}", token=tok4)
    det4 = pedido(pid4, tok4)
    s.check("(vii) tras reiniciar Pagos y pedidos:recuperar el pedido queda pagado con pago_id = comprobante de Pagos (aprobado)",
            det4.data["estado"] == "pagado" and comp4.data["estado"] == "aprobado" and det4.data["pago_id"] == comp4.data["id"],
            f"{campos_pedido(det4.data)} comprobante={(comp4.data or {}).get('id')}")
    s.check("(vii) BD de Pedidos: pago_id = comprobante; 1 solo pago; guia presente", pedidos_db(pid4, "pago_id") == comp4.data["id"]
            and pagos_db(f"pedido_id='{pid4}'") == "1" and det4.data["guia"] == guia_de(pid4), pedidos_db(pid4))
    r = comprar(tok4, clave4)
    s.check("(vii) repetir la clave => 201 mismo pedido con los mismos campos", r.status == 201 and r.data["id"] == pid4
            and campos_pedido(r.data) == campos_pedido(det4.data), campos_pedido(r.data))


def admin_envios(query):
    """SQL con el rol postgres del PG temporal e2e: SOLO para instalar/retirar el trigger de auditoria de la prueba."""
    out = subprocess.run(
        ["docker", "exec", "-e", "PGPASSWORD=" + ENV["PG_PASSWORD"], "mojarra-pg-e2e", "psql", "-h", "127.0.0.1",
         "-U", "postgres", "-d", "db_envios", "-v", "ON_ERROR_STOP=1", "-Atc", query], capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip())
    return out.stdout.strip()


AUDITORIA_ON = """
create table if not exists e2e_auditoria_envios (id bigserial primary key, guia text, antes text, despues text,
  ts timestamptz default clock_timestamp(), despachado_en timestamptz);
grant all on e2e_auditoria_envios to usr_envios;
grant usage on sequence e2e_auditoria_envios_id_seq to usr_envios;
create or replace function e2e_audit() returns trigger language plpgsql as $f$
begin insert into e2e_auditoria_envios(guia, antes, despues, despachado_en) values (NEW.guia, OLD.estado, NEW.estado, NEW.despachado_en);
return NEW; end $f$;
drop trigger if exists e2e_audit on envios;
create trigger e2e_audit after update on envios for each row execute function e2e_audit();
"""
AUDITORIA_OFF = "drop trigger if exists e2e_audit on envios; drop function if exists e2e_audit(); drop table if exists e2e_auditoria_envios;"


def transiciones(guia):
    """Todas las UPDATE de la fila del envio (cualquier UPDATE, aunque no cambie el estado), en orden."""
    return [x for x in sql("db_envios", "usr_envios", "PW_ENVIOS",
                           f"select antes||'>'||despues from e2e_auditoria_envios where guia='{guia}' order by id").splitlines() if x]


def estado_envio_bd(guia):
    return sql("db_envios", "usr_envios", "PW_ENVIOS", f"select estado from envios where guia='{guia}'")


def rastreo(guia, tok, base="envios"):
    return http("GET", f"{URL[base]}/api/envios/rastreo/{guia}", token=tok, timeout=15)


def segs_desde_despacho(guia):
    return float(sql("db_envios", "usr_envios", "PW_ENVIOS", f"select extract(epoch from now()-despachado_en) from envios where guia='{guia}'"))


@escenario(17, "Entrega automatica de Envios: preparando -> en_transito -> entregado sin tocar nada; 2 instancias; reinicio; no antes de tiempo")
def esc17(s):
    cfg = {"ENVIOS_DESPACHO_SEGUNDOS": "3", "ENVIOS_ENTREGA_SEGUNDOS": "3", "ENVIOS_DESPACHO_INTERVALO_SEGUNDOS": "1", "NOTIF_INTERVALO": "1"}
    try:
        _esc17(s, cfg)
    finally:
        try:
            admin_envios(AUDITORIA_OFF)
        except Exception as e:
            s.nota(f"no se pudo retirar la auditoria: {e}")
        svc("kill", "envios2")
        svc("restart", "envios", {"NOTIF_INTERVALO": "3"})  # vuelve a la fase 'altos' (despacho y entrega lentos)


def _esc17(s, cfg):
    rc, out = svc("restart", "envios", cfg)
    s.check("Envios reiniciado con ENVIOS_DESPACHO_SEGUNDOS=3, ENVIOS_ENTREGA_SEGUNDOS=3, ENVIOS_DESPACHO_INTERVALO_SEGUNDOS=1", rc == 0, out[-80:])
    admin_envios(AUDITORIA_ON)
    s.nota("instrumentacion de la prueba: trigger AFTER UPDATE en db_envios.envios que registra cada UPDATE (solo en el PG temporal; se retira al final)")

    # ---- A) sin tocar nada: preparando -> en_transito -> entregado, en orden
    # Las guias 'preparando' de escenarios anteriores se despachan al reiniciar con despacho a 3 s: se espera a que se asienten.
    ok, t = esperar(lambda: sql("db_envios", "usr_envios", "PW_ENVIOS", "select count(*) from envios where estado='preparando'") == "0", 30, 1)
    s.check(f"(A) guias antiguas en 'preparando' ya despachadas por el barrido ({t:.0f} s)", ok)
    time.sleep(3)
    total0 = int(sql("db_envios", "usr_envios", "PW_ENVIOS", "select count(*) from notificaciones_pedido"))
    c = compra_pagada()
    pid, guia = c["id"], c["guia"]
    t0, seq, tiempos = time.time(), [], {}
    while time.time() - t0 < 25:
        r = rastreo(guia, c["tok"])
        e = r.data["estado"] if r.status == 200 else f"HTTP{r.status}"
        if not seq or seq[-1] != e:
            seq.append(e)
            tiempos[e] = time.time() - t0
        if e == "entregado":
            break
        time.sleep(0.3)
    s.nota("secuencia de rastreo observada (s tras terminar la compra): " + ", ".join(f"{e}@{tiempos[e]:.1f}" for e in seq))
    s.check("(A) el rastreo recorre preparando -> en_transito -> entregado, en ese orden, sin intervencion", seq == ["preparando", "en_transito", "entregado"], seq)
    tr = transiciones(guia)
    s.check("(A) la BD registra exactamente 2 UPDATE del envio: preparando>en_transito y en_transito>entregado", tr == ["preparando>en_transito", "en_transito>entregado"], tr)
    desp = sql("db_envios", "usr_envios", "PW_ENVIOS", f"select despachado_en is not null from envios where guia='{guia}'")
    s.check("(A) despachado_en persistido en la BD de Envios", desp == "t", desp)
    d_entrega = sql("db_envios", "usr_envios", "PW_ENVIOS",
                    f"select round(extract(epoch from (select ts from e2e_auditoria_envios where guia='{guia}' and despues='entregado') - despachado_en)::numeric, 1) from envios where guia='{guia}'")
    s.check(f"(A) la entrega ocurre >= 3 s despues de despachado_en (segun la BD: {d_entrega} s) y no mucho mas tarde (< 8 s)", 3.0 <= float(d_entrega) < 8.0, d_entrega)
    ok, t = esperar(lambda: pedido(pid, c["tok"]).data["estado"] == "enviado", 15, 0.5)
    s.check("(A) el pedido en Pedidos esta 'enviado' (por la notificacion del despacho)", ok, pedido(pid, c["tok"]).data["estado"])
    ok, _ = esperar(lambda: n_outbox(pid, "enviada") == "1", 10, 0.5)
    total1 = int(sql("db_envios", "usr_envios", "PW_ENVIOS", "select count(*) from notificaciones_pedido"))
    time.sleep(6)  # varios barridos y ciclos del Notificador despues de la entrega
    total2 = int(sql("db_envios", "usr_envios", "PW_ENVIOS", "select count(*) from notificaciones_pedido"))
    s.check("(A) el pedido NO pasa a 'entregado': permanece 'enviado' 6 s despues de la entrega", pedido(pid, c["tok"]).data["estado"] == "enviado", pedido(pid, c["tok"]).data["estado"])
    s.check(f"(A) outbox: 1 fila 'enviada' del pedido y solo +1 fila global (el despacho; {total0} -> {total1} -> {total2}); la entrega no encola nada",
            ok and n_outbox(pid) == "1" and total1 == total0 + 1 and total2 == total1, f"{total0} {total1} {total2}")
    gen = http("POST", URL["envios"] + "/api/envios/generar", {"pedido_id": pid, "direccion": DIRECCION}, idem(), service=ENV["T_PEDIDOS_ENVIOS"])
    time.sleep(3)
    s.nota(f"POST /generar tras la entrega => {gen.status} {gen.data}")
    s.check("(A) repetir /generar y esperar no duplica ni deshace: 1 guia, misma guia (o 409), rastreo entregado, outbox 1, mismas 2 transiciones",
            n_guias(pid) == "1" and (gen.status == 409 or (gen.status in (200, 201) and gen.data["guia"] == guia))
            and rastreo(guia, c["tok"]).data["estado"] == "entregado" and n_outbox(pid) == "1" and transiciones(guia) == tr,
            f"{gen.status} {rastreo(guia, c['tok']).data} {transiciones(guia)}")
    s.check("(A) titularidad intacta: otro cliente no rastrea la guia entregada (403/404)", rastreo(guia, nuevo_usuario()[1]).status in (403, 404))

    # ---- B) segunda instancia (otro puerto, misma BD): la transicion ocurre una sola vez por envio
    rc, out = svc("start", "envios2", cfg)
    s.check("(B) 2a instancia de Envios en el puerto 8013 (misma BD) lista: /ready 200", rc == 0, out[-80:])
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(3) as ex:  # 3 en paralelo: Pedidos de pruebas tiene 4 workers PHP y Pagos le llama de vuelta
        compras = list(ex.map(lambda _: compra_pagada(), range(3)))
    t0 = time.time()
    ok, t = esperar(lambda: all(estado_envio_bd(x["guia"]) == "entregado" for x in compras), 30, 0.5)
    s.check(f"(B) 3 compras simultaneas con 2 instancias barriendo: las 3 quedan 'entregado' sin intervencion ({t:.1f} s)", ok, [estado_envio_bd(x["guia"]) for x in compras])
    time.sleep(4)
    trs = [transiciones(x["guia"]) for x in compras]
    s.check("(B) cada envio tiene exactamente 2 UPDATE (preparando>en_transito, en_transito>entregado): nadie entrego dos veces ni despacho dos veces",
            all(x == ["preparando>en_transito", "en_transito>entregado"] for x in trs), trs)
    ok, _ = esperar(lambda: all(pedido(x["id"], x["tok"]).data["estado"] == "enviado" for x in compras), 20, 0.5)
    s.check("(B) los 3 pedidos 'enviado' (ninguno 'entregado') y 1 fila de outbox 'enviada' cada uno",
            ok and all(n_outbox(x["id"]) == "1" and n_outbox(x["id"], "enviada") == "1" for x in compras))
    r1, r2 = rastreo(compras[0]["guia"], compras[0]["tok"], "envios"), rastreo(compras[0]["guia"], compras[0]["tok"], "envios2")
    s.check("(B) ambas instancias muestran el mismo rastreo 'entregado'", r1.status == r2.status == 200 and r1.data == r2.data and r1.data["estado"] == "entregado", f"{r1.data} | {r2.data}")
    svc("kill", "envios2")

    # ---- C) no entrega antes de tiempo: ENVIOS_ENTREGA_SEGUNDOS=60
    rc, out = svc("restart", "envios", {**cfg, "ENVIOS_ENTREGA_SEGUNDOS": "60"})
    s.check("(C) Envios reiniciado con ENVIOS_ENTREGA_SEGUNDOS=60 (despacho 3 s)", rc == 0, out[-80:])
    c = compra_pagada()
    guia = c["guia"]
    ok, t = esperar(lambda: estado_envio_bd(guia) == "en_transito", 20, 0.5)
    s.check(f"(C) despacha solo ({t:.1f} s)", ok, estado_envio_bd(guia))
    time.sleep(15)
    edad = segs_desde_despacho(guia)
    r = rastreo(guia, c["tok"])
    s.check(f"(C) {edad:.0f} s despues del despacho (< 60) sigue en_transito, sin entregar antes de tiempo",
            15 <= edad < 60 and r.data["estado"] == "en_transito" and transiciones(guia) == ["preparando>en_transito"], f"{edad:.1f} {r.data} {transiciones(guia)}")

    # ---- D) reinicio: se apaga Envios tras el despacho, vence el plazo con el servicio apagado, se reinicia
    cfgD = {**cfg, "ENVIOS_ENTREGA_SEGUNDOS": "12"}
    rc, out = svc("restart", "envios", cfgD)
    s.check("(D) Envios reiniciado con ENVIOS_ENTREGA_SEGUNDOS=12", rc == 0, out[-80:])
    c = compra_pagada()
    guia, pid = c["guia"], c["id"]
    ok, t = esperar(lambda: estado_envio_bd(guia) == "en_transito", 20, 0.3)
    s.check(f"(D) despachado ({t:.1f} s)", ok, estado_envio_bd(guia))
    svc("kill", "envios")
    s.check("(D) Envios apagado (kill -9): puerto 8003 cerrado", http("GET", URL["envios"] + "/health", timeout=3).status == 0)
    ok, t = esperar(lambda: segs_desde_despacho(guia) > 14, 30, 1)
    s.check(f"(D) con Envios apagado vence el plazo (despachado hace {segs_desde_despacho(guia):.0f} s > 12 s) y la BD sigue en_transito (nadie entrega)",
            ok and estado_envio_bd(guia) == "en_transito" and transiciones(guia) == ["preparando>en_transito"], f"{estado_envio_bd(guia)} {transiciones(guia)}")
    rc, out = svc("start", "envios", cfgD)
    s.check("(D) Envios reiniciado: /ready 200", rc == 0, out[-80:])
    ok, t = esperar(lambda: estado_envio_bd(guia) == "entregado", 15, 0.5)
    s.check(f"(D) tras reiniciar entrega sin intervencion ({t:.1f} s)", ok, estado_envio_bd(guia))
    ok2, _ = esperar(lambda: pedido(pid, c["tok"]).data["estado"] == "enviado", 15, 0.5)
    s.check("(D) rastreo entregado, pedido 'enviado' (no 'entregado'), 2 transiciones, outbox 1",
            rastreo(guia, c["tok"]).data["estado"] == "entregado" and ok2 and transiciones(guia) == ["preparando>en_transito", "en_transito>entregado"]
            and n_outbox(pid) == "1", f"{transiciones(guia)} {pedido(pid, c['tok']).data['estado']}")


def cuerpo_grande(extra=None, kib=300):
    d = dict(extra or {})
    d["relleno"] = "x" * (kib * 1024)
    return json.dumps(d).encode()


@escenario(15, "Limites con valores por defecto: 6o checkout 429, cuerpo >256 KiB 413, health/ready exentos, 401, 130 GET => 429 tras 120")
def esc15(s):
    os.environ["E2E_FASE"] = "default"
    os.environ.pop("ENVIOS_DESPACHO_SEGUNDOS", None)
    os.environ.pop("ENVIOS_DESPACHO_INTERVALO_SEGUNDOS", None)
    for n in ("pedidos", "carrito", "pagos", "envios"):
        svc("kill", n)
    for n in ("carrito", "envios", "pagos", "pedidos"):
        rc, out = svc("start", n)
        s.check(f"{n} reiniciado SIN variables de limite (valores por defecto)", rc == 0, out[-80:])
    # --- a) 6o POST /api/pedidos del mismo usuario en 1 minuto
    uid, tok = nuevo_usuario()
    p = nuevo_producto("10.00", 50)
    agregar(uid, tok, p, 1)
    codigos, ultima = [], None
    for i in range(6):
        r = comprar(tok, str(uuid.uuid4()))
        codigos.append(r.status)
        ultima = r
    s.nota(f"codigos de los 6 POST /api/pedidos del mismo usuario: {codigos}")
    s.check("los 5 primeros POST no dan 429 (1o 201 real; el resto 409 carrito vacio, pero admitidos)",
            codigos[0] == 201 and all(c != 429 for c in codigos[:5]), codigos)
    ra = ultima.headers.get("Retry-After") or ultima.headers.get("retry-after")
    s.check("el 6o => 429 con Retry-After numerico > 0", codigos[5] == 429 and (ra or "").isdigit() and int(ra) > 0, f"{ultima} Retry-After={ra}")
    # --- b) cuerpo > 256 KiB => 413 en los 4 servicios (con credencial valida; sin ella prevalece el 401)
    uid2, tok2 = nuevo_usuario()
    uid3, tok3 = nuevo_usuario()
    H = {"Content-Type": "application/json"}
    casos = {
        "carrito": ("POST", f"{URL['carrito']}/api/carrito/{uid2}/agregar", {"token": tok2, "headers": {"Idempotency-Key": str(uuid.uuid4())}}),
        "pedidos": ("POST", f"{URL['pedidos']}/api/pedidos", {"token": tok3, "headers": {"Idempotency-Key": str(uuid.uuid4())}}),
        "pagos": ("POST", f"{URL['pagos']}/api/pagos/procesar", {"service": ENV["T_PEDIDOS_PAGOS"], "headers": {"Idempotency-Key": str(uuid.uuid4())}}),
        "envios": ("POST", f"{URL['envios']}/api/envios/cotizar", {"token": tok2, "headers": {}}),
    }
    for n, (m, u, kw) in casos.items():
        r = http(m, u, raw=cuerpo_grande({"codigo_postal": "06600", "cantidad": 1}), headers={**H, **kw["headers"]},
                 token=kw.get("token"), service=kw.get("service"))
        s.check(f"{n}: cuerpo de 300 KiB => 413", r.status == 413, r)
    r = http("POST", casos["envios"][1], raw=cuerpo_grande({"codigo_postal": "06600", "cantidad": 1}, 300), headers=H)
    s.check("sin credencial y cuerpo grande sigue 401 (Envios)", r.status == 401, r)
    r = http("POST", casos["envios"][1], raw=cuerpo_grande({"codigo_postal": "06600", "cantidad": 1}, 200), headers=H, token=tok2)
    s.check("cuerpo de 200 KiB (bajo el tope) no da 413 (Envios cotizar)", r.status != 413, r)
    # --- c) /health y /ready exentos (>120 peticiones) y no consumen el cupo del usuario
    uid4, tok4 = nuevo_usuario()
    for n in ("carrito", "pedidos", "pagos", "envios"):
        peores = {"health": set(), "ready": set()}
        for ruta in ("health", "ready"):
            for _ in range(130):
                peores[ruta].add(http("GET", f"{URL[n]}/{ruta}", timeout=15).status)
        s.check(f"{n}: 130 x /health y 130 x /ready => solo 200 (sin 429)", peores == {"health": {200}, "ready": {200}}, peores)
    # --- d) 401 sin credencial (cubo anonimo propio) y 130 GET autenticados => 429 tras 120
    gets = {
        "carrito": f"{URL['carrito']}/api/carrito/{uid4}",
        "pedidos": f"{URL['pedidos']}/api/pedidos/usuario/{uid4}",
        "pagos": f"{URL['pagos']}/api/pagos/pedido/{uuid.uuid4()}",
        "envios": f"{URL['envios']}/api/envios/rastreo/{uuid.uuid4()}",
    }
    for n, u in gets.items():
        sin = http("GET", u)
        s.check(f"{n}: sin credencial => 401 (no 429)", sin.status == 401, sin)
        estados = [http("GET", u, token=tok4).status for _ in range(130)]
        primero = next((i + 1 for i, c in enumerate(estados) if c == 429), None)
        r = http("GET", u, token=tok4)
        ra = r.headers.get("Retry-After") or r.headers.get("retry-after")
        s.check(f"{n}: 130 GET autenticados (/health y /ready antes NO consumieron cupo): primer 429 en la peticion {primero} (esperado 121); sin 429 antes",
                primero == 121 and all(c != 429 for c in estados[:120]) and all(c == 429 for c in estados[120:]),
                f"{n} distintos={sorted(set(estados))} primer429={primero}")
        s.check(f"{n}: el 429 lleva Retry-After > 0", r.status == 429 and (ra or "").isdigit() and int(ra) > 0, f"{r.status} Retry-After={ra}")
        s.check(f"{n}: con el usuario saturado /health sigue 200 y la peticion sin credencial 401",
                http("GET", f"{URL[n]}/health").status == 200 and http("GET", u).status == 401)
    # Dejar el entorno en fase 'altos' no es necesario: es el ultimo escenario.


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
    elegidos = {int(a) for a in sys.argv[1:]}
    for fn in [f for f in [esc1, esc2, esc3, esc4, esc5, esc6, esc7, esc8, esc9, esc10, esc11, esc12, esc13, esc14, esc16, esc17, esc15] if not elegidos or f.num in elegidos]:
        fn()
    print("\n================ RESUMEN ================")
    for num, titulo, estado, fallos, nv in RESULTADOS:
        print(f"{num:>2}  {estado:<14} {titulo}" + (f"  ({fallos} comprobaciones fallidas)" if fallos else ""))
    print(f"duracion: {time.time() - t0:.0f} s")
    sys.exit(1 if any(r[2] == "FALLA" for r in RESULTADOS) else 0)


if __name__ == "__main__":
    main()
