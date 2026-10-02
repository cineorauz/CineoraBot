import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import config
import database as db
import ui
import utils
from utils import btn, grid, kb_of

user_router = Router()
admin_router = Router()
admin_router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
admin_router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))


class Support(StatesGroup):
    wait = State()


class SupportAdmin(StatesGroup):
    reply = State()


T = {
    "uz": {
        "help_text": (
            "🆘 <b>Yordam</b>\n\nSavol, taklif yoki muammo bo'lsa, adminga shu yerning o'zidan yozing — "
            "javob ham shu botda keladi.\n\n<b>Tez javoblar:</b>\n"
            "• Video ochilmasa: boshqa sifatni tanlang yoki qayta bosing.\n"
            "• Kino topilmasa: nomini yozing va 🔔 tugmasini bosing — yuklanishi bilan xabar beramiz.\n"
            "• Premium haqida: 💎 bo'limida."
        ),
        "help_btn": "🆘 Yordam",
        "write_btn": "✍️ Adminga yozish",
        "my_btn": "📂 Murojaatlarim",
        "prompt": (
            "✉️ <b>Adminga xabar</b>\n\nXabaringizni yozing. Matn, rasm yoki video yuborishingiz mumkin.\n"
            "Muammo bo'lsa, qaysi kino va qaysi sifat ekanini yozing."
        ),
        "sent": "✅ <b>Xabaringiz adminga yuborildi.</b>\nJavob shu botning o'zida keladi.",
        "more_btn": "✉️ Yana yozish",
        "admin_header": "💬 <b>Admin javobi</b>",
        "reply_btn": "✉️ Javob yozish",
        "resolved_btn": "✅ Muammo hal bo'ldi",
        "closed": "✅ Murojaat yopildi. Rahmat!",
        "my_title": "📂 <b>Murojaatlarim</b>",
        "st_open": "⏳ Javob kutilmoqda",
        "st_answered": "💬 Admin javob berdi",
        "st_closed": "✅ Yopilgan",
        "you": "Siz",
        "admin": "Admin",
        "cooldown": "⏳ Juda tez-tez yozyapsiz. Birozdan so'ng urinib ko'ring.",
        "unsupported": "⚠️ Matn, rasm, video yoki hujjat yuboring.",
        "cancel": "❌ Bekor qilish",
    },
    "en": {
        "help_text": (
            "🆘 <b>Help</b>\n\nHave a question, idea or problem? Write to the admin right here — "
            "the reply comes in this bot.\n\n<b>Quick answers:</b>\n"
            "• Video won't open: pick another quality or tap again.\n"
            "• Title not found: type it and tap 🔔 — we'll notify you when it's added.\n"
            "• About Premium: see the 💎 section."
        ),
        "help_btn": "🆘 Help",
        "write_btn": "✍️ Write to admin",
        "my_btn": "📂 My requests",
        "prompt": (
            "✉️ <b>Message to admin</b>\n\nWrite your message. You can send text, a photo or a video.\n"
            "If something is broken, mention the title and quality."
        ),
        "sent": "✅ <b>Your message was sent to the admin.</b>\nThe reply will arrive in this bot.",
        "more_btn": "✉️ Write more",
        "admin_header": "💬 <b>Admin reply</b>",
        "reply_btn": "✉️ Reply",
        "resolved_btn": "✅ Problem solved",
        "closed": "✅ Request closed. Thanks!",
        "my_title": "📂 <b>My requests</b>",
        "st_open": "⏳ Waiting for a reply",
        "st_answered": "💬 Admin replied",
        "st_closed": "✅ Closed",
        "you": "You",
        "admin": "Admin",
        "cooldown": "⏳ You're writing too fast. Please try again in a bit.",
        "unsupported": "⚠️ Please send text, a photo, a video or a document.",
        "cancel": "❌ Cancel",
    },
    "ru": {
        "help_text": (
            "🆘 <b>Помощь</b>\n\nЕсть вопрос, идея или проблема? Напишите админу прямо здесь — "
            "ответ придёт в этом боте.\n\n<b>Быстрые ответы:</b>\n"
            "• Видео не открывается: выберите другое качество или нажмите снова.\n"
            "• Не нашли фильм: напишите название и нажмите 🔔 — сообщим, когда добавим.\n"
            "• О Premium: раздел 💎."
        ),
        "help_btn": "🆘 Помощь",
        "write_btn": "✍️ Написать админу",
        "my_btn": "📂 Мои обращения",
        "prompt": (
            "✉️ <b>Сообщение админу</b>\n\nНапишите сообщение. Можно отправить текст, фото или видео.\n"
            "Если что-то не работает, укажите фильм и качество."
        ),
        "sent": "✅ <b>Ваше сообщение отправлено админу.</b>\nОтвет придёт в этом боте.",
        "more_btn": "✉️ Написать ещё",
        "admin_header": "💬 <b>Ответ админа</b>",
        "reply_btn": "✉️ Ответить",
        "resolved_btn": "✅ Проблема решена",
        "closed": "✅ Обращение закрыто. Спасибо!",
        "my_title": "📂 <b>Мои обращения</b>",
        "st_open": "⏳ Ждёт ответа",
        "st_answered": "💬 Админ ответил",
        "st_closed": "✅ Закрыто",
        "you": "Вы",
        "admin": "Админ",
        "cooldown": "⏳ Вы пишете слишком часто. Попробуйте чуть позже.",
        "unsupported": "⚠️ Отправьте текст, фото, видео или документ.",
        "cancel": "❌ Отмена",
    },
}


