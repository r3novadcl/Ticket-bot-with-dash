# SQLite persistence for the ticket system. One shared connection used
# by both the bot and the dashboard (same process/event loop).
import json
import time
import asyncio
import aiosqlite

DB_PATH = "data/tickets.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_config (
    guild_id              INTEGER PRIMARY KEY,
    prefix                TEXT DEFAULT '!',
    theme                 TEXT DEFAULT 'blue',
    category_id           INTEGER,
    log_channel_id        INTEGER,
    transcript_channel_id INTEGER,
    staff_role_ids        TEXT DEFAULT '[]',
    senior_role_ids       TEXT DEFAULT '[]',
    max_tickets_per_user  INTEGER DEFAULT 1,
    ticket_counter        INTEGER DEFAULT 0,
    welcome_message       TEXT DEFAULT 'Thanks for reaching out! Support will be with you shortly.',
    auto_close_hours      INTEGER DEFAULT 0,
    transcripts_enabled   INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS panels (
    panel_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id       INTEGER NOT NULL,
    channel_id     INTEGER NOT NULL,
    message_id     INTEGER,
    title          TEXT DEFAULT 'Support Tickets',
    description    TEXT DEFAULT 'Click the button below to open a ticket.',
    theme          TEXT DEFAULT 'blue',
    category_id    INTEGER,
    button_label   TEXT DEFAULT 'Open Ticket',
    button_emoji   TEXT,
    staff_role_ids TEXT DEFAULT '[]',
    created_by     INTEGER,
    created_at     INTEGER
);

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id           INTEGER NOT NULL,
    channel_id         INTEGER UNIQUE NOT NULL,
    panel_id           INTEGER,
    number             INTEGER,
    opener_id          INTEGER NOT NULL,
    claimed_by         INTEGER,
    status             TEXT DEFAULT 'open',
    locked             INTEGER DEFAULT 0,
    subject            TEXT,
    created_at         INTEGER,
    closed_at          INTEGER,
    closed_by          INTEGER,
    close_reason       TEXT,
    transcript_path    TEXT,
    transferred_count  INTEGER DEFAULT 0,
    control_message_id INTEGER
);

CREATE TABLE IF NOT EXISTS ticket_members (
    ticket_id  INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    added_by   INTEGER,
    added_at   INTEGER,
    PRIMARY KEY (ticket_id, user_id)
);

