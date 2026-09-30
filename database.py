import logging
import secrets
import string

import asyncpg

pool: asyncpg.Pool | None = None

_ALPHABET = string.ascii_letters + string.digits

_MOVIE_FIELDS = [
    "title", "category", "is_series", "year", "genres", "rating", "rating_votes",
    "poster_url", "tmdb_id", "tmdb_type", "seasons_total", "overview_en", "overview_ru",
    "runtime", "certification", "countries", "genre_tags", "imdb_id", "imdb_rating",
    "imdb_votes",
]
_LIST_FIELDS = {"genres", "countries", "genre_tags"}

# Foydalanuvchiga ko'rinadigan kinolar: yashirilmagan va kamida bitta fayli bor
_VISIBLE = (
    "NOT m.hidden AND EXISTS (SELECT 1 FROM media_files f WHERE f.movie_id = m.id)"
)
_LABEL_COLS = "m.id, m.title, m.year, m.is_series, m.imdb_rating, m.rating"


def generate_code(length: int = 10) -> str:
    """Tasodifiy kod, masalan: k7Xp2mQaR9 (faqat ulashish havolasi uchun)."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


async def init(dsn: str):
    global pool
    pool = await asyncpg.create_pool(dsn)
    await pool.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            lang TEXT,
            joined_at TIMESTAMPTZ DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS movies (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS favorites (
            user_id BIGINT,
            movie_id INT REFERENCES movies(id) ON DELETE CASCADE,
            PRIMARY KEY (user_id, movie_id)
        );
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS poster_id TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS code TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS category TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS genres TEXT[];
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS year INT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS is_series BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS rating REAL;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS rating_votes INT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS poster_url TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS tmdb_id INT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS tmdb_type TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS seasons_total INT NOT NULL DEFAULT 0;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS hidden BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS views INT NOT NULL DEFAULT 0;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS overview_en TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS overview_ru TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS overview_uz TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS runtime INT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS certification TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS countries TEXT[];
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS genre_tags TEXT[];
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS imdb_id TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS imdb_rating TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS imdb_votes INT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS rt_rating TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS meta_rating TEXT;
        CREATE TABLE IF NOT EXISTS movie_titles (
            movie_id INT REFERENCES movies(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            PRIMARY KEY (movie_id, title)
        );
        CREATE TABLE IF NOT EXISTS media_files (
            movie_id INT REFERENCES movies(id) ON DELETE CASCADE,
            season INT NOT NULL DEFAULT 0,
            episode INT NOT NULL DEFAULT 0,
            quality TEXT NOT NULL,
            file_id TEXT NOT NULL,
            file_type TEXT NOT NULL,
            caption TEXT,
            PRIMARY KEY (movie_id, season, episode, quality)
        );
        ALTER TABLE media_files ADD COLUMN IF NOT EXISTS cover_id TEXT;
        """
    )

    # Eski (movie_files) jadvaldagi fayllarni yangi jadvalga ko'chiramiz
    if await pool.fetchval("SELECT to_regclass('movie_files')::text"):
        try:
            await pool.execute(
                """
                INSERT INTO media_files (movie_id, season, episode, quality, file_id, file_type, caption)
                SELECT movie_id, 0, 0, quality, file_id, file_type, caption FROM movie_files
                ON CONFLICT DO NOTHING
                """
            )
        except Exception as e:
            logging.warning("Eski fayllarni ko'chirib bo'lmadi: %s", e)

    # Kodi yo'q kinolarga tasodifiy kod beramiz
    for r in await pool.fetch("SELECT id FROM movies WHERE code IS NULL"):
        await pool.execute(
            "UPDATE movies SET code=$1 WHERE id=$2", generate_code(), r["id"]
        )
    await pool.execute(
        "INSERT INTO movie_titles (movie_id, title) SELECT id, title FROM movies ON CONFLICT DO NOTHING"
    )
    await pool.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS movies_code_uidx ON movies(code)"
    )


# ---------- users ----------
async def add_user(user_id: int):
    await pool.execute(
        "INSERT INTO users (user_id) VALUES ($1) ON CONFLICT DO NOTHING", user_id
    )


async def get_lang(user_id: int):
    return await pool.fetchval("SELECT lang FROM users WHERE user_id=$1", user_id)


