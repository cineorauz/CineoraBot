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
        )
        """
    )


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
