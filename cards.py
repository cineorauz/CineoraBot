from html import escape

from aiogram.types import InlineKeyboardButton

import ux
import utils
from genres import country_name, country_tag, genre_label, genre_tag
from locales import t

# Kartochka tili: o'zbekcha tavsif Tilmoch tarjimasidan olinadi (bo'lmasa inglizcha tavsif chiqadi).
CARD_LANG = {"uz": "uz", "en": "en", "ru": "ru"}
LIMIT = 1024

# kod -> (o'zbekcha, ruscha, inglizcha)
AUDIO = {
    "uz": ("O'zbek tilida", "На узбекском", "In Uzbek"),
    "ru": ("Rus tilida", "На русском", "In Russian"),
    "en": ("Ingliz tilida", "На английском", "In English"),
    "orig": ("Original (subtitr bilan)", "Оригинал (субтитры)", "Original (subtitles)"),
}

L = {
    "uz": {
        "country": "Davlat", "audio": "Til", "seasons": "Fasllar", "episodes": "Qismlar",
        "duration": "Davomiyligi", "age": "Yosh chegarasi", "director": "Rejissyor", "cast": "Aktyorlar",
        "downloads": "Yuklashlar", "h": "soat", "min": "daqiqa",
        "na": "Hali yuklanmadi", "notify_hint": "Yuklanishi bilan sizga xabar beramiz",
        "lock": "Bu kontent faqat Premium obunachilar uchun",
        "users": "Foydalanuvchilar", "your": "Sizning bahoyingiz",
    },
    "en": {
        "country": "Country", "audio": "Language", "seasons": "Seasons", "episodes": "Episodes",
        "duration": "Duration", "age": "Age rating", "director": "Director", "cast": "Cast",
        "downloads": "Downloads", "h": "h", "min": "min",
        "na": "Not uploaded yet", "notify_hint": "We'll notify you as soon as it's added",
        "lock": "Premium members only",
        "users": "Users", "your": "Your rating",
    },
    "ru": {
        "country": "Страна", "audio": "Язык", "seasons": "Сезоны", "episodes": "Серии",
        "duration": "Длительность", "age": "Возраст", "director": "Режиссёр", "cast": "В ролях",
        "downloads": "Загрузок", "h": "ч", "min": "мин",
        "na": "Ещё не загружено", "notify_hint": "Сообщим, как только добавим",
        "lock": "Только для Premium",
        "users": "Пользователи", "your": "Ваша оценка",
    },
}

QBTN = {"2160": "🎞 4K", "1080": "🔥 1080p", "720": "✨ 720p", "480": "📺 480p", "360": "📱 360p"}
SHARE_SHORT = {"uz": "📤 Ulashish", "en": "📤 Share", "ru": "📤 Поделиться"}


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


def uz_name(m: dict):
    """O'zbekcha 2-nom (asosiy nomdan farq qilsa), aks holda None."""
    uz = (m.get("title_uz") or "").strip()
    if uz and uz.lower() != (m.get("title") or "").strip().lower():
        return uz
    return None


