import logging

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
from locales import t

BOT_USERNAME = ""


def sub_kb(lang: str, missing: list[str]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{t(lang, 'subscribe')} {ch}", url=f"https://t.me/{ch.lstrip('@')}")]
        for ch in missing
    ]
    rows.append([InlineKeyboardButton(text=t(lang, "check"), callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def missing_channels(bot: Bot, user_id: int) -> list[str]:
    missing = []
    for ch in config.CHANNELS:
        try:
            m = await bot.get_chat_member(ch, user_id)
            if m.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
                missing.append(ch)
        except Exception as e:
            logging.warning("Obunani tekshirib bo'lmadi (%s): %s", ch, e)
    return missing


async def gate(bot: Bot, user_id: int, lang: str, msg: Message) -> bool:
    """Obuna bo'lsa True, bo'lmasa obuna xabarini yuboradi va False qaytaradi."""
    missing = await missing_channels(bot, user_id)
    if missing:
        await msg.answer(t(lang, "sub_required"), reply_markup=sub_kb(lang, missing))
        return False
    return True