CREATE TABLE IF NOT EXISTS transfer_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id       INTEGER NOT NULL,
    from_user_id    INTEGER,
    to_role_id      INTEGER NOT NULL,
    reason          TEXT,
    transferred_by  INTEGER NOT NULL,
    transferred_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS blacklist (
    guild_id  INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    reason    TEXT,
    added_by  INTEGER,
    added_at  INTEGER,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS ticket_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id   INTEGER,
    guild_id    INTEGER NOT NULL,
    action      TEXT NOT NULL,
    actor_id    INTEGER,
    detail      TEXT,
    created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS noprefix (
    user_id     INTEGER PRIMARY KEY,
    added_by    INTEGER NOT NULL,
    added_at    INTEGER NOT NULL,
    expires_at  INTEGER
);

CREATE INDEX IF NOT EXISTS idx_tickets_guild_status ON tickets(guild_id, status);
CREATE INDEX IF NOT EXISTS idx_tickets_opener ON tickets(guild_id, opener_id);
CREATE INDEX IF NOT EXISTS idx_logs_ticket ON ticket_logs(ticket_id);
"""


def _row_to_config(row) -> dict:
    (guild_id, prefix, theme, category_id, log_channel_id, transcript_channel_id,
     staff_role_ids, senior_role_ids, max_tickets, ticket_counter, welcome_message,
     auto_close_hours, transcripts_enabled) = row
    return {
        "guild_id": guild_id,
        "prefix": prefix,
        "theme": theme,
        "category_id": category_id,
        "log_channel_id": log_channel_id,
        "transcript_channel_id": transcript_channel_id,
        "staff_role_ids": json.loads(staff_role_ids or "[]"),
        "senior_role_ids": json.loads(senior_role_ids or "[]"),
        "max_tickets_per_user": max_tickets,
        "ticket_counter": ticket_counter,
        "welcome_message": welcome_message,
        "auto_close_hours": auto_close_hours,
        "transcripts_enabled": bool(transcripts_enabled),
    }


def _row_to_panel(row) -> dict:
    (panel_id, guild_id, channel_id, message_id, title, description, theme,
     category_id, button_label, button_emoji, staff_role_ids, created_by, created_at) = row
    return {
        "panel_id": panel_id,
        "guild_id": guild_id,
        "channel_id": channel_id,
        "message_id": message_id,
        "title": title,
        "description": description,
        "theme": theme,
        "category_id": category_id,
        "button_label": button_label,
        "button_emoji": button_emoji,
        "staff_role_ids": json.loads(staff_role_ids or "[]"),
        "created_by": created_by,
        "created_at": created_at,
    }


def _row_to_ticket(row) -> dict:
    (ticket_id, guild_id, channel_id, panel_id, number, opener_id, claimed_by,
     status, locked, subject, created_at, closed_at, closed_by, close_reason,
     transcript_path, transferred_count, control_message_id) = row
    return {
        "ticket_id": ticket_id,
        "guild_id": guild_id,
        "channel_id": channel_id,
        "panel_id": panel_id,
        "number": number,
        "opener_id": opener_id,
        "claimed_by": claimed_by,
        "status": status,
        "locked": bool(locked),
        "subject": subject,
        "created_at": created_at,
        "closed_at": closed_at,
        "closed_by": closed_by,
        "close_reason": close_reason,
        "transcript_path": transcript_path,
        "transferred_count": transferred_count,
        "control_message_id": control_message_id,
    }


TICKET_COLUMNS = (
    "ticket_id, guild_id, channel_id, panel_id, number, opener_id, claimed_by, "
    "status, locked, subject, created_at, closed_at, closed_by, close_reason, "
    "transcript_path, transferred_count, control_message_id"
)
PANEL_COLUMNS = (
    "panel_id, guild_id, channel_id, message_id, title, description, theme, "
    "category_id, button_label, button_emoji, staff_role_ids, created_by, created_at"
)
CONFIG_COLUMNS = (
    "guild_id, prefix, theme, category_id, log_channel_id, transcript_channel_id, "
    "staff_role_ids, senior_role_ids, max_tickets_per_user, ticket_counter, "
    "welcome_message, auto_close_hours, transcripts_enabled"
)


class Database:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def init(self):
        import os
        os.makedirs("data/transcripts", exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def close(self):
        if self._conn:
            await self._conn.close()

    # guild config

    async def get_guild_config(self, guild_id: int) -> dict:
        cur = await self._conn.execute(
            f"SELECT {CONFIG_COLUMNS} FROM guild_config WHERE guild_id = ?", (guild_id,)
        )
        row = await cur.fetchone()
        if row:
            return _row_to_config(row)
        await self._conn.execute(
            "INSERT INTO guild_config (guild_id) VALUES (?)", (guild_id,)
        )
        await self._conn.commit()
        return await self.get_guild_config(guild_id)

    async def update_guild_config(self, guild_id: int, **fields):
        if not fields:
            return
        await self.get_guild_config(guild_id)  # ensure row exists
        json_fields = {"staff_role_ids", "senior_role_ids"}
        cols, vals = [], []
        for key, value in fields.items():
            if key in json_fields:
                value = json.dumps(value)
            cols.append(f"{key} = ?")
            vals.append(value)
        vals.append(guild_id)
        await self._conn.execute(
            f"UPDATE guild_config SET {', '.join(cols)} WHERE guild_id = ?", vals
        )
        await self._conn.commit()

    async def add_staff_role(self, guild_id: int, role_id: int):
        cfg = await self.get_guild_config(guild_id)
        roles = set(cfg["staff_role_ids"])
        roles.add(role_id)
        await self.update_guild_config(guild_id, staff_role_ids=list(roles))

    async def remove_staff_role(self, guild_id: int, role_id: int):
        cfg = await self.get_guild_config(guild_id)
        roles = [r for r in cfg["staff_role_ids"] if r != role_id]
        await self.update_guild_config(guild_id, staff_role_ids=roles)

    async def add_senior_role(self, guild_id: int, role_id: int):
        cfg = await self.get_guild_config(guild_id)
        roles = set(cfg["senior_role_ids"])
        roles.add(role_id)
        await self.update_guild_config(guild_id, senior_role_ids=list(roles))

    async def remove_senior_role(self, guild_id: int, role_id: int):
        cfg = await self.get_guild_config(guild_id)
        roles = [r for r in cfg["senior_role_ids"] if r != role_id]
        await self.update_guild_config(guild_id, senior_role_ids=roles)

    async def get_prefix(self, guild_id: int) -> str:
        cfg = await self.get_guild_config(guild_id)
        return cfg["prefix"]

    async def set_prefix(self, guild_id: int, prefix: str):
        await self.update_guild_config(guild_id, prefix=prefix)

    async def next_ticket_number(self, guild_id: int) -> int:
        async with self._lock:
            await self.get_guild_config(guild_id)
            await self._conn.execute(
                "UPDATE guild_config SET ticket_counter = ticket_counter + 1 WHERE guild_id = ?",
                (guild_id,),
            )
            await self._conn.commit()
            cur = await self._conn.execute(
                "SELECT ticket_counter FROM guild_config WHERE guild_id = ?", (guild_id,)
            )
            row = await cur.fetchone()
            return row[0]

    # panels

    async def create_panel(self, guild_id, channel_id, title, description, theme,
                            category_id, button_label, button_emoji, staff_role_ids,
                            created_by) -> int:
        cur = await self._conn.execute(
            """INSERT INTO panels
               (guild_id, channel_id, title, description, theme, category_id,
                button_label, button_emoji, staff_role_ids, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (guild_id, channel_id, title, description, theme, category_id,
             button_label, button_emoji, json.dumps(staff_role_ids or []),
             created_by, int(time.time())),
        )
        await self._conn.commit()
        return cur.lastrowid

    async def set_panel_message(self, panel_id: int, message_id: int):
        await self._conn.execute(
            "UPDATE panels SET message_id = ? WHERE panel_id = ?", (message_id, panel_id)
        )
        await self._conn.commit()

    async def get_panel(self, panel_id: int) -> dict | None:
        cur = await self._conn.execute(
            f"SELECT {PANEL_COLUMNS} FROM panels WHERE panel_id = ?", (panel_id,)
        )
        row = await cur.fetchone()
        return _row_to_panel(row) if row else None

    async def get_panel_by_message(self, message_id: int) -> dict | None:
        cur = await self._conn.execute(
            f"SELECT {PANEL_COLUMNS} FROM panels WHERE message_id = ?", (message_id,)
        )
        row = await cur.fetchone()
        return _row_to_panel(row) if row else None

    async def list_panels(self, guild_id: int) -> list[dict]:
        cur = await self._conn.execute(
            f"SELECT {PANEL_COLUMNS} FROM panels WHERE guild_id = ? ORDER BY panel_id", (guild_id,)
        )
        return [_row_to_panel(r) for r in await cur.fetchall()]

    async def update_panel(self, panel_id: int, **fields):
        if not fields:
            return
        if "staff_role_ids" in fields:
            fields["staff_role_ids"] = json.dumps(fields["staff_role_ids"])
        cols = [f"{k} = ?" for k in fields]
        vals = list(fields.values()) + [panel_id]
        await self._conn.execute(
            f"UPDATE panels SET {', '.join(cols)} WHERE panel_id = ?", vals
        )
        await self._conn.commit()

    async def delete_panel(self, panel_id: int):
        await self._conn.execute("DELETE FROM panels WHERE panel_id = ?", (panel_id,))
        await self._conn.commit()

    # tickets

    async def count_open_tickets_for_user(self, guild_id: int, user_id: int) -> int:
        cur = await self._conn.execute(
            "SELECT COUNT(*) FROM tickets WHERE guild_id = ? AND opener_id = ? AND status = 'open'",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        return row[0]

    async def create_ticket(self, guild_id, channel_id, panel_id, opener_id, subject=None) -> dict:
        number = await self.next_ticket_number(guild_id)
        cur = await self._conn.execute(
            """INSERT INTO tickets
               (guild_id, channel_id, panel_id, number, opener_id, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'open', ?)""",
            (guild_id, channel_id, panel_id, number, opener_id, int(time.time())),
        )
        await self._conn.commit()
        if subject:
            await self._conn.execute(
                "UPDATE tickets SET subject = ? WHERE ticket_id = ?", (subject, cur.lastrowid)
            )
            await self._conn.commit()
        return await self.get_ticket(cur.lastrowid)

    async def get_ticket(self, ticket_id: int) -> dict | None:
        cur = await self._conn.execute(
            f"SELECT {TICKET_COLUMNS} FROM tickets WHERE ticket_id = ?", (ticket_id,)
        )
        row = await cur.fetchone()
        return _row_to_ticket(row) if row else None

    async def get_ticket_by_channel(self, channel_id: int) -> dict | None:
        cur = await self._conn.execute(
            f"SELECT {TICKET_COLUMNS} FROM tickets WHERE channel_id = ?", (channel_id,)
        )
        row = await cur.fetchone()
        return _row_to_ticket(row) if row else None

    async def update_ticket(self, ticket_id: int, **fields):
        if not fields:
            return
        cols = [f"{k} = ?" for k in fields]
        vals = list(fields.values()) + [ticket_id]
        await self._conn.execute(
            f"UPDATE tickets SET {', '.join(cols)} WHERE ticket_id = ?", vals
        )
        await self._conn.commit()

    async def claim_ticket(self, ticket_id: int, staff_id: int):
        await self.update_ticket(ticket_id, claimed_by=staff_id)

    async def unclaim_ticket(self, ticket_id: int):
        await self.update_ticket(ticket_id, claimed_by=None)

    async def lock_ticket(self, ticket_id: int):
        await self.update_ticket(ticket_id, locked=1)

    async def unlock_ticket(self, ticket_id: int):
        await self.update_ticket(ticket_id, locked=0)

    async def close_ticket(self, ticket_id: int, closed_by: int, reason: str | None):
        await self.update_ticket(
            ticket_id, status="closed", closed_at=int(time.time()),
            closed_by=closed_by, close_reason=reason,
        )

    async def reopen_ticket(self, ticket_id: int):
        await self.update_ticket(
            ticket_id, status="open", closed_at=None, closed_by=None, close_reason=None,
        )

    async def set_transcript_path(self, ticket_id: int, path: str):
        await self.update_ticket(ticket_id, transcript_path=path)

    async def set_control_message(self, ticket_id: int, message_id: int):
        await self.update_ticket(ticket_id, control_message_id=message_id)

    async def delete_ticket_record(self, ticket_id: int):
        await self._conn.execute("DELETE FROM tickets WHERE ticket_id = ?", (ticket_id,))
        await self._conn.execute("DELETE FROM ticket_members WHERE ticket_id = ?", (ticket_id,))
        await self._conn.commit()

    async def list_open_tickets(self, guild_id: int) -> list[dict]:
        cur = await self._conn.execute(
            f"SELECT {TICKET_COLUMNS} FROM tickets WHERE guild_id = ? AND status = 'open' "
            f"ORDER BY created_at DESC",
            (guild_id,),
        )
        return [_row_to_ticket(r) for r in await cur.fetchall()]

    async def list_guild_tickets(self, guild_id: int, status: str | None = None, limit: int = 100) -> list[dict]:
        if status:
            cur = await self._conn.execute(
                f"SELECT {TICKET_COLUMNS} FROM tickets WHERE guild_id = ? AND status = ? "
                f"ORDER BY created_at DESC LIMIT ?",
                (guild_id, status, limit),
            )
        else:
            cur = await self._conn.execute(
                f"SELECT {TICKET_COLUMNS} FROM tickets WHERE guild_id = ? "
                f"ORDER BY created_at DESC LIMIT ?",
                (guild_id, limit),
            )
        return [_row_to_ticket(r) for r in await cur.fetchall()]

    async def list_stale_open_tickets(self, guild_id: int, older_than_ts: int) -> list[dict]:
        cur = await self._conn.execute(
            f"SELECT {TICKET_COLUMNS} FROM tickets WHERE guild_id = ? AND status = 'open' "
            f"AND created_at < ?",
            (guild_id, older_than_ts),
        )
        return [_row_to_ticket(r) for r in await cur.fetchall()]

    # ticket members

    async def add_ticket_member(self, ticket_id: int, user_id: int, added_by: int):
        await self._conn.execute(
            "INSERT OR IGNORE INTO ticket_members (ticket_id, user_id, added_by, added_at) "
            "VALUES (?, ?, ?, ?)",
            (ticket_id, user_id, added_by, int(time.time())),
        )
        await self._conn.commit()

    async def remove_ticket_member(self, ticket_id: int, user_id: int) -> bool:
        cur = await self._conn.execute(
            "DELETE FROM ticket_members WHERE ticket_id = ? AND user_id = ?",
            (ticket_id, user_id),
        )
        await self._conn.commit()
        return cur.rowcount > 0

    async def list_ticket_members(self, ticket_id: int) -> list[int]:
        cur = await self._conn.execute(
            "SELECT user_id FROM ticket_members WHERE ticket_id = ?", (ticket_id,)
        )
        return [r[0] for r in await cur.fetchall()]

    # transfer / escalation history

    async def log_transfer(self, ticket_id: int, from_user_id: int | None, to_role_id: int,
                            reason: str | None, transferred_by: int):
        await self._conn.execute(
            """INSERT INTO transfer_history
               (ticket_id, from_user_id, to_role_id, reason, transferred_by, transferred_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ticket_id, from_user_id, to_role_id, reason, transferred_by, int(time.time())),
        )
        await self._conn.execute(
            "UPDATE tickets SET transferred_count = transferred_count + 1, claimed_by = NULL "
            "WHERE ticket_id = ?",
            (ticket_id,),
        )
        await self._conn.commit()

    async def list_transfers(self, ticket_id: int) -> list[dict]:
        cur = await self._conn.execute(
            """SELECT id, ticket_id, from_user_id, to_role_id, reason, transferred_by, transferred_at
               FROM transfer_history WHERE ticket_id = ? ORDER BY transferred_at""",
            (ticket_id,),
        )
        rows = await cur.fetchall()
        return [
            {
                "id": r[0], "ticket_id": r[1], "from_user_id": r[2], "to_role_id": r[3],
                "reason": r[4], "transferred_by": r[5], "transferred_at": r[6],
            }
            for r in rows
        ]

    # blacklist

    async def blacklist_add(self, guild_id: int, user_id: int, reason: str | None, added_by: int):
        await self._conn.execute(
            """INSERT INTO blacklist (guild_id, user_id, reason, added_by, added_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(guild_id, user_id) DO UPDATE SET
                   reason = excluded.reason, added_by = excluded.added_by, added_at = excluded.added_at""",
            (guild_id, user_id, reason, added_by, int(time.time())),
        )
        await self._conn.commit()

    async def blacklist_remove(self, guild_id: int, user_id: int) -> bool:
        cur = await self._conn.execute(
            "DELETE FROM blacklist WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        await self._conn.commit()
        return cur.rowcount > 0

    async def is_blacklisted(self, guild_id: int, user_id: int) -> bool:
        cur = await self._conn.execute(
            "SELECT 1 FROM blacklist WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        return await cur.fetchone() is not None

    async def list_blacklist(self, guild_id: int) -> list[dict]:
        cur = await self._conn.execute(
            "SELECT user_id, reason, added_by, added_at FROM blacklist WHERE guild_id = ?",
            (guild_id,),
        )
        rows = await cur.fetchall()
        return [{"user_id": r[0], "reason": r[1], "added_by": r[2], "added_at": r[3]} for r in rows]

    # action logs

    async def log_action(self, guild_id: int, action: str, actor_id: int | None = None,
                          ticket_id: int | None = None, detail: str | None = None):
        await self._conn.execute(
            """INSERT INTO ticket_logs (ticket_id, guild_id, action, actor_id, detail, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ticket_id, guild_id, action, actor_id, detail, int(time.time())),
        )
        await self._conn.commit()

    async def list_ticket_action_logs(self, ticket_id: int) -> list[dict]:
        cur = await self._conn.execute(
            """SELECT id, ticket_id, guild_id, action, actor_id, detail, created_at
               FROM ticket_logs WHERE ticket_id = ? ORDER BY created_at""",
            (ticket_id,),
        )
        return [self._row_to_log(r) for r in await cur.fetchall()]

    async def list_guild_action_logs(self, guild_id: int, limit: int = 100) -> list[dict]:
        cur = await self._conn.execute(
            """SELECT id, ticket_id, guild_id, action, actor_id, detail, created_at
               FROM ticket_logs WHERE guild_id = ? ORDER BY created_at DESC LIMIT ?""",
            (guild_id, limit),
        )
        return [self._row_to_log(r) for r in await cur.fetchall()]

    @staticmethod
    def _row_to_log(r) -> dict:
        return {
            "id": r[0], "ticket_id": r[1], "guild_id": r[2], "action": r[3],
            "actor_id": r[4], "detail": r[5], "created_at": r[6],
        }

    # noprefix

    async def add_noprefix(self, user_id: int, added_by: int, expires_at: int | None = None):
        await self._conn.execute(
            """INSERT INTO noprefix (user_id, added_by, added_at, expires_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   added_by = excluded.added_by, added_at = excluded.added_at,
                   expires_at = excluded.expires_at""",
            (user_id, added_by, int(time.time()), expires_at),
        )
        await self._conn.commit()

    async def remove_noprefix(self, user_id: int) -> bool:
        cur = await self._conn.execute("DELETE FROM noprefix WHERE user_id = ?", (user_id,))
        await self._conn.commit()
        return cur.rowcount > 0

    async def is_noprefix(self, user_id: int) -> bool:
        cur = await self._conn.execute(
            "SELECT expires_at FROM noprefix WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
        if not row:
            return False
        expires_at = row[0]
        if expires_at is not None and expires_at < int(time.time()):
            await self._conn.execute("DELETE FROM noprefix WHERE user_id = ?", (user_id,))
            await self._conn.commit()
            return False
        return True

    async def get_noprefix(self, user_id: int):
        cur = await self._conn.execute(
            "SELECT user_id, added_by, added_at, expires_at FROM noprefix WHERE user_id = ?",
            (user_id,),
        )
        return await cur.fetchone()

    async def list_noprefix(self):
        cur = await self._conn.execute(
            "SELECT user_id, added_by, added_at, expires_at FROM noprefix"
        )
        return await cur.fetchall()