def card_text(m: dict, lang: str, avail=None, locked: bool = False, share: bool = False, detail: bool = False) -> str:
    """Qisqa kartochka. detail=True: rejissyor, aktyorlar, davlat, yosh chegarasi va h.k. ham chiqadi.
    avail: None — ko'rsatilmaydi, False — yuklanmagan, list — kino sifatlari, dict — serial fasllari."""
    cl = CARD_LANG.get(lang, "en")
    lb = L[cl]
    title = (m.get("title_ru") if cl == "ru" else None) or m.get("title") or "?"
    head = f"🎬 <b>{escape(title)}</b>"
    if m.get("year"):
        head += f" ({m['year']})"
    if m.get("is_premium"):
        head += "  💎"
    top = [head]
    uz = uz_name(m)
    if uz:
        top.append(f"🇺🇿 <i>{escape(uz)}</i>")
    tagline = tagline_for(m, cl) if detail else None
    if tagline:
        top.append(f"<i>{escape(tagline)}</i>")

    info = []
    scores = []
    if m.get("imdb_rating"):
        scores.append(f"<b>IMDb</b> {m['imdb_rating']}")
    if m.get("rating"):
        scores.append(f"<b>TMDB</b> {m['rating']:.1f}")
    line = "⭐ " + " • ".join(scores) if scores else ""
    if m.get("runtime"):
        rt = f"⏱ {fmt_duration(m['runtime'], cl)}"
        line = f"{line}   {rt}" if line else rt
    if line:
        info.append(line)
    if m.get("genre_tags"):
        info.append("🎭 " + " ".join("#" + genre_tag(g, cl) for g in m["genre_tags"]))
    audio = audio_label(m.get("audio"), cl)
    if isinstance(avail, list) and avail:
        qs = " • ".join(utils.q_label(q) for q in sorted(avail, key=utils.q_key, reverse=True))
        info.append(f"🖥 {qs}   🎙 {audio}")
    elif isinstance(avail, dict) and avail:
        info.append(f"📺 {lb['seasons']}: {len(avail)} • {lb['episodes']}: {sum(avail.values())}   🎙 {audio}")
    elif avail is False:
        info.append(f"⏳ <b>{lb['na']}</b>\n🔔 <i>{lb['notify_hint']}</i>")
    if locked and not share:
        info.append(f"🔒 <b>{lb['lock']}</b>")

    optional = []
    if detail:
        codes = m.get("country_codes") or []
        countries = [country_tag(c, cl) for c in codes] if codes else list(m.get("countries") or [])
        if countries:
            optional.append(f"🌍 <b>{lb['country']}:</b> " + " ".join("#" + c for c in countries))
        if m.get("certification"):
            optional.append(f"🔞 <b>{lb['age']}:</b> {cert_emoji(m['certification'])} {escape(m['certification'])}")
        if m.get("directors"):
            optional.append(f"🎥 <b>{lb['director']}:</b> {escape(m['directors'])}")
        if m.get("cast_top"):
            optional.append(f"👥 <b>{lb['cast']}:</b> {escape(m['cast_top'])}")
        if m.get("ub_count"):
            u_line = f"🗣 <b>{lb['users']}:</b> {m['ub_avg']:.1f}/10 ({m['ub_count']})"
            if m.get("my_rating") and not share:
                u_line += f" • {lb['your']}: {m['my_rating']}/10"
            optional.append(u_line)
        if m.get("views") and avail and not share:
            optional.append(f"📥 <b>{lb['downloads']}:</b> {m['views']}")

    def build(opt, ov):
        text = "\n".join(top)
        body = info + opt
        if body:
            text += "\n\n" + "\n".join(body)
        if ov:
            text += f"\n\n<blockquote expandable>{escape(ov)}</blockquote>"
        return text

    opt = list(optional)
    while True:
        budget = LIMIT - len(build(opt, None)) - 30
        if budget >= 120 or not opt:
            break
        opt.pop()
    ov = None
    overview = overview_for(m, cl)
    if overview and budget >= 60:
        ov = overview.strip()
        if len(ov) > budget:
            ov = ov[: budget - 1].rsplit(" ", 1)[0] + "…"
    return build(opt, ov)


def media_caption(m: dict, season: int, episode: int, quality: str) -> str:
    """Video izohi: nom+yil bold, 2-qatorda o'zbekcha nom, pastda quote ichida ma'lumotlar."""
    year = f" ({m['year']})" if m.get("year") else ""
    head = f"🎬 <b>{escape(m['title'])}{year}</b>"
    uz = uz_name(m)
    if uz:
        head += f"\n🇺🇿 <b>{escape(uz)}</b>"
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


# ---------------- kanalga e'lon ----------------
def _uz_genres(m: dict) -> list:
    if m.get("genre_tags"):
        return [genre_label(g, "uz") for g in m["genre_tags"]]
    return list(m.get("genres") or [])


