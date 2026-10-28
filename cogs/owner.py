import platform
import time

import discord
import psutil
from discord.ext import commands

import ui
from emojis import Emojis
from utils.helpers import DURATION_MAP


class Owner(commands.Cog, name="Owner"):
    """Owner-only utilities, hidden from the public help menu."""

    def __init__(self, bot):
        self.bot = bot

    def _looks_like_command(self, content: str) -> bool:
        if not content:
            return False
        first_word = content.split(maxsplit=1)[0].lower()
        return bool(first_word) and self.bot.get_command(first_word) is not None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return

        content = message.content.strip()
        if not content:
            return

        try:
            prefixes = await self.bot._get_prefix(self.bot, message)
        except Exception:
            from config import Config
            prefixes = [Config.DEFAULT_PREFIX]
        if isinstance(prefixes, str):
            prefixes = [prefixes]
        for p in prefixes:
            if isinstance(p, str) and content.startswith(p):
                return

        if not self._looks_like_command(content):
            return
        if not await self.bot.db.is_noprefix(message.author.id):
            return

        new_ctx = await self.bot.get_context(message)
        new_ctx.prefix = ""
        new_ctx.command = self.bot.get_command(content.split(maxsplit=1)[0].lower())
        if new_ctx.command is None:
            return
        try:
            await self.bot.invoke(new_ctx)
        except Exception as e:
            print(f"[noprefix] dispatch error for {message.author.id}: {e}")

    # cog / bot management

    @commands.command(name="reload", hidden=True)
    @commands.is_owner()
    async def reload_cog(self, ctx, cog: str):
        try:
            await self.bot.reload_extension(f"cogs.{cog}")
            view = ui.success(f"Reloaded `{cog}`.")
        except commands.ExtensionNotLoaded:
            view = ui.error(f"`{cog}` isn't loaded.")
        except Exception as e:
            view = ui.error(f"Failed to reload `{cog}`:\n```py\n{e}\n```")
        await ctx.reply(view=view)

    @commands.command(name="load", hidden=True)
    @commands.is_owner()
    async def load_cog(self, ctx, cog: str):
        try:
            await self.bot.load_extension(f"cogs.{cog}")
            view = ui.success(f"Loaded `{cog}`.")
        except commands.ExtensionAlreadyLoaded:
            view = ui.error(f"`{cog}` is already loaded.")
        except Exception as e:
            view = ui.error(f"Failed to load `{cog}`:\n```py\n{e}\n```")
        await ctx.reply(view=view)

    @commands.command(name="unload", hidden=True)
    @commands.is_owner()
    async def unload_cog(self, ctx, cog: str):
        if cog == "owner":
            return await ctx.reply(view=ui.error("Can't unload the owner cog."))
        try:
            await self.bot.unload_extension(f"cogs.{cog}")
            view = ui.success(f"Unloaded `{cog}`.")
        except commands.ExtensionNotLoaded:
            view = ui.error(f"`{cog}` isn't loaded.")
        await ctx.reply(view=view)

    @commands.command(name="sync", hidden=True)
    @commands.is_owner()
    async def sync_cmds(self, ctx, scope: str = "global"):
        msg = await ctx.reply(view=ui.text_container(f"{Emojis.LOADING} Syncing...", "blue"))
        try:
            synced = await self.bot.tree.sync(guild=ctx.guild) if scope == "guild" and ctx.guild else await self.bot.tree.sync()
            view = ui.success(f"Synced `{len(synced)}` command(s) ({scope}).")
        except Exception as e:
            view = ui.error(f"Sync failed:\n```py\n{e}\n```")
        await msg.edit(view=view)

    @commands.command(name="shutdown", aliases=["die"], hidden=True)
    @commands.is_owner()
    async def shutdown(self, ctx):
        await ctx.reply(view=ui.text_container(f"{Emojis.SHUTDOWN} Shutting down...", "red"))
        await self.bot.close()

    @commands.command(name="setstatus", hidden=True)
    @commands.is_owner()
    async def setstatus(self, ctx, status: str):
        status_map = {"online": discord.Status.online, "idle": discord.Status.idle,
                      "dnd": discord.Status.dnd, "invisible": discord.Status.invisible}
        s = status_map.get(status.lower())
        if not s:
            return await ctx.reply(view=ui.error("Invalid status. Use: online, idle, dnd, invisible."))
        await self.bot.change_presence(status=s)
        await ctx.reply(view=ui.success(f"Status set to `{status}`."))

    @commands.command(name="setactivity", hidden=True)
    @commands.is_owner()
    async def setactivity(self, ctx, *, text: str):
        await self.bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=text))
        await ctx.reply(view=ui.success(f"Activity set to `{text}`."))

    @commands.command(name="eval", aliases=["ev"], hidden=True)
    @commands.is_owner()
    async def eval_cmd(self, ctx, *, code: str):
        code = code.strip("`")
        if code.startswith("py"):
            code = code[2:].strip()
        env = {"bot": self.bot, "ctx": ctx, "discord": discord}
        try:
            result = eval(code, env)
            if hasattr(result, "__await__"):
                result = await result
            view = ui.text_container(f"{Emojis.CHECK} ```py\n{result}\n```", "blue")
        except Exception as e:
            view = ui.error(f"```py\n{type(e).__name__}: {e}\n```")
        await ctx.reply(view=view)

    @commands.command(name="sysinfo", hidden=True)
    @commands.is_owner()
    async def sysinfo(self, ctx):
        uptime = int(time.time() - self.bot.start_time)
        h, rem = divmod(uptime, 3600)
        m, s = divmod(rem, 60)
        mem = psutil.Process().memory_info().rss / 1024 / 1024
        open_tickets = sum(len(await self.bot.db.list_open_tickets(g.id)) for g in self.bot.guilds)

        text = (
            f"__**System Info**__\n"
            f"{Emojis.DOT} **Python:** `{platform.python_version()}`\n"
            f"{Emojis.DOT} **discord.py:** `{discord.__version__}`\n"
            f"{Emojis.DOT} **CPU:** `{psutil.cpu_percent()}%`\n"
            f"{Emojis.DOT} **Memory:** `{mem:.1f} MB`\n"
            f"{Emojis.DOT} **Uptime:** `{h}h {m}m {s}s`\n"
            f"{Emojis.DOT} **Guilds:** `{len(self.bot.guilds)}`\n"
            f"{Emojis.DOT} **Open tickets (Globally):** `{open_tickets}`"
        )
        await ctx.reply(view=ui.text_container(text, "blue"))

    @commands.command(name="guilds", hidden=True)
    @commands.is_owner()
    async def guilds_list(self, ctx):
        lines = [f"### {Emojis.INFO} Guilds ({len(self.bot.guilds)})"]
        for g in sorted(self.bot.guilds, key=lambda x: x.member_count or 0, reverse=True)[:25]:
            lines.append(f"{Emojis.DOT} **{g.name}** — `{g.member_count}` members (`{g.id}`)")
        await ctx.reply(view=ui.text_container("\n".join(lines), "blue"))

    @commands.command(name="leaveguild", hidden=True)
    @commands.is_owner()
    async def leave_guild(self, ctx, guild_id: int):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return await ctx.reply(view=ui.error("I'm not in a guild with that ID."))
        name = guild.name
        await guild.leave()
        await ctx.reply(view=ui.success(f"Left `{name}`."))

    # noprefix

    @commands.group(name="noprefix", aliases=["np"], invoke_without_command=True, hidden=True)
    @commands.is_owner()
    async def noprefix(self, ctx):
        text = (
            f"__**NoPrefix Management**__\n"
            f"{Emojis.DOT} `{ctx.prefix}noprefix add @user [1h/6h/1d/7d/30d/lifetime]`\n"
            f"{Emojis.DOT} `{ctx.prefix}noprefix remove @user`\n"
            f"{Emojis.DOT} `{ctx.prefix}noprefix list`\n"
            f"{Emojis.DOT} `{ctx.prefix}noprefix check @user`"
        )
        await ctx.reply(view=ui.text_container(text, "blue"))

    @noprefix.command(name="add", hidden=True)
    @commands.is_owner()
    async def noprefix_add(self, ctx, member: discord.Member, duration: str = "lifetime"):
        duration = duration.lower()
        if duration not in DURATION_MAP:
            return await ctx.reply(view=ui.error("Invalid duration. Use one of: `1h`, `6h`, `1d`, `7d`, `30d`, `lifetime`."))

        seconds = DURATION_MAP[duration]
        expires_at = int(time.time()) + seconds if seconds else None
        await self.bot.db.add_noprefix(member.id, ctx.author.id, expires_at)

        expiry_text = "Never (Lifetime)" if expires_at is None else f"<t:{expires_at}:R>"
        await ctx.reply(view=ui.text_container(
            f"{Emojis.SUCCESS} NoPrefix Granted\n{Emojis.DOT} **User:** {member.mention}\n"
            f"{Emojis.DOT} **Expires:** {expiry_text}", "blue",
        ))
        try:
            await member.send(view=ui.text_container(
                f"{Emojis.SUCCESS} You've been granted NoPrefix!\n"
                f"{Emojis.DOT} You can now use commands without typing a prefix.\n"
                f"{Emojis.DOT} **Expires:** {expiry_text}", "blue",
            ))
        except discord.HTTPException:
            pass

    @noprefix.command(name="remove", hidden=True)
    @commands.is_owner()
    async def noprefix_remove(self, ctx, member: discord.Member):
        if not await self.bot.db.remove_noprefix(member.id):
            return await ctx.reply(view=ui.error(f"{member.mention} doesn't have NoPrefix."))
        await ctx.reply(view=ui.success(f"Removed NoPrefix from {member.mention}."))

    @noprefix.command(name="check", hidden=True)
    @commands.is_owner()
    async def noprefix_check(self, ctx, member: discord.Member):
        row = await self.bot.db.get_noprefix(member.id)
        if not row or not await self.bot.db.is_noprefix(member.id):
            return await ctx.reply(view=ui.text_container(f"{Emojis.INFO} {member.mention} doesn't have active NoPrefix.", "blue"))
        _, added_by, added_at, expires_at = row
        expiry_text = "Never (Lifetime)" if expires_at is None else f"<t:{expires_at}:R>"
        await ctx.reply(view=ui.text_container(
            f"{Emojis.INFO} NoPrefix Status\n{Emojis.DOT} **User:** {member.mention}\n"
            f"{Emojis.DOT} **Granted:** <t:{added_at}:R>\n{Emojis.DOT} **Expires:** {expiry_text}", "blue",
        ))

    @noprefix.command(name="list", hidden=True)
    @commands.is_owner()
    async def noprefix_list(self, ctx):
        rows = await self.bot.db.list_noprefix()
        if not rows:
            return await ctx.reply(view=ui.text_container(f"{Emojis.INFO} No users have NoPrefix.", "blue"))
        lines = [f"__**NoPrefix Users**__ ({len(rows)})"]
        for user_id, added_by, added_at, expires_at in rows[:25]:
            expiry_text = "Lifetime" if expires_at is None else f"<t:{expires_at}:R>"
            lines.append(f"{Emojis.DOT} <@{user_id}> — expires {expiry_text}")
        await ctx.reply(view=ui.text_container("\n".join(lines), "blue"))


async def setup(bot):
    await bot.add_cog(Owner(bot))
