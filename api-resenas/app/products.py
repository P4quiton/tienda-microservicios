import httpx

from app.errors import ProductNotFound, ProductServiceUnavailable


class ProductVerifier:
    def __init__(self, base_url: str, timeout: float = 3.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def exists(self, product_id: str) -> None:
        try:
            response = httpx.get(
                f"{self.base_url}/api/productos/{product_id}",
                timeout=self.timeout,
            )
        except httpx.RequestError as error:
            raise ProductServiceUnavailable from error

        if response.status_code == 404:
            raise ProductNotFound
        if response.status_code != 200:
            raise ProductServiceUnavailable

        try:
            payload = response.json()
        except ValueError as error:
            raise ProductServiceUnavailable from error
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise ProductServiceUnavailable
