import asyncio
import logging
from html import escape
from urllib.parse import quote

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import database as db
import utils
from genres import (
    CATEGORIES,
    cat_icon,
    cat_label,
    country_name,
    country_tag,
    genre_label,
    genre_tag,
)
from locales import MENU_MAP, MENU_TEXTS, t

router = Router()

PAGE = 8
BROWSE_PAGE = 8
EP_PAGE = 30
CAPTION_LIMIT = 1024


# ---------------- yordamchilar ----------------
def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def grid(buttons: list, per_row: int) -> list:
    return [buttons[i : i + per_row] for i in range(0, len(buttons), per_row)]


def kb_of(rows: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def safe_edit(msg: Message, text: str, kb=None):
    try:
        await msg.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass


async def user_lang(user_id: int) -> str:
    return await db.get_lang(user_id) or "uz"


def movie_label(r) -> str:
    icon = "📺" if r["is_series"] else "🎬"
    year = f" ({r['year']})" if r["year"] else ""
    score = ""
    if r["imdb_rating"]:
        score = " ⭐" + r["imdb_rating"].split("/")[0]
    elif r["rating"]:
        score = f" ⭐{r['rating']:.1f}"
    return f"{icon} {r['title']}{year}{score}"


def movie_buttons(rows) -> list:
    return [[btn(movie_label(r), f"movie:{r['id']}")] for r in rows]


# ---------------- kino kartochkasi ----------------
async def card_extra(movie):
    """Serial uchun fasllar, kino uchun sifatlar."""
    if movie["is_series"]:
        return await db.season_counts(movie["id"])
    return await db.list_qualities(movie["id"], 0, 0)


def card_kb(lang: str, movie, fav: bool, extra) -> InlineKeyboardMarkup:
    movie_id = movie["id"]
    rows = []
    if movie["is_series"]:
        buttons = [btn(t(lang, "season_btn").format(n=s), f"se:{movie_id}:{s}") for s in sorted(extra)]
        rows += grid(buttons, 3)
    else:
        quals = sorted(extra, key=utils.q_key, reverse=True)
        if quals:
            rows.append([btn(f"📥 {utils.q_label(q)}", f"dl:{movie_id}:0:0:{q}") for q in quals])
    rows.append([btn(t(lang, "fav_remove" if fav else "fav_add"), f"fav:{movie_id}")])
    link = f"https://t.me/{utils.BOT_USERNAME}?start={movie['code']}"
    share_url = f"https://t.me/share/url?url={quote(link)}&text={quote('🎬 ' + movie['title'])}"
    rows.append([InlineKeyboardButton(text=t(lang, "share"), url=share_url)])
    return kb_of(rows)


def cert_emoji(cert: str) -> str:
    c = cert.upper()
    if c in ("G", "TV-Y", "TV-G", "TV-Y7"):
        return "🟢"
    if c in ("PG", "TV-PG"):
        return "🟡"
    if c in ("PG-13", "TV-14"):
        return "🟠"
    if c in ("R", "TV-MA", "NC-17"):
        return "🔴"
    return "⚪"


def card_lang(lang: str) -> str:
    """Kartochka tili: rus tanlagan foydalanuvchiga ruscha, qolganlarga (uz, en) inglizcha."""
    return "ru" if lang == "ru" else "en"


def country_tags(movie, cl: str) -> list:
    codes = movie["country_codes"] or []
    if codes:
        return [country_tag(c, cl) for c in codes]
    return list(movie["countries"] or [])


def pick_overview(movie, cl: str):
    if cl == "ru":
        return movie["overview_ru"] or movie["overview_en"]
    return movie["overview_en"]  # inglizcha tavsif bo'lmasa, rus tilini ko'rsatmaymiz


def card_text(movie, lang: str) -> str:
    cl = card_lang(lang)
    title = movie["title_ru"] if cl == "ru" and movie["title_ru"] else movie["title"]
    year = f" ({movie['year']})" if movie["year"] else ""
    head = f"🎬 <b>{escape(title)}</b>{year}"

    blocks = []
    rating_lines = []
    if movie["imdb_rating"]:
        votes = f" ({utils.short_num(movie['imdb_votes'])})" if movie["imdb_votes"] else ""
        rating_lines.append(f"IMDb ⭐ {movie['imdb_rating']}{votes}")
    if movie["rating"]:
        votes = f" ({utils.short_num(movie['rating_votes'])})" if movie["rating_votes"] else ""
        rating_lines.append(f"TMDB ⭐ {movie['rating']:.1f}/10{votes}")
    if rating_lines:
        tree = [
            ("└" if i == len(rating_lines) - 1 else "├") + " " + line
            for i, line in enumerate(rating_lines)
        ]
        blocks.append(
            "<blockquote>" + escape(t(cl, "ratings")) + "\n" + escape("\n".join(tree)) + "</blockquote>"
        )

    info = []
    if movie["certification"]:
        info.append(f"{cert_emoji(movie['certification'])} {escape(movie['certification'])}")
    if movie["runtime"]:
        info.append(f"⏱ {movie['runtime']} {t(cl, 'min')}")
    if info:
        blocks.append(" • ".join(info))

    tags = []
    countries = country_tags(movie, cl)
    if countries:
        tags.append(f"🌍 {t(cl, 'country')}: " + " ".join("#" + c for c in countries))
    if movie["genre_tags"]:
        tags.append(f"🎭 {t(cl, 'genres')}: " + ", ".join("#" + genre_tag(g, cl) for g in movie["genre_tags"]))
    if tags:
        blocks.append("\n".join(tags))

    tail = "\n\n".join(blocks)
    body = ""
    overview = pick_overview(movie, cl)
    budget = CAPTION_LIMIT - len(head) - len(tail) - 10
    if overview and budget > 60:
        ov = overview.strip()
        if len(ov) > budget:
            ov = ov[: budget - 1].rsplit(" ", 1)[0] + "…"
        body = escape(ov)
    return "\n\n".join(x for x in (head, body, tail) if x)


async def send_card(target: Message, user_id: int, lang: str, movie):
    if not movie or movie["hidden"]:
        await target.answer(t(lang, "not_found"))
        return
    fav, extra = await asyncio.gather(db.is_fav(user_id, movie["id"]), card_extra(movie))
    kb = card_kb(lang, movie, fav, extra)
    text = card_text(movie, lang)
    photo = movie["poster_id"] or movie["poster_url"]
    if photo:
        try:
            sent = await target.answer_photo(photo, caption=text, reply_markup=kb, parse_mode="HTML")
            if not movie["poster_id"] and sent.photo:
                await db.set_poster_id(movie["id"], sent.photo[-1].file_id)
            return
        except Exception as e:
            logging.warning("Kartochkani rasm bilan yuborib bo'lmadi: %s", e)
    await target.answer(text, reply_markup=kb, parse_mode="HTML")


# ---------------- video izohi (TMDB ma'lumotidan, o'zbekcha) ----------------
def fmt_runtime(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h} soat {m} daqiqa"
    if h:
        return f"{h} soat"
    return f"{m} daqiqa"


def media_caption(movie, season: int, episode: int, quality: str) -> str:
    year = f" ({movie['year']})" if movie["year"] else ""
    lines = [f"🎬 <b>{escape(movie['title'])}</b>{year}"]
    if season:
        lines.append(f"📺 {season}-fasl • {episode}-qism")
    lines.append("")
    lines.append(f"📀 Sifat: {utils.q_label(quality)}")
    if movie["runtime"]:
        lines.append(f"⏱ Davomiyligi: {fmt_runtime(movie['runtime'])}")
    if movie["genre_tags"]:
        names = [genre_label(g, "uz") for g in movie["genre_tags"]]
    else:
        names = list(movie["genres"] or [])
    if names:
        lines.append("🎭 Janr: " + escape(", ".join(names)))
    scores = []
    if movie["imdb_rating"]:
        scores.append(f"IMDb {movie['imdb_rating']}")
    if movie["rating"]:
        scores.append(f"TMDB {movie['rating']:.1f}/10")
    if scores:
        lines.append("⭐ " + " • ".join(scores))
    if movie["country_codes"]:
        lines.append("🌍 Davlat: " + escape(", ".join(country_name(c, "uz") for c in movie["country_codes"])))
    if movie["certification"]:
        lines.append(f"🔞 Yosh chegarasi: {escape(movie['certification'])}")
    lines.append("")
    lines.append("🍿 Yaxshi tomosha!")
    lines.append(f"🤖 @{utils.BOT_USERNAME}")
    return "\n".join(lines)


async def send_media(msg: Message, movie, f, season: int, episode: int, quality: str):
    caption = media_caption(movie, season, episode, quality)
    if f["file_type"] == "video":
        try:
            extra = {"cover": f["cover_id"]} if f["cover_id"] else {}
            await msg.answer_video(f["file_id"], caption=caption, parse_mode="HTML", **extra)
        except Exception as e:
            logging.warning("Muqova bilan yuborib bo'lmadi, muqovasiz yuborilyapti: %s", e)
            await msg.answer_video(f["file_id"], caption=caption, parse_mode="HTML")
    else:
        await msg.answer_document(f["file_id"], caption=caption, parse_mode="HTML")
    await db.add_view(movie["id"])


# ---------------- menyu bo'limlari ----------------
async def cats_view(lang: str):
    counts = await db.category_counts()
    buttons = []
    for i, cat in enumerate(CATEGORIES):
        n = counts.get(cat, 0)
        if n:
            buttons.append(btn(f"{cat_icon(cat)} {cat_label(cat, lang)} ({n})", f"br:c:{i}:0"))
    if not buttons:
        return t(lang, "empty"), None
    return t(lang, "cats_title"), kb_of(grid(buttons, 2))


async def genres_view(lang: str):
    rows = await db.genre_counts()
    buttons = [btn(f"{genre_label(r['tag'], lang)} ({r['c']})", f"br:g:{r['tag']}:0") for r in rows]
    if not buttons:
        return t(lang, "empty"), None
    return t(lang, "genres_title"), kb_of(grid(buttons, 2))


async def years_view(lang: str):
    rows = await db.decade_counts()
    buttons = [btn(f"📅 {r['dec']}–{r['dec'] + 9} ({r['c']})", f"br:y:{r['dec']}:0") for r in rows]
    if not buttons:
        return t(lang, "empty"), None
    return t(lang, "years_title"), kb_of(grid(buttons, 2))


def browse_title(lang: str, kind: str, value: str) -> str:
    if kind == "c":
        cat = CATEGORIES[int(value)]
        return f"{cat_icon(cat)} {cat_label(cat, lang)}"
    if kind == "g":
        return f"🎭 {genre_label(value, lang)}"
    if kind == "y":
        return f"📅 {value}–{int(value) + 9}"
    if kind == "p":
        return t(lang, "popular_title")
    return t(lang, "new_title")


async def browse_view(lang: str, kind: str, value: str, page: int):
    db_value = CATEGORIES[int(value)] if kind == "c" else value
    rows, total = await db.browse(kind, db_value, page * BROWSE_PAGE, BROWSE_PAGE)
    if not rows:
        return t(lang, "empty"), None
    pages = max(1, -(-total // BROWSE_PAGE))
    kb = movie_buttons(rows)
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(btn("⬅️", f"br:{kind}:{value}:{page - 1}"))
        nav.append(btn(f"{page + 1}/{pages}", "noop"))
        if page + 1 < pages:
            nav.append(btn("➡️", f"br:{kind}:{value}:{page + 1}"))
        kb.append(nav)
    if kind in ("c", "g", "y"):
        kb.append([btn(t(lang, "back"), f"mn:{kind}")])
    return f"{browse_title(lang, kind, value)} ({total})", kb_of(kb)


async def favorites_view(user_id: int, lang: str):
    rows = await db.list_favs(user_id)
    if not rows:
        return t(lang, "favorites_empty"), None
    return t(lang, "favorites_title"), kb_of(movie_buttons(rows))


async def answer_view(msg: Message, view):
    text, kb = view
    await msg.answer(text, reply_markup=kb)


@router.message(F.text.in_(MENU_TEXTS))
async def on_menu(m: Message):
    lang = await user_lang(m.from_user.id)
    if not await utils.gate(m.bot, m.from_user.id, lang, m):
        return
    key = MENU_MAP[m.text]
    if key == "m_search":
        await m.answer(t(lang, "search_hint"))
    elif key == "m_random":
        movie = await db.random_movie()
        if movie:
            await send_card(m, m.from_user.id, lang, movie)
        else:
            await m.answer(t(lang, "empty"))
    elif key == "m_cats":
        await answer_view(m, await cats_view(lang))
    elif key == "m_genres":
        await answer_view(m, await genres_view(lang))
    elif key == "m_years":
        await answer_view(m, await years_view(lang))
    elif key == "m_popular":
        await answer_view(m, await browse_view(lang, "p", "", 0))
    elif key == "m_new":
        await answer_view(m, await browse_view(lang, "n", "", 0))
    elif key == "m_fav":
        await answer_view(m, await favorites_view(m.from_user.id, lang))
    elif key == "m_lang":
        await m.answer(utils.LANG_PROMPT, reply_markup=utils.lang_kb())


@router.message(Command("favorites"))
async def favorites_cmd(m: Message):
    lang = await user_lang(m.from_user.id)
    if not await utils.gate(m.bot, m.from_user.id, lang, m):
        return
    await answer_view(m, await favorites_view(m.from_user.id, lang))


@router.callback_query(F.data.regexp(r"^mn:[cgy]$"))
async def on_menu_back(c: CallbackQuery):
    await c.answer()
    lang = await user_lang(c.from_user.id)
    views = {"c": cats_view, "g": genres_view, "y": years_view}
    text, kb = await views[c.data[3]](lang)
    await safe_edit(c.message, text, kb)


@router.callback_query(F.data.regexp(r"^br:[cgypn]:[^:]*:\d+$"))
async def on_browse(c: CallbackQuery):
    await c.answer()
    _, kind, value, page = c.data.split(":")
    lang = await user_lang(c.from_user.id)
    text, kb = await browse_view(lang, kind, value, int(page))
    await safe_edit(c.message, text, kb)


@router.callback_query(F.data == "noop")
async def on_noop(c: CallbackQuery):
    await c.answer()


# ---------------- qidiruv ----------------
def search_kb(rows, page: int, has_next: bool, q: str) -> InlineKeyboardMarkup:
    kb = movie_buttons(rows)
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


@router.message(F.text & ~F.text.startswith("/"))
async def text_handler(m: Message):
    lang = await user_lang(m.from_user.id)
    if not await utils.gate(m.bot, m.from_user.id, lang, m):
        return
    # callback_data 64 baytdan oshmasligi uchun qidiruv matnini qisqartiramiz
    q = m.text.strip().encode()[:40].decode(errors="ignore")
    rows, has_next = await run_search(q, 0)
    if not rows:
        await m.answer(t(lang, "not_found_hint"))
        return
    await m.answer(t(lang, "search_results"), reply_markup=search_kb(rows, 0, has_next, q))


@router.callback_query(F.data.startswith("sr:"))
async def search_page(c: CallbackQuery):
    await c.answer()
    _, page, q = c.data.split(":", 2)
    page = int(page)
    rows, has_next = await run_search(q, page)
    if rows:
        await c.message.edit_reply_markup(reply_markup=search_kb(rows, page, has_next, q))


@router.callback_query(F.data.startswith("movie:"))
async def open_movie(c: CallbackQuery):
    await c.answer()
    lang = await user_lang(c.from_user.id)
    movie = await db.get_movie(int(c.data.split(":")[1]))
    await send_card(c.message, c.from_user.id, lang, movie)


# ---------------- seriallar: fasl va qismlar ----------------
async def ep_kb(movie_id: int, season: int, page: int) -> InlineKeyboardMarkup:
    total, eps = await asyncio.gather(
        db.count_episodes(movie_id, season),
        db.list_episodes(movie_id, season, page * EP_PAGE, EP_PAGE),
    )
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
    await c.answer()
    _, movie_id, season = c.data.split(":")
    lang = await user_lang(c.from_user.id)
    movie, kb = await asyncio.gather(db.get_movie(int(movie_id)), ep_kb(int(movie_id), int(season), 0))
    if not movie or movie["hidden"]:
        await c.message.answer(t(lang, "not_found"))
        return
    title = f"📺 {escape(movie['title'])} — {t(lang, 'season_btn').format(n=season)[2:]}"
    await c.message.answer(f"{title}\n{t(lang, 'choose_ep')}", reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("epp:"))
async def episode_page(c: CallbackQuery):
    await c.answer()
    _, movie_id, season, page = c.data.split(":")
    kb = await ep_kb(int(movie_id), int(season), int(page))
    await c.message.edit_reply_markup(reply_markup=kb)


@router.callback_query(F.data.startswith("ep:"))
async def open_episode(c: CallbackQuery):
    _, movie_id, season, episode = c.data.split(":")
    lang = await user_lang(c.from_user.id)
    if not await utils.gate(c.bot, c.from_user.id, lang, c.message):
        await c.answer()
        return
    season, episode = int(season), int(episode)
    movie, quals = await asyncio.gather(
        db.get_movie(int(movie_id)), db.list_qualities(int(movie_id), season, episode)
    )
    quals = sorted(quals, key=utils.q_key, reverse=True)
    if not movie or movie["hidden"] or not quals:
        await c.answer(t(lang, "not_found"), show_alert=True)
        return
    if len(quals) == 1:
        await c.answer(t(lang, "sending"))
        f = await db.get_file(movie["id"], season, episode, quals[0])
        if f:
            await send_media(c.message, movie, f, season, episode, quals[0])
        return
    await c.answer()
    rows = [[btn(f"📥 {utils.q_label(q)}", f"dl:{movie['id']}:{season}:{episode}:{q}") for q in quals]]
    await c.message.answer(
        f"{escape(movie['title'])} • {episode}\n{t(lang, 'choose_quality')}",
        reply_markup=kb_of(rows),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("dl:"))
async def download(c: CallbackQuery):
    _, movie_id, season, episode, quality = c.data.split(":")
    lang = await user_lang(c.from_user.id)
    if not await utils.gate(c.bot, c.from_user.id, lang, c.message):
        await c.answer()
        return
    movie, f = await asyncio.gather(
        db.get_movie(int(movie_id)),
        db.get_file(int(movie_id), int(season), int(episode), quality),
    )
    if not movie or movie["hidden"] or not f:
        await c.answer(t(lang, "not_found"), show_alert=True)
        return
    await c.answer(t(lang, "sending"))
    await send_media(c.message, movie, f, int(season), int(episode), quality)


@router.callback_query(F.data.startswith("fav:"))
async def toggle_favorite(c: CallbackQuery):
    movie_id = int(c.data.split(":")[1])
    lang = await user_lang(c.from_user.id)
    movie = await db.get_movie(movie_id)
    if not movie or movie["hidden"]:
        await c.answer(t(lang, "not_found"), show_alert=True)
        return
    added, extra = await asyncio.gather(db.toggle_fav(c.from_user.id, movie_id), card_extra(movie))
    await c.answer(t(lang, "fav_added" if added else "fav_removed"))
    await c.message.edit_reply_markup(reply_markup=card_kb(lang, movie, added, extra))
