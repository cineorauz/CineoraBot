import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InputMediaPhoto, Message, ReplyKeyboardRemove

# Har foydalanuvchi uchun bitta "ekran" xabari: user_id -> (message_id, rasmlimi)
_screens: dict[int, tuple[int, bool]] = {}
_back: dict[int, str] = {}
_query: dict[int, str] = {}
_cleaned: set[int] = set()
_invoices: dict[int, int] = {}


def set_back(uid: int, route: str):
    _back[uid] = route


def get_back(uid: int) -> str:
    return _back.get(uid, "home")


def set_query(uid: int, q: str):
    _query[uid] = q


def get_query(uid: int) -> str:
    return _query.get(uid, "")


def set_invoice(uid: int, message_id: int):
    _invoices[uid] = message_id


def pop_invoice(uid: int):
    return _invoices.pop(uid, None)


async def delete_message(msg: Message):
    try:
        await msg.delete()
    except Exception:
        pass


async def delete_id(bot: Bot, chat_id: int, message_id: int):
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass


async def flash(bot: Bot, chat_id: int, text: str, seconds: int = 4):
    """Qisqa ogohlantirish yuboradi va bir necha soniyadan keyin o'zi o'chadi."""
    try:
        msg = await bot.send_message(chat_id, text, parse_mode="HTML")
    except Exception:
        return

    async def _later():
        await asyncio.sleep(seconds)
        await delete_id(bot, chat_id, msg.message_id)

    asyncio.create_task(_later())


async def remove_reply_kb(bot: Bot, chat_id: int, uid: int):
    """Eski pastki menyuni (reply keyboard) bir marta yo'qotadi."""
    if uid in _cleaned:
        return
    _cleaned.add(uid)
    try:
        tmp = await bot.send_message(chat_id, "⏳", reply_markup=ReplyKeyboardRemove())
        await tmp.delete()
    except Exception:
        pass


def _remember(uid: int, msg):
    if isinstance(msg, Message):
        _screens[uid] = (msg.message_id, bool(msg.photo))


async def show(
    bot: Bot,
    chat_id: int,
    uid: int,
    text: str,
    kb=None,
    *,
    photo=None,
    source: Message | None = None,
    keep_photo: bool = False,
    force_new: bool = False,
):
    """Ekranni ko'rsatadi: imkon bo'lsa mavjud xabarni tahrirlaydi, bo'lmasa eskisini o'chirib yangisini yuboradi.
    force_new=True bo'lsa har doim yangi xabar eng pastga yuboriladi (eskisi keyin o'chiriladi)."""
    if source is not None:
        cur_id, cur_photo = source.message_id, bool(source.photo)
    else:
        cur_id, cur_photo = _screens.get(uid, (None, False))

    if cur_id and not force_new:
        try:
            if photo and cur_photo:
                res = await bot.edit_message_media(
                    media=InputMediaPhoto(media=photo, caption=text, parse_mode="HTML"),
                    chat_id=chat_id,
                    message_id=cur_id,
                    reply_markup=kb,
                )
                _screens[uid] = (cur_id, True)
                return res if isinstance(res, Message) else None
            if not photo and cur_photo and keep_photo:
                res = await bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=cur_id,
                    caption=text,
                    reply_markup=kb,
                    parse_mode="HTML",
                )
                _screens[uid] = (cur_id, True)
                return res if isinstance(res, Message) else None
            if not photo and not cur_photo:
                res = await bot.edit_message_text(
                    text,
                    chat_id=chat_id,
                    message_id=cur_id,
                    reply_markup=kb,
                    parse_mode="HTML",
                )
                _screens[uid] = (cur_id, False)
                return res if isinstance(res, Message) else None
        except TelegramBadRequest as e:
            if "not modified" in str(e).lower():
                _screens[uid] = (cur_id, cur_photo)
                return None
            logging.info("Tahrirlab bo'lmadi, yangi xabar yuboriladi: %s", e)
        await delete_id(bot, chat_id, cur_id)
        cur_id = None

    sent = None
    if photo:
        try:
            sent = await bot.send_photo(chat_id, photo, caption=text, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            logging.warning("Rasm yuborib bo'lmadi: %s", e)
    if sent is None:
        sent = await bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")
    _remember(uid, sent)
    if force_new and cur_id:
        await delete_id(bot, chat_id, cur_id)
    return sent


async def show_for(target, text: str, kb=None, *, photo=None, keep_photo: bool = False):
    """show() ning qisqa varianti: Message yoki CallbackQuery bilan ishlaydi."""
    if isinstance(target, CallbackQuery):
        msg, uid, source = target.message, target.from_user.id, target.message
    else:
        msg, uid, source = target, target.from_user.id, None
    return await show(
        msg.bot, msg.chat.id, uid, text, kb, photo=photo, source=source, keep_photo=keep_photo
    )
