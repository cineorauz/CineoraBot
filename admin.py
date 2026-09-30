import asyncio
import logging
import time
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

import config
import database as db
import tmdb
import utils
from genres import CATEGORIES

router = Router()
router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

PAGE = 8
BTN_ADD = "➕ Qo'shish"
BTN_LIST = "📋 Ro'yxat"
BTN_STATS = "📊 Statistika"

# Bir vaqtda ko'p fayl yuborilganda ular navbat bilan ishlanadi (tartib buzilmasligi uchun)
_locks: dict[int, asyncio.Lock] = {}


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


# ---------------- yordamchilar ----------------
def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def grid(buttons: list, per_row: int = 2) -> list:
    return [buttons[i : i + per_row] for i in range(0, len(buttons), per_row)]


def kb_of(rows: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_ADD), KeyboardButton(text=BTN_LIST)],
            [KeyboardButton(text=BTN_STATS)],
        ],
        resize_keyboard=True,
    )


def movie_link(code: str) -> str:
    return f"https://t.me/{utils.BOT_USERNAME}?start={code}"


def imdb_status(d) -> str:
    if d.get("imdb_rating"):
        return f"IMDb ✅ {d['imdb_rating']}"
    return f"IMDb ⚠️ {d.get('omdb_error') or 'topilmadi'}"


async def safe_edit(msg: Message, text: str, kb=None):
    try:
        await msg.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass


