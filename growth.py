import logging
import re
from datetime import datetime, timedelta, timezone

import config
import database as db
import ux

UZ = timezone(timedelta(hours=5))  # Toshkent
_ref_pending: dict[int, int] = {}   # taklif qilingan -> taklif qilgan (mukofot hali berilmagan)
_day: dict[int, list] = {}          # user_id -> [sana, bugungi ko'rishlar soni]


def _int(key: str, default: int) -> int:
    try:
        return int(db.get_setting(key, str(default)))
    except ValueError:
        return default


def free_limit() -> int:
    return max(0, _int("free_limit", 0))   # 0 = o'chiq


def ref_days() -> int:
    return max(0, _int("ref_days", 3))


def ref_cap() -> int:
    return max(1, _int("ref_cap", 20))


async def init():
    await db.pool.execute(
        """
        ALTER TABLE users ADD COLUMN IF NOT EXISTS source TEXT;
        ALTER TABLE users ADD COLUMN IF NOT EXISTS digest BOOLEAN NOT NULL DEFAULT TRUE;
        CREATE TABLE IF NOT EXISTS referrals (
            invited BIGINT PRIMARY KEY,
            referrer BIGINT NOT NULL,
            rewarded BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS referrals_ref_idx ON referrals(referrer);
        CREATE TABLE IF NOT EXISTS collections (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            emoji TEXT NOT NULL DEFAULT '📚',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS collection_items (
            collection_id INT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
            movie_id INT NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
            pos INT NOT NULL DEFAULT 0,
            PRIMARY KEY (collection_id, movie_id)
        );
        CREATE INDEX IF NOT EXISTS downloads_user_idx ON downloads_log(user_id, created_at);
        """
    )
    rows = await db.pool.fetch("SELECT invited, referrer FROM referrals WHERE NOT rewarded")
    _ref_pending.update({r["invited"]: r["referrer"] for r in rows})


# ---------------- /start havolasi: referal va manba ----------------
async def on_start(uid: int, arg, is_new: bool):
    """Havola parametrini ishlaydi. Kino kodi bo'lsa qaytaradi; referal/manba bo'lsa None."""
    if not arg:
        return None
    if arg.startswith("r_"):
        if is_new and arg[2:].isdigit():
            ref = int(arg[2:])
            if ref != uid and (await db.get_user(ref))["exists"]:
                await db.pool.execute(
                    "INSERT INTO referrals (invited, referrer) VALUES ($1, $2) ON CONFLICT DO NOTHING", uid, ref
                )
                _ref_pending[uid] = ref
        return None
    if arg.startswith("s_"):
        slug = re.sub(r"[^a-z0-9_]", "", arg[2:].lower())[:24]
        if is_new and slug:
            await db.pool.execute(
                "INSERT INTO users (user_id, source) VALUES ($1, $2) "
                "ON CONFLICT (user_id) DO UPDATE SET source = COALESCE(users.source, $2)",
                uid, slug,
            )
        return None
    return arg


async def on_view(bot, uid: int):
    """Taklif qilingan foydalanuvchi birinchi videoni ko'rganda taklif qilganga mukofot beriladi."""
    ref = _ref_pending.pop(uid, None)
    if ref is None:
        return
    row = await db.pool.fetchrow(
        "UPDATE referrals SET rewarded = TRUE WHERE invited = $1 AND NOT rewarded RETURNING referrer", uid
    )
    if not row:
        return
    days = ref_days()
    done = await db.pool.fetchval("SELECT count(*) FROM referrals WHERE referrer=$1 AND rewarded", ref)
    if days <= 0 or done > ref_cap():
        return
    await db.grant_premium(ref, days, method="referral")
    lang = await db.get_lang(ref) or "uz"
    try:
        await bot.send_message(ref, ux.u(lang, "ref_reward").format(days=days), parse_mode="HTML")
    except Exception as e:
        logging.info("Referal xabarini yuborib bo'lmadi: %s", e)


async def ref_stats(uid: int) -> dict:
    row = await db.pool.fetchrow(
        "SELECT count(*) AS total, count(*) FILTER (WHERE rewarded) AS ok FROM referrals WHERE referrer=$1", uid
    )
    return {"total": row["total"], "ok": row["ok"], "earned": min(row["ok"], ref_cap()) * ref_days()}


async def sources():
    return await db.pool.fetch(
        "SELECT source, count(*) AS n, count(*) FILTER (WHERE downloads > 0) AS active FROM users "
        "WHERE source IS NOT NULL GROUP BY source ORDER BY n DESC LIMIT 20"
    )


# ---------------- kunlik bepul limit ----------------
def _today() -> str:
    return datetime.now(UZ).strftime("%Y-%m-%d")


async def _used_today(uid: int) -> int:
    rec = _day.get(uid)
    if rec is None or rec[0] != _today():
        if len(_day) > 20000:
            _day.clear()
        start = datetime.now(UZ).replace(hour=0, minute=0, second=0, microsecond=0)
        n = await db.pool.fetchval(
            "SELECT count(*) FROM downloads_log WHERE user_id=$1 AND created_at >= $2", uid, start
        )
        rec = _day[uid] = [_today(), n or 0]
    return rec[1]


