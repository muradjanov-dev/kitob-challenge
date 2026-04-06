import asyncio
from typing import Union, List
from aiogram import Bot
from asgiref.sync import sync_to_async
from django.core.cache import cache
from tgbot.models import RequiredGroup


async def check(user_id, channel: Union[int, str]):
    bot = Bot.get_current()
    try:
        member = await bot.get_chat_member(user_id=user_id, chat_id=channel)
        return member.is_chat_member()
    except Exception:
        return False


@sync_to_async
def get_required_groups():
    # Cache the list of required groups for 5 minutes to avoid DB hits on every request
    groups = cache.get("required_groups_list")
    if groups is None:
        groups = list(RequiredGroup.objects.all())
        cache.set("required_groups_list", groups, 300)
    return groups


async def get_result(user_id):
    # 1. Check Cache for "Subscribed" status
    # If user is fully subscribed, we cache this status for 1 hour.
    cache_key = f"user_subs_status_{user_id}"
    is_subscribed = cache.get(cache_key)

    if is_subscribed:
        return True, []

    # 2. Check Cache for "Not Subscribed" status (Negative Caching)
    # If we recently checked and they weren't subscribed, return that immediately
    # to avoid spamming Telegram API. (e.g. 30 seconds)
    cache_key_negative = f"user_subs_missing_{user_id}"
    missing_chats_cache = cache.get(cache_key_negative)
    if missing_chats_cache:
        return False, missing_chats_cache

    # 3. If not in cache, check all channels
    channels = await get_required_groups()
    if not channels:
        return True, []

    # Parallelize checks
    tasks = [check(user_id=user_id, channel=channel.chat_id)
             for channel in channels]
    results = await asyncio.gather(*tasks)

    final_status = True
    chat_ids = []

    for i, status in enumerate(results):
        if not status:
            final_status = False
            chat_ids.append(channels[i].id)

    # 4. Update Cache
    if final_status:
        # User is subscribed to everything. Cache for 1 hour.
        cache.set(cache_key, True, 3600)
        # Clear negative cache if exists
        cache.delete(cache_key_negative)
    else:
        # User is missing some channels. Cache this result for 30 seconds
        # so we don't spam API if they spam messages.
        cache.set(cache_key_negative, chat_ids, 30)

    return final_status, chat_ids
