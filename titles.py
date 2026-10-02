import logging

import database as db

FUZZY = False

# Nomni qidiruv kalitiga aylantiradi: kichik harf, kirill → lotin, apostrof/bo'sh joy/belgilar olib tashlanadi.
# Masalan: «O'rgimchak odam», «Oʻrgimchak odam», «Ўргимчак одам» → «orgimchakodam»
_FUNC = r"""
CREATE OR REPLACE FUNCTION norm_title(t text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT regexp_replace(
        translate(
            replace(replace(replace(replace(replace(replace(replace(lower(t),
                'ч','ch'),'ш','sh'),'щ','sh'),'ю','yu'),'я','ya'),'ё','yo'),'ж','j'),
            'абвгдезийклмнопрстуфхцыэўқғҳàáâäçèéêëìíîïñòóôöùúûüý',
            'abvgdeziyklmnoprstufxsieoqghaaaaceeeeiiiinoooouuuuy'
        ),
        '[^a-z0-9]', '', 'g')
$$;
"""

_TRIGGER = """
ALTER TABLE movie_titles ADD COLUMN IF NOT EXISTS norm TEXT;
CREATE OR REPLACE FUNCTION movie_titles_norm() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.norm := norm_title(NEW.title);
    RETURN NEW;
END
$$;
DROP TRIGGER IF EXISTS movie_titles_norm_trg ON movie_titles;
CREATE TRIGGER movie_titles_norm_trg BEFORE INSERT OR UPDATE OF title ON movie_titles
    FOR EACH ROW EXECUTE FUNCTION movie_titles_norm();
UPDATE movie_titles SET norm = norm_title(title) WHERE norm IS NULL;
"""


async def init():
    """Qidiruv uchun SQL funksiya, trigger va (mumkin bo'lsa) imlo xatolariga chidamli indeks."""
    global FUZZY
    await db.pool.execute(_FUNC)
    await db.pool.execute(_TRIGGER)
    try:
        await db.pool.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        await db.pool.execute(
            "CREATE INDEX IF NOT EXISTS movie_titles_norm_trgm ON movie_titles USING gin (norm gin_trgm_ops)"
        )
        FUZZY = True
    except Exception as e:
        logging.warning("pg_trgm yoqilmadi, imlo xatolariga chidamli qidiruv o'chiq: %s", e)


def _sql(cols: str) -> str:
    sim = "similarity(t.norm, q.n)" if FUZZY else "0.5"
    fuzzy = " OR t.norm % q.n" if FUZZY else ""
    return f"""
        SELECT {cols}, max(s.score) AS score FROM (
            SELECT t.movie_id,
                CASE WHEN t.norm = q.n THEN 3.0
                     WHEN t.norm LIKE q.n || '%' THEN 2.0
                     WHEN t.norm LIKE '%' || q.n || '%' THEN 1.5
                     ELSE {sim} END AS score
            FROM movie_titles t, (SELECT norm_title($1) AS n) q
            WHERE length(q.n) >= 2 AND (t.norm LIKE '%' || q.n || '%'{fuzzy})
        ) s JOIN movies m ON m.id = s.movie_id
        WHERE {db._VISIBLE}
        GROUP BY m.id ORDER BY max(s.score) DESC, m.id DESC OFFSET $2 LIMIT $3
    """


async def search(query: str, offset: int = 0, limit: int = 8):
    """Botdagi kontent bo'yicha qidiruv (ro'yxat ko'rinishi uchun)."""
    return await db._cached(
        "tsearch", 60, (query.lower(), offset, limit, FUZZY),
        lambda: db.pool.fetch(_sql(db._LABEL_COLS), query, offset, limit),
    )


async def inline_search(query: str, limit: int = 20):
    """Inline rejim uchun: to'liq qatorlar."""
    return await db._cached(
        "tisearch", 60, (query.lower(), limit, FUZZY),
        lambda: db.pool.fetch(_sql("m.*"), query, 0, limit),
    )