async def set_lang(user_id: int, lang: str):
    await pool.execute(
        """
        INSERT INTO users (user_id, lang) VALUES ($1, $2)
        ON CONFLICT (user_id) DO UPDATE SET lang = $2
        """,
        user_id,
        lang,
    )


# ---------- movies ----------
async def create_movie(d: dict):
    """Yangi kino/serial yaratadi va (id, kod) qaytaradi."""
    values = []
    for f in _MOVIE_FIELDS:
        v = d.get(f)
        if f in _LIST_FIELDS:
            v = v or []
        elif f == "is_series":
            v = bool(v)
        elif f == "seasons_total":
            v = v or 0
        values.append(v)
    cols = ", ".join(_MOVIE_FIELDS + ["code"])
    marks = ", ".join(f"${i}" for i in range(1, len(_MOVIE_FIELDS) + 2))
    for _ in range(5):
        code = generate_code()
        try:
            movie_id = await pool.fetchval(
                f"INSERT INTO movies ({cols}) VALUES ({marks}) RETURNING id",
                *values,
                code,
            )
        except asyncpg.UniqueViolationError:
            continue
        names = {d["title"], *d.get("aliases", [])}
        for name in names:
            name = (name or "").strip()
            if name:
                await add_alias(movie_id, name)
        return movie_id, code
    raise RuntimeError("Kod yaratib bo'lmadi")


async def update_meta(movie_id: int, d: dict):
    """TMDB/OMDb ma'lumotlarini yangilaydi (nom va kategoriya o'zgarmaydi)."""
    await pool.execute(
        """
        UPDATE movies SET
            year = COALESCE($2, year),
            genres = $3,
            rating = $4,
            poster_id = CASE WHEN poster_url IS DISTINCT FROM $5 THEN NULL ELSE poster_id END,
            poster_url = $5,
            overview_en = $6,
            overview_ru = $7,
            runtime = $8,
            certification = $9,
            countries = $10,
            genre_tags = $11,
            imdb_id = COALESCE($12, imdb_id),
            imdb_rating = COALESCE($13, imdb_rating),
            seasons_total = GREATEST(seasons_total, $14),
            rating_votes = $15,
            imdb_votes = COALESCE($16, imdb_votes)
        WHERE id = $1
        """,
        movie_id,
        d.get("year"),
        d.get("genres") or [],
        d.get("rating"),
        d.get("poster_url"),
        d.get("overview_en"),
        d.get("overview_ru"),
        d.get("runtime"),
        d.get("certification"),
        d.get("countries") or [],
        d.get("genre_tags") or [],
        d.get("imdb_id"),
        d.get("imdb_rating"),
        d.get("seasons_total") or 0,
        d.get("rating_votes"),
        d.get("imdb_votes"),
    )
    for name in d.get("aliases", []):
        if name:
            await add_alias(movie_id, name)


async def get_movie(movie_id: int):
    return await pool.fetchrow("SELECT * FROM movies WHERE id=$1", movie_id)


async def get_movie_by_code(code: str):
    """Ulashish havolasi uchun (yashirin kinolar chiqmaydi)."""
    return await pool.fetchrow(
        "SELECT * FROM movies WHERE code=$1 AND NOT hidden", code
    )


async def add_alias(movie_id: int, title: str):
    await pool.execute(
        "INSERT INTO movie_titles (movie_id, title) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        movie_id,
        title,
    )


async def get_aliases(movie_id: int) -> list[str]:
    rows = await pool.fetch(
        "SELECT title FROM movie_titles WHERE movie_id=$1 ORDER BY title", movie_id
    )
    return [r["title"] for r in rows]


async def set_title(movie_id: int, title: str):
    await pool.execute("UPDATE movies SET title=$1 WHERE id=$2", title, movie_id)
    await add_alias(movie_id, title)


async def set_overview_uz(movie_id: int, text: str | None):
    await pool.execute("UPDATE movies SET overview_uz=$1 WHERE id=$2", text, movie_id)


async def set_category(movie_id: int, category: str):
    await pool.execute("UPDATE movies SET category=$1 WHERE id=$2", category, movie_id)


async def set_seasons_total(movie_id: int, total: int):
    await pool.execute("UPDATE movies SET seasons_total=$1 WHERE id=$2", total, movie_id)


async def set_poster_id(movie_id: int, file_id: str):
    await pool.execute("UPDATE movies SET poster_id=$1 WHERE id=$2", file_id, movie_id)


