import asyncio
import re
from html import escape

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import admin
import config
import database as db
import translate
import ui
from utils import btn, kb_of

router = Router()
router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

S = ui.show_for


class UzTitle(StatesGroup):
    draft = State()


def split_names(text: str) -> list[str]:
    """Nomlarni yangi qatordan yoki nuqta-vergul bilan ajratib oladi."""
    parts = [p.strip() for p in re.split(r"[\n;]+", text or "")]
    return list(dict.fromkeys(p for p in parts if p))[:8]


def apply_uz(d: dict):
    """O'zbekcha nomni qo'llaydi: asosiy nom bo'ladi, asl nom va boshqalari qidiruvda qoladi."""
    orig = d.setdefault("title_orig", d["title"])
    names = d.get("uz_names") or []
    d["aliases"] = list(dict.fromkeys([*(d.get("aliases") or []), orig, *names]))
    d["title"] = names[0] if (names and d.get("uz_main", True)) else orig


# ---------------- admin.py ga ulanish (uning kodiga tegmasdan) ----------------
_orig_preview_kb = admin.preview_kb
_orig_preview_text = admin.preview_text
_orig_prepare = admin.prepare_draft


def preview_kb(d):
    kb = _orig_preview_kb(d)
    rows = list(kb.inline_keyboard)
    names = d.get("uz_names") or []
    extra = [[btn(f"🇺🇿 O'zbekcha nom: {names[0][:22]}" if names else "🇺🇿 O'zbekcha nom", "a:dr:uz")]]
    if d.get("uz_suggest") and not names:
        extra.append([btn(f"✅ «{d['uz_suggest'][:26]}» (tarjima)", "a:dr:uzs")])
    if names:
        extra.append([btn("🔁 Asosiy nom: " + ("ha" if d.get("uz_main", True) else "yo'q"), "a:dr:uzm")])
    rows[-1:-1] = extra  # «Bekor qilish» tugmasidan oldin
    return kb_of(rows)


def preview_text(d):
    text = _orig_preview_text(d)
    names = d.get("uz_names")
    if names:
        more = f" (+{len(names) - 1})" if len(names) > 1 else ""
        text += f"\n🇺🇿 O'zbekcha nom: <b>{escape(names[0])}</b>{more}"
    elif d.get("uz_suggest"):
        text += f"\n🇺🇿 Tarjima taklifi: <i>{escape(d['uz_suggest'])}</i>"
    return text


async def prepare_draft(d):
    await _orig_prepare(d)
    out, _err = await translate.translate_texts([d["title"]], "eng_Latn")
    if out and out[0].strip() and out[0].strip().lower() != d["title"].strip().lower():
        d["uz_suggest"] = out[0].strip()


admin.preview_kb = preview_kb
admin.preview_text = preview_text
admin.prepare_draft = prepare_draft


# ---------------- yangi kontent: o'zbekcha nom ----------------
@router.callback_query(admin.Add.draft, F.data == "a:dr:uz")
async def uz_ask(c: CallbackQuery, state: FSMContext):
    await state.set_state(UzTitle.draft)
    await c.answer()
    await S(
        c,
        "🇺🇿 <b>O'zbekcha nom</b>\n\nO'zbekcha nomni yozing. Bir nechta nom bo'lsa, har birini yangi qatordan yozing "
        "(birinchisi asosiy nom bo'ladi, qolganlari qidiruv uchun).\nAsl nom ham qidiruvda qoladi.",
        kb_of([[btn("◀️ Orqaga", "a:dr:uzb")]]),
    )


@router.callback_query(UzTitle.draft, F.data == "a:dr:uzb")
async def uz_back(c: CallbackQuery, state: FSMContext):
    d = (await state.get_data())["draft"]
    await state.set_state(admin.Add.draft)
    await c.answer()
    await admin.show_preview(c, d)


@router.message(UzTitle.draft, F.text & ~F.text.startswith("/"))
async def uz_input(m: Message, state: FSMContext):
    d = (await state.get_data())["draft"]
    names = split_names(m.text)
    await ui.delete_message(m)
    if not names:
        return
    d["uz_names"] = names
    d.setdefault("uz_main", True)
    apply_uz(d)
    await state.update_data(draft=d)
    await state.set_state(admin.Add.draft)
    await admin.show_preview(m, d)


@router.callback_query(admin.Add.draft, F.data == "a:dr:uzs")
async def uz_accept(c: CallbackQuery, state: FSMContext):
    d = (await state.get_data())["draft"]
    if d.get("uz_suggest"):
        d["uz_names"] = [d["uz_suggest"]]
        d.setdefault("uz_main", True)
        apply_uz(d)
        await state.update_data(draft=d)
    await c.answer("✅")
    await admin.refresh_preview(c, d)


