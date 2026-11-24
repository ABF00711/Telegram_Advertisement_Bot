import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ErrorEvent, Message

from bot.keyboards import (
    ad_actions_keyboard,
    channels_keyboard,
    confirm_delete_keyboard,
    manage_ad_keyboard,
    pick_ad_keyboard,
    repeat_keyboard,
    saved_ad_keyboard,
    schedules_keyboard,
)
from bot.media import MediaTooLarge, save_message_media
from bot.middleware import AdminMiddleware
from bot.states import Compose, NewAd
from campaigns.manager import (
    cancel_schedule,
    count_ads,
    create_ad,
    create_schedule,
    delete_ad,
    get_ad,
    list_ads,
    list_channels,
    list_postable_channels,
    list_schedule_view,
    remove_media,
    stats,
)
from campaigns.publisher import format_results, publish_to
from config import TIMEZONE
from database.database import utcnow
from scheduler.times import format_local, parse_when, time_help, to_utc_naive
from telegram import user_client
from telegram.channel_manager import sync_channels

logger = logging.getLogger(__name__)

router = Router(name="admin")
router.message.middleware(AdminMiddleware())
router.callback_query.middleware(AdminMiddleware())


def channel_prompt(mode: str, count: int) -> str:
    action = "post now" if mode == "now" else "schedule"
    return (
        f"Choose the channels for this {action}.\n"
        f"Selected: {count}\n"
        "Tap a channel to toggle it, then tap Done."
    )


async def safe_edit(message, text: str, markup=None) -> None:
    if message is None or not hasattr(message, "edit_text"):
        return
    try:
        await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        if hasattr(message, "answer"):
            await message.answer(text, reply_markup=markup)
            return
        raise


async def send_blocks(message: Message, text: str) -> None:
    block = ""
    parts = text.split("\n\n")
    for index, part in enumerate(parts):
        piece = part if index == len(parts) - 1 else part + "\n\n"
        if block and len(block) + len(piece) > 3500:
            await message.answer(block.strip())
            block = piece
        else:
            block += piece
    if block.strip():
        await message.answer(block.strip())


def schedule_text(view: dict) -> str:
    lines = ["Schedules", ""]
    if not view["active"]:
        lines.append("No active schedules.")
    else:
        lines.append("Active")
        for item in view["active"]:
            names = ", ".join(item["channels"]) or "No channels"
            repeat = "every day" if item["repeat"] == "daily" else "once"
            lines.append(
                f"#{item['id']} | ad #{item['ad_id']} | {repeat}\n"
                f"{format_local(item['run_at'])} ({TIMEZONE})\n"
                f"{item['preview']}\n"
                f"{names}"
            )
            if item["last_error"]:
                lines.append(f"Last problem: {item['last_error']}")
            lines.append("")
    if view["failed"]:
        lines.append("Recent failures")
        for item in view["failed"]:
            lines.append(
                f"#{item['id']} | ad #{item['ad_id']}: {item['last_error'] or 'failed'}"
            )
    text = "\n".join(lines).strip()
    return text if len(text) <= 3500 else text[:3490] + "\n..."


async def show_schedules(message: Message, edit: bool = False) -> None:
    view = await list_schedule_view()
    text = schedule_text(view)
    markup = schedules_keyboard(view["active"])
    if edit:
        await safe_edit(message, text, markup)
    else:
        await message.answer(text, reply_markup=markup)


async def begin_channel_choice(message, state: FSMContext, mode: str, ad_id: int) -> None:
    ad = await get_ad(ad_id)
    if ad is None:
        await state.clear()
        await safe_edit(message, "That advertisement no longer exists.")
        return
    channels = await list_postable_channels()
    if not channels:
        await state.clear()
        await safe_edit(
            message,
            "No channels where this account can post.\n"
            "Give it permission to post messages, then use /channels.",
        )
        return
    await state.set_state(Compose.choosing_channels)
    await state.update_data(mode=mode, ad_id=ad_id, selected=[])
    await safe_edit(message, channel_prompt(mode, 0), channels_keyboard(channels, set()))


@router.message(Command("start", "help"))
async def start_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Telegram Ad Automation\n\n"
        "This bot saves advertisements and publishes them on channels "
        "where your personal account can post.\n\n"
        "/newad - save an advertisement\n"
        "/ads - review or delete advertisements\n"
        "/post - publish now\n"
        "/schedule - choose a time\n"
        "/schedules - view or cancel the queue\n"
        "/channels - refresh your channels\n"
        "/status - connection and queue\n"
        "/cancel - stop the current step\n\n"
        f"Times use {TIMEZONE}. The scheduler runs only while this app is open."
    )


