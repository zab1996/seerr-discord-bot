"""Load bot configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    discord_token: str
    command_prefix: str
    discord_guild_id: int | None
    seerr_url: str
    seerr_api_key: str
    omdb_api_key: str
    library_name: str
    request_button_label: str
    seerr_emoji_name: str | None
    seerr_emoji_id: int | None


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def load_config() -> Config:
    emoji_id_raw = os.getenv("SEERR_EMOJI_ID", "").strip()
    emoji_name = os.getenv("SEERR_EMOJI_NAME", "seerr").strip() or None
    guild_raw = os.getenv("DISCORD_GUILD_ID", "").strip()

    return Config(
        discord_token=_require("DISCORD_TOKEN"),
        command_prefix=os.getenv("COMMAND_PREFIX", "!").strip() or "!",
        discord_guild_id=int(guild_raw) if guild_raw.isdigit() else None,
        seerr_url=_require("SEERR_URL").rstrip("/"),
        seerr_api_key=_require("SEERR_API_KEY"),
        omdb_api_key=_require("OMDB_API_KEY"),
        library_name=os.getenv("LIBRARY_NAME", "Library").strip() or "Library",
        request_button_label=(
            os.getenv("REQUEST_BUTTON_LABEL", "Request").strip() or "Request"
        ),
        seerr_emoji_name=emoji_name,
        seerr_emoji_id=int(emoji_id_raw) if emoji_id_raw.isdigit() else None,
    )
