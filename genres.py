import re

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

# ISO kod -> (inglizcha hashtag, o'zbekcha, ruscha)
COUNTRIES = {
    "US": ("UnitedStates", "AQSH", "США"),
    "GB": ("UnitedKingdom", "Buyuk Britaniya", "Великобритания"),
    "CA": ("Canada", "Kanada", "Канада"),
    "FR": ("France", "Fransiya", "Франция"),
    "DE": ("Germany", "Germaniya", "Германия"),
    "IT": ("Italy", "Italiya", "Италия"),
    "ES": ("Spain", "Ispaniya", "Испания"),
    "JP": ("Japan", "Yaponiya", "Япония"),
    "KR": ("SouthKorea", "Janubiy Koreya", "Южная Корея"),
    "CN": ("China", "Xitoy", "Китай"),
    "HK": ("HongKong", "Gonkong", "Гонконг"),
    "TW": ("Taiwan", "Tayvan", "Тайвань"),
    "IN": ("India", "Hindiston", "Индия"),
    "RU": ("Russia", "Rossiya", "Россия"),
    "UA": ("Ukraine", "Ukraina", "Украина"),
    "TR": ("Turkey", "Turkiya", "Турция"),
    "UZ": ("Uzbekistan", "O'zbekiston", "Узбекистан"),
    "KZ": ("Kazakhstan", "Qozog'iston", "Казахстан"),
    "AU": ("Australia", "Avstraliya", "Австралия"),
    "NZ": ("NewZealand", "Yangi Zelandiya", "Новая Зеландия"),
    "IE": ("Ireland", "Irlandiya", "Ирландия"),
    "MX": ("Mexico", "Meksika", "Мексика"),
    "BR": ("Brazil", "Braziliya", "Бразилия"),
    "AR": ("Argentina", "Argentina", "Аргентина"),
    "SE": ("Sweden", "Shvetsiya", "Швеция"),
    "NO": ("Norway", "Norvegiya", "Норвегия"),
    "DK": ("Denmark", "Daniya", "Дания"),
    "FI": ("Finland", "Finlyandiya", "Финляндия"),
    "NL": ("Netherlands", "Niderlandiya", "Нидерланды"),
    "BE": ("Belgium", "Belgiya", "Бельгия"),
    "CH": ("Switzerland", "Shveytsariya", "Швейцария"),
    "AT": ("Austria", "Avstriya", "Австрия"),
    "PL": ("Poland", "Polsha", "Польша"),
    "CZ": ("CzechRepublic", "Chexiya", "Чехия"),
    "HU": ("Hungary", "Vengriya", "Венгрия"),
    "RO": ("Romania", "Ruminiya", "Румыния"),
    "GR": ("Greece", "Gretsiya", "Греция"),
    "PT": ("Portugal", "Portugaliya", "Португалия"),
    "IL": ("Israel", "Isroil", "Израиль"),
    "IR": ("Iran", "Eron", "Иран"),
    "EG": ("Egypt", "Misr", "Египет"),
    "ZA": ("SouthAfrica", "Janubiy Afrika", "ЮАР"),
    "TH": ("Thailand", "Tailand", "Таиланд"),
    "ID": ("Indonesia", "Indoneziya", "Индонезия"),
    "PH": ("Philippines", "Filippin", "Филиппины"),
    "VN": ("Vietnam", "Vetnam", "Вьетнам"),
    "SA": ("SaudiArabia", "Saudiya Arabistoni", "Саудовская Аравия"),
    "AE": ("UnitedArabEmirates", "BAA", "ОАЭ"),
}


def hashtag(name: str) -> str:
    return re.sub(r"[^\w]", "", name.replace(" ", ""))


def cat_icon(cat: str) -> str:
    return CATEGORY_LABELS.get(cat, ("📁", {}))[0]


def cat_label(cat: str, lang: str) -> str:
    return CATEGORY_LABELS.get(cat, ("", {}))[1].get(lang, cat)


def genre_label(tag: str, lang: str) -> str:
    entry = GENRE_LABELS.get(tag)
    if not entry:
        return tag
    return entry[{"uz": 0, "ru": 1}.get(lang, 2)]


def genre_tag(tag: str, lang: str) -> str:
    """Hashtag ko'rinishi: inglizcha uchun asl teg, boshqa tillarda tarjimasi."""
    if lang == "en":
        return tag
    return hashtag(genre_label(tag, lang))


def country_tag(code: str, lang: str) -> str:
    entry = COUNTRIES.get(code)
    if not entry:
        return code
    if lang == "ru":
        return hashtag(entry[2])
    if lang == "uz":
        return hashtag(entry[1])
    return entry[0]


def country_name(code: str, lang: str) -> str:
    entry = COUNTRIES.get(code)
    if not entry:
        return code
    return entry[{"uz": 1, "ru": 2}.get(lang, 0)]
