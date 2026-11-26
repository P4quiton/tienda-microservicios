"""Identificadores: el contrato (docs/contratos-api.md) exige UUID v4 en todo identificador."""
from uuid import UUID


def uuid_v4(valor: object) -> str:
    """Normaliza a texto canónico; ValueError si no es un UUID v4 válido."""
    uuid = UUID(str(valor))
    if uuid.version != 4:
        raise ValueError("No es UUID v4")
    return str(uuid)
