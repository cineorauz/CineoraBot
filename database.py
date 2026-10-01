import asyncio
import logging
import secrets
import string
import time
from datetime import datetime, timezone

import asyncpg

pool: asyncpg.Pool | None = None

_ALPHABET = string.ascii_letters + string.digits
DEFAULT_PLANS = "30:29000:150,90:79000:400,365:249000:1400"

_MOVIE_FIELDS = [
    "title", "title_ru", "category", "is_series", "year", "genres", "rating", "rating_votes",
    "poster_url", "tmdb_id", "tmdb_type", "seasons_total", "episodes_total", "overview_en",
    "overview_ru", "overview_uz", "tagline_en", "tagline_ru", "tagline_uz", "runtime",
    "certification", "countries", "country_codes", "genre_tags", "imdb_id", "imdb_rating",
    "imdb_votes", "directors", "cast_top", "trailer_key", "is_premium", "audio", "series_status",
]
_LIST_FIELDS = {"genres", "countries", "country_codes", "genre_tags"}
_META_FIELDS = [
    "genres", "rating", "rating_votes", "poster_url", "overview_en", "overview_ru",
    "tagline_en", "tagline_ru", "runtime", "certification", "countries", "country_codes",
    "genre_tags", "directors", "cast_top", "trailer_key", "episodes_total",
]
_EDITABLE = {"overview_uz", "tagline_uz", "audio", "is_premium", "series_status"}

# Foydalanuvchiga ko'rinadigan kinolar: yashirilmagan va kamida bitta fayli bor
_VISIBLE = "NOT m.hidden AND EXISTS (SELECT 1 FROM media_files f WHERE f.movie_id = m.id)"
_LABEL_COLS = "m.id, m.title, m.year, m.is_series, m.imdb_rating, m.rating, m.is_premium"
_RATING_ORDER = (
    "COALESCE(NULLIF(split_part(m.imdb_rating, '/', 1), '')::numeric, m.rating::numeric, 0) DESC, m.id DESC"
)
_SORTS = {
    "n": "m.id DESC",
    "r": _RATING_ORDER,
    "a": "lower(m.title) ASC, m.id DESC",
    "v": "m.views DESC, m.id DESC",
}
_ADMIN_FILTERS = {
    "a": "TRUE",
    "m": "NOT m.is_series",
    "s": "m.is_series",
    "p": "m.is_premium",
    "h": "m.hidden",
    "e": "NOT EXISTS (SELECT 1 FROM media_files f WHERE f.movie_id = m.id)",
}

# ---------------- xotira keshlari (baza sekin bo'lsa ham bot tez ishlashi uchun) ----------------
_cache: dict = {}
_users: dict[int, dict] = {}
_favs: dict[int, set] = {}
_ratings: dict[int, dict] = {}
_reqs: dict[int, set] = {}
_settings: dict[str, str] = {}
_tasks: set = set()
_last_active = 0.0


def mark_active():
    global _last_active
    _last_active = time.monotonic()


def recently_active(seconds: int = 1200) -> bool:
    return time.monotonic() - _last_active < seconds


def bg(coro):
    """Muhim bo'lmagan yozuvlarni fonda bajaradi (foydalanuvchi kutib qolmaydi)."""
    task = asyncio.create_task(_run_bg(coro))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _run_bg(coro):
    try:
        await coro
    except Exception as e:
        logging.warning("Fon vazifasi xatosi: %s", e)


async def _cached(name: str, ttl: int, args: tuple, factory):
    key = (name, args)
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    value = await factory()
    if len(_cache) > 3000:
        _cache.clear()
    _cache[key] = (now + ttl, value)
    return value


def invalidate():
    _cache.clear()


