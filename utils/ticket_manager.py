import html
import os
import time

import discord

from emojis import Emojis
from utils import helpers

TRANSCRIPT_DIR = "data/transcripts"


def _base_overwrites(guild: discord.Guild, opener: discord.abc.User, cfg: dict) -> dict:
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True,
            manage_channels=True, manage_permissions=True, attach_files=True, embed_links=True,
        ),
    }
    opener_member = guild.get_member(opener.id)
    if opener_member:
        overwrites[opener_member] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True, attach_files=True,
        )
    for role_id in cfg.get("staff_role_ids", []):
        role = guild.get_role(role_id)
        if role:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, manage_messages=True,
            )
    return overwrites


async def open_ticket(bot, guild: discord.Guild, opener: discord.abc.User, panel: dict):
    import ui

    cfg = await bot.db.get_guild_config(guild.id)
    category = guild.get_channel(panel.get("category_id") or cfg.get("category_id"))
    if category and not isinstance(category, discord.CategoryChannel):
        category = None

    overwrites = _base_overwrites(guild, opener, cfg)
    number = await bot.db.next_ticket_number(guild.id)
    name = helpers.ticket_channel_name(number, opener.display_name)

    try:
        channel = await guild.create_text_channel(
            name=name, category=category, overwrites=overwrites,
            topic=f"Ticket opened by {opener} ({opener.id})",
            reason=f"Ticket opened by {opener} ({opener.id})",
        )
    except discord.HTTPException:
        return None, None

    cur = await bot.db._conn.execute(
        """INSERT INTO tickets (guild_id, channel_id, panel_id, number, opener_id, status, created_at)
           VALUES (?, ?, ?, ?, ?, 'open', ?)""",
        (guild.id, channel.id, panel.get("panel_id"), number, opener.id, int(time.time())),
    )
    await bot.db._conn.commit()
    ticket = await bot.db.get_ticket(cur.lastrowid)
    await bot.db.log_action(guild.id, "open", actor_id=opener.id, ticket_id=ticket["ticket_id"])

    welcome = cfg.get("welcome_message") or "Thanks for reaching out! Support will be with you shortly."
    mention_roles = " ".join(guild.get_role(r).mention for r in cfg.get("staff_role_ids", []) if guild.get_role(r))
    ping_text = f"{opener.mention} {mention_roles}".strip()

    try:
        await channel.send(ping_text, allowed_mentions=discord.AllowedMentions(users=True, roles=True))
    except discord.HTTPException as e:
        print(f"[ticket_manager] ping send failed: {e}")

    try:
        await channel.send(welcome)
    except discord.HTTPException as e:
        print(f"[ticket_manager] welcome send failed: {e}")

    try:
        view = ui.build_ticket_view(ticket, cfg)
        control_msg = await channel.send(view=view)
        await bot.db.set_control_message(ticket["ticket_id"], control_msg.id)
    except discord.HTTPException as e:
        print(f"[ticket_manager] control panel send failed: {e}")

    await _post_log(bot, guild, cfg, f"{Emojis.OPEN} {opener.mention} opened ticket **#{number:04d}** ({channel.mention}).")

    return await bot.db.get_ticket(ticket["ticket_id"]), channel


async def refresh_ticket_view(bot, ticket_id: int):
    import ui
    ticket = await bot.db.get_ticket(ticket_id)
    if not ticket:
        return None
    cfg = await bot.db.get_guild_config(ticket["guild_id"])
    return ui.build_ticket_view(ticket, cfg)


async def refresh_ticket_message(bot, ticket_id: int):
    ticket = await bot.db.get_ticket(ticket_id)
    if not ticket or not ticket.get("control_message_id"):
        return
    channel = bot.get_channel(ticket["channel_id"])
    if not channel:
        return
    view = await refresh_ticket_view(bot, ticket_id)
    try:
        await channel.get_partial_message(ticket["control_message_id"]).edit(view=view)
    except discord.HTTPException:
        pass


async def claim(bot, ticket: dict, staff: discord.Member):
    await bot.db.claim_ticket(ticket["ticket_id"], staff.id)
    await bot.db.log_action(ticket["guild_id"], "claim", actor_id=staff.id, ticket_id=ticket["ticket_id"])
    await _notify(bot, ticket, f"{Emojis.CLAIM} {staff.mention} claimed this ticket.")


async def unclaim(bot, ticket: dict, staff: discord.Member):
    await bot.db.unclaim_ticket(ticket["ticket_id"])
    await bot.db.log_action(ticket["guild_id"], "unclaim", actor_id=staff.id, ticket_id=ticket["ticket_id"])
    await _notify(bot, ticket, f"{Emojis.UNCLAIM} {staff.mention} unclaimed this ticket.")


