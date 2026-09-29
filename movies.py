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


def card_kb(lang: str, movie_id: int, files: dict, fav: bool, title: str) -> InlineKeyboardMarkup:
    rows = []
    quality_row = [
        InlineKeyboardButton(text=f"📥 {q}p", callback_data=f"dl:{movie_id}:{q}")
        for q in ("1080", "720")
        if q in files
    ]
    if quality_row:
        rows.append(quality_row)
    rows.append(
        [
            InlineKeyboardButton(
                text=t(lang, "fav_remove" if fav else "fav_add"),
                callback_data=f"fav:{movie_id}",
            )
        ]
    )
    link = f"https://t.me/{utils.BOT_USERNAME}?start=m{movie_id}"
    share_url = f"https://t.me/share/url?url={quote(link)}&text={quote('🎬 ' + title)}"
    rows.append([InlineKeyboardButton(text=t(lang, "share"), url=share_url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_card(target: Message, user_id: int, lang: str, movie_id: int):
    movie = await db.get_movie(movie_id)
    if not movie:
        await target.answer(t(lang, "not_found"))
        return
    files = await db.get_files(movie_id)
    fav = await db.is_fav(user_id, movie_id)
    kb = card_kb(lang, movie_id, files, fav, movie["title"])
    text = f"🎬 <b>{escape(movie['title'])}</b>\n🔑 {t(lang, 'code')}: <code>{movie_id}</code>"
    if movie["poster_id"]:
        await target.answer_photo(movie["poster_id"], caption=text, reply_markup=kb, parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


def list_kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=r["title"], callback_data=f"movie:{r['id']}")] for r in rows
        ]
    )


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
    q = m.text.strip()
    if q.isdigit():
        await send_card(m, m.from_user.id, lang, int(q))
        return
    rows = await db.search_movies(q)
    if not rows:
        await m.answer(t(lang, "not_found"))
        return
    await m.answer(t(lang, "search_results"), reply_markup=list_kb(rows))


@router.callback_query(F.data.startswith("movie:"))
async def open_movie(c: CallbackQuery):
    lang = await db.get_lang(c.from_user.id) or "uz"
    await send_card(c.message, c.from_user.id, lang, int(c.data.split(":")[1]))
    await c.answer()


@router.callback_query(F.data.startswith("dl:"))
async def download(c: CallbackQuery):
    _, mid, quality = c.data.split(":")
    lang = await db.get_lang(c.from_user.id) or "uz"
    if not await utils.gate(c.bot, c.from_user.id, lang, c.message):
        await c.answer()
        return
    movie = await db.get_movie(int(mid))
    files = await db.get_files(int(mid))
    f = files.get(quality)
    if not movie or not f:
        await c.answer(t(lang, "not_found"), show_alert=True)
        return
    # Admin yuborgan izoh (bold va boshqa formatlari bilan) aynan shunday chiqadi
    caption = f["caption"] or f"🎬 {escape(movie['title'])} • {quality}p"
    if f["file_type"] == "video":
        await c.message.answer_video(f["file_id"], caption=caption, parse_mode="HTML")
    else:
        await c.message.answer_document(f["file_id"], caption=caption, parse_mode="HTML")
    await c.answer()


@router.callback_query(F.data.startswith("fav:"))
async def toggle_favorite(c: CallbackQuery):
    mid = int(c.data.split(":")[1])
    lang = await db.get_lang(c.from_user.id) or "uz"
    movie = await db.get_movie(mid)
    if not movie:
        await c.answer(t(lang, "not_found"), show_alert=True)
        return
    added = await db.toggle_fav(c.from_user.id, mid)
    files = await db.get_files(mid)
    await c.message.edit_reply_markup(
        reply_markup=card_kb(lang, mid, files, added, movie["title"])
    )
    await c.answer(t(lang, "fav_added" if added else "fav_removed"))
