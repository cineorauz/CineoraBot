import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

import database as db

_banned: set[int] = set()
_seen: dict[int, float] = {}
_progress: dict[int, dict | None] = {}

_AUD = {
    "all": "TRUE",
    "prem": "premium_until > now()",
    "free": "(premium_until IS NULL OR premium_until <= now())",
    "uz": "lang = 'uz'",
    "en": "lang = 'en'",
    "ru": "lang = 'ru'",
}


async def init():
    """Qo'shimcha jadvallar va ustunlar (database.py'ga tegmaydi)."""
    await db.pool.execute(
        """
        ALTER TABLE users ADD COLUMN IF NOT EXISTS banned BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE users ADD COLUMN IF NOT EXISTS blocked BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ;
        ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name TEXT;
        ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT;
        CREATE TABLE IF NOT EXISTS progress (
            user_id BIGINT NOT NULL,
            movie_id INT NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
            season INT NOT NULL,
            episode INT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, movie_id)
        );
        CREATE TABLE IF NOT EXISTS downloads_log (
            movie_id INT,
            user_id BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS downloads_log_time_idx ON downloads_log(created_at);
        CREATE TABLE IF NOT EXISTS searches (
            q TEXT NOT NULL,
            found BOOLEAN NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS searches_time_idx ON searches(created_at);
        """
    )
    rows = await db.pool.fetch("SELECT user_id FROM users WHERE banned")
    _banned.update(r["user_id"] for r in rows)


# ---------- bloklash va faollik ----------
def is_banned(uid: int) -> bool:
    return uid in _banned


async def set_banned(uid: int, value: bool):
    await db.pool.execute("UPDATE users SET banned=$2 WHERE user_id=$1", uid, value)
    if value:
        _banned.add(uid)
    else:
        _banned.discard(uid)


def touch(uid: int):
    _seen[uid] = time.time()


async def flush_seen():
    """Oxirgi faollik vaqtlarini bazaga bitta so'rovda yozadi."""
    if not _seen:
        return
    items = list(_seen.items())
    _seen.clear()
    ids = [i for i, _ in items]
    times = [datetime.fromtimestamp(t, timezone.utc) for _, t in items]
    await db.pool.execute(
        "UPDATE users u SET last_seen = x.t FROM unnest($1::bigint[], $2::timestamptz[]) AS x(id, t) "
        "WHERE u.user_id = x.id",
        ids,
        times,
    )


def set_profile(uid: int, first_name: str | None, username: str | None):
    db.bg(
        db.pool.execute(
            "INSERT INTO users (user_id, first_name, username) VALUES ($1, $2, $3) "
            "ON CONFLICT (user_id) DO UPDATE SET first_name = $2, username = $3, blocked = FALSE",
            uid, first_name, username,
        )
    )


def mark_blocked(uid: int):
    db.bg(db.pool.execute("UPDATE users SET blocked = TRUE WHERE user_id=$1", uid))


# ---------- jurnallar (statistika uchun) ----------
def log_search(q: str, found: bool):
    db.bg(db.pool.execute("INSERT INTO searches (q, found) VALUES ($1, $2)", q[:80], found))


def log_download(movie_id: int, uid: int):
    db.bg(db.pool.execute("INSERT INTO downloads_log (movie_id, user_id) VALUES ($1, $2)", movie_id, uid))


# ---------- davom ettirish ----------
def set_progress(uid: int, movie_id: int, season: int, episode: int):
    _progress[uid] = {"movie_id": movie_id, "season": season, "episode": episode}
    db.bg(
        db.pool.execute(
            "INSERT INTO progress (user_id, movie_id, season, episode) VALUES ($1, $2, $3, $4) "
            "ON CONFLICT (user_id, movie_id) DO UPDATE SET season = $3, episode = $4, updated_at = now()",
            uid, movie_id, season, episode,
        )
    )


async def latest_progress(uid: int):
    if uid not in _progress:
        row = await db.pool.fetchrow(
            "SELECT movie_id, season, episode FROM progress WHERE user_id=$1 "
            "ORDER BY updated_at DESC LIMIT 1",
            uid,
        )
        _progress[uid] = dict(row) if row else None
    return _progress[uid]


async def get_progress(uid: int, movie_id: int):
    cur = await latest_progress(uid)
    if cur and cur["movie_id"] == movie_id:
        return cur
    row = await db.pool.fetchrow(
        "SELECT season, episode FROM progress WHERE user_id=$1 AND movie_id=$2", uid, movie_id
    )
    return {"movie_id": movie_id, "season": row["season"], "episode": row["episode"]} if row else None


async def neighbors(movie_id: int, season: int, episode: int):
    """((oldingi fasl, qism) | None, (keyingi fasl, qism) | None). Fasl chegarasidan ham o'tadi."""

    async def load():
        prev = await db.pool.fetchrow(
            "SELECT season, episode FROM media_files WHERE movie_id=$1 AND season > 0 "
            "AND (season, episode) < ($2, $3) GROUP BY season, episode "
            "ORDER BY season DESC, episode DESC LIMIT 1",
            movie_id, season, episode,
        )
        nxt = await db.pool.fetchrow(
            "SELECT season, episode FROM media_files WHERE movie_id=$1 AND season > 0 "
            "AND (season, episode) > ($2, $3) GROUP BY season, episode "
            "ORDER BY season, episode LIMIT 1",
            movie_id, season, episode,
        )
        return (
            (prev["season"], prev["episode"]) if prev else None,
            (nxt["season"], nxt["episode"]) if nxt else None,
        )

    return await db._cached("neigh", 300, (movie_id, season, episode), load)


