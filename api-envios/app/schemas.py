"""Cuerpos de entrada. Campos no declarados se rechazan (extra=forbid)."""
from typing import Annotated

from pydantic import UUID4, AfterValidator, BaseModel, ConfigDict, Field

CodigoPostal = Annotated[str, Field(pattern=r"^[0-9]{5}$")]


def _almacenable(valor: str) -> str:
    """PostgreSQL TEXT no admite NUL ni sustitutos UTF-16 sueltos; sin esto la BD responde 500."""
    if "\x00" in valor:
        raise ValueError("No puede contener caracteres NUL")
    try:
        valor.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("Contiene caracteres Unicode inválidos") from None
    return valor


# El contrato no declara longitudes: no se imponen límites propios, solo que sea almacenable.
Texto = Annotated[str, AfterValidator(_almacenable)]


class Estricto(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CotizarIn(Estricto):
    codigo_postal: CodigoPostal
    cantidad: Annotated[int, Field(ge=1, strict=True)]


class DireccionIn(Estricto):
    codigo_postal: CodigoPostal
    calle: Texto
    ciudad: Texto
    estado: Texto


class GenerarIn(Estricto):
    pedido_id: UUID4
    direccion: DireccionIn
