import asyncio
import re

import aiohttp

import config
from genres import GENRE_UZ

BASE = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p/w500"
ASIAN_DRAMA = {"KR", "JP", "CN", "TW", "TH", "TR", "HK"}

_GENRE_TAGS = {
    "Science Fiction": ["SciFi"],
    "Sci-Fi & Fantasy": ["SciFi", "Fantasy"],
    "Action & Adventure": ["Action", "Adventure"],
    "War & Politics": ["War", "Politics"],
    "TV Movie": ["TVMovie"],
}


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


async def omdb_ratings(imdb_id: str | None) -> dict:
    """IMDb, Rotten Tomatoes va Metacritic reytinglari (OMDb, kalit bo'lsa)."""
    if not config.OMDB_API_KEY or not imdb_id:
        return {}
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                "https://www.omdbapi.com/",
                params={"i": imdb_id, "apikey": config.OMDB_API_KEY},
            ) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return {}
    if data.get("Response") != "True":
        return {}
    out = {}
    imdb = data.get("imdbRating")
    if imdb and imdb != "N/A":
        out["imdb_rating"] = f"{imdb}/10"
    for r in data.get("Ratings", []):
        if r.get("Source") == "Rotten Tomatoes":
            out["rt_rating"] = r.get("Value")
        elif r.get("Source") == "Metacritic":
            out["meta_rating"] = r.get("Value")
    return out


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


def _hashtag(name: str) -> str:
    name = name.replace("United States of America", "United States")
    return re.sub(r"[^A-Za-z0-9]", "", name)


def _genre_tags(names: list[str]) -> list[str]:
    out = []
    for name in names:
        for tag in _GENRE_TAGS.get(name, [re.sub(r"[^A-Za-z0-9]", "", name)]):
            if tag and tag not in out:
                out.append(tag)
    return out


def _certification(media_type: str, data: dict):
    if media_type == "movie":
        for c in (data.get("release_dates") or {}).get("results", []):
            if c.get("iso_3166_1") == "US":
                for rd in c.get("release_dates", []):
                    if rd.get("certification"):
                        return rd["certification"]
    else:
        for c in (data.get("content_ratings") or {}).get("results", []):
            if c.get("iso_3166_1") == "US" and c.get("rating"):
                return c["rating"]
    return None


async def details(media_type: str, tmdb_id: int) -> dict:
    extra = "release_dates,external_ids" if media_type == "movie" else "content_ratings,external_ids"
    en = await _get(f"/{media_type}/{tmdb_id}", language="en-US", append_to_response=extra)
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
    genre_tags = _genre_tags([g["name"] for g in genre_items])

    prod = en.get("production_countries", [])
    codes = en.get("origin_country") or [c.get("iso_3166_1") for c in prod]
    countries = [_hashtag(c["name"]) for c in prod if c.get("name")] or [c for c in codes if c]
    category = detect_category(is_series, genre_ids, en.get("original_language", ""), codes)

    seasons = [s for s in en.get("seasons", []) if s.get("season_number", 0) > 0]
    seasons_total = max((s["season_number"] for s in seasons), default=0)

    if is_series:
        runs = en.get("episode_run_time") or []
        runtime = runs[0] if runs else None
    else:
        runtime = en.get("runtime") or None

    imdb_id = en.get("imdb_id") or (en.get("external_ids") or {}).get("imdb_id")
    ratings = await omdb_ratings(imdb_id)

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
        "genre_tags": genre_tags,
        "countries": countries,
        "rating": en.get("vote_average") or None,
        "poster_url": (IMG + poster) if poster else None,
        "tmdb_id": tmdb_id,
        "tmdb_type": media_type,
        "is_series": is_series,
        "seasons_total": seasons_total,
        "category": category,
        "overview_en": (en.get("overview") or "").strip() or None,
        "overview_ru": (ru.get("overview") or "").strip() or None,
        "runtime": runtime,
        "certification": _certification(media_type, en),
        "imdb_id": imdb_id,
        "imdb_rating": ratings.get("imdb_rating"),
        "rt_rating": ratings.get("rt_rating"),
        "meta_rating": ratings.get("meta_rating"),
    }
