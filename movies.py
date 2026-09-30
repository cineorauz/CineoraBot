import asyncio
import logging
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import cards
import database as db
import tmdb
import ui
import utils
from genres import CATEGORIES, cat_icon, cat_label, genre_label
from locales import MENU_MAP, t
from utils import btn, grid, kb_of

router = Router()

BROWSE_PAGE = 8
EP_PAGE = 30
MEDALS = ["🥇", "🥈", "🥉"]


# ---------------- yordamchilar ----------------
async def user_lang(user_id: int) -> str:
    return await db.get_lang(user_id) or "uz"


def label(r, prefix: str = "") -> str:
    year = f" ({r['year']})" if r["year"] else ""
    score = ""
    if r["imdb_rating"]:
        score = " ⭐" + r["imdb_rating"].split("/")[0]
    elif r["rating"]:
        score = f" ⭐{r['rating']:.1f}"
    lock = " 💎" if r["is_premium"] else ""
    return f"{prefix}{r['title']}{year}{score}{lock}"


def movie_buttons(rows, ranked: bool = False, start: int = 0) -> list:
    out = []
    for i, r in enumerate(rows):
        n = start + i
        if ranked:
            prefix = (MEDALS[n] if n < 3 else f"{n + 1}.") + " "
        else:
            prefix = "📺 " if r["is_series"] else "🎬 "
        out.append([btn(label(r, prefix), f"movie:{r['id']}")])
    return out


async def avail_for(movie):
    if movie["is_series"]:
        return await db.season_counts(movie["id"]) or False
    return await db.list_qualities(movie["id"], 0, 0) or False


def card_keyboard(lang: str, m: dict, fav: bool, avail, locked: bool):
    return utils.with_nav(cards.movie_kb(lang, m, fav, avail, locked), utils.nav_row(lang, "nav:back"))


# ---------------- kartochkalar ----------------
async def render_card(bot, chat_id: int, uid: int, lang: str, movie, source=None):
    if not movie or movie["hidden"]:
        await ui.show(bot, chat_id, uid, t(lang, "not_found"), kb_of([utils.nav_row(lang)]), source=source)
        return
    fav, avail, premium = await asyncio.gather(
        db.is_fav(uid, movie["id"]), avail_for(movie), db.is_premium(uid)
    )
    m = dict(movie)
    if avail is False:
        text = cards.card_text(m, lang, avail=False)
        if m.get("tmdb_id"):
            requested = await db.has_request(uid, m["tmdb_type"], m["tmdb_id"])
            kb = cards.missing_kb(lang, m["tmdb_type"], m["tmdb_id"], requested, m.get("trailer_key"))
        else:
            kb = kb_of([])
        kb = utils.with_nav(kb, utils.nav_row(lang, "nav:back"))
    else:
        locked = bool(m.get("is_premium")) and not premium
        text = cards.card_text(m, lang, avail=avail, locked=locked)
        kb = card_keyboard(lang, m, fav, avail, locked)
    photo = m.get("poster_id") or m.get("poster_url")
    sent = await ui.show(bot, chat_id, uid, text, kb, photo=photo, source=source)
    if sent is not None and sent.photo and not m.get("poster_id") and m.get("id"):
        db.bg(db.set_poster_id(m["id"], sent.photo[-1].file_id))


async def render_tmdb_card(bot, chat_id: int, uid: int, lang: str, media_type: str, tmdb_id: int, source=None):
    try:
        d = await tmdb.details_cached(media_type, tmdb_id)
    except tmdb.TMDBError:
        await ui.show(bot, chat_id, uid, t(lang, "tm_fail"), kb_of([utils.nav_row(lang, "nav:back")]), source=source)
        return
    have = await db.movies_by_tmdb(((media_type, tmdb_id),))
    row = have.get((media_type, tmdb_id))
    if row:
        await render_card(bot, chat_id, uid, lang, await db.get_movie(row["id"]), source)
        return
    requested = await db.has_request(uid, media_type, tmdb_id)
    kb = utils.with_nav(
        cards.missing_kb(lang, media_type, tmdb_id, requested, d.get("trailer_key")),
        utils.nav_row(lang, "nav:back"),
    )
    await ui.show(
        bot, chat_id, uid, cards.card_text(d, lang, avail=False), kb,
        photo=d.get("poster_url"), source=source,
    )


