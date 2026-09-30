import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, ErrorEvent, Message
from aiohttp import web

import admin
import config
import database as db
import movies
import utils
from locales import t

logging.basicConfig(level=logging.INFO)
router = Router()


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
        await movies.send_card(m, m.from_user.id, lang, movie)
    else:
        await m.answer(t(lang, "welcome"), reply_markup=utils.menu_kb(lang))


@router.message(Command("lang"))
async def lang_cmd(m: Message):
    await m.answer(utils.LANG_PROMPT, reply_markup=utils.lang_kb())


@router.callback_query(F.data.startswith("lang:"))
async def pick_lang(c: CallbackQuery):
    parts = c.data.split(":")
    lang = parts[1]
    code = parts[2] if len(parts) > 2 else None
    await c.answer()
    await db.set_lang(c.from_user.id, lang)
    await c.message.delete()
    if await utils.gate(c.bot, c.from_user.id, lang, c.message):
        await c.message.answer(t(lang, "welcome"), reply_markup=utils.menu_kb(lang))
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
    await c.message.answer(t(lang, "welcome"), reply_markup=utils.menu_kb(lang))


async def on_error(event: ErrorEvent, bot: Bot):
    """Kutilmagan xatolarni adminlarga Telegramda yuboradi (Render Logs'ga kirmasdan ko'rish uchun)."""
    exc = event.exception
    logging.exception("Ishlov berishda xato", exc_info=exc)
    if isinstance(exc, TelegramForbiddenError):
        return True  # foydalanuvchi botni bloklagan
    if isinstance(exc, TelegramBadRequest) and (
        "not modified" in str(exc) or "query is too old" in str(exc)
    ):
        return True  # zararsiz xatolar (ikki marta bosish va h.k.)
    text = f"⚠️ Bot xatosi:\n{type(exc).__name__}: {exc}"[:3500]
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            pass
    return True


async def main():
    await db.init(config.DATABASE_URL)
    bot = Bot(config.BOT_TOKEN)
    me = await bot.get_me()
    utils.BOT_USERNAME = me.username

    dp = Dispatcher()
    dp.errors.register(on_error)
    dp.include_router(admin.router)   # avval admin
    dp.include_router(router)         # /start, /lang, obuna
    dp.include_router(movies.router)  # menyu, qidiruv, tugmalar (oxirida)

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
