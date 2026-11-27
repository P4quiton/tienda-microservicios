from app.cotizacion import cotizar


def test_cotizacion_es_determinista():
    assert cotizar("06600", 1) == cotizar("06600", 1) == ("89.00", 2)


def test_cotizacion_zona_y_cantidad():
    assert cotizar("90000", 3) == ("229.00", 5)  # 89 + 10*9 + 25*2; 2 + 9//3
    assert cotizar("20000", 1) == ("109.00", 2)


def test_cotizacion_formato_decimal_dos_posiciones():
    costo, _ = cotizar("99999", 10_000)
    assert costo == "250154.00"  # 89 + 10*9 + 25*9999
