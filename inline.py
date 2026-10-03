import asyncio
import logging

from aiogram import Router
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultsButton,
    InputTextMessageContent,
    LinkPreviewOptions,
)

import cards
import database as db
import titles
import utils

router = Router()

OPEN_TEXT = {"uz": "▶️ Botda ko'rish", "en": "▶️ Open in bot", "ru": "▶️ Открыть в боте"}
BOT_BTN = {"uz": "🤖 Botni ochish", "en": "🤖 Open the bot", "ru": "🤖 Открыть бота"}


async def _avail(movie):
    if movie["is_series"]:
        return await db.season_counts(movie["id"]) or None
    return await db.list_qualities(movie["id"], 0, 0) or None


def _result(movie, avail, lang: str) -> InlineQueryResultArticle:
    m = dict(movie)
    year = f" ({m['year']})" if m.get("year") else ""
    icon = "📺 " if m.get("is_series") else "🎬 "
    title = f"{icon}{m['title']}{year}" + (" 💎" if m.get("is_premium") else "")

    parts = []
    uz = cards.uz_name(m)
    if uz:
        parts.append(f"🇺🇿 {uz}")  # o'zbekcha 2-nom
    if m.get("imdb_rating"):
        parts.append("⭐ " + m["imdb_rating"].split("/")[0])
    elif m.get("rating"):
        parts.append(f"⭐ {m['rating']:.1f}")
    if m.get("genres"):
        parts.append(", ".join(m["genres"][:3]))
    if isinstance(avail, list):
        parts.append(" ".join(utils.q_label(q) for q in sorted(avail, key=utils.q_key, reverse=True)))
    elif isinstance(avail, dict):
        parts.append(f"{len(avail)} fasl • {sum(avail.values())} qism")

    link = f"https://t.me/{utils.BOT_USERNAME}?start={m['code']}"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=OPEN_TEXT.get(lang, OPEN_TEXT["uz"]), url=link)]]
    )
    poster = m.get("poster_url")
    content = InputTextMessageContent(
        message_text=cards.card_text(m, lang, avail=avail, share=True),
        parse_mode="HTML",
        # Poster xabarning tepasida katta rasm bo'lib ko'rinadi
        link_preview_options=(
            LinkPreviewOptions(url=poster, prefer_large_media=True, show_above_text=True)
            if poster
            else LinkPreviewOptions(is_disabled=True)
        ),
    )
    return InlineQueryResultArticle(
        id=f"m{m['id']}",
        title=title,
        description=" • ".join(parts) or None,
        input_message_content=content,
        reply_markup=kb,
        thumbnail_url=poster.replace("/w500/", "/w185/") if poster else None,
    )


@router.inline_query()
async def on_inline(q: InlineQuery):
    uid = q.from_user.id
    lang = await db.get_lang(uid) or "uz"
    text = (q.query or "").strip()
    try:
        if text.startswith("share_"):
            movie = await db.get_movie_by_code(text[6:])
            movies = [movie] if movie and not movie["hidden"] else []
        elif text:
            movies = list(await titles.inline_search(text, 20))  # o'zbekcha nom, imlo xatosi, kirill ham ishlaydi
        else:
            movies = list(await db.inline_default(20))
        avails = await asyncio.gather(*(_avail(mv) for mv in movies))
        results = [_result(mv, av, lang) for mv, av in zip(movies, avails)]
    except Exception as e:
        logging.warning("Inline so'rovda xato: %s", e)
        results = []
    await q.answer(
        results=results,
        cache_time=15,
        is_personal=True,
        button=InlineQueryResultsButton(text=BOT_BTN.get(lang, BOT_BTN["uz"]), start_parameter="inline"),
    )
