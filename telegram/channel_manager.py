import logging

from sqlalchemy import select

from database.database import session_scope, utcnow
from database.models import Channel
from telegram.user_client import get_authorized_channels

logger = logging.getLogger(__name__)


async def sync_channels() -> dict:
    found = await get_authorized_channels()

    async with session_scope() as session:
        existing = {
            row.telegram_id: row
            for row in await session.scalars(select(Channel))
        }
        seen: set[int] = set()

        for item in found:
            telegram_id = int(item["id"])
            seen.add(telegram_id)
            row = existing.get(telegram_id)
            if row is None:
                row = Channel(telegram_id=telegram_id)
                session.add(row)
            row.access_hash = int(item["access_hash"] or 0)
            row.title = item["title"] or "Untitled"
            row.username = item["username"]
            row.can_post = bool(item["can_post"])
            row.synced_at = utcnow()

        for telegram_id, row in existing.items():
            if telegram_id not in seen:
                row.can_post = False
                row.synced_at = utcnow()

    postable = sum(1 for item in found if item["can_post"])
    logger.info("Synced %s channels, %s can post", len(found), postable)
    return {"total": len(found), "postable": postable}
