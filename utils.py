import asyncio
import logging
import re
from datetime import datetime, timezone
from html import escape

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
import database as db
import db_extra
import genres
import ui
from genres import CATEGORIES, cat_icon, cat_label
from locales import LANGS, t

# Bo'lim nomi: "Kinolar" o'rniga "Filmlar" ko'rsatiladi
genres.CATEGORY_LABELS["Kinolar"][1]["uz"] = "Filmlar"

BOT_USERNAME = ""
LANG_PROMPT = "🌐 Tilni tanlang / Choose language / Выберите язык"

HOME_LABEL = {"uz": "🏠 Bosh menyu", "en": "🏠 Main menu", "ru": "🏠 Главное меню"}
CONT_LABEL = {
    "uz": "▶️ Davom ettirish: {t} • {s}-fasl {e}-qism",
    "en": "▶️ Continue: {t} • S{s} E{e}",
    "ru": "▶️ Продолжить: {t} • С{s} Э{e}",
}

# Majburiy obuna ekrani matnlari
SUB_T = {
    "uz": {
        "title": "🔐 <b>Obuna bo'ling</b>\n\nBotdan foydalanish uchun quyidagi kanallarga obuna bo'ling. "
                 "Obuna bo'lishingiz bilan bu ekran o'zi yangilanadi ✨",
        "progress": "✅ Obuna: {done}/{total}",
        "left": "Yana {n} ta kanal qoldi",
        "joined": "✅ Rahmat! Obuna tasdiqlandi",
    },
    "en": {
        "title": "🔐 <b>Subscribe to continue</b>\n\nJoin the channels below to use the bot. "
                 "This screen updates automatically once you subscribe ✨",
        "progress": "✅ Subscribed: {done}/{total}",
        "left": "{n} channel(s) left",
        "joined": "✅ Thanks! Subscription confirmed",
    },
    "ru": {
        "title": "🔐 <b>Подпишитесь</b>\n\nЧтобы пользоваться ботом, подпишитесь на каналы ниже. "
                 "Экран обновится сам, как только вы подпишетесь ✨",
        "progress": "✅ Подписки: {done}/{total}",
        "left": "Осталось каналов: {n}",
        "joined": "✅ Спасибо! Подписка подтверждена",
    },
}

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
_titles: dict[str, str] = {}              # kanal -> nomi (tugmada username o'rniga)
_watch: dict[int, asyncio.Task] = {}      # obuna ekranini kuzatuvchi vazifalar
_pending: dict[int, str] = {}             # obunadan keyin ochiladigan kino kodi
GATE_OPEN = None                          # bot.py o'rnatadi: async def(bot, chat_id, uid, lang, movie, source)


# ---------------- tugmalar ----------------
def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def url_btn(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)


def grid(buttons: list, per_row: int) -> list:
    return [buttons[i : i + per_row] for i in range(0, len(buttons), per_row)]


