from utils import btn

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
        "res": "🔎 <b>{q}</b>\n✅ botda bor • ⏳ hali yuklanmagan",
        "list_head": "{title}\n<i>{p}/{pages} • {total} ta</i>",
        "sort_btn": "↕️ {name}",
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
        "res": "🔎 <b>{q}</b>\n✅ in the bot • ⏳ not uploaded yet",
        "list_head": "{title}\n<i>{p}/{pages} • {total}</i>",
        "sort_btn": "↕️ {name}",
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
        "res": "🔎 <b>{q}</b>\n✅ есть в боте • ⏳ ещё не загружено",
        "list_head": "{title}\n<i>{p}/{pages} • {total}</i>",
        "sort_btn": "↕️ {name}",
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


def item_label(r, extra: str = "", prefix: str = "") -> str:
    """Ro'yxat tugmasi: [📺] Nom • o'zbekcha nom (yil) ⭐8.7 [💎]."""
    name = r["title"]
    uz = _get(r, "title_uz")
    if uz and uz.strip().lower() != name.strip().lower() and len(name) + len(uz) <= 24:
        name = f"{name} • {uz}"
    tail = f" ({r['year']})" if r["year"] else ""
    if r["imdb_rating"]:
        tail += " ⭐" + r["imdb_rating"].split("/")[0]
    elif r["rating"]:
        tail += f" ⭐{r['rating']:.1f}"
    icon = "📺 " if r["is_series"] else ""
    lock = " 💎" if r["is_premium"] else ""
    room = max(10, 46 - len(prefix) - len(icon) - len(tail) - len(lock) - len(extra))
    if len(name) > room:
        name = name[: room - 1].rstrip() + "…"
    return f"{prefix}{icon}{name}{tail}{lock}{extra}"


def pager_row(page: int, pages: int, make_cb) -> list:
    """[⬅️] [2/5] [➡️] qatori (bitta sahifa bo'lsa bo'sh)."""
    if pages <= 1:
        return []
    return [[
        btn("⬅️", make_cb(page - 1)) if page > 0 else btn("·", "noop"),
        btn(f"{page + 1}/{pages}", "noop"),
        btn("➡️", make_cb(page + 1)) if page + 1 < pages else btn("·", "noop"),
    ]]
