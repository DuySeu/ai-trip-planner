from __future__ import annotations

from fastapi.testclient import TestClient

from core.chat_models import default_chat_model
from core.constants import ModelId
from core.settings import load_settings
from tests.integration.test_api_foundation import ENV, make_app


def test_models_lists_the_providers_catalog_and_default(db_pool):
    settings = load_settings(ENV)
    data = TestClient(make_app(db_pool, settings)).get("/models").json()["data"]
    assert data["provider"] == "openrouter"
    assert {"id": ModelId.LING_3_2_FLASH, "label": "inclusionAI: Ling 3.2 Flash (free)"} in data[
        "models"
    ]
    assert data["default_model"] == default_chat_model("openrouter", settings.chat_models)


def test_models_under_openai_is_empty(db_pool):
    settings = load_settings({**ENV, "LLM_PROVIDER": "openai", "OPENAI_API_KEY": "k"})
    response = TestClient(make_app(db_pool, settings, provider="openai")).get("/models")
    assert response.status_code == 200
    assert response.json()["data"] == {"provider": "openai", "default_model": None, "models": []}
