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
import tmdb
import translate
import ui
from utils import btn, kb_of

router = Router()
router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

S = ui.show_for


class UzTitle(StatesGroup):
    draft = State()


class UzEdit(StatesGroup):
    name = State()


def split_names(text: str) -> list[str]:
    """Nomlarni yangi qatordan yoki nuqta-vergul bilan ajratib oladi."""
    parts = [p.strip() for p in re.split(r"[\n;]+", text or "")]
    return list(dict.fromkeys(p for p in parts if p))[:8]


def apply_uz(d: dict):
    """Asosiy nom o'zgarmaydi. Birinchi o'zbekcha nom 2-nom (title_uz), hammasi qidiruvga qo'shiladi."""
    base = d.setdefault("base_aliases", list(d.get("aliases") or []))
    names = d.get("uz_names") or []
    d["title_uz"] = names[0] if names else None
    d["aliases"] = list(dict.fromkeys([*base, d["title"], *names]))


# ---------------- admin.py ga ulanish (uning kodiga tegmasdan) ----------------
_orig_preview_kb = admin.preview_kb
_orig_preview_text = admin.preview_text
_orig_prepare = admin.prepare_draft
_orig_movie_page = admin.movie_page
_orig_create = db.create_movie


def preview_kb(d):
    kb = _orig_preview_kb(d)
    rows = list(kb.inline_keyboard)
    names = d.get("uz_names") or []
    extra = [[btn(f"🇺🇿 {names[0][:26]}" if names else "🇺🇿 O'zbekcha nom qo'shish", "a:dr:uz")]]
    if d.get("uz_suggest") and not names:
        extra.append([btn(f"✅ «{d['uz_suggest'][:26]}» (tarjima)", "a:dr:uzs")])
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


async def create_movie(d):
    movie_id, code = await _orig_create(d)
    if d.get("title_uz"):
        await db.pool.execute("UPDATE movies SET title_uz=$1 WHERE id=$2", d["title_uz"], movie_id)
        db.invalidate()
    return movie_id, code


async def movie_page(movie_id: int):
    page = await _orig_movie_page(movie_id)
    if not page:
        return page
    text, kb = page
    movie = await db.get_movie(movie_id)
    uz = movie["title_uz"]
    lines = text.split("\n")
    lines.insert(1, f"🇺🇿 <b>{escape(uz)}</b>" if uz else "🇺🇿 <i>o'zbekcha nom yo'q</i>")
    rows = list(kb.inline_keyboard)
    extra = [[btn("🇺🇿 O'zbekcha nom", f"a:tu:{movie_id}")]]
    if uz:
        extra[0].append(btn("🔄 Almashtirish", f"a:tx:{movie_id}"))
    at = next(
        (i for i, r in enumerate(rows) if any((b.callback_data or "").startswith("a:n:") for b in r)),
        len(rows) - 2,
    )
    rows[at + 1 : at + 1] = extra
    return "\n".join(lines), kb_of(rows)


admin.preview_kb = preview_kb
admin.preview_text = preview_text
admin.prepare_draft = prepare_draft
admin.movie_page = movie_page
db.create_movie = create_movie


