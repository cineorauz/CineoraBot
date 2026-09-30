CATEGORIES = ["Kinolar", "Seriallar", "Animelar", "Dramalar", "Multfilmlar"]

# TMDB janr ID -> o'zbekcha nom
GENRE_UZ = {
    28: "Jangari",
    12: "Sarguzasht",
    16: "Animatsiya",
    35: "Komediya",
    80: "Kriminal",
    99: "Hujjatli",
    18: "Drama",
    10751: "Oilaviy",
    14: "Fentezi",
    36: "Tarixiy",
    27: "Qo'rqinchli",
    10402: "Musiqiy",
    9648: "Detektiv",
    10749: "Romantik",
    878: "Fantastika",
    10770: "Telefilm",
    53: "Triller",
    10752: "Urush",
    37: "Vestern",
    10759: "Jangari va sarguzasht",
    10762: "Bolalar",
    10763: "Yangiliklar",
    10764: "Realiti-shou",
    10765: "Fantastika va fentezi",
    10766: "Melodrama",
    10767: "Tok-shou",
    10768: "Urush va siyosat",
}

CATEGORY_LABELS = {
    "Kinolar": ("🎬", {"uz": "Kinolar", "en": "Movies", "ru": "Фильмы"}),
    "Seriallar": ("📺", {"uz": "Seriallar", "en": "Series", "ru": "Сериалы"}),
    "Animelar": ("🍥", {"uz": "Animelar", "en": "Anime", "ru": "Аниме"}),
    "Dramalar": ("🎭", {"uz": "Dramalar", "en": "Dramas", "ru": "Дорамы"}),
    "Multfilmlar": ("🧸", {"uz": "Multfilmlar", "en": "Cartoons", "ru": "Мультфильмы"}),
}

# hashtag -> (o'zbekcha, ruscha, inglizcha)
GENRE_LABELS = {
    "Action": ("Jangari", "Боевик", "Action"),
    "Adventure": ("Sarguzasht", "Приключения", "Adventure"),
    "Animation": ("Animatsiya", "Анимация", "Animation"),
    "Comedy": ("Komediya", "Комедия", "Comedy"),
    "Crime": ("Kriminal", "Криминал", "Crime"),
    "Documentary": ("Hujjatli", "Документальный", "Documentary"),
    "Drama": ("Drama", "Драма", "Drama"),
    "Family": ("Oilaviy", "Семейный", "Family"),
    "Fantasy": ("Fentezi", "Фэнтези", "Fantasy"),
    "History": ("Tarixiy", "Исторический", "History"),
    "Horror": ("Qo'rqinchli", "Ужасы", "Horror"),
    "Music": ("Musiqiy", "Музыка", "Music"),
    "Mystery": ("Detektiv", "Детектив", "Mystery"),
    "Romance": ("Romantik", "Мелодрама", "Romance"),
    "SciFi": ("Fantastika", "Фантастика", "Sci-Fi"),
    "TVMovie": ("Telefilm", "Телефильм", "TV Movie"),
    "Thriller": ("Triller", "Триллер", "Thriller"),
    "War": ("Urush", "Военный", "War"),
    "Western": ("Vestern", "Вестерн", "Western"),
    "Kids": ("Bolalar", "Детский", "Kids"),
    "News": ("Yangiliklar", "Новости", "News"),
    "Reality": ("Realiti-shou", "Реалити-шоу", "Reality"),
    "Soap": ("Melodrama", "Мыльная опера", "Soap"),
    "Talk": ("Tok-shou", "Ток-шоу", "Talk Show"),
    "Politics": ("Siyosat", "Политика", "Politics"),
}


def cat_icon(cat: str) -> str:
    return CATEGORY_LABELS.get(cat, ("📁", {}))[0]


def cat_label(cat: str, lang: str) -> str:
    return CATEGORY_LABELS.get(cat, ("", {}))[1].get(lang, cat)


def genre_label(tag: str, lang: str) -> str:
    entry = GENRE_LABELS.get(tag)
    if not entry:
        return tag
    return entry[{"uz": 0, "ru": 1}.get(lang, 2)]
