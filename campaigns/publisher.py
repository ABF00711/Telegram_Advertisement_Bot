import asyncio
import logging
import re
from dataclasses import dataclass
from html import unescape
from pathlib import Path

from sqlalchemy import select
from telethon.errors import (
    ChannelPrivateError,
    ChatAdminRequiredError,
    ChatWriteForbiddenError,
    FloodWaitError,
    UserBannedInChannelError,
)
from telethon.tl.types import InputPeerChannel, PeerChannel

from config import BASE_DIR
from database.database import session_scope
from database.models import Ad, Channel
from telegram.user_client import get_client

logger = logging.getLogger(__name__)

_TAG = re.compile(r"<[^>]+>")
_BREAK = re.compile(r"<br\s*/?>|</p>", re.IGNORECASE)


@dataclass
class PublishResult:
    title: str
    ok: bool
    error: str | None = None
    retry_after: int | None = None
    posted: bool = False


def html_to_text(value: str) -> str:
    text = _BREAK.sub("\n", value or "")
    text = _TAG.sub("", text)
    return unescape(text).strip()


def format_results(results: list[PublishResult]) -> str:
    if not results:
        return "Nothing was sent."
    sent = sum(1 for result in results if result.ok)
    lines = [f"Sent to {sent} of {len(results)} channels."]
    for result in results:
        if result.ok:
            lines.append(f"- {result.title}: sent")
        else:
            lines.append(f"- {result.title}: {result.error}")
    text = "\n".join(lines)
    if len(text) > 3500:
        return text[:3490] + "\n..."
    return text


def _peer(channel: dict):
    if channel["access_hash"]:
        return InputPeerChannel(channel["telegram_id"], channel["access_hash"])
    return PeerChannel(channel["telegram_id"])


def _explain(exc: Exception) -> tuple[str, int | None]:
    if isinstance(exc, FloodWaitError):
        return f"Telegram rate limit. Wait {exc.seconds} seconds.", int(exc.seconds)
    if isinstance(exc, (ChatWriteForbiddenError, ChatAdminRequiredError)):
        return "This account cannot post in that channel.", None
    if isinstance(exc, ChannelPrivateError):
        return "The channel is private, or this account was removed.", None
    if isinstance(exc, UserBannedInChannelError):
        return "This account is restricted in that channel.", None
    return str(exc) or exc.__class__.__name__, None


async def _send_text(peer, body_html: str, body_text: str) -> None:
    client = get_client()
    plain = body_text or html_to_text(body_html)
    if body_html:
        try:
            await client.send_message(peer, body_html, parse_mode="html", link_preview=False)
            return
        except (
            FloodWaitError,
            ChatWriteForbiddenError,
            ChatAdminRequiredError,
            ChannelPrivateError,
            UserBannedInChannelError,
        ):
            raise
        except ValueError:
            logger.exception("Formatted text was rejected. Sending plain text.")
    await client.send_message(peer, plain, parse_mode=None, link_preview=False)


async def _send_one(
    channel: dict,
    body_html: str,
    body_text: str,
    media_path: str | None,
    media_type: str | None,
) -> PublishResult:
    client = get_client()
    title = channel["title"] or "Untitled"
    if not channel["can_post"]:
        return PublishResult(title, False, "No permission to post.")
    if not client.is_connected():
        return PublishResult(title, False, "Personal account is not connected.")

    file_path = None
    if media_path:
        file_path = Path(media_path)
        if not file_path.is_absolute():
            file_path = BASE_DIR / media_path
        if not file_path.is_file():
            return PublishResult(title, False, "The saved media file is missing.")

    plain = (body_text or html_to_text(body_html)).strip()
    if file_path is None and not plain:
        return PublishResult(title, False, "Advertisement is empty.")

    peer = _peer(channel)
    file_kwargs = {
        "force_document": media_type == "document",
        "supports_streaming": media_type == "video",
    }
    try:
        if file_path is not None and plain and len(plain) <= 1024:
            if body_html:
                try:
                    await client.send_file(
                        peer,
                        file_path,
                        caption=body_html,
                        parse_mode="html",
                        **file_kwargs,
                    )
                    return PublishResult(title, True)
                except (
                    FloodWaitError,
                    ChatWriteForbiddenError,
                    ChatAdminRequiredError,
                    ChannelPrivateError,
                    UserBannedInChannelError,
                ):
                    raise
                except ValueError:
                    logger.exception("Formatted caption was rejected. Sending plain text.")
            await client.send_file(
                peer,
                file_path,
                caption=plain,
                parse_mode=None,
                **file_kwargs,
            )
            return PublishResult(title, True)
        if file_path is not None:
            await client.send_file(peer, file_path, parse_mode=None, **file_kwargs)
        if plain:
            try:
                await _send_text(peer, body_html, plain)
            except Exception as exc:
                if file_path is not None:
                    message, retry_after = _explain(exc)
                    return PublishResult(
                        title,
                        False,
                        f"The file was posted, but the text was not: {message}",
                        retry_after,
                        posted=True,
                    )
                raise
        return PublishResult(title, True)
    except Exception as exc:
        logger.exception("Publish failed for %s", title)
        message, retry_after = _explain(exc)
        return PublishResult(title, False, message, retry_after)


async def publish_to(ad_id: int, channel_ids: list[int]) -> list[PublishResult] | None:
    async with session_scope() as session:
        ad = await session.get(Ad, ad_id)
        if ad is None:
            return None
        body_html = ad.body_html or ""
        body_text = ad.body_text or ""
        media_path = ad.media_path
        media_type = ad.media_type
        found = []
        if channel_ids:
            found = list(
                await session.scalars(
                    select(Channel).where(Channel.telegram_id.in_(channel_ids))
                )
            )
        by_id = {row.telegram_id: row for row in found}

    results: list[PublishResult] = []
    ordered: list[dict] = []
    for telegram_id in channel_ids:
        row = by_id.get(int(telegram_id))
        if row is None:
            results.append(
                PublishResult(
                    str(telegram_id),
                    False,
                    "Channel is not in the saved list. Use /channels.",
                )
            )
            continue
        ordered.append(
            {
                "telegram_id": row.telegram_id,
                "access_hash": row.access_hash,
                "title": row.title,
                "can_post": row.can_post,
            }
        )

    for index, channel in enumerate(ordered):
        if index:
            await asyncio.sleep(1)
        results.append(
            await _send_one(channel, body_html, body_text, media_path, media_type)
        )
    return results