async def notify_requesters(bot, movie):
    """Kontent yuklanganda uni so'ragan foydalanuvchilarga xabar yuboradi."""
    if not movie["tmdb_id"]:
        return
    users = await db.requesters(movie["tmdb_type"], movie["tmdb_id"])
    for r in users:
        lang = r["lang"]
        try:
            await bot.send_message(
                r["user_id"],
                t(lang, "notified").format(title=escape(movie["title"])),
                reply_markup=kb_of([[btn(t(lang, "open_btn"), f"movie:{movie['id']}")]]),
                parse_mode="HTML",
            )
        except Exception:
            pass
        await asyncio.sleep(0.05)
    await db.mark_notified(movie["tmdb_type"], movie["tmdb_id"])


async def send_media(msg: Message, user_id: int, movie, f, season: int, episode: int, quality: str):
    caption = cards.media_caption(dict(movie), season, episode, quality)
    if f["file_type"] == "video":
        try:
            extra = {"cover": f["cover_id"]} if f["cover_id"] else {}
            await msg.answer_video(f["file_id"], caption=caption, parse_mode="HTML", **extra)
        except Exception as e:
            logging.warning("Muqova bilan yuborib bo'lmadi, muqovasiz yuborilyapti: %s", e)
            await msg.answer_video(f["file_id"], caption=caption, parse_mode="HTML")
    else:
        await msg.answer_document(f["file_id"], caption=caption, parse_mode="HTML")
    db.add_view(movie["id"])
    db.bump_downloads(user_id)


# ---------------- bo'limlar (ro'yxat ekranlari) ----------------
async def cats_view(lang: str):
    counts = await db.category_counts()
    buttons = [
        btn(f"{cat_icon(cat)} {cat_label(cat, lang)} ({counts[cat]})", f"br:c:{i}:0")
        for i, cat in enumerate(CATEGORIES)
        if counts.get(cat)
    ]
    if not buttons:
        return t(lang, "empty"), kb_of([utils.nav_row(lang)])
    return t(lang, "cats_title"), kb_of(grid(buttons, 2) + [utils.nav_row(lang)])


async def genres_view(lang: str):
    rows = await db.genre_counts()
    buttons = [btn(f"{genre_label(r['tag'], lang)} ({r['c']})", f"br:g:{r['tag']}:0") for r in rows]
    if not buttons:
        return t(lang, "empty"), kb_of([utils.nav_row(lang)])
    return t(lang, "genres_title"), kb_of(grid(buttons, 2) + [utils.nav_row(lang)])


async def years_view(lang: str):
    rows = await db.decade_counts()
    buttons = [btn(f"📅 {r['dec']}–{r['dec'] + 9} ({r['c']})", f"br:y:{r['dec']}:0") for r in rows]
    if not buttons:
        return t(lang, "empty"), kb_of([utils.nav_row(lang)])
    return t(lang, "years_title"), kb_of(grid(buttons, 2) + [utils.nav_row(lang)])


def browse_title(lang: str, kind: str, value: str) -> str:
    if kind == "c":
        cat = CATEGORIES[int(value)]
        return f"{cat_icon(cat)} <b>{escape(cat_label(cat, lang))}</b>"
    if kind == "g":
        return f"🎭 <b>{escape(genre_label(value, lang))}</b>"
    if kind == "y":
        return f"📅 <b>{value}–{int(value) + 9}</b>"
    return t(lang, "top_title" if kind == "p" else "new_title")


