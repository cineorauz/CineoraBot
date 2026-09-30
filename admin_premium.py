from html import escape

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import config
import database as db
import ui
import utils
from locales import t
from utils import btn, kb_of

router = Router()
router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

S = ui.show_for
BACK = kb_of([[btn("❌ Bekor qilish", "ap:home")]])
BACK_PANEL = kb_of([[btn("◀️ Premium paneli", "ap:home")]])


class AP(StatesGroup):
    grant = State()
    revoke = State()
    promo = State()
    plans = State()
    paytext = State()


async def panel():
    s = await db.premium_stats()
    text = (
        "💎 <b>Premium boshqaruvi</b>\n\n"
        f"✅ Faol obunachilar: <b>{s['active']}</b>\n"
        f"💰 Daromad: <b>{s['stars']}</b> ⭐ • <b>{utils.fmt_num(s['uzs'])}</b> so'm\n"
        f"🧾 Kutilayotgan cheklar: <b>{s['pending']}</b>"
    )
    kb = kb_of(
        [
            [btn("🎁 Premium berish", "ap:grant"), btn("🚫 Bekor qilish", "ap:revoke")],
            [btn("🎟 Promo-kodlar", "ap:promo"), btn("💳 Tariflar", "ap:plans")],
            [btn("🧾 To'lov matni", "ap:paytext")],
            [btn("◀️ Admin panel", "a:home")],
        ]
    )
    return text, kb


