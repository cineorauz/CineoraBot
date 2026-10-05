import asyncio
import base64
import datetime as dt
import decimal
import gzip
import io
import json
import logging
import uuid

from aiogram import BaseMiddleware, F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, Message

import ai
import config
import database as db
import growth
import hub
import support
import ui
from utils import btn, kb_of

admin_router = Router()
admin_router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

SKIP_TABLES = {"ai_usage", "ai_global"}
LOG_TABLES = {"downloads_log": "created_at", "searches": "created_at"}   # faqat oxirgi 30 kun


class AiFlagGuard(BaseMiddleware):
    """Foydalanuvchi boshqa tugma yoki buyruq bossa, «AI uchun yozish» rejimi o'chadi (oddiy matn qidiruv bo'lib qoladi)."""

    async def __call__(self, handler, event, data):
        if isinstance(event, CallbackQuery):
            if not (event.data or "").startswith("ai:"):
                ai.cancel(event.from_user.id)
        elif isinstance(event, Message) and (event.text or "").startswith("/"):
            ai.cancel(event.from_user.id)
        return await handler(event, data)


# ---------------- zaxira nusxa ----------------
def _enc(o):
    if isinstance(o, (dt.datetime, dt.date)):
        return o.isoformat()
    if isinstance(o, decimal.Decimal):
        return str(o)
    if isinstance(o, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(o)).decode()
    if isinstance(o, uuid.UUID):
        return str(o)
    if isinstance(o, dt.timedelta):
        return o.total_seconds()
    if isinstance(o, (set, frozenset)):
        return list(o)
    return str(o)


async def make_backup():
    """Hamma jadvallar JSON qatorlari (.jsonl) ko'rinishida, gzip bilan siqilgan. (bayt, {jadval: qatorlar})"""
    names = [
        r["table_name"]
        for r in await db.pool.fetch(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY 1"
        )
    ]
    buf = io.BytesIO()
    counts = {}
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as gz:
        for name in names:
            if name in SKIP_TABLES:
                continue
            where = f" WHERE \"{LOG_TABLES[name]}\" > now() - interval '30 days'" if name in LOG_TABLES else ""
            rows = await db.pool.fetch(f'SELECT * FROM "{name}"{where}')
            counts[name] = len(rows)
            for r in rows:
                line = json.dumps({"t": name, "r": dict(r)}, default=_enc, ensure_ascii=False)
                gz.write((line + "\n").encode("utf-8"))
    return buf.getvalue(), counts


async def send_backup(bot, targets):
    data, counts = await make_backup()
    if len(data) > 49 * 1024 * 1024:
        for uid in targets:
            await bot.send_message(uid, "⚠️ Zaxira nusxa 50 MB dan katta, Telegram orqali yuborib bo'lmaydi.")
        return
    stamp = dt.datetime.now(growth.UZ).strftime("%Y%m%d-%H%M")
    caption = (
        f"💾 Zaxira nusxa • {len(data) / 1048576:.1f} MB\n"
        f"👥 {counts.get('users', 0)} • 🎬 {counts.get('movies', 0)} • 🎞 {counts.get('media_files', 0)}\n"
        "Faylni xavfsiz joyda saqlang."
    )
    for uid in targets:
        try:
            await bot.send_document(
                uid, BufferedInputFile(data, filename=f"cineora-backup-{stamp}.jsonl.gz"), caption=caption
            )
        except Exception as e:
            logging.warning("Zaxirani yuborib bo'lmadi (%s): %s", uid, e)


