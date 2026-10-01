from html import escape
from urllib.parse import quote

import utils
from genres import country_name, country_tag, genre_label, genre_tag
from locales import t

# Kartochka tili: o'zbekcha tavsif Tilmoch tarjimasidan olinadi (bo'lmasa inglizcha tavsif chiqadi).
CARD_LANG = {"uz": "uz", "en": "en", "ru": "ru"}
LIMIT = 1024
DIV = "▬" * 14

# kod -> (o'zbekcha, ruscha, inglizcha)
AUDIO = {
    "uz": ("O'zbek tilida", "На узбекском", "In Uzbek"),
    "ru": ("Rus tilida", "На русском", "In Russian"),
    "en": ("Ingliz tilida", "На английском", "In English"),
    "orig": ("Original (subtitr bilan)", "Оригинал (субтитры)", "Original (subtitles)"),
}

L = {
    "uz": {
        "country": "Davlat", "audio": "Til", "quality": "Sifat", "seasons": "Fasllar",
        "episodes": "Qismlar", "genre": "Janr", "duration": "Davomiyligi",
        "age": "Yosh chegarasi", "director": "Rejissyor", "cast": "Aktyorlar",
        "downloads": "Yuklashlar", "h": "soat", "min": "daqiqa",
        "pick": "Sifatni tanlang:", "pick_season": "Faslni tanlang:",
        "na": "Hali yuklanmadi", "notify_hint": "Yuklanishi bilan sizga xabar beramiz",
        "lock": "Bu kontent faqat Premium obunachilar uchun",
        "users": "Foydalanuvchilar", "your": "Sizning bahoyingiz",
    },
    "en": {
        "country": "Country", "audio": "Language", "quality": "Quality", "seasons": "Seasons",
        "episodes": "Episodes", "genre": "Genre", "duration": "Duration",
        "age": "Age rating", "director": "Director", "cast": "Cast",
        "downloads": "Downloads", "h": "h", "min": "min",
        "pick": "Choose quality:", "pick_season": "Choose a season:",
        "na": "Not uploaded yet", "notify_hint": "We'll notify you as soon as it's added",
        "lock": "Premium members only",
        "users": "Users", "your": "Your rating",
    },
    "ru": {
        "country": "Страна", "audio": "Язык", "quality": "Качество", "seasons": "Сезоны",
        "episodes": "Серии", "genre": "Жанр", "duration": "Длительность",
        "age": "Возраст", "director": "Режиссёр", "cast": "В ролях",
        "downloads": "Загрузок", "h": "ч", "min": "мин",
        "pick": "Выберите качество:", "pick_season": "Выберите сезон:",
        "na": "Ещё не загружено", "notify_hint": "Сообщим, как только добавим",
        "lock": "Только для Premium",
        "users": "Пользователи", "your": "Ваша оценка",
    },
}

QBTN = {"2160": "🎞 4K", "1080": "🔥 1080p", "720": "✨ 720p", "480": "📺 480p", "360": "📱 360p"}


def audio_label(code, cl: str) -> str:
    entry = AUDIO.get(code or "uz")
    if not entry:
        return escape(str(code))
    return entry[{"uz": 0, "ru": 1}.get(cl, 2)]


def cert_emoji(cert: str) -> str:
    c = cert.upper()
    if c in ("G", "TV-Y", "TV-G", "TV-Y7"):
        return "🟢"
    if c in ("PG", "TV-PG"):
        return "🟡"
    if c in ("PG-13", "TV-14"):
        return "🟠"
    if c in ("R", "TV-MA", "NC-17"):
        return "🔴"
    return "⚪"


def fmt_duration(minutes, cl: str) -> str:
    h, m = divmod(int(minutes), 60)
    lb = L[cl]
    if h and m:
        return f"{h} {lb['h']} {m} {lb['min']}"
    if h:
        return f"{h} {lb['h']}"
    return f"{m} {lb['min']}"


def overview_for(m: dict, cl: str):
    if cl == "ru":
        return m.get("overview_ru") or m.get("overview_en")
    if cl == "uz":
        return m.get("overview_uz") or m.get("overview_en")
    return m.get("overview_en")  # inglizcha tavsif bo'lmasa, rus tilini ko'rsatmaymiz