def generate_code(length: int = 10) -> str:
    """Tasodifiy kod, masalan: k7Xp2mQaR9 (faqat ulashish havolasi uchun)."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def _like(query: str) -> str:
    safe = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{safe}%"


async def init(dsn: str):
    global pool
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10, command_timeout=30)
    await pool.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            lang TEXT,
            joined_at TIMESTAMPTZ DEFAULT now()
        );
        ALTER TABLE users ADD COLUMN IF NOT EXISTS premium_until TIMESTAMPTZ;
        ALTER TABLE users ADD COLUMN IF NOT EXISTS premium_reminded BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE users ADD COLUMN IF NOT EXISTS downloads INT NOT NULL DEFAULT 0;
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
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS episodes_total INT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS hidden BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS views INT NOT NULL DEFAULT 0;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS overview_en TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS overview_ru TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS overview_uz TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS tagline_en TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS tagline_ru TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS tagline_uz TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS title_ru TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS runtime INT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS certification TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS countries TEXT[];
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS country_codes TEXT[];
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS genre_tags TEXT[];
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS directors TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS cast_top TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS trailer_key TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS imdb_id TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS imdb_rating TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS imdb_votes INT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS rt_rating TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS meta_rating TEXT;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS is_premium BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS audio TEXT NOT NULL DEFAULT 'uz';
        ALTER TABLE movies ADD COLUMN IF NOT EXISTS series_status TEXT NOT NULL DEFAULT 'completed';
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
        ALTER TABLE media_files ADD COLUMN IF NOT EXISTS store_msg_id INT;
        CREATE TABLE IF NOT EXISTS ratings (
            user_id BIGINT NOT NULL,
            movie_id INT NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
            score SMALLINT NOT NULL CHECK (score BETWEEN 1 AND 10),
            created_at TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (user_id, movie_id)
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS requests (
            tmdb_type TEXT NOT NULL,
            tmdb_id INT NOT NULL,
            user_id BIGINT NOT NULL,
            title TEXT,
            year INT,
            notified BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (tmdb_type, tmdb_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            method TEXT,
            amount INT,
            currency TEXT,
            days INT,
            charge_id TEXT,
            created_at TIMESTAMPTZ DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS promo_codes (
            code TEXT PRIMARY KEY,
            days INT NOT NULL,
            max_uses INT NOT NULL DEFAULT 1,
            used INT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS promo_uses (
            code TEXT REFERENCES promo_codes(code) ON DELETE CASCADE,
            user_id BIGINT,
            PRIMARY KEY (code, user_id)
        );
        CREATE TABLE IF NOT EXISTS receipts (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            file_id TEXT,
            days INT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ DEFAULT now()
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

    for r in await pool.fetch("SELECT id FROM movies WHERE code IS NULL"):
        await pool.execute("UPDATE movies SET code=$1 WHERE id=$2", generate_code(), r["id"])
    await pool.execute(
        "INSERT INTO movie_titles (movie_id, title) SELECT id, title FROM movies ON CONFLICT DO NOTHING"
    )
    await pool.execute("CREATE UNIQUE INDEX IF NOT EXISTS movies_code_uidx ON movies(code)")

    for r in await pool.fetch("SELECT key, value FROM settings"):
        _settings[r["key"]] = r["value"]


async def ping() -> float:
    """Bazaga bitta so'rov yuborib, ketgan vaqtni (ms) qaytaradi."""
    t0 = time.perf_counter()
    await pool.fetchval("SELECT 1")
    return (time.perf_counter() - t0) * 1000


# ---------- sozlamalar ----------
def get_setting(key: str, default: str = "") -> str:
    return _settings.get(key, default)


async def set_setting(key: str, value: str):
    _settings[key] = value
    await pool.execute(
        "INSERT INTO settings (key, value) VALUES ($1, $2) "
        "ON CONFLICT (key) DO UPDATE SET value = $2",
        key,
        value,
    )


def parse_plans(text: str) -> list[dict]:
    plans = []
    for part in text.split(","):
        bits = part.strip().split(":")
        if len(bits) != 3:
            raise ValueError("format noto'g'ri")
        days, uzs, stars = (int(x) for x in bits)
        if days <= 0 or uzs < 0 or stars < 0:
            raise ValueError("qiymat noto'g'ri")
        plans.append({"days": days, "uzs": uzs, "stars": stars})
    if not plans:
        raise ValueError("bo'sh")
    return plans


def get_plans() -> list[dict]:
    try:
        return parse_plans(get_setting("plans", DEFAULT_PLANS))
    except ValueError:
        return parse_plans(DEFAULT_PLANS)


# ---------- users ----------
async def get_user(user_id: int) -> dict:
    u = _users.get(user_id)
    if u is None:
        row = await pool.fetchrow(
            "SELECT lang, premium_until, downloads FROM users WHERE user_id=$1", user_id
        )
        if row:
            u = {
                "lang": row["lang"],
                "premium_until": row["premium_until"],
                "downloads": row["downloads"],
                "exists": True,
            }
        else:
            u = {"lang": None, "premium_until": None, "downloads": 0, "exists": False}
        _users[user_id] = u
    return u


async def add_user(user_id: int):
    u = await get_user(user_id)
    if not u["exists"]:
        u["exists"] = True
        bg(pool.execute("INSERT INTO users (user_id) VALUES ($1) ON CONFLICT DO NOTHING", user_id))


