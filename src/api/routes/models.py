"""The chat models a visitor may pick in the chat composer, for the provider in use."""

from __future__ import annotations

from fastapi import APIRouter

from api.deps import Deps
from api.envelope import ApiResponse
from api.schemas.models import ModelOut, ModelsOut
from core.chat_models import chat_models_for, default_chat_model

router = APIRouter()


# GET /models - The provider's chat models and the one "Auto" stands for
@router.get("/models")
def list_models(deps: Deps) -> ApiResponse[ModelsOut]:
    provider = deps.settings.llm_provider
    return ApiResponse(
        success=True,
        data=ModelsOut(
            provider=provider,
            default_model=default_chat_model(provider, deps.settings.chat_models),
            models=[ModelOut(id=i, label=label) for i, label in chat_models_for(provider).items()],
        ),
    )