def tagline_for(m: dict, cl: str):
    if cl == "ru":
        return m.get("tagline_ru") or m.get("tagline_en")
    if cl == "uz":
        return m.get("tagline_uz") or m.get("tagline_en")
    return m.get("tagline_en")


def card_text(m: dict, lang: str, avail=None, locked: bool = False) -> str:
    """avail: None — ko'rsatilmaydi, False — yuklanmagan, list — kino sifatlari, dict — serial fasllari."""
    cl = CARD_LANG.get(lang, "en")
    lb = L[cl]
    title = (m.get("title_ru") if cl == "ru" else None) or m.get("title") or "?"
    head = f"🎬 <b>{escape(title)}</b>"
    if m.get("year"):
        head += f" ({m['year']})"
    if m.get("is_premium"):
        head += "  💎"
    core = [head]
    tagline = tagline_for(m, cl)
    if tagline:
        core.append(f"<i>{escape(tagline)}</i>")
    core.append(DIV)

    must = []
    codes = m.get("country_codes") or []
    countries = [country_tag(c, cl) for c in codes] if codes else list(m.get("countries") or [])
    if countries:
        must.append(f"🌍 <b>{lb['country']}:</b> " + " ".join("#" + c for c in countries))
    if isinstance(avail, list) and avail:
        must.append(f"🎙 <b>{lb['audio']}:</b> {audio_label(m.get('audio'), cl)}")
        qs = " • ".join(utils.q_label(q) for q in sorted(avail, key=utils.q_key, reverse=True))
        must.append(f"🖥 <b>{lb['quality']}:</b> {qs}")
    elif isinstance(avail, dict) and avail:
        must.append(f"🎙 <b>{lb['audio']}:</b> {audio_label(m.get('audio'), cl)}")
        must.append(
            f"📺 <b>{lb['seasons']}:</b> {len(avail)} • <b>{lb['episodes']}:</b> {sum(avail.values())}"
        )
    elif avail is False:
        must.append(f"⏳ <b>{lb['na']}</b>")

    ratings = []
    if m.get("imdb_rating"):
        votes = f" ({utils.short_num(m['imdb_votes'])})" if m.get("imdb_votes") else ""
        ratings.append(f"<b>IMDb</b> {m['imdb_rating']}{votes}")
    if m.get("rating"):
        votes = f" ({utils.short_num(m['rating_votes'])})" if m.get("rating_votes") else ""
        ratings.append(f"<b>TMDB</b> {m['rating']:.1f}/10{votes}")
    if ratings:
        must.append("⭐ " + " • ".join(ratings))
    if m.get("ub_count"):
        line = f"👥 <b>{lb['users']}:</b> {m['ub_avg']:.1f}/10 ({m['ub_count']})"
        if m.get("my_rating"):
            line += f" • {lb['your']}: {m['my_rating']}/10"
        must.append(line)
    elif m.get("my_rating"):
        must.append(f"🌟 <b>{lb['your']}:</b> {m['my_rating']}/10")
    if m.get("genre_tags"):
        tags = " ".join("#" + genre_tag(g, cl) for g in m["genre_tags"])
        must.append(f"🎭 <b>{lb['genre']}:</b> {tags}")
    if m.get("runtime"):
        must.append(f"⏱ <b>{lb['duration']}:</b> {fmt_duration(m['runtime'], cl)}")

    optional = []
    if m.get("certification"):
        optional.append(f"🔞 <b>{lb['age']}:</b> {cert_emoji(m['certification'])} {escape(m['certification'])}")
    if m.get("directors"):
        optional.append(f"🎥 <b>{lb['director']}:</b> {escape(m['directors'])}")
    if m.get("cast_top"):
        optional.append(f"👥 <b>{lb['cast']}:</b> {escape(m['cast_top'])}")
    if m.get("views") and avail:
        optional.append(f"📥 <b>{lb['downloads']}:</b> {m['views']}")

    if locked:
        footer = f"🔒 <b>{lb['lock']}</b>"
    elif isinstance(avail, list) and avail:
        footer = f"👇 <b>{lb['pick']}</b>"
    elif isinstance(avail, dict) and avail:
        footer = f"👇 <b>{lb['pick_season']}</b>"
    elif avail is False:
        footer = f"🔔 {lb['notify_hint']}"
    else:
        footer = ""

    overview = overview_for(m, cl)

    def build(opt, ov):
        text = "\n".join(core + must + opt)
        if ov:
            text += f"\n\n<blockquote expandable>{escape(ov)}</blockquote>"
        if footer:
            text += f"\n\n{footer}"
        return text

    opt = list(optional)
    while True:
        budget = LIMIT - len(build(opt, None)) - 40
        if budget >= 160 or not opt:
            break
        opt.pop()
    ov = None
    if overview and budget >= 60:
        ov = overview.strip()
        if len(ov) > budget:
            ov = ov[: budget - 1].rsplit(" ", 1)[0] + "…"
    return build(opt, ov)