async def get_lang(user_id: int):
    return (await get_user(user_id))["lang"]


async def set_lang(user_id: int, lang: str):
    await pool.execute(
        "INSERT INTO users (user_id, lang) VALUES ($1, $2) "
        "ON CONFLICT (user_id) DO UPDATE SET lang = $2",
        user_id,
        lang,
    )
    u = await get_user(user_id)
    u["lang"] = lang
    u["exists"] = True


async def premium_until(user_id: int):
    return (await get_user(user_id))["premium_until"]


async def is_premium(user_id: int) -> bool:
    until = await premium_until(user_id)
    return bool(until and until > datetime.now(timezone.utc))


async def grant_premium(
    user_id: int, days: int, method: str = "admin", amount: int = 0,
    currency: str = "", charge_id: str | None = None,
):
    until = await pool.fetchval(
        """
        INSERT INTO users (user_id, premium_until, premium_reminded)
        VALUES ($1, now() + make_interval(days => $2), FALSE)
        ON CONFLICT (user_id) DO UPDATE SET
            premium_until = GREATEST(COALESCE(users.premium_until, now()), now()) + make_interval(days => $2),
            premium_reminded = FALSE
        RETURNING premium_until
        """,
        user_id,
        days,
    )
    u = await get_user(user_id)
    u["premium_until"] = until
    u["exists"] = True
    await pool.execute(
        "INSERT INTO payments (user_id, method, amount, currency, days, charge_id) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        user_id, method, amount, currency, days, charge_id,
    )
    return until


async def revoke_premium(user_id: int):
    await pool.execute("UPDATE users SET premium_until = NULL WHERE user_id=$1", user_id)
    u = await get_user(user_id)
    u["premium_until"] = None


def bump_downloads(user_id: int):
    u = _users.get(user_id)
    if u:
        u["downloads"] += 1
    bg(pool.execute("UPDATE users SET downloads = downloads + 1 WHERE user_id=$1", user_id))


async def expiring_users():
    return await pool.fetch(
        """
        SELECT user_id, lang, premium_until FROM users
        WHERE premium_until > now() AND premium_until < now() + interval '3 days'
          AND NOT premium_reminded
        """
    )


async def mark_reminded(user_id: int):
    await pool.execute("UPDATE users SET premium_reminded = TRUE WHERE user_id=$1", user_id)


async def premium_stats() -> dict:
    return {
        "active": await pool.fetchval("SELECT count(*) FROM users WHERE premium_until > now()"),
        "pending": await pool.fetchval("SELECT count(*) FROM receipts WHERE status='pending'"),
        "stars": await pool.fetchval(
            "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE currency='XTR'"
        ),
        "uzs": await pool.fetchval(
            "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE currency='UZS'"
        ),
    }


# ---------- promo-kodlar va cheklar ----------
async def create_promo(days: int, max_uses: int) -> str:
    code = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
    await pool.execute(
        "INSERT INTO promo_codes (code, days, max_uses) VALUES ($1, $2, $3)", code, days, max_uses
    )
    return code


async def list_promos():
    return await pool.fetch(
        "SELECT code, days, max_uses, used FROM promo_codes ORDER BY created_at DESC LIMIT 15"
    )


async def redeem_promo(code: str, user_id: int):
    """(kunlar, xato) qaytaradi. xato: bad | used_up | already"""
    code = code.strip().upper()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT days, max_uses, used FROM promo_codes WHERE code=$1 FOR UPDATE", code
            )
            if not row:
                return None, "bad"
            if row["used"] >= row["max_uses"]:
                return None, "used_up"
            got = await conn.fetchval(
                "INSERT INTO promo_uses (code, user_id) VALUES ($1, $2) "
                "ON CONFLICT DO NOTHING RETURNING 1",
                code,
                user_id,
            )
            if not got:
                return None, "already"
            await conn.execute("UPDATE promo_codes SET used = used + 1 WHERE code=$1", code)
            return row["days"], None


async def add_receipt(user_id: int, file_id: str, days: int) -> int:
    return await pool.fetchval(
        "INSERT INTO receipts (user_id, file_id, days) VALUES ($1, $2, $3) RETURNING id",
        user_id, file_id, days,
    )