async def toggle_hidden(movie_id: int) -> bool:
    return await pool.fetchval(
        "UPDATE movies SET hidden = NOT hidden WHERE id=$1 RETURNING hidden", movie_id
    )


async def delete_movie(movie_id: int) -> bool:
    res = await pool.execute("DELETE FROM movies WHERE id=$1", movie_id)
    return res.endswith(" 1")


async def add_view(movie_id: int):
    await pool.execute("UPDATE movies SET views = views + 1 WHERE id=$1", movie_id)


async def list_movies(offset: int = 0, limit: int = 8):
    """Admin ro'yxati (hammasi, yashirinlar ham)."""
    return await pool.fetch(
        "SELECT id, title, hidden, is_series FROM movies ORDER BY id DESC OFFSET $1 LIMIT $2",
        offset,
        limit,
    )


# ---------- foydalanuvchi uchun qidiruv va ko'rish ----------
async def search_movies(query: str, offset: int = 0, limit: int = 8):
    safe = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return await pool.fetch(
        f"""
        SELECT DISTINCT {_LABEL_COLS} FROM movies m
        JOIN movie_titles t ON t.movie_id = m.id
        WHERE t.title ILIKE $1 AND {_VISIBLE}
        ORDER BY m.id DESC OFFSET $2 LIMIT $3
        """,
        f"%{safe}%",
        offset,
        limit,
    )


async def browse(kind: str, value, offset: int, limit: int):
    """kind: c=kategoriya, g=janr (hashtag), y=o'nyillik, p=mashhur, n=yangi."""
    where = _VISIBLE
    args = []
    order = "m.id DESC"
    if kind == "c":
        where += " AND m.category = $1"
        args = [value]
    elif kind == "g":
        where += " AND $1 = ANY(m.genre_tags)"
        args = [value]
    elif kind == "y":
        where += " AND m.year >= $1 AND m.year < $1 + 10"
        args = [int(value)]
    elif kind == "p":
        order = "m.views DESC, m.id DESC"
    n = len(args)
    rows = await pool.fetch(
        f"SELECT {_LABEL_COLS} FROM movies m WHERE {where} "
        f"ORDER BY {order} OFFSET ${n + 1} LIMIT ${n + 2}",
        *args,
        offset,
        limit,
    )
    total = await pool.fetchval(f"SELECT count(*) FROM movies m WHERE {where}", *args)
    return rows, total


async def category_counts() -> dict:
    rows = await pool.fetch(
        f"""
        SELECT m.category, count(*) AS c FROM movies m
        WHERE {_VISIBLE} AND m.category IS NOT NULL GROUP BY m.category
        """
    )
    return {r["category"]: r["c"] for r in rows}


async def genre_counts():
    return await pool.fetch(
        f"""
        SELECT g AS tag, count(*) AS c FROM movies m, unnest(m.genre_tags) AS g
        WHERE {_VISIBLE} GROUP BY g ORDER BY c DESC, g
        """
    )


async def decade_counts():
    return await pool.fetch(
        f"""
        SELECT (m.year / 10 * 10) AS dec, count(*) AS c FROM movies m
        WHERE {_VISIBLE} AND m.year IS NOT NULL GROUP BY dec ORDER BY dec DESC
        """
    )


async def random_movie():
    return await pool.fetchrow(
        f"SELECT m.* FROM movies m WHERE {_VISIBLE} ORDER BY random() LIMIT 1"
    )


# ---------- files ----------
async def save_file(
    movie_id: int,
    season: int,
    episode: int,
    quality: str,
    file_id: str,
    file_type: str,
    caption: str | None,
    cover_id: str | None = None,
):
    await pool.execute(
        """
        INSERT INTO media_files
            (movie_id, season, episode, quality, file_id, file_type, caption, cover_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (movie_id, season, episode, quality)
        DO UPDATE SET file_id = $5, file_type = $6, caption = $7, cover_id = $8
        """,
        movie_id,
        season,
        episode,
        quality,
        file_id,
        file_type,
        caption,
        cover_id,
    )


async def delete_file(movie_id: int, season: int, episode: int, quality: str):
    await pool.execute(
        "DELETE FROM media_files WHERE movie_id=$1 AND season=$2 AND episode=$3 AND quality=$4",
        movie_id,
        season,
        episode,
        quality,
    )


