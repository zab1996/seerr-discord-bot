"""OMDb API client for IMDb and Rotten Tomatoes ratings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class OmdbTitle:
    title: str | None
    year: str | None
    plot: str | None
    poster: str | None
    imdb_id: str | None
    imdb_rating: str | None
    rt_rating: str | None
    tomato_url: str | None
    raw: dict[str, Any]


class OmdbClient:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def by_imdb_id(self, imdb_id: str) -> OmdbTitle | None:
        if not imdb_id:
            return None
        data = await self._fetch(i=imdb_id, tomatoes="true")
        if not data or data.get("Response") == "False":
            return None
        return self._parse(data)

    async def _fetch(self, **params: str) -> dict[str, Any] | None:
        query = {"apikey": self._api_key, **params}
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get("https://www.omdbapi.com/", params=query)
        if not response.is_success:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    @staticmethod
    def _parse(data: dict[str, Any]) -> OmdbTitle:
        rt_rating: str | None = None
        for entry in data.get("Ratings") or []:
            if entry.get("Source") == "Rotten Tomatoes":
                rt_rating = entry.get("Value")
                break
        if not rt_rating:
            tomato = data.get("tomatoMeter")
            if tomato and tomato not in ("N/A", "n/a"):
                rt_rating = f"{tomato}%"

        imdb_rating = data.get("imdbRating")
        if imdb_rating in (None, "N/A", "n/a"):
            imdb_rating = None

        poster = data.get("Poster")
        if poster in (None, "N/A", "n/a"):
            poster = None

        tomato_url = data.get("tomatoURL")
        if tomato_url in (None, "N/A", "n/a"):
            tomato_url = None

        return OmdbTitle(
            title=data.get("Title"),
            year=data.get("Year"),
            plot=None if data.get("Plot") in (None, "N/A") else data.get("Plot"),
            poster=poster,
            imdb_id=data.get("imdbID"),
            imdb_rating=imdb_rating,
            rt_rating=rt_rating,
            tomato_url=tomato_url,
            raw=data,
        )