async def resolve_receipt(receipt_id: int, status: str):
    """Faqat kutilayotgan chekni hal qiladi (ikki admin bir vaqtda bosib yubormasligi uchun)."""
    return await pool.fetchrow(
        "UPDATE receipts SET status=$2 WHERE id=$1 AND status='pending' RETURNING user_id, days",
        receipt_id,
        status,
    )


# ---------- movies ----------
async def create_movie(d: dict):
    """Yangi kino/serial yaratadi va (id, kod) qaytaradi."""
    values = []
    for f in _MOVIE_FIELDS:
        v = d.get(f)
        if f in _LIST_FIELDS:
            v = v or []
        elif f in ("is_series", "is_premium"):
            v = bool(v)
        elif f == "seasons_total":
            v = v or 0
        elif f == "audio":
            v = v or "uz"
        elif f == "series_status":
            v = v or "completed"
        values.append(v)
    cols = ", ".join(_MOVIE_FIELDS + ["code"])
    marks = ", ".join(f"${i}" for i in range(1, len(_MOVIE_FIELDS) + 2))
    for _ in range(5):
        code = generate_code()
        try:
            movie_id = await pool.fetchval(
                f"INSERT INTO movies ({cols}) VALUES ({marks}) RETURNING id", *values, code
            )
        except asyncpg.UniqueViolationError:
            continue
        for name in {d["title"], *d.get("aliases", [])}:
            name = (name or "").strip()
            if name:
                await pool.execute(
                    "INSERT INTO movie_titles (movie_id, title) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    movie_id, name,
                )
        invalidate()
        return movie_id, code
    raise RuntimeError("Kod yaratib bo'lmadi")


async def update_meta(movie_id: int, d: dict):
    """TMDB/OMDb ma'lumotlarini yangilaydi (nom, kategoriya, premium, til, o'zbekcha matn o'zgarmaydi)."""
    n = len(_META_FIELDS)
    purl = _META_FIELDS.index("poster_url") + 2
    sets = [f"poster_id = CASE WHEN poster_url IS DISTINCT FROM ${purl} THEN NULL ELSE poster_id END"]
    sets += [f"{f} = ${i + 2}" for i, f in enumerate(_META_FIELDS)]
    sets += [
        f"year = COALESCE(${n + 2}, year)",
        f"imdb_id = COALESCE(${n + 3}, imdb_id)",
        f"imdb_rating = COALESCE(${n + 4}, imdb_rating)",
        f"imdb_votes = COALESCE(${n + 5}, imdb_votes)",
        f"title_ru = COALESCE(${n + 6}, title_ru)",
        f"seasons_total = GREATEST(seasons_total, ${n + 7})",
    ]
    values = []
    for f in _META_FIELDS:
        v = d.get(f)
        if f in _LIST_FIELDS:
            v = v or []
        values.append(v)
    values += [
        d.get("year"), d.get("imdb_id"), d.get("imdb_rating"), d.get("imdb_votes"),
        d.get("title_ru"), d.get("seasons_total") or 0,
    ]
    await pool.execute(f"UPDATE movies SET {', '.join(sets)} WHERE id = $1", movie_id, *values)
    for name in d.get("aliases", []):
        if name:
            await pool.execute(
                "INSERT INTO movie_titles (movie_id, title) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                movie_id, name,
            )
    invalidate()


async def get_movie(movie_id: int):
    return await _cached(
        "movie", 600, (movie_id,), lambda: pool.fetchrow("SELECT * FROM movies WHERE id=$1", movie_id)
    )


async def get_movie_by_code(code: str):
    """Ulashish havolasi uchun (yashirin kinolar chiqmaydi)."""
    return await _cached(
        "bycode", 600, (code,),
        lambda: pool.fetchrow("SELECT * FROM movies WHERE code=$1 AND NOT hidden", code),
    )


async def movies_by_ids(ids: tuple):
    if not ids:
        return []
    return await _cached(
        "byids", 120, (ids,),
        lambda: pool.fetch(
            f"SELECT {_LABEL_COLS} FROM movies m WHERE m.id = ANY($1::int[]) AND NOT m.hidden "
            "ORDER BY m.id DESC",
            list(ids),
        ),
    )


async def movies_by_tmdb(pairs) -> dict:
    """{(tur, tmdb_id): kino} — botda mavjud (fayli bor) kinolar."""
    ids = tuple(sorted({p[1] for p in pairs}))
    if not ids:
        return {}
    rows = await _cached(
        "bytmdb", 120, (ids,),
        lambda: pool.fetch(
            f"SELECT {_LABEL_COLS}, m.tmdb_id, m.tmdb_type FROM movies m "
            f"WHERE m.tmdb_id = ANY($1::int[]) AND {_VISIBLE}",
            list(ids),
        ),
    )
    return {(r["tmdb_type"], r["tmdb_id"]): r for r in rows}