async def lock(bot, ticket: dict):
    channel = bot.get_channel(ticket["channel_id"])
    if channel:
        locked_overwrite = discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True)
        opener = channel.guild.get_member(ticket["opener_id"])
        if opener:
            await channel.set_permissions(opener, overwrite=locked_overwrite)
        for uid in await bot.db.list_ticket_members(ticket["ticket_id"]):
            m = channel.guild.get_member(uid)
            if m:
                await channel.set_permissions(m, overwrite=locked_overwrite)
    await bot.db.lock_ticket(ticket["ticket_id"])
    await bot.db.log_action(ticket["guild_id"], "lock", ticket_id=ticket["ticket_id"])
    await _notify(bot, ticket, f"{Emojis.LOCK} Ticket locked. Only staff can send messages.")


async def unlock(bot, ticket: dict):
    channel = bot.get_channel(ticket["channel_id"])
    if channel:
        open_overwrite = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True)
        opener = channel.guild.get_member(ticket["opener_id"])
        if opener:
            await channel.set_permissions(opener, overwrite=open_overwrite)
        for uid in await bot.db.list_ticket_members(ticket["ticket_id"]):
            m = channel.guild.get_member(uid)
            if m:
                await channel.set_permissions(m, overwrite=open_overwrite)
    await bot.db.unlock_ticket(ticket["ticket_id"])
    await bot.db.log_action(ticket["guild_id"], "unlock", ticket_id=ticket["ticket_id"])
    await _notify(bot, ticket, f"{Emojis.UNLOCK} Ticket unlocked.")


async def rename(bot, ticket: dict, new_name: str):
    channel = bot.get_channel(ticket["channel_id"])
    if channel:
        safe = helpers.safe_channel_name(new_name)
        try:
            await channel.edit(name=f"{safe}-{ticket['number']:04d}"[:90])
        except discord.HTTPException:
            pass
    await bot.db.update_ticket(ticket["ticket_id"], subject=new_name)
    await bot.db.log_action(ticket["guild_id"], "rename", ticket_id=ticket["ticket_id"], detail=new_name)


async def add_member(bot, ticket: dict, member: discord.Member, added_by: discord.abc.User):
    channel = bot.get_channel(ticket["channel_id"])
    if channel:
        await channel.set_permissions(member, overwrite=discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True, attach_files=True,
        ))
    await bot.db.add_ticket_member(ticket["ticket_id"], member.id, added_by.id)
    await bot.db.log_action(ticket["guild_id"], "add_user", actor_id=added_by.id, ticket_id=ticket["ticket_id"], detail=str(member.id))
    await _notify(bot, ticket, f"{Emojis.ADD_USER} {member.mention} was added to the ticket by {added_by.mention}.")


async def remove_member(bot, ticket: dict, member: discord.Member) -> bool:
    removed = await bot.db.remove_ticket_member(ticket["ticket_id"], member.id)
    channel = bot.get_channel(ticket["channel_id"])
    if channel and removed:
        await channel.set_permissions(member, overwrite=None)
        await _notify(bot, ticket, f"{Emojis.REMOVE_USER} {member.mention} was removed from the ticket.")
    if removed:
        await bot.db.log_action(ticket["guild_id"], "remove_user", ticket_id=ticket["ticket_id"], detail=str(member.id))
    return removed


async def close(bot, ticket: dict, closed_by: discord.abc.User, reason: str | None):
    channel = bot.get_channel(ticket["channel_id"])
    cfg = await bot.db.get_guild_config(ticket["guild_id"])
    path = ""
    if channel:
        opener = channel.guild.get_member(ticket["opener_id"])
        if opener:
            await channel.set_permissions(opener, overwrite=discord.PermissionOverwrite(
                view_channel=True, send_messages=False, read_message_history=True,
            ))
        if cfg.get("transcripts_enabled", True):
            path = await generate_html_transcript(channel, ticket, closed_by=str(closed_by))
            await bot.db.set_transcript_path(ticket["ticket_id"], path)
        try:
            await channel.send(view=(_notice_view(f"{Emojis.CLOSE} Ticket closed by {closed_by.mention}." + (f"\n**Reason:** {reason}" if reason else ""), "red")))
        except discord.HTTPException:
            pass
    await bot.db.close_ticket(ticket["ticket_id"], closed_by.id, reason)
    await bot.db.log_action(ticket["guild_id"], "close", actor_id=closed_by.id, ticket_id=ticket["ticket_id"], detail=reason)
    await _post_log(bot, channel.guild if channel else None, cfg,
                     f"{Emojis.CLOSE} {closed_by.mention} closed ticket **#{ticket['number']:04d}**." + (f" Reason: {reason}" if reason else ""),
                     transcript_path=path)


