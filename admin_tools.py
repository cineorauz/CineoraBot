import asyncio
import logging
import time
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import admin
import config
import database as db
import db_extra
import movies
import ui
import utils
from utils import btn, grid, kb_of

router = Router()
router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

S = ui.show_for
_bc = {"running": False, "stop": False}


class Bc(StatesGroup):
    msg = State()


class Um(StatesGroup):
    find = State()
    msg = State()


class Sub(StatesGroup):
    add = State()


# ---------------- yangi admin bosh sahifasi (admin.py dagisini almashtiradi) ----------------
def home_view():
    maint = db.get_setting("maintenance") == "1"
    text = "🛠 <b>Admin panel</b>\n\nBo'limni tanlang 👇"
    if maint:
        text += "\n\n⚠️ <b>Texnik ishlar rejimi yoqilgan</b>"
    kb = kb_of(
        [
            [btn("➕ Qo'shish", "a:add"), btn("📋 Kinolar", "a:lr")],
            [btn("📥 So'rovlar", "a:reqs"), btn("💎 Premium", "ap:home")],
            [btn("📢 Xabar yuborish", "at:bc"), btn("👥 Foydalanuvchilar", "at:users")],
            [btn("📊 Statistika", "at:stats"), btn("📌 Majburiy kanallar", "at:subs")],
            [btn("🖼 Bannerlar", "a:bn"), btn("⚙️ Sozlamalar", "a:set")],
            [btn("🛠 Texnik ishlar: " + ("o'chirish" if maint else "yoqish"), "at:maint")],
            [btn("🏓 Tezlik", "a:ping"), btn("🏠 Bot menyusi", "home")],
        ]
    )
    return text, kb


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


@router.callback_query(F.data == "at:maint")
async def toggle_maint(c: CallbackQuery):
    now = db.get_setting("maintenance") == "1"
    await db.set_setting("maintenance", "0" if now else "1")
    await c.answer("🛠 Texnik ishlar o'chirildi" if now else "🛠 Texnik ishlar yoqildi")
    text, kb = home_view()
    await S(c, text, kb)


# ---------------- yangi qism: kuzatuvchilarga xabar ----------------
@router.callback_query(admin.Add.upload, F.data == "a:up:done")
async def done_wrapper(c: CallbackQuery, state: FSMContext):
    """Yuklashni tugatadi (admin.py dagi asosiy mantiq) va davom etayotgan serialda kuzatuvchilarga xabar yuboradi."""
    d = await state.get_data()
    await admin.on_done(c, state)
    try:
        movie = await db.get_movie(d["movie_id"])
        if d["saved"] and movie["is_series"] and movie["series_status"] == "ongoing":
            season = d["saved"][-1][0]
            numbers = sorted({s[1] for s in d["saved"] if s[0] == season})
            asyncio.create_task(movies.notify_followers(c.bot, movie, season, numbers[0], numbers[-1]))
    except Exception as e:
        logging.warning("Kuzatuvchilarga xabar yuborib bo'lmadi: %s", e)


# ---------------- statistika ----------------
def sparkline(values: list[int]) -> str:
    bars = "▁▂▃▄▅▆▇█"
    top = max(values) if values and max(values) > 0 else 1
    return "".join(bars[min(7, int(v / top * 7))] if v else "▁" for v in values)


def top_lines(rows) -> str:
    if not rows:
        return "—"
    return "\n".join(f"{i}. {escape(r['title'])} — {r['c']}" for i, r in enumerate(rows, 1))


def query_lines(rows) -> str:
    if not rows:
        return "—"
    return "\n".join(f"{i}. {escape(r['q'])} — {r['c']}" for i, r in enumerate(rows, 1))


