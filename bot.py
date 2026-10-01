import asyncio
import logging

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BotCommand, BotCommandScopeChat, CallbackQuery, ErrorEvent, Message
from aiohttp import web

import admin
import admin_premium
import admin_tools
import config
import database as db
import db_extra
import inline
import movies
import premium
import ui
import utils
from locales import t

logging.basicConfig(level=logging.INFO)
router = Router()


class Activity(BaseMiddleware):
    """Faollikni eslab qoladi; bloklangan foydalanuvchilarni va texnik ishlar rejimini boshqaradi."""

    async def __call__(self, handler, event, data):
        db.mark_active()
        user = data.get("event_from_user")
        if user:
            db_extra.touch(user.id)
            if user.id not in config.ADMIN_IDS:
                banned = db_extra.is_banned(user.id)
                maint = db.get_setting("maintenance") == "1"
                if banned or maint:
                    msg = getattr(event, "message", None)
                    if msg is not None and msg.successful_payment:
                        return await handler(event, data)  # to'lov yakunlanishi har doim ishlanadi
                    if getattr(event, "pre_checkout_query", None) is not None:
                        return await handler(event, data)
                    note = "🚫" if banned else "🛠 Texnik ishlar ketmoqda. Birozdan so'ng urinib ko'ring."
                    cq = getattr(event, "callback_query", None)
                    iq = getattr(event, "inline_query", None)
                    try:
                        if cq is not None:
                            await cq.answer(note, show_alert=True)
                        elif iq is not None:
                            await iq.answer([], cache_time=5)
                        elif msg is not None:
                            await msg.answer(note)
                    except Exception:
                        pass
                    return None
        return await handler(event, data)


@router.message(CommandStart())
async def start(m: Message, command: CommandObject):
    uid = m.from_user.id
    await db.add_user(uid)
    db_extra.set_profile(uid, m.from_user.first_name, m.from_user.username)  # ism, username; blok belgisi tozalanadi
    lang = await db.get_lang(uid)
    code = command.args
    await ui.delete_message(m)
    await ui.remove_reply_kb(m.bot, m.chat.id, uid)  # eski pastki menyu bo'lsa yo'qotiladi
    if not lang:
        await ui.show(m.bot, m.chat.id, uid, utils.LANG_PROMPT, utils.lang_kb(code or ""))
        return
    if not await utils.gate(m.bot, uid, lang, m):
        return
    movie = await db.get_movie_by_code(code) if code else None
    if movie:
        ui.set_back(uid, "home")
        await movies.render_card(m.bot, m.chat.id, uid, lang, movie)
    else:
        await utils.show_home(m.bot, m.chat.id, uid, lang, name=m.from_user.first_name or "")


@router.message(Command("lang"))
async def lang_cmd(m: Message):
    await ui.delete_message(m)
    await ui.show(m.bot, m.chat.id, m.from_user.id, utils.LANG_PROMPT, utils.lang_kb())


@router.callback_query(F.data == "lang_open")
async def lang_open(c: CallbackQuery):
    await c.answer()
    await ui.show_for(c, utils.LANG_PROMPT, utils.lang_kb())


@router.callback_query(F.data.startswith("lang:"))
async def pick_lang(c: CallbackQuery):
    parts = c.data.split(":")
    lang = parts[1]
    code = parts[2] if len(parts) > 2 else None
    uid = c.from_user.id
    await c.answer()
    await db.set_lang(uid, lang)
    if not await utils.gate(c.bot, uid, lang, c.message):
        return
    movie = await db.get_movie_by_code(code) if code else None
    if movie:
        await movies.render_card(c.bot, c.message.chat.id, uid, lang, movie, c.message)
    else:
        await utils.show_home(c.bot, c.message.chat.id, uid, lang, c.message, name=c.from_user.first_name or "")


@router.callback_query(F.data == "check_sub")
async def check_sub(c: CallbackQuery):
    uid = c.from_user.id
    lang = await db.get_lang(uid) or "uz"
    if await utils.missing_channels(c.bot, uid, use_cache=False):
        await c.answer(t(lang, "not_yet"), show_alert=True)
        return
    await c.answer()
    await utils.show_home(c.bot, c.message.chat.id, uid, lang, c.message, name=c.from_user.first_name or "")


async def on_error(event: ErrorEvent, bot: Bot):
    """Kutilmagan xatolarni adminlarga Telegramda yuboradi."""
    exc = event.exception
    logging.exception("Ishlov berishda xato", exc_info=exc)
    if isinstance(exc, TelegramForbiddenError):
        return True  # foydalanuvchi botni bloklagan
    if isinstance(exc, TelegramBadRequest) and (
        "not modified" in str(exc) or "query is too old" in str(exc)
    ):
        return True
    text = f"⚠️ Bot xatosi:\n{type(exc).__name__}: {exc}"[:3500]
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            pass
    return True


async def keepalive():
    """Foydalanuvchilar faol bo'lsa, bazani har 4 daqiqada 'uyg'otib' turadi (Neon uxlab qolmasligi uchun)."""
    while True:
        await asyncio.sleep(240)
        if db.recently_active():
            try:
                await db.ping()
            except Exception as e:
                logging.warning("Baza ping xatosi: %s", e)


async def seen_flusher():
    """Foydalanuvchilarning oxirgi faolligini har 5 daqiqada bazaga yozadi."""
    while True:
        await asyncio.sleep(300)
        try:
            await db_extra.flush_seen()
        except Exception as e:
            logging.warning("Faollikni yozib bo'lmadi: %s", e)


async def main():
    await db.init(config.DATABASE_URL)
    await db_extra.init()
    bot = Bot(config.BOT_TOKEN)
    me = await bot.get_me()
    utils.BOT_USERNAME = me.username

    commands = [
        BotCommand(command="start", description="🏠 Bosh menyu"),
        BotCommand(command="premium", description="💎 Premium"),
        BotCommand(command="lang", description="🌐 Til / Language"),
    ]
    await bot.set_my_commands(commands)
    # Adminlar uchun Menu tugmasida /admin ham ko'rinadi
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.set_my_commands(
                commands + [BotCommand(command="admin", description="🛠 Admin panel")],
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception as e:
            logging.warning("Admin buyruqlarini o'rnatib bo'lmadi (%s): %s", admin_id, e)

    dp = Dispatcher()
    dp.update.outer_middleware(Activity())
    dp.errors.register(on_error)
    dp.include_router(admin_tools.router)    # yangi admin sahifa va asboblar (admin.py dan oldin turishi shart)
    dp.include_router(admin.router)          # admin: kontent
    dp.include_router(admin_premium.router)  # admin: premium
    dp.include_router(premium.router)        # premium, profil, to'lovlar
    dp.include_router(inline.router)         # inline rejim (@bot nom)
    dp.include_router(router)                # /start, /lang, obuna
    dp.include_router(movies.router)         # qidiruv, kartochkalar, bo'limlar (oxirida)

    asyncio.create_task(keepalive())
    asyncio.create_task(seen_flusher())
    asyncio.create_task(premium.watcher(bot))

    # Render uchun kichik veb-server (UptimeRobot shu manzilni ping qiladi)
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Cineora Bot ishlayapti"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", config.PORT).start()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
