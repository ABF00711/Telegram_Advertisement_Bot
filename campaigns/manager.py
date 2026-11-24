import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from config import BASE_DIR
from database.database import session_scope, utcnow
from database.models import Ad, Channel, ScheduledPost

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


def remove_media(relative: str | None) -> None:
    if not relative:
        return
    path = Path(relative)
    if not path.is_absolute():
        path = BASE_DIR / relative
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.exception("Could not delete media %s", path)


def _preview(body_text: str, media_type: str | None) -> str:
    stripped = body_text.strip()
    if stripped:
        line = stripped.splitlines()[0].strip()
        return line[:117] + "..." if len(line) > 120 else line
    label = media_type or "media"
    return f"({label})"


def _ad_dict(ad: Ad) -> dict:
    return {
        "id": ad.id,
        "preview": ad.preview,
        "media_type": ad.media_type,
        "created_at": ad.created_at,
    }


def _channel_dict(channel: Channel) -> dict:
    return {
        "telegram_id": channel.telegram_id,
        "title": channel.title,
        "username": channel.username,
        "can_post": channel.can_post,
    }


async def create_ad(
    body_html: str,
    body_text: str,
    media_path: str | None,
    media_type: str | None,
) -> dict:
    plain = (body_text or "").strip()
    if len(plain) > 4096:
        raise ValueError("Text is longer than Telegram allows (4096 characters).")
    if media_path and len(plain) > 1024:
        raise ValueError(
            "A file caption can be at most 1024 characters. Shorten it, or send the text without a file."
        )
    if not plain and not media_path:
        raise ValueError("The advertisement is empty.")

    async with session_scope() as session:
        ad = Ad(
            preview=_preview(plain, media_type),
            body_text=plain,
            body_html=body_html or "",
            media_path=media_path,
            media_type=media_type,
        )
        session.add(ad)
        await session.flush()
        return _ad_dict(ad)


async def list_ads(limit: int = 20) -> list[dict]:
    async with session_scope() as session:
        rows = list(
            await session.scalars(select(Ad).order_by(Ad.id.desc()).limit(limit))
        )
        return [_ad_dict(row) for row in rows]


async def count_ads() -> int:
    async with session_scope() as session:
        return int(await session.scalar(select(func.count()).select_from(Ad)) or 0)


async def get_ad(ad_id: int) -> dict | None:
    async with session_scope() as session:
        ad = await session.get(Ad, ad_id)
        if ad is None:
            return None
        return _ad_dict(ad)


async def delete_ad(ad_id: int) -> str:
    async with session_scope() as session:
        ad = await session.get(Ad, ad_id)
        if ad is None:
            return "missing"
        active = await session.scalar(
            select(func.count())
            .select_from(ScheduledPost)
            .where(
                ScheduledPost.ad_id == ad_id,
                ScheduledPost.status.in_(("active", "running")),
            )
        )
        if active:
            return "scheduled"
        media = ad.media_path
        await session.delete(ad)
    remove_media(media)
    return "ok"


async def list_channels() -> list[dict]:
    async with session_scope() as session:
        rows = list(await session.scalars(select(Channel).order_by(Channel.title)))
        return [_channel_dict(row) for row in rows]


async def list_postable_channels() -> list[dict]:
    channels = await list_channels()
    # return [channel for channel in channels if channel["can_post"]]
    return channels


async def create_schedule(
    ad_id: int,
    channel_ids: list[int],
    run_at: datetime,
    repeat: str,
) -> int | None:
    if repeat not in {"once", "daily"}:
        raise ValueError("Repeat must be once or daily.")
    if not channel_ids:
        raise ValueError("Choose at least one channel.")

    async with session_scope() as session:
        ad = await session.get(Ad, ad_id)
        if ad is None:
            return None
        schedule = ScheduledPost(
            ad_id=ad_id,
            channel_ids=json.dumps([int(channel_id) for channel_id in channel_ids]),
            run_at=run_at,
            repeat=repeat,
            status="active",
        )
        session.add(schedule)
        await session.flush()
        return schedule.id


async def cancel_schedule(schedule_id: int) -> bool:
    async with session_scope() as session:
        schedule = await session.get(ScheduledPost, schedule_id)
        if schedule is None or schedule.status not in {"active", "running"}:
            return False
        schedule.status = "cancelled"
        return True


async def list_schedule_view(active_limit: int = 20, failed_limit: int = 5) -> dict:
    async with session_scope() as session:
        titles = {
            row.telegram_id: row.title
            for row in await session.scalars(select(Channel))
        }
        ads = {row.id: row.preview for row in await session.scalars(select(Ad))}
        active_rows = list(
            await session.scalars(
                select(ScheduledPost)
                .where(ScheduledPost.status == "active")
                .order_by(ScheduledPost.run_at)
                .limit(active_limit)
            )
        )
        failed_rows = list(
            await session.scalars(
                select(ScheduledPost)
                .where(ScheduledPost.status == "failed")
                .order_by(ScheduledPost.id.desc())
                .limit(failed_limit)
            )
        )

    def pack(row: ScheduledPost) -> dict:
        try:
            ids = json.loads(row.channel_ids)
        except json.JSONDecodeError:
            ids = []
        return {
            "id": row.id,
            "ad_id": row.ad_id,
            "preview": ads.get(row.ad_id, "Deleted ad"),
            "run_at": row.run_at,
            "repeat": row.repeat,
            "channels": [titles.get(int(channel_id), str(channel_id)) for channel_id in ids],
            "last_error": row.last_error,
            "status": row.status,
        }

    return {
        "active": [pack(row) for row in active_rows],
        "failed": [pack(row) for row in failed_rows],
    }


