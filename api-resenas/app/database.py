from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection

from app.config import Settings

REVIEW_INDEX_NAME = "producto_usuario_unico"


def create_mongo_client(settings: Settings) -> MongoClient:
    return MongoClient(
        host=settings.mongo_host,
        port=settings.mongo_port,
        username=settings.mongo_username,
        password=settings.mongo_password,
        authSource=settings.mongo_auth_source,
        serverSelectionTimeoutMS=settings.mongo_timeout_ms,
        connectTimeoutMS=settings.mongo_timeout_ms,
        appname="api-resenas",
    )


def ensure_review_indexes(collection: Collection) -> None:
    collection.create_index(
        [("producto_id", ASCENDING), ("usuario_id", ASCENDING)],
        unique=True,
        name=REVIEW_INDEX_NAME,
    )
    collection.create_index(
        [("producto_id", ASCENDING), ("creado_en", DESCENDING)],
        name="producto_fecha",
    )
