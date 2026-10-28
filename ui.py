import discord
from discord import ui

from emojis import Emojis
from utils import helpers


def container_view(*children, theme=None) -> ui.LayoutView:
    view = ui.LayoutView()
    view.add_item(ui.Container(*children, accent_color=helpers.theme_color(theme)))
    return view


def text_container(body: str, theme: str | None = None) -> ui.LayoutView:
    return container_view(ui.TextDisplay(body), theme=theme)


def success(body: str, theme: str | None = "blue") -> ui.LayoutView:
    return text_container(f"{Emojis.SUCCESS} {body}", theme)


def error(body: str, theme: str | None = "red") -> ui.LayoutView:
    return text_container(f"{Emojis.ERROR} {body}", theme)


def info(body: str, theme: str | None = None) -> ui.LayoutView:
    return text_container(f"{Emojis.INFO} {body}", theme)


class ConfirmView(ui.LayoutView):
    def __init__(self, *, body: str, theme: str | None, confirm_label: str = "Confirm",
                 cancel_label: str = "Cancel", danger: bool = True, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.value: bool | None = None

        confirm_btn = ui.Button(
            label=confirm_label,
            style=discord.ButtonStyle.danger if danger else discord.ButtonStyle.success,
        )
        cancel_btn = ui.Button(label=cancel_label, style=discord.ButtonStyle.secondary)

        async def _confirm(interaction: discord.Interaction):
            self.value = True
            confirm_btn.disabled = True
            cancel_btn.disabled = True
            await interaction.response.edit_message(view=self)
            self.stop()

        async def _cancel(interaction: discord.Interaction):
            self.value = False
            confirm_btn.disabled = True
            cancel_btn.disabled = True
            await interaction.response.edit_message(view=self)
            self.stop()

        confirm_btn.callback = _confirm
        cancel_btn.callback = _cancel

        row = ui.ActionRow(confirm_btn, cancel_btn)
        container = ui.Container(ui.TextDisplay(body), row, accent_color=helpers.theme_color(theme))
        self.add_item(container)


class RenameModal(ui.Modal, title="Rename Ticket"):
    new_name = ui.TextInput(label="New channel name", placeholder="billing-question", max_length=90)

    def __init__(self, on_submit_cb):
        super().__init__()
        self._cb = on_submit_cb

    async def on_submit(self, interaction: discord.Interaction):
        await self._cb(interaction, str(self.new_name.value))


class CloseReasonModal(ui.Modal, title="Close Ticket"):
    reason = ui.TextInput(
        label="Reason (optional)", style=discord.TextStyle.paragraph,
        placeholder="Issue resolved, user inactive, etc.", max_length=500, required=False,
    )

    def __init__(self, on_submit_cb):
        super().__init__()
        self._cb = on_submit_cb

    async def on_submit(self, interaction: discord.Interaction):
        await self._cb(interaction, str(self.reason.value) or None)


class TransferReasonModal(ui.Modal, title="Transfer / Escalate Ticket"):
    reason = ui.TextInput(
        label="Reason (optional)", style=discord.TextStyle.paragraph,
        placeholder="Why is this being escalated?", max_length=500, required=False,
    )

    def __init__(self, on_submit_cb):
        super().__init__()
        self._cb = on_submit_cb

    async def on_submit(self, interaction: discord.Interaction):
        await self._cb(interaction, str(self.reason.value) or None)


class PanelOpenButton(ui.Button):
    def __init__(self, label: str = "Open Ticket", emoji: str | None = None):
        super().__init__(
            label=label or "Open Ticket", emoji=emoji or Emojis.TICKET,
            style=discord.ButtonStyle.primary, custom_id="panel_open",
        )

    async def callback(self, interaction: discord.Interaction):
        await handle_panel_open(interaction)


def build_panel_view(title: str, description: str, theme: str | None,
                      button_label: str, button_emoji: str | None) -> ui.LayoutView:
    view = ui.LayoutView()
    children = [
        ui.TextDisplay(f"__**{title}**__"),
        ui.Separator(),
        ui.TextDisplay(description),
        ui.Separator(),
        ui.ActionRow(PanelOpenButton(button_label, button_emoji)),
    ]
    view.add_item(ui.Container(*children, accent_color=helpers.theme_color(theme)))
    return view


class TicketActionButton(ui.Button):
    def __init__(self, action: str, label: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style, custom_id=f"ticket_{action}")
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        await handle_ticket_action(interaction, self.action)


def build_ticket_view(ticket: dict, cfg: dict) -> ui.LayoutView:
    handler = f"<@{ticket['claimed_by']}>" if ticket["claimed_by"] else "*Unclaimed*"
    status = (
        f"__**Ticket**__ **{ticket['number']:04d}**\n"
        f"{Emojis.DOT} **Opened by:** <@{ticket['opener_id']}>\n"
        f"{Emojis.DOT} **Handler:** {handler}\n"
        f"{Emojis.DOT} **Status:** `{ticket['status'].upper()}`{' 🔐' if ticket['locked'] else ''}\n"
        f"{Emojis.DOT} **Opened:** <t:{ticket['created_at']}:R>"
    )
    if ticket["transferred_count"]:
        status += f"\n{Emojis.TRANSFER} **Transferred:** `{ticket['transferred_count']}` time(s)"
    if ticket["status"] == "closed" and ticket["close_reason"]:
        status += f"\n{Emojis.CLOSE} **Close reason:** {ticket['close_reason']}"

    children = [ui.TextDisplay(status), ui.Separator()]

    if ticket["status"] == "open":
        claim_btn = (
            TicketActionButton("unclaim", "Unclaim", discord.ButtonStyle.secondary)
            if ticket["claimed_by"] else
            TicketActionButton("claim", "Claim", discord.ButtonStyle.success)
        )
        children.append(ui.ActionRow(
            claim_btn,
            TicketActionButton("transfer", "Transfer", discord.ButtonStyle.primary),
            TicketActionButton("close", "Close", discord.ButtonStyle.danger),
        ))
        lock_btn = (
            TicketActionButton("unlock", "Unlock", discord.ButtonStyle.secondary)
            if ticket["locked"] else
            TicketActionButton("lock", "Lock", discord.ButtonStyle.secondary)
        )
        children.append(ui.ActionRow(
            lock_btn,
            TicketActionButton("rename", "Rename", discord.ButtonStyle.secondary),
            TicketActionButton("adduser", "Add User", discord.ButtonStyle.secondary),
            TicketActionButton("removeuser", "Remove User", discord.ButtonStyle.secondary),
        ))
    else:
        children.append(ui.ActionRow(
            TicketActionButton("reopen", "Reopen", discord.ButtonStyle.success),
            TicketActionButton("transcript", "Transcript", discord.ButtonStyle.secondary),
            TicketActionButton("delete", "Delete", discord.ButtonStyle.danger),
        ))

    view = ui.LayoutView()
    view.add_item(ui.Container(*children, accent_color=helpers.theme_color(cfg["theme"])))
    return view


def persistent_templates() -> list[discord.ui.View]:
    panel_view = discord.ui.View(timeout=None)
    panel_view.add_item(PanelOpenButton())

    ticket_view = discord.ui.View(timeout=None)
    actions = [
        ("claim", "Claim", discord.ButtonStyle.success),
        ("unclaim", "Unclaim", discord.ButtonStyle.secondary),
        ("transfer", "Transfer", discord.ButtonStyle.primary),
        ("close", "Close", discord.ButtonStyle.danger),
        ("lock", "Lock", discord.ButtonStyle.secondary),
        ("unlock", "Unlock", discord.ButtonStyle.secondary),
        ("rename", "Rename", discord.ButtonStyle.secondary),
        ("adduser", "Add User", discord.ButtonStyle.secondary),
        ("removeuser", "Remove User", discord.ButtonStyle.secondary),
        ("reopen", "Reopen", discord.ButtonStyle.success),
        ("transcript", "Transcript", discord.ButtonStyle.secondary),
        ("delete", "Delete", discord.ButtonStyle.danger),
    ]
    for action, label, style in actions:
        ticket_view.add_item(TicketActionButton(action, label, style))

    return [panel_view, ticket_view]


async def handle_panel_open(interaction: discord.Interaction):
    from utils import ticket_manager

    bot = interaction.client
    await interaction.response.defer(ephemeral=True, thinking=True)

    panel = await bot.db.get_panel_by_message(interaction.message.id)
    if not panel:
        return await interaction.followup.send(view=error("This panel is no longer configured."), ephemeral=True)

    cfg = await bot.db.get_guild_config(interaction.guild.id)

    if await bot.db.is_blacklisted(interaction.guild.id, interaction.user.id):
        return await interaction.followup.send(
            view=error("You're blacklisted from opening tickets here."), ephemeral=True,
        )

    open_count = await bot.db.count_open_tickets_for_user(interaction.guild.id, interaction.user.id)
    limit = cfg["max_tickets_per_user"] or 1
    if open_count >= limit:
        return await interaction.followup.send(
            view=error(f"You already have `{open_count}` open ticket(s) (limit `{limit}`)."), ephemeral=True,
        )

    ticket, channel = await ticket_manager.open_ticket(bot, interaction.guild, interaction.user, panel)
    if not channel:
        return await interaction.followup.send(
            view=error("Couldn't create your ticket channel — ask staff to check permissions and category."),
            ephemeral=True,
        )

    await interaction.followup.send(view=success(f"Your ticket is ready: {channel.mention}", panel["theme"]), ephemeral=True)


async def handle_ticket_action(interaction: discord.Interaction, action: str):
    from utils import ticket_manager

    bot = interaction.client
    ticket = await bot.db.get_ticket_by_channel(interaction.channel.id)
    if not ticket:
        return await interaction.response.send_message(view=error("This isn't a ticket channel."), ephemeral=True)
    cfg = await bot.db.get_guild_config(ticket["guild_id"])
    member = interaction.user

    if action in ("rename", "close", "transfer"):
        if not helpers.can_manage_ticket(bot, member, ticket, cfg):
            return await interaction.response.send_message(view=error("You don't have permission to do that."), ephemeral=True)
        if action == "rename":
            return await interaction.response.send_modal(RenameModal(_make_rename_cb(ticket["ticket_id"])))
        if action == "close":
            return await interaction.response.send_modal(CloseReasonModal(_make_close_cb(ticket["ticket_id"])))
        if action == "transfer":
            return await _start_transfer(interaction, ticket, cfg)

    if not helpers.can_manage_ticket(bot, member, ticket, cfg):
        return await interaction.response.send_message(view=error("You don't have permission to do that."), ephemeral=True)

    if action == "claim":
        if ticket["claimed_by"]:
            return await interaction.response.send_message(view=error("This ticket is already claimed."), ephemeral=True)
        await ticket_manager.claim(bot, ticket, member)
        return await _refresh_and_ack(interaction, ticket["ticket_id"])

    if action == "unclaim":
        await ticket_manager.unclaim(bot, ticket, member)
        return await _refresh_and_ack(interaction, ticket["ticket_id"])

    if action == "lock":
        await ticket_manager.lock(bot, ticket)
        return await _refresh_and_ack(interaction, ticket["ticket_id"])

    if action == "unlock":
        await ticket_manager.unlock(bot, ticket)
        return await _refresh_and_ack(interaction, ticket["ticket_id"])

    if action == "adduser":
        return await interaction.response.send_message(view=_UserPickView(ticket["ticket_id"], "add"), ephemeral=True)

    if action == "removeuser":
        return await interaction.response.send_message(view=_UserPickView(ticket["ticket_id"], "remove"), ephemeral=True)

    if action == "reopen":
        await ticket_manager.reopen(bot, ticket, member)
        return await _refresh_and_ack(interaction, ticket["ticket_id"])

    if action == "transcript":
        await interaction.response.defer(ephemeral=True, thinking=True)
        path = await ticket_manager.generate_transcript(bot, ticket)
        if not path:
            return await interaction.followup.send(view=error("Couldn't generate a transcript."), ephemeral=True)
        return await interaction.followup.send(
            view=text_container(f"{Emojis.TRANSCRIPT} Transcript ready.", cfg["theme"]),
            ephemeral=True, file=discord.File(path),
        )

    if action == "delete":
        confirm = ConfirmView(
            body=f"{Emojis.WARNING} Delete this ticket channel? A transcript is saved first. This can't be undone.",
            theme="red", confirm_label="Delete",
        )
        await interaction.response.send_message(view=confirm, ephemeral=True)
        await confirm.wait()
        if confirm.value:
            await ticket_manager.delete(bot, ticket, member)


async def _refresh_and_ack(interaction: discord.Interaction, ticket_id: int):
    from utils import ticket_manager
    view = await ticket_manager.refresh_ticket_view(interaction.client, ticket_id)
    if view is not None:
        await interaction.response.edit_message(view=view)
    else:
        await interaction.response.defer()


def _make_rename_cb(ticket_id: int):
    async def cb(interaction: discord.Interaction, new_name: str):
        from utils import ticket_manager
        bot = interaction.client
        ticket = await bot.db.get_ticket(ticket_id)
        if not ticket:
            return await interaction.response.send_message(view=error("This ticket no longer exists."), ephemeral=True)
        await ticket_manager.rename(bot, ticket, new_name)
        await interaction.response.send_message(view=success("Ticket renamed."), ephemeral=True)
        await ticket_manager.refresh_ticket_message(bot, ticket_id)
    return cb


def _make_close_cb(ticket_id: int):
    async def cb(interaction: discord.Interaction, reason: str | None):
        from utils import ticket_manager
        bot = interaction.client
        ticket = await bot.db.get_ticket(ticket_id)
        if not ticket:
            return await interaction.response.send_message(view=error("This ticket no longer exists."), ephemeral=True)
        await interaction.response.send_message(view=text_container(f"{Emojis.LOADING} Closing & saving transcript..."), ephemeral=True)
        await ticket_manager.close(bot, ticket, interaction.user, reason)
        await ticket_manager.refresh_ticket_message(bot, ticket_id)
    return cb


async def _start_transfer(interaction: discord.Interaction, ticket: dict, cfg: dict):
    senior_roles = helpers.eligible_senior_roles(interaction.guild, cfg)
    if not senior_roles:
        return await interaction.response.send_message(
            view=error("No senior/escalation roles configured yet. An admin can add one with `/ticketconfig seniorrole add`."),
            ephemeral=True,
        )
    view = _TransferRolePickView(ticket["ticket_id"], senior_roles)
    await interaction.response.send_message(view=view, ephemeral=True)


class _UserPickView(ui.LayoutView):
    def __init__(self, ticket_id: int, mode: str):
        super().__init__(timeout=120)
        self.ticket_id = ticket_id
        self.mode = mode

        prompt = "Select a user to add:" if mode == "add" else "Select a user to remove:"
        select = ui.UserSelect(placeholder="Choose a member...", min_values=1, max_values=1)
        select.callback = self._on_select
        container = ui.Container(
            ui.TextDisplay(f"{Emojis.USER} {prompt}"),
            ui.ActionRow(select),
            accent_color=helpers.theme_color(None),
        )
        self.add_item(container)

    async def _on_select(self, interaction: discord.Interaction):
        from utils import ticket_manager
        bot = interaction.client
        target_id = int(interaction.data["values"][0])
        member = interaction.guild.get_member(target_id) or await interaction.guild.fetch_member(target_id)
        ticket = await bot.db.get_ticket(self.ticket_id)
        if not ticket:
            return await interaction.response.edit_message(view=error("This ticket no longer exists."))

        if self.mode == "add":
            await ticket_manager.add_member(bot, ticket, member, interaction.user)
            text = f"{Emojis.SUCCESS} Added {member.mention} to the ticket."
        else:
            removed = await ticket_manager.remove_member(bot, ticket, member)
            text = (f"{Emojis.SUCCESS} Removed {member.mention} from the ticket." if removed
                    else f"{Emojis.ERROR} {member.mention} wasn't added to this ticket.")
        await interaction.response.edit_message(view=text_container(text, "blue"))


class _TransferRolePickView(ui.LayoutView):
    def __init__(self, ticket_id: int, senior_roles: list[discord.Role]):
        super().__init__(timeout=120)
        self.ticket_id = ticket_id

        select = ui.Select(
            placeholder="Choose a role...",
            options=[discord.SelectOption(label=r.name, value=str(r.id)) for r in senior_roles[:25]],
        )
        select.callback = self._on_select
        container = ui.Container(
            ui.TextDisplay(f"{Emojis.SENIOR} Escalate to which role?"),
            ui.ActionRow(select),
            accent_color=helpers.theme_color(None),
        )
        self.add_item(container)

    async def _on_select(self, interaction: discord.Interaction):
        role_id = int(interaction.data["values"][0])
        role = interaction.guild.get_role(role_id)
        if not role:
            return await interaction.response.edit_message(view=error("That role no longer exists."))
        await interaction.response.send_modal(TransferReasonModal(self._make_finish(role)))

    def _make_finish(self, role: discord.Role):
        async def finish(interaction: discord.Interaction, reason: str | None):
            from utils import ticket_manager
            bot = interaction.client
            ticket = await bot.db.get_ticket(self.ticket_id)
            if not ticket:
                return await interaction.response.send_message(view=error("This ticket no longer exists."), ephemeral=True)
            await ticket_manager.transfer(bot, ticket, role, reason, interaction.user)
            await interaction.response.send_message(view=success(f"Ticket transferred/escalated to {role.mention}."), ephemeral=True)
            await ticket_manager.refresh_ticket_message(bot, self.ticket_id)
        return finish
