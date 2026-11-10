from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RewriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    session_id: UUID
    revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    message: str = Field(min_length=1, max_length=2000)
    alpha: float = Field(ge=-2, le=2)
    beta: Literal[0] = 0

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
