from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
from statistics import mean
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from pymongo import DESCENDING, MongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings, load_settings
from app.database import create_mongo_client, ensure_review_indexes
from app.errors import ApiProblem, ProductNotFound, ProductServiceUnavailable
from app.limits import RequestGuardMiddleware, parse_trusted_proxy_cidrs
from app.products import ProductVerifier
from app.schemas import ReviewCreate, ReviewEnvelope, ReviewListEnvelope, ReviewResponse
from app.security import bearer_scheme, current_user

logger = logging.getLogger("api-resenas")


def create_app(
    settings: Settings | None = None,
    *,
    mongo_client: MongoClient | None = None,
    product_verifier: ProductVerifier | None = None,
) -> FastAPI:
    app_settings = settings or load_settings()
    trusted_proxies = parse_trusted_proxy_cidrs(app_settings.trusted_proxy_cidrs)
    owns_client = mongo_client is None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = mongo_client or create_mongo_client(app_settings)
        app.state.mongo_client = client
        app.state.reviews = client[app_settings.mongo_database]["resenas"]
        app.state.settings = app_settings
        app.state.product_verifier = product_verifier or ProductVerifier(
            app_settings.productos_api_url
        )
        app.state.review_indexes_ready = False
        try:
            ensure_review_indexes(app.state.reviews)
            app.state.review_indexes_ready = True
        except PyMongoError:
            logger.warning("No se pudieron preparar los índices de MongoDB; se reintentará al validar readiness.")
        try:
            yield
        finally:
            if owns_client:
                client.close()

    app = FastAPI(title="API Reseñas", version="1.1.0", lifespan=lifespan)
    app.add_middleware(
        RequestGuardMiddleware,
        trusted_proxies=trusted_proxies,
    )

    @app.exception_handler(ApiProblem)
    async def api_problem_handler(_: Request, error: ApiProblem) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "success": False,
                "message": error.message,
                "errors": error.errors,
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_: Request, error: StarletteHTTPException) -> JSONResponse:
        message = "Recurso no encontrado." if error.status_code == 404 else "Solicitud no permitida."
        return JSONResponse(
            status_code=error.status_code,
            content={"success": False, "message": message, "errors": {}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _: Request, error: RequestValidationError
    ) -> JSONResponse:
        errors: dict[str, list[str]] = {}
        malformed_json = False
        for detail in error.errors():
            location = [str(part) for part in detail.get("loc", ()) if part != "body"]
            field = ".".join(location) or "request"
            errors.setdefault(field, []).append(str(detail.get("msg", "Dato inválido.")))
            malformed_json = malformed_json or detail.get("type") == "json_invalid"
        return JSONResponse(
            status_code=400 if malformed_json else 422,
            content={
                "success": False,
                "message": "El cuerpo debe ser JSON válido." if malformed_json else "Los datos enviados no son válidos.",
                "errors": errors,
            },
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_: Request, error: Exception) -> JSONResponse:
        logger.error("Error inesperado en API Reseñas: %s", type(error).__name__)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "Error interno.",
                "errors": {},
            },
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "api-resenas"}

    @app.get("/ready")
    def ready(request: Request):
        try:
            request.app.state.mongo_client.admin.command("ping")
            if not request.app.state.review_indexes_ready:
                ensure_review_indexes(request.app.state.reviews)
                request.app.state.review_indexes_ready = True
        except PyMongoError:
            request.app.state.review_indexes_ready = False
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "service": "api-resenas"},
            )
        return {"status": "ok", "service": "api-resenas"}

    @app.get(
        "/api/resenas/producto/{producto_id}",
        response_model=ReviewListEnvelope,
    )
    def list_product_reviews(producto_id: UUID, request: Request) -> ReviewListEnvelope:
        if producto_id.version != 4:
            raise ApiProblem(
                status_code=422,
                message="El identificador del producto debe ser un UUID v4.",
                errors={"producto_id": ["Debe ser un UUID v4 válido."]},
            )

        try:
            documents = list(
                request.app.state.reviews.find({"producto_id": str(producto_id)}).sort(
                    [("creado_en", DESCENDING), ("id", 1)]
                )
            )
        except PyMongoError as error:
            raise ApiProblem(
                status_code=503,
                message="El servicio de reseñas no está disponible.",
                errors={},
            ) from error

        items = []
        for document in documents:
            created_at = document["creado_en"]
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            else:
                created_at = created_at.astimezone(timezone.utc)
            items.append(
                ReviewResponse.model_validate(
                    {
                        "id": document["id"],
                        "producto_id": document["producto_id"],
                        "usuario_id": document["usuario_id"],
                        "calificacion": document["calificacion"],
                        "comentario": document["comentario"],
                        "creado_en": created_at,
                    }
                )
            )
        promedio = round(mean(item.calificacion for item in items), 2) if items else None
        return ReviewListEnvelope(
            success=True,
            message="Reseñas consultadas correctamente.",
            data={"items": items, "promedio": promedio, "total": len(items)},
        )

    def authenticated_user(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    ) -> dict[str, str]:
        return current_user(credentials, app_settings)

    @app.post(
        "/api/resenas",
        status_code=201,
        response_model=ReviewEnvelope,
    )
    def create_review(
        payload: ReviewCreate,
        request: Request,
        user: dict[str, str] = Depends(authenticated_user),
    ) -> ReviewEnvelope:
        if payload.usuario_id is not None and str(payload.usuario_id) != user["usuario_id"]:
            raise ApiProblem(
                403,
                "El usuario_id no coincide con la credencial.",
                {"usuario_no_coincide": ["El usuario_id debe coincidir con el sub del token."]},
            )
        if not request.app.state.review_indexes_ready:
            raise ApiProblem(
                503,
                "Los índices de reseñas aún no están disponibles."
            )
        product_id = str(payload.producto_id)
        try:
            request.app.state.product_verifier.exists(product_id)
        except ProductNotFound as error:
            raise ApiProblem(404, "El producto no existe.") from error
        except ProductServiceUnavailable as error:
            raise ApiProblem(503, "El servicio de productos no está disponible.") from error

        created_at = datetime.now(timezone.utc)
        document = {
            "id": str(uuid4()),
            "producto_id": product_id,
            "usuario_id": user["usuario_id"],
            "calificacion": payload.calificacion,
            "comentario": payload.comentario,
            "creado_en": created_at,
        }
        try:
            request.app.state.reviews.insert_one(document)
        except DuplicateKeyError as error:
            raise ApiProblem(
                409,
                "El usuario ya publicó una reseña para este producto.",
            ) from error
        except PyMongoError as error:
            raise ApiProblem(503, "El servicio de reseñas no está disponible.") from error

        return ReviewEnvelope(
            success=True,
            message="Reseña creada correctamente.",
            data=ReviewResponse.model_validate(
                {
                    "id": document["id"],
                    "producto_id": document["producto_id"],
                    "usuario_id": document["usuario_id"],
                    "calificacion": document["calificacion"],
                    "comentario": document["comentario"],
                    "creado_en": document["creado_en"],
                }
            ),
        )

    return app


app = create_app()
