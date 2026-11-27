from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    port: int
    mongo_host: str
    mongo_port: int
    mongo_database: str
    mongo_username: str
    mongo_password: str
    mongo_auth_source: str
    mongo_timeout_ms: int
    jwt_issuer: str
    jwt_audience: str
    jwt_public_key_path: str
    productos_api_url: str
    trusted_proxy_cidrs: str = ""


def load_settings() -> Settings:
    return Settings(
        port=int(os.getenv("PORT", "8008")),
        mongo_host=os.getenv("MONGO_HOST", "127.0.0.1"),
        mongo_port=int(os.getenv("MONGO_PORT", "27017")),
        mongo_database=os.getenv("MONGO_DATABASE", "db_resenas"),
        mongo_username=os.getenv("MONGO_USERNAME", "usr_resenas"),
        mongo_password=os.getenv("MONGO_PASSWORD", ""),
        mongo_auth_source=os.getenv("MONGO_AUTH_SOURCE", "db_resenas"),
        mongo_timeout_ms=int(os.getenv("MONGO_TIMEOUT_MS", "3000")),
        jwt_issuer=os.getenv("JWT_ISSUER", "api-usuarios"),
        jwt_audience=os.getenv("JWT_AUDIENCE", "tienda-microservicios"),
        jwt_public_key_path=os.getenv("JWT_PUBLIC_KEY_PATH", ""),
        productos_api_url=os.getenv(
            "API_PRODUCTOS_URL", "http://127.0.0.1:8002"
        ).rstrip("/"),
        trusted_proxy_cidrs=os.getenv("TRUSTED_PROXIES", ""),
    )
