import asyncpg

pool: asyncpg.Pool | None = None


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
            poster_id TEXT,
            created_at TIMESTAMPTZ DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS movie_files (
            movie_id INT REFERENCES movies(id) ON DELETE CASCADE,
            quality TEXT NOT NULL,
            file_id TEXT NOT NULL,
            file_type TEXT NOT NULL,
            PRIMARY KEY (movie_id, quality)
        );
        CREATE TABLE IF NOT EXISTS favorites (
            user_id BIGINT,
            movie_id INT REFERENCES movies(id) ON DELETE CASCADE,
            PRIMARY KEY (user_id, movie_id)
        );
        """
    )
    await pool.execute("ALTER TABLE movie_files ADD COLUMN IF NOT EXISTS caption TEXT")


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


async def count_users() -> int:
    return await pool.fetchval("SELECT count(*) FROM users")


# ---------- movies ----------
async def add_movie(title: str, poster_id: str | None) -> int:
    return await pool.fetchval(
        "INSERT INTO movies (title, poster_id) VALUES ($1, $2) RETURNING id",
        title,
        poster_id,
    )


async def add_file(
    movie_id: int, quality: str, file_id: str, file_type: str, caption: str | None = None
):
    await pool.execute(
        """
        INSERT INTO movie_files (movie_id, quality, file_id, file_type, caption)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (movie_id, quality)
        DO UPDATE SET file_id = $3, file_type = $4, caption = $5
        """,
        movie_id,
        quality,
        file_id,
        file_type,
        caption,
    )


async def get_movie(movie_id: int):
    return await pool.fetchrow("SELECT * FROM movies WHERE id=$1", movie_id)


async def get_files(movie_id: int) -> dict:
    rows = await pool.fetch(
        "SELECT quality, file_id, file_type, caption FROM movie_files WHERE movie_id=$1",
        movie_id,
    )
    return {
        r["quality"]: {
            "file_id": r["file_id"],
            "file_type": r["file_type"],
            "caption": r["caption"],
        }
        for r in rows
    }


async def search_movies(query: str, limit: int = 8):
    return await pool.fetch(
        "SELECT id, title FROM movies WHERE title ILIKE $1 ORDER BY id DESC LIMIT $2",
        f"%{query}%",
        limit,
    )


async def delete_movie(movie_id: int) -> bool:
    res = await pool.execute("DELETE FROM movies WHERE id=$1", movie_id)
    return res.endswith(" 1")


async def count_movies() -> int:
    return await pool.fetchval("SELECT count(*) FROM movies")


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
        WHERE f.user_id=$1 ORDER BY m.id DESC LIMIT 30
        """,
        user_id,
    )
