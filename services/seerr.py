"""Seerr / Overseerr API client."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)


class SeerrError(Exception):
    """Raised when the Seerr API returns an error response."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class SeerrClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._base = f"{base_url.rstrip('/')}/api/v1"
        self._headers = {"X-Api-Key": api_key, "Accept": "application/json"}

    async def search(self, query: str, *, page: int = 1) -> list[dict[str, Any]]:
        # Seerr rejects '+' (httpx's default space encoding). Use %20 instead.
        encoded_query = quote(query, safe="")
        data = await self._get(f"/search?query={encoded_query}&page={page}")
        results = data.get("results") or []
        return [
            item
            for item in results
            if item.get("mediaType") in ("movie", "tv")
        ]

    async def get_movie(self, tmdb_id: int) -> dict[str, Any]:
        return await self._get(f"/movie/{tmdb_id}")

    async def get_tv(self, tmdb_id: int) -> dict[str, Any]:
        return await self._get(f"/tv/{tmdb_id}")

    async def create_request(
        self,
        *,
        media_type: str,
        media_id: int,
        seasons: list[int] | str | None = None,
        requested_by: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "mediaType": media_type,
            "mediaId": media_id,
        }
        if media_type == "tv" and seasons is not None:
            body["seasons"] = seasons

        who = requested_by or "unknown"
        season_info = f" seasons={body['seasons']!r}" if "seasons" in body else ""
        log.info(
            "Sending Seerr request by %s: POST /request mediaType=%s mediaId=%s%s",
            who,
            media_type,
            media_id,
            season_info,
        )

        try:
            result = await self._post("/request", json=body)
        except SeerrError as exc:
            log.warning(
                "Seerr request rejected for %s: mediaType=%s mediaId=%s — %s",
                who,
                media_type,
                media_id,
                exc,
            )
            raise

        request_id = result.get("id") if isinstance(result, dict) else None
        log.info(
            "Seerr request accepted for %s: mediaType=%s mediaId=%s request_id=%s",
            who,
            media_type,
            media_id,
            request_id,
        )
        return result

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self._base}{path}",
                headers=self._headers,
                params=params,
            )
        return self._handle(response)

    async def _post(self, path: str, *, json: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._base}{path}",
                headers=self._headers,
                json=json,
            )
        return self._handle(response)

    @staticmethod
    def _handle(response: httpx.Response) -> dict[str, Any]:
        if response.is_success:
            if not response.content:
                return {}
            return response.json()

        message = f"Seerr API error ({response.status_code})"
        try:
            payload = response.json()
            if isinstance(payload, dict):
                message = (
                    payload.get("message")
                    or payload.get("error")
                    or message
                )
        except ValueError:
            if response.text:
                message = response.text[:200]

        raise SeerrError(message, status_code=response.status_code)
