from html import escape

from locales import t
from utils import btn, grid

U = {
    "uz": {
        "home_hello": "👋 Salom, <b>{name}</b>!",
        "home_menu": "🏠 <b>Bosh menyu</b>",
        "home_hint": "Kino, serial yoki anime nomini yozing 👇",
        "b_ai": "✨ Maslahat", "b_lib": "🔖 Ro'yxat", "b_profile": "👤 Profil",
        "b_coll": "📚 To'plamlar", "b_invite": "👥 Do'st taklif qilish",
        "save": "🔖 Saqlash", "saved": "✅ Saqlangan", "rate": "⭐ Baholash", "more": "⋯ Yana",
        "similar": "🎯 O'xshashlar", "report": "🚩 Shikoyat",
        "t_saved": "🔖 Saqlandi", "t_unsaved": "Olib tashlandi",
        "tab_saved": "🔖 Saqlangan", "tab_hist": "👁 Ko'rilgan",
        "lib_saved": "🔖 <b>Saqlanganlar</b>", "lib_hist": "👁 <b>Ko'rilganlar</b>",
        "empty_saved": "🔖 Hali hech narsa saqlanmagan.\n\nKartochkadagi «Saqlash» tugmasini bosing.",
        "empty_hist": "👁 Siz hali hech narsa ko'rmagansiz.",
        "co_title": "📚 <b>To'plamlar</b>\nTanlang 👇",
        "co_empty": "📚 Hozircha to'plamlar yo'q.",
        "prof": "👤 <b>Profil</b>\n\n💎 Premium: {prem}\n👥 Do'stlar: {refs}\n🆔 <code>{uid}</code>",
        "ref": (
            "👥 <b>Do'stlarni taklif qiling</b>\n\nHavolangiz orqali kirgan do'stingiz birinchi videoni ko'rgach, "
            "sizga <b>+{days} kun Premium</b> beriladi.\n\n🔗 <code>{link}</code>\n\n"
            "Taklif qilinganlar: <b>{total}</b> • mukofot olingan: <b>{ok}</b> (+{earned} kun)"
        ),
        "ref_share": "🎬 Cineora — kino, serial va anime o'zbekcha! Qo'shiling:",
        "ref_send": "📨 Do'stlarga yuborish",
        "ref_reward": "🎁 Do'stingiz botdan foydalandi: <b>+{days} kun Premium</b>!",
        "rep_title": "🚩 <b>Shikoyat</b>\n\n<b>{title}</b> bo'yicha nima muammo?",
        "rep_file": "🎞 Fayl ishlamayapti", "rep_quality": "🌐 Tarjima / sifat xato", "rep_legal": "⚖️ Huquqbuzarlik",
        "rep_thanks": "✅ Rahmat! Adminga yuborildi.",
        "limit": "🎟 Bugungi bepul limit tugadi ({n}/{n}). 💎 Premium — cheksiz, yoki do'stlarni taklif qilib Premium kunlari oling (Profil).",
    },
    "en": {
        "home_hello": "👋 Hi, <b>{name}</b>!",
        "home_menu": "🏠 <b>Main menu</b>",
        "home_hint": "Type a movie, series or anime title 👇",
        "b_ai": "✨ Advisor", "b_lib": "🔖 My list", "b_profile": "👤 Profile",
        "b_coll": "📚 Collections", "b_invite": "👥 Invite friends",
        "save": "🔖 Save", "saved": "✅ Saved", "rate": "⭐ Rate", "more": "⋯ More",
        "similar": "🎯 Similar", "report": "🚩 Report",
        "t_saved": "🔖 Saved", "t_unsaved": "Removed",
        "tab_saved": "🔖 Saved", "tab_hist": "👁 Watched",
        "lib_saved": "🔖 <b>Saved</b>", "lib_hist": "👁 <b>Watched</b>",
        "empty_saved": "🔖 Nothing saved yet.\n\nTap “Save” on a movie card.",
        "empty_hist": "👁 You haven't watched anything yet.",
        "co_title": "📚 <b>Collections</b>\nPick one 👇",
        "co_empty": "📚 No collections yet.",
        "prof": "👤 <b>Profile</b>\n\n💎 Premium: {prem}\n👥 Friends: {refs}\n🆔 <code>{uid}</code>",
        "ref": (
            "👥 <b>Invite friends</b>\n\nWhen a friend joins via your link and watches their first video, "
            "you get <b>+{days} days of Premium</b>.\n\n🔗 <code>{link}</code>\n\n"
            "Invited: <b>{total}</b> • rewarded: <b>{ok}</b> (+{earned} days)"
        ),
        "ref_share": "🎬 Cineora — movies, series and anime in Uzbek! Join:",
        "ref_send": "📨 Send to friends",
        "ref_reward": "🎁 Your friend used the bot: <b>+{days} days of Premium</b>!",
        "rep_title": "🚩 <b>Report</b>\n\nWhat's wrong with <b>{title}</b>?",
        "rep_file": "🎞 File not working", "rep_quality": "🌐 Translation / quality issue", "rep_legal": "⚖️ Rights violation",
        "rep_thanks": "✅ Thanks! Sent to the admin.",
        "limit": "🎟 Today's free limit is used up ({n}/{n}). 💎 Premium is unlimited, or invite friends to earn Premium days (Profile).",
    },
    "ru": {
        "home_hello": "👋 Привет, <b>{name}</b>!",
        "home_menu": "🏠 <b>Главное меню</b>",
        "home_hint": "Напишите название фильма, сериала или аниме 👇",
        "b_ai": "✨ Совет", "b_lib": "🔖 Список", "b_profile": "👤 Профиль",
        "b_coll": "📚 Подборки", "b_invite": "👥 Пригласить друзей",
        "save": "🔖 Сохранить", "saved": "✅ Сохранено", "rate": "⭐ Оценить", "more": "⋯ Ещё",
        "similar": "🎯 Похожие", "report": "🚩 Жалоба",
        "t_saved": "🔖 Сохранено", "t_unsaved": "Удалено",
        "tab_saved": "🔖 Сохранённые", "tab_hist": "👁 Просмотрено",
        "lib_saved": "🔖 <b>Сохранённые</b>", "lib_hist": "👁 <b>Просмотренные</b>",
        "empty_saved": "🔖 Пока ничего не сохранено.\n\nНажмите «Сохранить» в карточке.",
        "empty_hist": "👁 Вы пока ничего не смотрели.",
        "co_title": "📚 <b>Подборки</b>\nВыберите 👇",
        "co_empty": "📚 Подборок пока нет.",
        "prof": "👤 <b>Профиль</b>\n\n💎 Premium: {prem}\n👥 Друзья: {refs}\n🆔 <code>{uid}</code>",
        "ref": (
            "👥 <b>Пригласите друзей</b>\n\nКогда друг зайдёт по вашей ссылке и посмотрит первое видео, "
            "вы получите <b>+{days} дн. Premium</b>.\n\n🔗 <code>{link}</code>\n\n"
            "Приглашено: <b>{total}</b> • награда получена: <b>{ok}</b> (+{earned} дн.)"
        ),
        "ref_share": "🎬 Cineora — фильмы, сериалы и аниме на узбекском! Присоединяйтесь:",
        "ref_send": "📨 Отправить друзьям",
        "ref_reward": "🎁 Ваш друг воспользовался ботом: <b>+{days} дн. Premium</b>!",
        "rep_title": "🚩 <b>Жалоба</b>\n\nЧто не так с <b>{title}</b>?",
        "rep_file": "🎞 Файл не работает", "rep_quality": "🌐 Ошибка перевода / качества", "rep_legal": "⚖️ Нарушение прав",
        "rep_thanks": "✅ Спасибо! Отправлено админу.",
        "limit": "🎟 Бесплатный лимит на сегодня исчерпан ({n}/{n}). 💎 Premium — без ограничений, или приглашайте друзей за дни Premium (Профиль).",
    },
}