async def add_alias(movie_id: int, title: str):
    await pool.execute(
        "INSERT INTO movie_titles (movie_id, title) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        movie_id, title,
    )
    invalidate()


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
    invalidate()


async def set_seasons_total(movie_id: int, total: int):
    await pool.execute("UPDATE movies SET seasons_total=$1 WHERE id=$2", total, movie_id)
    invalidate()


async def set_poster_id(movie_id: int, file_id: str):
    await pool.execute("UPDATE movies SET poster_id=$1 WHERE id=$2", file_id, movie_id)
    invalidate()


async def set_field(movie_id: int, field: str, value):
    if field not in _EDITABLE:
        raise ValueError("Ruxsat etilmagan maydon")
    await pool.execute(f"UPDATE movies SET {field}=$1 WHERE id=$2", value, movie_id)
    invalidate()


async def toggle_premium(movie_id: int) -> bool:
    val = await pool.fetchval(
        "UPDATE movies SET is_premium = NOT is_premium WHERE id=$1 RETURNING is_premium", movie_id
    )
    invalidate()
    return val


async def toggle_series_status(movie_id: int) -> str:
    val = await pool.fetchval(
        "UPDATE movies SET series_status = CASE WHEN series_status = 'ongoing' THEN 'completed' "
        "ELSE 'ongoing' END WHERE id=$1 RETURNING series_status",
        movie_id,
    )
    invalidate()
    return val


async def toggle_hidden(movie_id: int) -> bool:
    val = await pool.fetchval(
        "UPDATE movies SET hidden = NOT hidden WHERE id=$1 RETURNING hidden", movie_id
    )
    invalidate()
    return val


async def delete_movie(movie_id: int) -> bool:
    res = await pool.execute("DELETE FROM movies WHERE id=$1", movie_id)
    invalidate()
    return res.endswith(" 1")


def add_view(movie_id: int):
    bg(pool.execute("UPDATE movies SET views = views + 1 WHERE id=$1", movie_id))


async def admin_movies(filter_code: str, query: str, offset: int, limit: int):
    """Admin ro'yxati (yashirinlar ham). filtr: a/m/s/p/h/e. (qatorlar, jami) qaytaradi."""
    where = _ADMIN_FILTERS.get(filter_code, "TRUE")
    args = []
    if query:
        where += (
            " AND EXISTS (SELECT 1 FROM movie_titles t WHERE t.movie_id = m.id AND t.title ILIKE $1)"
        )
        args = [_like(query)]
    n = len(args)
    rows = await pool.fetch(
        f"""
        SELECT m.id, m.title, m.year, m.is_series, m.hidden, m.is_premium,
            (SELECT array_agg(DISTINCT f.quality) FROM media_files f
                WHERE f.movie_id = m.id AND f.season = 0) AS qs,
            (SELECT count(DISTINCT (f.season, f.episode)) FROM media_files f
                WHERE f.movie_id = m.id AND f.season > 0) AS eps
        FROM movies m WHERE {where} ORDER BY m.id DESC OFFSET ${n + 1} LIMIT ${n + 2}
        """,
        *args, offset, limit,
    )
    total = await pool.fetchval(f"SELECT count(*) FROM movies m WHERE {where}", *args)
    return rows, total


# ---------- foydalanuvchi uchun qidiruv va ko'rish ----------
async def search_movies(query: str, offset: int = 0, limit: int = 8):
    return await _cached(
        "search", 60, (query.lower(), offset, limit),
        lambda: pool.fetch(
            f"""
            SELECT DISTINCT {_LABEL_COLS} FROM movies m
            JOIN movie_titles t ON t.movie_id = m.id
            WHERE t.title ILIKE $1 AND {_VISIBLE}
            ORDER BY m.id DESC OFFSET $2 LIMIT $3
            """,
            _like(query), offset, limit,
        ),
    )


async def inline_search(query: str, limit: int = 20):
    """Inline rejim uchun: to'liq qatorlar (poster, kod va h.k.)."""
    return await _cached(
        "isearch", 60, (query.lower(), limit),
        lambda: pool.fetch(
            f"""
            SELECT m.* FROM movies m
            WHERE m.id IN (SELECT t.movie_id FROM movie_titles t WHERE t.title ILIKE $1)
              AND {_VISIBLE}
            ORDER BY m.id DESC LIMIT $2
            """,
            _like(query), limit,
        ),
    )


