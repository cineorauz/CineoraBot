import asyncio
import logging
import time
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import cards
import config
import database as db
import movies
import tmdb
import translate
import ui
import utils
from genres import CATEGORIES

router = Router()
router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

PAGE = 10
S = ui.show_for
DEFAULT_FOOTER = "🔔 @CineoraUz | Asosiy kanalimiz"

SLOTS = [
    ("home", "🏠 Bosh menyu"),
    ("Kinolar", "🎬 Filmlar"),
    ("Seriallar", "📺 Seriallar"),
    ("Animelar", "🍥 Animelar"),
    ("Dramalar", "🎭 Dramalar"),
    ("Multfilmlar", "🧸 Multfilmlar"),
    ("premium", "💎 Premium"),
    ("generic", "🖼 Umumiy"),
]

FILTERS = [
    ("a", "Hammasi"),
    ("m", "🎬 Film"),
    ("s", "📺 Serial"),
    ("p", "💎 Premium"),
    ("h", "🙈 Yashirin"),
    ("e", "📭 Fayli yo'q"),
]

# Bir vaqtda ko'p fayl yuborilganda ular navbat bilan ishlanadi (tartib buzilmasligi uchun)
_locks: dict[int, asyncio.Lock] = {}
_aq: dict[int, str] = {}      # admin ro'yxatidagi oxirgi qidiruv matni
_alast: dict[int, tuple] = {}  # admin ro'yxatidagi oxirgi (sahifa, filtr)


def user_lock(user_id: int) -> asyncio.Lock:
    return _locks.setdefault(user_id, asyncio.Lock())


class Add(StatesGroup):
    query = State()
    manual_title = State()
    draft = State()
    upload = State()


class Edit(StatesGroup):
    alias = State()
    title = State()
    overview = State()


class Banner(StatesGroup):
    wait = State()


class Cfg(StatesGroup):
    ann = State()
    store = State()
    footer = State()


class Search(StatesGroup):
    wait = State()


# ---------------- yordamchilar ----------------
def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def grid(buttons: list, per_row: int = 2) -> list:
    return [buttons[i : i + per_row] for i in range(0, len(buttons), per_row)]


