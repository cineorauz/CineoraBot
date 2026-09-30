import asyncio
import logging
from datetime import datetime, timezone
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

import config
import database as db
import utils
from locales import LANGS, menu_texts, t
from utils import btn, grid, kb_of

router = Router()


class Receipt(StatesGroup):
    wait = State()


class Promo(StatesGroup):
    wait = State()


async def lang_of(user_id: int) -> str:
    return await db.get_lang(user_id) or "uz"


def plan_price(plan: dict, lang: str) -> str:
    if config.PAYMENT_PROVIDER_TOKEN and plan["uzs"]:
        return f"{utils.fmt_num(plan['uzs'])} {t(lang, 'som')}"
    if plan["stars"]:
        return f"⭐{plan['stars']}"
    return "🧾"


async def premium_view(user_id: int, lang: str):
    until = await db.premium_until(user_id)
    now = datetime.now(timezone.utc)
    text = t(lang, "prem_title") + t(lang, "prem_benefits")
    if until and until > now:
        days = (until - now).days + 1
        text += t(lang, "prem_active").format(date=utils.fmt_date(until), days=days)
    else:
        text += t(lang, "prem_none")
    rows = [
        [btn(f"💎 {p['days']} {t(lang, 'days_word')} • {plan_price(p, lang)}", f"pm:{p['days']}")]
        for p in db.get_plans()
    ]
    rows.append([btn(t(lang, "promo_btn"), "promo:ask")])
    return text, kb_of(rows)


async def notify_admins(bot: Bot, text: str):
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception:
            pass


# ---------------- Premium ekrani ----------------
@router.message(F.text.in_(menu_texts("m_prem")))
@router.message(Command("premium"))
async def prem_menu(m: Message):
    lang = await lang_of(m.from_user.id)
    text, kb = await premium_view(m.from_user.id, lang)
    await m.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "prem:open")
async def prem_open(c: CallbackQuery):
    await c.answer()
    lang = await lang_of(c.from_user.id)
    text, kb = await premium_view(c.from_user.id, lang)
    await c.message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "prem:back")
async def prem_back(c: CallbackQuery):
    await c.answer()
    lang = await lang_of(c.from_user.id)
    text, kb = await premium_view(c.from_user.id, lang)
    try:
        await c.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await c.message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.regexp(r"^pm:\d+$"))
async def pick_method(c: CallbackQuery):
    await c.answer()
    days = int(c.data.split(":")[1])
    lang = await lang_of(c.from_user.id)
    plan = next((p for p in db.get_plans() if p["days"] == days), None)
    if not plan:
        return
    rows = []
    if plan["stars"]:
        rows.append([btn(t(lang, "pay_stars").format(n=plan["stars"]), f"pay:xtr:{days}")])
    if config.PAYMENT_PROVIDER_TOKEN and plan["uzs"]:
        rows.append([btn(t(lang, "pay_uzs").format(n=utils.fmt_num(plan["uzs"])), f"pay:uzs:{days}")])
    if db.get_setting("manual_pay_text"):
        rows.append([btn(t(lang, "pay_manual"), f"pay:man:{days}")])
    rows.append([btn(t(lang, "back"), "prem:back")])
    text = t(lang, "prem_pick_method").format(days=days) if len(rows) > 1 else t(lang, "no_methods")
    try:
        await c.message.edit_text(text, reply_markup=kb_of(rows), parse_mode="HTML")
    except Exception:
        await c.message.answer(text, reply_markup=kb_of(rows), parse_mode="HTML")


# ---------------- Stars va Click/Payme ----------------
@router.callback_query(F.data.regexp(r"^pay:(xtr|uzs):\d+$"))
async def pay_invoice(c: CallbackQuery):
    _, method, days = c.data.split(":")
    days = int(days)
    lang = await lang_of(c.from_user.id)
    plan = next((p for p in db.get_plans() if p["days"] == days), None)
    if not plan:
        await c.answer()
        return
    title = t(lang, "inv_title").format(days=days)
    desc = t(lang, "inv_desc")
    await c.answer()
    if method == "xtr":
        await c.message.answer_invoice(
            title=title, description=desc, payload=f"prem:{days}", currency="XTR",
            prices=[LabeledPrice(label=title, amount=plan["stars"])],
        )
    else:
        await c.message.answer_invoice(
            title=title, description=desc, payload=f"prem:{days}", currency="UZS",
            provider_token=config.PAYMENT_PROVIDER_TOKEN,
            prices=[LabeledPrice(label=title, amount=plan["uzs"] * 100)],
        )


