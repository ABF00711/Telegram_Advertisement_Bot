from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import ADMIN_USER_ID


class AdminMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = data.get("event_from_user")
        if user is None or user.id != ADMIN_USER_ID:
            if isinstance(event, Message):
                await event.answer("Access denied.")
            elif isinstance(event, CallbackQuery):
                await event.answer("Access denied.", show_alert=True)
            return None

        if isinstance(event, Message) and event.chat.type != ChatType.PRIVATE:
            return None
        if isinstance(event, CallbackQuery):
            message = event.message
            if message is None or message.chat.type != ChatType.PRIVATE:
                await event.answer()
                return None

        return await handler(event, data)
