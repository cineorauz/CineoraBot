import asyncio

import aiohttp

import config
from genres import GENRE_UZ

BASE = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p/w500"
ASIAN_DRAMA = {"KR", "JP", "CN", "TW", "TH", "TR", "HK"}


class TMDBError(Exception):
    pass


async def _get(path: str, **params):
    if not config.TMDB_API_KEY:
        raise TMDBError("TMDB_API_KEY o'rnatilmagan")
    params["api_key"] = config.TMDB_API_KEY
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(BASE + path, params=params) as resp:
                if resp.status != 200:
                    raise TMDBError(f"TMDB xatosi: {resp.status}")
                return await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        raise TMDBError(f"TMDB bilan ulanib bo'lmadi: {e}")


async def search(query: str) -> list[dict]:
    data = await _get("/search/multi", query=query, language="en-US", include_adult="false")
    out = []
    for x in data.get("results", []):
        media_type = x.get("media_type")
        if media_type not in ("movie", "tv"):
            continue
        date = x.get("release_date") or x.get("first_air_date") or ""
        out.append(
            {
                "type": media_type,
                "id": x["id"],
                "title": x.get("title") or x.get("name") or "?",
                "year": date[:4],
            }
        )
        if len(out) == 6:
            break
    return out


def detect_category(is_series: bool, genre_ids: list[int], lang: str, countries: list[str]) -> str:
    if 16 in genre_ids:
        return "Animelar" if lang == "ja" else "Multfilmlar"
    if is_series and 18 in genre_ids and set(countries) & ASIAN_DRAMA:
        return "Dramalar"
    return "Seriallar" if is_series else "Kinolar"


async def details(media_type: str, tmdb_id: int) -> dict:
    en = await _get(f"/{media_type}/{tmdb_id}", language="en-US")
    ru = await _get(f"/{media_type}/{tmdb_id}", language="ru-RU")
    is_series = media_type == "tv"

    title = en.get("title") or en.get("name") or ""
    original = en.get("original_title") or en.get("original_name") or ""
    ru_title = ru.get("title") or ru.get("name") or ""
    date = en.get("release_date") or en.get("first_air_date") or ""
    year = int(date[:4]) if date[:4].isdigit() else None

    genre_items = en.get("genres", [])
    genre_ids = [g["id"] for g in genre_items]
    genres = [GENRE_UZ.get(g["id"], g["name"]) for g in genre_items]

    countries = en.get("origin_country") or [
        c.get("iso_3166_1") for c in en.get("production_countries", [])
    ]
    category = detect_category(is_series, genre_ids, en.get("original_language", ""), countries)

    seasons = [s for s in en.get("seasons", []) if s.get("season_number", 0) > 0]
    seasons_total = max((s["season_number"] for s in seasons), default=0)

    poster = en.get("poster_path")
    aliases = []
    for name in (title, original, ru_title):
        name = (name or "").strip()
        if name and name not in aliases:
            aliases.append(name)

    return {
        "title": title or original or ru_title,
        "aliases": aliases,
        "year": year,
        "genres": genres,
        "rating": en.get("vote_average") or None,
        "poster_url": (IMG + poster) if poster else None,
        "tmdb_id": tmdb_id,
        "tmdb_type": media_type,
        "is_series": is_series,
        "seasons_total": seasons_total,
        "category": category,
    }
