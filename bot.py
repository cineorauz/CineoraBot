import asyncio
import logging

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, BotCommandScopeChat, CallbackQuery, ErrorEvent, Message
from aiohttp import web

import admin
import admin_premium
import admin_titles
import admin_tools
import config
import database as db
import db_extra
import inline
import movies
import premium
import scheduler
import support
import titles
import ui
import utils
from locales import t

logging.basicConfig(level=logging.INFO)
router = Router()

# ---------------- bot profili (BotFather'dagi matnlar) ----------------
DESC = {
    "uz": (
        "🎬 Cineora — kino, serial, anime va dramalar dunyosi.\n\n"
        "🔎 Nomini yozing — men topib beraman (o'zbekcha nom ham bo'ladi)\n"
        "🎙 O'zbekcha ovozda, HD sifatda\n"
        "⭐ Baholang, ro'yxat tuzing, yangi qismlardan xabardor bo'ling\n"
        "💎 Premium — yopiq premyeralar\n\n"
        "Boshlash uchun START ni bosing 👇"
    ),
    "ru": (
        "🎬 Cineora — мир фильмов, сериалов, аниме и дорам.\n\n"
        "🔎 Напишите название — я найду (можно и на узбекском)\n"
        "🎙 Узбекская озвучка, HD-качество\n"
        "⭐ Оценивайте, составляйте списки, получайте уведомления о новых сериях\n"
        "💎 Premium — закрытые премьеры\n\n"
        "Нажмите START, чтобы начать 👇"
    ),
    "en": (
        "🎬 Cineora — your world of movies, series, anime and dramas.\n\n"
        "🔎 Type a title and I'll find it (Uzbek titles work too)\n"
        "🎙 Uzbek voice-over, HD quality\n"
        "⭐ Rate, build your watchlist, get new-episode alerts\n"
        "💎 Premium — exclusive premieres\n\n"
        "Press START to begin 👇"
    ),
}
SHORT = {
    "uz": "🎬 Kino, serial, anime va dramalar — o'zbekcha ovozda, HD sifatda. Nomini yozing, tomosha qiling!",
    "ru": "🎬 Фильмы, сериалы, аниме и дорамы в HD. Напишите название — и смотрите!",
    "en": "🎬 Movies, series, anime and dramas in HD. Type a title and start watching!",
}
CMDS = {
    "uz": [
        BotCommand(command="start", description="🏠 Bosh menyu"),
        BotCommand(command="premium", description="💎 Premium"),
        BotCommand(command="help", description="🆘 Yordam"),
        BotCommand(command="lang", description="🌐 Til / Language"),
    ],
    "ru": [
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="premium", description="💎 Premium"),
        BotCommand(command="help", description="🆘 Помощь"),
        BotCommand(command="lang", description="🌐 Язык / Language"),
    ],
    "en": [
        BotCommand(command="start", description="🏠 Main menu"),
        BotCommand(command="premium", description="💎 Premium"),
        BotCommand(command="help", description="🆘 Help"),
        BotCommand(command="lang", description="🌐 Language"),
    ],
}


