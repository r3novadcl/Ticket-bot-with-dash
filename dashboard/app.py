import os
import time
import secrets
from pathlib import Path

import discord
from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from dashboard import oauth
from utils import helpers

BASE_DIR = Path(__file__).parent
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
SESSION_COOKIE = "ticket_session"

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["theme_choices"] = helpers.theme_choices
templates.env.globals["theme_label"] = helpers.theme_label
templates.env.filters["timestamp"] = lambda ts: (
    time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts)) if ts else "—"
)


def create_dashboard(bot) -> FastAPI:
    app = FastAPI(title="Ticket Bot Dashboard", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
    app.state.oauth_states: set[str] = set()

    def get_session(request: Request) -> dict | None:
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            return None
        return oauth.read_session_token(token)

    def require_session(request: Request) -> dict:
        session = get_session(request)
        if not session:
            raise HTTPException(status_code=401, detail="Not logged in")
        return session

    async def member_permission_level(guild: discord.Guild, user_id: int) -> str | None:
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except discord.HTTPException:
                return None
        if guild.owner_id == user_id or user_id in bot.owner_ids:
            return "owner"
        if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
            return "manager"
        return "member"

    async def require_manager(request: Request, guild_id: int):
        session = require_session(request)
        guild = bot.get_guild(guild_id)
        if not guild:
            raise HTTPException(status_code=404, detail="The bot isn't in that server.")
        level = await member_permission_level(guild, int(session["id"]))
        if level not in ("owner", "manager"):
            raise HTTPException(status_code=403, detail="You need Manage Server permission in that server.")
        return session, guild

    def ctx(request: Request, session: dict | None = None, **extra) -> dict:
        base = {"request": request}
        if session:
            base["session"] = session
            base["avatar"] = oauth.avatar_url(session["id"], session.get("avatar"))
        base.update(extra)
        return base

    # auth

    @app.get("/auth/login")
    async def auth_login():
        state = secrets.token_urlsafe(24)
        app.state.oauth_states.add(state)
        return RedirectResponse(oauth.build_authorize_url(state))

    @app.get("/auth/callback")
    async def auth_callback(request: Request, code: str = None, state: str = None, error: str = None):
        if error or not code:
            return RedirectResponse("/?error=login_failed")
        if state not in app.state.oauth_states:
            return RedirectResponse("/?error=invalid_state")
        app.state.oauth_states.discard(state)

        token_data = await oauth.exchange_code(code)
        if not token_data:
            return RedirectResponse("/?error=token_exchange_failed")
        user = await oauth.fetch_user(token_data["access_token"])
        if not user:
            return RedirectResponse("/?error=user_fetch_failed")

        session_token = oauth.create_session_token(user)
        resp = RedirectResponse("/dashboard")
        resp.set_cookie(SESSION_COOKIE, session_token, max_age=oauth.SESSION_MAX_AGE, httponly=True, samesite="lax")
        return resp

    @app.get("/auth/logout")
    async def auth_logout():
        resp = RedirectResponse("/")
        resp.delete_cookie(SESSION_COOKIE)
        return resp

    # home / guild picker

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        session = get_session(request)
        return templates.TemplateResponse("index.html", ctx(
            request, session, guild_count=len(bot.guilds),
            bot_name=(bot.user.name if bot.user else "Ticket Bot"),
        ))

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard_home(request: Request):
        session = require_session(request)
        user_id = int(session["id"])

        # Checked live against the bot's own guild/member cache every time,
        # so a new server or role change shows up immediately - no stale
        # cached permission list to fall out of sync with Discord.
        guilds = []
        for g in bot.guilds:
            level = await member_permission_level(g, user_id)
            if level in ("owner", "manager"):
                guilds.append({"id": g.id, "name": g.name, "icon": g.icon.url if g.icon else None})

        return templates.TemplateResponse("guilds.html", ctx(request, session, guilds=guilds))

    # guild home

    @app.get("/dashboard/{guild_id}", response_class=HTMLResponse)
    async def guild_home(request: Request, guild_id: int):
        session, guild = await require_manager(request, guild_id)
        cfg = await bot.db.get_guild_config(guild_id)
        panels = await bot.db.list_panels(guild_id)
        open_tickets = await bot.db.list_open_tickets(guild_id)

        return templates.TemplateResponse("guild_home.html", ctx(
            request, session, active="home",
            guild={"id": guild.id, "name": guild.name, "icon": guild.icon.url if guild.icon else None},
            cfg=cfg, panel_count=len(panels), open_count=len(open_tickets),
            categories=guild.categories, text_channels=guild.text_channels,
        ))

    @app.post("/dashboard/{guild_id}/config")
    async def guild_config_update(
        request: Request, guild_id: int,
        prefix: str = Form("!"), theme: str = Form("blue"),
        category_id: str = Form(""), log_channel_id: str = Form(""),
        transcript_channel_id: str = Form(""), max_tickets_per_user: int = Form(1),
        auto_close_hours: int = Form(0), welcome_message: str = Form(""),
        transcripts_enabled: str = Form("on"),
    ):
        await require_manager(request, guild_id)
        fields = {
            "prefix": prefix[:5] or "!",
            "theme": theme if helpers.theme_is_valid(theme) else "blue",
            "category_id": int(category_id) if category_id else None,
            "log_channel_id": int(log_channel_id) if log_channel_id else None,
            "transcript_channel_id": int(transcript_channel_id) if transcript_channel_id else None,
            "max_tickets_per_user": max(1, min(max_tickets_per_user, 25)),
            "auto_close_hours": max(0, min(auto_close_hours, 720)),
            "welcome_message": welcome_message[:500] or "Thanks for reaching out! Support will be with you shortly.",
            "transcripts_enabled": 1 if transcripts_enabled == "on" else 0,
        }
        await bot.db.update_guild_config(guild_id, **fields)
        return RedirectResponse(f"/dashboard/{guild_id}?saved=1", status_code=303)

    # roles

    @app.get("/dashboard/{guild_id}/roles", response_class=HTMLResponse)
    async def roles_page(request: Request, guild_id: int):
        session, guild = await require_manager(request, guild_id)
        cfg = await bot.db.get_guild_config(guild_id)
        roles = [r for r in sorted(guild.roles, reverse=True) if not r.is_default() and not r.managed]
        return templates.TemplateResponse("roles.html", ctx(
            request, session, active="roles", guild={"id": guild.id, "name": guild.name},
            roles=roles, staff_ids=set(cfg["staff_role_ids"]), senior_ids=set(cfg["senior_role_ids"]),
        ))

    @app.post("/dashboard/{guild_id}/roles")
    async def roles_update(request: Request, guild_id: int):
        await require_manager(request, guild_id)
        form = await request.form()
        staff_ids = [int(v) for v in form.getlist("staff_roles")]
        senior_ids = [int(v) for v in form.getlist("senior_roles")]
        await bot.db.update_guild_config(guild_id, staff_role_ids=staff_ids, senior_role_ids=senior_ids)
        return RedirectResponse(f"/dashboard/{guild_id}/roles?saved=1", status_code=303)

    # panels

    @app.get("/dashboard/{guild_id}/panels", response_class=HTMLResponse)
    async def panels_page(request: Request, guild_id: int):
        session, guild = await require_manager(request, guild_id)
        panels = await bot.db.list_panels(guild_id)
        for p in panels:
            ch = guild.get_channel(p["channel_id"])
            p["channel_name"] = ch.name if ch else "deleted-channel"
        return templates.TemplateResponse("panels.html", ctx(
            request, session, active="panels", guild={"id": guild.id, "name": guild.name},
            panels=panels, text_channels=guild.text_channels, categories=guild.categories,
            roles=[r for r in sorted(guild.roles, reverse=True) if not r.is_default() and not r.managed],
        ))

    @app.post("/dashboard/{guild_id}/panels/create")
    async def panel_create(
        request: Request, guild_id: int,
        channel_id: int = Form(...), title: str = Form("Support Tickets"),
        description: str = Form("Click the button below to open a ticket."),
        theme: str = Form("blue"), category_id: str = Form(""),
        button_label: str = Form("Open Ticket"), button_emoji: str = Form(""),
        staff_role_id: str = Form(""),
    ):
        session, guild = await require_manager(request, guild_id)
        channel = guild.get_channel(channel_id)
        if not channel:
            raise HTTPException(status_code=400, detail="Channel not found.")

        import ui
        resolved_theme = theme if helpers.theme_is_valid(theme) else "blue"
        panel_id = await bot.db.create_panel(
            guild_id, channel.id, title[:200], description[:1500], resolved_theme,
            int(category_id) if category_id else None,
            button_label[:80] or "Open Ticket", button_emoji or None,
            [int(staff_role_id)] if staff_role_id else [], int(session["id"]),
        )
        view = ui.build_panel_view(title[:200], description[:1500], resolved_theme, button_label[:80] or "Open Ticket", button_emoji or None)
        message = await channel.send(view=view)
        await bot.db.set_panel_message(panel_id, message.id)
        return RedirectResponse(f"/dashboard/{guild_id}/panels?saved=1", status_code=303)

    @app.post("/dashboard/{guild_id}/panels/{panel_id}/delete")
    async def panel_delete(request: Request, guild_id: int, panel_id: int):
        session, guild = await require_manager(request, guild_id)
        p = await bot.db.get_panel(panel_id)
        if p and p["guild_id"] == guild_id:
            channel = guild.get_channel(p["channel_id"])
            if channel and p["message_id"]:
                try:
                    msg = await channel.fetch_message(p["message_id"])
                    await msg.delete()
                except discord.HTTPException:
                    pass
            await bot.db.delete_panel(panel_id)
        return RedirectResponse(f"/dashboard/{guild_id}/panels?deleted=1", status_code=303)

    # tickets

    @app.get("/dashboard/{guild_id}/tickets", response_class=HTMLResponse)
    async def tickets_page(request: Request, guild_id: int, status: str = "open"):
        session, guild = await require_manager(request, guild_id)
        status = status if status in ("open", "closed") else "open"
        rows = await bot.db.list_guild_tickets(guild_id, status=status, limit=200)
        for t in rows:
            ch = guild.get_channel(t["channel_id"])
            t["channel_name"] = ch.name if ch else None
            opener = guild.get_member(t["opener_id"])
            t["opener_name"] = str(opener) if opener else f"User {t['opener_id']}"
            handler = guild.get_member(t["claimed_by"]) if t["claimed_by"] else None
            t["handler_name"] = str(handler) if handler else None
        return templates.TemplateResponse("tickets.html", ctx(
            request, session, active="tickets", guild={"id": guild.id, "name": guild.name},
            tickets=rows, status=status,
        ))

    @app.get("/dashboard/{guild_id}/tickets/{ticket_id}/transcript")
    async def ticket_transcript(request: Request, guild_id: int, ticket_id: int):
        await require_manager(request, guild_id)
        ticket = await bot.db.get_ticket(ticket_id)
        if not ticket or ticket["guild_id"] != guild_id:
            raise HTTPException(status_code=404, detail="Ticket not found.")
        path = ticket.get("transcript_path")
        if not path or not os.path.exists(path):
            channel = bot.get_channel(ticket["channel_id"])
            if not channel:
                raise HTTPException(status_code=404, detail="No transcript available and the channel is gone.")
            from utils import ticket_manager
            path = await ticket_manager.generate_html_transcript(channel, ticket)
            await bot.db.set_transcript_path(ticket_id, path)
        return FileResponse(path, media_type="text/html")

    # blacklist

    @app.get("/dashboard/{guild_id}/blacklist", response_class=HTMLResponse)
    async def blacklist_page(request: Request, guild_id: int):
        session, guild = await require_manager(request, guild_id)
        rows = await bot.db.list_blacklist(guild_id)
        for r in rows:
            m = guild.get_member(r["user_id"])
            r["user_name"] = str(m) if m else f"User {r['user_id']}"
        return templates.TemplateResponse("blacklist.html", ctx(
            request, session, active="blacklist", guild={"id": guild.id, "name": guild.name}, rows=rows,
        ))

    @app.post("/dashboard/{guild_id}/blacklist/add")
    async def blacklist_add(request: Request, guild_id: int, user_id: int = Form(...), reason: str = Form("")):
        session, guild = await require_manager(request, guild_id)
        await bot.db.blacklist_add(guild_id, user_id, reason or None, int(session["id"]))
        return RedirectResponse(f"/dashboard/{guild_id}/blacklist?saved=1", status_code=303)

    @app.post("/dashboard/{guild_id}/blacklist/{user_id}/remove")
    async def blacklist_remove(request: Request, guild_id: int, user_id: int):
        await require_manager(request, guild_id)
        await bot.db.blacklist_remove(guild_id, user_id)
        return RedirectResponse(f"/dashboard/{guild_id}/blacklist?removed=1", status_code=303)

    # logs

    @app.get("/dashboard/{guild_id}/logs", response_class=HTMLResponse)
    async def logs_page(request: Request, guild_id: int):
        session, guild = await require_manager(request, guild_id)
        rows = await bot.db.list_guild_action_logs(guild_id, limit=150)
        for r in rows:
            actor = guild.get_member(r["actor_id"]) if r["actor_id"] else None
            r["actor_name"] = str(actor) if actor else (f"User {r['actor_id']}" if r["actor_id"] else "—")
        return templates.TemplateResponse("logs.html", ctx(
            request, session, active="logs", guild={"id": guild.id, "name": guild.name}, rows=rows,
        ))

    @app.get("/healthz", response_class=PlainTextResponse)
    async def healthz():
        return "ok"

    return app


async def run_dashboard(bot):
    import uvicorn
    app = create_dashboard(bot)
    config = uvicorn.Config(app, host="0.0.0.0", port=DASHBOARD_PORT, log_level="warning")
    server = uvicorn.Server(config)
    print(f"  Dashboard starting on http://0.0.0.0:{DASHBOARD_PORT}")
    await server.serve()
