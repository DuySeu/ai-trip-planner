"""Response body of GET /models."""

from __future__ import annotations

from pydantic import BaseModel


# One pickable chat model
class ModelOut(BaseModel):
    id: str
    label: str


# The provider in use, the model "Auto" stands for, and the models a visitor may pick
class ModelsOut(BaseModel):
    provider: str
    default_model: str | None
    models: list[ModelOut]
