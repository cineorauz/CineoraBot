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

PAGE = 8
S = ui.show_for

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
    overview = State()


class Banner(StatesGroup):
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


def home_view():
    text = "🛠 <b>Admin panel</b>\n\nBo'limni tanlang 👇"
    kb = kb_of(
        [
            [btn("➕ Qo'shish", "a:add"), btn("📋 Kinolar", "a:list:0")],
            [btn("📥 So'rovlar", "a:reqs"), btn("💎 Premium", "ap:home")],
            [btn("🖼 Bannerlar", "a:bn"), btn("📊 Statistika", "a:stats")],
            [btn("🏓 Tezlik", "a:ping"), btn("🏠 Bot menyusi", "home")],
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
        "seasons_total": 0, "category": "Kinolar", "is_premium": False,
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


def preview_kb() -> InlineKeyboardMarkup:
    return kb_of(
        [
            [btn("✅ Tasdiqlash", "a:dr:ok")],
            [btn("📂 Kategoriya", "a:dr:cat"), btn("🔁 Kino/Serial", "a:dr:type")],
            [btn("💎 Premium", "a:dr:prem")],
            [btn("❌ Bekor qilish", "a:home")],
        ]
    )


def cat_kb() -> InlineKeyboardMarkup:
    return kb_of(grid([btn(c, f"a:dr:c:{i}") for i, c in enumerate(CATEGORIES)], 2))


async def show_preview(target, d: dict):
    await S(target, preview_text(d), preview_kb(), photo=d.get("poster_url"))


async def refresh_preview(c: CallbackQuery, d: dict):
    await S(c, preview_text(d), preview_kb(), keep_photo=True)


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
    rows = []
    if movie["is_series"]:
        rows.append([btn("➕ Boshqa fasl", f"a:sp:{movie['id']}")])
    rows.append([btn("➕ Yana qo'shish", "a:add"), btn("📋 Sahifa", f"a:m:{movie['id']}")])
    rows.append([btn("🛠 Admin panel", "a:home")])
    extra = ""
    if d["saved"] and movie["tmdb_id"]:
        asyncio.create_task(movies.notify_requesters(c.bot, movie))  # so'raganlarga xabar
        extra = "\n🔔 So'ragan foydalanuvchilarga xabar yuborilmoqda"
    await c.answer()
    await S(
        c,
        f"✅ <b>Tayyor!</b>\n\n🎬 <b>{escape(movie['title'])}</b>\n"
        f"📁 Shu safar: {len(d['saved'])} ta fayl{extra}\n"
        f"🔗 <code>{movie_link(movie['code'])}</code>",
        kb_of(rows),
    )


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
        flags = ("🙈 " if r["hidden"] else "") + ("💎 " if r["is_premium"] else "")
        kb.append([btn(f"{flags}{icon} {r['title']}", f"a:m:{r['id']}")])
    nav = []
    if page > 0:
        nav.append(btn("⬅️", f"a:list:{page - 1}"))
    if has_next:
        nav.append(btn("➡️", f"a:list:{page + 1}"))
    if nav:
        kb.append(nav)
    kb.append([btn("◀️ Orqaga", "a:home")])
    return "📋 <b>Kinolar</b>", kb_of(kb)


@router.callback_query(F.data.regexp(r"^a:list:\d+$"))
async def on_list(c: CallbackQuery, state: FSMContext):
    await state.clear()
    view = await list_view(int(c.data.split(":")[2]))
    if not view:
        await c.answer("Kinolar yo'q", show_alert=True)
        return
    await c.answer()
    await S(c, view[0], view[1])


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
        [btn("🏷 Qo'shimcha nom", f"a:t:{movie_id}"), btn("✏️ Nomi", f"a:n:{movie_id}")],
        [btn("📝 Tavsif (uz)", f"a:o:{movie_id}"), btn("🌐 Tarjima", f"a:tr:{movie_id}")],
        [btn("📂 Kategoriya", f"a:c:{movie_id}")],
    ]
    if movie["tmdb_id"]:
        rows.append([btn("🔄 Ma'lumotni yangilash (TMDB)", f"a:u:{movie_id}")])
    rows.append([btn(hide_text, f"a:h:{movie_id}"), btn("🗑 O'chirish", f"a:r:{movie_id}")])
    rows.append([btn("◀️ Ro'yxat", "a:list:0")])
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


# ---------------- tahrirlash ----------------
@router.callback_query(F.data.regexp(r"^a:p:\d+$"))
async def toggle_premium(c: CallbackQuery):
    movie_id = int(c.data.split(":")[2])
    val = await db.toggle_premium(movie_id)
    await c.answer("💎 Premium qilindi" if val else "Premium o'chirildi")
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
        "Bu matn avtomatik tarjimaning o'rniga kartochkada chiqadi.",
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
    view = await list_view(0)
    if view:
        await S(c, view[0], view[1])
    else:
        text, kb = home_view()
        await S(c, text, kb)


# ---------------- zaxira (eng oxirida turishi kerak) ----------------
@router.callback_query(F.data.regexp(r"^a:(up|dr|tm):"))
async def expired(c: CallbackQuery):
    await c.answer("Sessiya tugagan (bot qayta ishga tushgan). Qaytadan boshlang: /admin", show_alert=True)


@router.message(StateFilter(Add, Edit, Banner))
async def wrong_input(m: Message):
    await ui.delete_message(m)
    await ui.flash(m.bot, m.chat.id, "⚠️ Iltimos, so'ralgan narsani yuboring yoki tugmani bosing.")