@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    await q.answer(ok=True)


@router.message(F.successful_payment)
async def paid(m: Message):
    sp = m.successful_payment
    lang = await lang_of(m.from_user.id)
    try:
        days = int(sp.invoice_payload.split(":")[1])
    except (IndexError, ValueError):
        days = 30
    is_stars = sp.currency == "XTR"
    amount = sp.total_amount if is_stars else sp.total_amount // 100
    until = await db.grant_premium(
        m.from_user.id, days, method="stars" if is_stars else "uzs",
        amount=amount, currency=sp.currency, charge_id=sp.telegram_payment_charge_id,
    )
    await m.answer(t(lang, "paid_ok").format(date=utils.fmt_date(until)), parse_mode="HTML")
    await notify_admins(
        m.bot,
        f"💰 <b>Yangi to'lov</b>\n👤 {escape(m.from_user.full_name)} (<code>{m.from_user.id}</code>)\n"
        f"💎 {days} kun • {amount} {sp.currency}",
    )


# ---------------- Karta o'tkazma (chek) ----------------
@router.callback_query(F.data.regexp(r"^pay:man:\d+$"))
async def pay_manual(c: CallbackQuery):
    days = int(c.data.split(":")[2])
    lang = await lang_of(c.from_user.id)
    text = db.get_setting("manual_pay_text")
    if not text:
        await c.answer(t(lang, "no_methods"), show_alert=True)
        return
    await c.answer()
    rows = [[btn(t(lang, "send_receipt"), f"rcpt:{days}")], [btn(t(lang, "back"), f"pm:{days}")]]
    await c.message.edit_text(
        t(lang, "manual_head").format(text=escape(text)), reply_markup=kb_of(rows), parse_mode="HTML"
    )


@router.callback_query(F.data.regexp(r"^rcpt:\d+$"))
async def receipt_start(c: CallbackQuery, state: FSMContext):
    await c.answer()
    lang = await lang_of(c.from_user.id)
    await state.clear()
    await state.set_state(Receipt.wait)
    await state.update_data(days=int(c.data.split(":")[1]))
    await c.message.answer(t(lang, "receipt_ask"))


@router.message(Receipt.wait, F.photo | F.document)
async def receipt_in(m: Message, state: FSMContext):
    lang = await lang_of(m.from_user.id)
    days = (await state.get_data()).get("days", 30)
    await state.clear()
    file_id = m.photo[-1].file_id if m.photo else m.document.file_id
    rid = await db.add_receipt(m.from_user.id, file_id, days)
    plans = db.get_plans()
    rows = grid([btn(f"✅ {p['days']} kun", f"rc:ok:{rid}:{p['days']}") for p in plans], 3)
    rows.append([btn("❌ Rad etish", f"rc:no:{rid}")])
    caption = (
        f"🧾 <b>Yangi chek</b> #{rid}\n"
        f"👤 {escape(m.from_user.full_name)} (<code>{m.from_user.id}</code>)\n"
        f"💎 Tanlagan tarif: {days} kun"
    )
    for admin_id in config.ADMIN_IDS:
        try:
            await m.copy_to(admin_id, caption=caption, reply_markup=kb_of(rows), parse_mode="HTML")
        except Exception as e:
            logging.warning("Chekni adminga yuborib bo'lmadi: %s", e)
    await m.answer(t(lang, "receipt_sent"))


