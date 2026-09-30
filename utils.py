import logging
import re

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

import config
from locales import LANGS, t

BOT_USERNAME = ""
LANG_PROMPT = "🌐 Tilni tanlang / Choose language / Выберите язык"

QUALITY_ORDER = ["2160", "1080", "720", "480", "360"]

_QUALITY_RE = re.compile(r"\b(2160|1080|720|480|360)\s*p\b", re.I)
_EP_PATTERNS = [
    re.compile(r"s\d{1,2}\s*e(\d{1,4})", re.I),
    re.compile(r"\b(\d{1,4})\s*-?\s*(?:qism|seriya|серия|серии|эпизод|episode|ep)\b", re.I),
    re.compile(r"\b(?:qism|seriya|серия|эпизод|episode|ep|e)\s*[:#.\-]?\s*(\d{1,4})\b", re.I),
]


# ---------------- sifat va qism aniqlash ----------------
def quality_from_caption(caption: str):
    caption = caption or ""
    m = _QUALITY_RE.search(caption)
    if m:
        return m.group(1)
    if re.search(r"\b4k\b", caption, re.I):
        return "2160"
    return None


def quality_from_size(width: int, height: int):
    size = max(width or 0, height or 0)
    if not size:
        return None
    if size >= 3200:
        return "2160"
    if size >= 1700:
        return "1080"
    if size >= 1100:
        return "720"
    if size >= 700:
        return "480"
    return "360"


def resolve_quality(by_caption, by_size, taken: set):
    """(sifat, izoh) qaytaradi. `taken` — shu qismning shu sessiyada band sifatlari."""
    primary = by_caption or by_size or "HD"
    if primary not in taken:
        return primary, None
    if by_size and by_size not in taken:
        return by_size, (
            f"izohda {q_label(primary)} yozilgan, lekin u band. "
            f"Video o'lchamiga ko'ra {q_label(by_size)} deb belgilandi"
        )
    if primary in QUALITY_ORDER:
        for cand in QUALITY_ORDER[QUALITY_ORDER.index(primary) + 1 :]:
            if cand not in taken:
                return cand, f"{q_label(primary)} band edi, shuning uchun {q_label(cand)} deb belgilandi"
    return primary, f"{q_label(primary)} qayta yuklandi (eskisi almashtirildi)"


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


def short_num(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{round(n / 1_000)}K"
    return str(n)


# ---------------- klaviaturalar ----------------
def lang_kb(code: str = "") -> InlineKeyboardMarkup:
    suffix = f":{code}" if code else ""
    rows = [
        [InlineKeyboardButton(text=name, callback_data=f"lang:{c}{suffix}")]
        for c, name in LANGS.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def menu_kb(lang: str) -> ReplyKeyboardMarkup:
    layout = [
        ["m_search", "m_random"],
        ["m_cats", "m_genres"],
        ["m_years", "m_popular"],
        ["m_new", "m_fav"],
        ["m_lang"],
    ]
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, key)) for key in row] for row in layout],
        resize_keyboard=True,
        input_field_placeholder=t(lang, "placeholder"),
    )


def sub_kb(lang: str, missing: list[str]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{t(lang, 'subscribe')} {ch}", url=f"https://t.me/{ch.lstrip('@')}")]
        for ch in missing
    ]
    rows.append([InlineKeyboardButton(text=t(lang, "check"), callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------- majburiy obuna ----------------
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