@router.message(Command("cancel"))
async def cancel_handler(message: Message, state: FSMContext):
    current = await state.get_state()
    await state.clear()
    if current is None:
        await message.answer("Nothing to cancel.")
    else:
        await message.answer("Cancelled.")


@router.message(Command("channels"))
async def channels_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Fetching your Telegram channels...")
    try:
        await sync_channels()
        channels = await list_channels()
    except Exception:
        logger.exception("Channel refresh failed")
        await message.answer("Unable to retrieve channels. Check logs/app.log.")
        return

    if not channels:
        account = user_client.account_name or "the signed-in account"
        await message.answer(
            f"No broadcast channels found for {account}.\n"
            "Archived channels are included. Groups are not.\n"
            "The channels must be in this personal account's chat list."
        )
        return

    lines = [
        "Channel overview",
        "",
        f"Total channels: {len(channels)}",
        "",
    ]
    for channel in channels:
        username = f"@{channel['username']}" if channel["username"] else "Private channel"
        lines.append(f"{channel['title']}\n{username}")
        lines.append("")
    await send_blocks(message, "\n".join(lines).strip())


@router.message(Command("status"))
async def status_handler(message: Message, state: FSMContext):
    await state.clear()
    info = await stats()
    if user_client.client.is_connected() and user_client.account_name:
        account = f"{user_client.account_name} ({user_client.account_id})"
    else:
        account = "not connected"
    lines = [
        "System status",
        "",
        "Management bot: running",
        f"Personal account: {account}",
        f"Channels you can post to: {info['postable']} of {info['channels']}",
        f"Advertisements: {info['ads']}",
        f"Active schedules: {info['active']}",
    ]
    if info["failed"]:
        lines.append(f"Failed schedules: {info['failed']}")
    if info["next_run"] is not None:
        lines.append(f"Next post: {format_local(info['next_run'])} ({TIMEZONE})")
    else:
        lines.append("Next post: none")
    await message.answer("\n".join(lines))