async def browse_view(lang: str, kind: str, value: str, page: int):
    up = f"mn:{kind}" if kind in ("c", "g", "y") else None
    db_value = CATEGORIES[int(value)] if kind == "c" else value
    rows, total = await db.browse(kind, db_value, page * BROWSE_PAGE, BROWSE_PAGE)
    if not rows:
        return t(lang, "empty"), kb_of([utils.nav_row(lang, up)])
    pages = max(1, -(-total // BROWSE_PAGE))
    kb = movie_buttons(rows, ranked=(kind == "p"), start=page * BROWSE_PAGE)
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(btn("⬅️", f"br:{kind}:{value}:{page - 1}"))
        nav.append(btn(f"{page + 1}/{pages}", "noop"))
        if page + 1 < pages:
            nav.append(btn("➡️", f"br:{kind}:{value}:{page + 1}"))
        kb.append(nav)
    kb.append(utils.nav_row(lang, up))
    return f"{browse_title(lang, kind, value)}  ·  {total}", kb_of(kb)


async def favorites_view(user_id: int, lang: str):
    rows = await db.list_favs(user_id)
    if not rows:
        return t(lang, "favorites_empty"), kb_of([utils.nav_row(lang)])
    return t(lang, "favorites_title"), kb_of(movie_buttons(rows) + [utils.nav_row(lang)])


# ---------------- qidiruv ----------------
async def search_all(q: str):
    """Botdagi va TMDB'dagi natijalarni birlashtiradi: avval botda borlari, keyin yuklanmaganlari."""

    async def tm():
        try:
            return await tmdb.search_cached(q)
        except tmdb.TMDBError as e:
            logging.warning("TMDB qidiruv xatosi: %s", e)
            return None

    tm_rows, alias_rows = await asyncio.gather(tm(), db.search_movies(q, 0, 8))
    have = await db.movies_by_tmdb([(r["type"], r["id"]) for r in (tm_rows or [])])
    avail, missing, seen = [], [], set()
    for r in tm_rows or []:
        row = have.get((r["type"], r["id"]))
        if row:
            seen.add(row["id"])
            avail.append(btn(label(row, "✅ "), f"movie:{row['id']}"))
        else:
            year = f" ({r['year']})" if r["year"] else ""
            icon = "📺 " if r["type"] == "tv" else ""
            missing.append(btn(f"⏳ {icon}{r['title']}{year}", f"tm:{r['type']}:{r['id']}"))
    for row in alias_rows:
        if row["id"] not in seen:
            seen.add(row["id"])
            avail.append(btn(label(row, "✅ "), f"movie:{row['id']}"))
    return (avail + missing)[:10], tm_rows is None


async def do_search(bot, chat_id: int, uid: int, lang: str, q: str, source=None):
    await ui.show(bot, chat_id, uid, t(lang, "searching"), None, source=source)
    items, tm_failed = await search_all(q)
    ui.set_query(uid, q)
    ui.set_back(uid, "sr:0")
    if not items:
        text = t(lang, "tm_fail" if tm_failed else "not_found_hint")
        kb = kb_of([utils.nav_row(lang)])
    else:
        text = t(lang, "results").format(q=escape(q))
        kb = kb_of([[b] for b in items] + [utils.nav_row(lang)])
    await ui.show(bot, chat_id, uid, text, kb)


async def route_render(bot, chat_id: int, uid: int, lang: str, route: str, source=None):
    """«Orqaga» bosilganda foydalanuvchini oldingi ro'yxatga qaytaradi."""
    if route.startswith("br:"):
        _, kind, value, page = route.split(":")
        text, kb = await browse_view(lang, kind, value, int(page))
    elif route == "favs:open":
        text, kb = await favorites_view(uid, lang)
    elif route == "sr:0" and ui.get_query(uid):
        await do_search(bot, chat_id, uid, lang, ui.get_query(uid), source)
        return
    else:
        await utils.show_home(bot, chat_id, uid, lang, source)
        return
    ui.set_back(uid, route)
    await ui.show(bot, chat_id, uid, text, kb, source=source)


# ---------------- matnli xabarlar (qidiruv) ----------------
@router.message(F.text & ~F.text.startswith("/"))
async def text_handler(m: Message):
    uid = m.from_user.id
    lang = await user_lang(uid)
    await ui.delete_message(m)  # foydalanuvchi yozgan matn chatda qolmaydi
    if m.text in MENU_MAP:  # eski pastki menyu tugmalari bosilgan bo'lsa
        await utils.show_home(m.bot, m.chat.id, uid, lang)
        return
    if not await utils.gate(m.bot, uid, lang, m):
        return
    await do_search(m.bot, m.chat.id, uid, lang, m.text.strip()[:60])


@router.message(Command("favorites"))
async def favorites_cmd(m: Message):
    uid = m.from_user.id
    lang = await user_lang(uid)
    await ui.delete_message(m)
    ui.set_back(uid, "favs:open")
    text, kb = await favorites_view(uid, lang)
    await ui.show(m.bot, m.chat.id, uid, text, kb)


# ---------------- navigatsiya tugmalari ----------------
@router.callback_query(F.data == "home")
async def on_home(c: CallbackQuery):
    await c.answer()
    await utils.show_home(c.bot, c.message.chat.id, c.from_user.id, await user_lang(c.from_user.id), c.message)


@router.callback_query(F.data == "nav:back")
async def on_back(c: CallbackQuery):
    await c.answer()
    uid = c.from_user.id
    await route_render(c.bot, c.message.chat.id, uid, await user_lang(uid), ui.get_back(uid), c.message)


@router.callback_query(F.data == "nav:search")
async def nav_search(c: CallbackQuery):
    await c.answer()
    lang = await user_lang(c.from_user.id)
    ui.set_back(c.from_user.id, "home")
    await ui.show_for(c, t(lang, "search_hint"), kb_of([utils.nav_row(lang)]))


@router.callback_query(F.data == "nav:random")
async def nav_random(c: CallbackQuery):
    await c.answer()
    uid = c.from_user.id
    lang = await user_lang(uid)
    movie = await db.random_movie()
    ui.set_back(uid, "home")
    if not movie:
        await ui.show_for(c, t(lang, "empty"), kb_of([utils.nav_row(lang)]))
        return
    await render_card(c.bot, c.message.chat.id, uid, lang, movie, c.message)


@router.callback_query(F.data == "sr:0")
async def back_to_search(c: CallbackQuery):
    await c.answer()
    uid = c.from_user.id
    lang = await user_lang(uid)
    q = ui.get_query(uid)
    if q:
        await do_search(c.bot, c.message.chat.id, uid, lang, q, c.message)
    else:
        await utils.show_home(c.bot, c.message.chat.id, uid, lang, c.message)


@router.callback_query(F.data.regexp(r"^mn:[cgy]$"))
async def on_menu_views(c: CallbackQuery):
    await c.answer()
    uid = c.from_user.id
    lang = await user_lang(uid)
    views = {"c": cats_view, "g": genres_view, "y": years_view}
    ui.set_back(uid, "home")
    text, kb = await views[c.data[3]](lang)
    await ui.show_for(c, text, kb)


@router.callback_query(F.data.regexp(r"^br:[cgypn]:[^:]*:\d+$"))
async def on_browse(c: CallbackQuery):
    await c.answer()
    uid = c.from_user.id
    _, kind, value, page = c.data.split(":")
    lang = await user_lang(uid)
    ui.set_back(uid, c.data)
    text, kb = await browse_view(lang, kind, value, int(page))
    await ui.show_for(c, text, kb)


@router.callback_query(F.data == "favs:open")
async def favs_open(c: CallbackQuery):
    await c.answer()
    uid = c.from_user.id
    lang = await user_lang(uid)
    ui.set_back(uid, "favs:open")
    text, kb = await favorites_view(uid, lang)
    await ui.show_for(c, text, kb)


@router.callback_query(F.data == "noop")
async def on_noop(c: CallbackQuery):
    await c.answer()


# ---------------- kartochkalar ----------------
@router.callback_query(F.data.startswith("movie:"))
async def open_movie(c: CallbackQuery):
    await c.answer()
    uid = c.from_user.id
    lang = await user_lang(uid)
    movie = await db.get_movie(int(c.data.split(":")[1]))
    await render_card(c.bot, c.message.chat.id, uid, lang, movie, c.message)


@router.callback_query(F.data.regexp(r"^tm:(movie|tv):\d+$"))
async def open_tmdb(c: CallbackQuery):
    await c.answer()
    _, media_type, tmdb_id = c.data.split(":")
    uid = c.from_user.id
    await render_tmdb_card(c.bot, c.message.chat.id, uid, await user_lang(uid), media_type, int(tmdb_id), c.message)


@router.callback_query(F.data.regexp(r"^rq:(movie|tv):\d+$"))
async def toggle_req(c: CallbackQuery):
    _, media_type, tmdb_id = c.data.split(":")
    tmdb_id = int(tmdb_id)
    lang = await user_lang(c.from_user.id)
    try:
        d = await tmdb.details_cached(media_type, tmdb_id)
    except tmdb.TMDBError:
        await c.answer(t(lang, "tm_fail"), show_alert=True)
        return
    added = await db.toggle_request(c.from_user.id, media_type, tmdb_id, d["title"], d.get("year"))
    await c.answer(t(lang, "notify_added" if added else "notify_removed"))
    kb = utils.with_nav(
        cards.missing_kb(lang, media_type, tmdb_id, added, d.get("trailer_key")),
        utils.nav_row(lang, "nav:back"),
    )
    await c.message.edit_reply_markup(reply_markup=kb)


@router.callback_query(F.data.startswith("fav:"))
async def toggle_favorite(c: CallbackQuery):
    movie_id = int(c.data.split(":")[1])
    lang = await user_lang(c.from_user.id)
    movie = await db.get_movie(movie_id)
    if not movie or movie["hidden"]:
        await c.answer(t(lang, "not_found"), show_alert=True)
        return
    added, avail, premium = await asyncio.gather(
        db.toggle_fav(c.from_user.id, movie_id), avail_for(movie), db.is_premium(c.from_user.id)
    )
    await c.answer(t(lang, "fav_added" if added else "fav_removed"))
    if avail is False:
        return
    m = dict(movie)
    locked = bool(m.get("is_premium")) and not premium
    await c.message.edit_reply_markup(reply_markup=card_keyboard(lang, m, added, avail, locked))


# ---------------- seriallar: fasl va qismlar (kartochkaning o'zida) ----------------
async def ep_kb(lang: str, movie_id: int, season: int, page: int):
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
    rows.append(utils.nav_row(lang, f"movie:{movie_id}"))
    return kb_of(rows)


async def watch_allowed(movie, user_id: int) -> bool:
    return not movie["is_premium"] or await db.is_premium(user_id)


@router.callback_query(F.data.startswith("se:"))
async def open_season(c: CallbackQuery):
    _, movie_id, season = c.data.split(":")
    lang = await user_lang(c.from_user.id)
    movie, kb = await asyncio.gather(
        db.get_movie(int(movie_id)), ep_kb(lang, int(movie_id), int(season), 0)
    )
    if not movie or movie["hidden"]:
        await c.answer(t(lang, "not_found"), show_alert=True)
        return
    if not await watch_allowed(movie, c.from_user.id):
        await c.answer(t(lang, "lock_alert"), show_alert=True)
        return
    await c.answer()
    title = f"📺 <b>{escape(movie['title'])}</b> — {t(lang, 'season_btn').format(n=season)[2:]}"
    await ui.show_for(c, f"{title}\n\n{t(lang, 'choose_ep')}", kb, keep_photo=True)


@router.callback_query(F.data.startswith("epp:"))
async def episode_page(c: CallbackQuery):
    await c.answer()
    _, movie_id, season, page = c.data.split(":")
    kb = await ep_kb(await user_lang(c.from_user.id), int(movie_id), int(season), int(page))
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
    if not await watch_allowed(movie, c.from_user.id):
        await c.answer(t(lang, "lock_alert"), show_alert=True)
        return
    if len(quals) == 1:
        await c.answer(t(lang, "sending"))
        f = await db.get_file(movie["id"], season, episode, quals[0])
        if f:
            await send_media(c.message, c.from_user.id, movie, f, season, episode, quals[0])
        return
    await c.answer()
    rows = [
        [btn(cards.QBTN.get(q, f"📥 {q}"), f"dl:{movie['id']}:{season}:{episode}:{q}") for q in quals],
        utils.nav_row(lang, f"se:{movie['id']}:{season}"),
    ]
    text = f"🎬 <b>{escape(movie['title'])}</b> • {episode}\n\n{t(lang, 'choose_quality')}"
    await ui.show_for(c, text, kb_of(rows), keep_photo=True)


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
    if not await watch_allowed(movie, c.from_user.id):
        await c.answer(t(lang, "lock_alert"), show_alert=True)
        return
    await c.answer(t(lang, "sending"))
    await send_media(c.message, c.from_user.id, movie, f, int(season), int(episode), quality)
