"""At most DAILY_LIMIT automatic DMs a reader gets in a day (owner,
2026-11-01: 7-9 a day was too many; three at most).

Every scheduled sender asks take() before each DM and skips the reader when
it says no. The last slot is kept for the messages that matter most -- the
20:00 streak warning or the 23:57 personal report (`high=True`) -- so the
morning teaser and a reminder can never crowd them out.

Not counted: answers to what the reader did (report confirmation, wallet
charge, top-up approval, gifts, game results) and broadcasts the owner sends
by hand (internal/ops/broadcast).
"""
from django.core.cache import cache
from django.utils import timezone

DAILY_LIMIT = 3
RESERVED_FOR_HIGH = 1


def _key(telegram_id) -> str:
    return f"autodm:{timezone.localdate().isoformat()}:{telegram_id}"


def used(telegram_id) -> int:
    return int(cache.get(_key(telegram_id)) or 0)


def take(telegram_id, high: bool = False) -> bool:
    """Claim one of today's automatic DMs for this reader; False = skip them."""
    key = _key(telegram_id)
    cache.add(key, 0, 60 * 60 * 48)
    try:
        n = cache.incr(key)
    except ValueError:  # expired between add and incr
        cache.set(key, 1, 60 * 60 * 48)
        n = 1
    limit = DAILY_LIMIT if high else DAILY_LIMIT - RESERVED_FOR_HIGH
    if n > limit:
        try:
            cache.decr(key)
        except ValueError:
            pass
        return False
    return True