def tx(lang: str, key: str) -> str:
    return T.get(lang, T["uz"]).get(key) or T["uz"][key]


_open = {"n": 0}
_stamps: dict[int, deque] = defaultdict(deque)
CAPTIONABLE = ("photo", "video", "document", "audio", "voice", "animation")


def open_count() -> int:
    return _open["n"]


async def refresh_count():
    _open["n"] = await db.pool.fetchval("SELECT count(*) FROM tickets WHERE status = 'open'") or 0


async def init():
    await db.pool.execute(
        """
        CREATE TABLE IF NOT EXISTS tickets (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS ticket_msgs (
            id SERIAL PRIMARY KEY,
            ticket_id INT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            from_admin BOOLEAN NOT NULL,
            body TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS tickets_status_idx ON tickets(status, updated_at);
        """
    )
    await refresh_count()


# ---------------- yordamchilar ----------------
def describe(m: Message) -> str:
    if m.text:
        return m.text.strip()
    kind = (
        "📷 Rasm" if m.photo else "🎞 Video" if m.video else "📎 Hujjat" if m.document
        else "🎤 Ovozli xabar" if m.voice else "🎧 Audio" if m.audio
        else "🎭 Stiker" if m.sticker else "🎬 Animatsiya" if m.animation else "📨 Xabar"
    )
    cap = (m.caption or "").strip()
    return f"{kind}: {cap}" if cap else kind


async def deliver(bot: Bot, chat_id: int, src: Message, header: str, kb):
    """Xabarni (matn yoki media) sarlavha bilan yuboradi."""
    if src.text:
        return await bot.send_message(chat_id, f"{header}\n\n{escape(src.text)}"[:4096], reply_markup=kb, parse_mode="HTML")
    if any(getattr(src, k, None) for k in CAPTIONABLE):
        cap = escape((src.caption or "")[:800])
        return await bot.copy_message(
            chat_id, src.chat.id, src.message_id,
            caption=f"{header}\n\n{cap}".strip(), parse_mode="HTML", reply_markup=kb,
        )
    head = await bot.send_message(chat_id, header, reply_markup=kb, parse_mode="HTML")
    await bot.copy_message(chat_id, src.chat.id, src.message_id)
    return head


def too_fast(uid: int) -> bool:
    now = time.time()
    dq = _stamps[uid]
    while dq and now - dq[0] > 600:
        dq.popleft()
    if len(dq) >= 6:
        return True
    dq.append(now)
    return False


def ago(dt) -> str:
    s = int((datetime.now(timezone.utc) - dt).total_seconds())
    if s < 3600:
        return f"{max(1, s // 60)} daq"
    if s < 86400:
        return f"{s // 3600} soat"
    return f"{s // 86400} kun"


async def open_ticket(uid: int) -> int:
    row = await db.pool.fetchrow(
        "SELECT id FROM tickets WHERE user_id=$1 AND status <> 'closed' ORDER BY id DESC LIMIT 1", uid
    )
    if row:
        return row["id"]
    return await db.pool.fetchval("INSERT INTO tickets (user_id) VALUES ($1) RETURNING id", uid)


async def add_msg(tid: int, from_admin: bool, body: str):
    await db.pool.execute(
        "INSERT INTO ticket_msgs (ticket_id, from_admin, body) VALUES ($1, $2, $3)", tid, from_admin, body[:2000]
    )
    await db.pool.execute(
        "UPDATE tickets SET status=$2, updated_at=now() WHERE id=$1", tid, "answered" if from_admin else "open"
    )


