"""Endpoints de Envíos. Cada ruta aplica identidad, regla de negocio y sobre de respuesta."""
from typing import Annotated
from uuid import UUID

from pydantic import UUID4
from fastapi import APIRouter, Depends, Header, Path, Request

from app.auth import Identidad, autenticar, solo_servicio
from app.cotizacion import CantidadFueraDeRango, cotizar
from app.errors import ApiError, ok
from app.schemas import CotizarIn, GenerarIn

router = APIRouter(prefix="/api/envios")

# Estados de pedido con pago aprobado (la guía solo existe para pedidos pagados).
ESTADOS_PAGADOS = {"pagado", "enviado"}


@router.post("/cotizar")
def cotizar_envio(cuerpo: CotizarIn, _: Annotated[Identidad, Depends(autenticar)]):
    try:
        costo, dias = cotizar(cuerpo.codigo_postal, cuerpo.cantidad)
    except CantidadFueraDeRango:
        raise ApiError(422, "Error de validación",
                       {"cantidad": ["El importe resultante excede el máximo representable"]}) from None
    return ok({"costo_envio": costo, "dias_estimados": dias})


@router.post("/generar")
def generar_guia(
    cuerpo: GenerarIn,
    request: Request,
    idempotency_key: Annotated[UUID4, Header(alias="Idempotency-Key")],
    llamador: Annotated[Identidad, Depends(solo_servicio)],
):
    state = request.app.state
    # Misma clave ya en ejecución: 409 inmediato en vez de esperar al primero.
    with state.en_curso.reservar(idempotency_key, llamador.nombre):
        # Un reintento idéntico recibe la respuesta guardada aunque Pedidos haya cambiado o caído.
        previo = state.repo.resultado_previo(idempotency_key, llamador.nombre, cuerpo)
        if previo is not None:
            return ok(previo, status=201)
        pedido = state.pedidos.obtener(cuerpo.pedido_id)
        if pedido.estado not in ESTADOS_PAGADOS:
            raise ApiError(409, "El pedido no está pagado")
        envio = state.repo.generar(idempotency_key, llamador.nombre, cuerpo)
        return ok(envio, status=201)


@router.get("/rastreo/{guia}")
def rastrear(
    guia: str,
    request: Request,
    identidad: Annotated[Identidad, Depends(autenticar)],
):
    state = request.app.state
    envio = state.repo.buscar_por_guia(guia)
    if envio is None:
        raise ApiError(404, "Guía no encontrada")
    if identidad.tipo == "usuario" and not identidad.es_admin:
        # Propiedad: el titular lo informa Pedidos; el sub del JWT debe coincidir.
        pedido = state.pedidos.obtener(UUID(envio["pedido_id"]))
        if pedido.usuario_id != identidad.nombre:
            raise ApiError(403, "Permiso insuficiente")
    return ok(envio)