async def reopen(bot, ticket: dict, reopened_by: discord.abc.User):
    channel = bot.get_channel(ticket["channel_id"])
    if channel:
        opener = channel.guild.get_member(ticket["opener_id"])
        if opener:
            await channel.set_permissions(opener, overwrite=discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, attach_files=True,
            ))
    await bot.db.reopen_ticket(ticket["ticket_id"])
    await bot.db.log_action(ticket["guild_id"], "reopen", actor_id=reopened_by.id, ticket_id=ticket["ticket_id"])
    await _notify(bot, ticket, f"{Emojis.REOPEN} Ticket reopened by {reopened_by.mention}.")


async def delete(bot, ticket: dict, deleted_by: discord.abc.User):
    channel = bot.get_channel(ticket["channel_id"])
    cfg = await bot.db.get_guild_config(ticket["guild_id"])
    path = ticket.get("transcript_path") or ""
    if channel:
        if not path and cfg.get("transcripts_enabled", True):
            path = await generate_html_transcript(channel, ticket, closed_by=str(deleted_by))
        try:
            await channel.delete(reason=f"Ticket deleted by {deleted_by}")
        except discord.HTTPException:
            pass
    await bot.db.log_action(ticket["guild_id"], "delete", actor_id=deleted_by.id, ticket_id=ticket["ticket_id"], detail=path)
    await _post_log(bot, channel.guild if channel else bot.get_guild(ticket["guild_id"]), cfg,
                     f"{Emojis.DELETE} {deleted_by.mention} deleted ticket **#{ticket['number']:04d}**.", transcript_path=path)
    await bot.db.delete_ticket_record(ticket["ticket_id"])
    return path


async def transfer(bot, ticket: dict, to_role: discord.Role, reason: str | None, transferred_by: discord.abc.User):
    channel = bot.get_channel(ticket["channel_id"])
    from_user_id = ticket.get("claimed_by")

    if channel:
        if from_user_id:
            from_member = channel.guild.get_member(from_user_id)
            if from_member:
                await channel.set_permissions(from_member, overwrite=discord.PermissionOverwrite(
                    view_channel=False, send_messages=False,
                ))
        await channel.set_permissions(to_role, overwrite=discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True,
            attach_files=True, manage_messages=True,
        ))
        note = f"{Emojis.ESCALATE} This ticket was escalated to {to_role.mention}."
        if reason:
            note += f"\n**Reason:** {reason}"
        try:
            await channel.send(content=to_role.mention, view=(_notice_view(note, "purple")),
                                allowed_mentions=discord.AllowedMentions(roles=True))
        except discord.HTTPException:
            pass

    await bot.db.log_transfer(ticket["ticket_id"], from_user_id, to_role.id, reason, transferred_by.id)
    await bot.db.log_action(ticket["guild_id"], "transfer", actor_id=transferred_by.id,
                             ticket_id=ticket["ticket_id"], detail=f"role:{to_role.id} reason:{reason or ''}")

    cfg = await bot.db.get_guild_config(ticket["guild_id"])
    await _post_log(bot, channel.guild if channel else None, cfg,
                     f"{Emojis.TRANSFER} {transferred_by.mention} transferred ticket **#{ticket['number']:04d}** "
                     f"to {to_role.mention}." + (f" Reason: {reason}" if reason else ""))


async def generate_transcript(bot, ticket: dict) -> str:
    channel = bot.get_channel(ticket["channel_id"])
    if not channel:
        return ticket.get("transcript_path") or ""
    path = await generate_html_transcript(channel, ticket)
    await bot.db.set_transcript_path(ticket["ticket_id"], path)
    return path


async def _notify(bot, ticket: dict, text: str):
    channel = bot.get_channel(ticket["channel_id"])
    if not channel:
        return
    try:
        await channel.send(view=_notice_view(text, "blue"))
    except discord.HTTPException:
        pass


def _notice_view(text: str, theme: str):
    import ui
    return ui.text_container(text, theme)