@router.callback_query(F.data == "at:stats")
async def stats_screen(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer("Hisoblanmoqda...")
    base = await db.stats()
    x = await db_extra.stats_ext()
    u = x["users"]
    conv = f"{u['premium'] / u['total'] * 100:.1f}%" if u["total"] else "—"
    daily = [r["c"] for r in x["daily"]]
    langs = " • ".join(f"{r['lang']}: {r['c']}" for r in x["langs"])
    text = (
        "📊 <b>Statistika</b>\n\n"
        f"👥 <b>Foydalanuvchilar:</b> {u['total']}\n"
        f"🟢 Faol: bugun {u['dau']} • hafta {u['wau']} • oy {u['mau']}\n"
        f"🆕 Yangi: bugun +{u['new_day']} • hafta +{u['new_week']}\n"
        f"📈 7 kun: {sparkline(daily)}  ({', '.join(str(v) for v in daily)})\n"
        f"🌐 {langs}\n🚫 Botni bloklaganlar: {u['blocked']}\n\n"
        f"🎬 <b>Kontent:</b> film {base['movies']} • serial {base['series']} • fayl {base['files']} • 💎 {base['premium_movies']}\n"
        f"📥 Ochiq so'rovlar: {base['requests']}\n\n"
        f"🔥 <b>Top (bugun):</b>\n{top_lines(x['top_day'])}\n\n"
        f"🔥 <b>Top (hafta):</b>\n{top_lines(x['top_week'])}\n\n"
        f"🏆 <b>Top (hammasi):</b>\n{top_lines(x['top_all'])}\n\n"
        f"🔎 <b>Ko'p qidirilgan (hafta):</b>\n{query_lines(x['searches'])}\n\n"
        f"❓ <b>Topilmagan qidiruvlar:</b>\n{query_lines(x['missing'])}\n\n"
        f"💎 <b>Premium:</b> {u['premium']} ({conv})\n"
        f"💰 30 kun: {x['rev']['stars']} ⭐ • {utils.fmt_num(x['rev']['uzs'])} so'm"
    )
    rows = []
    for i, r in enumerate(x["missing"][:3]):
        rows.append([btn(f"➕ «{r['q'][:24]}» ni qo'shish", f"a:sq:{r['q'][:40]}")])
    rows.append([btn("◀️ Orqaga", "a:home")])
    await S(c, text[:4000], kb_of(rows))


@router.callback_query(F.data.startswith("a:sq:"))
async def add_from_search(c: CallbackQuery, state: FSMContext):
    """Topilmagan qidiruvdan kino qo'shishni boshlaydi (TMDB'da qidiradi)."""
    q = c.data[5:]
    await c.answer()
    await state.clear()
    await state.set_state(admin.Add.query)
    try:
        results = await admin.tmdb.search(q)
    except Exception as e:
        await ui.flash(c.bot, c.message.chat.id, f"⚠️ {escape(str(e))}")
        return
    rows = []
    for r in results:
        kind = "Kino" if r["type"] == "movie" else "Serial"
        year = f" ({r['year']})" if r["year"] else ""
        rows.append([btn(f"{r['title']}{year} • {kind}", f"a:tm:{r['type']}:{r['id']}")])
    rows += [[btn("✍️ Qo'lda kiritish", "a:tm:manual")], [btn("❌ Bekor qilish", "a:home")]]
    await S(c, f"🔎 «{escape(q)}» bo'yicha TMDB natijalari:" if results else "😕 TMDB'da topilmadi.", kb_of(rows))


# ---------------- xabar yuborish (reklama) ----------------
@router.callback_query(F.data == "at:bc")
async def bc_start(c: CallbackQuery, state: FSMContext):
    if _bc["running"]:
        await c.answer("Hozir boshqa xabar yuborilmoqda", show_alert=True)
        return
    await state.clear()
    await state.set_state(Bc.msg)
    await c.answer()
    await S(
        c,
        "📢 <b>Xabar yuborish</b>\n\nYubormoqchi bo'lgan xabarni shu yerga yuboring "
        "(matn, rasm, video, hujjat; izoh va formatlash saqlanadi).",
        kb_of([[btn("❌ Bekor qilish", "a:home")]]),
    )


@router.message(Bc.msg, ~F.text.startswith("/"))
async def bc_got_message(m: Message, state: FSMContext):
    await state.update_data(src_chat=m.chat.id, src_msg=m.message_id)
    cnt = await db_extra.audience_counts()
    kb = kb_of(
        [
            [btn(f"👥 Hammasi ({cnt['total']})", "at:bk:all")],
            [btn(f"💎 Premium ({cnt['prem']})", "at:bk:prem"), btn(f"🆓 Premiumsiz ({cnt['free']})", "at:bk:free")],
            [btn(f"🇺🇿 ({cnt['uz']})", "at:bk:uz"), btn(f"🇬🇧 ({cnt['en']})", "at:bk:en"), btn(f"🇷🇺 ({cnt['ru']})", "at:bk:ru")],
            [btn("❌ Bekor qilish", "a:home")],
        ]
    )
    # Yuqoridagi xabaringiz namuna (oldindan ko'rish) bo'lib turadi
    await ui.show(
        m.bot, m.chat.id, m.from_user.id,
        "👆 Shu xabar yuboriladi.\n\nKimlarga yuboramiz?", kb, force_new=True,
    )


@router.callback_query(Bc.msg, F.data.regexp(r"^at:bk:(all|prem|free|uz|en|ru)$"))
async def bc_confirm(c: CallbackQuery, state: FSMContext):
    kind = c.data.split(":")[2]
    count = len(await db_extra.audience(kind))
    await c.answer()
    await S(
        c,
        f"📢 Tasdiqlang: <b>{count}</b> ta foydalanuvchiga yuboriladi.",
        kb_of([[btn("🚀 Yuborish", f"at:bs:{kind}")], [btn("❌ Bekor qilish", "a:home")]]),
    )


def progress_text(sent, blocked, failed, total, done=False, stopped=False):
    head = "✅ <b>Yuborish tugadi</b>" if done and not stopped else (
        "⏹ <b>To'xtatildi</b>" if stopped else "📤 <b>Yuborilmoqda...</b>"
    )
    return (
        f"{head}\n\n📨 Yuborildi: {sent}\n🚫 Bloklagan: {blocked}\n⚠️ Xato: {failed}\n"
        f"📊 {sent + blocked + failed}/{total}"
    )


async def run_broadcast(bot, chat_id, progress_id, src_chat, src_msg, kind):
    ids = await db_extra.audience(kind)
    total = len(ids)
    sent = blocked = failed = 0
    last = 0.0
    stopped = False
    stop_kb = kb_of([[btn("⏹ To'xtatish", "at:bx")]])

    async def edit(text, kb):
        try:
            await bot.edit_message_text(text, chat_id=chat_id, message_id=progress_id, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass

    for uid in ids:
        if _bc["stop"]:
            stopped = True
            break
        ok = False
        for _attempt in range(2):
            try:
                await bot.copy_message(uid, src_chat, src_msg)
                sent += 1
                ok = True
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except TelegramForbiddenError:
                blocked += 1
                db_extra.mark_blocked(uid)
                ok = True
                break
            except Exception:
                break
        if not ok:
            failed += 1
        await asyncio.sleep(0.05)
        if time.monotonic() - last > 3:
            last = time.monotonic()
            await edit(progress_text(sent, blocked, failed, total), stop_kb)
    _bc["running"] = False
    await edit(
        progress_text(sent, blocked, failed, total, done=True, stopped=stopped),
        kb_of([[btn("🛠 Admin panel", "a:home")]]),
    )


@router.callback_query(Bc.msg, F.data.regexp(r"^at:bs:(all|prem|free|uz|en|ru)$"))
async def bc_send(c: CallbackQuery, state: FSMContext):
    if _bc["running"]:
        await c.answer("Hozir boshqa xabar yuborilmoqda", show_alert=True)
        return
    d = await state.get_data()
    kind = c.data.split(":")[2]
    await state.clear()
    await c.answer("🚀 Boshlandi")
    _bc["running"] = True
    _bc["stop"] = False
    sent = await ui.show(
        c.bot, c.message.chat.id, c.from_user.id, progress_text(0, 0, 0, 0),
        kb_of([[btn("⏹ To'xtatish", "at:bx")]]), source=c.message,
    )
    progress_id = sent.message_id if sent else c.message.message_id
    asyncio.create_task(
        run_broadcast(c.bot, c.message.chat.id, progress_id, d["src_chat"], d["src_msg"], kind)
    )


@router.callback_query(F.data == "at:bx")
async def bc_stop(c: CallbackQuery):
    _bc["stop"] = True
    await c.answer("⏹ To'xtatilmoqda...")


# ---------------- foydalanuvchilar ----------------
@router.callback_query(F.data == "at:users")
async def users_home(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    cnt = await db_extra.audience_counts()
    text = (
        "👥 <b>Foydalanuvchilar</b>\n\n"
        f"Faol (bloklamagan): <b>{cnt['total']}</b> • 💎 {cnt['prem']}\n"
        f"🇺🇿 {cnt['uz']} • 🇬🇧 {cnt['en']} • 🇷🇺 {cnt['ru']}"
    )
    await S(c, text, kb_of([[btn("🔎 ID yoki @username bo'yicha topish", "at:uf")], [btn("◀️ Orqaga", "a:home")]]))


@router.callback_query(F.data == "at:uf")
async def user_find_ask(c: CallbackQuery, state: FSMContext):
    await state.set_state(Um.find)
    await c.answer()
    await S(c, "🔎 Foydalanuvchi ID raqamini yoki @username ni yuboring:", kb_of([[btn("❌ Bekor qilish", "at:users")]]))


def user_view(r):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    name = escape(r["first_name"] or "—")
    uname = f" @{escape(r['username'])}" if r["username"] else ""
    prem = utils.fmt_date(r["premium_until"]) + " gacha" if r["premium_until"] and r["premium_until"] > now else "yo'q"
    seen = utils.fmt_date(r["last_seen"]) if r["last_seen"] else "—"
    state_txt = "⛔ Bloklangan" if r["banned"] else ("🚫 Botni bloklagan" if r["blocked"] else "✅ Faol")
    uid = r["user_id"]
    text = (
        f"👤 <b>{name}</b>{uname}\n🆔 <code>{uid}</code> • 🌐 {r['lang'] or '—'}\n"
        f"📅 Qo'shilgan: {utils.fmt_date(r['joined_at'])} • 👁 Oxirgi faollik: {seen}\n"
        f"💎 Premium: {prem}\n📥 Yuklashlar: {r['downloads']}\n📌 Holat: {state_txt}"
    )
    kb = kb_of(
        [
            [btn("🎁 +7 kun", f"at:ug:{uid}:7"), btn("🎁 +30 kun", f"at:ug:{uid}:30"), btn("🎁 +90 kun", f"at:ug:{uid}:90")],
            [btn("🚫 Premiumni olish", f"at:ur:{uid}")],
            [btn("✅ Blokdan chiqarish" if r["banned"] else "⛔ Bloklash", f"at:ub:{uid}")],
            [btn("✉️ Xabar yozish", f"at:um:{uid}")],
            [btn("◀️ Orqaga", "at:users")],
        ]
    )
    return text, kb


@router.message(Um.find, F.text & ~F.text.startswith("/"))
async def user_find(m: Message, state: FSMContext):
    await ui.delete_message(m)
    row = await db_extra.find_user(m.text)
    if not row:
        await ui.flash(m.bot, m.chat.id, "😕 Foydalanuvchi topilmadi (u botda /start bosgan bo'lishi kerak).")
        return
    await state.clear()
    text, kb = user_view(row)
    await S(m, text, kb)


async def reopen_user(c: CallbackQuery, uid: int):
    row = await db_extra.user_row(uid)
    if row:
        text, kb = user_view(row)
        await S(c, text, kb)


@router.callback_query(F.data.regexp(r"^at:ug:\d+:\d+$"))
async def user_grant(c: CallbackQuery):
    _, _, uid, days = c.data.split(":")
    uid, days = int(uid), int(days)
    until = await db.grant_premium(uid, days, method="admin")
    lang = await db.get_lang(uid) or "uz"
    from locales import t

    try:
        await c.bot.send_message(uid, t(lang, "promo_ok").format(days=days, date=utils.fmt_date(until)))
    except Exception:
        pass
    await c.answer(f"✅ +{days} kun")
    await reopen_user(c, uid)


@router.callback_query(F.data.regexp(r"^at:ur:\d+$"))
async def user_revoke(c: CallbackQuery):
    uid = int(c.data.split(":")[2])
    await db.revoke_premium(uid)
    await c.answer("Premium olindi")
    await reopen_user(c, uid)


@router.callback_query(F.data.regexp(r"^at:ub:\d+$"))
async def user_ban(c: CallbackQuery):
    uid = int(c.data.split(":")[2])
    new = not db_extra.is_banned(uid)
    await db_extra.set_banned(uid, new)
    await c.answer("⛔ Bloklandi" if new else "✅ Blokdan chiqarildi")
    await reopen_user(c, uid)


@router.callback_query(F.data.regexp(r"^at:um:\d+$"))
async def user_msg_ask(c: CallbackQuery, state: FSMContext):
    uid = int(c.data.split(":")[2])
    await state.set_state(Um.msg)
    await state.update_data(target=uid)
    await c.answer()
    await S(c, "✉️ Foydalanuvchiga yuboriladigan xabarni yozing:", kb_of([[btn("❌ Bekor qilish", f"at:uv:{uid}")]]))


@router.callback_query(F.data.regexp(r"^at:uv:\d+$"))
async def user_back(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    await reopen_user(c, int(c.data.split(":")[2]))


@router.message(Um.msg, ~F.text.startswith("/"))
async def user_msg_send(m: Message, state: FSMContext):
    uid = (await state.get_data())["target"]
    await state.clear()
    try:
        await m.bot.copy_message(uid, m.chat.id, m.message_id)
        note = "✅ Xabar yuborildi"
    except Exception as e:
        note = f"⚠️ Yuborib bo'lmadi: {e}"
    await ui.delete_message(m)
    row = await db_extra.user_row(uid)
    if row:
        text, kb = user_view(row)
        await S(m, f"{escape(note)}\n\n{text}", kb)


# ---------------- majburiy obuna kanallari ----------------
def subs_screen():
    chans = utils.channels()
    lines = ["📌 <b>Majburiy obuna kanallari</b>\n"]
    if chans:
        lines += [f"{i}. {escape(utils.chan_title(ch))}" for i, ch in enumerate(chans, 1)]
    else:
        lines.append("Hozircha yo'q (obuna talab qilinmaydi).")
    if db.get_setting("sub_channels", "ENV") == "ENV":
        lines.append("\n<i>Hozir Render sozlamasidagi (CHANNELS) ro'yxat ishlatilmoqda.</i>")
    rows = [[btn(f"🗑 {i}-ni olib tashlash", f"at:sx:{i - 1}")] for i in range(1, len(chans) + 1)]
    rows.append([btn("➕ Kanal qo'shish", "at:sa")])
    rows.append([btn("♻️ Render sozlamasiga qaytish", "at:sd")])
    rows.append([btn("◀️ Orqaga", "a:home")])
    return "\n".join(lines), kb_of(rows)


@router.callback_query(F.data == "at:subs")
async def subs_open(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    text, kb = subs_screen()
    await S(c, text, kb)


@router.callback_query(F.data == "at:sd")
async def subs_default(c: CallbackQuery):
    await db.set_setting("sub_channels", "ENV")
    await c.answer("Render sozlamasiga qaytdi")
    text, kb = subs_screen()
    await S(c, text, kb)


@router.callback_query(F.data.regexp(r"^at:sx:\d+$"))
async def subs_remove(c: CallbackQuery):
    idx = int(c.data.split(":")[2])
    chans = utils.channels()
    if 0 <= idx < len(chans):
        chans.pop(idx)
    await db.set_setting("sub_channels", ",".join(chans))
    await c.answer("🗑 Olib tashlandi")
    text, kb = subs_screen()
    await S(c, text, kb)


@router.callback_query(F.data == "at:sa")
async def subs_add_ask(c: CallbackQuery, state: FSMContext):
    await state.set_state(Sub.add)
    await c.answer()
    await S(
        c,
        "📌 <b>Kanal qo'shish</b>\n\nBotni avval kanalga <b>admin</b> qiling.\n\n"
        "• Ochiq kanal: <code>@kanal_nomi</code>\n"
        "• Yopiq kanal: <code>-1001234567890 https://t.me/+AbCdEf...</code> (ID va taklif havolasi)",
        kb_of([[btn("❌ Bekor qilish", "at:subs")]]),
    )


@router.message(Sub.add, F.text & ~F.text.startswith("/"))
async def subs_add_do(m: Message, state: FSMContext):
    await ui.delete_message(m)
    txt = m.text.strip()
    parts = txt.split()
    if txt.startswith("@") and len(parts) == 1:
        entry, ref = txt, txt
    elif len(parts) == 2 and parts[0].lstrip("-").isdigit() and parts[1].startswith("https://t.me/"):
        entry, ref = f"{parts[0]}|{parts[1]}", int(parts[0])
    else:
        await ui.flash(m.bot, m.chat.id, "⚠️ Format noto'g'ri. Qayta yuboring.", 5)
        return
    try:
        me = await m.bot.get_me()
        member = await m.bot.get_chat_member(ref, me.id)
        if member.status not in ("administrator", "creator"):
            raise ValueError("Bot bu kanalda admin emas")
    except Exception as e:
        await ui.flash(m.bot, m.chat.id, f"⚠️ {escape(str(e))}", 6)
        return
    await state.clear()
    chans = utils.channels()
    if entry not in chans:
        chans.append(entry)
    await db.set_setting("sub_channels", ",".join(chans))
    text, kb = subs_screen()
    await S(m, text, kb)


# ---------------- noto'g'ri kiritishlar (eng oxirida) ----------------
@router.message(StateFilter(Bc, Um, Sub))
async def wrong_input(m: Message):
    await ui.delete_message(m)
    await ui.flash(m.bot, m.chat.id, "⚠️ Iltimos, so'ralgan narsani yuboring yoki tugmani bosing.")
