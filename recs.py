import time

import tmdb

_cache: dict = {}


async def recommendations(media_type: str, tmdb_id: int) -> list[dict]:
    """TMDB tavsiyalari (o'xshash kino/seriallar), 1 soat keshlanadi."""
    key = (media_type, tmdb_id)
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    data = await tmdb._get(f"/{media_type}/{tmdb_id}/recommendations", language="en-US", page=1)
    out = []
    for x in data.get("results", [])[:12]:
        date = x.get("release_date") or x.get("first_air_date") or ""
        out.append(
            {
                "type": media_type,
                "id": x["id"],
                "title": x.get("title") or x.get("name") or "?",
                "year": date[:4],
            }
        )
    if len(_cache) > 300:
        _cache.clear()
    _cache[key] = (time.monotonic() + 3600, out)
    return out
