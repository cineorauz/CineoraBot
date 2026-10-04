import asyncio
import logging
from datetime import datetime, timezone
from html import escape
from urllib.parse import quote

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import admin
import admin_tools
import ai
import config
import database as db
import growth
import movies
import support
import ui
import utils
import ux
from genres import CATEGORIES, cat_icon, cat_label
from locales import t
from utils import btn, grid, kb_of, nav_row

user_router = Router()
admin_router = Router()
admin_router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
admin_router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

# Boshqa modullar profil va admin panelga qator qo'shishi uchun
PROFILE_ROWS: list = []   # async def(uid, lang) -> [qator, ...]
GROWTH_ROWS: list = []    # async def() -> [qator, ...]

LIB_PER = 8
TABS = {"s": ("tab_saved", "lib_saved", "empty_saved"), "h": ("tab_hist", "lib_hist", "empty_hist")}
REASONS = {"f": ("rep_file", "Fayl ishlamayapti"), "q": ("rep_quality", "Tarjima / sifat xato"), "l": ("rep_legal", "Huquqbuzarlik")}
_reported: set = set()


class CollName(StatesGroup):
    name = State()


class SrcName(StatesGroup):
    name = State()


async def lang_of(uid: int) -> str:
    return await db.get_lang(uid) or "uz"


async def scr(target, text: str, kb, slot: str = "generic"):
    return await ui.show_for(target, text, kb, photo=utils.banner(slot))


# ---------------- bosh menyu (utils.show_home o'rnini bosadi) ----------------
async def show_home(bot, chat_id: int, user_id: int, lang: str, source=None, name=None):
    ui.set_back(user_id, "home")
    counts, cont = await asyncio.gather(db.category_counts(), utils.continue_button(user_id, lang))
    head = ux.u(lang, "home_hello").format(name=escape(name)) if name is not None else ux.u(lang, "home_menu")
    text = f"{head}\n{ux.u(lang, 'home_hint')}"
    rows = []
    if cont:
        rows.append([btn(cont[0], cont[1])])
    cats = [
        btn(f"{cat_icon(c)} {cat_label(c, lang)}", f"br:c:{i}:0:n")
        for i, c in enumerate(CATEGORIES)
        if counts.get(c)
    ]
    rows += grid(cats, 2)
    rows.append([btn(ux.u(lang, "b_ai"), "ai:0"), btn(ux.u(lang, "b_lib"), "lb:s:0"), btn(ux.u(lang, "b_profile"), "nav:profile")])
    if user_id in config.ADMIN_IDS:
        rows.append([btn("🛠 Admin panel", "a:home")])
    await ui.show(bot, chat_id, user_id, text, kb_of(rows), photo=utils.banner("home"), source=source)


utils.show_home = show_home  # boshqa fayllar utils.show_home deb chaqirsa ham yangi menyu chiqadi


# ---------------- profil ----------------
async def profile_view(uid: int, lang: str):
    ui.set_back(uid, "nav:profile")
    until = await db.premium_until(uid)
    now = datetime.now(timezone.utc)
    prem = t(lang, "prem_yes").format(date=utils.fmt_date(until)) if until and until > now else t(lang, "prem_no")
    ref = await growth.ref_stats(uid)
    text = ux.u(lang, "prof").format(prem=prem, refs=ref["total"], uid=uid)
    first = [btn(t(lang, "prem_btn"), "prem:open")]
    if growth.ref_days() > 0:
        first.append(btn(ux.u(lang, "b_invite"), "ref:open"))
    rows = [first, [btn(t(lang, "change_lang"), "lang_open"), btn(support.tx(lang, "help_btn"), "sp:h")]]
    for fn in PROFILE_ROWS:
        rows += await fn(uid, lang)
    rows.append(nav_row(lang))
    return text, kb_of(rows)


