from typing import Literal, Optional

import discord
from discord.ext import commands

import ui
from emojis import Emojis
from utils import helpers, ticket_manager

Theme = Literal["red", "cyan", "blue", "purple", "white"]


class Tickets(commands.Cog, name="Tickets"):
    def __init__(self, bot):
        self.bot = bot

    async def _require_ticket(self, ctx: commands.Context) -> Optional[dict]:
        ticket = await self.bot.db.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            await ctx.reply(view=ui.error("This command only works inside a ticket channel."))
            return None
        return ticket

    async def _require_staff(self, ctx: commands.Context, ticket: dict) -> bool:
        cfg = await self.bot.db.get_guild_config(ctx.guild.id)
        if helpers.can_manage_ticket(self.bot, ctx.author, ticket, cfg):
            return True
        await ctx.reply(view=ui.error("You don't have permission to manage this ticket."))
        return False

    # ticketconfig

    @commands.hybrid_group(name="ticketconfig", aliases=["tconfig"], description="Configure the ticket system.")
    @helpers.require_manage_guild()
    async def ticketconfig(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await self._show_config(ctx)

    @ticketconfig.command(name="view", description="Show the current ticket configuration.")
    @helpers.require_manage_guild()
    async def tc_view(self, ctx: commands.Context):
        await self._show_config(ctx)

    async def _show_config(self, ctx: commands.Context):
        cfg = await self.bot.db.get_guild_config(ctx.guild.id)
        category = ctx.guild.get_channel(cfg["category_id"]) if cfg["category_id"] else None
        log_ch = ctx.guild.get_channel(cfg["log_channel_id"]) if cfg["log_channel_id"] else None
        transcript_ch = ctx.guild.get_channel(cfg["transcript_channel_id"]) if cfg["transcript_channel_id"] else None
        staff_roles = ", ".join(r.mention for r in helpers.eligible_staff_roles(ctx.guild, cfg)) or "*none set*"
        senior_roles = ", ".join(r.mention for r in helpers.eligible_senior_roles(ctx.guild, cfg)) or "*none set*"

        text = (
            f"__**Ticket Configuration**__\n"
            f"{Emojis.DOT} **Prefix:** `{cfg['prefix']}`\n"
            f"{Emojis.DOT} **Theme:** `{helpers.theme_label(cfg['theme'])}`\n"
            f"{Emojis.DOT} **Default category:** {category.mention if category else '*not set*'}\n"
            f"{Emojis.DOT} **Log channel:** {log_ch.mention if log_ch else '*not set*'}\n"
            f"{Emojis.DOT} **Transcript channel:** {transcript_ch.mention if transcript_ch else '*not set*'}\n"
            f"{Emojis.DOT} **Staff roles:** {staff_roles}\n"
            f"{Emojis.DOT} **Senior/escalation roles:** {senior_roles}\n"
            f"{Emojis.DOT} **Max tickets per user:** `{cfg['max_tickets_per_user']}`\n"
            f"{Emojis.DOT} **Auto-close after (hours, 0 = off):** `{cfg['auto_close_hours']}`\n"
            f"{Emojis.DOT} **Transcripts enabled:** `{cfg['transcripts_enabled']}`\n"
            f"{Emojis.DOT} **Welcome message:** {cfg['welcome_message']}"
        )
        await ctx.reply(view=ui.text_container(text, cfg["theme"]))

    @ticketconfig.command(name="prefix", description="Set the command prefix for this server.")
    @helpers.require_manage_guild()
    async def tc_prefix(self, ctx: commands.Context, prefix: str):
        if len(prefix) > 5:
            return await ctx.reply(view=ui.error("Prefix must be 5 characters or fewer."))
        await self.bot.db.set_prefix(ctx.guild.id, prefix)
        await ctx.reply(view=ui.success(f"Prefix set to `{prefix}`."))

    @ticketconfig.command(name="theme", description="Set the default colour theme.")
    @helpers.require_manage_guild()
    async def tc_theme(self, ctx: commands.Context, theme: Theme):
        await self.bot.db.update_guild_config(ctx.guild.id, theme=theme)
        await ctx.reply(view=ui.success(f"Theme set to `{helpers.theme_label(theme)}`.", theme))

    @ticketconfig.command(name="category", description="Set the default category new tickets are created in.")
    @helpers.require_manage_guild()
    async def tc_category(self, ctx: commands.Context, category: discord.CategoryChannel):
        await self.bot.db.update_guild_config(ctx.guild.id, category_id=category.id)
        await ctx.reply(view=ui.success(f"Default ticket category set to {category.mention}."))

    @ticketconfig.command(name="logchannel", description="Set the channel ticket action logs are posted to.")
    @helpers.require_manage_guild()
    async def tc_logchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        await self.bot.db.update_guild_config(ctx.guild.id, log_channel_id=channel.id)
        await ctx.reply(view=ui.success(f"Log channel set to {channel.mention}."))

    @ticketconfig.command(name="transcriptchannel", description="Set the channel closed-ticket transcripts are posted to.")
    @helpers.require_manage_guild()
    async def tc_transcriptchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        await self.bot.db.update_guild_config(ctx.guild.id, transcript_channel_id=channel.id)
        await ctx.reply(view=ui.success(f"Transcript channel set to {channel.mention}."))

    @ticketconfig.command(name="maxtickets", description="Max open tickets a single member can have at once.")
    @helpers.require_manage_guild()
    async def tc_maxtickets(self, ctx: commands.Context, amount: int):
        amount = max(1, min(amount, 25))
        await self.bot.db.update_guild_config(ctx.guild.id, max_tickets_per_user=amount)
        await ctx.reply(view=ui.success(f"Max tickets per user set to `{amount}`."))

    @ticketconfig.command(name="autoclose", description="Auto-close tickets left inactive this many hours (0 = off).")
    @helpers.require_manage_guild()
    async def tc_autoclose(self, ctx: commands.Context, hours: int):
        hours = max(0, min(hours, 720))
        await self.bot.db.update_guild_config(ctx.guild.id, auto_close_hours=hours)
        text = "Auto-close disabled." if hours == 0 else f"Tickets auto-close after `{hours}h` of inactivity."
        await ctx.reply(view=ui.success(text))

    @ticketconfig.command(name="transcripts", description="Enable or disable transcript generation.")
    @helpers.require_manage_guild()
    async def tc_transcripts(self, ctx: commands.Context, enabled: bool):
        await self.bot.db.update_guild_config(ctx.guild.id, transcripts_enabled=int(enabled))
        await ctx.reply(view=ui.success(f"Transcripts {'enabled' if enabled else 'disabled'}."))

    @ticketconfig.command(name="welcome", description="Set the welcome message posted in every new ticket.")
    @helpers.require_manage_guild()
    async def tc_welcome(self, ctx: commands.Context, *, message: str):
        await self.bot.db.update_guild_config(ctx.guild.id, welcome_message=message[:500])
        await ctx.reply(view=ui.success("Welcome message updated."))

    @ticketconfig.group(name="staffrole", description="Manage staff roles.")
    @helpers.require_manage_guild()
    async def tc_staffrole(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.reply(view=ui.error(f"Use `{ctx.prefix}ticketconfig staffrole add/remove <role>`."))

    @tc_staffrole.command(name="add", description="Add a staff role.")
    @helpers.require_manage_guild()
    async def tc_staffrole_add(self, ctx: commands.Context, role: discord.Role):
        await self.bot.db.add_staff_role(ctx.guild.id, role.id)
        await ctx.reply(view=ui.success(f"{role.mention} can now claim and manage tickets."))

    @tc_staffrole.command(name="remove", description="Remove a staff role.")
    @helpers.require_manage_guild()
    async def tc_staffrole_remove(self, ctx: commands.Context, role: discord.Role):
        await self.bot.db.remove_staff_role(ctx.guild.id, role.id)
        await ctx.reply(view=ui.success(f"{role.mention} removed from staff roles."))

    @ticketconfig.group(name="seniorrole", description="Manage senior/escalation roles (transfer targets).")
    @helpers.require_manage_guild()
    async def tc_seniorrole(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.reply(view=ui.error(f"Use `{ctx.prefix}ticketconfig seniorrole add/remove <role>`."))

    @tc_seniorrole.command(name="add", description="Add a senior/escalation role. It never needs Administrator.")
    @helpers.require_manage_guild()
    async def tc_seniorrole_add(self, ctx: commands.Context, role: discord.Role):
        await self.bot.db.add_senior_role(ctx.guild.id, role.id)
        await ctx.reply(view=ui.success(
            f"{role.mention} added as a senior/escalation role. Transferred tickets get an explicit "
            f"channel permission from the bot — this role does not need Administrator."
        ))

    @tc_seniorrole.command(name="remove", description="Remove a senior/escalation role.")
    @helpers.require_manage_guild()
    async def tc_seniorrole_remove(self, ctx: commands.Context, role: discord.Role):
        await self.bot.db.remove_senior_role(ctx.guild.id, role.id)
        await ctx.reply(view=ui.success(f"{role.mention} removed from senior/escalation roles."))

    # panel

    @commands.hybrid_group(name="panel", description="Manage ticket panels.")
    @helpers.require_manage_guild()
    async def panel(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await self._panel_list(ctx)

    @panel.command(name="create", description="Post a new ticket panel in a channel.")
    @helpers.require_manage_guild()
    async def panel_create(
        self, ctx: commands.Context, channel: discord.TextChannel,
        title: str = "Support Tickets", description: str = "Click the button below to open a ticket.",
        theme: Optional[Theme] = None, category: Optional[discord.CategoryChannel] = None,
        button_label: str = "Open Ticket", button_emoji: Optional[str] = None,
        staff_role: Optional[discord.Role] = None,
    ):
        cfg = await self.bot.db.get_guild_config(ctx.guild.id)
        resolved_theme = theme or cfg["theme"]

        perms = channel.permissions_for(ctx.guild.me)
        if not (perms.send_messages and perms.view_channel):
            return await ctx.reply(view=ui.error(f"I need permission to send messages in {channel.mention}."))

        panel_id = await self.bot.db.create_panel(
            ctx.guild.id, channel.id, title, description, resolved_theme,
            category.id if category else None, button_label, button_emoji,
            [staff_role.id] if staff_role else [], ctx.author.id,
        )
        view = ui.build_panel_view(title, description, resolved_theme, button_label, button_emoji)
        message = await channel.send(view=view)
        await self.bot.db.set_panel_message(panel_id, message.id)

        await ctx.reply(view=ui.success(f"Panel **#{panel_id}** posted in {channel.mention}.", resolved_theme))

    @panel.command(name="list", description="List all ticket panels in this server.")
    @helpers.require_manage_guild()
    async def panel_list(self, ctx: commands.Context):
        await self._panel_list(ctx)

    async def _panel_list(self, ctx: commands.Context):
        panels = await self.bot.db.list_panels(ctx.guild.id)
        if not panels:
            return await ctx.reply(view=ui.text_container(f"{Emojis.INFO} No panels configured yet. Use `/panel create` or visit dashboard.", "blue"))
        lines = [f"__**Ticket Panels**__ ({len(panels)})"]
        for p in panels:
            ch = ctx.guild.get_channel(p["channel_id"])
            lines.append(
                f"{Emojis.DOT} **#{p['panel_id']}** — \"{p['title']}\" in "
                f"{ch.mention if ch else '`deleted channel`'} (`{helpers.theme_label(p['theme'])}`)"
            )
        await ctx.reply(view=ui.text_container("\n".join(lines), "blue"))

    @panel.command(name="delete", description="Delete a ticket panel (does not affect existing open tickets).")
    @helpers.require_manage_guild()
    async def panel_delete(self, ctx: commands.Context, panel_id: int):
        p = await self.bot.db.get_panel(panel_id)
        if not p or p["guild_id"] != ctx.guild.id:
            return await ctx.reply(view=ui.error("No panel with that ID in this server."))
        channel = ctx.guild.get_channel(p["channel_id"])
        if channel and p["message_id"]:
            try:
                msg = await channel.fetch_message(p["message_id"])
                await msg.delete()
            except discord.HTTPException:
                pass
        await self.bot.db.delete_panel(panel_id)
        await ctx.reply(view=ui.success(f"Panel **#{panel_id}** deleted."))

    @panel.command(name="edit", description="Edit a panel's title, description, or theme.")
    @helpers.require_manage_guild()
    async def panel_edit(
        self, ctx: commands.Context, panel_id: int,
        title: Optional[str] = None, description: Optional[str] = None, theme: Optional[Theme] = None,
    ):
        p = await self.bot.db.get_panel(panel_id)
        if not p or p["guild_id"] != ctx.guild.id:
            return await ctx.reply(view=ui.error("No panel with that ID in this server."))
        fields = {}
        if title:
            fields["title"] = title
        if description:
            fields["description"] = description
        if theme:
            fields["theme"] = theme
        if not fields:
            return await ctx.reply(view=ui.error("Nothing to update — pass at least one field."))
        await self.bot.db.update_panel(panel_id, **fields)
        p = await self.bot.db.get_panel(panel_id)

        channel = ctx.guild.get_channel(p["channel_id"])
        if channel and p["message_id"]:
            try:
                view = ui.build_panel_view(p["title"], p["description"], p["theme"], p["button_label"], p["button_emoji"])
                msg = await channel.fetch_message(p["message_id"])
                await msg.edit(view=view)
            except discord.HTTPException:
                pass
        await ctx.reply(view=ui.success(f"Panel **#{panel_id}** updated."))

    # ticket actions

    @commands.hybrid_group(name="ticket", description="Manage support tickets.", fallback="help")
    async def ticket(self, ctx: commands.Context):
        text = (
            f"__**Ticket Commands**__\n"
            f"{Emojis.DOT} `{ctx.prefix}ticket open [subject]` — open a new ticket\n"
            f"{Emojis.DOT} `{ctx.prefix}ticket claim` / `unclaim` — claim/unclaim (staff)\n"
            f"{Emojis.DOT} `{ctx.prefix}ticket close [reason]` / `reopen` — close/reopen (staff)\n"
            f"{Emojis.DOT} `{ctx.prefix}ticket lock` / `unlock` — restrict members to read-only (staff)\n"
            f"{Emojis.DOT} `{ctx.prefix}ticket add <user>` / `remove <user>` — manage participants (staff)\n"
            f"{Emojis.DOT} `{ctx.prefix}ticket rename <name>` — rename the channel (staff)\n"
            f"{Emojis.DOT} `{ctx.prefix}ticket transfer <role> [reason]` — escalate to senior staff\n"
            f"{Emojis.DOT} `{ctx.prefix}ticket transcript` — generate/download a transcript\n"
            f"{Emojis.DOT} `{ctx.prefix}ticket history` — show this ticket's transfer history\n"
            f"{Emojis.DOT} `{ctx.prefix}ticket delete` — permanently delete this ticket (staff)"
        )
        await ctx.reply(view=ui.text_container(text, "blue"))

    @ticket.command(name="open", description="Open a new support ticket.")
    async def ticket_open(self, ctx: commands.Context, *, subject: Optional[str] = None):
        cfg = await self.bot.db.get_guild_config(ctx.guild.id)

        if await self.bot.db.is_blacklisted(ctx.guild.id, ctx.author.id):
            return await ctx.reply(view=ui.error("You're blacklisted from opening tickets here."))

        open_count = await self.bot.db.count_open_tickets_for_user(ctx.guild.id, ctx.author.id)
        limit = cfg["max_tickets_per_user"] or 1
        if open_count >= limit:
            return await ctx.reply(view=ui.error(f"You already have `{open_count}` open ticket(s) (limit: `{limit}`)."))

        panels = await self.bot.db.list_panels(ctx.guild.id)
        fake_panel = panels[0] if panels else {"panel_id": None, "category_id": cfg["category_id"], "theme": cfg["theme"]}

        ticket, channel = await ticket_manager.open_ticket(self.bot, ctx.guild, ctx.author, fake_panel)
        if not channel:
            return await ctx.reply(view=ui.error(
                f"Couldn't create your ticket channel — ask an admin to set a category with "
                f"`{ctx.prefix}ticketconfig category #category`."
            ))
        if subject:
            await self.bot.db.update_ticket(ticket["ticket_id"], subject=subject)
        await ctx.reply(view=ui.success(f"Your ticket is ready: {channel.mention}", cfg["theme"]))

    async def _refresh(self, ticket_id: int):
        await ticket_manager.refresh_ticket_message(self.bot, ticket_id)

    @ticket.command(name="claim", description="Claim this ticket.")
    async def ticket_claim(self, ctx: commands.Context):
        ticket = await self._require_ticket(ctx)
        if not ticket or not await self._require_staff(ctx, ticket):
            return
        if ticket["claimed_by"]:
            return await ctx.reply(view=ui.error("This ticket is already claimed."))
        await ticket_manager.claim(self.bot, ticket, ctx.author)
        await self._refresh(ticket["ticket_id"])
        await ctx.reply(view=ui.success("Ticket claimed."))

    @ticket.command(name="unclaim", description="Unclaim this ticket.")
    async def ticket_unclaim(self, ctx: commands.Context):
        ticket = await self._require_ticket(ctx)
        if not ticket or not await self._require_staff(ctx, ticket):
            return
        await ticket_manager.unclaim(self.bot, ticket, ctx.author)
        await self._refresh(ticket["ticket_id"])
        await ctx.reply(view=ui.success("Ticket unclaimed."))

    @ticket.command(name="close", description="Close this ticket.")
    async def ticket_close(self, ctx: commands.Context, *, reason: Optional[str] = None):
        ticket = await self._require_ticket(ctx)
        if not ticket or not await self._require_staff(ctx, ticket):
            return
        await ctx.reply(view=ui.text_container(f"{Emojis.LOADING} Closing & generating transcript...", "blue"))
        await ticket_manager.close(self.bot, ticket, ctx.author, reason)
        await self._refresh(ticket["ticket_id"])

    @ticket.command(name="reopen", description="Reopen this ticket.")
    async def ticket_reopen(self, ctx: commands.Context):
        ticket = await self._require_ticket(ctx)
        if not ticket or not await self._require_staff(ctx, ticket):
            return
        await ticket_manager.reopen(self.bot, ticket, ctx.author)
        await self._refresh(ticket["ticket_id"])
        await ctx.reply(view=ui.success("Ticket reopened."))

    @ticket.command(name="lock", description="Lock this ticket (opener/members become read-only).")
    async def ticket_lock(self, ctx: commands.Context):
        ticket = await self._require_ticket(ctx)
        if not ticket or not await self._require_staff(ctx, ticket):
            return
        await ticket_manager.lock(self.bot, ticket)
        await self._refresh(ticket["ticket_id"])
        await ctx.reply(view=ui.success("Ticket locked."))

    @ticket.command(name="unlock", description="Unlock this ticket.")
    async def ticket_unlock(self, ctx: commands.Context):
        ticket = await self._require_ticket(ctx)
        if not ticket or not await self._require_staff(ctx, ticket):
            return
        await ticket_manager.unlock(self.bot, ticket)
        await self._refresh(ticket["ticket_id"])
        await ctx.reply(view=ui.success("Ticket unlocked."))

    @ticket.command(name="rename", description="Rename this ticket's channel.")
    async def ticket_rename(self, ctx: commands.Context, *, name: str):
        ticket = await self._require_ticket(ctx)
        if not ticket or not await self._require_staff(ctx, ticket):
            return
        await ticket_manager.rename(self.bot, ticket, name)
        await self._refresh(ticket["ticket_id"])
        await ctx.reply(view=ui.success("Ticket renamed."))

    @ticket.command(name="add", description="Add a user to this ticket.")
    async def ticket_add(self, ctx: commands.Context, member: discord.Member):
        ticket = await self._require_ticket(ctx)
        if not ticket or not await self._require_staff(ctx, ticket):
            return
        await ticket_manager.add_member(self.bot, ticket, member, ctx.author)
        await ctx.reply(view=ui.success(f"Added {member.mention} to the ticket."))

    @ticket.command(name="remove", description="Remove a user from this ticket.")
    async def ticket_remove(self, ctx: commands.Context, member: discord.Member):
        ticket = await self._require_ticket(ctx)
        if not ticket or not await self._require_staff(ctx, ticket):
            return
        removed = await ticket_manager.remove_member(self.bot, ticket, member)
        if removed:
            await ctx.reply(view=ui.success(f"Removed {member.mention} from the ticket."))
        else:
            await ctx.reply(view=ui.error(f"{member.mention} wasn't added to this ticket."))

    @ticket.command(name="transfer", description="Transfer/escalate this ticket to a senior role.")
    async def ticket_transfer(self, ctx: commands.Context, role: discord.Role, *, reason: Optional[str] = None):
        ticket = await self._require_ticket(ctx)
        if not ticket or not await self._require_staff(ctx, ticket):
            return
        cfg = await self.bot.db.get_guild_config(ctx.guild.id)
        if role.id not in cfg.get("senior_role_ids", []):
            return await ctx.reply(view=ui.error(
                f"{role.mention} isn't a configured senior/escalation role. "
                f"Add it with `{ctx.prefix}ticketconfig seniorrole add @role`."
            ))
        await ticket_manager.transfer(self.bot, ticket, role, reason, ctx.author)
        await self._refresh(ticket["ticket_id"])
        await ctx.reply(view=ui.success(f"Ticket transferred to {role.mention}."))

    @ticket.command(name="transcript", description="Generate/download this ticket's transcript.")
    async def ticket_transcript(self, ctx: commands.Context):
        ticket = await self._require_ticket(ctx)
        if not ticket or not await self._require_staff(ctx, ticket):
            return
        path = await ticket_manager.generate_transcript(self.bot, ticket)
        if not path:
            return await ctx.reply(view=ui.error("Couldn't generate a transcript."))
        await ctx.reply(view=ui.success("Transcript generated."), file=discord.File(path))

    @ticket.command(name="history", description="Show this ticket's transfer/escalation history.")
    async def ticket_history(self, ctx: commands.Context):
        ticket = await self._require_ticket(ctx)
        if not ticket:
            return
        transfers = await self.bot.db.list_transfers(ticket["ticket_id"])
        if not transfers:
            return await ctx.reply(view=ui.text_container(f"{Emojis.INFO} This ticket has never been transferred.", "blue"))
        lines = [f"__**Transfer History — Ticket #{ticket['number']:04d}**__"]
        for t in transfers:
            from_text = f"<@{t['from_user_id']}>" if t["from_user_id"] else "*unclaimed*"
            lines.append(
                f"{Emojis.DOT} {from_text} → <@&{t['to_role_id']}> by <@{t['transferred_by']}> "
                f"<t:{t['transferred_at']}:R>" + (f" — _{t['reason']}_" if t["reason"] else "")
            )
        await ctx.reply(view=ui.text_container("\n".join(lines), "blue"))

    @ticket.command(name="delete", description="Permanently delete this ticket channel.")
    async def ticket_delete(self, ctx: commands.Context):
        ticket = await self._require_ticket(ctx)
        if not ticket or not await self._require_staff(ctx, ticket):
            return
        await ctx.reply(view=ui.text_container(f"{Emojis.WARNING} Deleting ticket & saving transcript...", "red"))
        await ticket_manager.delete(self.bot, ticket, ctx.author)

    # blacklist

    @commands.hybrid_group(name="blacklist", description="Manage the ticket blacklist.")
    @helpers.require_senior()
    async def blacklist(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await self._blacklist_list(ctx)

    @blacklist.command(name="add", description="Block a user from opening tickets.")
    @helpers.require_senior()
    async def blacklist_add(self, ctx: commands.Context, member: discord.Member, *, reason: Optional[str] = None):
        await self.bot.db.blacklist_add(ctx.guild.id, member.id, reason, ctx.author.id)
        await ctx.reply(view=ui.success(f"{member.mention} blacklisted from opening tickets." + (f" Reason: {reason}" if reason else "")))

    @blacklist.command(name="remove", description="Unblock a user.")
    @helpers.require_senior()
    async def blacklist_remove(self, ctx: commands.Context, member: discord.Member):
        if await self.bot.db.blacklist_remove(ctx.guild.id, member.id):
            await ctx.reply(view=ui.success(f"{member.mention} removed from the blacklist."))
        else:
            await ctx.reply(view=ui.error(f"{member.mention} isn't blacklisted."))

    @blacklist.command(name="list", description="Show the ticket blacklist.")
    @helpers.require_senior()
    async def blacklist_list(self, ctx: commands.Context):
        await self._blacklist_list(ctx)

    async def _blacklist_list(self, ctx: commands.Context):
        rows = await self.bot.db.list_blacklist(ctx.guild.id)
        if not rows:
            return await ctx.reply(view=ui.text_container(f"{Emojis.INFO} No one is blacklisted.", "blue"))
        lines = [f"__**Ticket Blacklist**__ ({len(rows)})"]
        for r in rows[:25]:
            lines.append(f"{Emojis.DOT} <@{r['user_id']}>" + (f" — _{r['reason']}_" if r["reason"] else ""))
        await ctx.reply(view=ui.text_container("\n".join(lines), "blue"))

    # stats

    @commands.hybrid_command(name="ticketstats", description="Show ticket stats for this server.")
    @helpers.require_staff()
    async def ticketstats(self, ctx: commands.Context):
        open_tickets = await self.bot.db.list_open_tickets(ctx.guild.id)
        all_recent = await self.bot.db.list_guild_tickets(ctx.guild.id, limit=500)
        closed_count = sum(1 for t in all_recent if t["status"] == "closed")
        claimed = sum(1 for t in open_tickets if t["claimed_by"])
        transferred = sum(t["transferred_count"] for t in all_recent)

        text = (
            f"__**Ticket Stats — {ctx.guild.name}**__\n"
            f"{Emojis.DOT} **Open:** `{len(open_tickets)}` (claimed: `{claimed}`, unclaimed: `{len(open_tickets) - claimed}`)\n"
            f"{Emojis.DOT} **Closed (recent {len(all_recent)}):** `{closed_count}`\n"
            f"{Emojis.DOT} **Total transfers/escalations:** `{transferred}`"
        )
        await ctx.reply(view=ui.text_container(text, "blue"))

    @commands.hybrid_command(name="activetickets", description="List currently open tickets.")
    @helpers.require_staff()
    async def activetickets(self, ctx: commands.Context):
        open_tickets = await self.bot.db.list_open_tickets(ctx.guild.id)
        if not open_tickets:
            return await ctx.reply(view=ui.text_container(f"{Emojis.INFO} No open tickets right now.", "blue"))
        lines = [f"## {Emojis.TICKET} Open Tickets ({len(open_tickets)})"]
        for t in open_tickets[:25]:
            ch = ctx.guild.get_channel(t["channel_id"])
            handler = f"<@{t['claimed_by']}>" if t["claimed_by"] else "*unclaimed*"
            lines.append(f"{Emojis.DOT} **#{t['number']:04d}** {ch.mention if ch else ''} — opener <@{t['opener_id']}>, handler {handler}")
        await ctx.reply(view=ui.text_container("\n".join(lines), "blue"))


async def setup(bot):
    await bot.add_cog(Tickets(bot))
