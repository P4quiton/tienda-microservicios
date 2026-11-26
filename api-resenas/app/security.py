from functools import lru_cache
from pathlib import Path
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidKeyError, InvalidTokenError

from app.config import Settings
from app.errors import ApiProblem, JWTConfigurationUnavailable

bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache(maxsize=8)
def _read_public_key(path: str) -> bytes:
    if not path:
        raise JWTConfigurationUnavailable
    try:
        pem = Path(path).read_bytes()
        public_key = serialization.load_pem_public_key(pem)
    except (OSError, ValueError, TypeError) as error:
        raise JWTConfigurationUnavailable from error
    if not isinstance(public_key, RSAPublicKey):
        raise JWTConfigurationUnavailable
    return pem


def current_user(
    credentials: HTTPAuthorizationCredentials | None,
    settings: Settings,
) -> dict[str, str]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiProblem(401, "Credencial inválida.")

    try:
        public_key = _read_public_key(settings.jwt_public_key_path)
    except JWTConfigurationUnavailable as error:
        raise ApiProblem(503, "La validación JWT no está configurada.") from error

    try:
        claims = jwt.decode(
            credentials.credentials,
            public_key,
            algorithms=["RS256"],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["sub", "role", "iss", "aud", "iat", "exp"]},
        )
    except InvalidKeyError as error:
        raise ApiProblem(503, "La validación JWT no está configurada.") from error
    except InvalidTokenError as error:
        raise ApiProblem(401, "Credencial inválida.") from error

    try:
        subject = UUID(claims["sub"])
    except (ValueError, TypeError, AttributeError) as error:
        raise ApiProblem(401, "Credencial inválida.") from error
    if subject.version != 4:
        raise ApiProblem(401, "Credencial inválida.")

    role = claims.get("role")
    if role not in {"cliente", "admin"}:
        raise ApiProblem(403, "Permiso insuficiente.")

    return {"usuario_id": str(subject), "role": role}