async def _post_log(bot, guild, cfg: dict, text: str, transcript_path: str | None = None):
    if not guild or not cfg.get("log_channel_id"):
        return
    channel = guild.get_channel(cfg["log_channel_id"])
    if not channel:
        return
    kwargs = {}
    if transcript_path:
        try:
            kwargs["file"] = discord.File(transcript_path)
        except OSError:
            pass
    try:
        await channel.send(view=(_notice_view(text, cfg.get("theme"))), **kwargs)
    except discord.HTTPException:
        pass


_STYLE = """
body{background:#313338;color:#dbdee1;font-family:'gg sans',Whitney,Helvetica,Arial,sans-serif;margin:0;padding:0}
.header{background:#1e1f22;padding:16px 24px;border-bottom:1px solid #26272b}
.header h1{margin:0;font-size:18px;color:#f2f3f5}
.header p{margin:4px 0 0;font-size:13px;color:#949ba4}
.messages{padding:16px 24px;max-width:900px}
.msg{display:flex;gap:16px;padding:8px 0}
.avatar{width:40px;height:40px;border-radius:50%;flex-shrink:0;background:#5865f2}
.body{flex:1;min-width:0}
.meta{font-size:14px}
.author{font-weight:600;color:#f2f3f5}
.tag-bot{background:#5865f2;color:#fff;font-size:10px;border-radius:3px;padding:1px 4px;margin-left:4px;vertical-align:middle}
.time{color:#949ba4;font-size:12px;margin-left:6px}
.content{white-space:pre-wrap;word-wrap:break-word;font-size:15px;line-height:1.4;margin-top:2px}
.attachment{margin-top:4px}
.attachment img{max-width:400px;max-height:300px;border-radius:8px;display:block}
.attachment a{color:#00a8fc;text-decoration:none;font-size:13px}
.embed{border-left:4px solid #5865f2;background:#2b2d31;border-radius:4px;padding:10px 12px;margin-top:6px;max-width:520px}
.embed .title{color:#f2f3f5;font-weight:600;margin-bottom:4px}
.embed .desc{color:#dbdee1;font-size:14px;white-space:pre-wrap}
.system{color:#949ba4;font-style:italic;font-size:13px}
footer{padding:16px 24px;color:#5c5e66;font-size:12px;border-top:1px solid #26272b}
"""


async def generate_html_transcript(channel: discord.TextChannel, ticket: dict, closed_by: str | None = None) -> str:
    out_dir = os.path.join(TRANSCRIPT_DIR, str(channel.guild.id))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"ticket-{ticket['number']:04d}-{ticket['ticket_id']}.html")

    rows = []
    try:
        async for msg in channel.history(limit=None, oldest_first=True):
            rows.append(_render_message(msg))
    except discord.Forbidden:
        pass
    except discord.HTTPException as e:
        rows.append(f'<div class="system">Transcript capture stopped early: {html.escape(str(e))}</div>')

    generated_at = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    doc = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Transcript — {html.escape(channel.name)}</title>
<style>{_STYLE}</style></head>
<body>
<div class="header">
  <h1>#{html.escape(channel.name)}</h1>
  <p>Ticket #{ticket['number']:04d} &middot; Opened by user ID {ticket['opener_id']} &middot;
     Generated {generated_at}{f' &middot; Closed by {html.escape(closed_by)}' if closed_by else ''}</p>
</div>
<div class="messages">
{''.join(rows) if rows else '<div class="system">No messages captured.</div>'}
</div>
<footer>{len(rows)} message(s) captured.</footer>
</body></html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return path


def _render_message(msg: discord.Message) -> str:
    author = msg.author
    bot_tag = '<span class="tag-bot">BOT</span>' if author.bot else ""
    ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
    content = html.escape(msg.content or "").replace("\n", "<br>")

    attachments = ""
    for att in msg.attachments:
        if att.content_type and att.content_type.startswith("image/"):
            attachments += f'<div class="attachment"><img src="{html.escape(att.url)}" loading="lazy"></div>'
        else:
            attachments += f'<div class="attachment">📎 <a href="{html.escape(att.url)}">{html.escape(att.filename)}</a></div>'

    embeds = ""
    for e in msg.embeds:
        title = html.escape(e.title) if e.title else ""
        desc = html.escape(e.description) if e.description else ""
        embeds += f'<div class="embed">{f"<div class=\"title\">{title}</div>" if title else ""}<div class="desc">{desc}</div></div>'

    return (
        f'<div class="msg"><img class="avatar" src="{html.escape(str(author.display_avatar.url))}">'
        f'<div class="body"><span class="meta"><span class="author">{html.escape(str(author))}</span>{bot_tag}'
        f'<span class="time">{ts}</span></span>'
        f'<div class="content">{content}</div>{attachments}{embeds}</div></div>'
    )
