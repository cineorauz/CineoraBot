# Keyinchalik "qq" (qoraqalpoq) shu yerga qo'shiladi
LANGS = {"uz": "🇺🇿 O'zbekcha", "en": "🇬🇧 English", "ru": "🇷🇺 Русский"}

TEXTS = {
    "uz": {
        "sub_required": "Botdan foydalanish uchun kanallarga obuna bo'ling, so'ng «Tekshirish» tugmasini bosing 👇",
        "subscribe": "➕ Obuna bo'lish",
        "check": "✅ Tekshirish",
        "not_yet": "Siz hali hamma kanalga obuna bo'lmadingiz.",
        "welcome": "🎬 Cineora Botga xush kelibsiz!\n\nKino nomini yozing yoki kino kodini yuboring.",
        "not_found": "😕 Hech narsa topilmadi.",
        "code": "Kod",
        "search_results": "🔎 Topilgan kinolar:",
        "fav_add": "⭐ Sevimlilarga qo'shish",
        "fav_remove": "❌ Sevimlilardan olib tashlash",
        "fav_added": "⭐ Sevimlilarga qo'shildi",
        "fav_removed": "Sevimlilardan olib tashlandi",
        "share": "📤 Ulashish",
        "favorites_title": "⭐ Sevimli kinolaringiz:",
        "favorites_empty": "Sevimlilar ro'yxati bo'sh.",
    },
    "en": {
        "sub_required": "Please subscribe to the channels below, then press “Check” 👇",
        "subscribe": "➕ Subscribe",
        "check": "✅ Check",
        "not_yet": "You haven't subscribed to all channels yet.",
        "welcome": "🎬 Welcome to Cineora Bot!\n\nSend a movie title or a movie code.",
        "not_found": "😕 Nothing found.",
        "code": "Code",
        "search_results": "🔎 Found movies:",
        "fav_add": "⭐ Add to favorites",
        "fav_remove": "❌ Remove from favorites",
        "fav_added": "⭐ Added to favorites",
        "fav_removed": "Removed from favorites",
        "share": "📤 Share",
        "favorites_title": "⭐ Your favorite movies:",
        "favorites_empty": "Your favorites list is empty.",
    },
    "ru": {
        "sub_required": "Подпишитесь на каналы ниже, затем нажмите «Проверить» 👇",
        "subscribe": "➕ Подписаться",
        "check": "✅ Проверить",
        "not_yet": "Вы ещё не подписались на все каналы.",
        "welcome": "🎬 Добро пожаловать в Cineora Bot!\n\nОтправьте название фильма или код фильма.",
        "not_found": "😕 Ничего не найдено.",
        "code": "Код",
        "search_results": "🔎 Найденные фильмы:",
        "fav_add": "⭐ В избранное",
        "fav_remove": "❌ Убрать из избранного",
        "fav_added": "⭐ Добавлено в избранное",
        "fav_removed": "Убрано из избранного",
        "share": "📤 Поделиться",
        "favorites_title": "⭐ Ваши избранные фильмы:",
        "favorites_empty": "Список избранного пуст.",
    },
}


def t(lang: str, key: str) -> str:
    return TEXTS.get(lang, TEXTS["uz"])[key]