def media_caption(m: dict, season: int, episode: int, quality: str) -> str:
    """Video izohi: nom+yil bold, pastda quote ichida ma'lumotlar (har doim o'zbekcha)."""
    year = f" ({m['year']})" if m.get("year") else ""
    head = f"🎬 <b>{escape(m['title'])}{year}</b>"
    q = [f"📀 <b>Sifat:</b> {utils.q_label(quality)}"]
    if season:
        q.append(f"📺 <b>Qism:</b> {season}-fasl, {episode}-qism")
    q.append(f"🎙 <b>Til:</b> {audio_label(m.get('audio'), 'uz')}")
    if m.get("genre_tags"):
        names = [genre_label(g, "uz") for g in m["genre_tags"]]
    else:
        names = list(m.get("genres") or [])
    if names:
        q.append(f"🎭 <b>Janr:</b> {escape(', '.join(names))}")
    scores = []
    if m.get("imdb_rating"):
        scores.append(f"<b>IMDb</b> {m['imdb_rating']}")
    if m.get("rating"):
        scores.append(f"<b>TMDB</b> {m['rating']:.1f}/10")
    if scores:
        q.append("⭐ " + " • ".join(scores))
    if m.get("country_codes"):
        q.append(f"🌍 <b>Davlat:</b> {escape(', '.join(country_name(c, 'uz') for c in m['country_codes']))}")
    return head + "\n\n<blockquote>" + "\n".join(q) + "</blockquote>"


def movie_kb(lang: str, m: dict, fav: bool, avail, locked: bool, my_rating=None):
    mid = m["id"]
    rows = []
    if locked:
        rows.append([utils.btn(t(lang, "prem_btn"), "prem:open")])
    elif isinstance(avail, dict):
        buttons = [utils.btn(t(lang, "season_btn").format(n=s), f"se:{mid}:{s}") for s in sorted(avail)]
        rows += utils.grid(buttons, 3)
    elif isinstance(avail, list) and avail:
        quals = sorted(avail, key=utils.q_key, reverse=True)
        rows.append([utils.btn(QBTN.get(q, f"📥 {q}"), f"dl:{mid}:0:0:{q}") for q in quals])
    rate_label = f"⭐ {my_rating}/10" if my_rating else t(lang, "rate_btn")
    rows.append(
        [
            utils.btn(t(lang, "fav_remove" if fav else "fav_add"), f"fav:{mid}"),
            utils.btn(rate_label, f"rt:{mid}"),
        ]
    )
    if m.get("trailer_key"):
        rows.append([utils.url_btn(t(lang, "trailer"), f"https://www.youtube.com/watch?v={m['trailer_key']}")])
    link = f"https://t.me/{utils.BOT_USERNAME}?start={m['code']}"
    share = f"https://t.me/share/url?url={quote(link)}&text={quote('🎬 ' + m['title'])}"
    rows.append([utils.url_btn(t(lang, "share"), share)])
    return utils.kb_of(rows)


def missing_kb(lang: str, tmdb_type: str, tmdb_id: int, requested: bool, trailer_key):
    rows = [[utils.btn(t(lang, "notify_off" if requested else "notify_on"), f"rq:{tmdb_type}:{tmdb_id}")]]
    if trailer_key:
        rows.append([utils.url_btn(t(lang, "trailer"), f"https://www.youtube.com/watch?v={trailer_key}")])
    return utils.kb_of(rows)