async def followers(movie_id: int):
    """Serialni «Ko'rmoqchiman»ga qo'shgan yoki ko'rayotgan foydalanuvchilar."""
    return await db.pool.fetch(
        """
        SELECT u.user_id, COALESCE(u.lang, 'uz') AS lang FROM users u
        WHERE NOT u.blocked AND NOT u.banned AND u.user_id IN (
            SELECT user_id FROM favorites WHERE movie_id = $1
            UNION SELECT user_id FROM progress WHERE movie_id = $1
        )
        """,
        movie_id,
    )


# ---------- xabar yuborish va foydalanuvchilar ----------
async def audience_counts():
    return await db.pool.fetchrow(
        """
        SELECT count(*) AS total,
            count(*) FILTER (WHERE premium_until > now()) AS prem,
            count(*) FILTER (WHERE premium_until IS NULL OR premium_until <= now()) AS free,
            count(*) FILTER (WHERE lang = 'uz') AS uz,
            count(*) FILTER (WHERE lang = 'en') AS en,
            count(*) FILTER (WHERE lang = 'ru') AS ru
        FROM users WHERE NOT blocked AND NOT banned
        """
    )


async def audience(kind: str) -> list[int]:
    cond = _AUD.get(kind, "TRUE")
    rows = await db.pool.fetch(f"SELECT user_id FROM users WHERE NOT blocked AND NOT banned AND {cond}")
    return [r["user_id"] for r in rows]


async def user_row(uid: int):
    return await db.pool.fetchrow(
        "SELECT user_id, lang, first_name, username, joined_at, last_seen, premium_until, "
        "downloads, banned, blocked FROM users WHERE user_id=$1",
        uid,
    )


async def find_user(q: str):
    q = q.strip()
    if q.isdigit():
        return await user_row(int(q))
    row = await db.pool.fetchrow("SELECT user_id FROM users WHERE lower(username) = lower($1)", q.lstrip("@"))
    return await user_row(row["user_id"]) if row else None


# ---------- kengaytirilgan statistika ----------
async def stats_ext():
    p = db.pool
    top_sql = (
        "SELECT m.title, count(*) AS c FROM downloads_log l JOIN movies m ON m.id = l.movie_id "
        "WHERE l.created_at > now() - $1::interval GROUP BY m.title ORDER BY c DESC LIMIT 5"
    )
    search_sql = (
        "SELECT lower(q) AS q, count(*) AS c FROM searches "
        "WHERE created_at > now() - interval '7 days' {extra} GROUP BY lower(q) ORDER BY c DESC LIMIT 5"
    )
    (users, daily, langs, top_day, top_week, top_all, top_search, missing, rev) = await asyncio.gather(
        p.fetchrow(
            """
            SELECT count(*) AS total,
                count(*) FILTER (WHERE last_seen > now() - interval '1 day') AS dau,
                count(*) FILTER (WHERE last_seen > now() - interval '7 days') AS wau,
                count(*) FILTER (WHERE last_seen > now() - interval '30 days') AS mau,
                count(*) FILTER (WHERE joined_at > now() - interval '1 day') AS new_day,
                count(*) FILTER (WHERE joined_at > now() - interval '7 days') AS new_week,
                count(*) FILTER (WHERE premium_until > now()) AS premium,
                count(*) FILTER (WHERE blocked) AS blocked
            FROM users
            """
        ),
        p.fetch(
            "SELECT d::date AS day, count(u.user_id) AS c "
            "FROM generate_series(current_date - 6, current_date, interval '1 day') AS d "
            "LEFT JOIN users u ON u.joined_at::date = d::date GROUP BY d ORDER BY d"
        ),
        p.fetch("SELECT COALESCE(lang, '—') AS lang, count(*) AS c FROM users GROUP BY 1 ORDER BY 2 DESC"),
        p.fetch(top_sql, timedelta(days=1)),
        p.fetch(top_sql, timedelta(days=7)),
        p.fetch("SELECT title, views AS c FROM movies WHERE views > 0 ORDER BY views DESC LIMIT 5"),
        p.fetch(search_sql.format(extra="")),
        p.fetch(search_sql.format(extra="AND NOT found")),
        p.fetchrow(
            "SELECT COALESCE(SUM(amount) FILTER (WHERE currency = 'XTR'), 0) AS stars, "
            "COALESCE(SUM(amount) FILTER (WHERE currency = 'UZS'), 0) AS uzs "
            "FROM payments WHERE created_at > now() - interval '30 days'"
        ),
    )
    return {
        "users": users, "daily": daily, "langs": langs, "top_day": top_day, "top_week": top_week,
        "top_all": top_all, "searches": top_search, "missing": missing, "rev": rev,
    }