async def stats() -> dict:
    async with session_scope() as session:
        ads = int(await session.scalar(select(func.count()).select_from(Ad)) or 0)
        channels = int(
            await session.scalar(select(func.count()).select_from(Channel)) or 0
        )
        postable = int(
            await session.scalar(
                select(func.count()).select_from(Channel).where(Channel.can_post.is_(True))
            )
            or 0
        )
        active = int(
            await session.scalar(
                select(func.count())
                .select_from(ScheduledPost)
                .where(ScheduledPost.status == "active")
            )
            or 0
        )
        failed = int(
            await session.scalar(
                select(func.count())
                .select_from(ScheduledPost)
                .where(ScheduledPost.status == "failed")
            )
            or 0
        )
        next_run = await session.scalar(
            select(ScheduledPost.run_at)
            .where(ScheduledPost.status == "active")
            .order_by(ScheduledPost.run_at)
            .limit(1)
        )
    return {
        "ads": ads,
        "channels": channels,
        "postable": postable,
        "active": active,
        "failed": failed,
        "next_run": next_run,
    }


def next_daily_run(run_at: datetime, now: datetime) -> datetime:
    nxt = run_at + timedelta(days=1)
    while nxt <= now:
        nxt += timedelta(days=1)
    return nxt


async def finish_schedule(schedule_id: int, results) -> dict:
    """Update a schedule after a publish attempt. Returns a short summary."""
    now = utcnow()
    sent = sum(1 for result in results if result.ok)
    errors = [result for result in results if not result.ok]
    error_text = None
    if errors:
        error_text = "; ".join(f"{result.title}: {result.error}" for result in errors)
        if len(error_text) > 1000:
            error_text = error_text[:1000]

    async with session_scope() as session:
        schedule = await session.get(ScheduledPost, schedule_id)
        if schedule is None:
            return {"status": "missing", "next_run": None}
        schedule.last_run_at = now
        if not results and not error_text:
            error_text = "Nothing was sent."
        schedule.last_error = error_text

        if schedule.status == "cancelled":
            return {"status": "cancelled", "next_run": None}
        if schedule.status not in {"running", "active"}:
            return {"status": schedule.status, "next_run": None}

        landed = sent or any(getattr(result, "posted", False) for result in results)
        if landed:
            schedule.attempts = 0
            if schedule.repeat == "daily":
                schedule.status = "active"
                schedule.run_at = next_daily_run(schedule.run_at, now)
            else:
                schedule.status = "completed"
            return {"status": schedule.status, "next_run": schedule.run_at if schedule.repeat == "daily" else None}

        retry_after = max(
            (result.retry_after or 0 for result in errors),
            default=0,
        )
        if retry_after:
            schedule.status = "active"
            schedule.run_at = now + timedelta(seconds=retry_after + 2)
            return {"status": "waiting", "next_run": schedule.run_at}

        schedule.attempts += 1
        if schedule.attempts >= MAX_ATTEMPTS:
            schedule.status = "failed"
            return {"status": "failed", "next_run": None}
        schedule.status = "active"
        schedule.run_at = now + timedelta(minutes=5)
        return {"status": "retry", "next_run": schedule.run_at, "attempts": schedule.attempts}


async def claim_due_schedules() -> list[dict]:
    now = utcnow()
    async with session_scope() as session:
        rows = list(
            await session.scalars(
                select(ScheduledPost)
                .where(
                    ScheduledPost.status == "active",
                    ScheduledPost.run_at <= now,
                )
                .order_by(ScheduledPost.run_at)
            )
        )
        claimed = []
        for row in rows:
            ad = await session.get(Ad, row.ad_id)
            if ad is None:
                row.status = "failed"
                row.last_error = "Advertisement was deleted."
                continue
            try:
                channel_ids = [int(channel_id) for channel_id in json.loads(row.channel_ids)]
            except (TypeError, ValueError, json.JSONDecodeError):
                channel_ids = []
            row.status = "running"
            claimed.append(
                {
                    "id": row.id,
                    "ad_id": row.ad_id,
                    "channel_ids": channel_ids,
                    "repeat": row.repeat,
                    "preview": ad.preview,
                }
            )
        return claimed


async def recover_interrupted() -> None:
    async with session_scope() as session:
        rows = list(
            await session.scalars(
                select(ScheduledPost).where(ScheduledPost.status == "running")
            )
        )
        for row in rows:
            row.status = "active"
            row.last_error = "The previous attempt was interrupted. It will run again."
    if rows:
        logger.warning("Returned %s interrupted schedules to the queue", len(rows))
