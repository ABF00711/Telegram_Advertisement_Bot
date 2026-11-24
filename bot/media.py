import logging
from uuid import uuid4

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from config import BASE_DIR, MEDIA_DIR

logger = logging.getLogger(__name__)

BOT_DOWNLOAD_LIMIT = 20 * 1024 * 1024


class MediaTooLarge(Exception):
    """The bot API cannot download this file."""


def _suffix(name: str | None, default: str) -> str:
    if not name or "." not in name:
        return default
    extension = "." + name.rsplit(".", 1)[-1].lower()
    if not extension[1:].isalnum() or len(extension) > 8:
        return default
    return extension


def _size(message: Message) -> int | None:
    media = message.video or message.animation or message.document
    if media is not None and media.file_size:
        return media.file_size
    if message.photo:
        return message.photo[-1].file_size
    return None


async def save_message_media(bot: Bot, message: Message) -> tuple[str, str]:
    size = _size(message)
    if size and size > BOT_DOWNLOAD_LIMIT:
        raise MediaTooLarge()

    if message.photo:
        source = message.photo[-1]
        kind = "photo"
        extension = ".jpg"
    elif message.video:
        source = message.video
        kind = "video"
        extension = _suffix(message.video.file_name, ".mp4")
    elif message.animation:
        source = message.animation
        kind = "animation"
        extension = _suffix(message.animation.file_name, ".mp4")
    elif message.document:
        source = message.document
        kind = "document"
        extension = _suffix(message.document.file_name, ".bin")
    else:
        raise ValueError("This message has no file.")

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    path = MEDIA_DIR / f"{uuid4().hex}{extension}"
    try:
        await bot.download(source, destination=path, timeout=180)
    except TelegramBadRequest as exc:
        path.unlink(missing_ok=True)
        raise MediaTooLarge() from exc
    except Exception:
        path.unlink(missing_ok=True)
        raise

    if not path.is_file() or path.stat().st_size == 0:
        path.unlink(missing_ok=True)
        raise RuntimeError("Downloaded file is empty.")

    logger.info("Saved %s (%s bytes)", path.name, path.stat().st_size)
    return path.relative_to(BASE_DIR).as_posix(), kind
