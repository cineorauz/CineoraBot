import asyncio

import aiohttp

import config

URL = "https://websocket.tahrirchi.uz/translate-v2"


async def translate_texts(texts: list[str], source: str, target: str = "uzn_Latn"):
    """Matnlar ro'yxatini tarjima qiladi. (natija, xato) qaytaradi."""
    key = getattr(config, "TAHRIRCHI_API_KEY", "")
    if not key:
        return None, "TAHRIRCHI_API_KEY o'rnatilmagan"
    payload = {"texts": texts, "source_lang": source, "target_lang": target, "model": "sayqalchi"}
    headers = {"Authorization": key, "Content-Type": "application/json"}
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(URL, json=payload, headers=headers) as resp:
                data = await resp.json(content_type=None)
                if resp.status != 200:
                    msg = (data or {}).get("message", "") if isinstance(data, dict) else ""
                    return None, f"Tarjima xatosi ({resp.status}) {msg}".strip()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        return None, f"Tarjima xizmatiga ulanib bo'lmadi: {e}"
    out = data.get("translated_texts") if isinstance(data, dict) else None
    if not out or len(out) != len(texts):
        return None, "Tarjima javobi noto'g'ri"
    return out, None


async def fill_uz(d: dict, force: bool = False):
    """d ichidagi overview_uz va tagline_uz ni (bo'sh bo'lsa yoki force bo'lsa) tarjima qilib to'ldiradi.
    Muvaffaqiyatli bo'lsa None, aks holda xato matnini qaytaradi."""
    todo = []
    if force or not d.get("overview_uz"):
        if d.get("overview_en"):
            todo.append(("overview_uz", d["overview_en"], "eng_Latn"))
        elif d.get("overview_ru"):
            todo.append(("overview_uz", d["overview_ru"], "rus_Cyrl"))
    if force or not d.get("tagline_uz"):
        if d.get("tagline_en"):
            todo.append(("tagline_uz", d["tagline_en"], "eng_Latn"))
        elif d.get("tagline_ru"):
            todo.append(("tagline_uz", d["tagline_ru"], "rus_Cyrl"))
    if not todo:
        return None
    groups: dict[str, list] = {}
    for field, text, lang in todo:
        groups.setdefault(lang, []).append((field, text))
    for lang, items in groups.items():
        out, err = await translate_texts([text for _, text in items], lang)
        if err:
            return err
        for (field, _), value in zip(items, out):
            d[field] = (value or "").strip() or None
    return None
