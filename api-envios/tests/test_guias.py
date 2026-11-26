from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from jsonschema import Draft4Validator

from tests.conftest import DIRECCION, SERVICIO, bearer


def generar(client, pedido_id, clave=None, direccion=None, headers=SERVICIO):
    return client.post(
        "/api/envios/generar",
        json={"pedido_id": pedido_id, "direccion": direccion or DIRECCION},
        headers={**headers, "Idempotency-Key": clave or str(uuid4())},
    )


def contar(pool, tabla="envios"):
    with pool.connection() as conn:
        return conn.execute(f"SELECT count(*) FROM {tabla}").fetchone()[0]


def test_generar_crea_guia_contractual(client, pedidos):
    pedido_id = pedidos.agregar(str(uuid4()))
    r = generar(client, pedido_id)
    assert r.status_code == 201
    data = r.json()["data"]
    assert data["pedido_id"] == pedido_id and data["estado"] == "preparando" and data["guia"].startswith("ENV")
    spec = client.get("/openapi.json").json()
    schema = spec["paths"]["/api/envios/generar"]["post"]["responses"]["201"]["content"]["application/json"]["schema"]
    Draft4Validator(schema).validate(r.json())


def test_repetir_misma_clave_devuelve_misma_guia(client, pedidos, pool):
    pedido_id, clave = pedidos.agregar(str(uuid4())), str(uuid4())
    a, b = generar(client, pedido_id, clave), generar(client, pedido_id, clave)
    assert a.status_code == b.status_code == 201 and a.json() == b.json()
    assert contar(pool) == 1


def test_reintento_identico_no_depende_de_pedidos(client, pedidos, pool):
    pedido_id, clave = pedidos.agregar(str(uuid4())), str(uuid4())
    a = generar(client, pedido_id, clave)
    pedidos.caido = True  # el reintento idéntico recibe lo guardado, no 503
    b = generar(client, pedido_id, clave)
    assert a.status_code == b.status_code == 201 and a.json() == b.json() and contar(pool) == 1
    # Misma clave con otro payload sigue siendo 409 aunque Pedidos esté caído.
    assert generar(client, pedido_id, clave, direccion={**DIRECCION, "calle": "Otra 2"}).status_code == 409


def test_clave_nueva_mismo_pedido_devuelve_misma_guia(client, pedidos, pool):
    pedido_id = pedidos.agregar(str(uuid4()))
    a, b = generar(client, pedido_id), generar(client, pedido_id)
    assert a.status_code == b.status_code == 201
    assert a.json()["data"] == b.json()["data"] and contar(pool) == 1


def test_clave_nueva_mismo_pedido_otra_direccion_409(client, pedidos, pool):
    pedido_id, clave = pedidos.agregar(str(uuid4())), str(uuid4())
    original = generar(client, pedido_id)
    distinto = generar(client, pedido_id, clave, direccion={**DIRECCION, "calle": "Otra 2"})
    assert original.status_code == 201
    assert distinto.status_code == 409 and distinto.json()["success"] is False
    assert contar(pool) == 1 and contar(pool, "idempotencia") == 1
    # La clave rechazada no queda asociada a la dirección equivocada.
    repetido = generar(client, pedido_id, clave)
    assert repetido.status_code == 201 and repetido.json()["data"] == original.json()["data"]


def test_misma_clave_otro_payload_409(client, pedidos):
    pedido_id, clave = pedidos.agregar(str(uuid4())), str(uuid4())
    assert generar(client, pedido_id, clave).status_code == 201
    r = generar(client, pedido_id, clave, direccion={**DIRECCION, "calle": "Otra 2"})
    assert r.status_code == 409 and r.json()["success"] is False


def test_solicitudes_concurrentes_crean_una_sola_guia(client, pedidos, pool):
    pedido_id = pedidos.agregar(str(uuid4()))
    with ThreadPoolExecutor(8) as ex:
        respuestas = list(ex.map(lambda _: generar(client, pedido_id), range(8)))
    assert {r.status_code for r in respuestas} == {201}
    assert len({r.json()["data"]["guia"] for r in respuestas}) == 1 and contar(pool) == 1


def test_pedido_no_pagado_409_sin_guia(client, pedidos, pool):
    pedido_id = pedidos.agregar(str(uuid4()), estado="pendiente")
    assert generar(client, pedido_id).status_code == 409
    assert contar(pool) == 0


def test_pedido_inexistente_404_y_pedidos_caido_503(client, pedidos):
    assert generar(client, str(uuid4())).status_code == 404
    pedidos.caido = True
    assert generar(client, str(uuid4())).status_code == 503


def test_generar_solo_identidad_interna(client, pedidos, make_token):
    pedido_id = pedidos.agregar(str(uuid4()))
    assert generar(client, pedido_id, headers={}).status_code == 401
    assert generar(client, pedido_id, headers=bearer(make_token(role="admin"))).status_code == 403


