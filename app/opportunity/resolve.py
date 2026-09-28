"""
resolve.py — Kanal/guruh nishonini (username, t.me link, ID) topish.
Eski bot.py dan ko'chirilgan (o'zgarishsiz): resolve_target, _load_dialog_cache,
_client_cache, _entity_name.
"""
import logging

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.types import PeerChannel, PeerChat, PeerUser

log = logging.getLogger("opportunity.resolve")


def _client_cache(client) -> dict:
    cache = getattr(client, "_dialog_cache", None)
    if cache is None:
        cache = {}
        client._dialog_cache = cache
    return cache


async def _load_dialog_cache(client: TelegramClient) -> int:
    """Barcha dialoglarni yuklab keshga yozadi (ID orqali topish uchun)."""
    new_cache: dict = {}
    count = 0
    try:
        async for dialog in client.iter_dialogs():
            ent = dialog.entity
            eid = getattr(ent, "id", None)
            did = dialog.id
            if did is not None:
                new_cache[did] = ent
            if eid is not None and eid != did:
                new_cache[eid] = ent
            count += 1
        client._dialog_cache = new_cache
        log.info(f"Dialog kesh yuklandi: {count} ta dialog, {len(new_cache)} kalit")
    except FloodWaitError as e:
        log.warning(f"FloodWait dialog kesh yuklashda: {e.seconds}s")
    except Exception as e:
        log.warning(f"Dialog kesh yuklanmadi: {e}")
    return count


def _entity_name(entity) -> str:
    return getattr(entity, "title", None) or str(getattr(entity, "id", "?"))


async def resolve_target(client: TelegramClient, target: str):
    """
    Kanal/guruhni username, t.me link yoki ID bo'yicha topadi.
    Strategy chain: bir necha usul ketma-ket sinaladi.
    Hammasi muvaffaqiyatsiz bo'lsa — None.
    """
    target = target.strip()
    cache = _client_cache(client)

    if not target.lstrip("-").isdigit():
        try:
            ent = await client.get_entity(target)
            return ent
        except FloodWaitError:
            raise
        except Exception:
            pass
        try:
            inp = await client.get_input_entity(target)
            ent = await client.get_entity(inp)
            return ent
        except FloodWaitError:
            raise
        except Exception:
            pass
        return None

    raw = target.lstrip("-")
    t_int = int(target)
    t_abs = int(raw)

    if raw.startswith("100") and len(raw) > 10:
        raw_ch = int(raw[3:])
    else:
        raw_ch = t_abs

    def _from_cache():
        for key in (t_int, -t_abs, t_abs, raw_ch, -raw_ch):
            if key in cache:
                return cache[key]
        return None

    def _cache_entity(ent):
        cache[t_int] = ent
        eid = getattr(ent, "id", None)
        if eid:
            cache[eid] = ent

    hit = _from_cache()
    if hit:
        return hit

    for cand in (t_int, -t_abs, t_abs, raw_ch):
        try:
            ent = await client.get_entity(cand)
            _cache_entity(ent)
            return ent
        except FloodWaitError:
            raise
        except Exception:
            pass

    for cand in (t_int, raw_ch):
        try:
            inp = await client.get_input_entity(cand)
            ent = await client.get_entity(inp)
            _cache_entity(ent)
            return ent
        except FloodWaitError:
            raise
        except Exception:
            pass

    for pid in (raw_ch, t_abs):
        try:
            ent = await client.get_entity(PeerChannel(pid))
            _cache_entity(ent)
            return ent
        except FloodWaitError:
            raise
        except Exception:
            pass

    for pid in (raw_ch, t_abs):
        try:
            ent = await client.get_entity(PeerChat(pid))
            _cache_entity(ent)
            return ent
        except FloodWaitError:
            raise
        except Exception:
            pass

    try:
        ent = await client.get_entity(PeerUser(t_abs))
        _cache_entity(ent)
        return ent
    except FloodWaitError:
        raise
    except Exception:
        pass

    await _load_dialog_cache(client)
    cache = _client_cache(client)
    hit = _from_cache()
    if hit:
        return hit

    return None