@router.callback_query(F.data.regexp(r"^rc:ok:\d+:\d+$"))
async def receipt_ok(c: CallbackQuery):
    if c.from_user.id not in config.ADMIN_IDS:
        await c.answer("Ruxsat yo'q", show_alert=True)
        return
    _, _, rid, days = c.data.split(":")
    row = await db.resolve_receipt(int(rid), "approved")
    if not row:
        await c.answer("Bu chek allaqachon ko'rib chiqilgan", show_alert=True)
        return
    until = await db.grant_premium(row["user_id"], int(days), method="receipt")
    lang = await lang_of(row["user_id"])
    try:
        await c.bot.send_message(
            row["user_id"],
            t(lang, "receipt_ok").format(days=days, date=utils.fmt_date(until)),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await c.answer("✅ Tasdiqlandi")
    try:
        await c.message.edit_caption(
            caption=(c.message.caption or "") + f"\n\n✅ Tasdiqlandi: {days} kun", reply_markup=None
        )
    except Exception:
        pass


@router.callback_query(F.data.regexp(r"^rc:no:\d+$"))
async def receipt_no(c: CallbackQuery):
    if c.from_user.id not in config.ADMIN_IDS:
        await c.answer("Ruxsat yo'q", show_alert=True)
        return
    row = await db.resolve_receipt(int(c.data.split(":")[2]), "rejected")
    if not row:
        await c.answer("Bu chek allaqachon ko'rib chiqilgan", show_alert=True)
        return
    lang = await lang_of(row["user_id"])
    try:
        await c.bot.send_message(row["user_id"], t(lang, "receipt_no"))
    except Exception:
        pass
    await c.answer("❌ Rad etildi")
    try:
        await c.message.edit_caption(caption=(c.message.caption or "") + "\n\n❌ Rad etildi", reply_markup=None)
    except Exception:
        pass


# ---------------- Promo-kod ----------------
@router.callback_query(F.data == "promo:ask")
async def promo_ask(c: CallbackQuery, state: FSMContext):
    await c.answer()
    lang = await lang_of(c.from_user.id)
    await state.clear()
    await state.set_state(Promo.wait)
    await c.message.answer(t(lang, "promo_ask"))


@router.message(Promo.wait, F.text & ~F.text.startswith("/"))
async def promo_in(m: Message, state: FSMContext):
    lang = await lang_of(m.from_user.id)
    days, err = await db.redeem_promo(m.text, m.from_user.id)
    if err:
        await m.answer(t(lang, {"bad": "promo_bad", "used_up": "promo_used", "already": "promo_already"}[err]))
        return
    await state.clear()
    until = await db.grant_premium(m.from_user.id, days, method="promo")
    await m.answer(t(lang, "promo_ok").format(days=days, date=utils.fmt_date(until)))


@router.message(Command("cancel"))
async def cancel_user(m: Message, state: FSMContext):
    await state.clear()
    lang = await lang_of(m.from_user.id)
    await m.answer(t(lang, "cancelled"))


@router.message(Receipt.wait)
async def receipt_wrong(m: Message):
    lang = await lang_of(m.from_user.id)
    await m.answer(t(lang, "receipt_ask"))


# ---------------- Profil ----------------
@router.message(F.text.in_(menu_texts("m_profile")))
async def profile(m: Message):
    lang = await lang_of(m.from_user.id)
    u = await db.get_user(m.from_user.id)
    favs = await db.fav_count(m.from_user.id)
    until = u["premium_until"]
    if until and until > datetime.now(timezone.utc):
        prem = t(lang, "prem_yes").format(date=utils.fmt_date(until))
    else:
        prem = t(lang, "prem_no")
    text = t(lang, "profile").format(
        id=m.from_user.id, lang=LANGS.get(lang, lang), prem=prem, favs=favs, dl=u["downloads"]
    )
    rows = [
        [btn(t(lang, "prem_btn"), "prem:open")],
        [btn(t(lang, "m_fav"), "favs:open"), btn(t(lang, "change_lang"), "lang_open")],
    ]
    await m.answer(text, reply_markup=kb_of(rows), parse_mode="HTML")


# ---------------- Tugash haqida eslatma ----------------
async def watcher(bot: Bot):
    while True:
        try:
            now = datetime.now(timezone.utc)
            for r in await db.expiring_users():
                lang = r["lang"] or "uz"
                days = max(1, (r["premium_until"] - now).days + 1)
                try:
                    await bot.send_message(
                        r["user_id"],
                        t(lang, "prem_expiring").format(days=days),
                        reply_markup=kb_of([[btn(t(lang, "prem_btn"), "prem:open")]]),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
                await db.mark_reminded(r["user_id"])
                await asyncio.sleep(0.1)
        except Exception as e:
            logging.warning("Premium eslatma xatosi: %s", e)
        await asyncio.sleep(6 * 3600)
