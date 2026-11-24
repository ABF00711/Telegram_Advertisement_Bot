from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def _label(text: str, limit: int = 40) -> str:
    cleaned = (text or "").replace("\n", " ").strip() or "Untitled"
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def pick_ad_keyboard(ads: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for ad in ads:
        builder.button(
            text=f"#{ad['id']} {_label(ad['preview'])}",
            callback_data=f"use:{ad['id']}",
        )
    builder.button(text="Cancel", callback_data="flow:cancel")
    builder.adjust(1)
    return builder.as_markup()


def manage_ad_keyboard(ads: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for ad in ads:
        builder.button(
            text=f"#{ad['id']} {_label(ad['preview'], 32)}",
            callback_data=f"ad:{ad['id']}",
        )
    builder.adjust(1)
    return builder.as_markup()


def ad_actions_keyboard(ad_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Post now", callback_data=f"quick:now:{ad_id}")
    builder.button(text="Schedule", callback_data=f"quick:later:{ad_id}")
    builder.button(text="Delete", callback_data=f"del:{ad_id}")
    builder.adjust(2, 1)
    return builder.as_markup()


def confirm_delete_keyboard(ad_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Delete", callback_data=f"delok:{ad_id}")
    builder.button(text="Keep", callback_data=f"ad:{ad_id}")
    builder.adjust(2)
    return builder.as_markup()


def saved_ad_keyboard(ad_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Post now", callback_data=f"quick:now:{ad_id}")
    builder.button(text="Schedule", callback_data=f"quick:later:{ad_id}")
    builder.adjust(2)
    return builder.as_markup()


def channels_keyboard(channels: list[dict], selected: set[int]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for channel in channels:
        telegram_id = int(channel["telegram_id"])
        mark = "✓ " if telegram_id in selected else ""
        builder.button(
            text=f"{mark}{_label(channel['title'])}",
            callback_data=f"ch:{telegram_id}",
        )
    builder.button(text="Done", callback_data="ch:done")
    builder.button(text="Cancel", callback_data="flow:cancel")
    builder.adjust(1)
    return builder.as_markup()


def repeat_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Once", callback_data="repeat:once")
    builder.button(text="Every day", callback_data="repeat:daily")
    builder.button(text="Cancel", callback_data="flow:cancel")
    builder.adjust(2, 1)
    return builder.as_markup()


def schedules_keyboard(schedules: list[dict]) -> InlineKeyboardMarkup | None:
    if not schedules:
        return None
    builder = InlineKeyboardBuilder()
    for item in schedules:
        builder.button(
            text=f"Cancel #{item['id']}",
            callback_data=f"schedcancel:{item['id']}",
        )
    builder.adjust(2)
    return builder.as_markup()
