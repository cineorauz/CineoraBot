import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import admin
import config
import database as db
import ui
from utils import btn, kb_of

router = Router()
router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

UZ = timezone(timedelta(hours=5))  # Toshkent: UTC+5, yozgi/qishki vaqt yo'q
S = ui.show_for
_count = {"n": 0}
SPEC = r"(n|e\d+-\d+-\d+)"
# Post uchun vaqtincha video: (kino, spec) -> (file_id, tur). Bazaga saqlanmaydi (faqat vaqtga qo'yilgan postda qisqa file_id)
_clip: dict[tuple, tuple] = {}


class SchedTime(StatesGroup):
    wait = State()


class ClipWait(StatesGroup):
    video = State()


def pending_count() -> int:
    return _count["n"]


async def refresh_count():
    _count["n"] = await db.pool.fetchval("SELECT count(*) FROM scheduled_posts WHERE status = 'pending'") or 0


async def init():
    await db.pool.execute(
        """
        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id SERIAL PRIMARY KEY,
            movie_id INT NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
            spec TEXT NOT NULL,
            run_at TIMESTAMPTZ NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_by BIGINT,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            sent_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS scheduled_posts_idx ON scheduled_posts(status, run_at);
        ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS clip_id TEXT;
        ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS clip_kind TEXT;
        """
    )
    await db.pool.execute("UPDATE scheduled_posts SET status='pending' WHERE status='sending'")
    await refresh_count()


# ---------------- vaqt yordamchilari ----------------
def fmt(dt) -> str:
    return dt.astimezone(UZ).strftime("%d.%m %H:%M")


def spec_label(spec: str) -> str:
    if spec == "n":
        return "to'liq post"
    m = re.fullmatch(r"e(\d+)-(\d+)-(\d+)", spec)
    if not m:
        return spec
    s, a, b = m.groups()
    return f"{s}-fasl, {a}-qism" if a == b else f"{s}-fasl, {a}–{b}-qismlar"


def quick_when(opt: str):
    """m30 — 30 daqiqadan keyin; h20 — eng yaqin 20:00 (bugun yoki ertaga)."""
    now = datetime.now(UZ)
    kind, val = opt[0], int(opt[1:])
    if kind == "m":
        return now + timedelta(minutes=val)
    dt = now.replace(hour=val, minute=0, second=0, microsecond=0)
    if dt <= now + timedelta(minutes=1):
        dt += timedelta(days=1)
    return dt


def parse_when(text: str):
    """«20:30» yoki «25.12 20:30» yoki «25.12.2026 20:30» (Toshkent vaqti)."""
    t = " ".join(text.strip().replace(",", " ").split())
    now = datetime.now(UZ)
    try:
        m = re.fullmatch(r"(\d{1,2})[:.](\d{2})", t)
        if m:
            dt = now.replace(hour=int(m[1]), minute=int(m[2]), second=0, microsecond=0)
            return dt + timedelta(days=1) if dt <= now else dt
        m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))? (\d{1,2})[:.](\d{2})", t)
        if m:
            day, mon, year, hh, mm = m.groups()
            y = int(year) if year else now.year
            y += 2000 if y < 100 else 0
            dt = datetime(y, int(mon), int(day), int(hh), int(mm), tzinfo=UZ)
            if not year and dt <= now:
                dt = dt.replace(year=y + 1)
            return dt
    except ValueError:
        return None
    return None


async def show(c: CallbackQuery, text: str, kb, photo=None):
    """Panel ekrani tahrirlanadi; bildirishnoma xabaridan bosilsa yangi xabar sifatida chiqadi."""
    uid = c.from_user.id
    if ui.screen_id(uid) == c.message.message_id:
        return await S(c, text, kb, photo=photo)
    return await ui.show(c.bot, c.message.chat.id, uid, text, kb, photo=photo, force_new=True)


# ---------------- e'lon oldindan ko'rish (admin.py dagisini almashtiradi) ----------------
async def need_channel(c: CallbackQuery) -> bool:
    if not db.get_setting("ann_channel"):
        await c.answer("Avval Sozlamalarda e'lon kanalini belgilang", show_alert=True)
        return False
    return True


