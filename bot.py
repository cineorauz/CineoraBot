import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiohttp import web

import config
import database as db
from locales import LANGS, t

logging.basicConfig(level=logging.INFO)
router = Router()

LANG_PROMPT = "🌐 Tilni tanlang / Choose language / Выберите язык"


def lang_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=n, callback_data=f"lang:{c}")] for c, n in LANGS.items()]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def sub_kb(lang: str, missing: list[str]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{t(lang, 'subscribe')} {ch}", url=f"https://t.me/{ch.lstrip('@')}")]
        for ch in missing
    ]
    rows.append([InlineKeyboardButton(text=t(lang, "check"), callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def missing_channels(bot: Bot, user_id: int) -> list[str]:
    missing = []
    for ch in config.CHANNELS:
        try:
            m = await bot.get_chat_member(ch, user_id)
            if m.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
                missing.append(ch)
        except Exception as e:  # bot kanalda admin emas yoki kanal topilmadi
            logging.warning("Obunani tekshirib bo'lmadi (%s): %s", ch, e)
    return missing


async def gate(bot: Bot, user_id: int, lang: str, msg: Message) -> bool:
    """Obuna bo'lsa True, bo'lmasa obuna xabarini yuboradi va False qaytaradi."""
    missing = await missing_channels(bot, user_id)
    if missing:
        await msg.answer(t(lang, "sub_required"), reply_markup=sub_kb(lang, missing))
        return False
    return True


@router.message(CommandStart())
async def start(m: Message):
    await db.add_user(m.from_user.id)
    lang = await db.get_lang(m.from_user.id)
    if not lang:
        await m.answer(LANG_PROMPT, reply_markup=lang_kb())
        return
    if await gate(m.bot, m.from_user.id, lang, m):
        await m.answer(t(lang, "welcome"))


@router.message(Command("lang"))
async def lang_cmd(m: Message):
    await m.answer(LANG_PROMPT, reply_markup=lang_kb())


@router.callback_query(F.data.startswith("lang:"))
async def pick_lang(c: CallbackQuery):
    lang = c.data.split(":")[1]
    await db.set_lang(c.from_user.id, lang)
    await c.message.delete()
    if await gate(c.bot, c.from_user.id, lang, c.message):
        await c.message.answer(t(lang, "welcome"))
    await c.answer()


@router.callback_query(F.data == "check_sub")
async def check_sub(c: CallbackQuery):
    lang = await db.get_lang(c.from_user.id) or "uz"
    if await missing_channels(c.bot, c.from_user.id):
        await c.answer(t(lang, "not_yet"), show_alert=True)
        return
    await c.message.delete()
    await c.message.answer(t(lang, "welcome"))
    await c.answer()


@router.message(F.text & ~F.text.startswith("/"))
async def text_handler(m: Message):
    lang = await db.get_lang(m.from_user.id) or "uz"
    if not await gate(m.bot, m.from_user.id, lang, m):
        return
    await m.answer(t(lang, "search_soon"))  # 2-bosqichda TMDB qidiruvi shu yerga keladi


async def main():
    await db.init(config.DATABASE_URL)
    bot = Bot(config.BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

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
