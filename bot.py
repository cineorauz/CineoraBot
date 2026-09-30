import asyncio
import logging
from html import escape

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, ErrorEvent, Message
from aiohttp import web

import admin
import admin_premium
import config
import database as db
import movies
import premium
import utils
from locales import t

logging.basicConfig(level=logging.INFO)
router = Router()


class Activity(BaseMiddleware):
    """Foydalanuvchilar faol ekanini eslab qoladi (bazani uyg'oq tutish uchun)."""

    async def __call__(self, handler, event, data):
        db.mark_active()
        return await handler(event, data)


@router.message(CommandStart())
async def start(m: Message, command: CommandObject):
    await db.add_user(m.from_user.id)
    lang = await db.get_lang(m.from_user.id)
    code = command.args
    if not lang:
        await m.answer(utils.LANG_PROMPT, reply_markup=utils.lang_kb(code or ""))
        return
    if not await utils.gate(m.bot, m.from_user.id, lang, m):
        return
    movie = await db.get_movie_by_code(code) if code else None
    if movie:
        await m.answer("🎬", reply_markup=utils.menu_kb(lang))
        await movies.send_card(m, m.from_user.id, lang, movie)
    else:
        await m.answer(
            t(lang, "welcome").format(name=escape(m.from_user.first_name or "")),
            reply_markup=utils.menu_kb(lang),
            parse_mode="HTML",
        )


@router.message(Command("lang"))
async def lang_cmd(m: Message):
    await m.answer(utils.LANG_PROMPT, reply_markup=utils.lang_kb())


@router.callback_query(F.data == "lang_open")
async def lang_open(c: CallbackQuery):
    await c.answer()
    await c.message.answer(utils.LANG_PROMPT, reply_markup=utils.lang_kb())


@router.callback_query(F.data.startswith("lang:"))
async def pick_lang(c: CallbackQuery):
    parts = c.data.split(":")
    lang = parts[1]
    code = parts[2] if len(parts) > 2 else None
    await c.answer()
    await db.set_lang(c.from_user.id, lang)
    await c.message.delete()
    if await utils.gate(c.bot, c.from_user.id, lang, c.message):
        await c.message.answer(
            t(lang, "welcome").format(name=escape(c.from_user.first_name or "")),
            reply_markup=utils.menu_kb(lang),
            parse_mode="HTML",
        )
        if code:
            movie = await db.get_movie_by_code(code)
            if movie:
                await movies.send_card(c.message, c.from_user.id, lang, movie)


@router.callback_query(F.data == "check_sub")
async def check_sub(c: CallbackQuery):
    lang = await db.get_lang(c.from_user.id) or "uz"
    if await utils.missing_channels(c.bot, c.from_user.id, use_cache=False):
        await c.answer(t(lang, "not_yet"), show_alert=True)
        return
    await c.answer()
    await c.message.delete()
    await c.message.answer(
        t(lang, "welcome").format(name=escape(c.from_user.first_name or "")),
        reply_markup=utils.menu_kb(lang),
        parse_mode="HTML",
    )


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


async def main():
    await db.init(config.DATABASE_URL)
    bot = Bot(config.BOT_TOKEN)
    me = await bot.get_me()
    utils.BOT_USERNAME = me.username

    dp = Dispatcher()
    dp.update.outer_middleware(Activity())
    dp.errors.register(on_error)
    dp.include_router(admin.router)          # admin: kontent
    dp.include_router(admin_premium.router)  # admin: premium
    dp.include_router(premium.router)        # premium, profil, to'lovlar
    dp.include_router(router)                # /start, /lang, obuna
    dp.include_router(movies.router)         # menyu, qidiruv, kartochkalar (oxirida)

    asyncio.create_task(keepalive())
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