async def inline_default(limit: int = 20):
    """So'rov bo'sh bo'lganda: eng yuqori reytingli va eng yangi kontent."""

    async def load():
        half = max(1, limit // 2)
        top = await pool.fetch(
            f"SELECT m.* FROM movies m WHERE {_VISIBLE} ORDER BY {_RATING_ORDER} LIMIT $1", half
        )
        new = await pool.fetch(
            f"SELECT m.* FROM movies m WHERE {_VISIBLE} ORDER BY m.id DESC LIMIT $1", half
        )
        seen, out = set(), []
        for r in list(new) + list(top):
            if r["id"] not in seen:
                seen.add(r["id"])
                out.append(r)
        return out[:limit]

    return await _cached("idefault", 60, (limit,), load)


async def browse(kind: str, value, offset: int, limit: int, sort: str = "n"):
    """kind: c=kategoriya, g=janr (hashtag), y=o'nyillik, p=reyting bo'yicha, n=yangi. sort: n/r/a/v."""

    async def load():
        where = _VISIBLE
        args = []
        order = _SORTS.get(sort, _SORTS["n"])
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
            order = _RATING_ORDER
        elif kind == "n":
            order = _SORTS["n"]
        n = len(args)
        rows = await pool.fetch(
            f"SELECT {_LABEL_COLS} FROM movies m WHERE {where} "
            f"ORDER BY {order} OFFSET ${n + 1} LIMIT ${n + 2}",
            *args, offset, limit,
        )
        total = await pool.fetchval(f"SELECT count(*) FROM movies m WHERE {where}", *args)
        return rows, total

    return await _cached("browse", 60, (kind, str(value), offset, limit, sort), load)


async def category_counts() -> dict:
    async def load():
        rows = await pool.fetch(
            f"SELECT m.category, count(*) AS c FROM movies m "
            f"WHERE {_VISIBLE} AND m.category IS NOT NULL GROUP BY m.category"
        )
        return {r["category"]: r["c"] for r in rows}

    return await _cached("catcounts", 60, (), load)


async def genre_counts():
    return await _cached(
        "gencounts", 60, (),
        lambda: pool.fetch(
            f"SELECT g AS tag, count(*) AS c FROM movies m, unnest(m.genre_tags) AS g "
            f"WHERE {_VISIBLE} GROUP BY g ORDER BY c DESC, g"
        ),
    )


async def decade_counts():
    return await _cached(
        "deccounts", 60, (),
        lambda: pool.fetch(
            f"SELECT (m.year / 10 * 10) AS dec, count(*) AS c FROM movies m "
            f"WHERE {_VISIBLE} AND m.year IS NOT NULL GROUP BY dec ORDER BY dec DESC"
        ),
    )


async def random_movie():
    return await pool.fetchrow(f"SELECT m.* FROM movies m WHERE {_VISIBLE} ORDER BY random() LIMIT 1")


# ---------- files ----------
async def save_file(
    movie_id: int, season: int, episode: int, quality: str, file_id: str,
    file_type: str, caption: str | None, cover_id: str | None = None,
):
    await pool.execute(
        """
        INSERT INTO media_files
            (movie_id, season, episode, quality, file_id, file_type, caption, cover_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (movie_id, season, episode, quality)
        DO UPDATE SET file_id = $5, file_type = $6, caption = $7, cover_id = $8
        """,
        movie_id, season, episode, quality, file_id, file_type, caption, cover_id,
    )
    invalidate()


async def set_store_msg(movie_id: int, season: int, episode: int, quality: str, msg_id: int):
    """Zaxira kanaldagi nusxaning xabar ID sini saqlaydi."""
    await pool.execute(
        "UPDATE media_files SET store_msg_id=$5 "
        "WHERE movie_id=$1 AND season=$2 AND episode=$3 AND quality=$4",
        movie_id, season, episode, quality, msg_id,
    )


async def delete_file(movie_id: int, season: int, episode: int, quality: str):
    await pool.execute(
        "DELETE FROM media_files WHERE movie_id=$1 AND season=$2 AND episode=$3 AND quality=$4",
        movie_id, season, episode, quality,
    )
    invalidate()


async def change_quality(movie_id: int, season: int, episode: int, old: str, new: str):
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM media_files WHERE movie_id=$1 AND season=$2 AND episode=$3 AND quality=$4",
                movie_id, season, episode, new,
            )
            await conn.execute(
                "UPDATE media_files SET quality=$5 WHERE movie_id=$1 AND season=$2 AND episode=$3 AND quality=$4",
                movie_id, season, episode, old, new,
            )
    invalidate()