# ---------------- asosiy buyruqlar va tugmalar ----------------
@router.message(Command("admin"))
async def admin_menu(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("🛠 Admin panel. Pastdagi tugmalardan foydalaning.", reply_markup=main_kb())


@router.message(Command("cancel"))
async def cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Bekor qilindi.", reply_markup=main_kb())


@router.message(Command("ping"))
async def ping(m: Message):
    db_ms = await db.ping()
    t0 = time.perf_counter()
    await m.bot.get_me()
    tg_ms = (time.perf_counter() - t0) * 1000
    await m.answer(f"🏓 Baza: {db_ms:.0f} ms\n📡 Telegram: {tg_ms:.0f} ms")


@router.message(F.text == BTN_ADD)
async def start_add(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Add.query)
    await m.answer("🔎 Kino yoki serial nomini yozing (TMDB'dan qidiraman).\n\nBekor qilish: /cancel")


@router.message(F.text == BTN_LIST)
async def open_list(m: Message, state: FSMContext):
    await state.clear()
    view = await list_view(0)
    if not view:
        await m.answer("Hozircha kinolar yo'q.")
        return
    await m.answer(view[0], reply_markup=view[1])


@router.message(F.text == BTN_STATS)
async def show_stats(m: Message, state: FSMContext):
    await state.clear()
    s = await db.stats()
    lines = [
        "📊 <b>Statistika</b>",
        f"👥 Foydalanuvchilar: {s['users']} (oxirgi 24 soatda +{s['users_day']})",
        f"🎬 Kinolar: {s['movies']}  •  📺 Seriallar: {s['series']}",
        f"📁 Fayllar: {s['files']}",
    ]
    if s["top"]:
        lines.append("\n🔥 <b>Eng ko'p yuklangan:</b>")
        for i, r in enumerate(s["top"], 1):
            lines.append(f"{i}. {escape(r['title'])} — {r['views']}")
    await m.answer("\n".join(lines), parse_mode="HTML")


# ---------------- qo'shish: TMDB qidiruv ----------------
@router.message(Add.query, F.text & ~F.text.startswith("/"))
async def on_query(m: Message, state: FSMContext):
    try:
        results = await tmdb.search(m.text.strip())
    except tmdb.TMDBError as e:
        await m.answer(
            f"⚠️ {e}\n\nQo'lda kiritishingiz mumkin:",
            reply_markup=kb_of([[btn("✍️ Qo'lda kiritish", "a:tm:manual")]]),
        )
        return
    rows = []
    for r in results:
        kind = "Kino" if r["type"] == "movie" else "Serial"
        year = f" ({r['year']})" if r["year"] else ""
        rows.append([btn(f"{r['title']}{year} • {kind}", f"a:tm:{r['type']}:{r['id']}")])
    rows.append([btn("✍️ Qo'lda kiritish", "a:tm:manual")])
    text = "Topilganlar:" if results else "😕 TMDB'da topilmadi. Boshqa nom yozing yoki qo'lda kiriting."
    await m.answer(text, reply_markup=kb_of(rows))


@router.callback_query(Add.query, F.data == "a:tm:manual")
async def on_manual(c: CallbackQuery, state: FSMContext):
    await state.set_state(Add.manual_title)
    await c.message.answer("✍️ Nomni yozing:")
    await c.answer()


@router.message(Add.manual_title, F.text & ~F.text.startswith("/"))
async def on_manual_title(m: Message, state: FSMContext):
    title = m.text.strip()
    draft = {
        "title": title,
        "aliases": [title],
        "year": None,
        "genres": [],
        "rating": None,
        "poster_url": None,
        "tmdb_id": None,
        "tmdb_type": None,
        "is_series": False,
        "seasons_total": 0,
        "category": "Kinolar",
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
        await c.message.answer(f"⚠️ {e}")
        return
    await state.update_data(draft=draft)
    await state.set_state(Add.draft)
    await c.message.delete()
    await show_preview(c.message, draft)


# ---------------- qo'shish: oldindan ko'rish ----------------
def preview_text(d: dict) -> str:
    year = f" ({d['year']})" if d.get("year") else ""
    kind = "📺 Serial" if d["is_series"] else "🎬 Kino"
    lines = [
        f"🎬 <b>{escape(d['title'])}</b>{year}",
        f"📂 {escape(d['category'])} • {kind}",
    ]
    if d.get("genres"):
        lines.append("🎭 " + escape(", ".join(d["genres"])))
    if d.get("tmdb_id"):
        tmdb_part = f"TMDB ⭐ {d['rating']:.1f}" if d.get("rating") else "TMDB —"
        lines.append(f"{tmdb_part}  •  {escape(imdb_status(d))}")
    if d["is_series"] and d.get("seasons_total"):
        lines.append(f"📼 Fasllar: {d['seasons_total']}")
    return "\n".join(lines)


def preview_kb() -> InlineKeyboardMarkup:
    return kb_of(
        [
            [btn("✅ Tasdiqlash", "a:dr:ok")],
            [btn("📂 Kategoriya", "a:dr:cat"), btn("🔁 Kino/Serial", "a:dr:type")],
            [btn("❌ Bekor qilish", "a:dr:cancel")],
        ]
    )


def cat_kb() -> InlineKeyboardMarkup:
    buttons = [btn(c, f"a:dr:c:{i}") for i, c in enumerate(CATEGORIES)]
    return kb_of(grid(buttons, 2))


async def show_preview(msg: Message, d: dict):
    text, kb = preview_text(d), preview_kb()
    if d.get("poster_url"):
        try:
            await msg.answer_photo(d["poster_url"], caption=text, reply_markup=kb, parse_mode="HTML")
            return
        except Exception as e:
            logging.warning("Posterni yuborib bo'lmadi: %s", e)
    await msg.answer(text, reply_markup=kb, parse_mode="HTML")


async def refresh_preview(msg: Message, d: dict):
    text, kb = preview_text(d), preview_kb()
    try:
        if msg.photo:
            await msg.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
        else:
            await msg.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass


@router.callback_query(Add.draft, F.data == "a:dr:cat")
async def draft_cat(c: CallbackQuery):
    await c.message.edit_reply_markup(reply_markup=cat_kb())
    await c.answer()


@router.callback_query(Add.draft, F.data.regexp(r"^a:dr:c:\d+$"))
async def draft_set_cat(c: CallbackQuery, state: FSMContext):
    idx = int(c.data.split(":")[3])
    d = (await state.get_data())["draft"]
    d["category"] = CATEGORIES[idx]
    await state.update_data(draft=d)
    await refresh_preview(c.message, d)
    await c.answer()


@router.callback_query(Add.draft, F.data == "a:dr:type")
async def draft_type(c: CallbackQuery, state: FSMContext):
    d = (await state.get_data())["draft"]
    d["is_series"] = not d["is_series"]
    await state.update_data(draft=d)
    await refresh_preview(c.message, d)
    await c.answer()


@router.callback_query(Add.draft, F.data == "a:dr:cancel")
async def draft_cancel(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.delete()
    await c.message.answer("Bekor qilindi.", reply_markup=main_kb())
    await c.answer()


@router.callback_query(Add.draft, F.data == "a:dr:ok")
async def draft_ok(c: CallbackQuery, state: FSMContext):
    d = (await state.get_data())["draft"]
    movie_id, _code = await db.create_movie(d)
    await c.answer("✅ Saqlandi")
    await c.message.edit_reply_markup(reply_markup=None)
    if d["is_series"]:
        await state.clear()
        text, kb = await season_picker(movie_id)
        await c.message.answer(text, reply_markup=kb)
    else:
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
            [
                btn("4K", "a:up:q:2160"),
                btn("1080p", "a:up:q:1080"),
                btn("720p", "a:up:q:720"),
                btn("480p", "a:up:q:480"),
            ],
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
        try:
            await bot.delete_message(chat_id, old)
        except Exception:
            pass
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
    await begin_upload(c.bot, c.message.chat.id, state, movie_id, season)


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
    rows = [[btn("📋 Sahifa", f"a:m:{movie['id']}")]]
    if movie["is_series"]:
        rows.insert(0, [btn("➕ Boshqa fasl", f"a:sp:{movie['id']}")])
    await safe_edit(
        c.message,
        f"✅ Tayyor!\n\n🎬 <b>{escape(movie['title'])}</b>\n"
        f"📁 Shu safar: {len(d['saved'])} ta fayl\n"
        f"🔗 <code>{movie_link(movie['code'])}</code>",
        kb_of(rows),
    )
    await c.answer()


# ---------------- ro'yxat va kino sahifasi ----------------
async def list_view(page: int):
    rows = await db.list_movies(page * PAGE, PAGE + 1)
    has_next = len(rows) > PAGE
    rows = rows[:PAGE]
    if not rows:
        return None
    kb = []
    for r in rows:
        icon = "📺" if r["is_series"] else "🎬"
        hidden = "🙈 " if r["hidden"] else ""
        kb.append([btn(f"{hidden}{icon} {r['title']}", f"a:m:{r['id']}")])
    nav = []
    if page > 0:
        nav.append(btn("⬅️", f"a:list:{page - 1}"))
    if has_next:
        nav.append(btn("➡️", f"a:list:{page + 1}"))
    if nav:
        kb.append(nav)
    return "📋 Kinolar:", kb_of(kb)


@router.callback_query(F.data.regexp(r"^a:list:\d+$"))
async def on_list(c: CallbackQuery):
    view = await list_view(int(c.data.split(":")[2]))
    if not view:
        await c.answer("Kinolar yo'q", show_alert=True)
        return
    await safe_edit(c.message, view[0], view[1])
    await c.answer()


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
    ]
    if movie["genres"]:
        lines.append("🎭 " + escape(", ".join(movie["genres"])))
    if movie["imdb_rating"]:
        lines.append(f"⭐ IMDb {movie['imdb_rating']}")
    if aliases:
        lines.append("🏷 " + escape(", ".join(aliases)))
    if summary:
        for r in summary:
            qs = ", ".join(utils.q_label(q) for q in sorted(r["qs"], key=utils.q_key, reverse=True))
            if r["season"] == 0:
                lines.append(f"📀 {qs}")
            else:
                lines.append(f"📼 {r['season']}-fasl: {r['eps']} qism ({qs})")
    else:
        lines.append("📁 Fayl yo'q")
    lines.append(f"👁 Yuklashlar: {movie['views']}")
    lines.append(f"🔗 <code>{movie_link(movie['code'])}</code>")
    hide_text = "👁 Ko'rsatish" if movie["hidden"] else "🙈 Yashirish"
    rows = [
        [btn("➕ Fayl / qism qo'shish", f"a:f:{movie_id}")],
        [btn("🏷 Qo'shimcha nom", f"a:t:{movie_id}"), btn("✏️ Nomi", f"a:n:{movie_id}")],
        [btn("📂 Kategoriya", f"a:c:{movie_id}")],
    ]
    if movie["tmdb_id"]:
        rows.append([btn("🔄 Ma'lumotni yangilash (TMDB)", f"a:u:{movie_id}")])
    rows.append([btn(hide_text, f"a:h:{movie_id}"), btn("🗑 O'chirish", f"a:r:{movie_id}")])
    rows.append([btn("◀️ Ro'yxat", "a:list:0")])
    return "\n".join(lines), kb_of(rows)


@router.callback_query(F.data.regexp(r"^a:m:\d+$"))
async def on_movie(c: CallbackQuery):
    page = await movie_page(int(c.data.split(":")[2]))
    if not page:
        await c.answer("Topilmadi", show_alert=True)
        return
    await safe_edit(c.message, page[0], page[1])
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
        await safe_edit(c.message, text, kb)
    else:
        await begin_upload(c.bot, c.message.chat.id, state, movie_id, 0)


@router.callback_query(F.data.regexp(r"^a:sp:\d+$"))
async def on_season_picker(c: CallbackQuery):
    text, kb = await season_picker(int(c.data.split(":")[2]))
    await safe_edit(c.message, text, kb)
    await c.answer()


# ---------------- tahrirlash ----------------
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
        await c.message.answer(f"⚠️ {e}")
        return
    await db.update_meta(movie_id, d)
    page = await movie_page(movie_id)
    await safe_edit(c.message, page[0], page[1])
    tmdb_part = f"TMDB ✅ {d['rating']:.1f}" if d.get("rating") else "TMDB —"
    await c.message.answer(f"✅ Ma'lumotlar yangilandi\n{tmdb_part}\n{imdb_status(d)}")


@router.callback_query(F.data.regexp(r"^a:t:\d+$"))
async def alias_start(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(Edit.alias)
    await state.update_data(movie_id=int(c.data.split(":")[2]))
    await c.message.answer("🏷 Qo'shimcha nomni yozing (masalan, o'zbekcha nomi).\nBekor qilish: /cancel")
    await c.answer()


@router.message(Edit.alias, F.text & ~F.text.startswith("/"))
async def alias_save(m: Message, state: FSMContext):
    movie_id = (await state.get_data())["movie_id"]
    await state.clear()
    await db.add_alias(movie_id, m.text.strip())
    page = await movie_page(movie_id)
    await m.answer("✅ Qo'shildi")
    if page:
        await m.answer(page[0], reply_markup=page[1], parse_mode="HTML")


@router.callback_query(F.data.regexp(r"^a:n:\d+$"))
async def title_start(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(Edit.title)
    await state.update_data(movie_id=int(c.data.split(":")[2]))
    await c.message.answer("✏️ Yangi nomni yozing.\nBekor qilish: /cancel")
    await c.answer()


@router.message(Edit.title, F.text & ~F.text.startswith("/"))
async def title_save(m: Message, state: FSMContext):
    movie_id = (await state.get_data())["movie_id"]
    await state.clear()
    await db.set_title(movie_id, m.text.strip())
    page = await movie_page(movie_id)
    await m.answer("✅ O'zgartirildi")
    if page:
        await m.answer(page[0], reply_markup=page[1], parse_mode="HTML")


@router.callback_query(F.data.regexp(r"^a:c:\d+$"))
async def category_pick(c: CallbackQuery):
    movie_id = int(c.data.split(":")[2])
    buttons = [btn(cat, f"a:cs:{movie_id}:{i}") for i, cat in enumerate(CATEGORIES)]
    rows = grid(buttons, 2)
    rows.append([btn("◀️ Orqaga", f"a:m:{movie_id}")])
    await c.message.edit_reply_markup(reply_markup=kb_of(rows))
    await c.answer()


@router.callback_query(F.data.regexp(r"^a:cs:\d+:\d+$"))
async def category_set(c: CallbackQuery):
    _, _, movie_id, idx = c.data.split(":")
    await db.set_category(int(movie_id), CATEGORIES[int(idx)])
    page = await movie_page(int(movie_id))
    await safe_edit(c.message, page[0], page[1])
    await c.answer("✅")


@router.callback_query(F.data.regexp(r"^a:h:\d+$"))
async def toggle_hide(c: CallbackQuery):
    movie_id = int(c.data.split(":")[2])
    hidden = await db.toggle_hidden(movie_id)
    page = await movie_page(movie_id)
    await safe_edit(c.message, page[0], page[1])
    await c.answer("🙈 Yashirildi" if hidden else "👁 Ko'rinadigan bo'ldi")


@router.callback_query(F.data.regexp(r"^a:r:\d+$"))
async def remove_ask(c: CallbackQuery):
    movie_id = int(c.data.split(":")[2])
    await safe_edit(
        c.message,
        "Rostdan ham o'chirilsinmi? Barcha fayllari bilan o'chib ketadi.",
        kb_of([[btn("✅ Ha, o'chirish", f"a:ry:{movie_id}"), btn("❌ Yo'q", f"a:m:{movie_id}")]]),
    )
    await c.answer()


@router.callback_query(F.data.regexp(r"^a:ry:\d+$"))
async def remove_do(c: CallbackQuery):
    ok = await db.delete_movie(int(c.data.split(":")[2]))
    await safe_edit(c.message, "✅ O'chirildi." if ok else "Topilmadi.")
    await c.answer()


# ---------------- zaxira (eng oxirida turishi kerak) ----------------
@router.callback_query(F.data.regexp(r"^a:(up|dr|tm):"))
async def expired(c: CallbackQuery):
    await c.answer("Sessiya tugagan (bot qayta ishga tushgan). Qaytadan boshlang: ➕ Qo'shish", show_alert=True)


@router.message(StateFilter(Add, Edit))
async def wrong_input(m: Message):
    await m.answer("Iltimos, so'ralgan narsani yuboring yoki tugmani bosing.\nBekor qilish: /cancel")
