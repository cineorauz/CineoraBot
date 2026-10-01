import asyncio
import logging
import re
from datetime import datetime, timezone
from html import escape

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
import database as db
import genres
import ui
from genres import CATEGORIES, cat_icon, cat_label
from locales import LANGS, t

# Bo'lim nomi: "Kinolar" o'rniga "Filmlar" ko'rsatiladi
genres.CATEGORY_LABELS["Kinolar"][1]["uz"] = "Filmlar"

BOT_USERNAME = ""
LANG_PROMPT = "🌐 Tilni tanlang / Choose language / Выберите язык"

HOME_LABEL = {"uz": "🏠 Bosh menyu", "en": "🏠 Main menu", "ru": "🏠 Главное меню"}

QUALITY_ORDER = ["2160", "1080", "720", "480", "360"]

_QUALITY_RE = re.compile(r"\b(2160|1080|720|480|360)\s*p\b", re.I)
_EP_PATTERNS = [
    re.compile(r"s\d{1,2}\s*e(\d{1,4})", re.I),
    re.compile(r"\b(\d{1,4})\s*-?\s*(?:qism|seriya|серия|серии|эпизод|episode|ep)\b", re.I),
    re.compile(r"\b(?:qism|seriya|серия|эпизод|episode|ep|e)\s*[:#.\-]?\s*(\d{1,4})\b", re.I),
]

# Obuna tekshiruvi natijasi 90 soniya eslab qolinadi
_SUB_TTL = 90
_sub_ok: dict[int, float] = {}


# ---------------- tugmalar ----------------
def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def url_btn(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)


def grid(buttons: list, per_row: int) -> list:
    return [buttons[i : i + per_row] for i in range(0, len(buttons), per_row)]


def kb_of(rows: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def nav_row(lang: str, back: str | None = None) -> list:
    """Pastdagi navigatsiya qatori: [◀️ Orqaga] [🏠 Bosh menyu]."""
    row = []
    if back:
        row.append(btn(t(lang, "back"), back))
    row.append(btn(HOME_LABEL.get(lang, HOME_LABEL["uz"]), "home"))
    return row


def with_nav(kb: InlineKeyboardMarkup, row: list) -> InlineKeyboardMarkup:
    return kb_of(list(kb.inline_keyboard) + [row])


def banner(slot: str):
    """Admin paneldan yuklangan banner rasmning file_id si (yo'q bo'lsa None)."""
    return db.get_setting(f"banner:{slot}") or None


# ---------------- bosh menyu ----------------
def home_kb(lang: str, counts: dict, favs: int, rated: int, is_admin: bool) -> InlineKeyboardMarkup:
    rows = [[btn(t(lang, "m_search"), "nav:search")]]
    cats = [
        btn(f"{cat_icon(cat)} {cat_label(cat, lang)} ({counts[cat]})", f"br:c:{i}:0:n")
        for i, cat in enumerate(CATEGORIES)
        if counts.get(cat)
    ]
    rows += grid(cats, 2)
    rows.append([btn(f"{t(lang, 'm_fav')} ({favs})", "fv:0")])
    rows.append([btn(t(lang, "m_top"), "br:p::0:r"), btn(t(lang, "m_more"), "nav:more")])
    if is_admin:
        rows.append([btn("🛠 Admin panel", "a:home")])
    return kb_of(rows)


async def show_home(bot: Bot, chat_id: int, user_id: int, lang: str, source=None, name: str | None = None):
    """Bosh menyu ekrani: banner, salom, kutubxona statistikasi va foydalanuvchi ma'lumotlari."""
    ui.set_back(user_id, "home")
    counts, favs, rated, until = await asyncio.gather(
        db.category_counts(), db.fav_count(user_id), db.rated_count(user_id), db.premium_until(user_id)
    )
    items = [f"{cat_icon(c)} {cat_label(c, lang)}: {counts[c]}" for c in CATEGORIES if counts.get(c)]
    lib = "\n".join(" • ".join(items[i : i + 2]) for i in range(0, len(items), 2)) or t(lang, "lib_empty")
    now = datetime.now(timezone.utc)
    if until and until > now:
        prem = t(lang, "prem_on").format(days=(until - now).days + 1)
    else:
        prem = t(lang, "prem_off")
    head = t(lang, "home_hello").format(name=escape(name)) if name is not None else t(lang, "home_menu")
    text = (
        f"{head}\n\n{t(lang, 'home_intro')}\n\n"
        f"<blockquote>📚 <b>{t(lang, 'lib_title')}</b>\n{lib}</blockquote>\n"
        f"<blockquote>👤 <b>{t(lang, 'you_title')}</b>\n"
        f"{t(lang, 'stat_line').format(favs=favs, rated=rated)}\n"
        f"{t(lang, 'stat_prem').format(prem=prem)}</blockquote>"
    )
    kb = home_kb(lang, counts, favs, rated, user_id in config.ADMIN_IDS)
    await ui.show(bot, chat_id, user_id, text, kb, photo=banner("home"), source=source)


def lang_kb(code: str = "") -> InlineKeyboardMarkup:
    suffix = f":{code}" if code else ""
    return kb_of([[btn(name, f"lang:{c}{suffix}")] for c, name in LANGS.items()])


def sub_kb(lang: str, missing: list[str]) -> InlineKeyboardMarkup:
    rows = [
        [url_btn(f"{t(lang, 'subscribe')} {ch}", f"https://t.me/{ch.lstrip('@')}")] for ch in missing
    ]
    rows.append([btn(t(lang, "check"), "check_sub")])
    return kb_of(rows)


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


def fmt_num(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def fmt_date(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%d.%m.%Y")


# ---------------- majburiy obuna ----------------
async def _is_member(bot: Bot, channel: str, user_id: int) -> bool:
    try:
        m = await bot.get_chat_member(channel, user_id)
        return m.status not in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED)
    except Exception as e:
        logging.warning("Obunani tekshirib bo'lmadi (%s): %s", channel, e)
        return True  # tekshirib bo'lmasa foydalanuvchini to'smaymiz


async def missing_channels(bot: Bot, user_id: int, use_cache: bool = True) -> list[str]:
    if not config.CHANNELS:
        return []
    now = asyncio.get_running_loop().time()
    if use_cache and now - _sub_ok.get(user_id, -1e9) < _SUB_TTL:
        return []
    results = await asyncio.gather(*(_is_member(bot, ch, user_id) for ch in config.CHANNELS))
    missing = [ch for ch, ok in zip(config.CHANNELS, results) if not ok]
    if not missing:
        _sub_ok[user_id] = now
    return missing


async def gate(bot: Bot, user_id: int, lang: str, msg: Message) -> bool:
    """Premium foydalanuvchilar majburiy obunadan ozod. Obuna bo'lmasa shu ekranda so'raladi."""
    if not config.CHANNELS or await db.is_premium(user_id):
        return True
    missing = await missing_channels(bot, user_id)
    if missing:
        await ui.show(bot, msg.chat.id, user_id, t(lang, "sub_required"), sub_kb(lang, missing))
        return False
    return True
