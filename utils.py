import logging
import re

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
from locales import t

BOT_USERNAME = ""

_QUALITY_RE = re.compile(r"\b(2160|1080|720|480|360)\s*p\b", re.I)
_EP_PATTERNS = [
    re.compile(r"s\d{1,2}\s*e(\d{1,4})", re.I),
    re.compile(r"\b(\d{1,4})\s*-?\s*(?:qism|seriya|серия|серии|эпизод|episode|ep)\b", re.I),
    re.compile(r"\b(?:qism|seriya|серия|эпизод|episode|ep|e)\s*[:#.\-]?\s*(\d{1,4})\b", re.I),
]


def detect_quality(caption: str, width: int, height: int) -> str:
    """Avval video o'lchamidan, bo'lmasa izohdan sifatni aniqlaydi."""
    size = max(width or 0, height or 0)
    if size:
        if size >= 3200:
            return "2160"
        if size >= 1700:
            return "1080"
        if size >= 1100:
            return "720"
        if size >= 700:
            return "480"
        return "360"
    caption = caption or ""
    m = _QUALITY_RE.search(caption)
    if m:
        return m.group(1)
    if re.search(r"\b4k\b", caption, re.I):
        return "2160"
    return "HD"


def detect_episode(caption: str):
    for pattern in _EP_PATTERNS:
        m = pattern.search(caption or "")
        if m:
            return int(m.group(1))
    return None


def q_label(q: str) -> str:
    if q == "2160":
        return "4K"
    return f"{q}p" if q.isdigit() else q


def q_key(q: str) -> int:
    return int(q) if q.isdigit() else 0


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