def announce_caption(
    m: dict, kind: str, footer: str, quals=None, seasons=None,
    season=None, ep_from=None, ep_to=None,
) -> str:
    """kind: 'n' — to'liq post, 'e' — yangi qism(lar) posti. footer — oddiy matn (escape qilinadi)."""
    title = escape(m["title"])
    uz = uz_name(m)
    uz_html = f"\n🇺🇿 <b>{escape(uz)}</b>" if uz else ""
    footer_html = f"\n\n{escape(footer)}" if footer else ""
    q_line = " • ".join(utils.q_label(q) for q in sorted(quals or [], key=utils.q_key, reverse=True))
    scores = []
    if m.get("imdb_rating"):
        scores.append(f"<b>IMDb:</b> {m['imdb_rating']}")
    if m.get("rating"):
        scores.append(f"<b>TMDB:</b> {m['rating']:.1f}/10")

    if kind == "e":
        ep = f"{ep_from}-qism" if ep_from == ep_to else f"{ep_from}–{ep_to}-qismlar"
        info = []
        if scores:
            info.append("⭐ " + " • ".join(scores))
        info.append(f"🎙 <b>Ovoz:</b> {audio_label(m.get('audio'), 'uz')}")
        if q_line:
            info.append(f"🖥 <b>Sifat:</b> {q_line}")
        return (
            f"🆕 <b>Yangi qism!</b>\n\n🎬 <b>{title}</b>{uz_html}\n📺 {season}-fasl, {ep}\n\n"
            f"<blockquote>{chr(10).join(info)}</blockquote>{footer_html}"
        )

    year = f" ({m['year']})" if m.get("year") else ""
    head = f"🎬 <b>{title}{year}</b>{uz_html}"
    info = []
    if scores:
        info.append("⭐ " + " • ".join(scores))
    names = _uz_genres(m)
    if names:
        info.append(f"🎭 <b>Janr:</b> {escape(', '.join(names))}")
    info.append(f"🎙 <b>Ovoz:</b> {audio_label(m.get('audio'), 'uz')}")
    if m.get("is_series"):
        if seasons:
            info.append(
                f"📺 <b>Fasllar soni:</b> {len(seasons)} ta • <b>Qismlar:</b> {sum(seasons.values())} ta"
            )
        status = "Tugagan" if m.get("series_status") == "completed" else "Davom etmoqda"
        info.append(f"📡 <b>Holat:</b> {status}")
    if q_line:
        info.append(f"🖥 <b>Sifat:</b> {q_line}")
    if m.get("year"):
        info.append(f"📅 <b>Chiqarilgan yili:</b> {m['year']}")
    if m.get("country_codes"):
        info.append(f"🌍 <b>Davlat:</b> {escape(', '.join(country_name(c, 'uz') for c in m['country_codes']))}")
    if m.get("runtime") and not m.get("is_series"):
        info.append(f"⏱ <b>Davomiyligi:</b> {fmt_duration(m['runtime'], 'uz')}")
    if m.get("certification"):
        info.append(f"🔞 <b>Yosh:</b> {escape(m['certification'])}")

    base = f"{head}\n\n<blockquote>{chr(10).join(info)}</blockquote>{footer_html}"
    overview = overview_for(m, "uz")
    budget = LIMIT - len(base) - 80
    if overview and budget >= 80:
        ov = overview.strip()
        if len(ov) > budget:
            ov = ov[: budget - 1].rsplit(" ", 1)[0] + "…"
        return (
            f"{head}\n\n<blockquote>{chr(10).join(info)}</blockquote>\n\n"
            f"<blockquote expandable>📖 <b>Qisqacha tavsif:</b>\n{escape(ov)}</blockquote>{footer_html}"
        )
    return base


def announce_kb(code: str):
    link = f"https://t.me/{utils.BOT_USERNAME}?start={code}"
    return utils.kb_of([[utils.url_btn("▶️ Tomosha qilish", link)]])


# ---------------- tugmalar ----------------
def movie_kb(lang: str, m: dict, fav: bool, avail, locked: bool, my_rating=None):
    """Asosiy ko'rinish: ko'rish tugmalari, Saqlash/Baholash, Treyler/Ulashish/Yana."""
    mid = m["id"]
    rows = []
    if locked:
        rows.append([utils.btn(t(lang, "prem_btn"), "prem:open")])
    elif isinstance(avail, dict):
        rows += utils.grid([utils.btn(t(lang, "season_btn").format(n=s), f"se:{mid}:{s}") for s in sorted(avail)], 3)
    elif isinstance(avail, list) and avail:
        quals = sorted(avail, key=utils.q_key, reverse=True)
        rows.append([utils.btn(QBTN.get(q, f"📥 {q}"), f"dl:{mid}:0:0:{q}") for q in quals])
    rate_label = f"⭐ {my_rating}/10" if my_rating else ux.u(lang, "rate")
    rows.append([utils.btn(ux.u(lang, "saved" if fav else "save"), f"fav:{mid}"), utils.btn(rate_label, f"rt:{mid}")])
    third = []
    if m.get("trailer_key"):
        third.append(utils.url_btn(t(lang, "trailer"), f"https://www.youtube.com/watch?v={m['trailer_key']}"))
    # Ulashish: chat tanlanadi va inline rejim orqali posterli chiroyli xabar yuboriladi
    third.append(
        InlineKeyboardButton(
            text=SHARE_SHORT.get(lang, SHARE_SHORT["uz"]), switch_inline_query=f"share_{m['code']}"
        )
    )
    third.append(utils.btn(ux.u(lang, "more"), f"mx:{mid}"))
    rows.append(third)
    return utils.kb_of(rows)


def more_kb(lang: str, m: dict, detail: bool):
    """«⋯ Yana» ichidagi qo'shimcha amallar."""
    mid = m["id"]
    first = []
    if m.get("tmdb_id"):
        first.append(utils.btn(ux.u(lang, "similar"), f"sm:{mid}"))
    first.append(utils.btn(ux.u(lang, "compact" if detail else "details"), f"inf:{mid}"))
    return utils.kb_of([first, [utils.btn(ux.u(lang, "report"), f"rpt:{mid}")], [utils.btn(t(lang, "back"), f"mv:{mid}")]])


def missing_kb(lang: str, tmdb_type: str, tmdb_id: int, requested: bool, trailer_key):
    rows = [[utils.btn(t(lang, "notify_off" if requested else "notify_on"), f"rq:{tmdb_type}:{tmdb_id}")]]
    if trailer_key:
        rows.append([utils.url_btn(t(lang, "trailer"), f"https://www.youtube.com/watch?v={trailer_key}")])
    return utils.kb_of(rows)