async def get_file(movie_id: int, season: int, episode: int, quality: str):
    return await _cached(
        "file", 600, (movie_id, season, episode, quality),
        lambda: pool.fetchrow(
            "SELECT file_id, file_type, cover_id FROM media_files "
            "WHERE movie_id=$1 AND season=$2 AND episode=$3 AND quality=$4",
            movie_id, season, episode, quality,
        ),
    )


async def list_qualities(movie_id: int, season: int, episode: int) -> list[str]:
    async def load():
        rows = await pool.fetch(
            "SELECT quality FROM media_files WHERE movie_id=$1 AND season=$2 AND episode=$3",
            movie_id, season, episode,
        )
        return [r["quality"] for r in rows]

    return await _cached("quals", 300, (movie_id, season, episode), load)


async def season_counts(movie_id: int) -> dict:
    async def load():
        rows = await pool.fetch(
            "SELECT season, count(DISTINCT episode) AS c FROM media_files "
            "WHERE movie_id=$1 AND season > 0 GROUP BY season ORDER BY season",
            movie_id,
        )
        return {r["season"]: r["c"] for r in rows}

    return await _cached("seasons", 300, (movie_id,), load)


async def list_episodes(movie_id: int, season: int, offset: int, limit: int):
    return await _cached(
        "eps", 300, (movie_id, season, offset, limit),
        lambda: pool.fetch(
            "SELECT DISTINCT episode FROM media_files WHERE movie_id=$1 AND season=$2 "
            "ORDER BY episode OFFSET $3 LIMIT $4",
            movie_id, season, offset, limit,
        ),
    )


async def count_episodes(movie_id: int, season: int) -> int:
    return await _cached(
        "epcount", 300, (movie_id, season),
        lambda: pool.fetchval(
            "SELECT count(DISTINCT episode) FROM media_files WHERE movie_id=$1 AND season=$2",
            movie_id, season,
        ),
    )


async def max_episode(movie_id: int, season: int) -> int:
    return await pool.fetchval(
        "SELECT COALESCE(MAX(episode), 0) FROM media_files WHERE movie_id=$1 AND season=$2",
        movie_id, season,
    )


async def file_summary(movie_id: int):
    return await pool.fetch(
        "SELECT season, count(DISTINCT episode) AS eps, array_agg(DISTINCT quality) AS qs "
        "FROM media_files WHERE movie_id=$1 GROUP BY season ORDER BY season",
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
        "premium_movies": await pool.fetchval("SELECT count(*) FROM movies WHERE is_premium"),
        "files": await pool.fetchval("SELECT count(*) FROM media_files"),
        "requests": await pool.fetchval(
            "SELECT count(DISTINCT (tmdb_type, tmdb_id)) FROM requests WHERE NOT notified"
        ),
        "top": await pool.fetch(
            "SELECT title, views FROM movies WHERE views > 0 ORDER BY views DESC LIMIT 5"
        ),
    }


# ---------- favorites (Ko'rmoqchiman) ----------
async def _load_favs(user_id: int) -> set:
    s = _favs.get(user_id)
    if s is None:
        rows = await pool.fetch("SELECT movie_id FROM favorites WHERE user_id=$1", user_id)
        s = _favs[user_id] = {r["movie_id"] for r in rows}
    return s


async def is_fav(user_id: int, movie_id: int) -> bool:
    return movie_id in await _load_favs(user_id)


async def fav_count(user_id: int) -> int:
    return len(await _load_favs(user_id))


async def toggle_fav(user_id: int, movie_id: int) -> bool:
    """Qo'shilsa True, olib tashlansa False. Baza fonda yangilanadi."""
    s = await _load_favs(user_id)
    if movie_id in s:
        s.discard(movie_id)
        bg(pool.execute("DELETE FROM favorites WHERE user_id=$1 AND movie_id=$2", user_id, movie_id))
        return False
    s.add(movie_id)
    bg(
        pool.execute(
            "INSERT INTO favorites (user_id, movie_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            user_id, movie_id,
        )
    )
    return True


async def list_favs(user_id: int):
    s = await _load_favs(user_id)
    return await movies_by_ids(tuple(sorted(s, reverse=True)[:100]))


