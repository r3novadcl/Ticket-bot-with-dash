# FX Ticket — Discord Ticket Bot with Web Dashboard

A configurable Discord ticket system built with **Python**, **discord.py**, and **SQLite**, with a web dashboard for managing server settings, ticket panels, staff roles, tickets, transcripts, blacklists, and logs.

> **Project:** FX Ticket  
> **Credits:** r3novadcl
> **Language:** Python  
> **Database:** SQLite  
> **Dashboard:** FastAPI
> **Discord library:** discord.py

---

## Features

### Discord ticket system
- Create and manage ticket panels.
- Open, close, reopen, lock, unlock, rename, claim, and unclaim tickets.
- Add or remove members from tickets.
- Transfer tickets to senior/escalation staff roles.
- Configure staff roles and senior roles separately.
- Set a default ticket category and custom ticket welcome message.
- Configure the maximum number of open tickets per user.
- Optional automatic closure for inactive tickets.
- Optional ticket transcripts and transcript delivery channel.
- Ticket history and action logging.
- Configurable command prefix and colour theme.
- Persistent ticket/panel components designed to keep working after bot restarts.

### Web dashboard
- Sign in using Discord OAuth2.
- View servers where the bot is present and where your account has permission to manage settings.
- Manage ticket configuration and staff roles.
- Create and delete ticket panels.
- Browse tickets and access available transcripts.
- Review blacklist entries and manage them.
- View ticket action logs.
- Health-check endpoint at `/healthz`.

### Additional
- SQLite database initialization and migrations.
- Emoji upload/sync helper with fallback icons.
- Owner-only bot management commands.
- Slash commands and prefix/hybrid commands where supported.

---

## Requirements

- Python **3.10 or newer** recommended.
- A Discord application and bot token.
- A server/host that can keep the bot process running.
- For dashboard login: Discord OAuth2 Client ID and Client Secret.
- A public HTTPS URL is recommended for a deployed dashboard. Local testing can use `http://localhost:8080`.

---

## Installation

### 1. Download the source

Extract the project ZIP and open a terminal in the `Ticket-Bot-Dash` folder.

### 2. Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 3. Configure environment variables

Create a file named `.env` in the project root, beside `main.py`, and add:

```env
BOT_TOKEN=YOUR_DISCORD_BOT_TOKEN
DEFAULT_PREFIX=!
DASHBOARD_ENABLED=true

# Discord OAuth2 settings for the web dashboard
DISCORD_CLIENT_ID=YOUR_DISCORD_APPLICATION_CLIENT_ID
DISCORD_CLIENT_SECRET=YOUR_DISCORD_OAUTH2_CLIENT_SECRET
DASHBOARD_REDIRECT_URI=http://localhost:8080/auth/callback

# Set a long, random secret for signing dashboard sessions
DASHBOARD_SESSION_SECRET=REPLACE_WITH_A_LONG_RANDOM_SECRET

# Dashboard web server port
DASHBOARD_PORT=8080
```

Replace every placeholder with your own values. Do **not** share your `.env` file or upload it to GitHub.

### 4. Configure the Discord Developer Portal