async def change_quality(movie_id: int, season: int, episode: int, old: str, new: str):
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM media_files WHERE movie_id=$1 AND season=$2 AND episode=$3 AND quality=$4",
                movie_id,
                season,
                episode,
                new,
            )
            await conn.execute(
                "UPDATE media_files SET quality=$5 WHERE movie_id=$1 AND season=$2 AND episode=$3 AND quality=$4",
                movie_id,
                season,
                episode,
                old,
                new,
            )


async def get_file(movie_id: int, season: int, episode: int, quality: str):
    return await pool.fetchrow(
        """
        SELECT file_id, file_type, caption, cover_id FROM media_files
        WHERE movie_id=$1 AND season=$2 AND episode=$3 AND quality=$4
        """,
        movie_id,
        season,
        episode,
        quality,
    )


async def list_qualities(movie_id: int, season: int, episode: int) -> list[str]:
    rows = await pool.fetch(
        "SELECT quality FROM media_files WHERE movie_id=$1 AND season=$2 AND episode=$3",
        movie_id,
        season,
        episode,
    )
    return [r["quality"] for r in rows]


async def season_counts(movie_id: int) -> dict:
    rows = await pool.fetch(
        """
        SELECT season, count(DISTINCT episode) AS c FROM media_files
        WHERE movie_id=$1 AND season > 0 GROUP BY season ORDER BY season
        """,
        movie_id,
    )
    return {r["season"]: r["c"] for r in rows}


async def list_episodes(movie_id: int, season: int, offset: int, limit: int):
    return await pool.fetch(
        """
        SELECT DISTINCT episode FROM media_files
        WHERE movie_id=$1 AND season=$2 ORDER BY episode OFFSET $3 LIMIT $4
        """,
        movie_id,
        season,
        offset,
        limit,
    )


async def count_episodes(movie_id: int, season: int) -> int:
    return await pool.fetchval(
        "SELECT count(DISTINCT episode) FROM media_files WHERE movie_id=$1 AND season=$2",
        movie_id,
        season,
    )


async def max_episode(movie_id: int, season: int) -> int:
    return await pool.fetchval(
        "SELECT COALESCE(MAX(episode), 0) FROM media_files WHERE movie_id=$1 AND season=$2",
        movie_id,
        season,
    )


async def file_summary(movie_id: int):
    return await pool.fetch(
        """
        SELECT season, count(DISTINCT episode) AS eps, array_agg(DISTINCT quality) AS qs
        FROM media_files WHERE movie_id=$1 GROUP BY season ORDER BY season
        """,
        movie_id,
    )


# ---------- stats ----------
async def stats() -> dict:
    return {
        "users": await pool.fetchval("SELECT count(*) FROM users"),
        "users_day": await pool.fetchval(
            "SELECT count(*) FROM users WHERE joined_at > now() - interval '1 day'"
        ),
        "movies": await pool.fetchval("SELECT count(*) FROM movies WHERE NOT is_series"),
        "series": await pool.fetchval("SELECT count(*) FROM movies WHERE is_series"),
        "files": await pool.fetchval("SELECT count(*) FROM media_files"),
        "top": await pool.fetch(
            "SELECT title, views FROM movies WHERE views > 0 ORDER BY views DESC LIMIT 5"
        ),
    }


# ---------- favorites ----------
async def toggle_fav(user_id: int, movie_id: int) -> bool:
    """Qo'shilsa True, olib tashlansa False."""
    res = await pool.execute(
        "DELETE FROM favorites WHERE user_id=$1 AND movie_id=$2", user_id, movie_id
    )
    if res.endswith(" 0"):
        await pool.execute(
            "INSERT INTO favorites (user_id, movie_id) VALUES ($1, $2)", user_id, movie_id
        )
        return True
    return False


async def is_fav(user_id: int, movie_id: int) -> bool:
    return bool(
        await pool.fetchval(
            "SELECT 1 FROM favorites WHERE user_id=$1 AND movie_id=$2", user_id, movie_id
        )
    )


async def list_favs(user_id: int):
    return await pool.fetch(
        f"""
        SELECT {_LABEL_COLS} FROM favorites f
        JOIN movies m ON m.id = f.movie_id
        WHERE f.user_id=$1 AND NOT m.hidden ORDER BY m.id DESC LIMIT 30
        """,
        user_id,
    )