def test_generar_validaciones(client, pedidos):
    pedido_id = pedidos.agregar(str(uuid4()))
    sin_clave = client.post("/api/envios/generar", json={"pedido_id": pedido_id, "direccion": DIRECCION}, headers=SERVICIO)
    assert sin_clave.status_code == 422
    assert generar(client, pedido_id, clave="no-uuid").status_code == 422
    assert generar(client, "no-uuid").status_code == 422
    assert generar(client, pedido_id, direccion={**DIRECCION, "codigo_postal": "1"}).status_code == 422
    extra = client.post("/api/envios/generar", json={"pedido_id": pedido_id, "direccion": DIRECCION, "x": 1},
                        headers={**SERVICIO, "Idempotency-Key": str(uuid4())})
    assert extra.status_code == 422


# --- rastreo y propiedad ---

def guia_de(client, pedidos, usuario_id):
    pedido_id = pedidos.agregar(usuario_id)
    return generar(client, pedido_id).json()["data"]


def rastrear(client, guia, headers):
    return client.get(f"/api/envios/rastreo/{guia}", headers=headers)


def test_titular_rastrea_su_guia(client, pedidos, make_token):
    titular = str(uuid4())
    envio = guia_de(client, pedidos, titular)
    r = rastrear(client, envio["guia"], bearer(make_token(sub=titular)))
    assert r.status_code == 200 and r.json()["data"] == envio


def test_otro_cliente_recibe_403(client, pedidos, make_token):
    envio = guia_de(client, pedidos, str(uuid4()))
    r = rastrear(client, envio["guia"], bearer(make_token(sub=str(uuid4()))))
    assert r.status_code == 403 and r.json()["success"] is False


def test_admin_y_servicio_rastrean_cualquier_guia(client, pedidos, make_token):
    envio = guia_de(client, pedidos, str(uuid4()))
    assert rastrear(client, envio["guia"], bearer(make_token(role="admin"))).status_code == 200
    assert rastrear(client, envio["guia"], SERVICIO).status_code == 200


def test_rastreo_sin_credencial_401_y_guia_inexistente_404(client, pedidos, make_token):
    envio = guia_de(client, pedidos, str(uuid4()))
    assert rastrear(client, envio["guia"], {}).status_code == 401
    assert rastrear(client, "ENV000000000000", bearer(make_token())).status_code == 404


def test_pedidos_caido_no_autoriza_cliente_pero_admin_si(client, pedidos, make_token):
    titular = str(uuid4())
    envio = guia_de(client, pedidos, titular)
    pedidos.caido = True
    assert rastrear(client, envio["guia"], bearer(make_token(sub=titular))).status_code == 503
    assert rastrear(client, envio["guia"], bearer(make_token(role="admin"))).status_code == 200


def test_misma_clave_en_curso_409_inmediato_y_reintento_devuelve_la_guia(client, pedidos, pool):
    import time
    pedido_id = pedidos.agregar(str(uuid4()))
    clave = str(uuid4())
    original = pedidos.obtener

    def lento(pid):
        time.sleep(1.0)
        return original(pid)

    pedidos.obtener = lento
    with ThreadPoolExecutor(2) as ex:
        primera = ex.submit(generar, client, pedido_id, clave)
        time.sleep(0.3)
        t0 = time.monotonic()
        segunda = generar(client, pedido_id, clave)
        assert time.monotonic() - t0 < 0.5
        assert segunda.status_code == 409 and segunda.json()["success"] is False
        assert primera.result().status_code == 201
    pedidos.obtener = original
    otra = generar(client, pedido_id, clave)
    assert otra.status_code == 201 and otra.json()["data"] == primera.result().json()["data"]
    assert contar(pool) == 1


def test_clave_en_curso_en_otra_replica_409_por_bloqueo_de_bd(client, pedidos, pool):
    from uuid import UUID
    pedido_id = pedidos.agregar(str(uuid4()))
    clave = str(uuid4())
    with pool.connection() as conn:  # simula otra réplica dentro de su transacción
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"clave:{UUID(clave)}",))
        assert generar(client, pedido_id, clave).status_code == 409
    assert generar(client, pedido_id, clave).status_code == 201


def test_uuid_distinto_de_v4_se_rechaza(client, pedidos):
    v1 = "c232ab00-9414-11ec-b3c8-9f6bdeced846"
    ok_id = pedidos.agregar(str(uuid4()))
    assert generar(client, v1).status_code == 422
    assert generar(client, ok_id, clave=v1).status_code == 422
    assert generar(client, ok_id, clave="no-es-uuid").status_code == 422


def test_sin_limites_propios_mas_estrictos_que_el_contrato(client, pedidos):
    largo = {**DIRECCION, "calle": "x" * 500, "ciudad": ""}
    assert generar(client, pedidos.agregar(str(uuid4())), direccion=largo).status_code == 201
    r = client.post("/api/envios/cotizar", json={"codigo_postal": "06600", "cantidad": 10**6},
                    headers=SERVICIO)
    assert r.status_code == 200
    assert client.get("/api/envios/rastreo/" + "G" * 100, headers=SERVICIO).status_code == 404
