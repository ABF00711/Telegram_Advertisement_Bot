import logging
from datetime import datetime

from aiogram import Bot

from campaigns.manager import claim_due_schedules, finish_schedule, recover_interrupted
from campaigns.publisher import PublishResult, format_results, publish_to
from config import ADMIN_USER_ID, TIMEZONE
from scheduler.times import format_local

logger = logging.getLogger(__name__)

_bot: Bot | None = None
_scheduler = None


def set_bot(bot: Bot) -> None:
    global _bot
    _bot = bot


async def _notify(text: str) -> None:
    if _bot is None:
        logger.info("Schedule notice: %s", text)
        return
    try:
        await _bot.send_message(ADMIN_USER_ID, text[:4000])
    except Exception:
        logger.exception("Could not notify the admin")


def _summary(schedule: dict, results, outcome: dict) -> str:
    lines = [
        f"Schedule #{schedule['id']} for ad #{schedule['ad_id']} ({schedule['preview']})",
        format_results(results),
    ]
    status = outcome.get("status")
    next_run = outcome.get("next_run")
    if status == "active" and isinstance(next_run, datetime):
        lines.append(f"Next run: {format_local(next_run)} ({TIMEZONE})")
    elif status == "completed":
        lines.append("This one-time schedule is finished.")
    elif status == "waiting" and isinstance(next_run, datetime):
        lines.append(f"Telegram asked for a wait. Next try: {format_local(next_run)} ({TIMEZONE})")
    elif status == "retry" and isinstance(next_run, datetime):
        lines.append(
            f"Attempt {outcome.get('attempts')} failed. Next try: {format_local(next_run)} ({TIMEZONE})"
        )
    elif status == "failed":
        lines.append("This schedule failed three times and will not run again.")
    elif status == "cancelled":
        lines.append("This schedule was cancelled while that attempt was running.")
    return "\n".join(lines)


async def process_due() -> None:
    try:
        claimed = await claim_due_schedules()
    except Exception:
        logger.exception("Could not read due schedules")
        return

    for schedule in claimed:
        try:
            results = await publish_to(schedule["ad_id"], schedule["channel_ids"])
        except Exception:
            logger.exception("Schedule %s failed", schedule["id"])
            results = [
                PublishResult(schedule["preview"], False, "Unexpected error while posting.")
            ]
        if results is None:
            results = [
                PublishResult(schedule["preview"], False, "Advertisement was deleted.")
            ]
        try:
            outcome = await finish_schedule(schedule["id"], results)
        except Exception:
            logger.exception("Could not record schedule %s", schedule["id"])
            await _notify(
                f"Schedule #{schedule['id']} ran, but the result could not be saved. See logs/app.log."
            )
            continue
        await _notify(_summary(schedule, results, outcome))


async def start_scheduler():
    global _scheduler
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    await recover_interrupted()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        process_due,
        "interval",
        seconds=15,
        id="process_due",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("Scheduler started")
    return scheduler


def shutdown_scheduler() -> None:
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
