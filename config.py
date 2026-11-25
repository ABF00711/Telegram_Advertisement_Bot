import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
MEDIA_DIR = DATA_DIR / "media"
LOG_DIR = BASE_DIR / "logs"
SESSION_DIR = BASE_DIR / "sessions"

for path in (DATA_DIR, MEDIA_DIR, LOG_DIR, SESSION_DIR):
    path.mkdir(parents=True, exist_ok=True)

API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")

if not all([API_ID, API_HASH, BOT_TOKEN, ADMIN_USER_ID]):
    raise ValueError("Missing configuration in .env")

API_ID = int(API_ID)
ADMIN_USER_ID = int(ADMIN_USER_ID)

# Keeps the session that is already signed in.
SESSION_NAME = os.getenv("SESSION_NAME", str(SESSION_DIR / "personal_user"))

TIMEZONE = os.getenv("TIMEZONE", "GMT")
try:
    LOCAL_TZ = ZoneInfo(TIMEZONE)
except Exception as exc:
    raise ValueError(f"Invalid TIMEZONE: {TIMEZONE}") from exc

_db_path = (DATA_DIR / "app.db").as_posix()
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{_db_path}")