async def build_preview(movie_id: int, spec: str):
    """(izoh, tugmalar, poster, video) yoki None."""
    movie = await db.get_movie(movie_id)
    if not movie:
        return None
    caption, _kb, poster = await admin.build_post(movie_id, spec)
    clip = _clip.get((movie_id, spec))
    back = f"a:an:{movie_id}" if movie["is_series"] else f"a:m:{movie_id}"
    rows = [
        [btn("🚀 Hozir joylash", f"a:ak:{movie_id}:{spec}"), btn("⏰ Vaqtga qo'yish", f"sc:p:{movie_id}:{spec}")],
        [btn("🔄 Videoni almashtirish" if clip else "🎬 Video qo'shish", f"cp:a:{movie_id}:{spec}")],
    ]
    if clip:
        rows.append([btn("🗑 Videoni olib tashlash", f"cp:x:{movie_id}:{spec}")])
    rows.append([btn("◀️ Orqaga", back)])
    return caption, kb_of(rows), poster, clip


async def send_clip_screen(bot, chat_id: int, uid: int, caption: str, kb, clip: tuple):
    """Video ko'rinishidagi oldindan ko'rish ekrani (eski ekran o'chiriladi)."""
    old = ui.screen_id(uid)
    file_id, kind = clip
    send = bot.send_animation if kind == "animation" else bot.send_video
    sent = await send(chat_id, file_id, caption=caption, reply_markup=kb, parse_mode="HTML")
    ui._remember(uid, sent)
    ui._buried.discard(uid)
    if old and old != sent.message_id:
        await ui.delete_id(bot, chat_id, old)


async def preview(c: CallbackQuery, movie_id: int, spec: str):
    view = await build_preview(movie_id, spec)
    if not view:
        await c.answer("Topilmadi", show_alert=True)
        return
    caption, kb, poster, clip = view
    if clip:
        try:
            await send_clip_screen(c.bot, c.message.chat.id, c.from_user.id, caption, kb, clip)
            return
        except Exception as e:
            _clip.pop((movie_id, spec), None)
            await c.answer(f"Videoni ko'rsatib bo'lmadi: {e}"[:190], show_alert=True)
            view = await build_preview(movie_id, spec)
            caption, kb, poster, clip = view
    await show(c, caption, kb, photo=poster)


@router.callback_query(F.data.regexp(r"^a:an:\d+$"))
async def announce_start(c: CallbackQuery):
    movie_id = int(c.data.split(":")[2])
    movie = await db.get_movie(movie_id)
    if not movie:
        await c.answer("Topilmadi", show_alert=True)
        return
    if not await need_channel(c):
        return
    await c.answer()
    if not movie["is_series"]:
        await preview(c, movie_id, "n")
        return
    counts = await db.season_counts(movie_id)
    rows = [[btn("📣 To'liq post (serial haqida)", f"a:av:{movie_id}:n")]]
    if counts:
        last_season = max(counts)
        last_ep = await db.max_episode(movie_id, last_season)
        rows.append(
            [btn(f"🆕 Yangi qism ({last_season}-fasl, {last_ep}-qism)", f"a:av:{movie_id}:e{last_season}-{last_ep}-{last_ep}")]
        )
    rows.append([btn("◀️ Orqaga", f"a:m:{movie_id}")])
    await show(c, "📣 <b>Qanday post joylaymiz?</b>", kb_of(rows))


@router.callback_query(F.data.regexp(rf"^a:av:\d+:{SPEC}$"))
async def announce_preview(c: CallbackQuery, state: FSMContext):
    _, _, movie_id, spec = c.data.split(":")
    await state.clear()
    if not await need_channel(c):
        return
    await c.answer()
    await preview(c, int(movie_id), spec)


# ---------------- video (ixtiyoriy) ----------------
@router.callback_query(F.data.regexp(rf"^cp:a:\d+:{SPEC}$"))
async def clip_ask(c: CallbackQuery, state: FSMContext):
    _, _, movie_id, spec = c.data.split(":")
    await state.set_state(ClipWait.video)
    await state.update_data(movie_id=int(movie_id), spec=spec)
    await c.answer()
    await show(
        c,
        "🎬 <b>Video qo'shish</b>\n\nKino parchasi yoki edit videoni <b>video</b> sifatida yuboring (fayl emas). "
        "U shu post bilan kanalga joylanadi va bazaga saqlanmaydi.\nVideo qo'shmasangiz, post poster bilan chiqadi.",
        kb_of([[btn("❌ Bekor qilish", f"a:av:{movie_id}:{spec}")]]),
    )


