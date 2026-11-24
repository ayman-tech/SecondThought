from __future__ import annotations

from typing import Literal, Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from secondthought.lab.catalog import get_catalog
from secondthought.lab.interventions import Intervention
from secondthought.lab.plans import MAX_INTERVENTIONS
from .prompts import (TASKS, MAX_CHARACTERS, MAX_SYSTEM_CHARACTERS,
                      DEFAULT_INPUT_TOKENS, MAX_INPUT_TOKENS,
                      DEFAULT_OUTPUT_TOKENS, MAX_OUTPUT_TOKENS)


class PromptInstructions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    task: Literal['rewrite','answer','summarize','continue','rewrite_continue','custom','none'] = 'rewrite'
    system_prompt: str | None = Field(default=TASKS['rewrite']['system_prompt'], max_length=MAX_SYSTEM_CHARACTERS)

    @model_validator(mode='after')
    def task_instructions(self):
        if 'system_prompt' not in self.model_fields_set:
            object.__setattr__(self, 'system_prompt', TASKS[self.task]['system_prompt'])
        if self.task == 'custom':
            if not self.system_prompt or not self.system_prompt.strip():
                raise ValueError('Enter custom instructions or select No system instruction')
        elif self.system_prompt != TASKS[self.task]['system_prompt']:
            raise ValueError('Edited instructions require the Custom task')
        return self


class ScoreRequest(BaseModel):
    """A completed response to score for the response inspector."""
    model_config = ConfigDict(extra='forbid', frozen=True)
    input: str = Field(min_length=1, max_length=MAX_CHARACTERS)
    response: str = Field(min_length=1, max_length=2 * MAX_CHARACTERS)
    task: Literal['rewrite','answer','summarize','continue','rewrite_continue','custom','none'] = 'rewrite'


class GenerationSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, allow_inf_nan=False)
    max_input_tokens: int = Field(default=DEFAULT_INPUT_TOKENS, strict=True, ge=128, le=MAX_INPUT_TOKENS)
    max_new_tokens: int = Field(default=DEFAULT_OUTPUT_TOKENS, strict=True, ge=32, le=MAX_OUTPUT_TOKENS)


class RunRequest(PromptInstructions):
    model_config = ConfigDict(extra='forbid', frozen=True, allow_inf_nan=False)
    session_id: UUID
    revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    model_id: str = Field(min_length=1,max_length=200)
    catalog_version: str | None = Field(default=None,pattern=r'^[0-9a-f]{64}$')
    input: str = Field(min_length=1,max_length=MAX_CHARACTERS)
    interventions: tuple[Intervention,...] = Field(default=(),max_length=MAX_INTERVENTIONS)
    generation: GenerationSettings = Field(default_factory=GenerationSettings)

    @field_validator('input')
    @classmethod
    def nonblank_input(cls,value):
        if not value.strip():
            raise ValueError('Enter input before generating a response')
        return value


class RewriteRequest(PromptInstructions):
    session_id: UUID
    revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    message: str = Field(min_length=1, max_length=MAX_CHARACTERS)
    max_input_tokens: int = Field(default=DEFAULT_INPUT_TOKENS, strict=True, ge=128, le=MAX_INPUT_TOKENS)
    max_new_tokens: int = Field(default=DEFAULT_OUTPUT_TOKENS, strict=True, ge=32, le=MAX_OUTPUT_TOKENS)
    alpha: float = Field(ge=-2, le=2)
    beta: Literal[0] = 0
    layer_strengths: dict[int, Annotated[float, Field(ge=-2, le=2)]] | None = None
    layer_vector_ids: dict[int, str] | None = None

    @model_validator(mode="after")
    def compatible_vector_choices(self):
        if self.layer_vector_ids is None:
            return self
        if self.layer_strengths is None:
            raise ValueError('Vector choices require explicit layer strengths')
        catalog = get_catalog()
        for index, vector_id in self.layer_vector_ids.items():
            vector = catalog.vectors.get(vector_id)
            if (index not in self.layer_strengths or vector is None or
                    vector.model_id != 'qwen2.5-0.5b-instruct' or vector.layer_index != index):
                raise ValueError('Vector choice must match a selected layer and model')
            catalog.vector(vector_id)
            if not vector.strength_min <= self.layer_strengths[index] <= vector.strength_max:
                raise ValueError('A steering strength is outside the chosen vector bounds')
        return self

    @field_validator("layer_strengths")
    @classmethod
    def supported_layers(cls, value):
        available = {entry['index'] for entry in get_catalog().layer_manifest('qwen2.5-0.5b-instruct')
                     if entry['available']}
        if value is not None and set(value) - available:
            raise ValueError("A requested layer has no available catalog vector")
        if value is not None:
            catalog = get_catalog()
            for index, strength in value.items():
                spec = catalog.vectors[catalog.defaults[('qwen2.5-0.5b-instruct', index)]]
                if not spec.strength_min <= strength <= spec.strength_max:
                    raise ValueError('A steering strength is outside its catalog bounds')
        return value

    @field_validator("message")
    @classmethod
    def meaningful_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Enter input before generating a response.")
        return value


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: UUID
    revision: int = Field(strict=True, ge=1, le=2_147_483_647)
