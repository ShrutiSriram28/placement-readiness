from __future__ import annotations
import serpapi
from app.config import settings

class InternetTool:
    def __init__(self) -> None:
        self.client = serpapi.Client(api_key=settings.serpapi_api_key)

    def search(self, query: str, num_results: int = 10) -> dict:
        result = self.client.search(
            {
                "engine": "google",
                "q": query,
                "num": num_results,
                "hl": "en",
            }
        )

        if not isinstance(result, dict):
            return {
                "search_metadata": {},
                "organic_results": [],
            }

        return result

    @staticmethod
    def compact_results(result: dict) -> list[dict]:
        compact = []

        for item in result.get("organic_results", []):
            compact.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "content": item.get("snippet", ""),
                    "position": item.get("position"),
                    "source": item.get("source"),
                }
            )

        return compact

internet_tool = InternetTool()