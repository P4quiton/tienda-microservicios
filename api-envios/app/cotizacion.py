"""Cotización simulada y determinista: depende solo de código postal y cantidad.

Regla (MXN): base 89.00 + 10.00 por dígito de zona (primer dígito del CP)
+ 25.00 por cada unidad adicional a la primera. Días: 2 + zona // 3.
Pedidos recalcula con esta misma regla; no hay peso en el MVP.
El contrato limita costo_envio a 10 enteros y 2 decimales: una cantidad cuyo importe no cabe es inválida.
"""
from decimal import Decimal

BASE = Decimal("89.00")
POR_ZONA = Decimal("10.00")
POR_UNIDAD_EXTRA = Decimal("25.00")
IMPORTE_MAXIMO = Decimal("9999999999.99")  # patrón de costo_envio en docs/api/envios.yaml


class CantidadFueraDeRango(ValueError):
    """El importe resultante no cabe en el formato decimal del contrato."""


def cotizar(codigo_postal: str, cantidad: int) -> tuple[str, int]:
    zona = int(codigo_postal[0])
    costo = BASE + POR_ZONA * zona + POR_UNIDAD_EXTRA * (cantidad - 1)
    if costo > IMPORTE_MAXIMO:
        raise CantidadFueraDeRango(cantidad)
    return f"{costo:.2f}", 2 + zona // 3