@user_router.callback_query(F.data.in_({"nav:profile", "nav:more"}))
async def on_profile(c: CallbackQuery):
    await c.answer()
    uid = c.from_user.id
    text, kb = await profile_view(uid, await lang_of(uid))
    await scr(c, text, kb)


# ---------------- kutubxona: saqlangan / ko'rilgan ----------------
async def library_view(uid: int, lang: str, tab: str, page: int):
    if tab not in TABS:
        tab = "s"
    rows = list(await (growth.history(uid) if tab == "h" else db.list_favs(uid)))
    pages = max(1, -(-len(rows) // LIB_PER))
    page = max(0, min(page, pages - 1))
    ui.set_back(uid, f"lb:{tab}:{page}")
    kb = [[btn(("• " if k == tab else "") + ux.u(lang, v[0]), f"lb:{k}:0") for k, v in TABS.items()]]
    if not rows:
        text = ux.u(lang, TABS[tab][2])
    else:
        chunk = rows[page * LIB_PER : (page + 1) * LIB_PER]
        kb += [[btn(ux.item_label(r), f"movie:{r['id']}")] for r in chunk]
        kb += ux.pager_row(page, pages, lambda p: f"lb:{tab}:{p}")
        text = ux.u(lang, "list_head").format(title=ux.u(lang, TABS[tab][1]), p=page + 1, pages=pages, total=len(rows))
    kb.append(nav_row(lang))
    return text, kb_of(kb)


@user_router.callback_query(F.data.regexp(r"^lb:[srh]:\d+$"))
async def on_library(c: CallbackQuery):
    await c.answer()
    uid = c.from_user.id
    _, tab, page = c.data.split(":")
    text, kb = await library_view(uid, await lang_of(uid), "h" if tab == "h" else "s", int(page))
    await scr(c, text, kb)


@user_router.callback_query(F.data.regexp(r"^(fv|rl):\d+$") | (F.data == "favs:open"))
async def legacy_library(c: CallbackQuery):
    """Eski tugmalar (Ko'rmoqchiman / Baholanganlar) yangi kutubxonaga olib boradi."""
    await c.answer()
    uid = c.from_user.id
    text, kb = await library_view(uid, await lang_of(uid), "s", 0)
    await scr(c, text, kb)


@user_router.message(Command("favorites"))
async def favorites_cmd(m: Message):
    uid = m.from_user.id
    await ui.delete_message(m)
    text, kb = await library_view(uid, await lang_of(uid), "s", 0)
    await scr(m, text, kb)


# ---------------- to'plamlar (foydalanuvchi; ✨ Maslahat ichidan ochiladi) ----------------
async def colls_view(uid: int, lang: str):
    ui.set_back(uid, "cl:0")
    rows = await growth.coll_public()
    if not rows:
        return ux.u(lang, "co_empty"), kb_of([nav_row(lang, "ai:0")])
    kb = [[btn(f"{r['emoji']} {r['title']} ({r['n']})", f"co:{r['id']}")] for r in rows]
    kb.append(nav_row(lang, "ai:0"))
    return ux.u(lang, "co_title"), kb_of(kb)


async def coll_view(uid: int, lang: str, cid: int):
    ui.set_back(uid, f"co:{cid}")
    coll = await growth.coll_get(cid)
    items = await growth.coll_items(cid) if coll else []
    if not items:
        return t(lang, "empty"), kb_of([nav_row(lang, "cl:0")])
    kb = [[btn(ux.item_label(r), f"movie:{r['id']}")] for r in items]
    kb.append(nav_row(lang, "cl:0"))
    return f"{coll['emoji']} <b>{escape(coll['title'])}</b>\n<i>{len(items)}</i>", kb_of(kb)


@user_router.callback_query(F.data == "cl:0")
async def on_colls(c: CallbackQuery):
    await c.answer()
    uid = c.from_user.id
    text, kb = await colls_view(uid, await lang_of(uid))
    await scr(c, text, kb)


@user_router.callback_query(F.data.regexp(r"^co:\d+$"))
async def on_coll(c: CallbackQuery):
    await c.answer()
    uid = c.from_user.id
    text, kb = await coll_view(uid, await lang_of(uid), int(c.data.split(":")[1]))
    await scr(c, text, kb)


# «Orqaga» tugmasi shu ekranlarga qaytara olishi uchun
async def _route(bot, chat_id, uid, lang, route, source):
    kind = route.split(":")[0]
    if kind == "lb":
        _, tab, page = route.split(":")
        text, kb = await library_view(uid, lang, tab, int(page))
    elif kind == "co":
        text, kb = await coll_view(uid, lang, int(route.split(":")[1]))
    elif kind == "nav":
        text, kb = await profile_view(uid, lang)
    else:
        text, kb = await colls_view(uid, lang)
    await ui.show(bot, chat_id, uid, text, kb, photo=utils.banner("generic"), source=source)


for _prefix in ("lb:", "co:", "cl:", "nav:profile"):
    movies.ROUTES[_prefix] = _route


# ---------------- referal ----------------
@user_router.callback_query(F.data == "ref:open")
async def on_referral(c: CallbackQuery):
    await c.answer()
    uid = c.from_user.id
    lang = await lang_of(uid)
    st = await growth.ref_stats(uid)
    link = f"https://t.me/{utils.BOT_USERNAME}?start=r_{uid}"
    text = ux.u(lang, "ref").format(days=growth.ref_days(), link=link, total=st["total"], ok=st["ok"], earned=st["earned"])
    share = f"https://t.me/share/url?url={quote(link, safe='')}&text={quote(ux.u(lang, 'ref_share'), safe='')}"
    await scr(c, text, kb_of([[utils.url_btn(ux.u(lang, "ref_send"), share)], nav_row(lang, "nav:profile")]))


# ---------------- shikoyat ----------------
@user_router.callback_query(F.data.regexp(r"^rpt:\d+$"))
async def report_open(c: CallbackQuery):
    mid = int(c.data.split(":")[1])
    uid = c.from_user.id
    lang = await lang_of(uid)
    movie = await db.get_movie(mid)
    if not movie or movie["hidden"]:
        await c.answer(t(lang, "not_found"), show_alert=True)
        return
    await c.answer()
    rows = [[btn(ux.u(lang, v[0]), f"rpr:{mid}:{k}")] for k, v in REASONS.items()]
    rows.append([btn(t(lang, "back"), f"mx:{mid}")])
    await ui.show_for(
        c, ux.u(lang, "rep_title").format(title=escape(movie["title"])), kb_of(rows),
        photo=movies.poster_of(movie), keep_photo=True,
    )


@user_router.callback_query(F.data.regexp(r"^rpr:\d+:[fql]$"))
async def report_send(c: CallbackQuery):
    _, mid, k = c.data.split(":")
    mid = int(mid)
    uid = c.from_user.id
    lang = await lang_of(uid)
    movie = await db.get_movie(mid)
    if not movie:
        await c.answer(t(lang, "not_found"), show_alert=True)
        return
    key = (uid, mid, k)
    if key not in _reported and (uid in config.ADMIN_IDS or not support.too_fast(uid)):
        _reported.add(key)
        reason = REASONS[k][1]
        tid = await support.open_ticket(uid)
        await support.add_msg(tid, False, f"🚩 Shikoyat: {reason} • {movie['title']} (#{mid})")
        text = (
            f"🚩 <b>Shikoyat</b> • #{tid}\n🎬 {escape(movie['title'])} (#{mid})\n❗ {reason}\n"
            f"👤 {escape(c.from_user.full_name)} (<code>{uid}</code>)"
        )
        kb = kb_of([
            [btn("↩️ Javob berish", f"sp:r:{tid}"), btn("📂 Suhbat", f"sp:v:{tid}")],
            [btn("🙈 Yashirish", f"hc:{mid}"), btn("📋 Kino sahifasi", f"a:m:{mid}")],
        ])
        for admin_id in config.ADMIN_IDS:
            try:
                await c.bot.send_message(admin_id, text, reply_markup=kb, parse_mode="HTML")
            except Exception as e:
                logging.warning("Shikoyatni adminga yuborib bo'lmadi: %s", e)
        await support.refresh_count()
    await c.answer(ux.u(lang, "rep_thanks"), show_alert=True)
    await movies.render_card(c.bot, c.message.chat.id, uid, lang, movie, c.message, keep=True)


@admin_router.callback_query(F.data.regexp(r"^hc:\d+$"))
async def hide_from_report(c: CallbackQuery):
    mid = int(c.data.split(":")[1])
    await db.pool.execute("UPDATE movies SET hidden = TRUE WHERE id=$1", mid)
    db.invalidate()
    await c.answer("🙈 Yashirildi", show_alert=True)
    try:
        await c.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


# ---------------- admin: to'plamlar ----------------
_orig_home_view = admin_tools.home_view
_orig_movie_page = admin.movie_page


def home_view():
    text, kb = _orig_home_view()
    rows = list(kb.inline_keyboard)
    at = next((i for i, r in enumerate(rows) if any(b.callback_data == "at:bc" for b in r)), len(rows) - 1)
    rows.insert(at, [btn("📚 To'plamlar", "col:l"), btn("📈 O'sish", "gr:home")])
    return text, kb_of(rows)


async def movie_page(movie_id: int):
    page = await _orig_movie_page(movie_id)
    if not page:
        return page
    text, kb = page
    rows = list(kb.inline_keyboard)
    rows[-2:-2] = [[btn("📚 To'plamga", f"col:x:{movie_id}")]]
    return text, kb_of(rows)


admin_tools.home_view = home_view
admin.movie_page = movie_page

AS = ui.show_for


async def colls_admin_view():
    rows = await growth.coll_all()
    kb = [[btn(f"{r['emoji']} {r['title']} ({r['n']})", f"col:o:{r['id']}")] for r in rows]
    kb.append([btn("➕ Yangi to'plam", "col:n")])
    kb.append([btn("◀️ Admin panel", "a:home")])
    text = "📚 <b>To'plamlar</b>\n\nKino qo'shish: kino sahifasi → «📚 To'plamga». Foydalanuvchilar ularni ✨ Maslahat ichida ko'radi."
    return text, kb_of(kb)


async def coll_admin_view(cid: int):
    coll = await growth.coll_get(cid)
    if not coll:
        return None
    items = await growth.coll_items(cid, visible=False)
    kb = [[btn(f"🗑 {r['title'][:40]}", f"col:r:{cid}:{r['id']}")] for r in items]
    kb.append([btn("🗑 To'plamni o'chirish", f"col:d:{cid}")])
    kb.append([btn("◀️ To'plamlar", "col:l")])
    head = f"{coll['emoji']} <b>{escape(coll['title'])}</b>\n"
    text = head + ("Olib tashlash uchun kinoni bosing:" if items else "Hali kino yo'q.")
    return text, kb_of(kb)


async def movie_colls_view(movie_id: int):
    rows = await growth.coll_all()
    have = await growth.coll_of(movie_id)
    kb = [[btn(("✅ " if r["id"] in have else "") + f"{r['emoji']} {r['title']}", f"col:a:{movie_id}:{r['id']}")] for r in rows]
    kb.append([btn("➕ Yangi to'plam", f"col:nm:{movie_id}")])
    kb.append([btn("◀️ Kino sahifasi", f"a:m:{movie_id}")])
    return "📚 <b>Qaysi to'plamga qo'shamiz?</b>", kb_of(kb)


@admin_router.callback_query(F.data == "col:l")
async def col_list(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    text, kb = await colls_admin_view()
    await AS(c, text, kb)


@admin_router.callback_query(F.data.regexp(r"^col:o:\d+$"))
async def col_open(c: CallbackQuery):
    view = await coll_admin_view(int(c.data.split(":")[2]))
    if not view:
        await c.answer("Topilmadi", show_alert=True)
        return
    await c.answer()
    await AS(c, view[0], view[1])


@admin_router.callback_query(F.data.regexp(r"^col:r:\d+:\d+$"))
async def col_remove(c: CallbackQuery):
    _, _, cid, mid = c.data.split(":")
    await db.pool.execute("DELETE FROM collection_items WHERE collection_id=$1 AND movie_id=$2", int(cid), int(mid))
    db.invalidate()
    await c.answer("🗑 Olib tashlandi")
    view = await coll_admin_view(int(cid))
    if view:
        await AS(c, view[0], view[1])


@admin_router.callback_query(F.data.regexp(r"^col:d:\d+$"))
async def col_delete(c: CallbackQuery):
    await growth.coll_delete(int(c.data.split(":")[2]))
    await c.answer("🗑 O'chirildi")
    text, kb = await colls_admin_view()
    await AS(c, text, kb)


@admin_router.callback_query(F.data.regexp(r"^col:x:\d+$"))
async def col_pick(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    text, kb = await movie_colls_view(int(c.data.split(":")[2]))
    await AS(c, text, kb)


@admin_router.callback_query(F.data.regexp(r"^col:a:\d+:\d+$"))
async def col_toggle(c: CallbackQuery):
    _, _, mid, cid = c.data.split(":")
    added = await growth.coll_toggle(int(cid), int(mid))
    await c.answer("✅ Qo'shildi" if added else "Olib tashlandi")
    text, kb = await movie_colls_view(int(mid))
    await AS(c, text, kb)


@admin_router.callback_query(F.data.regexp(r"^col:(n|nm:\d+)$"))
async def col_new_ask(c: CallbackQuery, state: FSMContext):
    parts = c.data.split(":")
    mid = int(parts[2]) if parts[1] == "nm" else None
    await state.set_state(CollName.name)
    await state.update_data(mid=mid)
    await c.answer()
    back = f"col:x:{mid}" if mid else "col:l"
    await AS(c, "📚 <b>Yangi to'plam</b>\n\nNomini yozing (masalan: «Marvel tartibi»):", kb_of([[btn("❌ Bekor qilish", back)]]))


@admin_router.message(CollName.name, F.text & ~F.text.startswith("/"))
async def col_new_save(m: Message, state: FSMContext):
    mid = (await state.get_data()).get("mid")
    await state.clear()
    await ui.delete_message(m)
    cid = await growth.coll_create(m.text.strip())
    if mid:
        await growth.coll_toggle(cid, mid)
        text, kb = await movie_colls_view(mid)
    else:
        text, kb = await colls_admin_view()
    await AS(m, text, kb)


# ---------------- admin: o'sish, limitlar, AI, manbalar ----------------
async def growth_view():
    lim, days, cap = growth.free_limit(), growth.ref_days(), growth.ref_cap()
    ail = ai.free_limit()
    text = (
        "📈 <b>O'sish va limitlar</b>\n\n"
        f"🎟 Kunlik bepul video limiti (Premiumsizlar): <b>{lim if lim else 'o‘chiq'}</b>\n"
        f"👥 Referal mukofoti: <b>{days}</b> kun (ko'pi bilan {cap} do'st)\n"
        f"{ai.status_text()} • bepul so'rov: <b>{ail}</b>/kun"
    )
    rows = [
        [btn(("✅ " if lim == v else "") + (f"🎟 {v}" if v else "🎟 O'chiq"), f"gr:l:{v}") for v in (0, 3, 5, 10)],
        [btn(("✅ " if days == v else "") + f"👥 {v} kun", f"gr:d:{v}") for v in (0, 2, 3, 5, 7)],
        [btn("🤖 AI maslahat: " + ("yoqiq ✅" if ai.switch_on() else "o'chiq ⛔"), "gr:ai")],
        [btn(("✅ " if ail == v else "") + f"🤖 {v}/kun", f"gr:a:{v}") for v in (2, 3, 5, 10)],
        [btn("🔗 Manbalar (reklama havolalari)", "gr:src")],
    ]
    for fn in GROWTH_ROWS:
        rows += await fn()
    rows.append([btn("◀️ Orqaga", "a:home")])
    return text, kb_of(rows)


@admin_router.callback_query(F.data == "gr:home")
async def gr_home(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    text, kb = await growth_view()
    await AS(c, text, kb)


@admin_router.callback_query(F.data.regexp(r"^gr:(l|d|a):\d+$"))
async def gr_set(c: CallbackQuery):
    _, kind, val = c.data.split(":")
    val = int(val)
    if kind == "l" and val in (0, 3, 5, 10):
        await db.set_setting("free_limit", str(val))
    elif kind == "d" and val in (0, 2, 3, 5, 7):
        await db.set_setting("ref_days", str(val))
    elif kind == "a" and val in (2, 3, 5, 10):
        await db.set_setting("ai_limit", str(val))
    else:
        await c.answer()
        return
    await c.answer("✅")
    text, kb = await growth_view()
    await AS(c, text, kb)


@admin_router.callback_query(F.data == "gr:ai")
async def gr_ai(c: CallbackQuery):
    await db.set_setting("ai_on", "0" if ai.switch_on() else "1")
    await c.answer("✅")
    text, kb = await growth_view()
    await AS(c, text, kb)


async def sources_view(note: str = ""):
    rows = await growth.sources()
    lines = ["🔗 <b>Manbalar</b>\n"]
    if rows:
        lines += [f"• <code>{escape(r['source'])}</code> — {r['n']} ta (video ko'rgan: {r['active']})" for r in rows]
    else:
        lines.append("Hali manba orqali kelgan foydalanuvchi yo'q.")
    lines.append("\nHar bir reklama joyi uchun alohida havola yarating va statistikani shu yerda kuzating.")
    text = (note + "\n\n" if note else "") + "\n".join(lines)
    return text, kb_of([[btn("➕ Yangi havola", "gr:srcnew")], [btn("◀️ Orqaga", "gr:home")]])


@admin_router.callback_query(F.data == "gr:src")
async def gr_src(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    text, kb = await sources_view()
    await AS(c, text, kb)


@admin_router.callback_query(F.data == "gr:srcnew")
async def gr_src_new(c: CallbackQuery, state: FSMContext):
    await state.set_state(SrcName.name)
    await c.answer()
    await AS(
        c, "🔗 Manba nomini yozing (lotin harf, raqam, _ ). Masalan: <code>tgkanal</code>, <code>insta</code>",
        kb_of([[btn("❌ Bekor qilish", "gr:src")]]),
    )


@admin_router.message(SrcName.name, F.text & ~F.text.startswith("/"))
async def gr_src_save(m: Message, state: FSMContext):
    import re

    await ui.delete_message(m)
    slug = re.sub(r"[^a-z0-9_]", "", m.text.strip().lower())[:24]
    if not slug:
        await ui.flash(m.bot, m.chat.id, "⚠️ Faqat lotin harf, raqam va _ ishlating.")
        return
    await state.clear()
    link = f"https://t.me/{utils.BOT_USERNAME}?start=s_{slug}"
    text, kb = await sources_view(f"✅ Havola tayyor:\n<code>{link}</code>")
    await AS(m, text, kb)


@admin_router.message(StateFilter(CollName, SrcName))
async def hub_wrong(m: Message):
    await ui.delete_message(m)
    await ui.flash(m.bot, m.chat.id, "⚠️ Matn ko'rinishida yuboring yoki tugmani bosing.")
