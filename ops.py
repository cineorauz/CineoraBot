import asyncio

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

import ai


class AiFlagGuard(BaseMiddleware):
    """Foydalanuvchi boshqa tugma yoki buyruq bossa, «AI uchun yozish» rejimi o'chadi (oddiy matn qidiruv bo'lib qoladi)."""

    async def __call__(self, handler, event, data):
        if isinstance(event, CallbackQuery):
            if not (event.data or "").startswith("ai:"):
                ai.cancel(event.from_user.id)
        elif isinstance(event, Message) and (event.text or "").startswith("/"):
            ai.cancel(event.from_user.id)
        return await handler(event, data)


def attach(dp):
    """bot.py chaqiradi: routerlar movies.router dan oldin ulanadi."""
    dp.callback_query.outer_middleware(AiFlagGuard())
    dp.message.outer_middleware(AiFlagGuard())
    dp.include_router(ai.router)


def start(bot):
    """bot.py chaqiradi: fon vazifalari va jadvallar."""
    asyncio.create_task(ai.init())
