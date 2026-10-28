import asyncio
import pkgutil
import time

import discord
from discord.ext import commands

import cogs as cogs_pkg
from config import Config
from utils.database import Database


class TicketBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True

        super().__init__(
            command_prefix=self._get_prefix,
            intents=intents,
            help_command=None,
            owner_ids=set(Config.OWNER_IDS),
            case_insensitive=True,
            strip_after_prefix=True,
        )
        self.db = Database()
        self.start_time = time.time()
        self.dashboard_task: asyncio.Task | None = None

    async def _get_prefix(self, bot: "TicketBot", message: discord.Message):
        if not message.guild:
            return commands.when_mentioned_or(Config.DEFAULT_PREFIX)(bot, message)
        try:
            prefix = await self.db.get_prefix(message.guild.id)
        except Exception:
            prefix = Config.DEFAULT_PREFIX
        return commands.when_mentioned_or(prefix or Config.DEFAULT_PREFIX)(bot, message)

    async def setup_hook(self):
        await self.db.init()
        print("  Database ready")

        await self._autoload_emojis()

        import ui
        for view in ui.persistent_templates():
            self.add_view(view)
        print("  Persistent ticket/panel buttons registered")

        cog_names = sorted(
            name for _, name, is_pkg in pkgutil.iter_modules(cogs_pkg.__path__)
            if not is_pkg and not name.startswith("_")
        )
        for cog in cog_names:
            try:
                await self.load_extension(f"cogs.{cog}")
                print(f"  Loaded cog: {cog}")
            except Exception as e:
                print(f"  Failed to load cog {cog}: {e!r}")

        try:
            synced = await self.tree.sync()
            print(f"  Synced {len(synced)} slash command(s)")
        except Exception as e:
            print(f"  Slash command sync failed: {e}")

        if Config.DASHBOARD_ENABLED:
            from dashboard.app import run_dashboard
            self.dashboard_task = self.loop.create_task(run_dashboard(self), name="dashboard")

            def _on_dashboard_done(task: asyncio.Task):
                if task.cancelled():
                    return
                exc = task.exception()
                if exc:
                    print(f"  Dashboard task ended with an error: {exc!r}")

            self.dashboard_task.add_done_callback(_on_dashboard_done)
        else:
            print("  Dashboard disabled (DASHBOARD_ENABLED=false)")

    async def close(self):
        if self.dashboard_task and not self.dashboard_task.done():
            self.dashboard_task.cancel()
            try:
                await self.dashboard_task
            except (asyncio.CancelledError, Exception):
                pass
        await self.db.close()
        await super().close()

    async def _autoload_emojis(self):
        try:
            from scripts.upload_application_emojis import run_sync
            summary = await asyncio.wait_for(
                run_sync(token=Config.TOKEN, quiet=True, timeout=15.0), timeout=25.0,
            )
            if summary.get("uploaded"):
                from emojis import Emojis
                Emojis.reload()
                print(f"  Emoji sync: uploaded {summary['uploaded']} new emoji(s)")
            else:
                print("  Emoji sync: up to date")
        except Exception as e:
            print(f"  Emoji sync skipped ({e}) - using cached/fallback icons")

    async def on_ready(self):
        print(f"  Logged in as {self.user} ({self.user.id})")
        print(f"  In {len(self.guilds)} guild(s)")
        await self.change_presence(
            status=discord.Status.online,
            activity=discord.Activity(type=discord.ActivityType.watching, name="FX Devs (r3novadcl)"),
        )


async def main():
    if not Config.TOKEN:
        raise SystemExit("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")

    bot = TicketBot()
    async with bot:
        await bot.start(Config.TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  Shutting down.")
