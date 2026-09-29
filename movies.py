import logging
from html import escape
from urllib.parse import quote

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import database as db
import utils
from locales import t

router = Router()

PAGE = 8
EP_PAGE = 30


def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def grid(buttons: list, per_row: int) -> list:
    return [buttons[i : i + per_row] for i in range(0, len(buttons), per_row)]


def kb_of(rows: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------- kino kartochkasi ----------------
async def card_kb(lang: str, movie, fav: bool) -> InlineKeyboardMarkup:
    movie_id = movie["id"]
    rows = []
    if movie["is_series"]:
        counts = await db.season_counts(movie_id)
        buttons = [btn(t(lang, "season_btn").format(n=s), f"se:{movie_id}:{s}") for s in sorted(counts)]
        rows += grid(buttons, 3)
    else:
        quals = sorted(await db.list_qualities(movie_id, 0, 0), key=utils.q_key, reverse=True)
        if quals:
            rows.append([btn(f"📥 {utils.q_label(q)}", f"dl:{movie_id}:0:0:{q}") for q in quals])
    rows.append([btn(t(lang, "fav_remove" if fav else "fav_add"), f"fav:{movie_id}")])
    link = f"https://t.me/{utils.BOT_USERNAME}?start={movie['code']}"
    share_url = f"https://t.me/share/url?url={quote(link)}&text={quote('🎬 ' + movie['title'])}"
    rows.append([InlineKeyboardButton(text=t(lang, "share"), url=share_url)])
    return kb_of(rows)


def card_text(movie) -> str:
    lines = [f"🎬 <b>{escape(movie['title'])}</b>"]
    meta = []
    if movie["category"]:
        meta.append(f"📂 {escape(movie['category'])}")
    if movie["year"]:
        meta.append(f"📅 {movie['year']}")
    if meta:
        lines.append(" • ".join(meta))
    if movie["genres"]:
        lines.append("🎭 " + escape(", ".join(movie["genres"])))
    if movie["rating"]:
        lines.append(f"⭐ {movie['rating']:.1f}")
    return "\n".join(lines)


async def send_card(target: Message, user_id: int, lang: str, movie):
    if not movie or movie["hidden"]:
        await target.answer(t(lang, "not_found"))
        return
    fav = await db.is_fav(user_id, movie["id"])
    kb = await card_kb(lang, movie, fav)
    text = card_text(movie)
    photo = movie["poster_id"] or movie["poster_url"]
    if photo:
        try:
            sent = await target.answer_photo(photo, caption=text, reply_markup=kb, parse_mode="HTML")
            if not movie["poster_id"] and sent.photo:
                await db.set_poster_id(movie["id"], sent.photo[-1].file_id)
            return
        except Exception as e:
            logging.warning("Posterni yuborib bo'lmadi: %s", e)
    await target.answer(text, reply_markup=kb, parse_mode="HTML")


async def send_media(msg: Message, movie, season: int, episode: int, quality: str) -> bool:
    f = await db.get_file(movie["id"], season, episode, quality)
    if not f:
        return False
    default = f"🎬 {escape(movie['title'])}"
    if season:
        default += f" • S{season:02d}E{episode:02d}"
    default += f" • {utils.q_label(quality)}"
    caption = f["caption"] or default  # admin yuborgan izoh (bold bilan) aynan chiqadi
    if f["file_type"] == "video":
        await msg.answer_video(f["file_id"], caption=caption, parse_mode="HTML")
    else:
        await msg.answer_document(f["file_id"], caption=caption, parse_mode="HTML")
    await db.add_view(movie["id"])
    return True


# ---------------- qidiruv ----------------
def list_kb(rows) -> InlineKeyboardMarkup:
    return kb_of([[btn(r["title"], f"movie:{r['id']}")] for r in rows])


def search_kb(rows, page: int, has_next: bool, q: str) -> InlineKeyboardMarkup:
    kb = [[btn(r["title"], f"movie:{r['id']}")] for r in rows]
    nav = []
    if page > 0:
        nav.append(btn("⬅️", f"sr:{page - 1}:{q}"))
    if has_next:
        nav.append(btn("➡️", f"sr:{page + 1}:{q}"))
    if nav:
        kb.append(nav)
    return kb_of(kb)


async def run_search(q: str, page: int):
    rows = await db.search_movies(q, page * PAGE, PAGE + 1)
    return rows[:PAGE], len(rows) > PAGE


@router.message(Command("favorites"))
async def favorites(m: Message):
    lang = await db.get_lang(m.from_user.id) or "uz"
    if not await utils.gate(m.bot, m.from_user.id, lang, m):
        return
    rows = await db.list_favs(m.from_user.id)
    if not rows:
        await m.answer(t(lang, "favorites_empty"))
        return
    await m.answer(t(lang, "favorites_title"), reply_markup=list_kb(rows))


@router.message(F.text & ~F.text.startswith("/"))
async def text_handler(m: Message):
    lang = await db.get_lang(m.from_user.id) or "uz"
    if not await utils.gate(m.bot, m.from_user.id, lang, m):
        return
    # callback_data 64 baytdan oshmasligi uchun qidiruv matnini qisqartiramiz
    q = m.text.strip().encode()[:40].decode(errors="ignore")
    rows, has_next = await run_search(q, 0)
    if not rows:
        await m.answer(t(lang, "not_found"))
        return
    await m.answer(t(lang, "search_results"), reply_markup=search_kb(rows, 0, has_next, q))


@router.callback_query(F.data.startswith("sr:"))
async def search_page(c: CallbackQuery):
    _, page, q = c.data.split(":", 2)
    page = int(page)
    rows, has_next = await run_search(q, page)
    if not rows:
        await c.answer()
        return
    await c.message.edit_reply_markup(reply_markup=search_kb(rows, page, has_next, q))
    await c.answer()


@router.callback_query(F.data.startswith("movie:"))
async def open_movie(c: CallbackQuery):
    lang = await db.get_lang(c.from_user.id) or "uz"
    movie = await db.get_movie(int(c.data.split(":")[1]))
    await send_card(c.message, c.from_user.id, lang, movie)
    await c.answer()


# ---------------- seriallar: fasl va qismlar ----------------
async def ep_kb(movie_id: int, season: int, page: int) -> InlineKeyboardMarkup:
    total = await db.count_episodes(movie_id, season)
    eps = await db.list_episodes(movie_id, season, page * EP_PAGE, EP_PAGE)
    buttons = [btn(str(r["episode"]), f"ep:{movie_id}:{season}:{r['episode']}") for r in eps]
    rows = grid(buttons, 5)
    nav = []
    if page > 0:
        nav.append(btn("⬅️", f"epp:{movie_id}:{season}:{page - 1}"))
    if (page + 1) * EP_PAGE < total:
        nav.append(btn("➡️", f"epp:{movie_id}:{season}:{page + 1}"))
    if nav:
        rows.append(nav)
    return kb_of(rows)


@router.callback_query(F.data.startswith("se:"))
async def open_season(c: CallbackQuery):
    _, movie_id, season = c.data.split(":")
    lang = await db.get_lang(c.from_user.id) or "uz"
    movie = await db.get_movie(int(movie_id))
    if not movie or movie["hidden"]:
        await c.answer(t(lang, "not_found"), show_alert=True)
        return
    kb = await ep_kb(int(movie_id), int(season), 0)
    title = f"📺 {escape(movie['title'])} — {t(lang, 'season_btn').format(n=season)[2:]}"
    await c.message.answer(f"{title}\n{t(lang, 'choose_ep')}", reply_markup=kb, parse_mode="HTML")
    await c.answer()


@router.callback_query(F.data.startswith("epp:"))
async def episode_page(c: CallbackQuery):
    _, movie_id, season, page = c.data.split(":")
    kb = await ep_kb(int(movie_id), int(season), int(page))
    await c.message.edit_reply_markup(reply_markup=kb)
    await c.answer()


@router.callback_query(F.data.startswith("ep:"))
async def open_episode(c: CallbackQuery):
    _, movie_id, season, episode = c.data.split(":")
    lang = await db.get_lang(c.from_user.id) or "uz"
    if not await utils.gate(c.bot, c.from_user.id, lang, c.message):
        await c.answer()
        return
    movie = await db.get_movie(int(movie_id))
    if not movie or movie["hidden"]:
        await c.answer(t(lang, "not_found"), show_alert=True)
        return
    season, episode = int(season), int(episode)
    quals = sorted(await db.list_qualities(movie["id"], season, episode), key=utils.q_key, reverse=True)
    if not quals:
        await c.answer(t(lang, "not_found"), show_alert=True)
        return
    if len(quals) == 1:
        await send_media(c.message, movie, season, episode, quals[0])
    else:
        rows = [[btn(f"📥 {utils.q_label(q)}", f"dl:{movie['id']}:{season}:{episode}:{q}") for q in quals]]
        await c.message.answer(
            f"{escape(movie['title'])} • {episode}\n{t(lang, 'choose_quality')}",
            reply_markup=kb_of(rows),
            parse_mode="HTML",
        )
    await c.answer()


@router.callback_query(F.data.startswith("dl:"))
async def download(c: CallbackQuery):
    _, movie_id, season, episode, quality = c.data.split(":")
    lang = await db.get_lang(c.from_user.id) or "uz"
    if not await utils.gate(c.bot, c.from_user.id, lang, c.message):
        await c.answer()
        return
    movie = await db.get_movie(int(movie_id))
    if not movie or movie["hidden"]:
        await c.answer(t(lang, "not_found"), show_alert=True)
        return
    ok = await send_media(c.message, movie, int(season), int(episode), quality)
    if not ok:
        await c.answer(t(lang, "not_found"), show_alert=True)
        return
    await c.answer()


@router.callback_query(F.data.startswith("fav:"))
async def toggle_favorite(c: CallbackQuery):
    movie_id = int(c.data.split(":")[1])
    lang = await db.get_lang(c.from_user.id) or "uz"
    movie = await db.get_movie(movie_id)
    if not movie or movie["hidden"]:
        await c.answer(t(lang, "not_found"), show_alert=True)
        return
    added = await db.toggle_fav(c.from_user.id, movie_id)
    await c.message.edit_reply_markup(reply_markup=await card_kb(lang, movie, added))
    await c.answer(t(lang, "fav_added" if added else "fav_removed"))