# ---------------- kunlik hisobot ----------------
async def build_report():
    p = db.pool
    u = await p.fetchrow(
        "SELECT count(*) AS total, "
        "count(*) FILTER (WHERE joined_at > now() - interval '1 day') AS new_d, "
        "count(*) FILTER (WHERE last_seen > now() - interval '1 day') AS act_d, "
        "count(*) FILTER (WHERE premium_until > now()) AS prem, "
        "count(*) FILTER (WHERE blocked) AS blocked FROM users"
    )
    views = await p.fetchval("SELECT count(*) FROM downloads_log WHERE created_at > now() - interval '1 day'")
    top = await p.fetch(
        "SELECT m.title, count(*) AS c FROM downloads_log l JOIN movies m ON m.id = l.movie_id "
        "WHERE l.created_at > now() - interval '1 day' GROUP BY m.title ORDER BY c DESC LIMIT 3"
    )
    miss = await p.fetch(
        "SELECT lower(q) AS q, count(*) AS c FROM searches "
        "WHERE created_at > now() - interval '1 day' AND NOT found GROUP BY lower(q) ORDER BY c DESC LIMIT 5"
    )
    reqs = await p.fetchval(
        "SELECT count(*) FROM (SELECT DISTINCT tmdb_type, tmdb_id FROM requests WHERE NOT notified) x"
    )
    ai_n = await p.fetchval("SELECT n FROM ai_global WHERE day = $1", dt.datetime.now(growth.UZ).date()) or 0
    from html import escape

    top_t = "\n".join(f"{i}. {escape(r['title'])} — {r['c']}" for i, r in enumerate(top, 1)) or "—"
    miss_t = "\n".join(f"• {escape(r['q'])} — {r['c']}" for r in miss) or "—"
    text = (
        f"📰 <b>Kunlik hisobot</b> • {dt.datetime.now(growth.UZ):%d.%m}\n\n"
        f"👥 Foydalanuvchilar: <b>{u['total']}</b> (🆕 +{u['new_d']} • 🟢 faol {u['act_d']})\n"
        f"💎 Premium: {u['prem']} • 🚫 botni bloklagan: {u['blocked']}\n"
        f"🎬 Ko'rishlar (24 soat): <b>{views}</b>\n\n"
        f"🔥 <b>Top:</b>\n{top_t}\n\n❓ <b>Topilmagan qidiruvlar:</b>\n{miss_t}\n\n"
        f"📥 Ochiq so'rovlar: {reqs} • 🆘 murojaatlar: {support.open_count()} • 🤖 AI bugun: {ai_n}"
    )
    kb = kb_of([[btn("📊 To'liq statistika", "at:stats"), btn("📥 So'rovlar", "a:reqs")]])
    return text, kb


async def send_report(bot, targets):
    text, kb = await build_report()
    for uid in targets:
        try:
            await bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            logging.warning("Hisobotni yuborib bo'lmadi (%s): %s", uid, e)


async def cron(bot):
    """Har daqiqa vaqtni tekshiradi: 04:00 zaxira, 09:00 hisobot (Toshkent), kuniga bir marta."""
    while True:
        await asyncio.sleep(60)
        try:
            now = dt.datetime.now(growth.UZ)
            today = now.strftime("%Y-%m-%d")
            if now.hour == 4 and db.get_setting("backup_on", "1") == "1" and db.get_setting("backup_last") != today:
                await db.set_setting("backup_last", today)
                await send_backup(bot, config.ADMIN_IDS)
            if now.hour == 9 and db.get_setting("report_on", "1") == "1" and db.get_setting("report_last") != today:
                await db.set_setting("report_last", today)
                await send_report(bot, config.ADMIN_IDS)
        except Exception as e:
            logging.warning("Kunlik vazifalar xatosi: %s", e)


# ---------------- admin paneldagi tugmalar (📈 O'sish ichida) ----------------
async def growth_rows():
    b = db.get_setting("backup_on", "1") == "1"
    r = db.get_setting("report_on", "1") == "1"
    return [
        [btn("💾 Zaxira: " + ("✅" if b else "⛔"), "op:bt"), btn("💾 Hozir", "op:bk")],
        [btn("📰 Hisobot: " + ("✅" if r else "⛔"), "op:rt"), btn("📰 Hozir", "op:rp")],
    ]


hub.GROWTH_ROWS.append(growth_rows)


@admin_router.callback_query(F.data.regexp(r"^op:(bt|rt)$"))
async def toggle(c: CallbackQuery):
    key = "backup_on" if c.data == "op:bt" else "report_on"
    await db.set_setting(key, "0" if db.get_setting(key, "1") == "1" else "1")
    await c.answer("✅")
    text, kb = await hub.growth_view()
    await ui.show_for(c, text, kb)


@admin_router.callback_query(F.data == "op:bk")
async def backup_now(c: CallbackQuery):
    await c.answer("Tayyorlanmoqda...")
    await send_backup(c.bot, [c.from_user.id])


@admin_router.callback_query(F.data == "op:rp")
async def report_now(c: CallbackQuery):
    await c.answer()
    await send_report(c.bot, [c.from_user.id])


def attach(dp):
    """bot.py chaqiradi: routerlar movies.router dan oldin ulanadi."""
    dp.callback_query.outer_middleware(AiFlagGuard())
    dp.message.outer_middleware(AiFlagGuard())
    dp.include_router(admin_router)
    dp.include_router(ai.router)


def start(bot):
    """bot.py chaqiradi: jadvallar va fon vazifalari."""
    asyncio.create_task(ai.init())
    asyncio.create_task(cron(bot))
