import logging
import secrets
import string

import asyncpg

pool: asyncpg.Pool | None = None

_ALPHABET = string.ascii_letters + string.digits


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
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS poster_url TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS tmdb_id INT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS tmdb_type TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS seasons_total INT NOT NULL DEFAULT 0;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS hidden BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS views INT NOT NULL DEFAULT 0;
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
    for _ in range(5):
        code = generate_code()
        try:
            movie_id = await pool.fetchval(
                """
                INSERT INTO movies
                    (title, category, is_series, year, genres, rating, poster_url,
                     tmdb_id, tmdb_type, seasons_total, code)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                RETURNING id
                """,
                d["title"],
                d.get("category"),
                bool(d.get("is_series")),
                d.get("year"),
                d.get("genres") or [],
                d.get("rating"),
                d.get("poster_url"),
                d.get("tmdb_id"),
                d.get("tmdb_type"),
                d.get("seasons_total") or 0,
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


async def search_movies(query: str, offset: int = 0, limit: int = 8):
    safe = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return await pool.fetch(
        """
        SELECT DISTINCT m.id, m.title FROM movies m
        JOIN movie_titles t ON t.movie_id = m.id
        WHERE t.title ILIKE $1 AND NOT m.hidden
        ORDER BY m.id DESC OFFSET $2 LIMIT $3
        """,
        f"%{safe}%",
        offset,
        limit,
    )


async def list_movies(offset: int = 0, limit: int = 8):
    return await pool.fetch(
        "SELECT id, title, hidden, is_series FROM movies ORDER BY id DESC OFFSET $1 LIMIT $2",
        offset,
        limit,
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
):
    await pool.execute(
        """
        INSERT INTO media_files (movie_id, season, episode, quality, file_id, file_type, caption)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (movie_id, season, episode, quality)
        DO UPDATE SET file_id = $5, file_type = $6, caption = $7
        """,
        movie_id,
        season,
        episode,
        quality,
        file_id,
        file_type,
        caption,
    )


async def delete_file(movie_id: int, season: int, episode: int, quality: str):
    await pool.execute(
        "DELETE FROM media_files WHERE movie_id=$1 AND season=$2 AND episode=$3 AND quality=$4",
        movie_id,
        season,
        episode,
        quality,
    )


async def get_file(movie_id: int, season: int, episode: int, quality: str):
    return await pool.fetchrow(
        """
        SELECT file_id, file_type, caption FROM media_files
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
        """
        SELECT m.id, m.title FROM favorites f
        JOIN movies m ON m.id = f.movie_id
        WHERE f.user_id=$1 AND NOT m.hidden ORDER BY m.id DESC LIMIT 30
        """,
        user_id,
    )