# ---------------- yangi kontent: o'zbekcha nom ----------------
@router.callback_query(admin.Add.draft, F.data == "a:dr:uz")
async def uz_ask(c: CallbackQuery, state: FSMContext):
    await state.set_state(UzTitle.draft)
    await c.answer()
    await S(
        c,
        "🇺🇿 <b>O'zbekcha nom</b>\n\nO'zbekcha nomni yozing. Asl (original) nom asosiy bo'lib qoladi, "
        "o'zbekcha nom 2-qatorda chiqadi.\nBir nechta nom bo'lsa, har birini yangi qatordan yozing "
        "(birinchisi ko'rinadi, qolganlari faqat qidiruv uchun).",
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
    apply_uz(d)
    await state.update_data(draft=d)
    await state.set_state(admin.Add.draft)
    await admin.show_preview(m, d)


@router.callback_query(admin.Add.draft, F.data == "a:dr:uzs")
async def uz_accept(c: CallbackQuery, state: FSMContext):
    d = (await state.get_data())["draft"]
    if d.get("uz_suggest"):
        d["uz_names"] = [d["uz_suggest"]]
        apply_uz(d)
        await state.update_data(draft=d)
    await c.answer("✅")
    await admin.refresh_preview(c, d)


# ---------------- mavjud kino: o'zbekcha nom ----------------
@router.callback_query(F.data.regexp(r"^a:tu:\d+$"))
async def uz_edit_ask(c: CallbackQuery, state: FSMContext):
    movie_id = int(c.data.split(":")[2])
    await state.clear()
    await state.set_state(UzEdit.name)
    await state.update_data(movie_id=movie_id)
    await c.answer()
    await S(
        c,
        "🇺🇿 <b>O'zbekcha nom</b>\n\nYangi o'zbekcha nomni yozing (u 2-qatorda ko'rinadi). "
        "Qo'shimcha qidiruv nomlari bo'lsa, ularni keyingi qatorlarga yozing.\n"
        "O'chirish uchun <code>-</code> yuboring.",
        kb_of([[btn("❌ Bekor qilish", f"a:m:{movie_id}")]]),
    )


@router.message(UzEdit.name, F.text & ~F.text.startswith("/"))
async def uz_edit_save(m: Message, state: FSMContext):
    movie_id = (await state.get_data())["movie_id"]
    await state.clear()
    await ui.delete_message(m)
    if m.text.strip() == "-":
        await db.pool.execute("UPDATE movies SET title_uz=NULL WHERE id=$1", movie_id)
    else:
        names = split_names(m.text)
        if names:
            await db.pool.execute("UPDATE movies SET title_uz=$1 WHERE id=$2", names[0], movie_id)
            for name in names:
                await db.add_alias(movie_id, name)
    db.invalidate()
    page = await admin.movie_page(movie_id)
    await S(m, page[0], page[1])


@router.callback_query(F.data.regexp(r"^a:tx:\d+$"))
async def uz_swap(c: CallbackQuery):
    """Asosiy va o'zbekcha nomni almashtiradi (masalan, nom noto'g'ri tartibda kiritilgan bo'lsa)."""
    movie_id = int(c.data.split(":")[2])
    row = await db.pool.fetchrow(
        "UPDATE movies SET title = title_uz, title_uz = title WHERE id=$1 AND title_uz IS NOT NULL "
        "RETURNING title, title_uz",
        movie_id,
    )
    if not row:
        await c.answer("O'zbekcha nom yo'q", show_alert=True)
        return
    await db.add_alias(movie_id, row["title"])
    await db.add_alias(movie_id, row["title_uz"])
    db.invalidate()
    await c.answer("🔄 Almashtirildi")
    await admin.open_page(c, movie_id)


# ---------------- mavjud kinolarda bir nechta qo'shimcha nom ----------------
@router.message(admin.Edit.alias, F.text & ~F.text.startswith("/"))
async def bulk_alias(m: Message, state: FSMContext):
    movie_id = (await state.get_data())["movie_id"]
    await state.clear()
    await ui.delete_message(m)
    for name in split_names(m.text):
        await db.add_alias(movie_id, name)
    page = await admin.movie_page(movie_id)
    await S(m, page[0], page[1])


# ---------------- qidiruv nomlari bo'limi ----------------
@router.callback_query(F.data == "at:tn")
async def names_home(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    row = await db.pool.fetchrow(
        "SELECT (SELECT count(*) FROM movies) AS movies, (SELECT count(*) FROM movie_titles) AS names, "
        "(SELECT count(*) FROM movies WHERE title_uz IS NOT NULL) AS uz"
    )
    text = (
        "🇺🇿 <b>Nomlar va qidiruv</b>\n\n"
        f"🎬 Kontent: {row['movies']} ta • 🇺🇿 o'zbekcha nomi borlar: {row['uz']} ta • 🏷 qidiruv nomlari: {row['names']} ta\n\n"
        "Asosiy nom original bo'lib qoladi, o'zbekcha nom 2-qatorda (kartochka, video, kanal posti) chiqadi.\n"
        "Qidiruv imlo xatolari, apostrof va kirill/lotin farqiga chidamli.\n\n"
        "• yangi kontent qo'shganda: 🇺🇿 O'zbekcha nom tugmasi;\n"
        "• kino sahifasida: 🇺🇿 O'zbekcha nom va 🏷 Qo'shimcha nom;\n"
        "• 🌐 avto tarjima faqat qidiruv uchun yashirin nom qo'shadi (ko'rinmaydi)."
    )
    kb = kb_of(
        [
            [btn("🌐 Avto tarjima (faqat qidiruv)", "at:tna")],
            [btn("♻️ Eski nomlarni tuzatish (TMDB)", "at:tfc")],
            [btn("◀️ Orqaga", "a:home")],
        ]
    )
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
        "Tarjima so'zma-so'z bo'ladi va faqat qidiruv uchun yashirin nom sifatida qo'shiladi "
        "(foydalanuvchiga ko'rsatilmaydi). Davom etamizmi?",
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
    await S(c, f"✅ <b>{added}</b> ta qidiruv nomi qo'shildi.{note}", kb_of([[btn("◀️ Orqaga", "at:tn")]]))


@router.callback_query(F.data == "at:tfc")
async def fix_confirm(c: CallbackQuery):
    await c.answer()
    await S(
        c,
        "♻️ <b>Eski nomlarni tuzatish</b>\n\n"
        "O'zbekcha nomi yo'q va nomi TMDB'dagi asl nomdan farq qiladigan kinolarda: hozirgi nom "
        "<b>o'zbekcha nom</b> bo'ladi, asosiy nom esa TMDB'dagi original nomga almashadi.\n\n"
        "Qo'lda boshqa nom qo'ygan bo'lsangiz, u ham o'zbekcha nom deb olinadi (keyin kino sahifasida "
        "🔄 Almashtirish bilan to'g'rilash mumkin). Davom etamizmi?",
        kb_of([[btn("✅ Ha, tuzatish", "at:tfr")], [btn("◀️ Orqaga", "at:tn")]]),
    )


@router.callback_query(F.data == "at:tfr")
async def fix_run(c: CallbackQuery):
    await c.answer("Tekshirilmoqda...")
    rows = await db.pool.fetch(
        "SELECT id, title, tmdb_type, tmdb_id FROM movies WHERE tmdb_id IS NOT NULL AND title_uz IS NULL ORDER BY id"
    )
    fixed = errors = 0
    for r in rows[:80]:
        try:
            data = await tmdb._get(f"/{r['tmdb_type']}/{r['tmdb_id']}", language="en-US")
        except Exception:
            errors += 1
            continue
        orig = (data.get("title") or data.get("name") or "").strip()
        if orig and orig.lower() != r["title"].strip().lower():
            await db.pool.execute("UPDATE movies SET title=$2, title_uz=$3 WHERE id=$1", r["id"], orig, r["title"])
            await db.add_alias(r["id"], orig)
            fixed += 1
        await asyncio.sleep(0.15)
    db.invalidate()
    more = "\n\nYana bor, tugmani qayta bosing." if len(rows) > 80 else ""
    err = f"\n⚠️ TMDB xatosi: {errors} ta" if errors else ""
    await S(
        c,
        f"✅ Tekshirildi: {min(len(rows), 80)} ta, tuzatildi: <b>{fixed}</b> ta.{err}{more}",
        kb_of([[btn("◀️ Orqaga", "at:tn")]]),
    )


@router.message(StateFilter(UzTitle, UzEdit))
async def wrong(m: Message):
    await ui.delete_message(m)
    await ui.flash(m.bot, m.chat.id, "⚠️ Nomni matn ko'rinishida yuboring yoki tugmani bosing.")
