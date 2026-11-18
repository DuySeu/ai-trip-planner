"""The Tavily client: the part of it this project uses, and the one place that imports the SDK."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol


# The part of the Tavily client used here; tests pass a fake
class TavilyClient(Protocol):
    # One search; the answer holds a "results" list of title, url and content
    def search(
        self, query: str, max_results: int = ..., include_domains: Sequence[str] = ...
    ) -> dict[str, Any]: ...


# The real client; the SDK is imported here so code that injects its own client does not need it
def create_client(api_key: str) -> TavilyClient:
    from tavily import TavilyClient as SdkClient  # type: ignore[import-untyped]

    client: TavilyClient = SdkClient(api_key=api_key)
    return client