1. Open the [Discord Developer Portal](https://discord.com/developers/applications).
2. Select your application and open **Bot**.
3. Copy the bot token into `BOT_TOKEN`. If the token has ever been exposed, regenerate it.
4. Under **Privileged Gateway Intents**, enable **Server Members Intent** and **Message Content Intent** if your bot's features require them.
5. Open **OAuth2** and add the exact value of `DASHBOARD_REDIRECT_URI` to **Redirects**.
6. Use the bot's OAuth2 URL generator to invite it to your server with the permissions required for managing channels, roles/overwrites, messages, and ticket transcripts.

For local testing, the redirect URI should match exactly in both `.env` and the Developer Portal. For production, replace it with your dashboard's public HTTPS callback URL, for example `https://your-domain.example/auth/callback`, and register that exact URL in the portal.

### 5. Check the owner ID

Open `config.py` and replace the existing value in `OWNER_IDS` with your own Discord user ID. Keep this list limited to trusted bot owners.

### 6. Start the bot

```bash
python main.py
```

When startup succeeds, the bot connects to Discord, initializes the SQLite database, loads its cogs, registers persistent UI components, syncs application commands, and starts the dashboard if enabled.

---

## Opening the dashboard

With the default configuration, visit:

```text
http://localhost:8080
```

Choose the Discord login option. The dashboard uses Discord OAuth2 to identify you, then checks your permissions for each server before allowing management access.

For a hosted deployment, open the dashboard using the public URL configured in `DASHBOARD_REDIRECT_URI`. Make sure the hosting provider exposes the configured port and that HTTPS/proxy settings are configured correctly.

To run only the bot without the dashboard, set:

```env
DASHBOARD_ENABLED=false
```

---

## First-time server setup

1. Invite the bot to your Discord server.
2. Ensure the bot has permission to view channels, send messages, manage channels, manage channel permissions, embed links, and attach files as required by your setup.
3. Use the bot's ticket configuration commands or the web dashboard to choose the default ticket category, staff roles, log channel, transcript channel, theme, and ticket limits.
4. Create a ticket panel and post it in a channel visible to your members.
5. Test opening and closing a ticket with a regular member account before announcing the system.

Use the built-in command help to see the commands available in the version you are running.

---

## Configuration notes

| Setting | Purpose |
|---|---|
| `BOT_TOKEN` | Discord bot token |
| `DEFAULT_PREFIX` | Default prefix used before a server-specific prefix is configured |
| `DASHBOARD_ENABLED` | Enables or disables the dashboard |
| `DISCORD_CLIENT_ID` | Discord application/client ID for OAuth2 |
| `DISCORD_CLIENT_SECRET` | OAuth2 client secret; keep private |
| `DASHBOARD_REDIRECT_URI` | Exact OAuth2 callback URL |
| `DASHBOARD_SESSION_SECRET` | Secret used to sign dashboard session cookies |
| `DASHBOARD_PORT` | Port used by the dashboard; defaults to `8080` |

The project currently stores data in a local SQLite database under `data/`. Back up the database and transcript directory before moving the bot or making significant changes.

---

## Troubleshooting

- **`BOT_TOKEN is not set`** — confirm that `.env` is in the same directory as `main.py` and that `BOT_TOKEN` is filled in.
- **Dashboard login fails** — verify the Client ID, Client Secret, and exact callback URL. The redirect URL must match the Discord Developer Portal entry.
- **Dashboard does not open on a host** — confirm `DASHBOARD_ENABLED=true`, check `DASHBOARD_PORT`, and ensure the host exposes the port.
- **Prefix commands do not respond** — check `DEFAULT_PREFIX`, the server's configured prefix, and the Message Content Intent setting.
- **Slash commands are missing** — check the startup logs for command-sync errors and confirm the bot was invited with the `applications.commands` scope.
- **Ticket actions fail** — verify the bot's channel permissions and that the configured staff roles/category/log channels still exist.
- **Emoji sync fails** — the bot is designed to continue with cached/fallback icons if the upload helper cannot sync emojis.

---

## Credits

**FX DEVELOPMENT** — project branding and source distribution.

Built with:
- [discord.py](https://discordpy.readthedocs.io/)
- [FastAPI](https://fastapi.tiangolo.com/)
- [Uvicorn](https://www.uvicorn.org/)
- [Jinja2](https://jinja.palletsprojects.com/)
- [aiosqlite](https://aiosqlite.omnilib.dev/)
- [python-dotenv](https://github.com/theskumar/python-dotenv)
- [itsdangerous](https://itsdangerous.palletsprojects.com/)

Thanks to the maintainers of these open-source projects.

---

## Security

- Never publish your bot token, OAuth2 client secret, or `.env` file.
- Keep `DASHBOARD_SESSION_SECRET` stable and private in production.
- Use HTTPS for a public dashboard.
- Only grant bot-owner access to trusted people.
- Do not publish a database or transcript folder containing real user/ticket data.
- Review dependencies and permissions before deploying a modified copy.

---

**FX DEVELOPMENT**  
*Ticket management, made simpler.*