def kb_of(rows: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def short(text: str, n: int = 24) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


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


# ---------------- majburiy kanallar (paneldan boshqariladi) ----------------
def channels() -> list[str]:
    """Panelda belgilangan kanallar; belgilanmagan bo'lsa Render sozlamasi (CHANNELS)."""
    raw = db.get_setting("sub_channels", "ENV")
    if raw == "ENV":
        return list(config.CHANNELS)
    return [c for c in raw.split(",") if c.strip()]


def chan_ref(entry: str):
    """Telegram API uchun kanal manzili: '@nom' yoki raqamli ID."""
    return int(entry.split("|")[0]) if "|" in entry else entry


def chan_url(entry: str) -> str:
    if "|" in entry:
        return entry.split("|", 1)[1]
    return f"https://t.me/{entry.lstrip('@')}"


def chan_title(entry: str) -> str:
    """Admin ro'yxati uchun (username/ID ko'rinadi)."""
    return f"🔒 {entry.split('|')[0]}" if "|" in entry else entry


async def chan_name(bot: Bot, entry: str) -> str | None:
    """Foydalanuvchi tugmasi uchun kanal nomi (username emas). Bir marta so'raladi va eslab qolinadi."""
    if entry in _titles:
        return _titles[entry]
    try:
        chat = await bot.get_chat(chan_ref(entry))
    except Exception as e:
        logging.warning("Kanal nomini olib bo'lmadi (%s): %s", entry, e)
        return None
    name = (chat.title or "").strip()
    if name:
        _titles[entry] = name
    return name or None


# ---------------- bosh menyu ----------------
def home_kb(lang: str, counts: dict, favs: int, rated: int, is_admin: bool, cont=None) -> InlineKeyboardMarkup:
    rows = []
    if cont:
        rows.append([btn(cont[0], cont[1])])
    rows.append([btn(t(lang, "m_search"), "nav:search")])
    cats = [
        btn(f"{cat_icon(cat)} {cat_label(cat, lang)} ({counts[cat]})", f"br:c:{i}:0:n")
        for i, cat in enumerate(CATEGORIES)
        if counts.get(cat)
    ]
    rows += grid(cats, 2)
    rows.append([btn(f"{t(lang, 'm_fav')} ({favs})", "fv:0")])
    rows.append([btn(t(lang, "m_top"), "br:p::0:r"), btn(t(lang, "m_new"), "br:n::0:n")])
    rows.append([btn(t(lang, "m_random"), "nav:random"), btn(t(lang, "m_more"), "nav:more")])
    if is_admin:
        rows.append([btn("🛠 Admin panel", "a:home")])
    return kb_of(rows)


async def continue_button(user_id: int, lang: str):
    """Serialni davom ettirish tugmasi: (matn, callback) yoki None."""
    prog = await db_extra.latest_progress(user_id)
    if not prog:
        return None
    movie = await db.get_movie(prog["movie_id"])
    if not movie or movie["hidden"]:
        return None
    _prev, nxt = await db_extra.neighbors(movie["id"], prog["season"], prog["episode"])
    s, e = nxt if nxt else (prog["season"], prog["episode"])
    label = CONT_LABEL.get(lang, CONT_LABEL["uz"]).format(t=short(movie["title"], 22), s=s, e=e)
    return label, f"cw:{movie['id']}"


async def show_home(bot: Bot, chat_id: int, user_id: int, lang: str, source=None, name: str | None = None):
    """Bosh menyu ekrani: banner, salom, kutubxona statistikasi va foydalanuvchi ma'lumotlari."""
    ui.set_back(user_id, "home")
    counts, favs, rated, until, cont = await asyncio.gather(
        db.category_counts(),
        db.fav_count(user_id),
        db.rated_count(user_id),
        db.premium_until(user_id),
        continue_button(user_id, lang),
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
    kb = home_kb(lang, counts, favs, rated, user_id in config.ADMIN_IDS, cont)
    await ui.show(bot, chat_id, user_id, text, kb, photo=banner("home"), source=source)


def lang_kb(code: str = "") -> InlineKeyboardMarkup:
    suffix = f":{code}" if code else ""
    return kb_of([[btn(name, f"lang:{c}{suffix}")] for c, name in LANGS.items()])


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
async def _member(bot: Bot, entry: str, user_id: int):
    """True/False; tekshirib bo'lmasa None."""
    try:
        m = await bot.get_chat_member(chan_ref(entry), user_id)
    except TelegramRetryAfter as e:
        await asyncio.sleep(min(e.retry_after, 3))
        return None
    except Exception as e:
        logging.warning("Obunani tekshirib bo'lmadi (%s): %s", entry, e)
        return None
    if m.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
        return False
    if m.status == ChatMemberStatus.RESTRICTED:
        return bool(getattr(m, "is_member", True))
    return True


async def _scan(bot: Bot, user_id: int):
    """(obuna bo'lmagan kanallar, noaniq natija bormi)."""
    chans = channels()
    results = await asyncio.gather(*(_member(bot, ch, user_id) for ch in chans))
    missing = [ch for ch, ok in zip(chans, results) if ok is False]
    return missing, any(r is None for r in results)


async def missing_channels(bot: Bot, user_id: int, use_cache: bool = True) -> list[str]:
    """Obuna bo'lmagan kanallar. Tekshirib bo'lmagan kanal bo'yicha foydalanuvchi to'silmaydi."""
    if not channels():
        return []
    now = asyncio.get_running_loop().time()
    if use_cache and now - _sub_ok.get(user_id, -1e9) < _SUB_TTL:
        return []
    missing, _uncertain = await _scan(bot, user_id)
    if missing:
        _sub_ok.pop(user_id, None)
    else:
        _sub_ok[user_id] = now
    return missing


def set_pending(uid: int, code):
    """Obunadan keyin ochiladigan kino (havola orqali kirganda)."""
    if code:
        _pending[uid] = code
    else:
        _pending.pop(uid, None)


def stop_gate_watch(uid: int):
    task = _watch.pop(uid, None)
    if task and task is not asyncio.current_task():
        task.cancel()


async def show_gate(bot: Bot, chat_id: int, uid: int, lang: str, missing: list[str], source=None, watch: bool = True):
    """Obuna ekrani: faqat obuna bo'lmagan kanallar, tugmada kanal nomi (username emas)."""
    total = len(channels())
    names = await asyncio.gather(*(chan_name(bot, ch) for ch in missing))
    rows = [
        [url_btn(f"➕ {short(name or f'Kanal {i}', 32)}", chan_url(ch))]
        for i, (ch, name) in enumerate(zip(missing, names), 1)
    ]
    rows.append([btn(t(lang, "check"), "check_sub")])
    st = SUB_T.get(lang, SUB_T["uz"])
    text = f"{st['title']}\n\n{st['progress'].format(done=max(0, total - len(missing)), total=total)}"
    await ui.show(bot, chat_id, uid, text, kb_of(rows), source=source)
    if watch:
        stop_gate_watch(uid)
        task = asyncio.create_task(_gate_loop(bot, chat_id, uid, lang, ui.screen_id(uid), tuple(missing)))
        _watch[uid] = task
        task.add_done_callback(lambda tk: _watch.pop(uid, None) if _watch.get(uid) is tk else None)


async def _gate_loop(bot: Bot, chat_id: int, uid: int, lang: str, msg_id, shown: tuple):
    """Tugmani bosmasa ham o'zi tekshiradi: obuna bo'lingan kanal ro'yxatdan yo'qoladi, hammasi bo'lsa menyu ochiladi."""
    for i in range(45):  # ~3.5 daqiqa
        await asyncio.sleep(3 if i < 20 else 6)
        if ui.screen_id(uid) != msg_id:
            return  # foydalanuvchi boshqa ekranga o'tdi
        try:
            missing, uncertain = await _scan(bot, uid)
            if not missing:
                if uncertain:
                    continue  # aniq bilmaymiz: o'tkazib yubormaymiz
                await gate_done(bot, chat_id, uid, lang)
                return
            if tuple(missing) != shown:
                shown = tuple(missing)
                await show_gate(bot, chat_id, uid, lang, missing, watch=False)
                msg_id = ui.screen_id(uid)
        except Exception as e:
            logging.warning("Obuna kuzatuvi xatosi: %s", e)


async def gate_done(bot: Bot, chat_id: int, uid: int, lang: str, source=None):
    """Obuna tasdiqlandi: kutilayotgan kino bo'lsa o'sha, bo'lmasa bosh menyu."""
    stop_gate_watch(uid)
    _sub_ok[uid] = asyncio.get_running_loop().time()
    code = _pending.pop(uid, None)
    if code and GATE_OPEN:
        movie = await db.get_movie_by_code(code)
        if movie:
            await GATE_OPEN(bot, chat_id, uid, lang, movie, source)
            return
    await show_home(bot, chat_id, uid, lang, source)


async def gate(bot: Bot, user_id: int, lang: str, msg: Message) -> bool:
    """Premium foydalanuvchilar majburiy obunadan ozod. Obuna bo'lmasa shu ekranda so'raladi."""
    if not channels() or await db.is_premium(user_id):
        return True
    missing = await missing_channels(bot, user_id)
    if missing:
        await show_gate(bot, msg.chat.id, user_id, lang, missing)
        return False
    return True
