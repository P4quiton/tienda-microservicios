from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    producto_id: UUID
    # Opcional. El autor siempre sale del sub del JWT; si se envía debe coincidir con él.
    usuario_id: UUID | None = None
    calificacion: Annotated[int, Field(strict=True, ge=1, le=5)]
    comentario: Annotated[str, Field(max_length=1000)]

    @field_validator("producto_id")
    @classmethod
    def product_id_must_be_v4(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("Debe ser un UUID v4 válido.")
        return value


class ReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    producto_id: UUID
    usuario_id: UUID
    calificacion: int
    comentario: str
    creado_en: datetime


class ReviewListData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ReviewResponse]
    promedio: float | None
    total: int


class ReviewListEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: Literal[True]
    message: str
    data: ReviewListData


class ReviewEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: Literal[True]
    message: str
    data: ReviewResponse
