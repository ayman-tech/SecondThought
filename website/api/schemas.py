from __future__ import annotations

from typing import Literal, Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RewriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    session_id: UUID
    revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    message: str = Field(min_length=1, max_length=2000)
    alpha: float = Field(ge=-2, le=2)
    beta: Literal[0] = 0
    layer_strengths: dict[int, Annotated[float, Field(ge=-2, le=2)]] | None = None

    @field_validator("layer_strengths")
    @classmethod
    def supported_layers(cls, value):
        if value is not None and set(value) - {0, 4, 11, 21, 22}:
            raise ValueError("Only layers 0, 4, 11, 21 and 22 have available vectors")
        return value

    @field_validator("message")
    @classmethod
    def meaningful_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Enter a draft before changing its formality.")
        return value


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: UUID
    revision: int = Field(strict=True, ge=1, le=2_147_483_647)
