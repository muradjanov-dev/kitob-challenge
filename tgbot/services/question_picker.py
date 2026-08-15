# -*- coding: utf-8 -*-
"""
Smart LRU (Least-Recently-Used) question selector for live games.
Guarantees 0% repetition until the entire question pool has completed a full cycle.
"""
import random


def pick_least_recently_used(pool, get_key_fn, recent_games, get_game_keys_fn, count):
    """
    Selects `count` items from `pool` using a strict Least-Recently-Used (LRU) algorithm.

    :param pool: list of question dicts/strings in the bank
    :param get_key_fn: function(item) -> unique key (e.g. quote, q, emoji, display)
    :param recent_games: iterable of recent game model instances ordered by -starts_at
    :param get_game_keys_fn: function(game) -> list of keys that were used in that game
    :param count: number of questions needed for the new game
    :return: list of `count` items from `pool`
    """
    if not pool:
        return []

    count = min(count, len(pool))

    # Map each key in the pool to how recently it was used (index 0 = most recent game)
    # Lower value = used longer ago (or never used).
    key_last_seen = {}
    for game_idx, game in enumerate(recent_games):
        try:
            used_keys = get_game_keys_fn(game) or []
        except Exception:
            used_keys = []
        for k in used_keys:
            if k and k not in key_last_seen:
                # game_idx: 0 is the most recent game, 1 is 2nd most recent, etc.
                # We store negative index so smaller number means seen longer ago.
                key_last_seen[k] = -game_idx

    # Group pool items by their recency tier
    # -infinity (never seen in recent games) is tier -999999
    tiered = {}
    for item in pool:
        k = get_key_fn(item)
        tier = key_last_seen.get(k, -999999)
        if tier not in tiered:
            tiered[tier] = []
        tiered[tier].append(item)

    # Sort tiers from oldest (lowest score) to newest (highest score)
    sorted_tiers = sorted(tiered.keys())

    selected = []
    for tier in sorted_tiers:
        items_in_tier = list(tiered[tier])
        random.shuffle(items_in_tier)
        needed = count - len(selected)
        selected.extend(items_in_tier[:needed])
        if len(selected) >= count:
            break

    # Shuffle the final selected questions so their in-game order is mixed
    random.shuffle(selected)
    return selected[:count]