@router.message(Command("newad"))
async def new_ad_handler(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(NewAd.content)
    await message.answer(
        "Send the advertisement as it should appear.\n"
        "Text, or one photo, video, GIF, or file. A caption is included.\n"
        "/cancel to stop."
    )


@router.message(Command("ads"))
async def ads_handler(message: Message, state: FSMContext):
    await state.clear()
    ads = await list_ads()
    total = await count_ads()
    if not ads:
        await message.answer("No advertisements yet. Use /newad.")
        return
    header = f"Advertisements ({total})"
    if total > len(ads):
        header += f"\nShowing the latest {len(ads)}."
    await message.answer(header, reply_markup=manage_ad_keyboard(ads))


@router.message(Command("post", "schedule"))
async def pick_for_publish(message: Message, state: FSMContext, command: CommandObject):
    mode = "schedule" if command.command == "schedule" else "now"
    ads = await list_ads()
    if not ads:
        await state.clear()
        await message.answer("No advertisements yet. Use /newad.")
        return
    await state.clear()
    await state.set_state(Compose.picking_ad)
    await state.update_data(mode=mode, selected=[])
    title = (
        "Choose an advertisement to schedule."
        if mode == "schedule"
        else "Choose an advertisement to post now."
    )
    await message.answer(title, reply_markup=pick_ad_keyboard(ads))


@router.message(Command("schedules"))
async def schedules_handler(message: Message, state: FSMContext):
    await state.clear()
    await show_schedules(message)


@router.message(NewAd.content, F.media_group_id)
async def reject_album(message: Message):
    await message.answer("Send one photo or video, not an album.")


@router.message(NewAd.content, F.photo | F.video | F.animation | F.document | F.text)
async def capture_ad(message: Message, state: FSMContext, bot):
    if message.text and message.text.startswith("/"):
        await message.answer("Send the advertisement, or /cancel.")
        return

    body_text = message.text or message.caption or ""
    body_html = message.html_text or ""
    if len(body_text) > 4096:
        await message.answer("That text is longer than Telegram allows (4096 characters).")
        return

    media_path = None
    media_type = None
    if message.photo or message.video or message.animation or message.document:
        try:
            media_path, media_type = await save_message_media(bot, message)
        except MediaTooLarge:
            await message.answer(
                "That file is too large. The bot can download files up to 20 MB."
            )
            return
        except Exception:
            logger.exception("Could not save advertisement media")
            await message.answer("I could not save that file. Try a smaller one.")
            return

    try:
        ad = await create_ad(body_html, body_text, media_path, media_type)
    except ValueError as exc:
        remove_media(media_path)
        await message.answer(str(exc))
        return
    except Exception:
        remove_media(media_path)
        logger.exception("Could not store advertisement")
        await message.answer("I could not store that advertisement. Check logs/app.log.")
        return

    await state.clear()
    kind = ad["media_type"] or "text"
    await message.answer(
        f"Saved advertisement #{ad['id']} ({kind}).\n{ad['preview']}",
        reply_markup=saved_ad_keyboard(ad["id"]),
    )


@router.message(NewAd.content)
async def capture_ad_unsupported(message: Message):
    await message.answer("Send text, a photo, a video, a GIF, or a file. /cancel to stop.")


@router.message(Compose.picking_ad)
async def remind_pick(message: Message):
    await message.answer("Tap one of the advertisements above, or /cancel.")


@router.message(Compose.choosing_channels)
async def remind_channels(message: Message):
    await message.answer("Tap the channel buttons, then Done. /cancel to stop.")


@router.message(Compose.choosing_time, F.text)
async def capture_time(message: Message, state: FSMContext):
    try:
        when = parse_when(message.text or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return
    run_at = to_utc_naive(when)
    if run_at <= utcnow():
        await message.answer("That time has already passed.\n" + time_help())
        return
    await state.update_data(run_at=run_at.isoformat(timespec="seconds"))
    await state.set_state(Compose.choosing_repeat)
    await message.answer(
        f"Post at {format_local(run_at)} ({TIMEZONE}).\nHow often?",
        reply_markup=repeat_keyboard(),
    )


@router.message(Compose.choosing_time)
async def remind_time(message: Message):
    await message.answer(time_help())


@router.message(Compose.choosing_repeat)
async def remind_repeat(message: Message):
    await message.answer("Tap Once or Every day. /cancel to stop.")


@router.callback_query(F.data == "flow:cancel")
async def flow_cancel(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await query.answer("Cancelled.")
    await safe_edit(query.message, "Cancelled.")


@router.callback_query(F.data.startswith("ad:"))
async def open_ad(query: CallbackQuery):
    try:
        ad_id = int(query.data.split(":", 1)[1])
    except (TypeError, ValueError):
        await query.answer()
        return
    ad = await get_ad(ad_id)
    if ad is None:
        await query.answer("That advertisement no longer exists.", show_alert=True)
        return
    kind = ad["media_type"] or "text"
    await query.answer()
    await safe_edit(
        query.message,
        f"Advertisement #{ad['id']} ({kind})\n{ad['preview']}",
        ad_actions_keyboard(ad["id"]),
    )


@router.callback_query(F.data.startswith("del:"))
async def ask_delete(query: CallbackQuery):
    try:
        ad_id = int(query.data.split(":", 1)[1])
    except (TypeError, ValueError):
        await query.answer()
        return
    ad = await get_ad(ad_id)
    if ad is None:
        await query.answer("That advertisement no longer exists.", show_alert=True)
        return
    await query.answer()
    await safe_edit(
        query.message,
        f"Delete advertisement #{ad_id}?\n"
        "Posts already published stay in the channels.\n"
        "Cancel active schedules before deleting.",
        confirm_delete_keyboard(ad_id),
    )


@router.callback_query(F.data.startswith("delok:"))
async def confirm_delete(query: CallbackQuery):
    try:
        ad_id = int(query.data.split(":", 1)[1])
    except (TypeError, ValueError):
        await query.answer()
        return
    result = await delete_ad(ad_id)
    if result == "scheduled":
        await query.answer("Cancel its active schedules first.", show_alert=True)
        return
    if result == "missing":
        await query.answer("That advertisement no longer exists.", show_alert=True)
        return
    await query.answer("Deleted.")
    ads = await list_ads()
    if not ads:
        await safe_edit(query.message, "Advertisement deleted. You have none left.")
        return
    await safe_edit(query.message, "Advertisement deleted.", manage_ad_keyboard(ads))


@router.callback_query(F.data.startswith("quick:"))
async def quick_publish(query: CallbackQuery, state: FSMContext):
    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[1] not in {"now", "later"}:
        await query.answer()
        return
    try:
        ad_id = int(parts[2])
    except ValueError:
        await query.answer()
        return
    mode = "now" if parts[1] == "now" else "schedule"
    if await get_ad(ad_id) is None:
        await query.answer("That advertisement no longer exists.", show_alert=True)
        return
    await query.answer()
    await begin_channel_choice(query.message, state, mode, ad_id)


@router.callback_query(Compose.picking_ad, F.data.startswith("use:"))
async def use_ad(query: CallbackQuery, state: FSMContext):
    try:
        ad_id = int((query.data or "").split(":", 1)[1])
    except (TypeError, ValueError):
        await query.answer()
        return
    data = await state.get_data()
    mode = data.get("mode") or "now"
    await query.answer()
    await begin_channel_choice(query.message, state, mode, ad_id)


@router.callback_query(Compose.choosing_channels, F.data.startswith("ch:"))
async def toggle_channel(query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    mode = data.get("mode") or "now"
    ad_id = data.get("ad_id")
    selected = {int(item) for item in data.get("selected") or []}
    token = (query.data or "").split(":", 1)[1]

    channels = await list_postable_channels()
    allowed = {int(channel["telegram_id"]) for channel in channels}

    if token == "done":
        selected &= allowed
        if not selected:
            await query.answer("Select at least one channel.", show_alert=True)
            return
        if mode == "now":
            await query.answer()
            await state.clear()
            await safe_edit(query.message, "Posting...")
            results = await publish_to(int(ad_id), sorted(selected))
            if results is None:
                await safe_edit(query.message, "That advertisement no longer exists.")
                return
            await safe_edit(query.message, format_results(results))
            return

        await state.update_data(selected=sorted(selected))
        await state.set_state(Compose.choosing_time)
        await query.answer()
        await safe_edit(query.message, "When should it post?\n\n" + time_help())
        return

    try:
        telegram_id = int(token)
    except ValueError:
        await query.answer()
        return
    if telegram_id not in allowed:
        await query.answer("That channel cannot be posted to.", show_alert=True)
        return
    if telegram_id in selected:
        selected.remove(telegram_id)
    else:
        selected.add(telegram_id)
    await state.update_data(selected=sorted(selected))
    await query.answer()
    await safe_edit(
        query.message,
        channel_prompt(mode, len(selected)),
        channels_keyboard(channels, selected),
    )


@router.callback_query(Compose.choosing_repeat, F.data.startswith("repeat:"))
async def choose_repeat(query: CallbackQuery, state: FSMContext):
    repeat = (query.data or "").split(":", 1)[1]
    if repeat not in {"once", "daily"}:
        await query.answer()
        return
    data = await state.get_data()
    try:
        ad_id = int(data["ad_id"])
        selected = [int(item) for item in data.get("selected") or []]
        run_at = datetime.fromisoformat(data["run_at"])
    except (KeyError, TypeError, ValueError):
        await state.clear()
        await query.answer("This schedule expired. Use /schedule again.", show_alert=True)
        return

    schedule_id = await create_schedule(ad_id, selected, run_at, repeat)
    await state.clear()
    if schedule_id is None:
        await query.answer("That advertisement no longer exists.", show_alert=True)
        await safe_edit(query.message, "That advertisement no longer exists.")
        return

    cadence = "once" if repeat == "once" else "every day"
    await query.answer("Scheduled.")
    await safe_edit(
        query.message,
        f"Schedule #{schedule_id} saved.\n"
        f"It will post {cadence} at {format_local(run_at)} ({TIMEZONE}).\n"
        "The queue is checked every 15 seconds while this app is running.\n"
        "A daily post that was missed while the app was closed is sent once, then continues from the next day.",
    )


@router.callback_query(F.data.startswith("schedcancel:"))
async def cancel_scheduled(query: CallbackQuery):
    try:
        schedule_id = int((query.data or "").split(":", 1)[1])
    except (TypeError, ValueError):
        await query.answer()
        return
    cancelled = await cancel_schedule(schedule_id)
    if not cancelled:
        await query.answer("That schedule is no longer active.", show_alert=True)
    else:
        await query.answer("Cancelled.")
    await show_schedules(query.message, edit=True)


@router.callback_query()
async def expired_button(query: CallbackQuery):
    await query.answer("That button has expired. Open the menu again.", show_alert=True)


@router.error()
async def on_error(event: ErrorEvent):
    logger.exception("Update failed", exc_info=event.exception)
    update = event.update
    notice = "Something went wrong. Check logs/app.log."
    if update.callback_query:
        try:
            await update.callback_query.answer(notice, show_alert=True)
        except Exception:
            logger.exception("Could not answer the failed callback")
    elif update.message:
        try:
            await update.message.answer(notice)
        except Exception:
            logger.exception("Could not report the handler error")
