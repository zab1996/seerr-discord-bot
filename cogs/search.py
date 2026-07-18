"""Search and request media via Seerr with OMDb ratings."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from services.omdb import OmdbClient, OmdbTitle
from services.seerr import SeerrClient, SeerrError

if TYPE_CHECKING:
    from config import Config

log = logging.getLogger(__name__)

TMDB_IMAGE = "https://image.tmdb.org/t/p/w500"
VIEW_TIMEOUT = 600


def _user_label(user: discord.abc.User | None) -> str:
    if user is None:
        return "unknown"
    return f"{user} ({user.id})"


def _year_from(value: str | None) -> str:
    if not value:
        return "????"
    return value[:4]


def _availability_label(media_info: dict[str, Any] | None) -> str:
    if not media_info:
        return "Not in library"
    status = media_info.get("status")
    # Seerr MediaStatus: 1 UNKNOWN, 2 PENDING, 3 PROCESSING,
    # 4 PARTIALLY_AVAILABLE, 5 AVAILABLE, 6 BLACKLISTED, 7 DELETED
    labels = {
        1: "Unknown",
        2: "Pending / requested",
        3: "Processing / downloading",
        4: "Partially available",
        5: "Available",
        6: "Blacklisted",
        7: "Deleted / not in library",
    }
    if isinstance(status, int) and status in labels:
        return labels[status]
    if status is not None:
        return str(status).replace("_", " ").title()
    return "Not in library"


def _availability_color(media_info: dict[str, Any] | None) -> discord.Color:
    if not media_info:
        return discord.Color.dark_grey()
    status = media_info.get("status")
    colors = {
        2: discord.Color.gold(),
        3: discord.Color.orange(),
        4: discord.Color.blue(),
        5: discord.Color.green(),
        6: discord.Color.dark_grey(),
        7: discord.Color.dark_red(),
    }
    if isinstance(status, int) and status in colors:
        return colors[status]
    return discord.Color.blurple()


def _is_available(media_info: dict[str, Any] | None) -> bool:
    """True when Seerr reports the title as fully available in the library."""
    return bool(media_info) and media_info.get("status") == 5


def _title_from_result(item: dict[str, Any]) -> str:
    if item.get("mediaType") == "tv":
        return item.get("name") or item.get("originalName") or "Unknown"
    return item.get("title") or item.get("originalTitle") or "Unknown"


def _year_from_result(item: dict[str, Any]) -> str:
    if item.get("mediaType") == "tv":
        return _year_from(item.get("firstAirDate"))
    return _year_from(item.get("releaseDate"))


def _poster_url(path: str | None, omdb: OmdbTitle | None = None) -> str | None:
    if omdb and omdb.poster:
        return omdb.poster
    if path:
        return f"{TMDB_IMAGE}{path}"
    return None


def _seerr_emoji(config: Config) -> discord.PartialEmoji | None:
    if config.seerr_emoji_id and config.seerr_emoji_name:
        return discord.PartialEmoji(
            name=config.seerr_emoji_name,
            id=config.seerr_emoji_id,
        )
    return None


def build_detail_embed(
    details: dict[str, Any],
    *,
    media_type: str,
    omdb: OmdbTitle | None,
    library_name: str = "Library",
) -> discord.Embed:
    if media_type == "tv":
        title = details.get("name") or "Unknown"
        year = _year_from(details.get("firstAirDate"))
        overview = details.get("overview") or ""
    else:
        title = details.get("title") or "Unknown"
        year = _year_from(details.get("releaseDate"))
        overview = details.get("overview") or ""

    if omdb and omdb.plot:
        overview = omdb.plot

    media_info = details.get("mediaInfo")
    status_label = _availability_label(media_info)

    embed = discord.Embed(
        title=f"{title} ({year})",
        description=(overview[:4000] if overview else "No plot available."),
        color=_availability_color(media_info),
    )
    embed.add_field(name="Type", value="TV Show" if media_type == "tv" else "Movie", inline=True)
    embed.add_field(name=library_name, value=status_label, inline=True)

    imdb_id = (omdb.imdb_id if omdb else None) or details.get("imdbId")
    imdb_rating = omdb.imdb_rating if omdb else None
    if imdb_id:
        rating_text = f"{imdb_rating}/10" if imdb_rating else "N/A"
        embed.add_field(
            name="IMDb",
            value=f"[{rating_text}](https://www.imdb.com/title/{imdb_id}/)",
            inline=True,
        )
    elif imdb_rating:
        embed.add_field(name="IMDb", value=f"{imdb_rating}/10", inline=True)

    rt_rating = omdb.rt_rating if omdb else None
    tomato_url = omdb.tomato_url if omdb else None
    if rt_rating:
        if tomato_url:
            embed.add_field(
                name="RT Critics",
                value=f"[{rt_rating}]({tomato_url})",
                inline=True,
            )
        else:
            embed.add_field(name="RT Critics", value=rt_rating, inline=True)

    embed.set_footer(text=f"{library_name}: {status_label}")

    poster = _poster_url(details.get("posterPath"), omdb)
    if poster:
        embed.set_thumbnail(url=poster)

    return embed


class SeasonSelect(discord.ui.Select):
    def __init__(
        self,
        *,
        media_id: int,
        seasons: list[dict[str, Any]],
        seerr: SeerrClient,
        library_name: str,
    ) -> None:
        self.media_id = media_id
        self.seerr = seerr
        self.library_name = library_name

        options = [
            discord.SelectOption(
                label="All seasons",
                value="all",
                description="Request every season",
            )
        ]
        for season in seasons:
            number = season.get("seasonNumber")
            if number is None or number == 0:
                continue
            name = season.get("name") or f"Season {number}"
            episode_count = season.get("episodeCount")
            desc = f"{episode_count} episodes" if episode_count else None
            options.append(
                discord.SelectOption(
                    label=name[:100],
                    value=str(number),
                    description=desc[:100] if desc else None,
                )
            )
            if len(options) >= 25:
                break

        super().__init__(
            placeholder="Choose seasons to request…",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        choice = self.values[0]
        seasons: list[int] | str = "all" if choice == "all" else [int(choice)]
        label = "all seasons" if choice == "all" else f"season {choice}"
        user = _user_label(interaction.user)
        log.info(
            "TV request by %s: tmdb_id=%s seasons=%s",
            user,
            self.media_id,
            label,
        )
        await interaction.response.defer(ephemeral=False)
        try:
            await self.seerr.create_request(
                media_type="tv",
                media_id=self.media_id,
                seasons=seasons,
                requested_by=user,
            )
        except SeerrError as exc:
            log.warning(
                "TV request failed for %s tmdb_id=%s: %s",
                user,
                self.media_id,
                exc,
            )
            await interaction.followup.send(
                f"Could not create request: {exc}",
            )
            return

        log.info("TV request succeeded for %s tmdb_id=%s (%s)", user, self.media_id, label)
        await interaction.followup.send(
            f"{interaction.user.mention} requested this show for "
            f"**{self.library_name}** ({label}).",
        )
        if self.view:
            for item in self.view.children:
                item.disabled = True  # type: ignore[attr-defined]
            try:
                await interaction.message.edit(view=self.view)  # type: ignore[union-attr]
            except (discord.HTTPException, AttributeError):
                pass


class SeasonSelectView(discord.ui.View):
    def __init__(
        self,
        *,
        media_id: int,
        seasons: list[dict[str, Any]],
        seerr: SeerrClient,
        library_name: str,
    ) -> None:
        super().__init__(timeout=VIEW_TIMEOUT)
        self.add_item(
            SeasonSelect(
                media_id=media_id,
                seasons=seasons,
                seerr=seerr,
                library_name=library_name,
            )
        )


class RequestButton(discord.ui.Button):
    def __init__(
        self,
        *,
        media_type: str,
        media_id: int,
        seerr: SeerrClient,
        config: Config,
        seasons: list[dict[str, Any]] | None = None,
    ) -> None:
        emoji = _seerr_emoji(config)
        # Discord button labels max out at 80 characters
        label = config.request_button_label[:80]
        super().__init__(
            style=discord.ButtonStyle.primary,
            label=label,
            emoji=emoji,
            custom_id=f"request:{media_type}:{media_id}",
        )
        self.media_type = media_type
        self.media_id = media_id
        self.seerr = seerr
        self.config = config
        self.seasons = seasons or []

    async def callback(self, interaction: discord.Interaction) -> None:
        user = _user_label(interaction.user)
        if self.media_type == "tv":
            log.info(
                "Request button (TV) by %s: tmdb_id=%s — opening season picker",
                user,
                self.media_id,
            )
            view = SeasonSelectView(
                media_id=self.media_id,
                seasons=self.seasons,
                seerr=self.seerr,
                library_name=self.config.library_name,
            )
            await interaction.response.send_message(
                "Select which seasons to request:",
                view=view,
                ephemeral=True,
            )
            return

        log.info("Movie request by %s: tmdb_id=%s", user, self.media_id)
        await interaction.response.defer(ephemeral=False)
        try:
            await self.seerr.create_request(
                media_type="movie",
                media_id=self.media_id,
                requested_by=user,
            )
        except SeerrError as exc:
            log.warning(
                "Movie request failed for %s tmdb_id=%s: %s",
                user,
                self.media_id,
                exc,
            )
            await interaction.followup.send(
                f"Could not create request: {exc}",
            )
            return

        log.info("Movie request succeeded for %s tmdb_id=%s", user, self.media_id)
        await interaction.followup.send(
            f"{interaction.user.mention} requested this movie for "
            f"**{self.config.library_name}**.",
        )


class DetailView(discord.ui.View):
    def __init__(
        self,
        *,
        media_type: str,
        media_id: int,
        details: dict[str, Any],
        omdb: OmdbTitle | None,
        seerr: SeerrClient,
        config: Config,
    ) -> None:
        super().__init__(timeout=VIEW_TIMEOUT)

        imdb_id = (omdb.imdb_id if omdb else None) or details.get("imdbId")
        if imdb_id:
            self.add_item(
                discord.ui.Button(
                    style=discord.ButtonStyle.link,
                    label="IMDb",
                    url=f"https://www.imdb.com/title/{imdb_id}/",
                )
            )

        tomato_url = omdb.tomato_url if omdb else None
        if tomato_url:
            self.add_item(
                discord.ui.Button(
                    style=discord.ButtonStyle.link,
                    label="Rotten Tomatoes",
                    url=tomato_url,
                )
            )

        seasons = details.get("seasons") if media_type == "tv" else None
        if not _is_available(details.get("mediaInfo")):
            self.add_item(
                RequestButton(
                    media_type=media_type,
                    media_id=media_id,
                    seerr=seerr,
                    config=config,
                    seasons=seasons if isinstance(seasons, list) else None,
                )
            )


class ResultSelect(discord.ui.Select):
    def __init__(
        self,
        results: list[dict[str, Any]],
        *,
        seerr: SeerrClient,
        omdb: OmdbClient,
        config: Config,
    ) -> None:
        self.results = {f"{r['mediaType']}:{r['id']}": r for r in results}
        self.seerr = seerr
        self.omdb_client = omdb
        self.config = config

        options: list[discord.SelectOption] = []
        for item in results[:25]:
            media_type = item["mediaType"]
            label = f"{_title_from_result(item)} ({_year_from_result(item)})"
            kind = "TV" if media_type == "tv" else "Movie"
            overview = (item.get("overview") or "").strip()
            desc = f"{kind} — {overview}" if overview else kind
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=f"{media_type}:{item['id']}",
                    description=desc[:100],
                )
            )

        super().__init__(
            placeholder="Pick a title…",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        key = self.values[0]
        media_type, id_str = key.split(":", 1)
        media_id = int(id_str)
        user = _user_label(interaction.user)
        picked = self.results.get(key, {})
        title = _title_from_result(picked) if picked else key
        log.info(
            "Result selected by %s: %s %s (tmdb_id=%s)",
            user,
            media_type,
            title,
            media_id,
        )

        await interaction.response.defer()

        try:
            if media_type == "tv":
                details = await self.seerr.get_tv(media_id)
            else:
                details = await self.seerr.get_movie(media_id)
        except SeerrError as exc:
            log.warning("Failed to load details for %s tmdb_id=%s: %s", user, media_id, exc)
            await interaction.followup.send(f"Failed to load details: {exc}", ephemeral=True)
            return

        omdb_data: OmdbTitle | None = None
        imdb_id = details.get("imdbId")
        if imdb_id:
            try:
                omdb_data = await self.omdb_client.by_imdb_id(imdb_id)
            except Exception:
                log.exception("OMDb lookup failed for %s (user %s)", imdb_id, user)

        embed = build_detail_embed(
            details,
            media_type=media_type,
            omdb=omdb_data,
            library_name=self.config.library_name,
        )
        view = DetailView(
            media_type=media_type,
            media_id=media_id,
            details=details,
            omdb=omdb_data,
            seerr=self.seerr,
            config=self.config,
        )
        await interaction.followup.send(embed=embed, view=view)


class ResultSelectView(discord.ui.View):
    def __init__(
        self,
        results: list[dict[str, Any]],
        *,
        seerr: SeerrClient,
        omdb: OmdbClient,
        config: Config,
    ) -> None:
        super().__init__(timeout=VIEW_TIMEOUT)
        self.add_item(
            ResultSelect(results, seerr=seerr, omdb=omdb, config=config)
        )


class SearchCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        config: Config = bot.config  # type: ignore[attr-defined]
        self.config = config
        self.seerr = SeerrClient(config.seerr_url, config.seerr_api_key)
        self.omdb = OmdbClient(config.omdb_api_key)

    @commands.hybrid_command(name="search", description="Search movies and TV shows")
    @app_commands.describe(query="Movie or TV show name to search for")
    async def search(self, ctx: commands.Context, *, query: str) -> None:
        query = query.strip()
        user = _user_label(ctx.author)
        via = "slash" if ctx.interaction else "prefix"
        log.info("search by %s via %s: %r", user, via, query)

        if not query:
            await ctx.reply("Please provide a movie or show name.", mention_author=False)
            return

        await ctx.defer()

        try:
            results = await self.seerr.search(query)
        except SeerrError as exc:
            log.warning("Seerr search failed for %s query=%r: %s", user, query, exc)
            await ctx.reply(f"Seerr search failed: {exc}", mention_author=False)
            return
        except Exception:
            log.exception("Unexpected search error for %s query=%r", user, query)
            await ctx.reply("Unexpected error talking to Seerr.", mention_author=False)
            return

        if not results:
            log.info("No results for %s query=%r", user, query)
            await ctx.reply(f"No movies or shows found for **{query}**.", mention_author=False)
            return

        log.info("Search returned %s result(s) for %s query=%r", len(results), user, query)
        view = ResultSelectView(
            results,
            seerr=self.seerr,
            omdb=self.omdb,
            config=self.config,
        )
        await ctx.reply(
            f"Found **{len(results)}** result(s) for **{query}**. Pick one:",
            view=view,
            mention_author=False,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SearchCog(bot))
