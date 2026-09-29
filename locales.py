# Keyinchalik "qq" (qoraqalpoq) shu yerga qo'shiladi
LANGS = {"uz": "🇺🇿 O'zbekcha", "en": "🇬🇧 English", "ru": "🇷🇺 Русский"}

TEXTS = {
    "uz": {
        "sub_required": "Botdan foydalanish uchun kanallarga obuna bo'ling, so'ng «Tekshirish» tugmasini bosing 👇",
        "subscribe": "➕ Obuna bo'lish",
        "check": "✅ Tekshirish",
        "not_yet": "Siz hali hamma kanalga obuna bo'lmadingiz.",
        "welcome": "🎬 Cineora Botga xush kelibsiz!\n\nKino nomini yozing yoki kino kodini yuboring.",
        "search_soon": "🔎 Qidiruv tez orada qo'shiladi.",
    },
    "en": {
        "sub_required": "Please subscribe to the channels below, then press “Check” 👇",
        "subscribe": "➕ Subscribe",
        "check": "✅ Check",
        "not_yet": "You haven't subscribed to all channels yet.",
        "welcome": "🎬 Welcome to Cineora Bot!\n\nSend a movie title or a movie code.",
        "search_soon": "🔎 Search is coming soon.",
    },
    "ru": {
        "sub_required": "Подпишитесь на каналы ниже, затем нажмите «Проверить» 👇",
        "subscribe": "➕ Подписаться",
        "check": "✅ Проверить",
        "not_yet": "Вы ещё не подписались на все каналы.",
        "welcome": "🎬 Добро пожаловать в Cineora Bot!\n\nОтправьте название фильма или код фильма.",
        "search_soon": "🔎 Поиск скоро появится.",
    },
}


def t(lang: str, key: str) -> str:
    return TEXTS.get(lang, TEXTS["uz"])[key]