async def quota(uid: int):
    """(ruxsat bormi, bugun ishlatilgan, limit). Premium va adminlarga limit yo'q."""
    lim = free_limit()
    if lim <= 0 or uid in config.ADMIN_IDS or await db.is_premium(uid):
        return True, 0, lim
    used = await _used_today(uid)
    return used < lim, used, lim


def bump_quota(uid: int):
    rec = _day.get(uid)
    if rec and rec[0] == _today():
        rec[1] += 1


# ---------------- tarix va tavsiyalar ----------------
async def history(uid: int):
    return await db._cached(
        "hist", 30, (uid,),
        lambda: db.pool.fetch(
            f"SELECT {db._LABEL_COLS} FROM movies m JOIN ("
            "SELECT movie_id, max(created_at) AS seen FROM downloads_log "
            "WHERE user_id=$1 AND movie_id IS NOT NULL GROUP BY movie_id) h ON h.movie_id = m.id "
            "WHERE NOT m.hidden ORDER BY h.seen DESC LIMIT 60",
            uid,
        ),
    )


async def history_count(uid: int) -> int:
    return await db._cached(
        "histn", 60, (uid,),
        lambda: db.pool.fetchval("SELECT count(DISTINCT movie_id) FROM downloads_log WHERE user_id=$1", uid),
    ) or 0


_TASTE = """
SELECT g, count(*) AS c FROM (
    SELECT movie_id FROM favorites WHERE user_id=$1
    UNION ALL SELECT movie_id FROM ratings WHERE user_id=$1 AND score >= 7
    UNION ALL SELECT movie_id FROM downloads_log WHERE user_id=$1 AND movie_id IS NOT NULL
) s JOIN movies m ON m.id = s.movie_id, unnest(m.genre_tags) g
GROUP BY g ORDER BY c DESC, g LIMIT 3
"""


async def recommend(uid: int):
    """(sevgan janrlar, kinolar). Ma'lumot yo'q bo'lsa — eng yuqori reytinglilar."""

    async def load():
        tags = [r["g"] for r in await db.pool.fetch(_TASTE, uid)]
        if tags:
            rows = await db.pool.fetch(
                f"SELECT {db._LABEL_COLS} FROM movies m WHERE {db._VISIBLE} AND m.genre_tags && $2::text[] "
                "AND m.id NOT IN ("
                "SELECT movie_id FROM favorites WHERE user_id=$1 "
                "UNION SELECT movie_id FROM ratings WHERE user_id=$1 "
                "UNION SELECT movie_id FROM downloads_log WHERE user_id=$1 AND movie_id IS NOT NULL) "
                "ORDER BY (SELECT count(*) FROM unnest(m.genre_tags) x WHERE x = ANY($2::text[])) DESC, "
                f"{db._RATING_ORDER} LIMIT 10",
                uid, tags,
            )
            if rows:
                return tags, rows
        rows, _total = await db.browse("p", "", 0, 10, "r")
        return [], rows

    return await db._cached("foryou", 300, (uid,), load)


# ---------------- to'plamlar ----------------
async def coll_public():
    return await db._cached(
        "colls", 120, (),
        lambda: db.pool.fetch(
            "SELECT c.id, c.title, c.emoji, count(m.id) AS n FROM collections c "
            "JOIN collection_items i ON i.collection_id = c.id "
            f"JOIN movies m ON m.id = i.movie_id AND {db._VISIBLE} "
            "GROUP BY c.id ORDER BY c.id DESC"
        ),
    )


async def coll_all():
    return await db.pool.fetch(
        "SELECT c.id, c.title, c.emoji, (SELECT count(*) FROM collection_items i WHERE i.collection_id = c.id) AS n "
        "FROM collections c ORDER BY c.id DESC"
    )


async def coll_get(cid: int):
    return await db.pool.fetchrow("SELECT id, title, emoji FROM collections WHERE id=$1", cid)


async def coll_items(cid: int, visible: bool = True):
    cond = db._VISIBLE if visible else "TRUE"
    return await db.pool.fetch(
        f"SELECT {db._LABEL_COLS} FROM collection_items i JOIN movies m ON m.id = i.movie_id "
        f"WHERE i.collection_id=$1 AND {cond} ORDER BY i.pos, m.year NULLS LAST, m.id LIMIT 40",
        cid,
    )


async def coll_create(title: str) -> int:
    db.invalidate()
    return await db.pool.fetchval("INSERT INTO collections (title) VALUES ($1) RETURNING id", title[:40])


async def coll_delete(cid: int):
    await db.pool.execute("DELETE FROM collections WHERE id=$1", cid)
    db.invalidate()


async def coll_of(movie_id: int) -> set:
    rows = await db.pool.fetch("SELECT collection_id FROM collection_items WHERE movie_id=$1", movie_id)
    return {r["collection_id"] for r in rows}


async def coll_toggle(cid: int, movie_id: int) -> bool:
    """Qo'shilsa True, olib tashlansa False."""
    db.invalidate()
    gone = await db.pool.fetchval(
        "DELETE FROM collection_items WHERE collection_id=$1 AND movie_id=$2 RETURNING 1", cid, movie_id
    )
    if gone:
        return False
    await db.pool.execute(
        "INSERT INTO collection_items (collection_id, movie_id, pos) "
        "SELECT $1::int, $2::int, COALESCE(MAX(pos), 0) + 1 FROM collection_items WHERE collection_id = $1::int",
        cid, movie_id,
    )
    return True
