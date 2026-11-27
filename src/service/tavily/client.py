"""The Tavily client: the part of it this project uses, and the one place that imports the SDK."""

from __future__ import annotations

from typing import Any, Protocol


# The part of the Tavily client used here; tests pass a fake
class TavilyClient(Protocol):
    # One search with Tavily's request parameters as keywords; the answer holds a "results" list of
    # title, url and content
    def search(self, query: str, **params: Any) -> dict[str, Any]: ...


# The real client; the SDK is imported here so code that injects its own client does not need it
def create_client(api_key: str) -> TavilyClient:
    from tavily import TavilyClient as SdkClient  # type: ignore[import-untyped]

    client: TavilyClient = SdkClient(api_key=api_key)
    return client