@router.callback_query(F.data == "ap:home")
async def home(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    text, kb = await panel()
    await S(c, text, kb)


# ---------- berish / bekor qilish ----------
@router.callback_query(F.data == "ap:grant")
async def grant_ask(c: CallbackQuery, state: FSMContext):
    await state.set_state(AP.grant)
    await c.answer()
    await S(c, "🎁 Foydalanuvchi ID va kunlar sonini yuboring.\nMasalan: <code>123456789 30</code>", BACK)


@router.message(AP.grant, F.text & ~F.text.startswith("/"))
async def grant_do(m: Message, state: FSMContext):
    await ui.delete_message(m)
    try:
        uid, days = (int(x) for x in m.text.split())
        assert days > 0
    except (ValueError, AssertionError):
        await ui.flash(m.bot, m.chat.id, "Format noto'g'ri. Masalan: <code>123456789 30</code>")
        return
    await state.clear()
    until = await db.grant_premium(uid, days, method="admin")
    lang = await db.get_lang(uid) or "uz"
    note = ""
    try:
        await m.bot.send_message(uid, t(lang, "promo_ok").format(days=days, date=utils.fmt_date(until)))
    except Exception:
        note = "\n⚠️ Foydalanuvchiga xabar yuborib bo'lmadi (bot bilan boshlamagan bo'lishi mumkin)."
    await S(m, f"✅ <code>{uid}</code> ga {days} kun Premium berildi (gacha: {utils.fmt_date(until)}).{note}", BACK_PANEL)


@router.callback_query(F.data == "ap:revoke")
async def revoke_ask(c: CallbackQuery, state: FSMContext):
    await state.set_state(AP.revoke)
    await c.answer()
    await S(c, "🚫 Premium bekor qilinadigan foydalanuvchi ID sini yuboring.", BACK)


@router.message(AP.revoke, F.text & ~F.text.startswith("/"))
async def revoke_do(m: Message, state: FSMContext):
    await ui.delete_message(m)
    if not m.text.strip().isdigit():
        await ui.flash(m.bot, m.chat.id, "ID raqam bo'lishi kerak.")
        return
    await state.clear()
    await db.revoke_premium(int(m.text.strip()))
    await S(m, "✅ Premium bekor qilindi.", BACK_PANEL)


# ---------- promo-kodlar ----------
@router.callback_query(F.data == "ap:promo")
async def promo_list(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    rows = await db.list_promos()
    lines = ["🎟 <b>Promo-kodlar</b>\n"]
    for r in rows:
        lines.append(f"<code>{r['code']}</code> — {r['days']} kun • {r['used']}/{r['max_uses']}")
    if not rows:
        lines.append("Hozircha yo'q.")
    kb = kb_of([[btn("➕ Yangi promo-kod", "ap:promo_new")], [btn("◀️ Premium paneli", "ap:home")]])
    await S(c, "\n".join(lines), kb)


@router.callback_query(F.data == "ap:promo_new")
async def promo_new(c: CallbackQuery, state: FSMContext):
    await state.set_state(AP.promo)
    await c.answer()
    await S(
        c,
        "🎟 Kunlar va necha marta ishlatilishini yuboring.\nMasalan: <code>30 50</code> "
        "(30 kunlik, 50 kishi ishlata oladi)",
        BACK,
    )


@router.message(AP.promo, F.text & ~F.text.startswith("/"))
async def promo_do(m: Message, state: FSMContext):
    await ui.delete_message(m)
    try:
        days, uses = (int(x) for x in m.text.split())
        assert days > 0 and uses > 0
    except (ValueError, AssertionError):
        await ui.flash(m.bot, m.chat.id, "Format noto'g'ri. Masalan: <code>30 50</code>")
        return
    await state.clear()
    code = await db.create_promo(days, uses)
    await S(
        m,
        f"✅ Promo-kod yaratildi:\n\n<code>{code}</code>\n\n💎 {days} kun • {uses} marta",
        kb_of([[btn("🎟 Promo-kodlar", "ap:promo")], [btn("◀️ Premium paneli", "ap:home")]]),
    )


# ---------- tariflar ----------
@router.callback_query(F.data == "ap:plans")
async def plans_view(c: CallbackQuery, state: FSMContext):
    lines = ["💳 <b>Joriy tariflar</b>\n"]
    for p in db.get_plans():
        lines.append(f"• {p['days']} kun — {utils.fmt_num(p['uzs'])} so'm • ⭐{p['stars']}")
    lines.append(
        "\nYangilash uchun shu formatda yuboring (kun:so'm:stars, vergul bilan):\n"
        "<code>30:29000:150, 90:79000:400, 365:249000:1400</code>"
    )
    await state.set_state(AP.plans)
    await c.answer()
    await S(c, "\n".join(lines), BACK)


@router.message(AP.plans, F.text & ~F.text.startswith("/"))
async def plans_do(m: Message, state: FSMContext):
    await ui.delete_message(m)
    try:
        db.parse_plans(m.text)
    except ValueError:
        await ui.flash(m.bot, m.chat.id, "Format noto'g'ri. Masalan: <code>30:29000:150, 90:79000:400</code>")
        return
    await state.clear()
    await db.set_setting("plans", m.text.strip())
    await S(m, "✅ Tariflar yangilandi.", BACK_PANEL)


# ---------- to'lov matni ----------
@router.callback_query(F.data == "ap:paytext")
async def paytext_ask(c: CallbackQuery, state: FSMContext):
    current = db.get_setting("manual_pay_text") or "(o'rnatilmagan)"
    await state.set_state(AP.paytext)
    await c.answer()
    await S(
        c,
        f"🧾 <b>Karta orqali to'lov matni</b>\n\nHozirgi:\n{escape(current)}\n\n"
        "Yangi matnni yuboring (karta raqami, egasi, izoh). O'chirish uchun <code>-</code> yuboring.",
        BACK,
    )


@router.message(AP.paytext, F.text & ~F.text.startswith("/"))
async def paytext_do(m: Message, state: FSMContext):
    await ui.delete_message(m)
    await state.clear()
    value = "" if m.text.strip() == "-" else m.text.strip()
    await db.set_setting("manual_pay_text", value)
    await S(m, "✅ Saqlandi." if value else "✅ Karta orqali to'lov o'chirildi.", BACK_PANEL)


@router.message(StateFilter(AP))
async def wrong(m: Message):
    await ui.delete_message(m)
    await ui.flash(m.bot, m.chat.id, "⚠️ Iltimos, so'ralgan formatda yuboring.")
