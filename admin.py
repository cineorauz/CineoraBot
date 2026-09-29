from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import config
import database as db
import utils

router = Router()
router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))


class AddMovie(StatesGroup):
    title = State()
    poster = State()
    q1080 = State()
    q720 = State()


class DelMovie(StatesGroup):
    code = State()


def menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Kino qo'shish", callback_data="admin:add")],
            [InlineKeyboardButton(text="🗑 Kino o'chirish", callback_data="admin:del")],
            [InlineKeyboardButton(text="📊 Statistika", callback_data="admin:stats")],
        ]
    )


def file_of(m: Message):
    """Fayl id, turi va izohni (bold va boshqa formatlari bilan, HTML ko'rinishida) qaytaradi."""
    caption = m.html_text if m.caption else None
    if m.video:
        return [m.video.file_id, "video", caption]
    if m.document:
        return [m.document.file_id, "document", caption]
    return None


@router.message(Command("admin"))
async def admin_menu(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("🛠 Admin panel", reply_markup=menu_kb())


@router.message(Command("cancel"))
async def cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Bekor qilindi. /admin")


@router.callback_query(F.data == "admin:stats")
async def stats(c: CallbackQuery):
    users = await db.count_users()
    movies = await db.count_movies()
    await c.message.answer(f"📊 Foydalanuvchilar: {users}\n🎬 Kinolar: {movies}")
    await c.answer()


# ---------- kino qo'shish ----------
@router.callback_query(F.data == "admin:add")
async def add_start(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(AddMovie.title)
    await c.message.answer("🎬 Kino nomini yozing\n(bekor qilish: /cancel)")
    await c.answer()


@router.message(AddMovie.title, F.text)
async def add_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text.strip())
    await state.set_state(AddMovie.poster)
    await m.answer("🖼 Poster rasmini yuboring\n(o'tkazib yuborish: /skip)")


@router.message(AddMovie.poster, F.photo)
async def add_poster(m: Message, state: FSMContext):
    await state.update_data(poster=m.photo[-1].file_id)
    await state.set_state(AddMovie.q1080)
    await m.answer("📀 1080p faylni yuboring (video yoki hujjat)\n(o'tkazib yuborish: /skip)")


@router.message(AddMovie.poster, Command("skip"))
async def skip_poster(m: Message, state: FSMContext):
    await state.set_state(AddMovie.q1080)
    await m.answer("📀 1080p faylni yuboring (video yoki hujjat)\n(o'tkazib yuborish: /skip)")


@router.message(AddMovie.q1080, F.video | F.document)
async def add_1080(m: Message, state: FSMContext):
    await state.update_data(f1080=file_of(m))
    await state.set_state(AddMovie.q720)
    await m.answer("📀 720p faylni yuboring (video yoki hujjat)\n(o'tkazib yuborish: /skip)")


@router.message(AddMovie.q1080, Command("skip"))
async def skip_1080(m: Message, state: FSMContext):
    await state.set_state(AddMovie.q720)
    await m.answer("📀 720p faylni yuboring (video yoki hujjat)\n(o'tkazib yuborish: /skip)")


async def finish(m: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    movie_id = await db.add_movie(data["title"], data.get("poster"))
    for q in ("1080", "720"):
        f = data.get("f" + q)
        if f:
            await db.add_file(movie_id, q, f[0], f[1], f[2])
    link = f"https://t.me/{utils.BOT_USERNAME}?start=m{movie_id}"
    await m.answer(f"✅ Qo'shildi!\n\n🔑 Kod: {movie_id}\n🔗 {link}")


@router.message(AddMovie.q720, F.video | F.document)
async def add_720(m: Message, state: FSMContext):
    await state.update_data(f720=file_of(m))
    await finish(m, state)


@router.message(AddMovie.q720, Command("skip"))
async def skip_720(m: Message, state: FSMContext):
    await finish(m, state)


# ---------- kino o'chirish ----------
@router.callback_query(F.data == "admin:del")
async def del_start(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(DelMovie.code)
    await c.message.answer("🗑 O'chiriladigan kino kodini yozing\n(bekor qilish: /cancel)")
    await c.answer()


@router.message(DelMovie.code, F.text)
async def del_code(m: Message, state: FSMContext):
    await state.clear()
    if not m.text.strip().isdigit():
        await m.answer("Kod raqam bo'lishi kerak. /admin")
        return
    ok = await db.delete_movie(int(m.text.strip()))
    await m.answer("✅ O'chirildi. /admin" if ok else "Bunday kod topilmadi. /admin")
