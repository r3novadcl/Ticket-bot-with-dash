import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    TOKEN = os.getenv("BOT_TOKEN")
    DEFAULT_PREFIX = os.getenv("DEFAULT_PREFIX", "!")
    
    OWNER_IDS = [1484508031923392522]

    BOT_NAME = "FX Ticket"

    DASHBOARD_ENABLED = os.getenv("DASHBOARD_ENABLED", "true").lower() == "true"