@router.message(ClipWait.video, F.video | F.animation)
async def clip_got(m: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    await ui.delete_message(m)
    if m.video:
        clip = (m.video.file_id, "video")
    else:
        clip = (m.animation.file_id, "animation")
    movie_id, spec = d["movie_id"], d["spec"]
    _clip[(movie_id, spec)] = clip
    view = await build_preview(movie_id, spec)
    if not view:
        return
    caption, kb, _poster, _clip_now = view
    try:
        await send_clip_screen(m.bot, m.chat.id, m.from_user.id, caption, kb, clip)
    except Exception as e:
        _clip.pop((movie_id, spec), None)
        await ui.flash(m.bot, m.chat.id, f"⚠️ Videoni qabul qilib bo'lmadi: {escape(str(e))[:150]}", 6)


@router.message(StateFilter(ClipWait))
async def clip_wrong(m: Message):
    await ui.delete_message(m)
    await ui.flash(m.bot, m.chat.id, "⚠️ Videoni fayl emas, <b>video</b> sifatida yuboring yoki «Bekor qilish» ni bosing.", 5)


@router.callback_query(F.data.regexp(rf"^cp:x:\d+:{SPEC}$"))
async def clip_remove(c: CallbackQuery):
    _, _, movie_id, spec = c.data.split(":")
    _clip.pop((int(movie_id), spec), None)
    await c.answer("🗑 Olib tashlandi")
    await preview(c, int(movie_id), spec)


# ---------------- vaqt tanlash ----------------
def picker_kb(quick: str, manual_cb: str, back_cb: str):
    now = datetime.now(UZ)

    def hour_btn(h: int, icon: str):
        day = "Bugun" if quick_when(f"h{h}").date() == now.date() else "Ertaga"
        return btn(f"{icon} {day} {h:02d}:00", f"{quick}:h{h}")

    return kb_of(
        [
            [btn("⏱ 30 daqiqadan keyin", f"{quick}:m30"), btn("⏱ 1 soatdan keyin", f"{quick}:m60")],
            [btn("⏱ 3 soatdan keyin", f"{quick}:m180")],
            [hour_btn(9, "🌅"), hour_btn(12, "🌤")],
            [hour_btn(18, "🌆"), hour_btn(20, "🌙")],
            [btn("✍️ Vaqtni o'zim yozaman", manual_cb)],
            [btn("◀️ Orqaga", back_cb)],
        ]
    )


def picker_text(title: str, label: str) -> str:
    now = datetime.now(UZ)
    return (
        f"⏰ <b>Qachon joylaymiz?</b>\n\n🎬 {escape(title)} — {escape(label)}\n"
        f"🕒 Hozir: <b>{now:%H:%M}</b> (Toshkent vaqti)\n\nTez variantni tanlang yoki vaqtni yozing 👇"
    )


@router.callback_query(F.data.regexp(rf"^sc:p:\d+:{SPEC}$"))
async def pick_new(c: CallbackQuery):
    _, _, movie_id, spec = c.data.split(":")
    movie = await db.get_movie(int(movie_id))
    if not movie:
        await c.answer("Topilmadi", show_alert=True)
        return
    await c.answer()
    kb = picker_kb(f"sc:s:{movie_id}:{spec}", f"sc:w:{movie_id}:{spec}", f"a:av:{movie_id}:{spec}")
    await show(c, picker_text(movie["title"], spec_label(spec)), kb)


async def job(sid: int):
    return await db.pool.fetchrow(
        "SELECT s.id, s.movie_id, s.spec, s.run_at, s.status, s.error, (s.clip_id IS NOT NULL) AS has_clip, m.title "
        "FROM scheduled_posts s JOIN movies m ON m.id = s.movie_id WHERE s.id=$1",
        sid,
    )


async def done_view(sid: int, updated: bool):
    r = await job(sid)
    video = "\n🎬 Video bilan" if r["has_clip"] else ""
    text = (
        f"✅ <b>{'Reja yangilandi' if updated else 'Rejalashtirildi'}</b>\n\n"
        f"🎬 {escape(r['title'])}\n📣 {escape(spec_label(r['spec']))}{video}\n"
        f"🕒 <b>{fmt(r['run_at'])}</b> (Toshkent)\n\nBot shu vaqtda kanalga o'zi joylaydi."
    )
    kb = kb_of([[btn("⏰ Rejalar", "sc:list")], [btn("◀️ Kino sahifasi", f"a:m:{r['movie_id']}")]])
    return text, kb


async def schedule_new(uid: int, movie_id: int, spec: str, when):
    clip = _clip.pop((movie_id, spec), None)
    fid, kind = clip if clip else (None, None)
    row = await db.pool.fetchrow(
        "SELECT id FROM scheduled_posts WHERE movie_id=$1 AND spec=$2 AND status IN ('pending','failed')",
        movie_id, spec,
    )
    if row:
        await db.pool.execute(
            "UPDATE scheduled_posts SET run_at=$2, status='pending', error=NULL, "
            "clip_id=COALESCE($3, clip_id), clip_kind=COALESCE($4, clip_kind) WHERE id=$1",
            row["id"], when, fid, kind,
        )
        sid, updated = row["id"], True
    else:
        sid = await db.pool.fetchval(
            "INSERT INTO scheduled_posts (movie_id, spec, run_at, created_by, clip_id, clip_kind) "
            "VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
            movie_id, spec, when, uid, fid, kind,
        )
        updated = False
    await refresh_count()
    return await done_view(sid, updated)


async def reschedule(sid: int, when):
    await db.pool.execute(
        "UPDATE scheduled_posts SET run_at=$2, status='pending', error=NULL WHERE id=$1 AND status IN ('pending','failed')",
        sid, when,
    )
    await refresh_count()
    return await done_view(sid, True)


@router.callback_query(F.data.regexp(rf"^sc:s:\d+:{SPEC}:[mh]\d+$"))
async def quick_new(c: CallbackQuery):
    _, _, movie_id, spec, opt = c.data.split(":")
    text, kb = await schedule_new(c.from_user.id, int(movie_id), spec, quick_when(opt))
    await c.answer("⏰ Rejalashtirildi")
    await show(c, text, kb)


@router.callback_query(F.data.regexp(rf"^sc:w:\d+:{SPEC}$"))
async def manual_new(c: CallbackQuery, state: FSMContext):
    _, _, movie_id, spec = c.data.split(":")
    await state.set_state(SchedTime.wait)
    await state.update_data(mode="new", movie_id=int(movie_id), spec=spec)
    await c.answer()
    await show(c, manual_text(), kb_of([[btn("❌ Bekor qilish", f"sc:p:{movie_id}:{spec}")]]))


def manual_text() -> str:
    return (
        "✍️ <b>Vaqtni yozing</b> (Toshkent vaqti)\n\n"
        "• bugun/ertaga: <code>20:30</code>\n• sana bilan: <code>25.12 20:30</code> yoki <code>25.12.2026 20:30</code>"
    )


@router.callback_query(F.data.regexp(r"^sc:chg:\d+$"))
async def pick_existing(c: CallbackQuery):
    sid = int(c.data.split(":")[2])
    r = await job(sid)
    if not r:
        await c.answer("Topilmadi", show_alert=True)
        return
    await c.answer()
    kb = picker_kb(f"sc:r:{sid}", f"sc:rw:{sid}", f"sc:v:{sid}")
    await show(c, picker_text(r["title"], spec_label(r["spec"])), kb)


@router.callback_query(F.data.regexp(r"^sc:r:\d+:[mh]\d+$"))
async def quick_existing(c: CallbackQuery):
    _, _, sid, opt = c.data.split(":")
    text, kb = await reschedule(int(sid), quick_when(opt))
    await c.answer("🕒 Vaqt yangilandi")
    await show(c, text, kb)


@router.callback_query(F.data.regexp(r"^sc:rw:\d+$"))
async def manual_existing(c: CallbackQuery, state: FSMContext):
    sid = int(c.data.split(":")[2])
    await state.set_state(SchedTime.wait)
    await state.update_data(mode="res", sid=sid)
    await c.answer()
    await show(c, manual_text(), kb_of([[btn("❌ Bekor qilish", f"sc:v:{sid}")]]))


@router.message(SchedTime.wait, F.text & ~F.text.startswith("/"))
async def time_input(m: Message, state: FSMContext):
    await ui.delete_message(m)
    when = parse_when(m.text)
    if not when:
        await ui.flash(m.bot, m.chat.id, "⚠️ Format: <code>20:30</code> yoki <code>25.12 20:30</code>", 6)
        return
    if when <= datetime.now(UZ) + timedelta(seconds=30):
        await ui.flash(m.bot, m.chat.id, "⚠️ Bu vaqt o'tib ketgan. Kelajakdagi vaqtni yozing.", 5)
        return
    d = await state.get_data()
    await state.clear()
    if d.get("mode") == "res":
        text, kb = await reschedule(d["sid"], when)
    else:
        text, kb = await schedule_new(m.from_user.id, d["movie_id"], d["spec"], when)
    await S(m, text, kb)


@router.message(StateFilter(SchedTime))
async def time_wrong(m: Message):
    await ui.delete_message(m)
    await ui.flash(m.bot, m.chat.id, "⚠️ Vaqtni matn ko'rinishida yozing: 20:30 yoki 25.12 20:30")


# ---------------- rejalar ro'yxati ----------------
async def list_view():
    rows = await db.pool.fetch(
        "SELECT s.id, s.spec, s.run_at, s.status, (s.clip_id IS NOT NULL) AS has_clip, m.title "
        "FROM scheduled_posts s JOIN movies m ON m.id = s.movie_id WHERE s.status IN ('pending', 'failed') "
        "ORDER BY (s.status = 'failed') DESC, s.run_at LIMIT 10"
    )
    sent = await db.pool.fetch(
        "SELECT s.spec, s.sent_at, m.title FROM scheduled_posts s JOIN movies m ON m.id = s.movie_id "
        "WHERE s.status = 'sent' ORDER BY s.sent_at DESC LIMIT 3"
    )
    await refresh_count()
    lines = ["⏰ <b>Rejalashtirilgan postlar</b> (Toshkent vaqti)\n"]
    if rows:
        for i, r in enumerate(rows, 1):
            icon = "❌" if r["status"] == "failed" else "⏰"
            clip = "🎬 " if r["has_clip"] else ""
            lines.append(f"{i}. {icon} {fmt(r['run_at'])} — {clip}{escape(r['title'])} ({escape(spec_label(r['spec']))})")
    else:
        lines.append("Hozircha reja yo'q. Kino sahifasi → 📣 Kanalga e'lon → ⏰ Vaqtga qo'yish.")
    if sent:
        lines.append("\n✅ <b>Oxirgi joylanganlar:</b>")
        lines += [f"• {fmt(s['sent_at'])} — {escape(s['title'])}" for s in sent]
    kb = [[btn(str(i), f"sc:v:{r['id']}") for i, r in enumerate(rows, 1)]] if rows else []
    kb.append([btn("◀️ Admin panel", "a:home")])
    return "\n".join(lines), kb_of(kb)


@router.callback_query(F.data == "sc:list")
async def list_open(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    text, kb = await list_view()
    await show(c, text, kb)


@router.callback_query(F.data.regexp(r"^sc:v:\d+$"))
async def detail_open(c: CallbackQuery, state: FSMContext):
    await state.clear()
    r = await job(int(c.data.split(":")[2]))
    if not r:
        await c.answer("Topilmadi", show_alert=True)
        return
    await c.answer()
    failed = r["status"] == "failed"
    video = "\n🎬 Video bilan" if r["has_clip"] else ""
    text = (
        f"⏰ <b>Reja #{r['id']}</b>\n\n🎬 {escape(r['title'])}\n📣 {escape(spec_label(r['spec']))}{video}\n"
        f"🕒 <b>{fmt(r['run_at'])}</b> (Toshkent)"
    )
    if failed:
        text += f"\n\n❌ <b>Xato:</b> {escape(r['error'] or '—')}"
    rows = [
        [btn("🔁 Qayta urinish" if failed else "🚀 Hozir yuborish", f"sc:now:{r['id']}")],
        [btn("🕒 Vaqtni o'zgartirish", f"sc:chg:{r['id']}"), btn("🗑 Bekor qilish", f"sc:del:{r['id']}")],
        [btn("◀️ Rejalar", "sc:list")],
    ]
    await show(c, text, kb_of(rows))


@router.callback_query(F.data.regexp(r"^sc:del:\d+$"))
async def delete_job(c: CallbackQuery):
    await db.pool.execute(
        "DELETE FROM scheduled_posts WHERE id=$1 AND status IN ('pending', 'failed')", int(c.data.split(":")[2])
    )
    await refresh_count()
    await c.answer("🗑 Bekor qilindi")
    text, kb = await list_view()
    await show(c, text, kb)


@router.callback_query(F.data.regexp(r"^sc:now:\d+$"))
async def send_now(c: CallbackQuery):
    sid = int(c.data.split(":")[2])
    row = await db.pool.fetchrow(
        "UPDATE scheduled_posts SET status='sending' WHERE id=$1 AND status IN ('pending', 'failed') "
        "RETURNING id, movie_id, spec, created_by, clip_id, clip_kind",
        sid,
    )
    if not row:
        await c.answer("Allaqachon yuborilgan", show_alert=True)
        return
    await c.answer("Yuborilmoqda...")
    err = await send_claimed(c.bot, row, notify=False)
    await refresh_count()
    if err:
        await c.answer(f"❌ {err}"[:190], show_alert=True)
    text, kb = await list_view()
    await show(c, text, kb)


# ---------------- hozir joylash (admin.py dagisidan oldin turadi) ----------------
async def post_now(bot: Bot, movie_id: int, spec: str, clip=None) -> str:
    """Kanalga joylaydi. Video bor bo'lsa shu video bilan, bo'lmasa poster bilan. Video yuborilmasa izoh qaytaradi."""
    channel = db.get_setting("ann_channel")
    if not channel:
        raise RuntimeError("E'lon kanali belgilanmagan")
    caption, kb, poster = await admin.build_post(movie_id, spec)
    note = ""
    if clip and clip[0]:
        try:
            send = bot.send_animation if clip[1] == "animation" else bot.send_video
            await send(int(channel), clip[0], caption=caption, reply_markup=kb, parse_mode="HTML")
            return ""
        except Exception as e:
            logging.warning("Videoni kanalga yuborib bo'lmadi: %s", e)
            note = f"video yuborilmadi ({str(e)[:80]}), poster bilan joylandi"
    if poster:
        await bot.send_photo(int(channel), poster, caption=caption, reply_markup=kb, parse_mode="HTML")
    else:
        await bot.send_message(int(channel), caption, reply_markup=kb, parse_mode="HTML")
    return note


@router.callback_query(F.data.regexp(rf"^a:ak:\d+:{SPEC}$"))
async def announce_send(c: CallbackQuery):
    _, _, movie_id, spec = c.data.split(":")
    movie_id = int(movie_id)
    if not await need_channel(c):
        return
    try:
        note = await post_now(c.bot, movie_id, spec, _clip.get((movie_id, spec)))
    except Exception as e:
        await c.answer(f"Joylab bo'lmadi: {e}"[:190], show_alert=True)
        return
    _clip.pop((movie_id, spec), None)
    await c.answer(("⚠️ " + note) if note else "✅ Kanalga joylandi", show_alert=bool(note))
    await admin.open_page(c, movie_id)


async def tell(bot: Bot, uid, text: str):
    if not uid:
        return
    try:
        await bot.send_message(uid, text, parse_mode="HTML", reply_markup=kb_of([[btn("⏰ Rejalar", "sc:list")]]))
    except Exception as e:
        logging.warning("Reja xabarini yuborib bo'lmadi: %s", e)


async def send_claimed(bot: Bot, row, notify: bool = True):
    """Band qilingan rejani yuboradi. Xato bo'lsa matnini qaytaradi."""
    sid = row["id"]
    movie = await db.get_movie(row["movie_id"])
    title = escape(movie["title"]) if movie else str(row["movie_id"])
    clip = (row["clip_id"], row["clip_kind"] or "video") if row["clip_id"] else None
    try:
        note = await post_now(bot, row["movie_id"], row["spec"], clip)
    except Exception as e:
        err = str(e)[:300]
        await db.pool.execute("UPDATE scheduled_posts SET status='failed', error=$2 WHERE id=$1", sid, err)
        if notify:
            await tell(bot, row["created_by"], f"❌ <b>Rejali post joylanmadi</b>\n🎬 {title}\n⚠️ {escape(err)}")
        return err
    await db.pool.execute(
        "UPDATE scheduled_posts SET status='sent', sent_at=now(), error=NULL, clip_id=NULL, clip_kind=NULL WHERE id=$1",
        sid,
    )
    if notify:
        extra = f"\n⚠️ {escape(note)}" if note else ""
        await tell(
            bot, row["created_by"],
            f"✅ <b>Rejali post kanalga joylandi</b>\n🎬 {title} — {escape(spec_label(row['spec']))}{extra}",
        )
    return None


async def worker(bot: Bot):
    """Har 20 soniyada vaqti kelgan postlarni kanalga joylaydi."""
    while True:
        try:
            rows = await db.pool.fetch(
                "UPDATE scheduled_posts SET status='sending' WHERE id IN ("
                "SELECT id FROM scheduled_posts WHERE status='pending' AND run_at <= now() "
                "ORDER BY run_at LIMIT 5 FOR UPDATE SKIP LOCKED) "
                "RETURNING id, movie_id, spec, created_by, clip_id, clip_kind"
            )
            for row in rows:
                await send_claimed(bot, row)
                await asyncio.sleep(1)
            if rows:
                await refresh_count()
        except Exception as e:
            logging.warning("Reja xodimi xatosi: %s", e)
        await asyncio.sleep(20)