# ---------- baholar (1–10) ----------
async def _load_ratings(user_id: int) -> dict:
    r = _ratings.get(user_id)
    if r is None:
        rows = await pool.fetch("SELECT movie_id, score FROM ratings WHERE user_id=$1", user_id)
        r = _ratings[user_id] = {x["movie_id"]: x["score"] for x in rows}
    return r


async def get_rating(user_id: int, movie_id: int):
    return (await _load_ratings(user_id)).get(movie_id)


async def rated_count(user_id: int) -> int:
    return len(await _load_ratings(user_id))


async def set_rating(user_id: int, movie_id: int, score: int):
    """score 1–10; 0 bo'lsa baho olib tashlanadi."""
    r = await _load_ratings(user_id)
    if score <= 0:
        r.pop(movie_id, None)
        await pool.execute("DELETE FROM ratings WHERE user_id=$1 AND movie_id=$2", user_id, movie_id)
    else:
        r[movie_id] = score
        await pool.execute(
            "INSERT INTO ratings (user_id, movie_id, score) VALUES ($1, $2, $3) "
            "ON CONFLICT (user_id, movie_id) DO UPDATE SET score = $3, created_at = now()",
            user_id, movie_id, score,
        )
    invalidate()


async def rating_stats(movie_id: int):
    return await _cached(
        "rstats", 120, (movie_id,),
        lambda: pool.fetchrow(
            "SELECT COALESCE(AVG(score), 0)::float AS avg, count(*) AS cnt FROM ratings WHERE movie_id=$1",
            movie_id,
        ),
    )


async def list_rated(user_id: int):
    return await _cached(
        "rated", 60, (user_id,),
        lambda: pool.fetch(
            f"SELECT {_LABEL_COLS}, r.score AS my_score FROM ratings r "
            "JOIN movies m ON m.id = r.movie_id "
            "WHERE r.user_id=$1 AND NOT m.hidden ORDER BY r.created_at DESC LIMIT 100",
            user_id,
        ),
    )


# ---------- so'rovlar (yuklanmagan kontent uchun) ----------
async def _load_reqs(user_id: int) -> set:
    s = _reqs.get(user_id)
    if s is None:
        rows = await pool.fetch(
            "SELECT tmdb_type, tmdb_id FROM requests WHERE user_id=$1 AND NOT notified", user_id
        )
        s = _reqs[user_id] = {(r["tmdb_type"], r["tmdb_id"]) for r in rows}
    return s


async def has_request(user_id: int, tmdb_type: str, tmdb_id: int) -> bool:
    return (tmdb_type, tmdb_id) in await _load_reqs(user_id)


async def toggle_request(user_id: int, tmdb_type: str, tmdb_id: int, title: str, year) -> bool:
    s = await _load_reqs(user_id)
    key = (tmdb_type, tmdb_id)
    if key in s:
        s.discard(key)
        bg(
            pool.execute(
                "DELETE FROM requests WHERE tmdb_type=$1 AND tmdb_id=$2 AND user_id=$3",
                tmdb_type, tmdb_id, user_id,
            )
        )
        return False
    s.add(key)
    bg(
        pool.execute(
            "INSERT INTO requests (tmdb_type, tmdb_id, user_id, title, year) VALUES ($1, $2, $3, $4, $5) "
            "ON CONFLICT (tmdb_type, tmdb_id, user_id) DO UPDATE SET notified = FALSE, title = $4, year = $5",
            tmdb_type, tmdb_id, user_id, title, year,
        )
    )
    return True


async def requesters(tmdb_type: str, tmdb_id: int):
    return await pool.fetch(
        "SELECT r.user_id, COALESCE(u.lang, 'uz') AS lang FROM requests r "
        "LEFT JOIN users u ON u.user_id = r.user_id "
        "WHERE r.tmdb_type=$1 AND r.tmdb_id=$2 AND NOT r.notified",
        tmdb_type, tmdb_id,
    )


async def mark_notified(tmdb_type: str, tmdb_id: int):
    await pool.execute(
        "UPDATE requests SET notified = TRUE WHERE tmdb_type=$1 AND tmdb_id=$2", tmdb_type, tmdb_id
    )
    _reqs.clear()


async def pending_requests(limit: int = 15):
    return await pool.fetch(
        "SELECT tmdb_type, tmdb_id, max(title) AS title, max(year) AS year, count(*) AS c "
        "FROM requests WHERE NOT notified GROUP BY tmdb_type, tmdb_id "
        "ORDER BY c DESC, max(created_at) DESC LIMIT $1",
        limit,
    )
