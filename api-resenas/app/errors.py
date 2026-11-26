from dataclasses import dataclass, field


@dataclass
class ApiProblem(Exception):
    status_code: int
    message: str
    errors: dict[str, list[str]] = field(default_factory=dict)


class ProductNotFound(Exception):
    pass


class ProductServiceUnavailable(Exception):
    pass


class JWTConfigurationUnavailable(Exception):
    pass