def u(lang: str, key: str) -> str:
    return U.get(lang, U["uz"]).get(key) or U["uz"][key]


def _get(r, key):
    try:
        return r[key]
    except (KeyError, IndexError):
        return None


def _short(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def plain_label(r) -> str:
    """Raqamli ro'yxat qatori: [📺] Nom • o'zbekcha nom (yil) ⭐8.7 [💎]. HTML uchun xavfsiz."""
    name = _short(r["title"], 34)
    uz = _get(r, "title_uz")
    if uz and uz.strip().lower() != r["title"].strip().lower():
        name += f" • {_short(uz, 24)}"
    tail = f" ({r['year']})" if r["year"] else ""
    if r["imdb_rating"]:
        tail += " ⭐" + r["imdb_rating"].split("/")[0]
    elif r["rating"]:
        tail += f" ⭐{r['rating']:.1f}"
    icon = "📺 " if _get(r, "is_series") else ""
    lock = " 💎" if r["is_premium"] else ""
    return f"{icon}{escape(name)}{tail}{lock}"


def numbered(lines: list, entries: list, start: int = 1):
    """Raqamli matn va 5 tadan raqam tugmalari. entries: [callback_data]"""
    text = "\n".join(f"{start + i}. {line}" for i, line in enumerate(lines))
    return text, grid([btn(str(start + i), cb) for i, cb in enumerate(entries)], 5)


def page_nav(lang: str, make_cb, page: int, pages: int) -> list:
    """[◀️ Oldingi] [Keyingi ▶️] qatori."""
    nav = []
    if page > 0:
        nav.append(btn(t(lang, "prev"), make_cb(page - 1)))
    if page + 1 < pages:
        nav.append(btn(t(lang, "next"), make_cb(page + 1)))
    return nav
