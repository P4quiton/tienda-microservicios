"""Proxy TCP con inyeccion de fallos entre Pedidos y una dependencia (Pagos/Carrito).

Uso: python fault_proxy.py PUERTO_ESCUCHA PUERTO_DESTINO PUERTO_CONTROL
Modos (POST http://127.0.0.1:CONTROL/modo  {"modo": "...", "ruta": "subcadena"}):
  pass            reenvia todo.
  drop_response   si la ruta de la peticion contiene `ruta`, la reenvia al destino (el efecto SE PRODUCE),
                  descarta la respuesta y cierra la conexion: el cliente ve un resultado incierto.
  delay           si la ruta contiene `ruta`, espera `segundos` antes de reenviar (el efecto ocurre tarde).
  refuse          si la ruta contiene `ruta`, cierra la conexion sin reenviar (el efecto NO se produce).
`ruta` vacia = todas las rutas. GET /contador devuelve cuantas peticiones se descartaron.
"""
import json
import socket
import sys
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

ESTADO = {"modo": "pass", "ruta": "", "descartadas": 0, "coincidencias": 0, "segundos": 0}


def _leer_peticion(conn):
    datos = b""
    while b"\r\n\r\n" not in datos:
        trozo = conn.recv(65536)
        if not trozo:
            return datos
        datos += trozo
    cab, _, resto = datos.partition(b"\r\n\r\n")
    largo = 0
    for linea in cab.split(b"\r\n")[1:]:
        k, _, v = linea.partition(b":")
        if k.strip().lower() == b"content-length":
            largo = int(v.strip())
    while len(resto) < largo:
        trozo = conn.recv(65536)
        if not trozo:
            break
        resto += trozo
    return cab + b"\r\n\r\n" + resto


def _atender(conn, destino):
    try:
        conn.settimeout(30)
        peticion = _leer_peticion(conn)
        if not peticion:
            return
        linea = peticion.split(b"\r\n", 1)[0].decode(errors="replace")
        aplica = ESTADO["modo"] != "pass" and ESTADO["ruta"] in linea
        if aplica:
            ESTADO["coincidencias"] += 1
        if aplica and ESTADO["modo"] == "delay":
            time.sleep(float(ESTADO["segundos"]))
        if aplica and ESTADO["modo"] == "refuse":
            ESTADO["descartadas"] += 1
            return
        # Se fuerza Connection: close para poder delimitar la respuesta por cierre.
        cab, _, cuerpo = peticion.partition(b"\r\n\r\n")
        lineas = [l for l in cab.split(b"\r\n") if not l.lower().startswith(b"connection:")]
        lineas.append(b"Connection: close")
        peticion = b"\r\n".join(lineas) + b"\r\n\r\n" + cuerpo
        with socket.create_connection(("127.0.0.1", destino), timeout=30) as up:
            up.sendall(peticion)
            respuesta = b""
            while True:
                trozo = up.recv(65536)
                if not trozo:
                    break
                respuesta += trozo
        if aplica and ESTADO["modo"] == "drop_response":
            ESTADO["descartadas"] += 1
            return
        conn.sendall(respuesta)
    except OSError:
        pass
    finally:
        conn.close()


class Control(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _out(self):
        raw = json.dumps(ESTADO).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._out()

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        ESTADO.update(json.loads(self.rfile.read(n) or b"{}"))
        self._out()


if __name__ == "__main__":
    escucha, destino, control = map(int, sys.argv[1:4])
    threading.Thread(target=HTTPServer(("127.0.0.1", control), Control).serve_forever, daemon=True).start()
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", escucha))
    srv.listen(64)
    while True:
        c, _ = srv.accept()
        threading.Thread(target=_atender, args=(c, destino), daemon=True).start()
