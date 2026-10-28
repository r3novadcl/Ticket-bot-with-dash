import time

import discord
from discord.ext import commands
from discord import app_commands

import ui
from emojis import Emojis
from config import Config


class Events(commands.Cog, name="Info"):
    def __init__(self, bot):
        self.bot = bot
        bot.tree.on_error = self.on_app_command_error

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.content.strip() in (f"<@{self.bot.user.id}>", f"<@!{self.bot.user.id}>"):
            prefix = await self.bot.db.get_prefix(message.guild.id) or Config.DEFAULT_PREFIX
            text = (
                f"__**Hey {message.author.display_name}!**__\n"
                f"{Emojis.DOT} My prefix here is `{prefix}`\n"
                f"{Emojis.DOT} Type `{prefix}help` or `/help` for commands\n"
                f"{Emojis.DOT} Try `/panel create` to set up a ticket panel"
            )
            await message.reply(view=ui.text_container(text, "blue"))

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingPermissions):
            perms = ", ".join(f"`{p}`" for p in error.missing_permissions)
            return await ctx.reply(view=ui.error(f"You need {perms} permission(s)."))
        if isinstance(error, commands.BotMissingPermissions):
            perms = ", ".join(f"`{p}`" for p in error.missing_permissions)
            return await ctx.reply(view=ui.error(f"I need {perms} permission(s) to do that."))
        if isinstance(error, commands.MissingRequiredArgument):
            return await ctx.reply(view=ui.error(
                f"Missing argument: `{error.param.name}`\n"
                f"Usage: `{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}`"
            ))
        if isinstance(error, commands.BadArgument):
            return await ctx.reply(view=ui.error(str(error)))
        if isinstance(error, commands.CommandOnCooldown):
            return await ctx.reply(view=ui.error(f"Slow down! Try again in `{error.retry_after:.1f}s`."))
        if isinstance(error, commands.NotOwner):
            return await ctx.reply(view=ui.error("Owner-only command."))
        if isinstance(error, commands.CheckFailure):
            return await ctx.reply(view=ui.error("You don't have permission to use this command."))

        print(f"[on_command_error] {ctx.command}: {error!r}")
        await ctx.reply(view=ui.error(f"An error occurred:\n```py\n{str(error)[:500]}\n```"))

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            perms = ", ".join(f"`{p}`" for p in error.missing_permissions)
            view = ui.error(f"You need {perms} permission(s).")
        elif isinstance(error, app_commands.CheckFailure):
            view = ui.error("You don't have permission to use this command.")
        elif isinstance(error, app_commands.CommandOnCooldown):
            view = ui.error(f"Slow down! Try again in `{error.retry_after:.1f}s`.")
        else:
            print(f"[on_app_command_error] {interaction.command}: {error!r}")
            view = ui.error(f"An error occurred:\n```py\n{str(error)[:500]}\n```")

        try:
            if interaction.response.is_done():
                await interaction.followup.send(view=view, ephemeral=True)
            else:
                await interaction.response.send_message(view=view, ephemeral=True)
        except discord.HTTPException:
            pass

    def _help_text(self, prefix: str) -> str:
        lines = [f"__**FeroX Tickets**__"]
        for cog_name, cog in sorted(self.bot.cogs.items()):
            cmds = [c for c in cog.get_commands() if not c.hidden]
            if not cmds:
                continue
            lines.append(f"\n**{cog_name}**")
            for c in cmds:
                lines.append(f"{Emojis.DOT} `{prefix}{c.qualified_name}`")
        return "\n".join(lines)

    @commands.command(name="help", aliases=["commands"])
    async def help_cmd(self, ctx):
        prefix = await self.bot.db.get_prefix(ctx.guild.id) if ctx.guild else "!"
        await ctx.reply(view=ui.text_container(self._help_text(prefix), "blue"))

    @app_commands.command(name="help", description="Show all available commands.")
    async def help_slash(self, interaction: discord.Interaction):
        prefix = await self.bot.db.get_prefix(interaction.guild.id) if interaction.guild else "!"
        await interaction.response.send_message(view=ui.text_container(self._help_text(prefix), "blue"), ephemeral=True)

    @commands.command(name="ping")
    async def ping_cmd(self, ctx):
        await ctx.reply(view=ui.text_container(f"{Emojis.LATENCY} Pong! `{round(self.bot.latency * 1000)}ms`", "blue"))

    @app_commands.command(name="ping", description="Check the bot's latency.")
    async def ping_slash(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            view=ui.text_container(f"{Emojis.LATENCY} Pong! `{round(self.bot.latency * 1000)}ms`", "blue"), ephemeral=True,
        )

    def _about_text(self) -> str:
        from utils.helpers import format_uptime
        return (
            f"__**FeroX Tickets**__\n"
            f"{Emojis.DOT} **Uptime:** `{format_uptime(self.bot.start_time)}`\n"
            f"{Emojis.DOT} **Servers:** `{len(self.bot.guilds)}`\n"
            f"{Emojis.DOT} **discord.py:** `{discord.__version__}`"
        )

    @commands.command(name="about", aliases=["botinfo", "uptime"])
    async def about_cmd(self, ctx):
        await ctx.reply(view=ui.text_container(self._about_text(), "blue"))

    @app_commands.command(name="about", description="Show bot info and uptime.")
    async def about_slash(self, interaction: discord.Interaction):
        await interaction.response.send_message(view=ui.text_container(self._about_text(), "blue"), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Events(bot))
