"""Seerr Discord bot entrypoint."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from config import Config, load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("seerr-bot")


class SeerrBot(commands.Bot):
    def __init__(self, *, config: Config) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=config.command_prefix, intents=intents)
        self.config = config

    async def setup_hook(self) -> None:
        await self.load_extension("cogs.search")

        # Guild sync is instant. Global sync can take up to ~1 hour and also
        # duplicates /search in the UI if both are registered — so only one.
        if self.config.discord_guild_id:
            guild = discord.Object(id=self.config.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info(
                "Synced %s slash command(s) to guild %s (instant)",
                len(synced),
                self.config.discord_guild_id,
            )
            for cmd in synced:
                log.info("  /%s", cmd.name)

            # Drop global commands so Discord doesn't show two /search entries
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            log.info("Cleared global slash commands to avoid duplicates")
        else:
            synced = await self.tree.sync()
            log.info("Synced %s global application command(s)", len(synced))
            log.warning(
                "DISCORD_GUILD_ID is not set — global slash sync can take up to an hour. "
                "Set your server ID for instant /search."
            )

    async def on_ready(self) -> None:
        assert self.user is not None
        log.info("Logged in as %s (%s)", self.user, self.user.id)
        log.info("Invite needs scope: bot + applications.commands")

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        author = f"{ctx.author} ({ctx.author.id})" if ctx.author else "unknown"
        log.warning("Command error for %s in %s: %s", author, ctx.command, error)


def main() -> None:
    config = load_config()
    bot = SeerrBot(config=config)
    bot.run(config.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