def kb_of(rows: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


CANCEL_KB = kb_of([[btn("❌ Bekor qilish", "a:home")]])


def movie_link(code: str) -> str:
    return f"https://t.me/{utils.BOT_USERNAME}?start={code}"


def imdb_status(d) -> str:
    if d.get("imdb_rating"):
        return f"IMDb ✅ {d['imdb_rating']}"
    return f"IMDb ⚠️ {d.get('omdb_error') or 'topilmadi'}"


def status_label(status) -> str:
    return "Tugagan" if (status or "completed") == "completed" else "Davom etmoqda"


def home_view():
    text = "🛠 <b>Admin panel</b>\n\nBo'limni tanlang 👇"
    kb = kb_of(
        [
            [btn("➕ Qo'shish", "a:add"), btn("📋 Kinolar", "a:lr")],
            [btn("📥 So'rovlar", "a:reqs"), btn("💎 Premium", "ap:home")],
            [btn("🖼 Bannerlar", "a:bn"), btn("⚙️ Sozlamalar", "a:set")],
            [btn("📊 Statistika", "a:stats"), btn("🏓 Tezlik", "a:ping")],
            [btn("🏠 Bot menyusi", "home")],
        ]
    )
    return text, kb


# ---------------- asosiy ----------------
@router.message(Command("admin"))
async def admin_cmd(m: Message, state: FSMContext):
    await state.clear()
    await ui.delete_message(m)
    await ui.remove_reply_kb(m.bot, m.chat.id, m.from_user.id)
    text, kb = home_view()
    await S(m, text, kb)


@router.message(Command("cancel"))
async def cancel_cmd(m: Message, state: FSMContext):
    await state.clear()
    await ui.delete_message(m)
    text, kb = home_view()
    await S(m, text, kb)


@router.callback_query(F.data == "a:home")
async def admin_home(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    text, kb = home_view()
    await S(c, text, kb)


@router.message(Command("ping"))
async def ping_cmd(m: Message):
    await ui.delete_message(m)
    times = [await db.ping() for _ in range(3)]
    await ui.flash(m.bot, m.chat.id, "🏓 Baza: " + " → ".join(f"{x:.0f}" for x in times) + " ms", 8)


@router.callback_query(F.data == "a:ping")
async def ping_btn(c: CallbackQuery):
    times = [await db.ping() for _ in range(3)]
    t0 = time.perf_counter()
    await c.bot.get_me()
    tg_ms = (time.perf_counter() - t0) * 1000
    await c.answer(
        "🏓 Baza: " + " → ".join(f"{x:.0f}" for x in times) + f" ms\n📡 Telegram: {tg_ms:.0f} ms",
        show_alert=True,
    )


@router.callback_query(F.data == "a:stats")
async def show_stats(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    s = await db.stats()
    lines = [
        "📊 <b>Statistika</b>\n",
        f"👥 Foydalanuvchilar: <b>{s['users']}</b> (24 soatda +{s['users_day']})",
        f"🎬 Kinolar: {s['movies']}  •  📺 Seriallar: {s['series']}  •  💎 Premium: {s['premium_movies']}",
        f"📁 Fayllar: {s['files']}",
        f"📥 Ochiq so'rovlar: {s['requests']}",
    ]
    if s["top"]:
        lines.append("\n🔥 <b>Eng ko'p yuklangan:</b>")
        for i, r in enumerate(s["top"], 1):
            lines.append(f"{i}. {escape(r['title'])} — {r['views']}")
    await S(c, "\n".join(lines), kb_of([[btn("◀️ Orqaga", "a:home")]]))


@router.callback_query(F.data == "a:reqs")
async def open_requests(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    rows = await db.pending_requests()
    if not rows:
        await S(c, "📥 Hozircha so'rovlar yo'q.", kb_of([[btn("◀️ Orqaga", "a:home")]]))
        return
    kb = [
        [
            btn(
                f"{r['c']}× {'📺' if r['tmdb_type'] == 'tv' else '🎬'} {r['title']} ({r['year'] or '—'})",
                f"a:rq:{r['tmdb_type']}:{r['tmdb_id']}",
            )
        ]
        for r in rows
    ]
    kb.append([btn("◀️ Orqaga", "a:home")])
    await S(
        c,
        "📥 <b>Foydalanuvchi so'rovlari</b>\nEng ko'p so'ralganlari yuqorida. Tanlab qo'shing 👇",
        kb_of(kb),
    )


# ---------------- bannerlar ----------------
def banners_screen():
    rows = [
        [btn(f"{'✅' if db.get_setting('banner:' + slot) else '➖'} {label}", f"a:bs:{slot}")]
        for slot, label in SLOTS
    ]
    rows.append([btn("◀️ Orqaga", "a:home")])
    text = (
        "🖼 <b>Bannerlar</b>\n\nHar ekran uchun banner rasmini yuklang (✅ — o'rnatilgan).\n"
        "Banner bo'lmasa, ekran oddiy matn ko'rinishida chiqadi."
    )
    return text, kb_of(rows)


@router.callback_query(F.data == "a:bn")
async def banners_view(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    text, kb = banners_screen()
    await S(c, text, kb)


@router.callback_query(F.data.regexp(r"^a:bs:\w+$"))
async def banner_pick(c: CallbackQuery, state: FSMContext):
    slot = c.data.split(":")[2]
    await state.set_state(Banner.wait)
    await state.update_data(slot=slot)
    await c.answer()
    label = dict(SLOTS).get(slot, slot)
    rows = [[btn("🗑 Olib tashlash", f"a:bd:{slot}")], [btn("◀️ Orqaga", "a:bn")]]
    await S(c, f"🖼 <b>{label}</b> uchun rasmni yuboring (fayl emas, oddiy rasm sifatida).", kb_of(rows))


@router.message(Banner.wait, F.photo)
async def banner_save(m: Message, state: FSMContext):
    slot = (await state.get_data())["slot"]
    await state.clear()
    await ui.delete_message(m)
    await db.set_setting(f"banner:{slot}", m.photo[-1].file_id)
    text, kb = banners_screen()
    await S(m, text, kb)


@router.callback_query(F.data.regexp(r"^a:bd:\w+$"))
async def banner_delete(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await db.set_setting(f"banner:{c.data.split(':')[2]}", "")
    await c.answer("Olib tashlandi")
    text, kb = banners_screen()
    await S(c, text, kb)


# ---------------- sozlamalar (kanallar, himoya, e'lon yozuvi) ----------------
def settings_view():
    ann = db.get_setting("ann_channel")
    store = db.get_setting("store_channel")
    protect = db.get_setting("protect", "1") == "1"
    footer = db.get_setting("ann_footer", DEFAULT_FOOTER)
    ann_t = f"✅ {escape(db.get_setting('ann_channel_title'))}" if ann else "❌ o'rnatilmagan"
    store_t = f"✅ {escape(db.get_setting('store_channel_title'))}" if store else "❌ o'rnatilmagan"
    text = (
        "⚙️ <b>Sozlamalar</b>\n\n"
        f"📣 E'lon kanali: {ann_t}\n"
        f"🗄 Zaxira kanal: {store_t}\n"
        f"🔒 Videolarni himoyalash (forward/saqlash yo'q): {'✅ yoqilgan' if protect else '❌ o`chirilgan'}\n"
        f"📝 E'lon oxiridagi yozuv:\n<code>{escape(footer)}</code>"
    )
    kb = kb_of(
        [
            [btn("📣 E'lon kanali", "a:cfg:ann"), btn("🗄 Zaxira kanal", "a:cfg:store")],
            [btn("🔒 Himoya: " + ("o'chirish" if protect else "yoqish"), "a:cfg:protect")],
            [btn("📝 E'lon yozuvi", "a:cfg:footer")],
            [btn("◀️ Orqaga", "a:home")],
        ]
    )
    return text, kb


@router.callback_query(F.data == "a:set")
async def settings_open(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    text, kb = settings_view()
    await S(c, text, kb)


@router.callback_query(F.data == "a:cfg:protect")
async def cfg_protect(c: CallbackQuery):
    now = db.get_setting("protect", "1") == "1"
    await db.set_setting("protect", "0" if now else "1")
    await c.answer("🔒 Himoya o'chirildi" if now else "🔒 Himoya yoqildi")
    text, kb = settings_view()
    await S(c, text, kb)


@router.callback_query(F.data.regexp(r"^a:cfg:(ann|store)$"))
async def cfg_channel_ask(c: CallbackQuery, state: FSMContext):
    kind = c.data.split(":")[2]
    await state.set_state(Cfg.ann if kind == "ann" else Cfg.store)
    await c.answer()
    what = "e'lon (post)" if kind == "ann" else "zaxira (fayl nusxalari)"
    await S(
        c,
        f"📣 <b>{what.capitalize()} kanali</b>\n\n"
        "1. Botni kanalga <b>admin</b> qiling (post yuborish huquqi bilan).\n"
        "2. Kanaldan istalgan postni shu yerga <b>forward</b> qiling "
        "(yoki kanal ID sini, masalan <code>-1001234567890</code>, yuboring).",
        kb_of([[btn("❌ Bekor qilish", "a:set")]]),
    )


def channel_id_from(m: Message):
    origin = getattr(m, "forward_origin", None)
    chat = getattr(origin, "chat", None) if origin else None
    if chat is not None:
        return chat.id
    fc = getattr(m, "forward_from_chat", None)
    if fc is not None:
        return fc.id
    txt = (m.text or "").strip()
    if txt.lstrip("-").isdigit():
        return int(txt)
    return None


async def check_channel(bot, chat_id: int):
    try:
        chat = await bot.get_chat(chat_id)
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id, me.id)
    except Exception as e:
        return None, f"Kanalga kirib bo'lmadi: {e}"
    if member.status not in ("administrator", "creator"):
        return None, "Bot bu kanalda admin emas"
    if member.status == "administrator" and getattr(member, "can_post_messages", True) is False:
        return None, "Botda post yuborish huquqi yo'q"
    return chat.title or str(chat_id), None


@router.message(StateFilter(Cfg.ann, Cfg.store))
async def cfg_channel_save(m: Message, state: FSMContext):
    cur = await state.get_state()
    key = "ann_channel" if cur == Cfg.ann.state else "store_channel"
    chat_id = channel_id_from(m)
    await ui.delete_message(m)
    if chat_id is None:
        await ui.flash(m.bot, m.chat.id, "⚠️ Kanaldan post forward qiling yoki ID yuboring.")
        return
    title, err = await check_channel(m.bot, chat_id)
    if err:
        await ui.flash(m.bot, m.chat.id, f"⚠️ {escape(err)}", 6)
        return
    await state.clear()
    await db.set_setting(key, str(chat_id))
    await db.set_setting(key + "_title", title)
    text, kb = settings_view()
    await S(m, text, kb)


@router.callback_query(F.data == "a:cfg:footer")
async def cfg_footer_ask(c: CallbackQuery, state: FSMContext):
    await state.set_state(Cfg.footer)
    await c.answer()
    await S(
        c,
        "📝 E'lon oxiridagi yozuvni yuboring (oddiy matn).\n"
        f"Hozirgi: <code>{escape(db.get_setting('ann_footer', DEFAULT_FOOTER))}</code>\n\n"
        "O'chirish uchun <code>-</code> yuboring.",
        kb_of([[btn("❌ Bekor qilish", "a:set")]]),
    )


@router.message(Cfg.footer, F.text & ~F.text.startswith("/"))
async def cfg_footer_save(m: Message, state: FSMContext):
    await state.clear()
    await ui.delete_message(m)
    value = "" if m.text.strip() == "-" else m.text.strip()
    await db.set_setting("ann_footer", value if value else " ")
    text, kb = settings_view()
    await S(m, text, kb)


# ---------------- tarjima (Tilmoch) ----------------
async def prepare_draft(d: dict):
    """Yangi qo'shiladigan kontent uchun o'zbekcha tavsifni avtomatik tarjima qiladi."""
    err = await translate.fill_uz(d)
    if err:
        d["tr_status"] = f"🌐 Tarjima: ⚠️ {err}"
    elif d.get("overview_uz"):
        d["tr_status"] = "🌐 Tarjima: ✅ o'zbekcha tavsif tayyor"
    else:
        d["tr_status"] = "🌐 Tarjima: tavsif topilmadi"


async def translate_movie(movie_id: int, force: bool = False):
    """Mavjud kinoning o'zbekcha tavsif/tagline'ini tarjima qiladi. Xato matnini yoki None qaytaradi."""
    movie = await db.get_movie(movie_id)
    keys = ("overview_en", "overview_ru", "tagline_en", "tagline_ru", "overview_uz", "tagline_uz")
    tmp = {k: movie[k] for k in keys}
    err = await translate.fill_uz(tmp, force=force)
    if err:
        return err
    for field in ("overview_uz", "tagline_uz"):
        if tmp.get(field) and tmp[field] != movie[field]:
            await db.set_field(movie_id, field, tmp[field])
    return None


# ---------------- qo'shish: TMDB qidiruv ----------------
@router.callback_query(F.data == "a:add")
async def add_start(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(Add.query)
    await c.answer()
    await S(c, "🔎 <b>Qo'shish</b>\n\nKino yoki serial nomini yozing (TMDB'dan qidiraman).", CANCEL_KB)


@router.message(Add.query, F.text & ~F.text.startswith("/"))
async def on_query(m: Message, state: FSMContext):
    await ui.delete_message(m)
    manual = [btn("✍️ Qo'lda kiritish", "a:tm:manual")]
    try:
        results = await tmdb.search(m.text.strip())
    except tmdb.TMDBError as e:
        await S(m, f"⚠️ {escape(str(e))}\n\nQo'lda kiritishingiz mumkin:", kb_of([manual, [btn("❌ Bekor qilish", "a:home")]]))
        return
    rows = []
    for r in results:
        kind = "Kino" if r["type"] == "movie" else "Serial"
        year = f" ({r['year']})" if r["year"] else ""
        rows.append([btn(f"{r['title']}{year} • {kind}", f"a:tm:{r['type']}:{r['id']}")])
    rows += [manual, [btn("❌ Bekor qilish", "a:home")]]
    text = "Topilganlar:" if results else "😕 TMDB'da topilmadi. Boshqa nom yozing yoki qo'lda kiriting."
    await S(m, text, kb_of(rows))


@router.callback_query(Add.query, F.data == "a:tm:manual")
async def on_manual(c: CallbackQuery, state: FSMContext):
    await state.set_state(Add.manual_title)
    await c.answer()
    await S(c, "✍️ Nomni yozing:", CANCEL_KB)


@router.message(Add.manual_title, F.text & ~F.text.startswith("/"))
async def on_manual_title(m: Message, state: FSMContext):
    await ui.delete_message(m)
    title = m.text.strip()
    draft = {
        "title": title, "aliases": [title], "year": None, "genres": [], "rating": None,
        "poster_url": None, "tmdb_id": None, "tmdb_type": None, "is_series": False,
        "seasons_total": 0, "category": "Kinolar", "is_premium": False, "series_status": "completed",
    }
    await state.update_data(draft=draft)
    await state.set_state(Add.draft)
    await show_preview(m, draft)


@router.callback_query(Add.query, F.data.regexp(r"^a:tm:(movie|tv):\d+$"))
async def on_pick(c: CallbackQuery, state: FSMContext):
    _, _, media_type, tmdb_id = c.data.split(":")
    await c.answer("Yuklanmoqda...")
    try:
        draft = await tmdb.details(media_type, int(tmdb_id))
    except tmdb.TMDBError as e:
        await ui.flash(c.bot, c.message.chat.id, f"⚠️ {escape(str(e))}")
        return
    draft["series_status"] = "completed"
    await prepare_draft(draft)
    await state.update_data(draft=draft)
    await state.set_state(Add.draft)
    await show_preview(c, draft)


@router.callback_query(F.data.regexp(r"^a:rq:(movie|tv):\d+$"))
async def on_request_pick(c: CallbackQuery, state: FSMContext):
    """So'rovlar ro'yxatidan tanlangan kontentni qo'shishni boshlaydi."""
    _, _, media_type, tmdb_id = c.data.split(":")
    await c.answer("Yuklanmoqda...")
    try:
        draft = await tmdb.details(media_type, int(tmdb_id))
    except tmdb.TMDBError as e:
        await ui.flash(c.bot, c.message.chat.id, f"⚠️ {escape(str(e))}")
        return
    draft["series_status"] = "completed"
    await prepare_draft(draft)
    await state.clear()
    await state.update_data(draft=draft)
    await state.set_state(Add.draft)
    await show_preview(c, draft)


# ---------------- qo'shish: oldindan ko'rish ----------------
def preview_text(d: dict) -> str:
    year = f" ({d['year']})" if d.get("year") else ""
    kind = "📺 Serial" if d["is_series"] else "🎬 Kino"
    lines = [
        f"🎬 <b>{escape(d['title'])}</b>{year}",
        f"📂 {escape(d['category'])} • {kind}",
        f"💎 Premium: {'ha' if d.get('is_premium') else 'yo`q'}",
    ]
    if d["is_series"]:
        lines.append(f"📡 Holat: {status_label(d.get('series_status'))}")
    if d.get("genres"):
        lines.append("🎭 " + escape(", ".join(d["genres"])))
    if d.get("tmdb_id"):
        tmdb_part = f"TMDB ⭐ {d['rating']:.1f}" if d.get("rating") else "TMDB —"
        lines.append(f"{tmdb_part}  •  {escape(imdb_status(d))}")
    if d.get("tr_status"):
        lines.append(escape(d["tr_status"]))
    if d["is_series"] and d.get("seasons_total"):
        lines.append(f"📼 Fasllar: {d['seasons_total']}")
    return "\n".join(lines)


def preview_kb(d: dict) -> InlineKeyboardMarkup:
    rows = [
        [btn("✅ Tasdiqlash", "a:dr:ok")],
        [btn("📂 Kategoriya", "a:dr:cat"), btn("🔁 Kino/Serial", "a:dr:type")],
        [btn("💎 Premium", "a:dr:prem")],
    ]
    if d.get("is_series"):
        rows.append([btn("📡 Holat: " + status_label(d.get("series_status")), "a:dr:st")])
    rows.append([btn("❌ Bekor qilish", "a:home")])
    return kb_of(rows)


def cat_kb() -> InlineKeyboardMarkup:
    return kb_of(grid([btn(c, f"a:dr:c:{i}") for i, c in enumerate(CATEGORIES)], 2))


async def show_preview(target, d: dict):
    await S(target, preview_text(d), preview_kb(d), photo=d.get("poster_url"))


async def refresh_preview(c: CallbackQuery, d: dict):
    await S(c, preview_text(d), preview_kb(d), keep_photo=True)


@router.callback_query(Add.draft, F.data == "a:dr:cat")
async def draft_cat(c: CallbackQuery):
    await c.message.edit_reply_markup(reply_markup=cat_kb())
    await c.answer()


@router.callback_query(Add.draft, F.data.regexp(r"^a:dr:c:\d+$"))
async def draft_set_cat(c: CallbackQuery, state: FSMContext):
    d = (await state.get_data())["draft"]
    d["category"] = CATEGORIES[int(c.data.split(":")[3])]
    await state.update_data(draft=d)
    await c.answer()
    await refresh_preview(c, d)


@router.callback_query(Add.draft, F.data == "a:dr:type")
async def draft_type(c: CallbackQuery, state: FSMContext):
    d = (await state.get_data())["draft"]
    d["is_series"] = not d["is_series"]
    await state.update_data(draft=d)
    await c.answer()
    await refresh_preview(c, d)


@router.callback_query(Add.draft, F.data == "a:dr:prem")
async def draft_prem(c: CallbackQuery, state: FSMContext):
    d = (await state.get_data())["draft"]
    d["is_premium"] = not d.get("is_premium")
    await state.update_data(draft=d)
    await c.answer()
    await refresh_preview(c, d)


@router.callback_query(Add.draft, F.data == "a:dr:st")
async def draft_status(c: CallbackQuery, state: FSMContext):
    d = (await state.get_data())["draft"]
    d["series_status"] = "ongoing" if (d.get("series_status") or "completed") == "completed" else "completed"
    await state.update_data(draft=d)
    await c.answer()
    await refresh_preview(c, d)


@router.callback_query(Add.draft, F.data == "a:dr:ok")
async def draft_ok(c: CallbackQuery, state: FSMContext):
    d = (await state.get_data())["draft"]
    movie_id, _code = await db.create_movie(d)
    await c.answer("✅ Saqlandi")
    if d["is_series"]:
        await state.clear()
        text, kb = await season_picker(movie_id)
        await S(c, text, kb)
    else:
        await ui.delete_message(c.message)
        await begin_upload(c.bot, c.message.chat.id, state, movie_id, 0)


# ---------------- fayl yuklash ----------------
async def season_picker(movie_id: int):
    movie = await db.get_movie(movie_id)
    counts = await db.season_counts(movie_id)
    total = max(movie["seasons_total"], max(counts, default=0))
    buttons = [btn(f"{s}-fasl ({counts.get(s, 0)})", f"a:sn:{movie_id}:{s}") for s in range(1, total + 1)]
    rows = grid(buttons, 3)
    rows.append([btn(f"➕ {total + 1}-fasl", f"a:sn:{movie_id}:{total + 1}")])
    rows.append([btn("◀️ Sahifa", f"a:m:{movie_id}")])
    return "📺 Qaysi faslga qism qo'shamiz? (qavsda: yuklangan qismlar soni)", kb_of(rows)


def upload_kb() -> InlineKeyboardMarkup:
    return kb_of(
        [
            [btn("4K", "a:up:q:2160"), btn("1080p", "a:up:q:1080"), btn("720p", "a:up:q:720"), btn("480p", "a:up:q:480")],
            [btn("↩️ Oxirgisini o'chirish", "a:up:undo"), btn("✅ Tugatish", "a:up:done")],
        ]
    )


def status_text(d: dict) -> str:
    saved, season = d["saved"], d["season"]
    note = d.get("last_note")
    note_line = f"\n⚠️ {note}" if note else ""
    if not saved:
        if season == 0:
            return (
                "📀 Fayllarni yuboring (video yoki hujjat).\n"
                "Sifat avval izohdan, keyin video o'lchamidan aniqlanadi. "
                "Bir nechta sifatni ketma-ket yuborishingiz mumkin."
            )
        return (
            f"📺 {season}-fasl. Qismlarni ketma-ket yuboring.\n\n"
            f"Qism raqami izohdan o'qiladi (1-qism, E05). Topilmasa {d['base'] + 1}-qismdan boshlanadi. "
            "Izohda raqam bo'lmasa, har qismning sifatlarini (1080p, 720p) ketma-ket yuboring."
        )
    last = saved[-1]
    hint = "\n\nSifat noto'g'ri bo'lsa, pastdagi tugma bilan oxirgi fayl sifatini o'zgartiring."
    if season == 0:
        qs = sorted({s[2] for s in saved}, key=utils.q_key, reverse=True)
        return (
            f"✅ {utils.q_label(last[2])} qabul qilindi{note_line}\n\n"
            f"📀 Yuklangan: {', '.join(utils.q_label(q) for q in qs)}{hint}\n\n"
            "Yana sifat yuboring yoki ✅ Tugatish."
        )
    eps = len({s[1] for s in saved})
    return (
        f"✅ {season}-fasl, {last[1]}-qism ({utils.q_label(last[2])}) qabul qilindi{note_line}\n\n"
        f"📼 Shu safar: {eps} ta qism, {len(saved)} ta fayl{hint}\n\n"
        "Davom eting yoki ✅ Tugatish."
    )


async def post_status(bot, chat_id: int, state: FSMContext):
    """Holat xabarini har doim eng pastda ko'rsatadi (eskisini o'chirib)."""
    d = await state.get_data()
    old = d.get("status_id")
    if old:
        await ui.delete_id(bot, chat_id, old)
    sent = await bot.send_message(chat_id, status_text(d), reply_markup=upload_kb())
    await state.update_data(status_id=sent.message_id)


async def begin_upload(bot, chat_id: int, state: FSMContext, movie_id: int, season: int):
    await state.clear()
    await state.set_state(Add.upload)
    base = await db.max_episode(movie_id, season) if season else 0
    await state.update_data(
        movie_id=movie_id, season=season, cur_ep=None, base=base, saved=[], status_id=None, last_note=None
    )
    await post_status(bot, chat_id, state)


@router.callback_query(F.data.regexp(r"^a:sn:\d+:\d+$"))
async def on_season(c: CallbackQuery, state: FSMContext):
    _, _, movie_id, season = c.data.split(":")
    movie_id, season = int(movie_id), int(season)
    movie = await db.get_movie(movie_id)
    if not movie:
        await c.answer("Topilmadi", show_alert=True)
        return
    if season > movie["seasons_total"]:
        await db.set_seasons_total(movie_id, season)
    await c.answer()
    await ui.delete_message(c.message)
    await begin_upload(c.bot, c.message.chat.id, state, movie_id, season)


async def copy_to_storage(m: Message, movie_id: int, season: int, episode: int, quality: str,
                          file_id: str, file_type: str) -> bool:
    """Faylni zaxira kanalga nusxalaydi. Muvaffaqiyatli bo'lsa True."""
    store_id = db.get_setting("store_channel")
    if not store_id:
        return False
    try:
        movie = await db.get_movie(movie_id)
        cap = movie["title"] + (f" • S{season:02d}E{episode:02d}" if season else "") + f" • {utils.q_label(quality)}"
        if file_type == "video":
            sent = await m.bot.send_video(int(store_id), file_id, caption=cap)
        else:
            sent = await m.bot.send_document(int(store_id), file_id, caption=cap)
        await db.set_store_msg(movie_id, season, episode, quality, sent.message_id)
        return True
    except Exception as e:
        logging.warning("Zaxira kanalga nusxalab bo'lmadi: %s", e)
        return False


@router.message(Add.upload, F.video | F.document)
async def on_file(m: Message, state: FSMContext):
    async with user_lock(m.from_user.id):
        d = await state.get_data()
        movie_id, season, saved = d["movie_id"], d["season"], d["saved"]
        plain = m.caption or ""  # izoh faqat sifat/qism raqamini aniqlash uchun o'qiladi, saqlanmaydi
        cover_id = None
        if m.video:
            file_id, file_type, w, h = m.video.file_id, "video", m.video.width, m.video.height
            cover = getattr(m.video, "cover", None)  # videoning muqovasi (thumbnail)
            if cover:
                cover_id = cover[-1].file_id
        else:
            file_id, file_type, w, h = m.document.file_id, "document", 0, 0

        by_caption = utils.quality_from_caption(plain)
        by_size = utils.quality_from_size(w, h)

        if season == 0:
            episode = 0
        else:
            episode = utils.detect_episode(plain)
            if episode is None:
                cur = d["cur_ep"]
                if cur is None:
                    episode = d["base"] + 1
                else:
                    taken_cur = {s[2] for s in saved if s[1] == cur}
                    cands = {q for q in (by_caption, by_size) if q}
                    episode = cur if (cands and cands - taken_cur) else cur + 1

        taken = {s[2] for s in saved if s[0] == season and s[1] == episode}
        quality, note = utils.resolve_quality(by_caption, by_size, taken)

        await db.save_file(movie_id, season, episode, quality, file_id, file_type, None, cover_id)
        # Zaxira kanalga nusxalansa, admin chatidagi fayl xabari o'chiriladi (chat toza qoladi)
        if await copy_to_storage(m, movie_id, season, episode, quality, file_id, file_type):
            await ui.delete_message(m)
        saved.append([season, episode, quality])
        await state.update_data(saved=saved, cur_ep=episode, last_note=note)
        await post_status(m.bot, m.chat.id, state)


@router.callback_query(Add.upload, F.data.regexp(r"^a:up:q:\d+$"))
async def on_quality(c: CallbackQuery, state: FSMContext):
    new_q = c.data.split(":")[3]
    d = await state.get_data()
    saved = d["saved"]
    if not saved:
        await c.answer("Hali fayl yuborilmagan", show_alert=True)
        return
    season, episode, old_q = saved[-1]
    if old_q == new_q:
        await c.answer("Allaqachon shunday")
        return
    await db.change_quality(d["movie_id"], season, episode, old_q, new_q)
    saved[-1][2] = new_q
    await state.update_data(saved=saved, last_note=None)
    await c.answer(f"✅ {utils.q_label(new_q)}")
    await post_status(c.bot, c.message.chat.id, state)


@router.callback_query(Add.upload, F.data == "a:up:undo")
async def on_undo(c: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    saved = d["saved"]
    if not saved:
        await c.answer("O'chiradigan narsa yo'q", show_alert=True)
        return
    season, episode, quality = saved.pop()
    await db.delete_file(d["movie_id"], season, episode, quality)
    await state.update_data(saved=saved, cur_ep=saved[-1][1] if saved else None, last_note=None)
    await c.answer("↩️ O'chirildi")
    await post_status(c.bot, c.message.chat.id, state)


@router.callback_query(Add.upload, F.data == "a:up:done")
async def on_done(c: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    movie = await db.get_movie(d["movie_id"])
    saved = d["saved"]
    rows = []
    ask = ""
    if saved and db.get_setting("ann_channel"):
        mid = movie["id"]
        if not movie["is_series"]:
            rows.append([btn("📣 Kanalga joylash", f"a:av:{mid}:n")])
            ask = "\n\n📣 Kanalga joylaymizmi?"
        elif movie["series_status"] == "completed":
            rows.append([btn("📣 Serialni kanalga joylash", f"a:av:{mid}:n")])
            ask = "\n\n📣 Serial tugagan. Kanalga joylaymizmi?"
        else:
            season = saved[-1][0]
            eps = sorted({s[1] for s in saved if s[0] == season})
            rows.append([btn("🆕 Yangi qism(lar)ni joylash", f"a:av:{mid}:e{season}-{eps[0]}-{eps[-1]}")])
            rows.append([btn("📣 Serialni (to'liq post)", f"a:av:{mid}:n")])
            ask = "\n\n🆕 Yangi qism(lar)ni kanalga joylaymizmi?"
    if movie["is_series"]:
        rows.append([btn("➕ Boshqa fasl", f"a:sp:{movie['id']}")])
    rows.append([btn("➕ Yana qo'shish", "a:add"), btn("📋 Sahifa", f"a:m:{movie['id']}")])
    rows.append([btn("🛠 Admin panel", "a:home")])
    extra = ""
    if saved and movie["tmdb_id"]:
        asyncio.create_task(movies.notify_requesters(c.bot, movie))  # so'raganlarga xabar
        extra = "\n🔔 So'ragan foydalanuvchilarga xabar yuborilmoqda"
    await c.answer()
    await S(
        c,
        f"✅ <b>Tayyor!</b>\n\n🎬 <b>{escape(movie['title'])}</b>\n"
        f"📁 Shu safar: {len(saved)} ta fayl{extra}\n"
        f"🔗 <code>{movie_link(movie['code'])}</code>{ask}",
        kb_of(rows),
    )


# ---------------- ro'yxat (raqamli, filtr va qidiruv bilan) ----------------
def admin_line(r) -> str:
    icon = "📺" if r["is_series"] else "🎬"
    year = f" ({r['year']})" if r["year"] else ""
    flags = ("🙈" if r["hidden"] else "") + ("💎" if r["is_premium"] else "")
    if r["is_series"]:
        info = f"{r['eps']} qism" if r["eps"] else "📭"
    else:
        qs = sorted(r["qs"] or [], key=utils.q_key, reverse=True)
        info = "·".join(utils.q_label(q) for q in qs) if qs else "📭"
    return f"{icon} {escape(movies.short(r['title'], 30))}{year} • {info} {flags}".rstrip()


async def list_view(uid: int, page: int, f: str):
    q = _aq.get(uid, "") if f == "q" else ""
    flt = "a" if f == "q" else f
    rows, total = await db.admin_movies(flt, q, page * PAGE, PAGE)
    _alast[uid] = (page, f)
    pages = max(1, -(-total // PAGE))
    if f == "q":
        head = f"📋 <b>Kinolar</b> • 🔎 «{escape(q)}»"
    else:
        head = f"📋 <b>Kinolar</b> • {dict(FILTERS).get(f, 'Hammasi')}"
    kb = []
    if rows:
        start = page * PAGE + 1
        lines = [f"{start + i}. {admin_line(r)}" for i, r in enumerate(rows)]
        text = f"{head}\n📄 Sahifa {page + 1}/{pages} • Jami: {total} ta\n\n" + "\n".join(lines)
        kb += grid([btn(str(start + i), f"a:m:{r['id']}") for i, r in enumerate(rows)], 5)
        nav = []
        if page > 0:
            nav.append(btn("⬅️ Oldingi", f"a:list:{page - 1}:{f}"))
        if page + 1 < pages:
            nav.append(btn("Keyingi ➡️", f"a:list:{page + 1}:{f}"))
        if nav:
            kb.append(nav)
    else:
        text = f"{head}\n\nHech narsa topilmadi."
    chips = [
        btn(("✅ " if code == f else "") + label, f"a:list:0:{code}") for code, label in FILTERS
    ]
    kb += grid(chips, 3)
    if f == "q":
        kb.append([btn("🔎 Yangi qidiruv", "a:ls"), btn("✖️ Tozalash", "a:list:0:a")])
    else:
        kb.append([btn("🔎 Qidirish", "a:ls")])
    kb.append([btn("◀️ Orqaga", "a:home")])
    return text, kb_of(kb)


@router.callback_query(F.data.regexp(r"^a:list:\d+:[amsphqe]$"))
async def on_list(c: CallbackQuery, state: FSMContext):
    await state.clear()
    _, _, page, f = c.data.split(":")
    await c.answer()
    text, kb = await list_view(c.from_user.id, int(page), f)
    await S(c, text, kb)


@router.callback_query(F.data == "a:lr")
async def list_return(c: CallbackQuery, state: FSMContext):
    """Oxirgi ko'rilgan ro'yxat sahifasiga qaytadi."""
    await state.clear()
    await c.answer()
    page, f = _alast.get(c.from_user.id, (0, "a"))
    text, kb = await list_view(c.from_user.id, page, f)
    await S(c, text, kb)


@router.callback_query(F.data == "a:ls")
async def list_search_ask(c: CallbackQuery, state: FSMContext):
    await state.set_state(Search.wait)
    await c.answer()
    await S(c, "🔎 Kino nomini yozing (har qanday tilda):", kb_of([[btn("❌ Bekor qilish", "a:lr")]]))


@router.message(Search.wait, F.text & ~F.text.startswith("/"))
async def list_search_do(m: Message, state: FSMContext):
    await state.clear()
    await ui.delete_message(m)
    _aq[m.from_user.id] = m.text.strip()
    text, kb = await list_view(m.from_user.id, 0, "q")
    await S(m, text, kb)


# ---------------- kino sahifasi ----------------
async def movie_page(movie_id: int):
    movie = await db.get_movie(movie_id)
    if not movie:
        return None
    aliases = [a for a in await db.get_aliases(movie_id) if a != movie["title"]]
    summary = await db.file_summary(movie_id)
    year = f" ({movie['year']})" if movie["year"] else ""
    hidden = "  🙈 yashirin" if movie["hidden"] else ""
    kind = "📺 Serial" if movie["is_series"] else "🎬 Kino"
    lines = [
        f"🎬 <b>{escape(movie['title'])}</b>{year}{hidden}",
        f"📂 {escape(movie['category'] or '—')} • {kind}",
        f"💎 Premium: {'ha' if movie['is_premium'] else 'yo`q'}  •  🎙 Til: {cards.audio_label(movie['audio'], 'uz')}",
    ]
    if movie["is_series"]:
        lines.append(f"📡 Holat: {status_label(movie['series_status'])}")
    if movie["genres"]:
        lines.append("🎭 " + escape(", ".join(movie["genres"])))
    if movie["imdb_rating"]:
        lines.append(f"⭐ IMDb {movie['imdb_rating']}")
    lines.append(f"🌐 Tavsif (uz): {'✅' if movie['overview_uz'] else '—'}")
    if aliases:
        lines.append("🏷 " + escape(", ".join(aliases)))
    if summary:
        for r in summary:
            qs = ", ".join(utils.q_label(q) for q in sorted(r["qs"], key=utils.q_key, reverse=True))
            lines.append(f"📀 {qs}" if r["season"] == 0 else f"📼 {r['season']}-fasl: {r['eps']} qism ({qs})")
    else:
        lines.append("📁 Fayl yo'q")
    lines.append(f"👁 Yuklashlar: {movie['views']}")
    lines.append(f"🔗 <code>{movie_link(movie['code'])}</code>")
    prem_text = "💎 Premium: o'chirish" if movie["is_premium"] else "💎 Premium qilish"
    hide_text = "👁 Ko'rsatish" if movie["hidden"] else "🙈 Yashirish"
    rows = [
        [btn("➕ Fayl / qism qo'shish", f"a:f:{movie_id}")],
        [btn(prem_text, f"a:p:{movie_id}"), btn("🎙 Til", f"a:l:{movie_id}")],
    ]
    if movie["is_series"]:
        rows.append([btn("📡 Holat: " + status_label(movie["series_status"]), f"a:ss:{movie_id}")])
    rows += [
        [btn("🏷 Qo'shimcha nom", f"a:t:{movie_id}"), btn("✏️ Nomi", f"a:n:{movie_id}")],
        [btn("📝 Tavsif (uz)", f"a:o:{movie_id}"), btn("🌐 Tarjima", f"a:tr:{movie_id}")],
        [btn("📂 Kategoriya", f"a:c:{movie_id}"), btn("📣 Kanalga e'lon", f"a:an:{movie_id}")],
    ]
    if movie["tmdb_id"]:
        rows.append([btn("🔄 Ma'lumotni yangilash (TMDB)", f"a:u:{movie_id}")])
    rows.append([btn(hide_text, f"a:h:{movie_id}"), btn("🗑 O'chirish", f"a:r:{movie_id}")])
    rows.append([btn("◀️ Ro'yxat", "a:lr")])
    return "\n".join(lines), kb_of(rows)


async def open_page(c: CallbackQuery, movie_id: int):
    page = await movie_page(movie_id)
    if not page:
        await c.answer("Topilmadi", show_alert=True)
        return False
    await S(c, page[0], page[1])
    return True


@router.callback_query(F.data.regexp(r"^a:m:\d+$"))
async def on_movie(c: CallbackQuery, state: FSMContext):
    await state.clear()
    if await open_page(c, int(c.data.split(":")[2])):
        await c.answer()


@router.callback_query(F.data.regexp(r"^a:f:\d+$"))
async def on_add_files(c: CallbackQuery, state: FSMContext):
    movie_id = int(c.data.split(":")[2])
    movie = await db.get_movie(movie_id)
    if not movie:
        await c.answer("Topilmadi", show_alert=True)
        return
    await c.answer()
    if movie["is_series"]:
        text, kb = await season_picker(movie_id)
        await S(c, text, kb)
    else:
        await ui.delete_message(c.message)
        await begin_upload(c.bot, c.message.chat.id, state, movie_id, 0)


@router.callback_query(F.data.regexp(r"^a:sp:\d+$"))
async def on_season_picker(c: CallbackQuery):
    text, kb = await season_picker(int(c.data.split(":")[2]))
    await c.answer()
    await S(c, text, kb)


# ---------------- kanalga e'lon ----------------
async def build_post(movie_id: int, spec: str):
    """(izoh, tugma, poster) qaytaradi. spec: 'n' (to'liq post) yoki 'e{fasl}-{dan}-{gacha}' (yangi qism)."""
    movie = await db.get_movie(movie_id)
    m = dict(movie)
    footer = db.get_setting("ann_footer", DEFAULT_FOOTER).strip()
    summary = await db.file_summary(movie_id)
    seasons = await db.season_counts(movie_id) if movie["is_series"] else None
    if spec == "n":
        quals = {q for r in summary for q in r["qs"]}
        caption = cards.announce_caption(m, "n", footer, quals=quals, seasons=seasons)
    else:
        season, a, b = (int(x) for x in spec[1:].split("-"))
        quals = {q for r in summary if r["season"] == season for q in r["qs"]}
        caption = cards.announce_caption(
            m, "e", footer, quals=quals, season=season, ep_from=a, ep_to=b
        )
    return caption, cards.announce_kb(movie["code"]), movie["poster_id"] or movie["poster_url"]


@router.callback_query(F.data.regexp(r"^a:an:\d+$"))
async def announce_start(c: CallbackQuery):
    movie_id = int(c.data.split(":")[2])
    movie = await db.get_movie(movie_id)
    if not movie:
        await c.answer("Topilmadi", show_alert=True)
        return
    if not db.get_setting("ann_channel"):
        await c.answer("Avval Sozlamalarda e'lon kanalini belgilang", show_alert=True)
        return
    await c.answer()
    if not movie["is_series"]:
        caption, _kb, poster = await build_post(movie_id, "n")
        rows = [[btn("✅ Kanalga joylash", f"a:ak:{movie_id}:n")], [btn("◀️ Orqaga", f"a:m:{movie_id}")]]
        await S(c, caption, kb_of(rows), photo=poster)
        return
    counts = await db.season_counts(movie_id)
    rows = [[btn("📣 To'liq post (serial haqida)", f"a:av:{movie_id}:n")]]
    if counts:
        last_season = max(counts)
        last_ep = await db.max_episode(movie_id, last_season)
        rows.append([btn(f"🆕 Yangi qism ({last_season}-fasl, {last_ep}-qism)", f"a:av:{movie_id}:e{last_season}-{last_ep}-{last_ep}")])
    rows.append([btn("◀️ Orqaga", f"a:m:{movie_id}")])
    await S(c, "📣 <b>Qanday post joylaymiz?</b>", kb_of(rows))


@router.callback_query(F.data.regexp(r"^a:av:\d+:(n|e\d+-\d+-\d+)$"))
async def announce_preview(c: CallbackQuery):
    _, _, movie_id, spec = c.data.split(":")
    movie_id = int(movie_id)
    if not db.get_setting("ann_channel"):
        await c.answer("Avval Sozlamalarda e'lon kanalini belgilang", show_alert=True)
        return
    await c.answer()
    caption, _kb, poster = await build_post(movie_id, spec)
    rows = [[btn("✅ Kanalga joylash", f"a:ak:{movie_id}:{spec}")], [btn("◀️ Orqaga", f"a:m:{movie_id}")]]
    await S(c, caption, kb_of(rows), photo=poster)


@router.callback_query(F.data.regexp(r"^a:ak:\d+:(n|e\d+-\d+-\d+)$"))
async def announce_send(c: CallbackQuery):
    _, _, movie_id, spec = c.data.split(":")
    movie_id = int(movie_id)
    channel = db.get_setting("ann_channel")
    if not channel:
        await c.answer("E'lon kanali belgilanmagan", show_alert=True)
        return
    caption, kb, poster = await build_post(movie_id, spec)
    try:
        if poster:
            await c.bot.send_photo(int(channel), poster, caption=caption, reply_markup=kb, parse_mode="HTML")
        else:
            await c.bot.send_message(int(channel), caption, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        await c.answer(f"Joylab bo'lmadi: {e}"[:190], show_alert=True)
        return
    await c.answer("✅ Kanalga joylandi")
    await open_page(c, movie_id)


# ---------------- tahrirlash ----------------
@router.callback_query(F.data.regexp(r"^a:p:\d+$"))
async def toggle_premium(c: CallbackQuery):
    movie_id = int(c.data.split(":")[2])
    val = await db.toggle_premium(movie_id)
    await c.answer("💎 Premium qilindi" if val else "Premium o'chirildi")
    await open_page(c, movie_id)


@router.callback_query(F.data.regexp(r"^a:ss:\d+$"))
async def toggle_status(c: CallbackQuery):
    movie_id = int(c.data.split(":")[2])
    val = await db.toggle_series_status(movie_id)
    await c.answer("📡 " + status_label(val))
    await open_page(c, movie_id)


@router.callback_query(F.data.regexp(r"^a:l:\d+$"))
async def audio_pick(c: CallbackQuery):
    movie_id = int(c.data.split(":")[2])
    buttons = [btn(v[0], f"a:ls:{movie_id}:{code}") for code, v in cards.AUDIO.items()]
    rows = grid(buttons, 2)
    rows.append([btn("◀️ Orqaga", f"a:m:{movie_id}")])
    await c.message.edit_reply_markup(reply_markup=kb_of(rows))
    await c.answer()


@router.callback_query(F.data.regexp(r"^a:ls:\d+:\w+$"))
async def audio_set(c: CallbackQuery):
    _, _, movie_id, code = c.data.split(":")
    await db.set_field(int(movie_id), "audio", code)
    await c.answer("✅")
    await open_page(c, int(movie_id))


@router.callback_query(F.data.regexp(r"^a:u:\d+$"))
async def on_refresh_meta(c: CallbackQuery):
    movie_id = int(c.data.split(":")[2])
    movie = await db.get_movie(movie_id)
    if not movie or not movie["tmdb_id"]:
        await c.answer("TMDB ma'lumoti yo'q", show_alert=True)
        return
    await c.answer("Yangilanmoqda...")
    try:
        d = await tmdb.details(movie["tmdb_type"], movie["tmdb_id"])
    except tmdb.TMDBError as e:
        await ui.flash(c.bot, c.message.chat.id, f"⚠️ {escape(str(e))}")
        return
    await db.update_meta(movie_id, d)
    tr_err = await translate_movie(movie_id)  # faqat yo'q bo'lgan o'zbekcha matnlar tarjima qilinadi
    await open_page(c, movie_id)
    tmdb_part = f"TMDB ✅ {d['rating']:.1f}" if d.get("rating") else "TMDB —"
    tr_part = f"\n🌐 ⚠️ {escape(tr_err)}" if tr_err else ""
    await ui.flash(c.bot, c.message.chat.id, f"✅ Yangilandi\n{tmdb_part}\n{escape(imdb_status(d))}{tr_part}", 7)


@router.callback_query(F.data.regexp(r"^a:tr:\d+$"))
async def on_translate(c: CallbackQuery):
    movie_id = int(c.data.split(":")[2])
    await c.answer("Tarjima qilinmoqda...")
    err = await translate_movie(movie_id, force=True)
    await open_page(c, movie_id)
    await ui.flash(c.bot, c.message.chat.id, f"🌐 ⚠️ {escape(err)}" if err else "🌐 ✅ Tarjima yangilandi", 6)


def ask_kb(movie_id: int) -> InlineKeyboardMarkup:
    return kb_of([[btn("❌ Bekor qilish", f"a:m:{movie_id}")]])


@router.callback_query(F.data.regexp(r"^a:o:\d+$"))
async def overview_start(c: CallbackQuery, state: FSMContext):
    movie_id = int(c.data.split(":")[2])
    await state.clear()
    await state.set_state(Edit.overview)
    await state.update_data(movie_id=movie_id)
    await c.answer()
    await S(
        c,
        "📝 O'zbekcha tavsifni yozing (400 belgigacha yaxshi).\n"
        "Bu matn avtomatik tarjimaning o'rniga kartochkada va e'londa chiqadi.",
        ask_kb(movie_id),
    )


@router.message(Edit.overview, F.text & ~F.text.startswith("/"))
async def overview_save(m: Message, state: FSMContext):
    movie_id = (await state.get_data())["movie_id"]
    await state.clear()
    await ui.delete_message(m)
    await db.set_field(movie_id, "overview_uz", m.text.strip())
    page = await movie_page(movie_id)
    await S(m, page[0], page[1])


@router.callback_query(F.data.regexp(r"^a:t:\d+$"))
async def alias_start(c: CallbackQuery, state: FSMContext):
    movie_id = int(c.data.split(":")[2])
    await state.clear()
    await state.set_state(Edit.alias)
    await state.update_data(movie_id=movie_id)
    await c.answer()
    await S(c, "🏷 Qo'shimcha nomni yozing (masalan, o'zbekcha nomi).", ask_kb(movie_id))


@router.message(Edit.alias, F.text & ~F.text.startswith("/"))
async def alias_save(m: Message, state: FSMContext):
    movie_id = (await state.get_data())["movie_id"]
    await state.clear()
    await ui.delete_message(m)
    await db.add_alias(movie_id, m.text.strip())
    page = await movie_page(movie_id)
    await S(m, page[0], page[1])


@router.callback_query(F.data.regexp(r"^a:n:\d+$"))
async def title_start(c: CallbackQuery, state: FSMContext):
    movie_id = int(c.data.split(":")[2])
    await state.clear()
    await state.set_state(Edit.title)
    await state.update_data(movie_id=movie_id)
    await c.answer()
    await S(c, "✏️ Yangi nomni yozing.", ask_kb(movie_id))


@router.message(Edit.title, F.text & ~F.text.startswith("/"))
async def title_save(m: Message, state: FSMContext):
    movie_id = (await state.get_data())["movie_id"]
    await state.clear()
    await ui.delete_message(m)
    await db.set_title(movie_id, m.text.strip())
    page = await movie_page(movie_id)
    await S(m, page[0], page[1])


@router.callback_query(F.data.regexp(r"^a:c:\d+$"))
async def category_pick(c: CallbackQuery):
    movie_id = int(c.data.split(":")[2])
    rows = grid([btn(cat, f"a:cs:{movie_id}:{i}") for i, cat in enumerate(CATEGORIES)], 2)
    rows.append([btn("◀️ Orqaga", f"a:m:{movie_id}")])
    await c.message.edit_reply_markup(reply_markup=kb_of(rows))
    await c.answer()


@router.callback_query(F.data.regexp(r"^a:cs:\d+:\d+$"))
async def category_set(c: CallbackQuery):
    _, _, movie_id, idx = c.data.split(":")
    await db.set_category(int(movie_id), CATEGORIES[int(idx)])
    await c.answer("✅")
    await open_page(c, int(movie_id))


@router.callback_query(F.data.regexp(r"^a:h:\d+$"))
async def toggle_hide(c: CallbackQuery):
    movie_id = int(c.data.split(":")[2])
    hidden = await db.toggle_hidden(movie_id)
    await c.answer("🙈 Yashirildi" if hidden else "👁 Ko'rinadigan bo'ldi")
    await open_page(c, movie_id)


@router.callback_query(F.data.regexp(r"^a:r:\d+$"))
async def remove_ask(c: CallbackQuery):
    movie_id = int(c.data.split(":")[2])
    await c.answer()
    await S(
        c,
        "🗑 Rostdan ham o'chirilsinmi?\nBarcha fayllari bilan o'chib ketadi.",
        kb_of([[btn("✅ Ha, o'chirish", f"a:ry:{movie_id}"), btn("❌ Yo'q", f"a:m:{movie_id}")]]),
    )


@router.callback_query(F.data.regexp(r"^a:ry:\d+$"))
async def remove_do(c: CallbackQuery):
    ok = await db.delete_movie(int(c.data.split(":")[2]))
    await c.answer("✅ O'chirildi" if ok else "Topilmadi")
    page, f = _alast.get(c.from_user.id, (0, "a"))
    text, kb = await list_view(c.from_user.id, page, f)
    await S(c, text, kb)


# ---------------- zaxira (eng oxirida turishi kerak) ----------------
@router.callback_query(F.data.regexp(r"^a:(up|dr|tm):"))
async def expired(c: CallbackQuery):
    await c.answer("Sessiya tugagan (bot qayta ishga tushgan). Qaytadan boshlang: /admin", show_alert=True)


@router.message(StateFilter(Add, Edit, Banner, Cfg, Search))
async def wrong_input(m: Message):
    await ui.delete_message(m)
    await ui.flash(m.bot, m.chat.id, "⚠️ Iltimos, so'ralgan narsani yuboring yoki tugmani bosing.")
