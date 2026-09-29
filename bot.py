import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiohttp import web

import admin
import config
import database as db
import movies
import utils
from locales import LANGS, t

logging.basicConfig(level=logging.INFO)
router = Router()

LANG_PROMPT = "🌐 Tilni tanlang / Choose language / Выберите язык"


def lang_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=n, callback_data=f"lang:{c}")] for c, n in LANGS.items()]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(CommandStart())
async def start(m: Message, command: CommandObject):
    await db.add_user(m.from_user.id)
    lang = await db.get_lang(m.from_user.id)
    if not lang:
        await m.answer(LANG_PROMPT, reply_markup=lang_kb())
        return
    if not await utils.gate(m.bot, m.from_user.id, lang, m):
        return
    args = command.args
    if args and args.startswith("m") and args[1:].isdigit():
        await movies.send_card(m, m.from_user.id, lang, int(args[1:]))
    else:
        await m.answer(t(lang, "welcome"))


@router.message(Command("lang"))
async def lang_cmd(m: Message):
    await m.answer(LANG_PROMPT, reply_markup=lang_kb())


@router.callback_query(F.data.startswith("lang:"))
async def pick_lang(c: CallbackQuery):
    lang = c.data.split(":")[1]
    await db.set_lang(c.from_user.id, lang)
    await c.message.delete()
    if await utils.gate(c.bot, c.from_user.id, lang, c.message):
        await c.message.answer(t(lang, "welcome"))
    await c.answer()


@router.callback_query(F.data == "check_sub")
async def check_sub(c: CallbackQuery):
    lang = await db.get_lang(c.from_user.id) or "uz"
    if await utils.missing_channels(c.bot, c.from_user.id):
        await c.answer(t(lang, "not_yet"), show_alert=True)
        return
    await c.message.delete()
    await c.message.answer(t(lang, "welcome"))
    await c.answer()


async def main():
    await db.init(config.DATABASE_URL)
    bot = Bot(config.BOT_TOKEN)
    me = await bot.get_me()
    utils.BOT_USERNAME = me.username

    dp = Dispatcher()
    dp.include_router(admin.router)   # avval admin
    dp.include_router(router)         # /start, /lang, obuna
    dp.include_router(movies.router)  # qidiruv, tugmalar (oxirida)

    # Render uchun kichik veb-server (UptimeRobot shu manzilni ping qiladi)
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Cineora Bot ishlayapti"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", config.PORT).start()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