async def show_help(bot: Bot, chat_id: int, uid: int, lang: str, source=None, force_new: bool = False):
    has = await db.pool.fetchval("SELECT 1 FROM tickets WHERE user_id=$1 LIMIT 1", uid)
    rows = [[btn(tx(lang, "write_btn"), "sp:w")]]
    if has:
        rows.append([btn(tx(lang, "my_btn"), "sp:my")])
    rows.append(utils.nav_row(lang, "nav:more"))
    await ui.show(
        bot, chat_id, uid, tx(lang, "help_text"), kb_of(rows),
        photo=utils.banner("generic"), source=source, force_new=force_new,
    )


# ---------------- foydalanuvchi tomoni ----------------
@user_router.message(Command("help"))
async def help_cmd(m: Message, state: FSMContext):
    await state.clear()
    await ui.delete_message(m)
    lang = await db.get_lang(m.from_user.id) or "uz"
    await show_help(m.bot, m.chat.id, m.from_user.id, lang)


@user_router.callback_query(F.data == "sp:h")
async def help_cb(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    lang = await db.get_lang(c.from_user.id) or "uz"
    await show_help(c.bot, c.message.chat.id, c.from_user.id, lang, source=c.message)


@user_router.callback_query(F.data == "sp:w")
async def write_start(c: CallbackQuery, state: FSMContext):
    uid = c.from_user.id
    lang = await db.get_lang(uid) or "uz"
    await state.set_state(Support.wait)
    await c.answer()
    # Har doim eng pastga yangi xabar sifatida (admin javobi ostida bosilgan bo'lsa ham)
    await ui.show(
        c.bot, c.message.chat.id, uid, tx(lang, "prompt"),
        kb_of([[btn(tx(lang, "cancel"), "sp:h")]]), force_new=True,
    )


async def receive(m: Message, state: FSMContext):
    uid = m.from_user.id
    lang = await db.get_lang(uid) or "uz"
    if uid not in config.ADMIN_IDS and too_fast(uid):
        await ui.delete_message(m)
        await ui.flash(m.bot, m.chat.id, tx(lang, "cooldown"))
        return
    tid = await open_ticket(uid)
    await add_msg(tid, False, describe(m))
    await state.clear()
    uname = f" @{escape(m.from_user.username)}" if m.from_user.username else ""
    header = f"🆘 <b>Murojaat #{tid}</b>\n👤 {escape(m.from_user.full_name)}{uname} (<code>{uid}</code>)"
    kb = kb_of([[btn("↩️ Javob berish", f"sp:r:{tid}"), btn("📂 Suhbat", f"sp:v:{tid}")]])
    for admin_id in config.ADMIN_IDS:
        try:
            await deliver(m.bot, admin_id, m, header, kb)
        except Exception as e:
            logging.warning("Murojaatni adminga yuborib bo'lmadi (%s): %s", admin_id, e)
    await refresh_count()
    await ui.delete_message(m)
    await ui.show(
        m.bot, m.chat.id, uid, tx(lang, "sent"),
        kb_of([[btn(tx(lang, "more_btn"), "sp:w")], utils.nav_row(lang)]),
    )


@user_router.message(Support.wait, F.text & ~F.text.startswith("/"))
async def support_text(m: Message, state: FSMContext):
    await receive(m, state)


@user_router.message(Support.wait, F.photo | F.video | F.document | F.voice | F.audio | F.sticker | F.animation)
async def support_media(m: Message, state: FSMContext):
    await receive(m, state)


async def my_screen(uid: int, lang: str):
    t = await db.pool.fetchrow("SELECT id, status FROM tickets WHERE user_id=$1 ORDER BY id DESC LIMIT 1", uid)
    if not t:
        return None
    msgs = await db.pool.fetch(
        "SELECT from_admin, body FROM ticket_msgs WHERE ticket_id=$1 ORDER BY id DESC LIMIT 6", t["id"]
    )
    lines = [
        f"{'🛠' if r['from_admin'] else '👤'} <b>{tx(lang, 'admin' if r['from_admin'] else 'you')}:</b> "
        f"{escape(r['body'][:300])}"
        for r in reversed(msgs)
    ]
    status = tx(lang, {"open": "st_open", "answered": "st_answered", "closed": "st_closed"}[t["status"]])
    text = f"{tx(lang, 'my_title')}\n{status}\n\n" + "\n\n".join(lines)
    rows = [[btn(tx(lang, "write_btn"), "sp:w")]]
    if t["status"] != "closed":
        rows.append([btn(tx(lang, "resolved_btn"), f"sp:c:{t['id']}")])
    rows.append(utils.nav_row(lang, "sp:h"))
    return text, kb_of(rows)


@user_router.callback_query(F.data == "sp:my")
async def my_cb(c: CallbackQuery):
    await c.answer()
    uid = c.from_user.id
    lang = await db.get_lang(uid) or "uz"
    view = await my_screen(uid, lang)
    if not view:
        await show_help(c.bot, c.message.chat.id, uid, lang, source=c.message)
        return
    await ui.show(c.bot, c.message.chat.id, uid, view[0], view[1], source=c.message)


@user_router.callback_query(F.data.regexp(r"^sp:c:\d+$"))
async def close_by_user(c: CallbackQuery):
    tid = int(c.data.split(":")[2])
    uid = c.from_user.id
    lang = await db.get_lang(uid) or "uz"
    row = await db.pool.fetchrow(
        "UPDATE tickets SET status='closed', updated_at=now() WHERE id=$1 AND user_id=$2 RETURNING id", tid, uid
    )
    await refresh_count()
    await c.answer(tx(lang, "closed") if row else "—", show_alert=bool(row))
    if ui.screen_id(uid) == c.message.message_id:
        await show_help(c.bot, c.message.chat.id, uid, lang, source=c.message)
    else:
        try:
            await c.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass


@user_router.message(StateFilter(Support))
async def support_other(m: Message):
    lang = await db.get_lang(m.from_user.id) or "uz"
    await ui.delete_message(m)
    await ui.flash(m.bot, m.chat.id, tx(lang, "unsupported"))


# ---------------- admin tomoni ----------------
async def tickets_screen():
    rows = await db.pool.fetch(
        """
        SELECT t.id, t.user_id, t.status, t.updated_at, u.first_name, u.username,
            (SELECT body FROM ticket_msgs m WHERE m.ticket_id = t.id ORDER BY m.id DESC LIMIT 1) AS last
        FROM tickets t LEFT JOIN users u ON u.user_id = t.user_id
        WHERE t.status <> 'closed'
        ORDER BY (t.status = 'open') DESC, t.updated_at DESC LIMIT 10
        """
    )
    await refresh_count()
    if not rows:
        return "🆘 <b>Murojaatlar</b>\n\nHozircha ochiq murojaat yo'q.", kb_of([[btn("◀️ Orqaga", "a:home")]])
    lines = []
    for i, r in enumerate(rows, 1):
        icon = "🔴" if r["status"] == "open" else "🟡"
        name = escape(r["first_name"] or str(r["user_id"]))
        snippet = escape((r["last"] or "")[:40])
        lines.append(f"{i}. {icon} {name} • {ago(r['updated_at'])} — {snippet}")
    text = "🆘 <b>Murojaatlar</b>\n🔴 javob kutmoqda • 🟡 javob berilgan\n\n" + "\n".join(lines)
    kb = grid([btn(str(i), f"sp:v:{r['id']}") for i, r in enumerate(rows, 1)], 5)
    kb.append([btn("◀️ Orqaga", "a:home")])
    return text, kb_of(kb)


async def ticket_view(tid: int):
    t = await db.pool.fetchrow(
        "SELECT t.id, t.user_id, t.status, u.first_name, u.username FROM tickets t "
        "LEFT JOIN users u ON u.user_id = t.user_id WHERE t.id=$1",
        tid,
    )
    if not t:
        return None
    msgs = await db.pool.fetch(
        "SELECT from_admin, body FROM ticket_msgs WHERE ticket_id=$1 ORDER BY id DESC LIMIT 8", tid
    )
    lines = [f"{'🛠' if r['from_admin'] else '👤'} {escape(r['body'][:300])}" for r in reversed(msgs)]
    status = {"open": "🔴 javob kutmoqda", "answered": "🟡 javob berilgan", "closed": "✅ yopilgan"}[t["status"]]
    uname = f" @{escape(t['username'])}" if t["username"] else ""
    text = (
        f"🆘 <b>Murojaat #{tid}</b> • {status}\n"
        f"👤 {escape(t['first_name'] or '—')}{uname} (<code>{t['user_id']}</code>)\n\n" + "\n\n".join(lines)
    )
    rows = [
        [btn("↩️ Javob berish", f"sp:r:{tid}")],
        [btn("✅ Yopish", f"sp:x:{tid}"), btn("👤 Foydalanuvchi", f"sp:u:{t['user_id']}")],
        [btn("◀️ Murojaatlar", "sp:t")],
    ]
    return text, kb_of(rows)


async def admin_show(c: CallbackQuery, text: str, kb):
    # Bildirishnoma (foydalanuvchi xabari nusxasi) tahrirlanmasligi uchun doim yangi xabar sifatida
    await ui.show(c.bot, c.message.chat.id, c.from_user.id, text, kb, force_new=True)


@admin_router.callback_query(F.data == "sp:t")
async def tickets_list(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    text, kb = await tickets_screen()
    await admin_show(c, text, kb)


@admin_router.callback_query(F.data.regexp(r"^sp:v:\d+$"))
async def ticket_open(c: CallbackQuery, state: FSMContext):
    await state.clear()
    view = await ticket_view(int(c.data.split(":")[2]))
    if not view:
        await c.answer("Topilmadi", show_alert=True)
        return
    await c.answer()
    await admin_show(c, view[0], view[1])


@admin_router.callback_query(F.data.regexp(r"^sp:r:\d+$"))
async def reply_start(c: CallbackQuery, state: FSMContext):
    tid = int(c.data.split(":")[2])
    await state.set_state(SupportAdmin.reply)
    await state.update_data(tid=tid)
    await c.answer()
    await admin_show(
        c, f"↩️ <b>Murojaat #{tid}</b> uchun javobingizni yozing (matn, rasm yoki video).",
        kb_of([[btn("❌ Bekor qilish", f"sp:v:{tid}")]]),
    )


async def admin_reply(m: Message, state: FSMContext):
    tid = (await state.get_data())["tid"]
    t = await db.pool.fetchrow("SELECT user_id FROM tickets WHERE id=$1", tid)
    await state.clear()
    if not t:
        await ui.delete_message(m)
        return
    uid = t["user_id"]
    lang = await db.get_lang(uid) or "uz"
    kb = kb_of([[btn(tx(lang, "reply_btn"), "sp:w")], [btn(tx(lang, "resolved_btn"), f"sp:c:{tid}")]])
    try:
        await deliver(m.bot, uid, m, tx(lang, "admin_header"), kb)
        await add_msg(tid, True, describe(m))
        note = "✅ Javob yuborildi"
    except TelegramForbiddenError:
        db.bg(db.pool.execute("UPDATE users SET blocked = TRUE WHERE user_id=$1", uid))
        note = "⚠️ Foydalanuvchi botni bloklagan"
    except Exception as e:
        note = f"⚠️ Yuborib bo'lmadi: {e}"
    await ui.delete_message(m)
    await refresh_count()
    view = await ticket_view(tid)
    if view:
        await ui.show(m.bot, m.chat.id, m.from_user.id, f"{escape(note)}\n\n{view[0]}", view[1])


@admin_router.message(SupportAdmin.reply, F.text & ~F.text.startswith("/"))
async def admin_reply_text(m: Message, state: FSMContext):
    await admin_reply(m, state)


@admin_router.message(SupportAdmin.reply, F.photo | F.video | F.document | F.voice | F.audio | F.animation)
async def admin_reply_media(m: Message, state: FSMContext):
    await admin_reply(m, state)


@admin_router.callback_query(F.data.regexp(r"^sp:x:\d+$"))
async def ticket_close(c: CallbackQuery):
    tid = int(c.data.split(":")[2])
    await db.pool.execute("UPDATE tickets SET status='closed', updated_at=now() WHERE id=$1", tid)
    await c.answer("✅ Yopildi")
    text, kb = await tickets_screen()
    await admin_show(c, text, kb)


@admin_router.callback_query(F.data.regexp(r"^sp:u:\d+$"))
async def ticket_user(c: CallbackQuery):
    import admin_tools
    import db_extra

    row = await db_extra.user_row(int(c.data.split(":")[2]))
    if not row:
        await c.answer("Topilmadi", show_alert=True)
        return
    await c.answer()
    text, kb = admin_tools.user_view(row)
    await admin_show(c, text, kb)


@admin_router.message(StateFilter(SupportAdmin))
async def admin_other(m: Message):
    await ui.delete_message(m)
    await ui.flash(m.bot, m.chat.id, "⚠️ Matn, rasm yoki video yuboring.")
