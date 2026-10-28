import time

import discord
from discord.ext import commands as _commands

THEMES = {
    "red": {"label": "Red", "color": 0xED4245},
    "cyan": {"label": "Cyan", "color": 0x00C8DC},
    "blue": {"label": "Blue", "color": 0x3B82F6},
    "purple": {"label": "Purple", "color": 0x9333EA},
    "white": {"label": "White", "color": 0xE6E6EB},
}
DEFAULT_THEME = "blue"


def theme_color(theme: str | None) -> int:
    if not theme:
        theme = DEFAULT_THEME
    entry = THEMES.get(theme.lower())
    return entry["color"] if entry else THEMES[DEFAULT_THEME]["color"]


def theme_label(theme: str | None) -> str:
    if not theme:
        theme = DEFAULT_THEME
    entry = THEMES.get(theme.lower())
    return entry["label"] if entry else THEMES[DEFAULT_THEME]["label"]


def theme_is_valid(theme: str) -> bool:
    return isinstance(theme, str) and theme.lower() in THEMES


def theme_choices() -> list[str]:
    return list(THEMES.keys())


def is_owner(bot, user_id: int) -> bool:
    return user_id in getattr(bot, "owner_ids", set())


def is_staff(bot, member: discord.Member, cfg: dict) -> bool:
    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True
    if is_owner(bot, member.id):
        return True
    role_ids = {r.id for r in member.roles}
    return bool(role_ids & (set(cfg.get("staff_role_ids", [])) | set(cfg.get("senior_role_ids", []))))


def is_senior(bot, member: discord.Member, cfg: dict) -> bool:
    if member.guild_permissions.administrator or is_owner(bot, member.id):
        return True
    role_ids = {r.id for r in member.roles}
    return bool(role_ids & set(cfg.get("senior_role_ids", [])))


def can_manage_ticket(bot, member: discord.Member, ticket: dict, cfg: dict) -> bool:
    return is_staff(bot, member, cfg) or member.id == ticket.get("opener_id")


def eligible_senior_roles(guild: discord.Guild, cfg: dict) -> list[discord.Role]:
    return [guild.get_role(r) for r in cfg.get("senior_role_ids", []) if guild.get_role(r)]


def eligible_staff_roles(guild: discord.Guild, cfg: dict) -> list[discord.Role]:
    return [guild.get_role(r) for r in cfg.get("staff_role_ids", []) if guild.get_role(r)]


def require_manage_guild():
    async def predicate(ctx: _commands.Context) -> bool:
        if is_owner(ctx.bot, ctx.author.id):
            return True
        if ctx.author.guild_permissions.manage_guild or ctx.author.guild_permissions.administrator:
            return True
        raise _commands.MissingPermissions(["manage_guild"])
    return _commands.check(predicate)


def require_staff():
    async def predicate(ctx: _commands.Context) -> bool:
        cfg = await ctx.bot.db.get_guild_config(ctx.guild.id)
        if is_staff(ctx.bot, ctx.author, cfg):
            return True
        raise _commands.CheckFailure("You must be ticket staff to use this command.")
    return _commands.check(predicate)


def require_senior():
    async def predicate(ctx: _commands.Context) -> bool:
        cfg = await ctx.bot.db.get_guild_config(ctx.guild.id)
        if is_senior(ctx.bot, ctx.author, cfg) or ctx.author.guild_permissions.manage_guild:
            return True
        raise _commands.CheckFailure("You must be senior staff to use this command.")
    return _commands.check(predicate)


DURATION_MAP = {"1h": 3600, "6h": 21600, "1d": 86400, "7d": 604800, "30d": 2592000, "lifetime": None}


def safe_channel_name(name: str, max_len: int = 90) -> str:
    import re
    slug = name.lower().strip().replace(" ", "-")
    slug = re.sub(r"[^a-z0-9-]+", "-", slug).strip("-")
    return (slug or "ticket")[:max_len]


def ticket_channel_name(number: int, opener_name: str, prefix: str = "ticket") -> str:
    return f"{prefix}-{number:04d}-{safe_channel_name(opener_name)[:20]}"[:90]


def format_duration(seconds: int) -> str:
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def format_uptime(start_time: float) -> str:
    return format_duration(time.time() - start_time)


def parse_duration(text: str) -> tuple[bool, int | None]:
    key = text.lower().strip()
    if key not in DURATION_MAP:
        return False, 0
    return True, DURATION_MAP[key]
