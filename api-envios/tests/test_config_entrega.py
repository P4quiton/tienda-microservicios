import pytest

from app.config import load_settings


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    clave = tmp_path / "publica.pem"
    clave.write_text("clave ficticia de configuración")
    for nombre, valor in {
        "DB_HOST": "localhost",
        "DB_DATABASE": "db_prueba",
        "DB_USERNAME": "usr_prueba",
        "DB_PASSWORD": "prueba",
        "JWT_PUBLIC_KEY_PATH": str(clave),
        "JWT_ISSUER": "emisor-prueba",
        "JWT_AUDIENCE": "audiencia-prueba",
        "SERVICE_TOKEN_PEDIDOS_ENVIOS": "entrada-prueba",
        "SERVICE_TOKEN_ENVIOS_PEDIDOS": "salida-prueba",
        "API_PEDIDOS_URL": "http://pedidos.invalid",
    }.items():
        monkeypatch.setenv(nombre, valor)
    monkeypatch.delenv("ENVIOS_ENTREGA_SEGUNDOS", raising=False)


@pytest.mark.parametrize("valor", ["0", "-1", "1.5", "abc", ""])
def test_entrega_rechaza_valores_que_no_son_enteros_positivos(entorno, monkeypatch, valor):
    monkeypatch.setenv("ENVIOS_ENTREGA_SEGUNDOS", valor)
    with pytest.raises(RuntimeError, match="ENVIOS_ENTREGA_SEGUNDOS"):
        load_settings()


def test_entrega_tiene_default_y_acepta_entero_positivo(entorno, monkeypatch):
    assert load_settings().entrega_segundos == 60
    monkeypatch.setenv("ENVIOS_ENTREGA_SEGUNDOS", "1")
    assert load_settings().entrega_segundos == 1
