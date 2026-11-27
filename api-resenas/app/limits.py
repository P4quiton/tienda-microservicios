from collections import deque
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from math import ceil
from threading import Lock
from time import monotonic
from typing import Callable

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY_BYTES = 256 * 1024
WINDOW_SECONDS = 60
MAX_COUNTERS = 10_000
PURGE_INTERVAL_SECONDS = 30
QUERY_METHODS = {"GET", "HEAD", "OPTIONS"}


class RequestTooLarge(Exception):
    pass


def parse_trusted_proxy_cidrs(
    value: str,
) -> tuple[IPv4Network | IPv6Network, ...]:
    networks: list[IPv4Network | IPv6Network] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            network = ip_network(item)
        except ValueError as error:
            raise ValueError(
                f"TRUSTED_PROXIES contiene un valor inválido: {item!r}"
            ) from error
        if network.prefixlen == 0:
            raise ValueError(
                f"TRUSTED_PROXIES no puede incluir rangos /0: {item!r}"
            )
        networks.append(network)
    return tuple(networks)


class RequestGuardMiddleware:
    """Aplica cuotas por IP y limita bytes realmente recibidos por instancia."""

    def __init__(
        self,
        app: ASGIApp,
        trusted_proxies: tuple[IPv4Network | IPv6Network, ...] = (),
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.app = app
        self.clock = clock
        self.trusted_proxies = trusted_proxies
        self.counters: dict[tuple[str, str], deque[float]] = {}
        self.lock = Lock()
        self.next_purge = 0.0

    def _client_ip(self, scope: Scope, headers: Headers) -> str:
        peer = (scope.get("client") or ("unknown", 0))[0]
        try:
            peer_ip = ip_address(peer)
        except ValueError:
            return "unknown"
        if not any(peer_ip in network for network in self.trusted_proxies):
            return str(peer_ip)

        forwarded = ",".join(headers.getlist("x-forwarded-for"))
        try:
            chain = [ip_address(item.strip()) for item in forwarded.split(",")]
        except ValueError:
            return str(peer_ip)
        for address in reversed(chain):
            if not any(address in network for network in self.trusted_proxies):
                return str(address)
        return str(peer_ip)

    def _retry_after(self, scope: Scope, headers: Headers) -> int:
        method, path = scope["method"], scope["path"]
        if method in {"GET", "HEAD"} and path in {"/health", "/ready"}:
            return 0
        if path == "/internal" or path.startswith("/internal/"):
            category, limit = "internal", 300
        elif method in QUERY_METHODS:
            category, limit = "query", 120
        else:
            category, limit = "mutation", 30
        key = (self._client_ip(scope, headers), category)

        with self.lock:
            now = self.clock()
            cutoff = now - WINDOW_SECONDS
            if now >= self.next_purge:
                stale = [key for key, hits in self.counters.items() if hits[-1] <= cutoff]
                for stale_key in stale:
                    del self.counters[stale_key]
                self.next_purge = now + PURGE_INTERVAL_SECONDS

            hits = self.counters.get(key)
            if hits is None:
                if len(self.counters) >= MAX_COUNTERS:
                    return WINDOW_SECONDS
                hits = self.counters[key] = deque()
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return max(1, ceil(hits[0] + WINDOW_SECONDS - now))
            hits.append(now)
            return 0

    @staticmethod
    async def _read_body(headers: Headers, receive: Receive) -> bytearray | None:
        for value in headers.getlist("content-length"):
            try:
                length = int(value)
            except ValueError:
                continue  # El servidor HTTP valida el framing.
            if length > MAX_BODY_BYTES:
                raise RequestTooLarge

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return None
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                raise RequestTooLarge
            body.extend(chunk)
            if not message.get("more_body", False):
                return body

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        retry_after = self._retry_after(scope, headers)
        if retry_after:
            response = JSONResponse(
                status_code=429,
                content={"success": False, "message": "Se excedió el límite de solicitudes.", "errors": {}},
                headers={"Retry-After": str(retry_after)},
            )
            await response(scope, receive, send)
            return

        try:
            body = await self._read_body(headers, receive)
        except RequestTooLarge:
            response = JSONResponse(
                status_code=413,
                content={"success": False, "message": "El cuerpo excede el límite de 256 KiB.", "errors": {}},
            )
            await response(scope, receive, send)
            return
        if body is None:
            return

        # Reentrega el cuerpo validado y deja que el servidor notifique desconexiones.
        async def replay() -> Message:
            nonlocal body
            if body is None:
                return await receive()
            message = {"type": "http.request", "body": bytes(body), "more_body": False}
            body = None
            return message

        await self.app(scope, replay, send)