@router.callback_query(admin.Add.draft, F.data == "a:dr:uzm")
async def uz_main_toggle(c: CallbackQuery, state: FSMContext):
    d = (await state.get_data())["draft"]
    d["uz_main"] = not d.get("uz_main", True)
    apply_uz(d)
    await state.update_data(draft=d)
    await c.answer()
    await admin.refresh_preview(c, d)


# ---------------- mavjud kino: bir nechta qo'shimcha nom ----------------
@router.message(admin.Edit.alias, F.text & ~F.text.startswith("/"))
async def bulk_alias(m: Message, state: FSMContext):
    movie_id = (await state.get_data())["movie_id"]
    await state.clear()
    await ui.delete_message(m)
    for name in split_names(m.text):
        await db.add_alias(movie_id, name)
    page = await admin.movie_page(movie_id)
    await S(m, page[0], page[1])


# ---------------- barcha kinolarga avtomatik tarjima nom ----------------
@router.callback_query(F.data == "at:tn")
async def names_home(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    row = await db.pool.fetchrow(
        "SELECT (SELECT count(*) FROM movies) AS movies, (SELECT count(*) FROM movie_titles) AS names"
    )
    text = (
        "🇺🇿 <b>Qidiruv nomlari</b>\n\n"
        f"🎬 Kontent: {row['movies']} ta • 🏷 Qidiruvdagi nomlar: {row['names']} ta\n\n"
        "Qidiruv imlo xatolari, apostrof va kirill/lotin farqlariga chidamli. O'zbekcha nom qo'shishning yo'llari:\n"
        "• yangi kontent qo'shganda 🇺🇿 O'zbekcha nom tugmasi;\n"
        "• kino sahifasida 🏷 Qo'shimcha nom (har bir nom yangi qatordan);\n"
        "• quyidagi tugma bilan hammasiga avtomatik tarjima nom qo'shish (qidiruv uchun)."
    )
    kb = kb_of([[btn("🌐 Avto tarjima nomlarni qo'shish", "at:tna")], [btn("◀️ Orqaga", "a:home")]])
    await S(c, text, kb)


@router.callback_query(F.data == "at:tna")
async def names_confirm(c: CallbackQuery):
    rows = await db.pool.fetch("SELECT title FROM movies WHERE tmdb_id IS NOT NULL")
    chars = sum(len(r["title"]) for r in rows)
    await c.answer()
    await S(
        c,
        f"🌐 <b>{len(rows)}</b> ta kontent nomi tarjima qilinadi.\n"
        f"💰 Taxminiy narx: <b>~{int(chars * 0.35) + 1} so'm</b> (Tilmoch hisobingizdan).\n\n"
        "Tarjima so'zma-so'z bo'ladi va faqat qidiruv uchun qo'shimcha nom sifatida qo'shiladi. Davom etamizmi?",
        kb_of([[btn("✅ Ha, boshlash", "at:tnc")], [btn("◀️ Orqaga", "at:tn")]]),
    )


@router.callback_query(F.data == "at:tnc")
async def names_run(c: CallbackQuery):
    await c.answer("Tarjima qilinmoqda...")
    rows = await db.pool.fetch("SELECT id, title FROM movies WHERE tmdb_id IS NOT NULL ORDER BY id")
    added, error = 0, None
    for i in range(0, len(rows), 25):
        chunk = rows[i : i + 25]
        out, err = await translate.translate_texts([r["title"] for r in chunk], "eng_Latn")
        if err:
            error = err
            break
        for r, tr in zip(chunk, out):
            tr = (tr or "").strip()
            if tr and tr.lower() != r["title"].strip().lower():
                await db.add_alias(r["id"], tr)
                added += 1
        await asyncio.sleep(1.3)  # Tilmoch: daqiqasiga 50 so'rovgacha
    note = f"\n\n⚠️ {escape(error)}" if error else ""
    await S(
        c,
        f"✅ <b>{added}</b> ta qo'shimcha nom qo'shildi.{note}",
        kb_of([[btn("◀️ Orqaga", "at:tn")]]),
    )


@router.message(StateFilter(UzTitle))
async def wrong(m: Message):
    await ui.delete_message(m)
    await ui.flash(m.bot, m.chat.id, "⚠️ Nomni matn ko'rinishida yuboring yoki «Orqaga» ni bosing.")