async def setup_profile(bot: Bot):
    """Bot tavsifi, qisqa tavsif (About) va buyruqlarni uch tilda o'rnatadi (har ishga tushganda yangilanadi)."""
    for code in ("uz", "ru", "en", None):
        lang = code or "uz"  # tilsiz (standart) variant o'zbekcha
        try:
            await bot.set_my_description(description=DESC[lang], language_code=code)
            await bot.set_my_short_description(short_description=SHORT[lang], language_code=code)
            await bot.set_my_commands(CMDS[lang], language_code=code)
        except Exception as e:
            logging.warning("Bot profilini o'rnatib bo'lmadi (%s): %s", code, e)
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.set_my_commands(
                CMDS["uz"] + [BotCommand(command="admin", description="🛠 Admin panel")],
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception as e:
            logging.warning("Admin buyruqlarini o'rnatib bo'lmadi (%s): %s", admin_id, e)


class Activity(BaseMiddleware):
    """Faollikni eslab qoladi; bloklangan foydalanuvchilarni, texnik ishlar rejimini va yordam rejimini boshqaradi."""

    async def __call__(self, handler, event, data):
        db.mark_active()
        user = data.get("event_from_user")
        if user:
            db_extra.touch(user.id)
            cq = getattr(event, "callback_query", None)
            state = data.get("state")
            # Yordam yozish rejimida boshqa tugma bosilsa, rejim o'chadi (matn qidiruv bo'lib ketmasligi uchun)
            if cq is not None and state is not None and not (cq.data or "").startswith("sp:"):
                cur = await state.get_state()
                if cur and cur.startswith("Support"):
                    await state.clear()
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
async def start(m: Message, command: CommandObject, state: FSMContext):
    await state.clear()
    uid = m.from_user.id
    ui.forget(uid)  # chat tozalangan bo'lsa ham yangi ekran yuboriladi (eski xabar tahrirlanmaydi)
    await db.add_user(uid)
    db_extra.set_profile(uid, m.from_user.first_name, m.from_user.username)  # ism, username; blok belgisi tozalanadi
    lang = await db.get_lang(uid)
    code = command.args
    await ui.delete_message(m)
    await ui.remove_reply_kb(m.bot, m.chat.id, uid)  # eski pastki menyu bo'lsa yo'qotiladi
    if not lang:
        await ui.show(m.bot, m.chat.id, uid, utils.LANG_PROMPT, utils.lang_kb(code or ""))
        return
    utils.set_pending(uid, None)
    if not await utils.gate(m.bot, uid, lang, m):
        utils.set_pending(uid, code)  # obunadan keyin shu kino ochiladi
        return
    movie = await db.get_movie_by_code(code) if code else None
    if movie:
        ui.set_back(uid, "home")
        await movies.render_card(m.bot, m.chat.id, uid, lang, movie)
    else:
        await utils.show_home(m.bot, m.chat.id, uid, lang, name=m.from_user.first_name or "")


@router.message(Command("lang"))
async def lang_cmd(m: Message, state: FSMContext):
    await state.clear()
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
        utils.set_pending(uid, code)
        return
    movie = await db.get_movie_by_code(code) if code else None
    if movie:
        await movies.render_card(c.bot, c.message.chat.id, uid, lang, movie, c.message)
    else:
        await utils.show_home(c.bot, c.message.chat.id, uid, lang, c.message, name=c.from_user.first_name or "")


@router.callback_query(F.data == "check_sub")
async def check_sub(c: CallbackQuery):
    """«Tekshirish»: ekran shu joyda yangilanadi (faqat qolgan kanallar), hammasi bo'lsa menyu ochiladi."""
    uid = c.from_user.id
    lang = await db.get_lang(uid) or "uz"
    st = utils.SUB_T.get(lang, utils.SUB_T["uz"])
    missing = await utils.missing_channels(c.bot, uid, use_cache=False)
    if missing:
        await c.answer(st["left"].format(n=len(missing)))
        await utils.show_gate(c.bot, c.message.chat.id, uid, lang, missing, source=c.message)
        return
    await c.answer(st["joined"])
    await utils.gate_done(c.bot, c.message.chat.id, uid, lang, source=c.message)


async def open_pending(bot: Bot, chat_id: int, uid: int, lang: str, movie, source):
    """Obunadan keyin havola orqali kelgan kino ochiladi."""
    ui.set_back(uid, "home")
    await movies.render_card(bot, chat_id, uid, lang, movie, source)


async def on_error(event: ErrorEvent, bot: Bot):
    """Kutilmagan xatolarni adminlarga yuboradi; tugma «qotib» qolmasligi uchun foydalanuvchiga ham bildiradi."""
    exc = event.exception
    logging.exception("Ishlov berishda xato", exc_info=exc)
    if isinstance(exc, TelegramForbiddenError):
        return True  # foydalanuvchi botni bloklagan
    if isinstance(exc, TelegramBadRequest) and (
        "not modified" in str(exc) or "query is too old" in str(exc)
    ):
        return True
    cq = getattr(event.update, "callback_query", None)
    if cq is not None:
        try:
            await cq.answer("⚠️ Xatolik yuz berdi. Qayta urinib ko'ring.")
        except Exception:
            pass
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
    await support.init()
    await titles.init()
    await scheduler.init()
    bot = Bot(config.BOT_TOKEN)
    me = await bot.get_me()
    utils.BOT_USERNAME = me.username
    utils.GATE_OPEN = open_pending

    await setup_profile(bot)

    dp = Dispatcher()
    dp.update.outer_middleware(Activity())
    dp.errors.register(on_error)
    dp.include_router(admin_tools.router)    # yangi admin sahifa va asboblar (admin.py dan oldin turishi shart)
    dp.include_router(admin_titles.router)   # o'zbekcha 2-nom (admin.py ga ulanadi, uning handlerlaridan oldin turadi)
    dp.include_router(scheduler.router)      # kanalga e'lon: hozir yoki vaqtga qo'yib (admin.py dagi e'lon oynasini almashtiradi)
    dp.include_router(support.admin_router)  # yordam: admin tomoni
    dp.include_router(admin.router)          # admin: kontent
    dp.include_router(admin_premium.router)  # admin: premium
    dp.include_router(premium.router)        # premium, profil, to'lovlar
    dp.include_router(support.user_router)   # yordam: foydalanuvchi tomoni
    dp.include_router(inline.router)         # inline rejim (@bot nom)
    dp.include_router(router)                # /start, /lang, obuna
    dp.include_router(movies.router)         # qidiruv, kartochkalar, bo'limlar (oxirida)

    asyncio.create_task(keepalive())
    asyncio.create_task(seen_flusher())
    asyncio.create_task(premium.watcher(bot))
    asyncio.create_task(scheduler.worker(bot))

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
